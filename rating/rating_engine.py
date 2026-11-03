"""
Primary Configurable Rating Calculation Engine.
Executes versioned rating manual pipelines, discrete factor tables, additive fees,
statutory limits, and currency rounding conventions.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from rating.spec_schema import RatingManualSpec, StepType, ClampStage, TaxBaseType
from rating.calculation_trace import CalculationTrace
from rating.rounding_policy import quantize_currency
from rating.rule_validator import (
    RatingRuleValidator,
    MissingRatingVariableError,
    UnsupportedCategoryError,
    InvalidPolicyIdentifierError
)


class RatingCalculationError(Exception):
    """Raised when an unrecoverable mathematical or pipeline execution error occurs."""
    pass


class UnsupportedRatingRuleError(RatingCalculationError):
    """Raised when the specification contains an unsupported pipeline step or formula."""
    pass


class PolicyRatingResult(BaseModel):
    policy_id: str
    manual_id: str
    manual_version: str
    currency: str
    currency_precision: int
    premium: float
    unrounded_premium: float
    taxable_base: float = 0.0
    tax_amount: float = 0.0
    applied_fees_total: float = 0.0
    is_clamped: bool = False
    is_ineligible: bool = False
    ineligibility_reasons: List[str] = Field(default_factory=list)
    trace: CalculationTrace


class DeterministicRatingEngine:
    """
    Executes the configurable insurance rating pipeline deterministically.
    """

    def __init__(self, spec: RatingManualSpec):
        self.spec = spec
        self.validator = RatingRuleValidator(spec)
        self.precision = spec.currency_precision

    def calculate_policy(self, policy: Dict[str, Any]) -> PolicyRatingResult:
        """
        Rates a single policy according to the specification's calculation pipeline.
        """
        # 1. Pre-flight Validation
        val_res = self.validator.validate_policy(policy)
        if not val_res.is_valid:
            error_msg = "; ".join(val_res.errors)
            if "Missing mandatory rating variable" in error_msg:
                raise MissingRatingVariableError(f"Policy '{val_res.policy_id}': {error_msg}")
            if "Unsupported category" in error_msg:
                raise UnsupportedCategoryError(f"Policy '{val_res.policy_id}': {error_msg}")
            if "Missing mandatory 'policy_id'" in error_msg:
                raise InvalidPolicyIdentifierError(f"Policy identifier error: {error_msg}")
            raise RatingCalculationError(f"Validation failure for policy '{val_res.policy_id}': {error_msg}")

        # If ineligible under underwriting criteria
        if not val_res.is_eligible:
            trace = CalculationTrace(
                policy_id=val_res.policy_id,
                manual_id=self.spec.manual_id,
                manual_version=self.spec.version,
                currency=self.spec.currency,
                currency_precision=self.precision,
                unrounded_final_premium=0.0,
                final_quantized_premium=0.0,
                is_ineligible=True,
                ineligibility_reasons=val_res.rejection_reasons
            )
            return PolicyRatingResult(
                policy_id=val_res.policy_id,
                manual_id=self.spec.manual_id,
                manual_version=self.spec.version,
                currency=self.spec.currency,
                currency_precision=self.precision,
                premium=0.0,
                unrounded_premium=0.0,
                is_ineligible=True,
                ineligibility_reasons=val_res.rejection_reasons,
                trace=trace
            )

        policy_id = val_res.policy_id
        trace = CalculationTrace(
            policy_id=policy_id,
            manual_id=self.spec.manual_id,
            manual_version=self.spec.version,
            currency=self.spec.currency,
            currency_precision=self.precision,
            unrounded_final_premium=0.0,
            final_quantized_premium=0.0
        )

        running_premium = 0.0
        pure_or_loaded_premium = 0.0
        taxable_fees = 0.0
        taxable_discounts = 0.0
        total_fees = 0.0
        tax_amount = 0.0
        is_clamped = False
        step_idx = 1

        pipeline = self.spec.calculation_pipeline or []

        for step in pipeline:
            step_type = step.step_type

            # Step: BASE_RATE
            if step_type == StepType.BASE_RATE:
                starting = running_premium
                running_premium = float(self.spec.base_rate)
                pure_or_loaded_premium = running_premium
                trace.add_step(
                    step_number=step_idx,
                    step_type="BASE_RATE",
                    rule_name="base_rate",
                    starting_amount=starting,
                    ending_amount=running_premium,
                    factor_or_rate=self.spec.base_rate,
                    description=f"Base Rate initialized to {self.spec.base_rate:.2f} {self.spec.currency}"
                )
                step_idx += 1

            # Step: MULTIPLICATIVE_FACTOR
            elif step_type == StepType.MULTIPLICATIVE_FACTOR:
                var_name = step.variable
                if not var_name or var_name not in self.spec.factor_tables:
                    raise UnsupportedRatingRuleError(f"Factor table for variable '{var_name}' not configured.")
                cat = str(policy[var_name]).strip()
                factor = float(self.spec.factor_tables[var_name][cat])
                starting = running_premium
                running_premium = running_premium * factor
                pure_or_loaded_premium = running_premium
                trace.add_step(
                    step_number=step_idx,
                    step_type="MULTIPLICATIVE_FACTOR",
                    rule_name=f"factor_{var_name}",
                    input_value=cat,
                    factor_or_rate=factor,
                    starting_amount=starting,
                    ending_amount=running_premium,
                    description=f"Multiplied by factor for {var_name}='{cat}' ({factor:.4f})"
                )
                step_idx += 1

            # Step: DISCOUNT_CREDIT
            elif step_type == StepType.DISCOUNT_CREDIT:
                var_name = step.variable
                if not var_name or var_name not in self.spec.discount_tables:
                    raise UnsupportedRatingRuleError(f"Discount table for variable '{var_name}' not configured.")
                cat = str(policy[var_name]).strip()
                val = float(self.spec.discount_tables[var_name][cat])
                starting = running_premium

                # Multiplicative discount if 0 < val <= 1.0, or negative additive credit if val < 0
                if 0.0 < val <= 1.0:
                    running_premium = running_premium * val
                    if step.is_taxable_deduction:
                        taxable_discounts += (starting - running_premium)
                    desc = f"Applied discount factor for {var_name}='{cat}' ({val:.4f})"
                else:
                    running_premium = max(0.0, running_premium + val)
                    if step.is_taxable_deduction:
                        taxable_discounts += abs(val)
                    desc = f"Applied discount credit for {var_name}='{cat}' ({val:.2f})"

                pure_or_loaded_premium = running_premium
                trace.add_step(
                    step_number=step_idx,
                    step_type="DISCOUNT_CREDIT",
                    rule_name=f"discount_{var_name}",
                    input_value=cat,
                    factor_or_rate=val,
                    starting_amount=starting,
                    ending_amount=running_premium,
                    description=desc
                )
                step_idx += 1

            # Step: INTERMEDIATE_ROUNDING
            elif step_type == StepType.INTERMEDIATE_ROUNDING:
                prec = step.precision if step.precision is not None else 4
                method = step.rule or self.spec.rounding_rule.method
                starting = running_premium
                running_premium = float(quantize_currency(running_premium, precision=prec, method=method))
                pure_or_loaded_premium = running_premium
                trace.add_step(
                    step_number=step_idx,
                    step_type="INTERMEDIATE_ROUNDING",
                    rule_name="intermediate_rounding",
                    starting_amount=starting,
                    ending_amount=running_premium,
                    description=f"Intermediate rounding to {prec} decimals using {method}"
                )
                step_idx += 1

            # Step: ADDITIVE_FEE
            elif step_type == StepType.ADDITIVE_FEE:
                fee_name = step.fee_name
                if not fee_name or fee_name not in self.spec.additive_fees:
                    raise UnsupportedRatingRuleError(f"Additive fee '{fee_name}' not declared in manual.")
                fee_val = float(self.spec.additive_fees[fee_name])
                starting = running_premium
                running_premium = running_premium + fee_val
                total_fees += fee_val
                if step.is_taxable or self.spec.fee_taxability.get(fee_name, False):
                    taxable_fees += fee_val

                trace.add_step(
                    step_number=step_idx,
                    step_type="ADDITIVE_FEE",
                    rule_name=f"fee_{fee_name}",
                    factor_or_rate=fee_val,
                    starting_amount=starting,
                    ending_amount=running_premium,
                    description=f"Added fee '{fee_name}' of {fee_val:.2f} {self.spec.currency}"
                )
                step_idx += 1

            # Step: STATUTORY_CLAMPING
            elif step_type == StepType.STATUTORY_CLAMPING:
                min_p = step.min_premium if step.min_premium is not None else self.spec.min_premium
                max_p = step.max_premium if step.max_premium is not None else self.spec.max_premium
                starting = running_premium
                clamped_prem = running_premium
                desc = "No clamping required."

                if min_p is not None and clamped_prem < min_p:
                    clamped_prem = float(min_p)
                    is_clamped = True
                    desc = f"Clamped to statutory minimum premium of {min_p:.2f} {self.spec.currency}"
                elif max_p is not None and clamped_prem > max_p:
                    clamped_prem = float(max_p)
                    is_clamped = True
                    desc = f"Clamped to regulatory maximum ceiling of {max_p:.2f} {self.spec.currency}"

                running_premium = clamped_prem
                trace.add_step(
                    step_number=step_idx,
                    step_type="STATUTORY_CLAMPING",
                    rule_name="min_max_clamping",
                    starting_amount=starting,
                    ending_amount=running_premium,
                    description=desc
                )
                step_idx += 1

            # Step: STATUTORY_TAX
            elif step_type == StepType.STATUTORY_TAX:
                rate = step.tax_rate if step.tax_rate is not None else self.spec.tax_rate
                base_type = step.tax_base or self.spec.tax_base
                starting = running_premium

                if base_type == TaxBaseType.TAXABLE_BASE:
                    tax_base = pure_or_loaded_premium + taxable_fees - taxable_discounts
                else:  # GROSS_PREMIUM
                    tax_base = running_premium

                taxable_base_val = max(0.0, tax_base)
                tax_val = float(quantize_currency(
                    taxable_base_val * rate,
                    precision=self.precision,
                    method=self.spec.rounding_rule.method
                ))
                tax_amount = tax_val
                running_premium = running_premium + tax_val
                trace.add_step(
                    step_number=step_idx,
                    step_type="STATUTORY_TAX",
                    rule_name="premium_tax",
                    factor_or_rate=rate,
                    starting_amount=starting,
                    ending_amount=running_premium,
                    description=f"Assessed statutory tax of {tax_val:.2f} ({rate*100:.2f}% on {taxable_base_val:.2f})"
                )
                step_idx += 1

            # Step: FINAL_ROUNDING
            elif step_type == StepType.FINAL_ROUNDING:
                method = step.rule or self.spec.rounding_rule.method
                starting = running_premium
                q_prem = quantize_currency(running_premium, precision=self.precision, method=method)
                running_premium = float(q_prem)
                trace.add_step(
                    step_number=step_idx,
                    step_type="FINAL_ROUNDING",
                    rule_name="final_rounding",
                    starting_amount=starting,
                    ending_amount=running_premium,
                    description=f"Final rounding to {self.precision} decimals ({self.spec.currency}) via {method}"
                )
                step_idx += 1

            else:
                raise UnsupportedRatingRuleError(f"Unsupported pipeline step type: '{step_type}'")

        unrounded = float(trace.steps[-2].ending_amount) if len(trace.steps) > 1 else running_premium
        final_prem = running_premium
        trace.unrounded_final_premium = round(unrounded, 6)
        trace.final_quantized_premium = round(final_prem, self.precision)

        return PolicyRatingResult(
            policy_id=policy_id,
            manual_id=self.spec.manual_id,
            manual_version=self.spec.version,
            currency=self.spec.currency,
            currency_precision=self.precision,
            premium=round(final_prem, self.precision),
            unrounded_premium=round(unrounded, 6),
            taxable_base=round(pure_or_loaded_premium + taxable_fees - taxable_discounts, self.precision),
            tax_amount=round(tax_amount, self.precision),
            applied_fees_total=round(total_fees, self.precision),
            is_clamped=is_clamped,
            is_ineligible=False,
            trace=trace
        )
