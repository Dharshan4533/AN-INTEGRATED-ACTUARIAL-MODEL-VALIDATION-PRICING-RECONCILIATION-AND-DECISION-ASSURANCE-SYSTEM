"""
Dual Independent Verification Calculator.
Provides an independently implemented, decimal-exact calculation engine that verifies
the primary engine's output to guarantee calculation integrity and detect software bugs.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_CEILING, ROUND_FLOOR
from typing import Dict, Any, List
from pydantic import BaseModel, Field

from rate_engine.spec_schema import RatingManualSpec, RoundingMethod
from rate_engine.rating_engine import RatingResult


class VerificationOutcome(BaseModel):
    policy_id: str
    is_verified: bool
    primary_premium: float
    independent_premium: float
    discrepancy: float
    tolerance: float = 0.00
    verification_checks: List[str] = Field(default_factory=list)
    failure_reasons: List[str] = Field(default_factory=list)


class DualIndependentCalculator:
    """
    Independent alternative calculator using strict fixed-point Decimal arithmetic.
    Used exclusively to audit and challenge the primary rating engine.
    """

    def __init__(self, spec: RatingManualSpec):
        self.spec = spec

    def calculate_independent_decimal(self, policy: Dict[str, Any]) -> Decimal:
        """
        Pure Decimal-based computation of policy premium.
        Constructed with separate logic from the primary engine.
        """
        # 1. Base rate
        val = Decimal(str(self.spec.base_rate))

        # 2. Multiplicative factors
        for var_name, factor_table in self.spec.factor_tables.items():
            cat = str(policy[var_name]).strip()
            factor_dec = Decimal(str(factor_table[cat]))
            val = val * factor_dec

        # 3. Additive fees
        for fee_name, fee_amt in self.spec.additive_fees.items():
            val = val + Decimal(str(fee_amt))

        # 4. Clamping
        if self.spec.min_premium is not None:
            min_dec = Decimal(str(self.spec.min_premium))
            if val < min_dec:
                val = min_dec

        if self.spec.max_premium is not None:
            max_dec = Decimal(str(self.spec.max_premium))
            if val > max_dec:
                val = max_dec

        # 5. Rounding
        precision = self.spec.rounding_rule.precision
        method = self.spec.rounding_rule.method

        if method == RoundingMethod.ROUND_HALF_UP:
            r_mode = ROUND_HALF_UP
        elif method == RoundingMethod.ROUND_HALF_EVEN:
            r_mode = ROUND_HALF_EVEN
        elif method == RoundingMethod.ROUND_CEILING:
            r_mode = ROUND_CEILING
        else:
            r_mode = ROUND_FLOOR

        quant = Decimal("1") if precision == 0 else Decimal("0." + ("0" * precision))
        return val.quantize(quant, rounding=r_mode)

    def verify(self, primary_result: RatingResult, policy: Dict[str, Any]) -> VerificationOutcome:
        """Verify primary rating result against the independent calculation."""
        indep_dec = self.calculate_independent_decimal(policy)
        indep_float = float(indep_dec)
        prim_float = primary_result.premium

        discrepancy = abs(prim_float - indep_float)
        is_verified = bool(discrepancy <= 1e-4)

        checks = [
            f"Independent Decimal calculation completed: {indep_float:.2f} {self.spec.currency}",
            f"All {len(self.spec.factor_tables)} factor tables independently resolved",
            f"All {len(self.spec.additive_fees)} additive fees independently applied",
            f"Rounding rule ({self.spec.rounding_rule.method.value}, {self.spec.rounding_rule.precision} dec) checked",
        ]

        failures = []
        if not is_verified:
            failures.append(
                f"Discrepancy detected: Primary={prim_float:.2f} vs Independent={indep_float:.2f} (diff={discrepancy:.6f})"
            )

        return VerificationOutcome(
            policy_id=primary_result.policy_id,
            is_verified=is_verified,
            primary_premium=prim_float,
            independent_premium=indep_float,
            discrepancy=round(discrepancy, 6),
            tolerance=0.00,
            verification_checks=checks,
            failure_reasons=failures
        )
