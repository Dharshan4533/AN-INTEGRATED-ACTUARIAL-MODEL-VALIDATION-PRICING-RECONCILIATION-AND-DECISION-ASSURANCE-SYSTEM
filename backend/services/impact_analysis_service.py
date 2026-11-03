"""
Portfolio Impact and Dislocation Analysis Service.
Aggregates portfolio-level changes, verifies aggregate reconciliation identities via Decimal arithmetic,
and profiles dislocation distributions across segments.
"""

from decimal import Decimal
import numpy as np
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from rating.spec_schema import RatingManualSpec
from backend.services.rate_change_service import RateChangeService, PolicyAttributionResult
from rating.rule_validator import RatingRuleValidator


class SegmentImpact(BaseModel):
    segment_variable: str
    segment_value: str
    policy_count: int
    total_old_premium: float
    total_new_premium: float
    dollar_change: float
    percentage_change: float
    avg_old_premium: float
    avg_new_premium: float


class PortfolioReconciliationReport(BaseModel):
    old_manual_id: str
    old_version: str
    new_manual_id: str
    new_version: str
    currency: str
    total_submitted_policies: int
    total_valid_policies: int
    total_failed_policies: int
    total_ineligible_policies: int
    total_old_premium: float
    total_new_premium: float
    aggregate_dollar_change: float
    aggregate_percentage_change: float
    sum_individual_deltas: float
    aggregate_reconciliation_residual: float
    is_aggregate_reconciled: bool
    count_rate_increase: int
    count_rate_decrease: int
    count_rate_unchanged: int
    pct_rate_increase: float
    pct_rate_decrease: float
    pct_rate_unchanged: float
    min_dollar_change: float
    max_dollar_change: float
    min_pct_change: Optional[float] = None
    max_pct_change: Optional[float] = None
    pct_change_percentiles: Dict[str, float] = Field(default_factory=dict)
    top_increases: List[Dict[str, Any]] = Field(default_factory=list)
    top_decreases: List[Dict[str, Any]] = Field(default_factory=list)
    segment_impacts: List[SegmentImpact] = Field(default_factory=list)
    policy_results: List[PolicyAttributionResult] = Field(default_factory=list)


class ImpactAnalysisService:
    """
    Analyzes aggregate rate change impact across policy census.
    """

    def __init__(self, old_spec: RatingManualSpec, new_spec: RatingManualSpec):
        self.old_spec = old_spec
        self.new_spec = new_spec
        self.rate_service = RateChangeService(old_spec, new_spec)
        self.validator_old = RatingRuleValidator(old_spec)
        self.validator_new = RatingRuleValidator(new_spec)
        self.precision = new_spec.currency_precision

    def reconcile_census(self, census: List[Dict[str, Any]]) -> PortfolioReconciliationReport:
        """
        Executes full portfolio reconciliation and computes dislocation metrics.
        """
        valid_policies: List[Dict[str, Any]] = []
        failed_count = 0
        ineligible_count = 0

        for row in census:
            v_old = self.validator_old.validate_policy(row)
            v_new = self.validator_new.validate_policy(row)
            if not v_old.is_valid or not v_new.is_valid:
                failed_count += 1
            elif not v_old.is_eligible or not v_new.is_eligible:
                ineligible_count += 1
                valid_policies.append(row)
            else:
                valid_policies.append(row)

        dec_old_total = Decimal("0.0")
        dec_new_total = Decimal("0.0")
        dec_deltas_sum = Decimal("0.0")

        policy_results: List[PolicyAttributionResult] = []
        pct_changes: List[float] = []

        increases = 0
        decreases = 0
        unchanged = 0

        for p in valid_policies:
            res = self.rate_service.evaluate_policy_change(p)
            policy_results.append(res)

            if res.eligibility_status == "ELIGIBLE":
                dec_old_total += Decimal(str(res.old_premium))
                dec_new_total += Decimal(str(res.new_premium))
                dec_deltas_sum += Decimal(str(res.absolute_change))

                if res.absolute_change > 0:
                    increases += 1
                elif res.absolute_change < 0:
                    decreases += 1
                else:
                    unchanged += 1

                if res.percentage_change is not None:
                    pct_changes.append(res.percentage_change)

        total_valid = increases + decreases + unchanged
        old_tot = float(dec_old_total)
        new_tot = float(dec_new_total)
        agg_delta = round(new_tot - old_tot, self.precision)
        deltas_sum = float(dec_deltas_sum)

        agg_residual = round(abs(agg_delta - deltas_sum), 6)
        is_reconciled = bool(agg_residual <= 1e-4)

        agg_pct = round((agg_delta / old_tot) * 100.0, 2) if old_tot > 0 else 0.0

        pct_inc = round((increases / total_valid) * 100.0, 2) if total_valid > 0 else 0.0
        pct_dec = round((decreases / total_valid) * 100.0, 2) if total_valid > 0 else 0.0
        pct_unc = round((unchanged / total_valid) * 100.0, 2) if total_valid > 0 else 0.0

        percentiles_dict: Dict[str, float] = {}
        if pct_changes:
            arr = np.array(pct_changes)
            percentiles_dict = {
                "p10": round(float(np.percentile(arr, 10)), 2),
                "p25": round(float(np.percentile(arr, 25)), 2),
                "p50": round(float(np.percentile(arr, 50)), 2),
                "p75": round(float(np.percentile(arr, 75)), 2),
                "p90": round(float(np.percentile(arr, 90)), 2),
                "p99": round(float(np.percentile(arr, 99)), 2),
            }

        sorted_by_delta = sorted(
            [r for r in policy_results if r.eligibility_status == "ELIGIBLE"],
            key=lambda x: x.absolute_change,
            reverse=True
        )
        top_increases = [
            {"policy_id": r.policy_id, "old": r.old_premium, "new": r.new_premium, "delta": r.absolute_change, "pct": r.percentage_change}
            for r in sorted_by_delta[:5] if r.absolute_change > 0
        ]
        top_decreases = [
            {"policy_id": r.policy_id, "old": r.old_premium, "new": r.new_premium, "delta": r.absolute_change, "pct": r.percentage_change}
            for r in reversed(sorted_by_delta[-5:]) if r.absolute_change < 0
        ]

        # Segment breakdown (e.g. by territory)
        segment_impacts: List[SegmentImpact] = []
        for var in sorted(self.new_spec.factor_tables.keys()):
            cat_groups: Dict[str, List[PolicyAttributionResult]] = {}
            for idx, p in enumerate(valid_policies):
                if var in p:
                    c = str(p[var]).strip()
                    cat_groups.setdefault(c, []).append(policy_results[idx])

            for c, r_list in sorted(cat_groups.items()):
                c_old = sum(r.old_premium for r in r_list)
                c_new = sum(r.new_premium for r in r_list)
                c_diff = round(c_new - c_old, self.precision)
                c_pct = round((c_diff / c_old) * 100.0, 2) if c_old > 0 else 0.0
                segment_impacts.append(SegmentImpact(
                    segment_variable=var,
                    segment_value=c,
                    policy_count=len(r_list),
                    total_old_premium=round(c_old, self.precision),
                    total_new_premium=round(c_new, self.precision),
                    dollar_change=c_diff,
                    percentage_change=c_pct,
                    avg_old_premium=round(c_old / len(r_list), self.precision) if r_list else 0.0,
                    avg_new_premium=round(c_new / len(r_list), self.precision) if r_list else 0.0
                ))

        return PortfolioReconciliationReport(
            old_manual_id=self.old_spec.manual_id,
            old_version=self.old_spec.version,
            new_manual_id=self.new_spec.manual_id,
            new_version=self.new_spec.version,
            currency=self.new_spec.currency,
            total_submitted_policies=len(census),
            total_valid_policies=total_valid,
            total_failed_policies=failed_count,
            total_ineligible_policies=ineligible_count,
            total_old_premium=round(old_tot, self.precision),
            total_new_premium=round(new_tot, self.precision),
            aggregate_dollar_change=agg_delta,
            aggregate_percentage_change=agg_pct,
            sum_individual_deltas=round(deltas_sum, self.precision),
            aggregate_reconciliation_residual=agg_residual,
            is_aggregate_reconciled=is_reconciled,
            count_rate_increase=increases,
            count_rate_decrease=decreases,
            count_rate_unchanged=unchanged,
            pct_rate_increase=pct_inc,
            pct_rate_decrease=pct_dec,
            pct_rate_unchanged=pct_unc,
            min_dollar_change=min((r.absolute_change for r in sorted_by_delta), default=0.0),
            max_dollar_change=max((r.absolute_change for r in sorted_by_delta), default=0.0),
            min_pct_change=min(pct_changes) if pct_changes else None,
            max_pct_change=max(pct_changes) if pct_changes else None,
            pct_change_percentiles=percentiles_dict,
            top_increases=top_increases,
            top_decreases=top_decreases,
            segment_impacts=segment_impacts,
            policy_results=policy_results
        )
