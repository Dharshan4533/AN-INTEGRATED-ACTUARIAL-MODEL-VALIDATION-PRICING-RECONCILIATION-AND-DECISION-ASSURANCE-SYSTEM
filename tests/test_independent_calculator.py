"""
Test Suite for Structurally Independent Decimal Calculator.
Verifies exact monetary equality ($0.00 difference after quantization),
intermediate calculation tolerance, and boundary stress tests.
"""

import json
import pytest
from decimal import Decimal

from rating.spec_schema import RatingManualSpec, RoundingRule, RoundingMethod
from rating.spec_loader import load_rating_manual
from rating.rating_engine import DeterministicRatingEngine
from rating.independent_calculator import IndependentCalculator
from rating.rounding_policy import quantize_currency
from backend.services.verification_service import VerificationService


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


def test_independent_calculator_exact_monetary_agreement(new_manual, sample_policies):
    """
    Verifies that IndependentCalculator achieves exact monetary equality (discrepancy = $0.00)
    for all policies against the primary engine.
    """
    primary_engine = DeterministicRatingEngine(new_manual)
    indep_calc = IndependentCalculator(new_manual)

    for p in sample_policies:
        res_prim = primary_engine.calculate_policy(p)
        v_res = indep_calc.verify(res_prim, p)

        assert v_res.is_verified is True
        assert v_res.discrepancy == 0.00
        assert v_res.intermediate_discrepancy <= 1e-4
        assert len(v_res.failure_reasons) == 0


def test_rounding_boundary_half_up_vs_half_even():
    """
    Verifies exact rounding behavior at the .005 boundary.
    ROUND_HALF_UP rounds .005 away from zero to .01.
    ROUND_HALF_EVEN rounds .005 to nearest even (e.g. 0.025 -> 0.02, 0.015 -> 0.02).
    """
    val_odd = Decimal("100.015")
    val_even = Decimal("100.025")

    # ROUND_HALF_UP: both round up
    assert quantize_currency(val_odd, 2, RoundingMethod.ROUND_HALF_UP) == Decimal("100.02")
    assert quantize_currency(val_even, 2, RoundingMethod.ROUND_HALF_UP) == Decimal("100.03")

    # ROUND_HALF_EVEN: rounds to nearest even
    assert quantize_currency(val_odd, 2, RoundingMethod.ROUND_HALF_EVEN) == Decimal("100.02")
    assert quantize_currency(val_even, 2, RoundingMethod.ROUND_HALF_EVEN) == Decimal("100.02")


def test_independent_calculator_detects_tampering(new_manual, sample_policies):
    """
    Verifies that if primary result is tampered by even 1 cent, independent verification fails.
    """
    primary_engine = DeterministicRatingEngine(new_manual)
    indep_calc = IndependentCalculator(new_manual)

    policy = sample_policies[0]
    res_prim = primary_engine.calculate_policy(policy)

    # Tamper with the result by 1 cent
    tampered_res = res_prim.model_copy()
    tampered_res.premium = round(tampered_res.premium + 0.01, 2)

    v_res = indep_calc.verify(tampered_res, policy)
    assert v_res.is_verified is False
    assert v_res.discrepancy == 0.01
    assert any("Monetary premium mismatch" in r for r in v_res.failure_reasons)


def test_batch_verification_service(new_manual, sample_policies):
    """
    Verifies full census batch verification summary.
    """
    service = VerificationService(new_manual)
    summary = service.verify_census(sample_policies)

    assert summary.is_100_percent_verified is True
    assert summary.total_policies_checked == 5
    assert summary.total_passed == 5
    assert summary.total_failed == 0
    assert summary.max_monetary_discrepancy == 0.00
