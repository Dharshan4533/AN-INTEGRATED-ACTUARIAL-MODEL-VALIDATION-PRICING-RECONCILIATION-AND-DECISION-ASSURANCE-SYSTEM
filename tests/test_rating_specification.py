"""
Test Suite for Rating Manual Specification & Loader.
Validates Pydantic schema validation, ISO 4217 minor-unit precision, canonical JCS checksums,
and spec diffing.
"""

import json
import pytest
from rating.spec_schema import RatingManualSpec, RoundingRule, RoundingMethod, StepType
from rating.spec_loader import load_rating_manual, compute_spec_hash, canonical_json_dumps
from rating.rounding_policy import get_currency_precision, quantize_currency
from backend.services.rating_manual_service import RatingManualService


def test_iso_4217_currency_precision_lookup():
    """Verify ISO 4217 minor units are looked up accurately."""
    assert get_currency_precision("USD") == 2
    assert get_currency_precision("EUR") == 2
    assert get_currency_precision("GBP") == 2
    assert get_currency_precision("INR") == 2
    assert get_currency_precision("JPY") == 0
    assert get_currency_precision("KRW") == 0
    assert get_currency_precision("KWD") == 3
    assert get_currency_precision("BHD") == 3
    # Explicit override takes priority
    assert get_currency_precision("USD", override=4) == 4


def test_rfc_8785_canonical_json_dumps():
    """Verify deterministic key sorting and minimal whitespace."""
    obj1 = {"b": 2, "a": 1, "nested": {"z": 9, "y": 8}}
    obj2 = {"nested": {"y": 8, "z": 9}, "a": 1, "b": 2}
    assert canonical_json_dumps(obj1) == canonical_json_dumps(obj2)
    assert canonical_json_dumps(obj1) == '{"a":1,"b":2,"nested":{"y":8,"z":9}}'


def test_spec_hash_determinism_and_drift():
    """Verify that hashing a spec is strictly deterministic and detects any mutation."""
    spec, hash1 = load_rating_manual("rating_specs/manual_v1_old.json")
    _, hash2 = load_rating_manual("rating_specs/manual_v1_old.json")
    assert hash1 == hash2

    # Mutate a factor
    mutated_dict = spec.model_dump()
    mutated_dict["factor_tables"]["territory"]["Urban"] = 1.25
    hash_mutated = compute_spec_hash(mutated_dict)
    assert hash1 != hash_mutated


def test_invalid_spec_denominators_rejected():
    """Verify invalid bounds (min > max) or non-positive base rates are rejected."""
    base_dict = {
        "manual_id": "TEST-SPEC",
        "name": "Test Spec",
        "version": "1.0.0",
        "base_rate": 500.0,
        "currency": "USD"
    }
    # Base rate <= 0 rejected
    with pytest.raises(ValueError):
        RatingManualSpec(**{**base_dict, "base_rate": 0.0})

    # min_premium > max_premium rejected
    with pytest.raises(ValueError):
        RatingManualSpec(**{**base_dict, "min_premium": 600.0, "max_premium": 400.0})


def test_manual_service_diffing():
    """Verify semantic rule diffing identifies modified base rate, factor tables, and fees."""
    old_spec, _ = load_rating_manual("rating_specs/manual_v1_old.json")
    new_spec, _ = load_rating_manual("rating_specs/manual_v2_new.json")

    diff = RatingManualService.compare_manuals(old_spec, new_spec)
    assert diff.old_manual_id == "manual_v1_old"
    assert diff.new_manual_id == "manual_v2_new"
    assert diff.base_rate_change_dollar == 40.0
    assert diff.base_rate_change_pct == 10.0

    change_names = [c.component_name for c in diff.rule_changes]
    assert "base_rate" in change_names
    assert "territory[Urban]" in change_names
    assert "territory[Rural]" in change_names
    assert "policy_fee" in change_names
