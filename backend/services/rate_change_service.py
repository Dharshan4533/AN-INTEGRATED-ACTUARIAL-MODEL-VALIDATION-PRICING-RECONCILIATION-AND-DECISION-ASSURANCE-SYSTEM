"""
Rate Change Service.
Calculates policy-level premium changes, safe percentage changes on zero baselines,
and exact stepwise factor attribution with unallocated interaction reporting.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from rating.spec_schema import RatingManualSpec
from rating.rating_engine import DeterministicRatingEngine, PolicyRatingResult
from rating.rounding_policy import quantize_currency


class AttributionStep(BaseModel):
    step_number: int
    component_name: str
    component_type: str  # "BASE_RATE", "FACTOR", "FEE", "TAX", "UNALLOCATED_INTERACTION"
    starting_premium: float
    ending_premium: float
    dollar_impact: float
    percentage_impact: float
    cumulative_dollar_impact: float
    description: str


class PolicyAttributionResult(BaseModel):
    policy_id: str
    eligibility_status: str = "ELIGIBLE"  # "ELIGIBLE", "NEW_INCEPTION", "DISPLACED_INELIGIBLE", "INELIGIBLE_BOTH"
    old_premium: float
    new_premium: float
    absolute_change: float
    percentage_change: Optional[float] = None
    percentage_change_explanation: Optional[str] = None
    is_exact_reconciliation: bool = True
    attribution_residual: float = 0.0
    tolerance_epsilon: float = 1e-4
    steps: List[AttributionStep] = Field(default_factory=list)
    attributions_by_component: Dict[str, float] = Field(default_factory=dict)
    unallocated_interaction_adjustment: float = 0.0


class RateChangeService:
    """
    Decomposes policy-level premium differences into exact sequential factor attributions.
    """

    def __init__(self, old_spec: RatingManualSpec, new_spec: RatingManualSpec):
        self.old_spec = old_spec
        self.new_spec = new_spec
        self.old_engine = DeterministicRatingEngine(old_spec)
        self.new_engine = DeterministicRatingEngine(new_spec)
        self.precision = new_spec.currency_precision

    def evaluate_policy_change(self, policy: Dict[str, Any]) -> PolicyAttributionResult:
        """
        Calculates old vs new premium and decomposes difference into step contributions.
        """
        p_id = str(policy.get("policy_id") or policy.get("IDpol", "UNKNOWN"))

        # Calculate under Old and New
        res_old = self.old_engine.calculate_policy(policy)
        res_new = self.new_engine.calculate_policy(policy)

        # Handle Asymmetric Eligibility
        if res_old.is_ineligible and res_new.is_ineligible:
            return PolicyAttributionResult(
                policy_id=p_id,
                eligibility_status="INELIGIBLE_BOTH",
                old_premium=0.0,
                new_premium=0.0,
                absolute_change=0.0,
                percentage_change=None,
                percentage_change_explanation="Policy is ineligible under both rating manuals."
            )
        elif res_old.is_ineligible and not res_new.is_ineligible:
            return PolicyAttributionResult(
                policy_id=p_id,
                eligibility_status="NEW_INCEPTION",
                old_premium=0.0,
                new_premium=res_new.premium,
                absolute_change=res_new.premium,
                percentage_change=None,
                percentage_change_explanation="New inception: policy was ineligible under old manual."
            )
        elif not res_old.is_ineligible and res_new.is_ineligible:
            return PolicyAttributionResult(
                policy_id=p_id,
                eligibility_status="DISPLACED_INELIGIBLE",
                old_premium=res_old.premium,
                new_premium=0.0,
                absolute_change=-res_old.premium,
                percentage_change=-100.0,
                percentage_change_explanation="Displaced: policy is ineligible under revision."
            )

        p_old = res_old.premium
        p_new = res_new.premium
        delta_total = round(p_new - p_old, self.precision)

        # Safe percentage change check
        if p_old == 0.0:
            pct_change = None
            pct_explanation = "Baseline premium is zero; percentage change is mathematically undefined."
        else:
            pct_change = round((delta_total / p_old) * 100.0, 2)
            pct_explanation = None

        steps: List[AttributionStep] = []
        attributions: Dict[str, float] = {}
        current_p = p_old
        step_idx = 1

        # Current working configuration starting from old_spec
        current_spec_dict = self.old_spec.model_dump()

        # Step 1: Base Rate Impact
        if self.new_spec.base_rate != self.old_spec.base_rate:
            temp_dict = dict(current_spec_dict)
            temp_dict["base_rate"] = self.new_spec.base_rate
            temp_spec = RatingManualSpec(**temp_dict)
            next_p = DeterministicRatingEngine(temp_spec).calculate_policy(policy).premium
            diff = round(next_p - current_p, self.precision)

            steps.append(AttributionStep(
                step_number=step_idx,
                component_name="base_rate",
                component_type="BASE_RATE",
                starting_premium=current_p,
                ending_premium=next_p,
                dollar_impact=diff,
                percentage_impact=round((diff / p_old) * 100.0 if p_old > 0 else 0.0, 2),
                cumulative_dollar_impact=round(next_p - p_old, self.precision),
                description=f"Base rate changed from {self.old_spec.base_rate:.2f} to {self.new_spec.base_rate:.2f}"
            ))
            attributions["base_rate"] = diff
            current_p = next_p
            current_spec_dict["base_rate"] = self.new_spec.base_rate
            step_idx += 1
        else:
            attributions["base_rate"] = 0.0

        # Step 2: Multiplicative Rating Factors (Variable-by-Variable)
        all_vars = sorted(list(set(self.old_spec.factor_tables.keys()) | set(self.new_spec.factor_tables.keys())))
        for var_name in all_vars:
            old_table = self.old_spec.factor_tables.get(var_name, {})
            new_table = self.new_spec.factor_tables.get(var_name, {})
            cat = str(policy.get(var_name, "")).strip()

            old_f = old_table.get(cat, 1.0)
            new_f = new_table.get(cat, 1.0)

            if old_f != new_f:
                temp_dict = dict(current_spec_dict)
                temp_tables = dict(temp_dict.get("factor_tables", {}))
                temp_tables[var_name] = new_table
                temp_dict["factor_tables"] = temp_tables
                temp_spec = RatingManualSpec(**temp_dict)
                next_p = DeterministicRatingEngine(temp_spec).calculate_policy(policy).premium
                diff = round(next_p - current_p, self.precision)

                steps.append(AttributionStep(
                    step_number=step_idx,
                    component_name=var_name,
                    component_type="FACTOR",
                    starting_premium=current_p,
                    ending_premium=next_p,
                    dollar_impact=diff,
                    percentage_impact=round((diff / p_old) * 100.0 if p_old > 0 else 0.0, 2),
                    cumulative_dollar_impact=round(next_p - p_old, self.precision),
                    description=f"Factor '{var_name}' ({cat}) changed from {old_f:.4f} to {new_f:.4f}"
                ))
                attributions[var_name] = diff
                current_p = next_p
                current_spec_dict["factor_tables"][var_name] = new_table
                step_idx += 1
            else:
                attributions[var_name] = 0.0

        # Step 3: Additive Fees (individual fee breakdown)
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
                diff = round(next_p - current_p, self.precision)

                steps.append(AttributionStep(
                    step_number=step_idx,
                    component_name=fee_name,
                    component_type="FEE",
                    starting_premium=current_p,
                    ending_premium=next_p,
                    dollar_impact=diff,
                    percentage_impact=round((diff / p_old) * 100.0 if p_old > 0 else 0.0, 2),
                    cumulative_dollar_impact=round(next_p - p_old, self.precision),
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

        attributions["fees"] = round(total_fee_diff, self.precision)

        # Step 4: Unallocated Interaction and Rounding Adjustment
        sum_attributed = round(sum(s.dollar_impact for s in steps), self.precision)
        unallocated = round(p_new - current_p, self.precision)

        if abs(unallocated) > 0:
            steps.append(AttributionStep(
                step_number=step_idx,
                component_name="unallocated_interaction",
                component_type="UNALLOCATED_INTERACTION",
                starting_premium=current_p,
                ending_premium=p_new,
                dollar_impact=unallocated,
                percentage_impact=round((unallocated / p_old) * 100.0 if p_old > 0 else 0.0, 2),
                cumulative_dollar_impact=round(p_new - p_old, self.precision),
                description="Unallocated multi-factor interactions, statutory limits, or intermediate rounding."
            ))
            attributions["unallocated_interaction"] = unallocated
            sum_attributed = round(sum_attributed + unallocated, self.precision)
        else:
            attributions["unallocated_interaction"] = 0.0

        residual = round(abs(delta_total - sum_attributed), 6)
        is_exact = bool(residual <= 1e-4)

        return PolicyAttributionResult(
            policy_id=p_id,
            eligibility_status="ELIGIBLE",
            old_premium=p_old,
            new_premium=p_new,
            absolute_change=delta_total,
            percentage_change=pct_change,
            percentage_change_explanation=pct_explanation,
            is_exact_reconciliation=is_exact,
            attribution_residual=residual,
            tolerance_epsilon=1e-4,
            steps=steps,
            attributions_by_component=attributions,
            unallocated_interaction_adjustment=unallocated
        )
