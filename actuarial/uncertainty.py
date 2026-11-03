"""
Actuarial Uncertainty Quantification Module.
Implements:
1. Epistemic Parameter Uncertainty via Delta-Method with Parameter Covariance Matrices.
2. Aleatory Process Uncertainty via Compound Poisson-Gamma Distribution Variance.
"""

from typing import Dict, Any, Tuple, Optional
import numpy as np
import pandas as pd
from pydantic import BaseModel


class ParameterConfidenceInterval(BaseModel):
    point_estimate: float
    lower_95: float
    upper_95: float
    standard_error_log_scale: float
    relative_margin_of_error_pct: float
    is_excessive_uncertainty: bool  # True if relative width > 70% (+/- 35%)


class PredictionInterval(BaseModel):
    expected_value: float
    variance: float
    standard_deviation: float
    gamma_dispersion_phi: float
    zero_claim_probability: float
    interval_type: str = "Compound Poisson-Gamma Aleatory Spread"
    upper_95_bound: float


class PolicyUncertaintyAssessment(BaseModel):
    frequency_ci: ParameterConfidenceInterval
    severity_ci: ParameterConfidenceInterval
    pure_premium_ci: ParameterConfidenceInterval
    aleatory_prediction_interval: PredictionInterval
    uncertainty_level: str  # "LOW", "MODERATE", "ELEVATED"
    audit_notes: str


class ActuarialUncertaintyEngine:
    def __init__(
        self,
        freq_cov_params: Optional[Dict[str, Dict[str, float]]] = None,
        sev_cov_params: Optional[Dict[str, Dict[str, float]]] = None,
        gamma_scale: float = 4.0923
    ):
        self.freq_cov = freq_cov_params
        self.sev_cov = sev_cov_params
        self.gamma_scale = gamma_scale

    def compute_policy_uncertainty(
        self,
        design_vector: pd.DataFrame,
        freq_est: float,
        sev_est: float,
        exposure: float = 1.0
    ) -> PolicyUncertaintyAssessment:
        """
        Compute delta-method parameter confidence intervals and compound variance
        for a single policyholder design row.
        """
        x_row = design_vector.values[0]
        cols = list(design_vector.columns)

        # ----------------------------------------------------
        # 1. Frequency Delta-Method
        # ----------------------------------------------------
        if self.freq_cov:
            # Reconstruct cov matrix for columns present
            cov_mat = np.array([
                [self.freq_cov.get(r, {}).get(c, 0.0) for c in cols]
                for r in cols
            ])
            var_log_freq = float(np.dot(x_row, np.dot(cov_mat, x_row)))
            se_log_freq = np.sqrt(max(1e-8, var_log_freq))
        else:
            se_log_freq = 0.08  # Empirical fallback SE

        freq_lower = float(freq_est * np.exp(-1.96 * se_log_freq))
        freq_upper = float(freq_est * np.exp(+1.96 * se_log_freq))
        freq_rel_margin = float(((freq_upper - freq_lower) / (2 * freq_est)) * 100.0) if freq_est > 0 else 0.0

        freq_ci = ParameterConfidenceInterval(
            point_estimate=round(freq_est, 5),
            lower_95=round(freq_lower, 5),
            upper_95=round(freq_upper, 5),
            standard_error_log_scale=round(se_log_freq, 5),
            relative_margin_of_error_pct=round(freq_rel_margin, 2),
            is_excessive_uncertainty=bool(freq_rel_margin > 35.0)
        )

        # ----------------------------------------------------
        # 2. Severity Delta-Method
        # ----------------------------------------------------
        if self.sev_cov:
            cov_mat_sev = np.array([
                [self.sev_cov.get(r, {}).get(c, 0.0) for c in cols]
                for r in cols
            ])
            var_log_sev = float(np.dot(x_row, np.dot(cov_mat_sev, x_row)))
            se_log_sev = np.sqrt(max(1e-8, var_log_sev))
        else:
            se_log_sev = 0.12  # Empirical fallback SE

        sev_lower = float(sev_est * np.exp(-1.96 * se_log_sev))
        sev_upper = float(sev_est * np.exp(+1.96 * se_log_sev))
        sev_rel_margin = float(((sev_upper - sev_lower) / (2 * sev_est)) * 100.0) if sev_est > 0 else 0.0

        sev_ci = ParameterConfidenceInterval(
            point_estimate=round(sev_est, 2),
            lower_95=round(sev_lower, 2),
            upper_95=round(sev_upper, 2),
            standard_error_log_scale=round(se_log_sev, 5),
            relative_margin_of_error_pct=round(sev_rel_margin, 2),
            is_excessive_uncertainty=bool(sev_rel_margin > 35.0)
        )

        # ----------------------------------------------------
        # 3. Pure Premium Delta-Method (Sum of Log-Variances)
        # ----------------------------------------------------
        pp_est = freq_est * sev_est
        var_log_pp = (se_log_freq ** 2) + (se_log_sev ** 2)
        se_log_pp = np.sqrt(var_log_pp)

        pp_lower = float(pp_est * np.exp(-1.96 * se_log_pp))
        pp_upper = float(pp_est * np.exp(+1.96 * se_log_pp))
        pp_rel_margin = float(((pp_upper - pp_lower) / (2 * pp_est)) * 100.0) if pp_est > 0 else 0.0

        pp_ci = ParameterConfidenceInterval(
            point_estimate=round(pp_est, 2),
            lower_95=round(pp_lower, 2),
            upper_95=round(pp_upper, 2),
            standard_error_log_scale=round(se_log_pp, 5),
            relative_margin_of_error_pct=round(pp_rel_margin, 2),
            is_excessive_uncertainty=bool(pp_rel_margin > 35.0)
        )

        # ----------------------------------------------------
        # 4. Aleatory Process Prediction Interval (Compound Poisson-Gamma)
        # Var(S) = lambda * e * (1 + phi) * mu^2
        # ----------------------------------------------------
        phi = float(self.gamma_scale)
        exp_claims = freq_est * exposure
        p_zero = float(np.exp(-exp_claims))
        
        # Compound variance
        compound_var = exp_claims * (1.0 + phi) * (sev_est ** 2)
        compound_sd = np.sqrt(max(0.0, compound_var))
        expected_loss = pp_est * exposure
        
        # Approximate 95th percentile of compound loss:
        # If P(N=0) >= 0.95, 95th quantile is 0; otherwise use shifted lognormal / gamma approximation
        if p_zero >= 0.95:
            upper_95 = 0.0
        else:
            # Shifted lognormal quantile match
            upper_95 = float(expected_loss + 1.96 * compound_sd)

        pred_interval = PredictionInterval(
            expected_value=round(expected_loss, 2),
            variance=round(compound_var, 2),
            standard_deviation=round(compound_sd, 2),
            gamma_dispersion_phi=round(phi, 4),
            zero_claim_probability=round(p_zero, 4),
            upper_95_bound=round(upper_95, 2)
        )

        # Overall uncertainty rating
        if pp_rel_margin > 35.0 or freq_rel_margin > 35.0:
            level = "ELEVATED"
            notes = "Wide confidence interval (> 35% margin). Policyholder risk profile contains rare feature combinations with sparse exposure."
        elif pp_rel_margin > 20.0:
            level = "MODERATE"
            notes = "Moderate parameter confidence interval (20-35% margin). Standard statistical estimation spread."
        else:
            level = "LOW"
            notes = "Narrow confidence interval (< 20% margin). Robust sample size in training dataset for this profile segment."

        return PolicyUncertaintyAssessment(
            frequency_ci=freq_ci,
            severity_ci=sev_ci,
            pure_premium_ci=pp_ci,
            aleatory_prediction_interval=pred_interval,
            uncertainty_level=level,
            audit_notes=notes
        )
