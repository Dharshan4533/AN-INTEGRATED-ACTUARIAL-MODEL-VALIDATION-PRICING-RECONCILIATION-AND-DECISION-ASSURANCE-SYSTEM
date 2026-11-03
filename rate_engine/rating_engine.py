"""
Primary Deterministic Rating Engine.
Calculates insurance premiums in strict accordance with the versioned rating manual specification.
Produces an audit-ready, step-by-step calculation trace.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_CEILING, ROUND_FLOOR
from typing import Dict, Any, Optional
from pydantic import BaseModel

from rate_engine.spec_schema import RatingManualSpec, RoundingMethod, CalculationPipelineStep
from rate_engine.validator import CensusValidator, PolicyValidationResult
from rate_engine.calculation_trace import (
    CalculationTrace,
    FactorApplicationTrace,
    FeeApplicationTrace,
    StepTrace,
)


class RatingResult(BaseModel):
    policy_id: str
    manual_id: str
    manual_version: str
    currency: str
    currency_symbol: str
    premium: float
    unrounded_premium: float
    trace: CalculationTrace


class RatingCalculationError(Exception):
    """Raised when a policy calculation fails rating validation or rules."""
    def __init__(self, policy_id: str, errors: list):
        self.policy_id = policy_id
        self.errors = errors
        super().__init__(f"Rating calculation failed for policy '{policy_id}': {'; '.join(errors)}")


class DeterministicRatingEngine:
    """Executes deterministic insurance rating calculations."""

    ROUNDING_MAP = {
        RoundingMethod.ROUND_HALF_UP: ROUND_HALF_UP,
        RoundingMethod.ROUND_HALF_EVEN: ROUND_HALF_EVEN,
        RoundingMethod.ROUND_CEILING: ROUND_CEILING,
        RoundingMethod.ROUND_FLOOR: ROUND_FLOOR,
    }

    def __init__(self, spec: RatingManualSpec):
        self.spec = spec
        self.validator = CensusValidator(spec)

    def calculate_policy(self, raw_policy: Dict[str, Any]) -> RatingResult:
        """
        Execute full rating pipeline on a policy record.
        Raises RatingCalculationError if policy fails validation.
        """
        val_res: PolicyValidationResult = self.validator.validate_policy(raw_policy)
        if not val_res.is_valid:
            raise RatingCalculationError(val_res.policy_id, val_res.errors)

        policy = val_res.validated_record
        policy_id = policy["policy_id"]

        steps_trace: list[StepTrace] = []
        factors_trace: list[FactorApplicationTrace] = []
        fees_trace: list[FeeApplicationTrace] = []

        step_counter = 1
        current_val = float(self.spec.base_rate)
        steps_trace.append(StepTrace(
            step_number=step_counter,
            step_name="Base Rate Initialization",
            operation="INITIALIZE",
            value_in=0.0,
            operand=current_val,
            value_out=current_val,
            formula_description=f"Base rate = {current_val:.2f} {self.spec.currency}"
        ))

        cumulative_factor = 1.0

        for pipeline_step in self.spec.calculation_order:
            if pipeline_step == CalculationPipelineStep.BASE_RATE:
                # Already initialized
                continue

            elif pipeline_step == CalculationPipelineStep.MULTIPLICATIVE_FACTORS:
                for var_name, factor_table in self.spec.factor_tables.items():
                    category = policy[var_name]
                    factor_val = float(factor_table[category])
                    cumulative_factor *= factor_val
                    prev_val = current_val
                    current_val *= factor_val

                    factors_trace.append(FactorApplicationTrace(
                        variable_name=var_name,
                        selected_category=category,
                        factor_value=factor_val,
                        running_subtotal=current_val
                    ))

                    step_counter += 1
                    steps_trace.append(StepTrace(
                        step_number=step_counter,
                        step_name=f"Factor: {var_name} ({category})",
                        operation="MULTIPLY",
                        value_in=prev_val,
                        operand=factor_val,
                        value_out=current_val,
                        formula_description=f"{prev_val:.4f} × {factor_val:.4f} = {current_val:.4f}"
                    ))

            elif pipeline_step == CalculationPipelineStep.ADDITIVE_FEES:
                for fee_name, fee_amt in self.spec.additive_fees.items():
                    fee_float = float(fee_amt)
                    prev_val = current_val
                    current_val += fee_float

                    fees_trace.append(FeeApplicationTrace(
                        fee_name=fee_name,
                        fee_amount=fee_float,
                        running_subtotal=current_val
                    ))

                    step_counter += 1
                    steps_trace.append(StepTrace(
                        step_number=step_counter,
                        step_name=f"Fee: {fee_name}",
                        operation="ADD",
                        value_in=prev_val,
                        operand=fee_float,
                        value_out=current_val,
                        formula_description=f"{prev_val:.4f} + {fee_float:.2f} = {current_val:.4f}"
                    ))

            elif pipeline_step == CalculationPipelineStep.MIN_MAX_CLAMPING:
                clamped_by = None
                prev_val = current_val

                if self.spec.min_premium is not None and current_val < self.spec.min_premium:
                    clamped_by = "min_premium"
                    current_val = float(self.spec.min_premium)
                elif self.spec.max_premium is not None and current_val > self.spec.max_premium:
                    clamped_by = "max_premium"
                    current_val = float(self.spec.max_premium)

                if clamped_by:
                    step_counter += 1
                    steps_trace.append(StepTrace(
                        step_number=step_counter,
                        step_name=f"Bound Clamping ({clamped_by})",
                        operation="CLAMP",
                        value_in=prev_val,
                        operand=current_val,
                        value_out=current_val,
                        formula_description=f"Clamped by {clamped_by}: {prev_val:.4f} -> {current_val:.2f}"
                    ))

            elif pipeline_step == CalculationPipelineStep.ROUNDING:
                # Handled at final step
                pass

        # Final Rounding
        unrounded = current_val
        precision = self.spec.rounding_rule.precision
        method_enum = self.spec.rounding_rule.method
        decimal_method = self.ROUNDING_MAP[method_enum]

        # Convert via string representation to avoid binary float artifacts
        d_val = Decimal(str(unrounded))
        quantize_str = "1" if precision == 0 else "0." + ("0" * precision)
        rounded_decimal = d_val.quantize(Decimal(quantize_str), rounding=decimal_method)
        final_rounded = float(rounded_decimal)

        step_counter += 1
        steps_trace.append(StepTrace(
            step_number=step_counter,
            step_name="Rounding Finalization",
            operation="ROUND",
            value_in=unrounded,
            operand=f"{precision} decimals ({method_enum.value})",
            value_out=final_rounded,
            formula_description=f"round({unrounded:.6f}, {precision}, {method_enum.value}) = {final_rounded:.2f}"
        ))

        # Compile comprehensive calculation trace
        subtotal_factors = float(self.spec.base_rate) * cumulative_factor
        total_fees = sum(float(f) for f in self.spec.additive_fees.values())
        subtotal_fees = subtotal_factors + total_fees

        clamped_flag = None
        if self.spec.min_premium is not None and subtotal_fees < self.spec.min_premium:
            clamped_flag = "min_premium"
        elif self.spec.max_premium is not None and subtotal_fees > self.spec.max_premium:
            clamped_flag = "max_premium"

        trace = CalculationTrace(
            policy_id=policy_id,
            manual_id=self.spec.manual_id,
            manual_version=self.spec.version,
            base_rate=float(self.spec.base_rate),
            factors_applied=factors_trace,
            cumulative_factor=round(cumulative_factor, 6),
            subtotal_after_factors=round(subtotal_factors, 4),
            fees_applied=fees_trace,
            total_fees=round(total_fees, 2),
            subtotal_after_fees=round(subtotal_fees, 4),
            clamped_by=clamped_flag,
            subtotal_after_clamping=round(unrounded, 4),
            unrounded_premium=unrounded,
            rounded_premium=final_rounded,
            precision=precision,
            rounding_method=method_enum.value,
            steps=steps_trace
        )

        return RatingResult(
            policy_id=policy_id,
            manual_id=self.spec.manual_id,
            manual_version=self.spec.version,
            currency=self.spec.currency,
            currency_symbol=self.spec.currency_symbol,
            premium=final_rounded,
            unrounded_premium=unrounded,
            trace=trace
        )
