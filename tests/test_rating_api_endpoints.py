"""
Test Suite for Rating API Endpoints.
Verifies REST contracts for manual validation, version comparison, policy rate change,
portfolio reconciliation, and dual independent verification.
"""

import json
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from rating.spec_loader import load_rating_manual

client = TestClient(app)


@pytest.fixture
def sample_payloads():
    old_spec, _ = load_rating_manual("rating_specs/manual_v1_old.json")
    new_spec, _ = load_rating_manual("rating_specs/manual_v2_new.json")
    with open("sample_data/policies_5_sample.json", "r", encoding="utf-8") as f:
        census = json.load(f)
    return {
        "old_manual": old_spec.model_dump(),
        "new_manual": new_spec.model_dump(),
        "census": census,
        "single_policy": census[0]
    }


def test_rating_manual_validate_endpoint(sample_payloads):
    """Test POST /api/v1/rating-manuals/validate returns canonical SHA-256."""
    res = client.post("/api/v1/rating-manuals/validate", json=sample_payloads["old_manual"])
    assert res.status_code == 200
    data = res.json()
    assert data["is_valid"] is True
    assert data["manual_id"] == "manual_v1_old"
    assert len(data["canonical_sha256"]) == 64


def test_rating_manual_compare_endpoint(sample_payloads):
    """Test POST /api/v1/rating-manuals/compare produces rule diffs."""
    payload = {
        "old_manual": sample_payloads["old_manual"],
        "new_manual": sample_payloads["new_manual"]
    }
    res = client.post("/api/v1/rating-manuals/compare", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["old_manual_id"] == "manual_v1_old"
    assert data["new_manual_id"] == "manual_v2_new"
    assert data["base_rate_change_dollar"] == 40.0
    assert len(data["rule_changes"]) > 0


def test_rating_manual_samples_endpoint():
    """Test GET /api/v1/rating-manuals/samples returns pre-packaged specs."""
    res = client.get("/api/v1/rating-manuals/samples")
    assert res.status_code == 200
    data = res.json()
    assert "old_manual" in data
    assert "new_manual" in data


def test_rate_change_evaluate_policy_endpoint(sample_payloads):
    """Test POST /api/v1/rate-change/evaluate-policy performs stepwise attribution."""
    payload = {
        "old_manual": sample_payloads["old_manual"],
        "new_manual": sample_payloads["new_manual"],
        "policy": sample_payloads["single_policy"]
    }
    res = client.post("/api/v1/rate-change/evaluate-policy", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["policy_id"] == "POL-001"
    assert data["old_premium"] == 505.00
    assert data["new_premium"] == 602.00
    assert data["absolute_change"] == 97.00
    assert data["is_exact_reconciliation"] is True
    assert data["attribution_residual"] == 0.00


def test_rate_change_reconcile_portfolio_endpoint(sample_payloads):
    """Test POST /api/v1/rate-change/reconcile-portfolio reconciles full census."""
    payload = {
        "old_manual": sample_payloads["old_manual"],
        "new_manual": sample_payloads["new_manual"],
        "census": sample_payloads["census"]
    }
    res = client.post("/api/v1/rate-change/reconcile-portfolio", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["is_aggregate_reconciled"] is True
    assert data["total_valid_policies"] == 5
    assert data["aggregate_dollar_change"] == 269.00
    assert data["aggregate_percentage_change"] == 12.66
    assert data["aggregate_reconciliation_residual"] == 0.00


def test_rate_change_sample_census_endpoint():
    """Test GET /api/v1/rate-change/sample-census returns 5 benchmark policies."""
    res = client.get("/api/v1/rate-change/sample-census")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 5
    assert data[0]["policy_id"] == "POL-001"


def test_verification_policy_endpoint(sample_payloads):
    """Test POST /api/v1/verification/verify-policy evaluates dual calculator agreement."""
    payload = {
        "manual": sample_payloads["new_manual"],
        "policy": sample_payloads["single_policy"]
    }
    res = client.post("/api/v1/verification/verify-policy", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["is_verified"] is True
    assert data["discrepancy"] == 0.00


def test_verification_census_endpoint(sample_payloads):
    """Test POST /api/v1/verification/verify-census evaluates batch dual verification."""
    payload = {
        "manual": sample_payloads["new_manual"],
        "census": sample_payloads["census"]
    }
    res = client.post("/api/v1/verification/verify-census", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["is_100_percent_verified"] is True
    assert data["total_policies_checked"] == 5
    assert data["total_passed"] == 5
    assert data["max_monetary_discrepancy"] == 0.00


def test_rate_change_generate_report_endpoint(sample_payloads):
    """Test POST /api/v1/rate-change/generate-report creates full assurance memo."""
    payload = {
        "old_manual": sample_payloads["old_manual"],
        "new_manual": sample_payloads["new_manual"],
        "census": sample_payloads["census"],
        "output_format": "markdown",
        "record_in_ledger": True
    }
    res = client.post("/api/v1/rate-change/generate-report", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert data["is_aggregate_reconciled"] is True
    assert data["verification_passed"] is True
    assert "# Rate Change Assurance" in data["report"]
    assert "audit_trail" in data
    assert len(data["audit_trail"]["replay_token"]) == 64
    assert len(data["audit_trail"]["entry_hash"]) == 64


def test_rate_change_audit_ledger_status_endpoint():
    """Test GET /api/v1/rate-change/audit-ledger/status checks cryptographic integrity."""
    res = client.get("/api/v1/rate-change/audit-ledger/status")
    assert res.status_code == 200
    data = res.json()
    assert data["is_valid"] is True
    assert data["tamper_detected"] is False
    assert "genesis_hash" in data

