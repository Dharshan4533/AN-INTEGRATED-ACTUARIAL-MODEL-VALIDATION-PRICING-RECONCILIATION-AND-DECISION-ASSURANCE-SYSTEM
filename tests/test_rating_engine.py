"""
Test Suite for Rate Change Assurance Workbench.
Verifies hand-calculated benchmarks, dual independent calculations,
exact factor attribution, aggregate reconciliation, and boundary edge cases.
"""

import json
import pytest
from pathlib import Path
from decimal import Decimal

from rate_engine.spec_schema import RatingManualSpec, RoundingRule, RoundingMethod
from rate_engine.spec_loader import load_rating_manual, compute_spec_hash
from rate_engine.validator import CensusValidator
from rate_engine.rating_engine import DeterministicRatingEngine, RatingCalculationError
from rate_engine.independent_verifier import DualIndependentCalculator
from rate_engine.attribution import ExactFactorAttributor
from rate_engine.portfolio_reconciler import PortfolioReconciler


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


def test_hand_calculated_policy_benchmarks(old_manual, new_manual, sample_policies):
    """
    Verify all 5 policies against hand-calculated actuarial answers.
    Acceptance criteria: Bit-exact agreement with hand calculations.
    """
    old_engine = DeterministicRatingEngine(old_manual)
    new_engine = DeterministicRatingEngine(new_manual)

    for p in sample_policies:
        p_id = p["policy_id"]
        exp_old = p["expected_old_premium"]
        exp_new = p["expected_new_premium"]
        exp_delta = p["expected_delta"]
        exp_pct = p["expected_pct_change"]

        res_old = old_engine.calculate_policy(p)
        res_new = new_engine.calculate_policy(p)

        assert res_old.premium == exp_old, f"Policy {p_id} old premium mismatch: {res_old.premium} vs {exp_old}"
        assert res_new.premium == exp_new, f"Policy {p_id} new premium mismatch: {res_new.premium} vs {exp_new}"

        delta = round(res_new.premium - res_old.premium, 2)
        assert delta == exp_delta, f"Policy {p_id} delta mismatch: {delta} vs {exp_delta}"

        pct = round((delta / res_old.premium) * 100.0, 2)
        assert pct == exp_pct, f"Policy {p_id} % change mismatch: {pct} vs {exp_pct}"


def test_dual_independent_verification_100_percent_agreement(old_manual, new_manual, sample_policies):
    """
    Verify that the primary rating engine agrees with the dual independent Decimal calculator.
    Tolerance: exactly 0.00 difference.
    """
    old_engine = DeterministicRatingEngine(old_manual)
    new_engine = DeterministicRatingEngine(new_manual)
    old_verifier = DualIndependentCalculator(old_manual)
    new_verifier = DualIndependentCalculator(new_manual)

    for p in sample_policies:
        # Check under Old Manual
        res_old = old_engine.calculate_policy(p)
        ver_old = old_verifier.verify(res_old, p)
        assert ver_old.is_verified is True
        assert ver_old.discrepancy == 0.00
        assert len(ver_old.failure_reasons) == 0

        # Check under New Manual
        res_new = new_engine.calculate_policy(p)
        ver_new = new_verifier.verify(res_new, p)
        assert ver_new.is_verified is True
        assert ver_new.discrepancy == 0.00
        assert len(ver_new.failure_reasons) == 0


def test_exact_factor_attribution_decomposition(old_manual, new_manual, sample_policies):
    """
    Verify that sequential factor attribution decomposes delta P exactly with 0 residual.
    """
    attributor = ExactFactorAttributor(old_manual, new_manual)

    for p in sample_policies:
        p_id = p["policy_id"]
        attr = attributor.attribute_policy(p)

        assert attr.is_exact_reconciliation is True
        assert attr.attribution_residual == 0.00

        # Check components match documented expected attributions
        exp_attr = p["expected_attributions"]
        for comp, exp_val in exp_attr.items():
            assert attr.attributions_by_component[comp] == exp_val, (
                f"Policy {p_id} component '{comp}' attribution mismatch: "
                f"{attr.attributions_by_component[comp]} vs {exp_val}"
            )

        sum_steps = round(sum(s.dollar_impact for s in attr.steps), 2)
        assert sum_steps == attr.absolute_change


def test_aggregate_portfolio_reconciliation_identity(old_manual, new_manual, sample_policies):
    """
    Verify portfolio aggregate reconciliation identity:
    Sum(Delta P_i) == Total New Premium - Total Old Premium.
    """
    reconciler = PortfolioReconciler(old_manual, new_manual)
    report = reconciler.reconcile_census(sample_policies)

    assert report.total_valid_policies == 5
    assert report.total_failed_policies == 0
    assert report.total_old_premium == 2125.00
    assert report.total_new_premium == 2394.00
    assert report.aggregate_dollar_change == 269.00
    assert report.aggregate_percentage_change == 12.66
    assert report.is_aggregate_reconciled is True
    assert report.reconciliation_error == 0.00
    assert report.all_independent_checks_passed is True
    assert report.policies_increasing_count == 5


def test_undefined_percentage_change_on_zero_baseline(old_manual, new_manual):
    """
    Verify that when baseline premium is zero, percentage change is reported as undefined.
    """
    # Create manual with 0 base rate and 0 fee
    zero_dict = old_manual.model_dump()
    zero_dict["base_rate"] = 0.0001
    zero_dict["additive_fees"] = {}
    zero_dict["factor_tables"]["territory"]["Rural"] = 0.0000001
    # Clamping floor of 0
    zero_dict["rounding_rule"]["precision"] = 2
    # Or test directly with ExactFactorAttributor on mock 0 premium
    attributor = ExactFactorAttributor(old_manual, new_manual)

    mock_old_res = old_manual
    # Pass a synthetic policy where old_premium is forced to 0.0
    from rate_engine.rating_engine import RatingResult
    from rate_engine.calculation_trace import CalculationTrace

    mock_res_old = RatingResult(
        policy_id="POL-ZERO",
        manual_id="old",
        manual_version="1.0.0",
        currency="USD",
        currency_symbol="$",
        premium=0.00,
        unrounded_premium=0.00,
        trace=CalculationTrace(
            policy_id="POL-ZERO", manual_id="old", manual_version="1.0",
            base_rate=0.0, cumulative_factor=1.0, subtotal_after_factors=0.0,
            total_fees=0.0, subtotal_after_fees=0.0, subtotal_after_clamping=0.0,
            unrounded_premium=0.0, rounded_premium=0.0, precision=2, rounding_method="ROUND_HALF_UP"
        )
    )

    p_test = {"policy_id": "POL-ZERO", "territory": "Urban"}
    attr = attributor.attribute_policy(p_test, old_res=mock_res_old)

    assert attr.percentage_change is None
    assert "undefined" in attr.percentage_change_explanation.lower()


def test_missing_variable_rejection(old_manual):
    """
    Verify that a policy missing a required factor variable produces an explicit error,
    not a guessed premium.
    """
    engine = DeterministicRatingEngine(old_manual)
    bad_policy = {"policy_id": "POL-MISSING-VAR"}  # missing 'territory'

    with pytest.raises(RatingCalculationError) as exc_info:
        engine.calculate_policy(bad_policy)

    assert "Missing required rating variable 'territory'" in str(exc_info.value)


def test_unsupported_category_rejection(old_manual):
    """
    Verify that an unknown category raises an explicit validation error listing valid categories.
    """
    engine = DeterministicRatingEngine(old_manual)
    bad_policy = {"policy_id": "POL-UNKNOWN-CAT", "territory": "MetroArea"}

    with pytest.raises(RatingCalculationError) as exc_info:
        engine.calculate_policy(bad_policy)

    assert "Unsupported category 'MetroArea'" in str(exc_info.value)
    assert "Urban" in str(exc_info.value)


def test_missing_policy_id_rejection(old_manual):
    """Verify that a policy record without an identifier is rejected."""
    engine = DeterministicRatingEngine(old_manual)
    bad_policy = {"territory": "Urban"}  # Missing policy_id

    with pytest.raises(RatingCalculationError) as exc_info:
        engine.calculate_policy(bad_policy)

    assert "Missing or empty required field 'policy_id'" in str(exc_info.value)


def test_spec_cryptographic_checksum_changes_on_modification(old_manual):
    """
    Verify that modifying any rule in the rating manual changes its cryptographic SHA-256 hash.
    """
    raw_dict = old_manual.model_dump()
    hash_1 = compute_spec_hash(raw_dict)

    # Change fee by 1 cent
    raw_dict["additive_fees"]["policy_fee"] = 25.01
    hash_2 = compute_spec_hash(raw_dict)

    assert hash_1 != hash_2, "SHA-256 checksum must detect manual rule changes."


def test_clamping_minimum_and_maximum_premium():
    """
    Verify that min_premium and max_premium boundaries clamp premiums properly.
    """
    spec_data = {
        "manual_id": "manual_clamped",
        "name": "Clamped Manual",
        "version": "1.0.0",
        "effective_date": "2026-01-01",
        "line_of_business": "Auto",
        "currency": "USD",
        "currency_symbol": "$",
        "base_rate": 100.0,
        "factor_tables": {"territory": {"Low": 0.50, "High": 3.00}},
        "additive_fees": {"fee": 10.0},
        "min_premium": 150.0,  # Floor: 100 * 0.5 + 10 = 60 -> should clamp to 150
        "max_premium": 250.0,  # Ceiling: 100 * 3.0 + 10 = 310 -> should clamp to 250
        "rounding_rule": {"precision": 2, "method": "ROUND_HALF_UP"},
        "calculation_order": ["base_rate", "multiplicative_factors", "additive_fees", "min_max_clamping", "rounding"]
    }
    spec = RatingManualSpec(**spec_data)
    engine = DeterministicRatingEngine(spec)

    # 1. Floor test
    p_low = {"policy_id": "POL-LOW", "territory": "Low"}
    res_low = engine.calculate_policy(p_low)
    assert res_low.premium == 150.00
    assert res_low.trace.clamped_by == "min_premium"

    # 2. Ceiling test
    p_high = {"policy_id": "POL-HIGH", "territory": "High"}
    res_high = engine.calculate_policy(p_high)
    assert res_high.premium == 250.00
    assert res_high.trace.clamped_by == "max_premium"


def test_deterministic_reproducibility(old_manual, sample_policies):
    """
    Verify that running calculations repeatedly produces bit-exact identical output.
    """
    engine = DeterministicRatingEngine(old_manual)
    runs = []

    for _ in range(20):
        run_premiums = [engine.calculate_policy(p).premium for p in sample_policies]
        runs.append(run_premiums)

    # All runs must be identical to the first run
    for r in runs[1:]:
        assert r == runs[0]
