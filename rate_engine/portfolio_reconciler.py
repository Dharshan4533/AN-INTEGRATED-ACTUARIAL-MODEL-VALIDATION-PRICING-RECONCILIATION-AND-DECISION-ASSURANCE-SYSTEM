"""
Portfolio Reconciliation & Impact Analysis Engine.
Aggregates policy-level calculations across an entire census, verifies aggregate reconciliation,
evaluates policy increase/decrease shares, and reports independent verification status.
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from rate_engine.spec_schema import RatingManualSpec
from rate_engine.rating_engine import DeterministicRatingEngine, RatingResult, RatingCalculationError
from rate_engine.independent_verifier import DualIndependentCalculator, VerificationOutcome
from rate_engine.attribution import ExactFactorAttributor, PolicyAttributionResult


class PolicyComparisonRecord(BaseModel):
    policy_id: str
    attributes: Dict[str, Any]
    old_premium: float
    new_premium: float
    dollar_change: float
    percentage_change: Optional[float] = None
    is_verified_by_independent_calc: bool
    independent_discrepancy: float
    attribution: PolicyAttributionResult


class PortfolioReconciliationReport(BaseModel):
    old_manual_id: str
    old_manual_version: str
    new_manual_id: str
    new_manual_version: str
    currency: str
    currency_symbol: str
    total_policies_submitted: int
    total_valid_policies: int
    total_failed_policies: int
    total_old_premium: float
    total_new_premium: float
    aggregate_dollar_change: float
    aggregate_percentage_change: float
    policies_increasing_count: int
    policies_increasing_pct: float
    policies_decreasing_count: int
    policies_decreasing_pct: float
    policies_unchanged_count: int
    policies_unchanged_pct: float
    is_aggregate_reconciled: bool
    reconciliation_error: float
    all_independent_checks_passed: bool
    policy_records: List[PolicyComparisonRecord] = Field(default_factory=list)
    exceptions: List[Dict[str, Any]] = Field(default_factory=list)


class PortfolioReconciler:
    """Executes portfolio-wide rate change impact analysis and reconciliation."""

    def __init__(self, old_spec: RatingManualSpec, new_spec: RatingManualSpec):
        self.old_spec = old_spec
        self.new_spec = new_spec
        self.old_engine = DeterministicRatingEngine(old_spec)
        self.new_engine = DeterministicRatingEngine(new_spec)
        self.old_verifier = DualIndependentCalculator(old_spec)
        self.new_verifier = DualIndependentCalculator(new_spec)
        self.attributor = ExactFactorAttributor(old_spec, new_spec)

    def reconcile_census(self, census_policies: List[Dict[str, Any]]) -> PortfolioReconciliationReport:
        """
        Run end-to-end reconciliation and verification over a collection of policies.
        """
        records: List[PolicyComparisonRecord] = []
        exceptions: List[Dict[str, Any]] = []

        total_submitted = len(census_policies)

        for p in census_policies:
            p_id = str(p.get("policy_id", "UNKNOWN"))
            try:
                # 1. Primary rating calculations
                old_res = self.old_engine.calculate_policy(p)
                new_res = self.new_engine.calculate_policy(p)

                # 2. Dual independent verification checks
                old_ver = self.old_verifier.verify(old_res, p)
                new_ver = self.new_verifier.verify(new_res, p)
                is_verified = old_ver.is_verified and new_ver.is_verified
                max_discrepancy = max(old_ver.discrepancy, new_ver.discrepancy)

                # 3. Exact factor attribution
                attr_res = self.attributor.attribute_policy(p, old_res, new_res)

                records.append(PolicyComparisonRecord(
                    policy_id=p_id,
                    attributes={k: v for k, v in p.items() if k != "policy_id"},
                    old_premium=old_res.premium,
                    new_premium=new_res.premium,
                    dollar_change=round(new_res.premium - old_res.premium, 2),
                    percentage_change=attr_res.percentage_change,
                    is_verified_by_independent_calc=is_verified,
                    independent_discrepancy=round(max_discrepancy, 6),
                    attribution=attr_res
                ))

            except RatingCalculationError as rce:
                exceptions.append({
                    "policy_id": p_id,
                    "error_type": "RatingCalculationError",
                    "details": rce.errors,
                    "raw_record": p
                })
            except Exception as exc:
                exceptions.append({
                    "policy_id": p_id,
                    "error_type": type(exc).__name__,
                    "details": [str(exc)],
                    "raw_record": p
                })

        valid_count = len(records)
        failed_count = len(exceptions)

        if valid_count > 0:
            sum_old = round(sum(r.old_premium for r in records), 2)
            sum_new = round(sum(r.new_premium for r in records), 2)
            agg_delta = round(sum_new - sum_old, 2)
            sum_of_policy_deltas = round(sum(r.dollar_change for r in records), 2)

            recon_error = abs(agg_delta - sum_of_policy_deltas)
            is_reconciled = bool(recon_error <= 1e-4)

            agg_pct = round((agg_delta / sum_old) * 100.0, 2) if sum_old > 0 else 0.0

            n_inc = sum(1 for r in records if r.dollar_change > 0)
            n_dec = sum(1 for r in records if r.dollar_change < 0)
            n_unch = sum(1 for r in records if r.dollar_change == 0)

            all_verified = all(r.is_verified_by_independent_calc for r in records)

        else:
            sum_old = 0.0
            sum_new = 0.0
            agg_delta = 0.0
            recon_error = 0.0
            is_reconciled = True
            agg_pct = 0.0
            n_inc = 0
            n_dec = 0
            n_unch = 0
            all_verified = True

        return PortfolioReconciliationReport(
            old_manual_id=self.old_spec.manual_id,
            old_manual_version=self.old_spec.version,
            new_manual_id=self.new_spec.manual_id,
            new_manual_version=self.new_spec.version,
            currency=self.new_spec.currency,
            currency_symbol=self.new_spec.currency_symbol,
            total_policies_submitted=total_submitted,
            total_valid_policies=valid_count,
            total_failed_policies=failed_count,
            total_old_premium=sum_old,
            total_new_premium=sum_new,
            aggregate_dollar_change=agg_delta,
            aggregate_percentage_change=agg_pct,
            policies_increasing_count=n_inc,
            policies_increasing_pct=round((n_inc / valid_count) * 100.0 if valid_count > 0 else 0.0, 1),
            policies_decreasing_count=n_dec,
            policies_decreasing_pct=round((n_dec / valid_count) * 100.0 if valid_count > 0 else 0.0, 1),
            policies_unchanged_count=n_unch,
            policies_unchanged_pct=round((n_unch / valid_count) * 100.0 if valid_count > 0 else 0.0, 1),
            is_aggregate_reconciled=is_reconciled,
            reconciliation_error=round(recon_error, 6),
            all_independent_checks_passed=all_verified,
            policy_records=records,
            exceptions=exceptions
        )
