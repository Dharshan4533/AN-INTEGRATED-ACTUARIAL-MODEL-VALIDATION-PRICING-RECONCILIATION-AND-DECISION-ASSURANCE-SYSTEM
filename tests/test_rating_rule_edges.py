"""
Test Suite for Rating Rule Edges & Validation Faults.
Verifies missing field rejection, unmapped category faults, statutory limits,
discounts, tax base definitions, and eligibility rules.
"""

import pytest
from rating.spec_schema import RatingManualSpec, StepType, ClampStage, TaxBaseType
from rating.spec_loader import load_rating_manual
from rating.rating_engine import DeterministicRatingEngine
from rating.rule_validator import (
    RatingRuleValidator,
    MissingRatingVariableError,
    UnsupportedCategoryError,
    InvalidPolicyIdentifierError
)


@pytest.fixture
def base_manual() -> RatingManualSpec:
    spec, _ = load_rating_manual("rating_specs/manual_v1_old.json")
    return spec


def test_missing_variable_rejection(base_manual):
    """Verify that a policy missing a required factor variable is rejected."""
    engine = DeterministicRatingEngine(base_manual)
    bad_policy = {"policy_id": "ERR-01"}  # Missing 'territory'

    with pytest.raises(MissingRatingVariableError) as exc_info:
        engine.calculate_policy(bad_policy)
    assert "Missing mandatory rating variable 'territory'" in str(exc_info.value)


def test_unsupported_category_rejection(base_manual):
    """Verify that a policy with an unknown category is rejected."""
    engine = DeterministicRatingEngine(base_manual)
    bad_policy = {"policy_id": "ERR-02", "territory": "Metropolis"}  # Unsupported

    with pytest.raises(UnsupportedCategoryError) as exc_info:
        engine.calculate_policy(bad_policy)
    assert "Unsupported category 'Metropolis'" in str(exc_info.value)


def test_missing_policy_id_rejection(base_manual):
    """Verify that records missing policy identifiers are rejected."""
    engine = DeterministicRatingEngine(base_manual)
    bad_policy = {"territory": "Urban"}  # Missing policy_id

    with pytest.raises(InvalidPolicyIdentifierError) as exc_info:
        engine.calculate_policy(bad_policy)
    assert "Missing mandatory 'policy_id'" in str(exc_info.value)


def test_underwriting_ineligibility_handling(base_manual):
    """Verify that underwriting eligibility conditions mark policies as INELIGIBLE."""
    spec_dict = base_manual.model_dump()
    spec_dict["eligibility_rules"] = {
        "driver_age": [18, 90]  # Allowed age range
    }
    spec = RatingManualSpec(**spec_dict)
    engine = DeterministicRatingEngine(spec)

    ineligible_policy = {"policy_id": "INEL-01", "territory": "Urban", "driver_age": 16}
    res = engine.calculate_policy(ineligible_policy)

    assert res.is_ineligible is True
    assert res.premium == 0.0
    assert any("outside eligible range [18, 90]" in r for r in res.ineligibility_reasons)


def test_statutory_clamping_floor_and_ceiling(base_manual):
    """Verify that statutory minimum floor and maximum ceiling clamp calculated premiums."""
    spec_dict = base_manual.model_dump()
    spec_dict["min_premium"] = 400.00
    spec_dict["max_premium"] = 450.00
    spec = RatingManualSpec(**spec_dict)
    engine = DeterministicRatingEngine(spec)

    # Rural under manual v1: Base 400 * 0.8 + 25 = 345. Should clamp to 400.00.
    rural_policy = {"policy_id": "CLAMP-01", "territory": "Rural"}
    res_rural = engine.calculate_policy(rural_policy)
    assert res_rural.premium == 400.00
    assert res_rural.is_clamped is True

    # Urban under manual v1: Base 400 * 1.2 + 25 = 505. Should clamp to 450.00.
    urban_policy = {"policy_id": "CLAMP-02", "territory": "Urban"}
    res_urban = engine.calculate_policy(urban_policy)
    assert res_urban.premium == 450.00
    assert res_urban.is_clamped is True


def test_statutory_tax_calculation(base_manual):
    """Verify that statutory percentage tax applies accurately to taxable base."""
    spec_dict = base_manual.model_dump()
    spec_dict["tax_rate"] = 0.05  # 5% tax
    spec_dict["tax_base"] = TaxBaseType.TAXABLE_BASE
    spec_dict["fee_taxability"] = {"policy_fee": False}  # Fee is tax exempt
    spec = RatingManualSpec(**spec_dict)
    engine = DeterministicRatingEngine(spec)

    # Suburban policy: Base 400 * 1.0 = 400 (taxable). Fee 25 (exempt).
    # Tax = 400 * 0.05 = 20.00. Final = 400 + 25 + 20 = 445.00.
    policy = {"policy_id": "TAX-01", "territory": "Suburban"}
    res = engine.calculate_policy(policy)
    assert res.taxable_base == 400.00
    assert res.tax_amount == 20.00
    assert res.premium == 445.00
