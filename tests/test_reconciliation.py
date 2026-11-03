"""
Tests for Premium Reconciliation Engine, Run Registry, and Data-Quality Gate.
Verifies exact 5-step attribution identity, replay reproducibility (10^-6), and data-quality rules.
"""

import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.schemas.pricing_schema import PolicyInput
from backend.services.reconciliation_service import reconciliation_service
from backend.services.run_registry import run_registry
from actuarial.data_gate import DataQualityGate

client = TestClient(app)


@pytest.fixture
def policy_a():
    return PolicyInput(
        Area="A",
        VehPower=5,
        VehAge=8,
        DrivAge=50,
        BonusMalus=50,
        VehBrand="B1",
        VehGas="Regular",
        Density=80.0,
        Region="R24",
        Exposure=1.0
    )


@pytest.fixture
def policy_b():
    return PolicyInput(
        Area="E",
        VehPower=9,
        VehAge=2,
        DrivAge=22,
        BonusMalus=100,
        VehBrand="B12",
        VehGas="Diesel",
        Density=4500.0,
        Region="R11",
        Exposure=0.5
    )


def test_reconciliation_exactness_identity(policy_a, policy_b):
    """
    Core Actuarial Requirement:
    Delta P = P_B - P_A must equal the sum of sequential deltas within epsilon = 10^-4.
    """
    response = reconciliation_service.reconcile_policies(
        policy_a=policy_a,
        policy_b=policy_b,
        assumptions_a={"fixed_expense": 30.0, "tax_rate": 0.18},
        assumptions_b={"fixed_expense": 45.0, "tax_rate": 0.20},
        model_family_a="poisson",
        model_family_b="nb2"
    )

    assert response.is_exact_reconciliation is True
    assert response.reconciliation_error <= 1e-4

    sum_steps = sum(step.dollar_impact for step in response.sequential_steps)
    # The sum of rounded step impacts should equal total difference within display rounding (0.05 EUR)
    assert abs(sum_steps - response.total_difference) <= 0.05
    assert len(response.sequential_steps) == 5
    assert response.run_id.startswith("run_")


def test_reconciliation_order_sensitivity(policy_a, policy_b):
    """
    Verify path-order sensitivity analysis reports step magnitudes under alternative orders.
    """
    response = reconciliation_service.reconcile_policies(
        policy_a=policy_a,
        policy_b=policy_b
    )

    sensitivity = response.order_sensitivity_analysis
    assert "forward_sequence" in sensitivity
    assert "reverse_sequence" in sensitivity
    assert "max_step_divergence" in sensitivity
    assert sensitivity["max_step_divergence"] >= 0.0


def test_run_registry_replay_reproducibility(policy_a, policy_b):
    """
    Replay Reproducibility Test:
    Given a recorded Run ID, replay must recreate the stored premium within epsilon = 10^-6.
    """
    recon_res = reconciliation_service.reconcile_policies(
        policy_a=policy_a,
        policy_b=policy_b
    )
    run_id = recon_res.run_id

    # Verify run dossier retrieval
    run_record = run_registry.get_run(run_id)
    assert run_record is not None
    assert run_record["run_id"] == run_id
    assert "artifact_checksums" in run_record
    assert "unrounded_calculation_trace" in run_record

    # Verify replay endpoint
    replay_result = run_registry.replay_run(run_id)
    assert replay_result["is_reproducible"] is True
    assert replay_result["absolute_difference"] <= 1e-6


def test_reconciliation_api_endpoints(policy_a, policy_b):
    """Verify HTTP endpoints for reconcile, runs list, get run, and replay."""
    payload = {
        "policy_a": policy_a.model_dump(),
        "policy_b": policy_b.model_dump(),
        "model_family_a": "poisson",
        "model_family_b": "nb2",
        "user_notes": "Automated regression test"
    }

    # 1. POST /api/v1/reconcile
    res = client.post("/api/v1/reconcile", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["is_exact_reconciliation"] is True
    assert len(data["sequential_steps"]) == 5
    run_id = data["run_id"]

    # 2. GET /api/v1/runs
    res_list = client.get("/api/v1/runs?limit=10")
    assert res_list.status_code == 200
    assert any(r["run_id"] == run_id for r in res_list.json()["runs"])

    # 3. GET /api/v1/runs/{run_id}
    res_get = client.get(f"/api/v1/runs/{run_id}")
    assert res_get.status_code == 200
    assert res_get.json()["run_id"] == run_id

    # 4. POST /api/v1/runs/{run_id}/replay
    res_replay = client.post(f"/api/v1/runs/{run_id}/replay")
    assert res_replay.status_code == 200
    assert res_replay.json()["is_reproducible"] is True
    assert res_replay.json()["absolute_difference"] <= 1e-6


def test_data_gate_fault_injection():
    """Controlled fault injection test for the 10 data-quality rules."""
    gate = DataQualityGate()

    # Fault 1: Invalid Exposure (<= 0)
    p_bad_exp = {
        "Area": "C", "VehPower": 6, "VehAge": 5, "DrivAge": 40, "BonusMalus": 50,
        "VehBrand": "B1", "VehGas": "Regular", "Density": 250, "Region": "R24", "Exposure": -0.1
    }
    rep1 = gate.validate_policy(p_bad_exp)
    assert rep1.status == "FAILED"
    assert rep1.is_prediction_ready is False
    assert any("EXPOSURE" in f.rule_id for f in rep1.findings)

    # Fault 2: Out of range Driver Age (age 14 < 18)
    p_bad_age = {
        "Area": "C", "VehPower": 6, "VehAge": 5, "DrivAge": 14, "BonusMalus": 50,
        "VehBrand": "B1", "VehGas": "Regular", "Density": 250, "Region": "R24", "Exposure": 1.0
    }
    rep2 = gate.validate_policy(p_bad_age)
    assert rep2.status == "FAILED"
    assert any("DRIVAGE" in f.rule_id for f in rep2.findings)

    # Fault 3: Unseen categorical level
    p_unseen = {
        "Area": "UNKNOWN_AREA", "VehPower": 6, "VehAge": 5, "DrivAge": 40, "BonusMalus": 50,
        "VehBrand": "B1", "VehGas": "Regular", "Density": 250, "Region": "R24", "Exposure": 1.0
    }
    rep3 = gate.validate_policy(p_unseen)
    assert any("AREA" in f.rule_id for f in rep3.findings)
