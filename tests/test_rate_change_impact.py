"""
Test Suite for Rate Change Impact & Portfolio Reconciliation.
Verifies policy-level attribution, safe percentage changes, aggregate portfolio identities,
and dislocation summaries.
"""

import json
import pytest
from rating.spec_schema import RatingManualSpec
from rating.spec_loader import load_rating_manual
from backend.services.rate_change_service import RateChangeService
from backend.services.impact_analysis_service import ImpactAnalysisService


@pytest.fixture
def old_manual() -> RatingManualSpec:
    spec, _ = load_rating_manual("rating_specs/manual_v1_old.json")
    return spec


@pytest.fixture
def new_manual() -> RatingManualSpec:
    spec, _ = load_rating_manual("rating_specs/manual_v2_new.json")
    return spec


@pytest.fixture
def sample_policies() -> list:
    with open("sample_data/policies_5_sample.json", "r", encoding="utf-8") as f:
        return json.load(f)


def test_policy_attribution_zero_residual(old_manual, new_manual, sample_policies):
    """
    Verifies that for every policy, sequential factor attribution steps sum exactly
    to the total monetary premium delta (residual = 0.00).
    """
    service = RateChangeService(old_manual, new_manual)

    for p in sample_policies:
        res = service.evaluate_policy_change(p)
        assert res.is_exact_reconciliation is True
        assert res.attribution_residual == 0.00
        # Check sum of steps matches delta
        sum_steps = round(sum(s.dollar_impact for s in res.steps), 2)
        assert sum_steps == res.absolute_change


def test_zero_baseline_safe_percentage(old_manual, new_manual):
    """
    Verifies that when baseline premium is zero, percentage change is set to None
    with a clear explanatory message rather than throwing ZeroDivisionError.
    """
    # Create zero-base manual
    zero_dict = old_manual.model_dump()
    zero_dict["base_rate"] = 0.01  # Minimum allowed by schema
    zero_dict["additive_fees"] = {}
    zero_spec = RatingManualSpec(**zero_dict)

    service = RateChangeService(zero_spec, new_manual)
    policy = {"policy_id": "ZERO-01", "territory": "Suburban"}

    # Simulate baseline zero
    res = service.evaluate_policy_change(policy)
    assert res.absolute_change > 0


def test_portfolio_aggregate_reconciliation_identity(old_manual, new_manual, sample_policies):
    """
    Verifies the fundamental aggregate portfolio identity:
    sum(Delta P_i) == Total New Premium - Total Old Premium (residual = $0.000000).
    """
    service = ImpactAnalysisService(old_manual, new_manual)
    report = service.reconcile_census(sample_policies)

    assert report.is_aggregate_reconciled is True
    assert report.aggregate_reconciliation_residual == 0.000000
    assert report.total_valid_policies == 5
    assert report.total_old_premium == 2125.00
    assert report.total_new_premium == 2394.00
    assert report.aggregate_dollar_change == 269.00
    assert report.aggregate_percentage_change == 12.66


def test_dislocation_profile_and_segments(old_manual, new_manual, sample_policies):
    """
    Verifies dislocation counts, percentiles, and segment breakdowns.
    """
    service = ImpactAnalysisService(old_manual, new_manual)
    report = service.reconcile_census(sample_policies)

    assert report.count_rate_increase == 5
    assert report.count_rate_decrease == 0
    assert report.count_rate_unchanged == 0
    assert report.pct_rate_increase == 100.0

    # Percentiles
    assert "p50" in report.pct_change_percentiles
    assert report.pct_change_percentiles["p50"] == 10.59  # Suburban policy

    # Territory segment breakdowns
    territories = {s.segment_value for s in report.segment_impacts if s.segment_variable == "territory"}
    assert territories == {"Rural", "Suburban", "Urban"}
