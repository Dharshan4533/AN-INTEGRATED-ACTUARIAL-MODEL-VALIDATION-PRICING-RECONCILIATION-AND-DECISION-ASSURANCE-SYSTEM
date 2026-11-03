"""
Premium Reconciliation Engine.
Executes exact sequential arithmetic attribution decomposing premium differences into
documented risk, model, exposure, assumption, and tax components, with path-order sensitivity analysis.
"""

from typing import Dict, List, Optional, Any, Tuple
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from backend.schemas.pricing_schema import PolicyInput, PricingAssumptionsInput
from backend.services.pricing_service import pricing_service
from actuarial.pricing import ActuarialPricingEngine, DEFAULT_PRICING_ASSUMPTIONS
from backend.services.run_registry import run_registry


class AttributionStep(BaseModel):
    step_number: int
    step_name: str
    description: str
    starting_premium: float
    ending_premium: float
    dollar_impact: float
    percentage_impact: float
    cumulative_change: float


class ReconciliationResponse(BaseModel):
    policy_a_total_premium: float
    policy_b_total_premium: float
    total_difference: float
    is_exact_reconciliation: bool
    reconciliation_error: float
    tolerance_epsilon: float = 1e-4
    primary_sequence_order: List[str]
    sequential_steps: List[AttributionStep]
    order_sensitivity_analysis: Dict[str, Any]
    run_id: str
    currency: str = "EUR"
    currency_symbol: str = "€"


class ReconciliationService:
    def __init__(self):
        self.registry = run_registry

    def _evaluate_state(
        self,
        policy: PolicyInput,
        model_family: str,
        exposure: float,
        assumptions: Dict[str, Any]
    ) -> Tuple[float, Dict[str, float]]:
        """
        Evaluate full unrounded pricing for a specific state (features, model, exposure, assumptions).
        Returns total payable premium and trace components.
        """
        p_dict = policy.model_dump()
        p_dict["Exposure"] = exposure
        X_design = pricing_service.preprocessor.transform_single(p_dict)

        # 1. Frequency inference
        if model_family.lower() in ["nb2", "negative_binomial"] and hasattr(pricing_service, "nb_model") and pricing_service.nb_model:
            freq_model = pricing_service.nb_model
        else:
            freq_model = pricing_service.freq_model

        freq_params = np.array([freq_model["params"].get(col, 0.0) for col in X_design.columns])
        lin_freq = float(np.dot(X_design.values[0], freq_params))
        freq = float(np.exp(lin_freq))

        # 2. Severity inference
        sev_model = pricing_service.sev_model
        sev_params = np.array([sev_model["params"].get(col, 0.0) for col in X_design.columns])
        lin_sev = float(np.dot(X_design.values[0], sev_params))
        sev = float(np.exp(lin_sev))

        # 3. Unrounded pricing formulas
        pure_prem = freq * sev
        expected_loss = pure_prem * exposure

        fixed_exp = float(assumptions.get("fixed_expense", DEFAULT_PRICING_ASSUMPTIONS["fixed_expense"]))
        var_exp = float(assumptions.get("variable_expense_ratio", DEFAULT_PRICING_ASSUMPTIONS["variable_expense_ratio"]))
        risk_m = float(assumptions.get("risk_margin", DEFAULT_PRICING_ASSUMPTIONS["risk_margin"]))
        prof_m = float(assumptions.get("profit_margin", DEFAULT_PRICING_ASSUMPTIONS["profit_margin"]))
        tax_r = float(assumptions.get("tax_rate", DEFAULT_PRICING_ASSUMPTIONS["tax_rate"]))

        denom = 1.0 - var_exp - risk_m - prof_m
        if denom <= 0.05:
            denom = 0.05

        comm_prem = (expected_loss + fixed_exp) / denom
        tax_amt = comm_prem * tax_r
        total_prem = comm_prem + tax_amt

        trace = {
            "frequency": freq,
            "severity": sev,
            "pure_premium": pure_prem,
            "exposure": exposure,
            "expected_loss": expected_loss,
            "fixed_expense": fixed_exp,
            "commercial_premium": comm_prem,
            "tax_amount": tax_amt,
            "total_premium": total_prem
        }
        return total_prem, trace

    def reconcile_policies(
        self,
        policy_a: PolicyInput,
        policy_b: PolicyInput,
        assumptions_a: Optional[Dict[str, Any]] = None,
        assumptions_b: Optional[Dict[str, Any]] = None,
        model_family_a: str = "poisson",
        model_family_b: str = "poisson",
        user_notes: Optional[str] = None,
        convert_to_inr: bool = False
    ) -> ReconciliationResponse:
        """
        Execute 5-step sequential arithmetic premium attribution.
        Order of sequence:
        Step 0: Baseline State (Policy A, Model A, Exposure A, Assumptions A)
        Step 1: Pure Risk (Policy B features, Model A, Exposure A, Assumptions A)
        Step 2: Model Family (Policy B features, Model B, Exposure A, Assumptions A)
        Step 3: Exposure Scaling (Policy B features, Model B, Exposure B, Assumptions A)
        Step 4: Commercial Assumptions (Policy B features, Model B, Exposure B, Assumptions B [before tax])
        Step 5: Statutory Tax (Policy B features, Model B, Exposure B, Assumptions B [with tax])
        """
        assump_a = dict(DEFAULT_PRICING_ASSUMPTIONS)
        if assumptions_a:
            assump_a.update(assumptions_a)

        assump_b = dict(DEFAULT_PRICING_ASSUMPTIONS)
        if assumptions_b:
            assump_b.update(assumptions_b)

        exp_a = float(policy_a.Exposure)
        exp_b = float(policy_b.Exposure)

        # Sequence evaluations
        # State 0: Baseline
        p0, trace0 = self._evaluate_state(policy_a, model_family_a, exp_a, assump_a)

        # State 1: Pure Risk (Policy B features, rest held constant)
        p1, trace1 = self._evaluate_state(policy_b, model_family_a, exp_a, assump_a)

        # State 2: Model Specification (Model B, rest held constant)
        p2, trace2 = self._evaluate_state(policy_b, model_family_b, exp_a, assump_a)

        # State 3: Exposure Scaling (Exposure B, rest held constant)
        p3, trace3 = self._evaluate_state(policy_b, model_family_b, exp_b, assump_a)

        # State 4: Commercial Assumptions (Assumptions B with Tax Rate held at A)
        assump_b_pretax = dict(assump_b)
        assump_b_pretax["tax_rate"] = assump_a["tax_rate"]
        p4, trace4 = self._evaluate_state(policy_b, model_family_b, exp_b, assump_b_pretax)

        # State 5: Final Target State (Assumptions B including Tax Rate B)
        p5, trace5 = self._evaluate_state(policy_b, model_family_b, exp_b, assump_b)

        rate = float(assump_a.get("inr_exchange_rate", DEFAULT_PRICING_ASSUMPTIONS.get("inr_exchange_rate", 90.00))) if convert_to_inr else 1.0
        cur_code = "INR" if convert_to_inr else "EUR"
        cur_sym = "₹" if convert_to_inr else "€"

        p0_rep = p0 * rate
        p1_rep = p1 * rate
        p2_rep = p2 * rate
        p3_rep = p3 * rate
        p4_rep = p4 * rate
        p5_rep = p5 * rate

        total_diff = p5 - p0
        total_diff_rep = p5_rep - p0_rep

        delta_1 = p1 - p0  # Delta P_input
        delta_2 = p2 - p1  # Delta P_model
        delta_3 = p3 - p2  # Delta P_exposure
        delta_4 = p4 - p3  # Delta P_assump
        delta_5 = p5 - p4  # Delta P_tax

        delta_1_rep = delta_1 * rate
        delta_2_rep = delta_2 * rate
        delta_3_rep = delta_3 * rate
        delta_4_rep = delta_4 * rate
        delta_5_rep = delta_5 * rate

        sum_deltas = delta_1 + delta_2 + delta_3 + delta_4 + delta_5
        recon_error = abs(total_diff - sum_deltas)
        recon_error_rep = recon_error * rate
        is_exact = bool(recon_error <= 1e-4)

        steps = [
            AttributionStep(
                step_number=1,
                step_name="Pure Risk Characteristics",
                description="Effect of updating driver, vehicle, and geographic rating territory features (Policy A -> Policy B).",
                starting_premium=round(p0_rep, 2),
                ending_premium=round(p1_rep, 2),
                dollar_impact=round(delta_1_rep, 2),
                percentage_impact=round((delta_1 / p0) * 100.0 if p0 > 0 else 0.0, 2),
                cumulative_change=round(p1_rep - p0_rep, 2)
            ),
            AttributionStep(
                step_number=2,
                step_name="Model Specification",
                description=f"Effect of switching model structure or family ({model_family_a} -> {model_family_b}).",
                starting_premium=round(p1_rep, 2),
                ending_premium=round(p2_rep, 2),
                dollar_impact=round(delta_2_rep, 2),
                percentage_impact=round((delta_2 / p0) * 100.0 if p0 > 0 else 0.0, 2),
                cumulative_change=round(p2_rep - p0_rep, 2)
            ),
            AttributionStep(
                step_number=3,
                step_name="Exposure Term Scaling",
                description=f"Effect of adjusting policy term length ({exp_a:.2f} yrs -> {exp_b:.2f} yrs).",
                starting_premium=round(p2_rep, 2),
                ending_premium=round(p3_rep, 2),
                dollar_impact=round(delta_3_rep, 2),
                percentage_impact=round((delta_3 / p0) * 100.0 if p0 > 0 else 0.0, 2),
                cumulative_change=round(p3_rep - p0_rep, 2)
            ),
            AttributionStep(
                step_number=4,
                step_name="Commercial Loading & Expenses",
                description="Effect of modifying fixed administrative expenses, variable expense ratio, and profit/risk margins.",
                starting_premium=round(p3_rep, 2),
                ending_premium=round(p4_rep, 2),
                dollar_impact=round(delta_4_rep, 2),
                percentage_impact=round((delta_4 / p0) * 100.0 if p0 > 0 else 0.0, 2),
                cumulative_change=round(p4_rep - p0_rep, 2)
            ),
            AttributionStep(
                step_number=5,
                step_name="Statutory Insurance Tax",
                description=f"Effect of statutory tax levy rate adjustment ({assump_a['tax_rate']*100:.1f}% -> {assump_b['tax_rate']*100:.1f}%).",
                starting_premium=round(p4_rep, 2),
                ending_premium=round(p5_rep, 2),
                dollar_impact=round(delta_5_rep, 2),
                percentage_impact=round((delta_5 / p0) * 100.0 if p0 > 0 else 0.0, 2),
                cumulative_change=round(p5_rep - p0_rep, 2)
            )
        ]

        # ----------------------------------------------------
        # Path-Order Sensitivity Analysis:
        # Evaluate reverse sequence (Tax -> Assump -> Exposure -> Model -> Pure Risk)
        # to quantify step order path dependence.
        # ----------------------------------------------------
        # Reverse Sequence:
        # Rev 0: Baseline (A)
        r0 = p0
        # Rev 1: Tax on Policy A
        assump_a_with_tax_b = dict(assump_a)
        assump_a_with_tax_b["tax_rate"] = assump_b["tax_rate"]
        r1, _ = self._evaluate_state(policy_a, model_family_a, exp_a, assump_a_with_tax_b)
        delta_rev_tax = r1 - r0

        # Rev 2: Commercial loadings on Policy A
        r2, _ = self._evaluate_state(policy_a, model_family_a, exp_a, assump_b)
        delta_rev_assump = r2 - r1

        # Rev 3: Exposure on Policy A
        r3, _ = self._evaluate_state(policy_a, model_family_a, exp_b, assump_b)
        delta_rev_exposure = r3 - r2

        # Rev 4: Model family on Policy A
        r4, _ = self._evaluate_state(policy_a, model_family_b, exp_b, assump_b)
        delta_rev_model = r4 - r3

        # Rev 5: Policy B features (Final target)
        r5 = p5
        delta_rev_risk = r5 - r4

        delta_rev_tax_rep = delta_rev_tax * rate
        delta_rev_assump_rep = delta_rev_assump * rate
        delta_rev_exposure_rep = delta_rev_exposure * rate
        delta_rev_model_rep = delta_rev_model * rate
        delta_rev_risk_rep = delta_rev_risk * rate

        order_sensitivity = {
            "comparison_note": f"Evaluates attribution magnitudes under forward vs. reversed factorization paths in {cur_code} ({cur_sym}) to measure non-linear interaction sensitivity.",
            "forward_sequence": {
                "pure_risk": round(delta_1_rep, 2),
                "model_specification": round(delta_2_rep, 2),
                "exposure_scaling": round(delta_3_rep, 2),
                "commercial_assumptions": round(delta_4_rep, 2),
                "statutory_tax": round(delta_5_rep, 2)
            },
            "reverse_sequence": {
                "statutory_tax": round(delta_rev_tax_rep, 2),
                "commercial_assumptions": round(delta_rev_assump_rep, 2),
                "exposure_scaling": round(delta_rev_exposure_rep, 2),
                "model_specification": round(delta_rev_model_rep, 2),
                "pure_risk": round(delta_rev_risk_rep, 2)
            },
            "max_step_divergence": round(max(
                abs(delta_1_rep - delta_rev_risk_rep),
                abs(delta_2_rep - delta_rev_model_rep),
                abs(delta_3_rep - delta_rev_exposure_rep),
                abs(delta_4_rep - delta_rev_assump_rep),
                abs(delta_5_rep - delta_rev_tax_rep)
            ), 2),
            "interaction_comment": (
                "Step order divergence reflects the compounding multiplicative structure of commercial loadings "
                "and tax on pure risk, documenting full path-dependent actuarial decomposition."
            )
        }

        # Record run in immutable registry
        run_inputs = {
            "policy_a": policy_a.model_dump(),
            "policy_b": policy_b.model_dump(),
            "model_family_a": model_family_a,
            "model_family_b": model_family_b,
            "convert_to_inr": convert_to_inr
        }
        run_assumptions = {
            "assumptions_a": assump_a,
            "assumptions_b": assump_b
        }
        run_trace = {
            "premium_a": p0,
            "premium_b": p5,
            "delta_pure_risk": delta_1,
            "delta_model": delta_2,
            "delta_exposure": delta_3,
            "delta_assumptions": delta_4,
            "delta_tax": delta_5,
            "total_difference": total_diff,
            "sum_of_deltas": sum_deltas,
            "reconciliation_error": recon_error
        }
        run_outputs = {
            "premium_a": round(p0_rep, 2),
            "premium_b": round(p5_rep, 2),
            "total_difference": round(total_diff_rep, 2),
            "is_exact_reconciliation": is_exact,
            "currency": cur_code
        }

        run_id = self.registry.record_run(
            run_type="RECONCILIATION",
            inputs=run_inputs,
            assumptions=run_assumptions,
            calculation_trace=run_trace,
            outputs=run_outputs,
            user_notes=user_notes
        )

        return ReconciliationResponse(
            policy_a_total_premium=round(p0_rep, 2),
            policy_b_total_premium=round(p5_rep, 2),
            total_difference=round(total_diff_rep, 2),
            is_exact_reconciliation=is_exact,
            reconciliation_error=round(recon_error_rep, 6),
            tolerance_epsilon=round(1e-4 * rate, 6),
            primary_sequence_order=[
                "Pure Risk Characteristics",
                "Model Specification",
                "Exposure Term Scaling",
                "Commercial Loading & Expenses",
                "Statutory Insurance Tax"
            ],
            sequential_steps=steps,
            order_sensitivity_analysis=order_sensitivity,
            run_id=run_id,
            currency=cur_code,
            currency_symbol=cur_sym
        )


# Global singleton instance
reconciliation_service = ReconciliationService()
