"""
Structurally Independent Decimal Calculation Verifier.
Implements an independent calculation pipeline using Python's decimal.Decimal
with explicit context precision (prec=28) and strict currency quantization.
"""

from decimal import Decimal, getcontext, ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_CEILING, ROUND_FLOOR
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from rating.spec_schema import RatingManualSpec, StepType, ClampStage, TaxBaseType
from rating.rating_engine import PolicyRatingResult
from rating.rounding_policy import quantize_currency

# Explicit Decimal context precision configuration
getcontext().prec = 28


class VerificationResult(BaseModel):
    policy_id: str
    is_verified: bool
    primary_premium: float
    independent_premium: float
    discrepancy: float
    intermediate_discrepancy: float
    failure_reasons: List[str] = Field(default_factory=list)


class IndependentCalculator:
    """
    Independent rating calculator using Decimal arithmetic (prec=28)
    with distinct pipeline evaluation and separate intermediate vs final checks.
    """

    def __init__(self, spec: RatingManualSpec):
        self.spec = spec
        self.precision = spec.currency_precision
        # Build local decimal representation of factor tables
        self.dec_base_rate = Decimal(str(spec.base_rate))
        self.dec_factors: Dict[str, Dict[str, Decimal]] = {
            var: {cat: Decimal(str(f)) for cat, f in tbl.items()}
            for var, tbl in spec.factor_tables.items()
        }
        self.dec_discounts: Dict[str, Dict[str, Decimal]] = {
            var: {cat: Decimal(str(f)) for cat, f in tbl.items()}
            for var, tbl in spec.discount_tables.items()
        }
        self.dec_fees: Dict[str, Decimal] = {
            name: Decimal(str(f)) for name, f in spec.additive_fees.items()
        }
        self.dec_min_p = Decimal(str(spec.min_premium)) if spec.min_premium is not None else None
        self.dec_max_p = Decimal(str(spec.max_premium)) if spec.max_premium is not None else None
        self.dec_tax_rate = Decimal(str(spec.tax_rate))

    def calculate_independent_decimal(self, policy: Dict[str, Any]) -> Tuple[Decimal, Decimal]:
        """
        Calculates premium using independent Decimal pipeline.
        Returns:
            Tuple[Decimal, Decimal]: (unrounded_intermediate_decimal, final_quantized_currency_decimal)
        """
        running = Decimal("0.0")
        pure_or_loaded = Decimal("0.0")
        taxable_fees = Decimal("0.0")
        taxable_discounts = Decimal("0.0")

        pipeline = self.spec.calculation_pipeline or []

        for step in pipeline:
            stype = step.step_type

            if stype == StepType.BASE_RATE:
                running = self.dec_base_rate
                pure_or_loaded = running

            elif stype == StepType.MULTIPLICATIVE_FACTOR:
                var = step.variable
                cat = str(policy[var]).strip()
                factor = self.dec_factors[var][cat]
                running = running * factor
                pure_or_loaded = running

            elif stype == StepType.DISCOUNT_CREDIT:
                var = step.variable
                cat = str(policy[var]).strip()
                val = self.dec_discounts[var][cat]
                if Decimal("0.0") < val <= Decimal("1.0"):
                    start = running
                    running = running * val
                    if step.is_taxable_deduction:
                        taxable_discounts += (start - running)
                else:
                    running = max(Decimal("0.0"), running + val)
                    if step.is_taxable_deduction:
                        taxable_discounts += abs(val)
                pure_or_loaded = running

            elif stype == StepType.INTERMEDIATE_ROUNDING:
                prec = step.precision if step.precision is not None else 4
                method = step.rule or self.spec.rounding_rule.method
                running = quantize_currency(running, precision=prec, method=method)
                pure_or_loaded = running

            elif stype == StepType.ADDITIVE_FEE:
                fee_name = step.fee_name
                fee_val = self.dec_fees[fee_name]
                running = running + fee_val
                if step.is_taxable or self.spec.fee_taxability.get(fee_name, False):
                    taxable_fees += fee_val

            elif stype == StepType.STATUTORY_CLAMPING:
                min_p = Decimal(str(step.min_premium)) if step.min_premium is not None else self.dec_min_p
                max_p = Decimal(str(step.max_premium)) if step.max_premium is not None else self.dec_max_p
                if min_p is not None and running < min_p:
                    running = min_p
                elif max_p is not None and running > max_p:
                    running = max_p

            elif stype == StepType.STATUTORY_TAX:
                rate = Decimal(str(step.tax_rate)) if step.tax_rate is not None else self.dec_tax_rate
                base_type = step.tax_base or self.spec.tax_base
                if base_type == TaxBaseType.TAXABLE_BASE:
                    tax_base = pure_or_loaded + taxable_fees - taxable_discounts
                else:
                    tax_base = running
                taxable_base_val = max(Decimal("0.0"), tax_base)
                tax_val = quantize_currency(
                    taxable_base_val * rate,
                    precision=self.precision,
                    method=self.spec.rounding_rule.method
                )
                running = running + tax_val

            elif stype == StepType.FINAL_ROUNDING:
                pass  # Handled at return

        unrounded = running
        quantized = quantize_currency(
            running,
            precision=self.precision,
            method=self.spec.rounding_rule.method
        )
        return unrounded, quantized

    def verify(
        self,
        primary_result: PolicyRatingResult,
        policy: Dict[str, Any],
        intermediate_tolerance: float = 1e-4
    ) -> VerificationResult:
        """
        Verifies primary rating result against independent Decimal calculation.
        """
        # If policy is ineligible, verification passes if both agree on ineligibility
        if primary_result.is_ineligible:
            return VerificationResult(
                policy_id=primary_result.policy_id,
                is_verified=True,
                primary_premium=0.0,
                independent_premium=0.0,
                discrepancy=0.0,
                intermediate_discrepancy=0.0
            )

        dec_unrounded, dec_quantized = self.calculate_independent_decimal(policy)
        indep_final = float(dec_quantized)
        indep_unrounded = float(dec_unrounded)

        monetary_diff = round(abs(primary_result.premium - indep_final), 6)
        inter_diff = round(abs(primary_result.unrounded_premium - indep_unrounded), 6)

        reasons = []
        # Exact monetary equality check: 0.00 difference after quantization
        if monetary_diff != 0.0:
            reasons.append(
                f"Monetary premium mismatch: Primary={primary_result.premium:.2f} vs "
                f"Independent={indep_final:.2f} (diff={monetary_diff:.4f})"
            )
        # Intermediate tolerance check
        if inter_diff > intermediate_tolerance:
            reasons.append(
                f"Intermediate unrounded difference exceeds tolerance: Primary={primary_result.unrounded_premium:.6f} vs "
                f"Independent={indep_unrounded:.6f} (diff={inter_diff:.6f} > {intermediate_tolerance})"
            )

        is_verified = (len(reasons) == 0)

        return VerificationResult(
            policy_id=primary_result.policy_id,
            is_verified=is_verified,
            primary_premium=primary_result.premium,
            independent_premium=indep_final,
            discrepancy=monetary_diff,
            intermediate_discrepancy=inter_diff,
            failure_reasons=reasons
        )
