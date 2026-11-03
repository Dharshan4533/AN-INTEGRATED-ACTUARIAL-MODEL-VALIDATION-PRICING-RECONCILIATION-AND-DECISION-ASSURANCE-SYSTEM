"""
Simulation Service for Aggregate Portfolio Loss and Stress Testing.
Performs Monte Carlo simulations using Poisson compound frequency and Gamma severity,
calculating empirical Value at Risk (VaR) and Tail Value at Risk (TVaR / Expected Shortfall).
"""

import os
import time
import joblib
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from scipy import stats
from backend.core.config import settings
from backend.schemas.portfolio_schema import (
    PortfolioSimulateRequest, PortfolioSimulateResponse,
    RiskMeasureItem, HistogramBin,
    StressTestScenarioInput, StressTestResponse
)
from actuarial.preprocessing import ActuarialPreprocessor


class SimulationService:
    def __init__(self):
        self.preprocessor = None
        self.freq_model = None
        self.sev_model = None
        self.benchmark_df = None
        self._load_dependencies()

    def _load_dependencies(self):
        if os.path.exists(settings.PREPROCESSOR_PATH):
            self.preprocessor = ActuarialPreprocessor.load(settings.PREPROCESSOR_PATH)
        if os.path.exists(settings.FREQ_MODEL_PATH):
            self.freq_model = joblib.load(settings.FREQ_MODEL_PATH)
        if os.path.exists(settings.SEV_MODEL_PATH):
            self.sev_model = joblib.load(settings.SEV_MODEL_PATH)
        if os.path.exists(settings.BENCHMARK_PORTFOLIO_PATH):
            self.benchmark_df = pd.read_csv(settings.BENCHMARK_PORTFOLIO_PATH)

    def _get_portfolio_df(self, request: PortfolioSimulateRequest) -> pd.DataFrame:
        if request.custom_policies and len(request.custom_policies) > 0:
            return pd.DataFrame([p.model_dump() for p in request.custom_policies])
        if self.benchmark_df is not None:
            return self.benchmark_df.copy()
        # Fallback to sample from raw frequency data
        df = pd.read_csv(settings.RAW_FREQ_PATH, nrows=500)
        return df

    def simulate_portfolio(self, request: PortfolioSimulateRequest) -> PortfolioSimulateResponse:
        t0 = time.time()
        rng = np.random.RandomState(request.random_seed)

        df = self._get_portfolio_df(request)
        n_policies = len(df)
        
        # Ensure preprocessor and models are ready
        if not self.preprocessor or not self.freq_model or not self.sev_model:
            self._load_dependencies()
            if not self.preprocessor or not self.freq_model or not self.sev_model:
                raise RuntimeError("Models are not loaded for simulation.")

        # Transform portfolio into design matrix
        X_design = self.preprocessor.transform(df)
        exposure = df["Exposure"].fillna(1.0).clip(0.001, 1.0).values

        # Predict frequency rates
        freq_params = np.array([self.freq_model["params"].get(c, 0.0) for c in X_design.columns])
        lin_freq = np.dot(X_design.values, freq_params)
        freq_rates = np.exp(lin_freq)
        expected_claims_per_policy = freq_rates * exposure
        portfolio_lambda = float(np.sum(expected_claims_per_policy))

        # Predict severities
        sev_params = np.array([self.sev_model["params"].get(c, 0.0) for c in X_design.columns])
        lin_sev = np.dot(X_design.values, sev_params)
        expected_severities = np.exp(lin_sev)

        # Portfolio aggregate expected loss
        total_expected_loss = float(np.sum(expected_claims_per_policy * expected_severities))
        weighted_mean_severity = total_expected_loss / portfolio_lambda if portfolio_lambda > 0 else 1500.0

        # Dispersion scale from Gamma GLM
        dispersion = float(self.sev_model.get("scale", 4.0923))
        shape_k = 1.0 / max(0.05, dispersion)

        # Theoretical compound Poisson-Gamma moments
        # E[S] = sum(lambda_i * e_i * mu_i)
        # Var(S) = sum(lambda_i * e_i * (1 + phi) * mu_i^2)
        theo_mean = float(np.sum(expected_claims_per_policy * expected_severities))
        theo_var = float(np.sum(expected_claims_per_policy * (1.0 + dispersion) * (expected_severities ** 2)))

        # Monte Carlo Simulation with Heterogeneous Policy Severity Sampling
        M = request.n_simulations
        sim_claim_counts = rng.poisson(portfolio_lambda, size=M)
        
        simulated_losses = np.zeros(M, dtype=float)
        total_claims_drawn = int(np.sum(sim_claim_counts))
        if total_claims_drawn > 0:
            policy_claim_probs = expected_claims_per_policy / portfolio_lambda
            sampled_policy_indices = rng.choice(n_policies, size=total_claims_drawn, p=policy_claim_probs)
            sampled_mus = expected_severities[sampled_policy_indices]
            
            # Policy-specific Gamma draws: Gamma(shape=k, scale=mu_j * phi)
            unit_gammas = rng.gamma(shape=shape_k, scale=1.0, size=total_claims_drawn)
            claim_severities = unit_gammas * (sampled_mus * dispersion)
            
            # Cumulative sums to split into simulation runs
            split_indices = np.cumsum(sim_claim_counts)[:-1]
            split_claims = np.split(claim_severities, split_indices)
            for i, claims in enumerate(split_claims):
                if len(claims) > 0:
                    simulated_losses[i] = np.sum(claims)

        # Currency conversion factor
        rate = float(settings.INR_EXCHANGE_RATE) if request.convert_to_inr else 1.0
        cur_code = "INR" if request.convert_to_inr else "EUR"
        cur_sym = "₹" if request.convert_to_inr else "€"

        simulated_losses_conv = simulated_losses * rate
        total_exp_loss_conv = total_expected_loss * rate

        mean_loss = float(np.mean(simulated_losses_conv))
        std_loss = float(np.std(simulated_losses_conv, ddof=1)) if M > 1 else 0.0
        sim_mean_se = std_loss / np.sqrt(M) if M > 0 else 0.0
        theo_mean_conv = theo_mean * rate
        z_score = abs(mean_loss - theo_mean_conv) / sim_mean_se if sim_mean_se > 0 else 0.0
        moment_verified = bool(z_score <= 2.58)

        # Risk Measures (VaR, TVaR, and Monte Carlo Standard Errors)
        risk_measures = []
        # Silverman bandwidth for VaR density estimate
        bandwidth = 1.06 * std_loss * (M ** (-0.2)) if std_loss > 0 else 1.0

        for cl in request.confidence_levels:
            var_val = float(np.percentile(simulated_losses_conv, cl * 100.0))
            tail_mask = simulated_losses_conv >= var_val
            tail_losses = simulated_losses_conv[tail_mask]
            tail_count = len(tail_losses)
            tvar_val = float(np.mean(tail_losses)) if tail_count > 0 else var_val
            
            # MCSE for TVaR
            tvar_var = float(np.var(tail_losses, ddof=1)) if tail_count > 1 else 0.0
            tvar_mcse = float(np.sqrt(tvar_var / tail_count)) if tail_count > 0 else 0.0

            # MCSE for VaR: sqrt(q*(1-q)) / (f(VaR_q) * sqrt(M))
            kde_pts = np.sum(np.abs(simulated_losses_conv - var_val) <= bandwidth)
            f_var = (kde_pts / (2.0 * bandwidth * M)) if (kde_pts > 0 and bandwidth > 0) else 1e-5
            var_mcse = float(np.sqrt(cl * (1.0 - cl)) / (f_var * np.sqrt(M)))

            risk_measures.append(RiskMeasureItem(
                confidence_level=cl,
                confidence_percent=f"{round(cl * 100.0, 1)}%",
                var=round(var_val, 2),
                tvar=round(tvar_val, 2),
                var_mcse=round(var_mcse, 2),
                tvar_mcse=round(tvar_mcse, 2)
            ))

        # Histogram (20 bins)
        hist_counts, bin_edges = np.histogram(simulated_losses_conv, bins=20)
        bin_width = bin_edges[1] - bin_edges[0]
        histogram_bins = []
        for i in range(len(hist_counts)):
            density_val = float(hist_counts[i] / (M * bin_width)) if bin_width > 0 else 0.0
            histogram_bins.append(HistogramBin(
                bin_start=round(float(bin_edges[i]), 2),
                bin_end=round(float(bin_edges[i+1]), 2),
                frequency=int(hist_counts[i]),
                density=density_val
            ))

        skew_loss = float(stats.skew(simulated_losses_conv))
        runtime = round(time.time() - t0, 3)

        assumptions = (
            f"Heterogeneous Stochastic Assumption: Compound Poisson-Gamma process with policy-specific severity distributions. "
            f"Portfolio Claim Count N ~ Poisson(λ={portfolio_lambda:.1f}), "
            f"Individual claim severity drawn from policy-specific Gamma(mean=μ_j, shape={shape_k:.2f}). "
            f"Theoretical portfolio expected loss = {theo_mean_conv:.2f} {cur_sym} (simulated mean convergence z-score = {z_score:.2f}). "
            f"Evaluated over {M:,} Monte Carlo trials with random seed {request.random_seed}."
        )

        return PortfolioSimulateResponse(
            n_policies=n_policies,
            total_exposure_years=round(float(np.sum(exposure)), 2),
            expected_claim_count=round(portfolio_lambda, 2),
            expected_total_loss=round(total_exp_loss_conv, 2),
            mean_simulated_loss=round(mean_loss, 2),
            std_simulated_loss=round(std_loss, 2),
            loss_skewness=round(skew_loss, 3),
            risk_measures=risk_measures,
            loss_histogram=histogram_bins,
            simulation_count=M,
            random_seed=request.random_seed,
            runtime_seconds=runtime,
            currency=cur_code,
            currency_symbol=cur_sym,
            assumptions_summary=assumptions,
            theoretical_expected_loss=round(theo_mean_conv, 2),
            theoretical_variance=round(theo_var * (rate ** 2), 2),
            moment_convergence_verified=moment_verified,
            moment_z_score=round(z_score, 3)
        )

    def run_stress_test(self, scenario: StressTestScenarioInput) -> StressTestResponse:
        """Evaluate baseline vs stressed portfolio capital requirements."""
        # 1. Baseline simulation
        base_req = PortfolioSimulateRequest(
            n_simulations=scenario.n_simulations,
            random_seed=scenario.random_seed,
            convert_to_inr=scenario.convert_to_inr
        )
        base_res = self.simulate_portfolio(base_req)

        # 2. Stressed calculation
        df_stressed = self.benchmark_df.copy() if self.benchmark_df is not None else pd.read_csv(settings.RAW_FREQ_PATH, nrows=500)
        
        # Apply Bonus-Malus shift if any
        if scenario.bonus_malus_shift != 0.0:
            df_stressed["BonusMalus"] = (df_stressed["BonusMalus"] + scenario.bonus_malus_shift).clip(50, 230)

        # Stressed simulation with custom multipliers
        t0 = time.time()
        rng = np.random.RandomState(scenario.random_seed)
        X_design = self.preprocessor.transform(df_stressed)
        exposure = df_stressed["Exposure"].fillna(1.0).clip(0.001, 1.0).values

        freq_params = np.array([self.freq_model["params"].get(c, 0.0) for c in X_design.columns])
        lin_freq = np.dot(X_design.values, freq_params)
        freq_rates = np.exp(lin_freq) * scenario.frequency_multiplier
        stressed_lambda = float(np.sum(freq_rates * exposure))

        sev_params = np.array([self.sev_model["params"].get(c, 0.0) for c in X_design.columns])
        lin_sev = np.dot(X_design.values, sev_params)
        stressed_severities = np.exp(lin_sev) * scenario.severity_multiplier

        stressed_total_exp_loss = float(np.sum(freq_rates * exposure * stressed_severities))
        stressed_mean_sev = stressed_total_exp_loss / stressed_lambda if stressed_lambda > 0 else 1800.0

        dispersion = float(self.sev_model.get("scale", 1.05))
        shape_k = 1.0 / max(0.05, dispersion)
        scale_theta = stressed_mean_sev * dispersion

        M = scenario.n_simulations
        sim_counts = rng.poisson(stressed_lambda, size=M)
        total_claims = int(np.sum(sim_counts))
        sim_losses = np.zeros(M, dtype=float)
        if total_claims > 0:
            severities = rng.gamma(shape=shape_k, scale=scale_theta, size=total_claims)
            split_indices = np.cumsum(sim_counts)[:-1]
            split_claims = np.split(severities, split_indices)
            for i, claims in enumerate(split_claims):
                if len(claims) > 0:
                    sim_losses[i] = np.sum(claims)

        rate = float(settings.INR_EXCHANGE_RATE) if scenario.convert_to_inr else 1.0
        cur_code = "INR" if scenario.convert_to_inr else "EUR"
        cur_sym = "₹" if scenario.convert_to_inr else "€"

        sim_losses_conv = sim_losses * rate
        stressed_exp_loss_conv = stressed_total_exp_loss * rate

        stressed_var_99 = float(np.percentile(sim_losses_conv, 99.0))
        tail = sim_losses_conv[sim_losses_conv >= stressed_var_99]
        stressed_tvar_99 = float(np.mean(tail)) if len(tail) > 0 else stressed_var_99

        # Extract baseline 99% metrics
        base_var_99 = next(item.var for item in base_res.risk_measures if item.confidence_level == 0.99)
        base_tvar_99 = next(item.tvar for item in base_res.risk_measures if item.confidence_level == 0.99)

        base_metrics = {
            "expected_loss": base_res.expected_total_loss,
            "mean_simulated_loss": base_res.mean_simulated_loss,
            "var_99": base_var_99,
            "tvar_99": base_tvar_99
        }

        stressed_metrics = {
            "expected_loss": round(stressed_exp_loss_conv, 2),
            "mean_simulated_loss": round(float(np.mean(sim_losses_conv)), 2),
            "var_99": round(stressed_var_99, 2),
            "tvar_99": round(stressed_tvar_99, 2)
        }

        abs_impact = {
            "delta_expected_loss": round(stressed_metrics["expected_loss"] - base_metrics["expected_loss"], 2),
            "delta_var_99": round(stressed_metrics["var_99"] - base_metrics["var_99"], 2),
            "delta_tvar_99": round(stressed_metrics["tvar_99"] - base_metrics["tvar_99"], 2)
        }

        def calc_pct(old_val, new_val):
            return round(((new_val - old_val) / old_val) * 100.0, 2) if old_val > 0 else 0.0

        pct_impact = {
            "pct_expected_loss": calc_pct(base_metrics["expected_loss"], stressed_metrics["expected_loss"]),
            "pct_var_99": calc_pct(base_metrics["var_99"], stressed_metrics["var_99"]),
            "pct_tvar_99": calc_pct(base_metrics["tvar_99"], stressed_metrics["tvar_99"])
        }

        summary = (
            f"Under scenario '{scenario.name}' (Freq x{scenario.frequency_multiplier:.2f}, "
            f"Sev x{scenario.severity_multiplier:.2f}), portfolio Expected Loss increases by "
            f"{abs_impact['delta_expected_loss']:+,.2f} {cur_sym} ({pct_impact['pct_expected_loss']:+.1f}%). "
            f"99% Value at Risk increases by {abs_impact['delta_var_99']:+,.2f} {cur_sym} ({pct_impact['pct_var_99']:+.1f}%), "
            f"requiring an estimated capital buffer addition of {abs_impact['delta_var_99']:,.2f} {cur_sym}."
        )

        return StressTestResponse(
            scenario_name=scenario.name,
            n_policies=base_res.n_policies,
            baseline_metrics=base_metrics,
            stressed_metrics=stressed_metrics,
            absolute_impact=abs_impact,
            percentage_impact=pct_impact,
            capital_strain_summary=summary,
            currency=cur_code,
            currency_symbol=cur_sym
        )


simulation_service = SimulationService()
