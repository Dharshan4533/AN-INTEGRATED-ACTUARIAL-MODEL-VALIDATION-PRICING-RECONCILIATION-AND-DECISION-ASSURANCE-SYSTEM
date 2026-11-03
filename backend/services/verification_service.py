"""
Independent Calculation Verification Service.
Executes batch dual-calculator verification, compares primary engine results against
arbitrary-precision Decimal outputs, and reports discrepancy audits.
"""

from typing import Any, Dict, List
from pydantic import BaseModel, Field

from rating.spec_schema import RatingManualSpec
from rating.rating_engine import DeterministicRatingEngine
from rating.independent_calculator import IndependentCalculator, VerificationResult


class BatchVerificationSummary(BaseModel):
    manual_id: str
    manual_version: str
    currency: str
    total_policies_checked: int
    total_passed: int
    total_failed: int
    agreement_rate_pct: float
    max_monetary_discrepancy: float
    max_intermediate_discrepancy: float
    is_100_percent_verified: bool
    policy_results: List[VerificationResult] = Field(default_factory=list)
    failure_details: List[Dict[str, Any]] = Field(default_factory=list)


class VerificationService:
    """
    Coordinates dual-engine independent calculation verification for a rating manual.
    """

    def __init__(self, spec: RatingManualSpec):
        self.spec = spec
        self.primary_engine = DeterministicRatingEngine(spec)
        self.independent_calc = IndependentCalculator(spec)

    def verify_policy(self, policy: Dict[str, Any]) -> VerificationResult:
        """
        Runs dual verification on a single policy.
        """
        primary_res = self.primary_engine.calculate_policy(policy)
        return self.independent_calc.verify(primary_res, policy)

    def verify_census(self, census: List[Dict[str, Any]]) -> BatchVerificationSummary:
        """
        Runs dual verification across a full policy census.
        """
        results: List[VerificationResult] = []
        failures: List[Dict[str, Any]] = []
        max_monetary = 0.0
        max_inter = 0.0
        passed = 0

        for p in census:
            v_res = self.verify_policy(p)
            results.append(v_res)

            if v_res.is_verified:
                passed += 1
            else:
                failures.append({
                    "policy_id": v_res.policy_id,
                    "primary_premium": v_res.primary_premium,
                    "independent_premium": v_res.independent_premium,
                    "discrepancy": v_res.discrepancy,
                    "intermediate_discrepancy": v_res.intermediate_discrepancy,
                    "reasons": v_res.failure_reasons
                })

            if v_res.discrepancy > max_monetary:
                max_monetary = v_res.discrepancy
            if v_res.intermediate_discrepancy > max_inter:
                max_inter = v_res.intermediate_discrepancy

        total = len(census)
        agreement_pct = round((passed / total) * 100.0, 2) if total > 0 else 100.0

        return BatchVerificationSummary(
            manual_id=self.spec.manual_id,
            manual_version=self.spec.version,
            currency=self.spec.currency,
            total_policies_checked=total,
            total_passed=passed,
            total_failed=len(failures),
            agreement_rate_pct=agreement_pct,
            max_monetary_discrepancy=max_monetary,
            max_intermediate_discrepancy=max_inter,
            is_100_percent_verified=(passed == total),
            policy_results=results,
            failure_details=failures
        )
