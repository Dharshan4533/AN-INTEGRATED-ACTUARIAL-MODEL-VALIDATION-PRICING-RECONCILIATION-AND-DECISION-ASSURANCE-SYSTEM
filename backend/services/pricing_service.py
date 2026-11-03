"""
Pricing Service.
Orchestrates statistical inference from trained Poisson and Gamma GLMs,
actuarial pricing formulas, risk tier classification, and explainability attributions.
"""

import os
import joblib
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from actuarial.preprocessing import ActuarialPreprocessor
from actuarial.pricing import ActuarialPricingEngine
from actuarial.risk_tiering import RiskTierClassifier
from explainability.shap_service import ShapExplainabilityService
from backend.services.run_registry import run_registry
from backend.core.config import settings
from backend.schemas.pricing_schema import (
    PolicyInput, QuoteRequest, QuoteResponse,
    ComparisonRequest, ComparisonResponse,
    WhatIfRequest, WhatIfResponse, PricingAssumptionsInput
)


class PricingService:
    def __init__(self):
        self.preprocessor = None
        self.freq_model = None
        self.nb_model = None
        self.sev_model = None
        self.shap_service = None
        self.risk_classifier = RiskTierClassifier(settings.RISK_TIER_PATH)
        self.pricing_engine = ActuarialPricingEngine()
        self._load_artifacts()

    def _load_artifacts(self):
        """Load trained models and preprocessor if available."""
        if os.path.exists(settings.PREPROCESSOR_PATH):
            self.preprocessor = ActuarialPreprocessor.load(settings.PREPROCESSOR_PATH)
        if os.path.exists(settings.FREQ_MODEL_PATH):
            self.freq_model = joblib.load(settings.FREQ_MODEL_PATH)
        nb_path = os.path.join(settings.MODELS_DIR, "frequency_nb2.joblib")
        if os.path.exists(nb_path):
            self.nb_model = joblib.load(nb_path)
        if os.path.exists(settings.SEV_MODEL_PATH):
            self.sev_model = joblib.load(settings.SEV_MODEL_PATH)
        if self.freq_model and self.sev_model and self.preprocessor:
            self.shap_service = ShapExplainabilityService()

    @property
    def is_ready(self) -> bool:
        return (
            self.preprocessor is not None
            and self.freq_model is not None
            and self.sev_model is not None
        )

    def predict_quote(
        self,
        policy: PolicyInput,
        custom_assumptions: Optional[PricingAssumptionsInput] = None
    ) -> QuoteResponse:
        """Calculate complete actuarial quote for a policy profile."""
        if not self.is_ready:
            raise RuntimeError("Model artifacts are not loaded. Run offline training first.")

        policy_dict = policy.model_dump()
        
        # 1. Transform features into GLM design matrix
        X_design = self.preprocessor.transform_single(policy_dict)

        # 2. Predict annualized claim frequency (offset = 0 for 1-year rate)
        freq_params = np.array([self.freq_model["params"].get(col, 0.0) for col in X_design.columns])
        lin_pred_freq = float(np.dot(X_design.values[0], freq_params))
        annualized_freq = float(np.exp(lin_pred_freq))

        # 3. Predict expected claim severity (Gamma GLM with log link)
        sev_params = np.array([self.sev_model["params"].get(col, 0.0) for col in X_design.columns])
        lin_pred_sev = float(np.dot(X_design.values[0], sev_params))
        expected_sev = float(np.exp(lin_pred_sev))

        # 4. Actuarial pricing calculations
        exposure = float(policy.Exposure)
        engine = self.pricing_engine
        if custom_assumptions:
            assump_dict = custom_assumptions.model_dump(exclude_none=True)
            engine = ActuarialPricingEngine(assump_dict)

        pricing_results = engine.calculate_pricing(
            annualized_frequency=annualized_freq,
            expected_severity=expected_sev,
            exposure=exposure,
            convert_to_inr=policy.convert_to_inr
        )

        # 5. Risk tier classification based on annual pure premium in EUR
        eur_pure_premium = annualized_freq * expected_sev
        risk_tier = self.risk_classifier.classify(eur_pure_premium)

        # 6. Feature attribution drivers
        explanation = self.shap_service.explain_local(policy_dict)
        key_drivers = explanation.get("all_attributions", [])[:5]

        disclaimer = (
            "Research Model Disclaimer: Predictions derived from French MTPL research dataset. "
            "For actuarial analytics demonstration and educational evaluation only."
        )

        # Record quote in immutable run registry
        base_prem = (
            pricing_results["pricing_breakdown"]["total_commercial_premium"]
            if not policy.convert_to_inr
            else pricing_results["pricing_breakdown"]["total_commercial_premium"] / engine.assumptions["inr_exchange_rate"]
        )
        run_id = run_registry.record_run(
            run_type="QUOTE",
            inputs={"policy": policy_dict},
            assumptions=dict(engine.assumptions),
            calculation_trace={
                "frequency": annualized_freq,
                "severity": expected_sev,
                "pure_premium": annualized_freq * expected_sev,
                "exposure": exposure,
                "expected_loss": (annualized_freq * expected_sev) * exposure,
                "total_premium": base_prem
            },
            outputs={
                "total_commercial_premium": pricing_results["pricing_breakdown"]["total_commercial_premium"],
                "currency": pricing_results["currency"]
            }
        )

        return QuoteResponse(
            policy=policy,
            annualized_frequency=pricing_results["annualized_frequency"],
            expected_claim_count_term=pricing_results["expected_claim_count_term"],
            expected_severity=pricing_results["expected_severity"],
            annual_pure_premium=pricing_results["pricing_breakdown"]["annual_pure_premium"],
            term_expected_loss=pricing_results["pricing_breakdown"]["term_expected_loss"],
            commercial_premium_before_tax=pricing_results["pricing_breakdown"]["commercial_premium_before_tax"],
            statutory_tax=pricing_results["pricing_breakdown"]["statutory_tax"],
            total_commercial_premium=pricing_results["pricing_breakdown"]["total_commercial_premium"],
            pricing_breakdown=pricing_results["pricing_breakdown"],
            risk_tier=risk_tier,
            key_risk_drivers=key_drivers,
            currency=pricing_results["currency"],
            currency_symbol=pricing_results["currency_symbol"],
            is_converted_currency=pricing_results["is_converted_currency"],
            conversion_rate_used=pricing_results["conversion_rate_used"],
            data_disclaimer=disclaimer,
            run_id=run_id
        )

    def compare_policies(self, request: ComparisonRequest) -> ComparisonResponse:
        """Compare 2 to 5 policy profiles using identical models and pricing assumptions."""
        quotes = [self.predict_quote(p, request.custom_assumptions) for p in request.policies]

        comparison_table = []
        premiums = []
        for idx, q in enumerate(quotes):
            premiums.append(q.total_commercial_premium)
            comparison_table.append({
                "profile_id": f"Profile {idx + 1}",
                "driver_age": q.policy.DrivAge,
                "bonus_malus": q.policy.BonusMalus,
                "veh_power": q.policy.VehPower,
                "veh_age": q.policy.VehAge,
                "area": q.policy.Area,
                "density": q.policy.Density,
                "exposure": q.policy.Exposure,
                "annualized_frequency": q.annualized_frequency,
                "expected_severity": q.expected_severity,
                "annual_pure_premium": q.annual_pure_premium,
                "total_commercial_premium": q.total_commercial_premium,
                "risk_tier": q.risk_tier["tier_name"],
                "risk_score": q.risk_tier["risk_score"]
            })

        min_idx = int(np.argmin(premiums))
        max_idx = int(np.argmax(premiums))

        return ComparisonResponse(
            quotes=quotes,
            comparison_table=comparison_table,
            lowest_premium_index=min_idx,
            highest_premium_index=max_idx
        )

    def what_if_analysis(self, request: WhatIfRequest) -> WhatIfResponse:
        """Compare baseline and revised policy profiles and compute absolute and percentage deltas."""
        base_q = self.predict_quote(request.baseline_policy, request.custom_assumptions)
        rev_q = self.predict_quote(request.revised_policy, request.custom_assumptions)

        # Helper for % delta
        def calc_pct(old_val, new_val):
            if old_val == 0:
                return 0.0
            return round(((new_val - old_val) / old_val) * 100.0, 2)

        differences = {
            "frequency_abs_diff": round(rev_q.annualized_frequency - base_q.annualized_frequency, 5),
            "frequency_pct_diff": calc_pct(base_q.annualized_frequency, rev_q.annualized_frequency),
            "severity_abs_diff": round(rev_q.expected_severity - base_q.expected_severity, 2),
            "severity_pct_diff": calc_pct(base_q.expected_severity, rev_q.expected_severity),
            "pure_premium_abs_diff": round(rev_q.annual_pure_premium - base_q.annual_pure_premium, 2),
            "pure_premium_pct_diff": calc_pct(base_q.annual_pure_premium, rev_q.annual_pure_premium),
            "commercial_premium_abs_diff": round(rev_q.total_commercial_premium - base_q.total_commercial_premium, 2),
            "commercial_premium_pct_diff": calc_pct(base_q.total_commercial_premium, rev_q.total_commercial_premium),
            "risk_score_diff": round(rev_q.risk_tier["risk_score"] - base_q.risk_tier["risk_score"], 1),
            "tier_changed": base_q.risk_tier["tier_name"] != rev_q.risk_tier["tier_name"],
            "from_tier": base_q.risk_tier["tier_name"],
            "to_tier": rev_q.risk_tier["tier_name"]
        }

        return WhatIfResponse(
            baseline_quote=base_q,
            revised_quote=rev_q,
            differences=differences
        )


pricing_service = PricingService()
