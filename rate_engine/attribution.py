"""
Exact Factor Attribution Engine.
Decomposes policy premium changes (P_new - P_old) into exact, defensible factor contributions
such as base rate revisions, rating table adjustments, fee modifications, and rounding residuals.
Guarantees sum of contributions equals total premium change within tolerance.
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from rate_engine.spec_schema import RatingManualSpec
from rate_engine.rating_engine import DeterministicRatingEngine, RatingResult


class AttributionStep(BaseModel):
    step_number: int
    component_name: str
    component_type: str  # BASE_RATE, FACTOR, FEE, BOUNDS_ROUNDING
    starting_premium: float
    ending_premium: float
    dollar_impact: float
    percentage_impact: float
    cumulative_dollar_impact: float
    description: str


class PolicyAttributionResult(BaseModel):
    policy_id: str
    old_premium: float
    new_premium: float
    absolute_change: float
    percentage_change: Optional[float] = None
    percentage_change_explanation: str
    is_exact_reconciliation: bool
    attribution_residual: float
    tolerance_epsilon: float = 1e-4
    steps: List[AttributionStep] = Field(default_factory=list)
    attributions_by_component: Dict[str, float] = Field(default_factory=dict)


class ExactFactorAttributor:
    """
    Computes exact factor attribution decomposing P_new - P_old.
    Uses sequential arithmetic factorial path with full residual tracking.
    """

    def __init__(self, old_spec: RatingManualSpec, new_spec: RatingManualSpec):
        self.old_spec = old_spec
        self.new_spec = new_spec
        self.old_engine = DeterministicRatingEngine(old_spec)
        self.new_engine = DeterministicRatingEngine(new_spec)

    def attribute_policy(
        self,
        policy: Dict[str, Any],
        old_res: Optional[RatingResult] = None,
        new_res: Optional[RatingResult] = None
    ) -> PolicyAttributionResult:
        """
        Decomposes total premium change into sequential factor contributions.
        """
        if old_res is None:
            old_res = self.old_engine.calculate_policy(policy)
        if new_res is None:
            new_res = self.new_engine.calculate_policy(policy)

        p_old = old_res.premium
        p_new = new_res.premium
        delta_total = p_new - p_old

        # Percentage change handling
        if p_old == 0.0:
            pct_change = None
            pct_explanation = "Percentage change is undefined because baseline (old) premium is zero."
        else:
            pct_change = round((delta_total / p_old) * 100.0, 2)
            pct_explanation = f"{(delta_total / p_old) * 100.0:+.2f}% relative to baseline premium of {p_old:.2f}"

        # ----------------------------------------------------
        # Sequential Factor Attribution Pipeline:
        # Step 0: Old baseline State
        # Step 1: Base Rate (New Base Rate, rest Old)
        # Step 2..K: Factor tables (Progressively update factors to New)
        # Step K+1: Additive fees (New fees, rest New)
        # Step K+2: Final Clamping & Rounding (Target New State)
        # ----------------------------------------------------
        steps: List[AttributionStep] = []
        attributions: Dict[str, float] = {}

        current_spec_dict = self.old_spec.model_dump()
        current_p = p_old
        step_idx = 1

        # 1. Base Rate Change
        if self.new_spec.base_rate != self.old_spec.base_rate:
            temp_dict = dict(current_spec_dict)
            temp_dict["base_rate"] = self.new_spec.base_rate
            temp_spec = RatingManualSpec(**temp_dict)
            next_p = DeterministicRatingEngine(temp_spec).calculate_policy(policy).premium
            diff = round(next_p - current_p, 2)

            steps.append(AttributionStep(
                step_number=step_idx,
                component_name="base_rate",
                component_type="BASE_RATE",
                starting_premium=current_p,
                ending_premium=next_p,
                dollar_impact=diff,
                percentage_impact=round((diff / p_old) * 100.0 if p_old > 0 else 0.0, 2),
                cumulative_dollar_impact=round(next_p - p_old, 2),
                description=f"Base rate revised from {self.old_spec.base_rate:.2f} to {self.new_spec.base_rate:.2f}"
            ))
            attributions["base_rate"] = diff
            current_p = next_p
            current_spec_dict["base_rate"] = self.new_spec.base_rate
            step_idx += 1
        else:
            attributions["base_rate"] = 0.0

        # 2. Factor Tables (evaluated factor by factor)
        all_factor_vars = list(dict.fromkeys(
            list(self.old_spec.factor_tables.keys()) + list(self.new_spec.factor_tables.keys())
        ))

        for var_name in all_factor_vars:
            old_table = self.old_spec.factor_tables.get(var_name, {})
            new_table = self.new_spec.factor_tables.get(var_name, {})

            cat = str(policy.get(var_name, "")).strip()
            old_f = old_table.get(cat, 1.0)
            new_f = new_table.get(cat, 1.0)

            temp_dict = dict(current_spec_dict)
            temp_dict["factor_tables"] = dict(temp_dict.get("factor_tables", {}))
            temp_dict["factor_tables"][var_name] = new_table
            temp_spec = RatingManualSpec(**temp_dict)
            next_p = DeterministicRatingEngine(temp_spec).calculate_policy(policy).premium
            diff = round(next_p - current_p, 2)

            steps.append(AttributionStep(
                step_number=step_idx,
                component_name=f"factor_{var_name}",
                component_type="FACTOR",
                starting_premium=current_p,
                ending_premium=next_p,
                dollar_impact=diff,
                percentage_impact=round((diff / p_old) * 100.0 if p_old > 0 else 0.0, 2),
                cumulative_dollar_impact=round(next_p - p_old, 2),
                description=f"Factor '{var_name}' ({cat}) changed from {old_f:.4f} to {new_f:.4f}"
            ))
            attributions[var_name] = diff
            current_p = next_p
            current_spec_dict["factor_tables"][var_name] = new_table
            step_idx += 1

        # 3. Additive Fees (individual breakdown and summary)
        all_fee_names = sorted(list(set(self.old_spec.additive_fees.keys()) | set(self.new_spec.additive_fees.keys())))
        total_fee_diff = 0.0
        current_fees = dict(current_spec_dict.get("additive_fees", {}))

        for fee_name in all_fee_names:
            old_fee = self.old_spec.additive_fees.get(fee_name, 0.0)
            new_fee = self.new_spec.additive_fees.get(fee_name, 0.0)
            if old_fee != new_fee:
                temp_fees = dict(current_fees)
                temp_fees[fee_name] = new_fee
                temp_dict = dict(current_spec_dict)
                temp_dict["additive_fees"] = temp_fees
                temp_spec = RatingManualSpec(**temp_dict)
                next_p = DeterministicRatingEngine(temp_spec).calculate_policy(policy).premium
                diff = round(next_p - current_p, 2)

                steps.append(AttributionStep(
                    step_number=step_idx,
                    component_name=fee_name,
                    component_type="FEE",
                    starting_premium=current_p,
                    ending_premium=next_p,
                    dollar_impact=diff,
                    percentage_impact=round((diff / p_old) * 100.0 if p_old > 0 else 0.0, 2),
                    cumulative_dollar_impact=round(next_p - p_old, 2),
                    description=f"Fee '{fee_name}' revised: {old_fee} -> {new_fee}"
                ))
                attributions[fee_name] = diff
                total_fee_diff += diff
                current_p = next_p
                current_fees[fee_name] = new_fee
                current_spec_dict["additive_fees"] = current_fees
                step_idx += 1
            else:
                attributions[fee_name] = 0.0

        attributions["fees"] = round(total_fee_diff, 2)

        # 4. Final target reconciliation check
        sum_attributed = sum(s.dollar_impact for s in steps)
        residual = abs(delta_total - sum_attributed)
        is_exact = bool(residual <= 1e-4)

        if not is_exact and abs(p_new - current_p) > 0:
            rounding_diff = round(p_new - current_p, 2)
            steps.append(AttributionStep(
                step_number=step_idx,
                component_name="bounds_and_rounding",
                component_type="BOUNDS_ROUNDING",
                starting_premium=current_p,
                ending_premium=p_new,
                dollar_impact=rounding_diff,
                percentage_impact=round((rounding_diff / p_old) * 100.0 if p_old > 0 else 0.0, 2),
                cumulative_dollar_impact=round(p_new - p_old, 2),
                description="Clamping limits, interaction adjustment, or rounding policy difference."
            ))
            attributions["bounds_and_rounding"] = rounding_diff
            sum_attributed += rounding_diff
            residual = abs(delta_total - sum_attributed)
            is_exact = bool(residual <= 1e-4)

        return PolicyAttributionResult(
            policy_id=str(policy.get("policy_id", "UNKNOWN")),
            old_premium=p_old,
            new_premium=p_new,
            absolute_change=round(delta_total, 2),
            percentage_change=pct_change,
            percentage_change_explanation=pct_explanation,
            is_exact_reconciliation=is_exact,
            attribution_residual=round(residual, 6),
            tolerance_epsilon=1e-4,
            steps=steps,
            attributions_by_component=attributions
        )
