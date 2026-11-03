"""
Controlled Experiments and Acceptance Verification Suite.
Validates the complete Actuarial Model Validation, Reconciliation, and Decision Assurance System:
1. Controlled Fault Injections in Data-Quality Gate
2. Reconciliation Exactness Across Multiple Policy Profiles
3. Replay Reproducibility within 10^-6 Tolerance
4. Non-Double-Counted Heavy-Tail Layering Identity
5. Heterogeneous Portfolio Simulation Compound Moment Convergence
6. Demographic and Neutral Territorial Calibration
7. Population Stability Index (PSI) Drift Detection
"""

import json
import os
import pytest
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas.pricing_schema import PolicyInput
from backend.schemas.portfolio_schema import PortfolioSimulateRequest
from backend.services.reconciliation_service import reconciliation_service
from backend.services.run_registry import run_registry
from backend.services.simulation_service import SimulationService
from backend.services.monitoring_service import monitoring_service
from actuarial.data_gate import DataQualityGate
from actuarial.heavy_tail import MeanExcessAnalyzer

client = TestClient(app)


def test_data_gate_controlled_fault_injections():
    """
    Controlled Fault Injection Test:
    Verify data-quality gate identifies injected anomalies and blocks execution.
    """
    gate = DataQualityGate()

    # Fault 1: Missing core feature
    df_missing = pd.DataFrame([{
        "Area": "C", "VehPower": 6, "VehAge": 6, "DrivAge": 45,
        # 'BonusMalus' omitted
        "VehBrand": "B1", "VehGas": "Regular", "Density": 500, "Region": "R24", "Exposure": 1.0
    }])
    rep1 = gate.validate_frequency_dataset(df_missing)
    assert rep1.status == "FAILED"
    assert rep1.is_prediction_ready is False
    assert any("SCHEMA_CONFORMITY" in f.rule_id for f in rep1.findings)

    # Fault 2: Negative exposure
    df_neg_exp = pd.DataFrame([{
        "Area": "C", "VehPower": 6, "VehAge": 6, "DrivAge": 45, "BonusMalus": 50,
        "VehBrand": "B1", "VehGas": "Regular", "Density": 500, "Region": "R24", "Exposure": -0.25
    }])
    rep2 = gate.validate_frequency_dataset(df_neg_exp)
    assert rep2.status == "FAILED"
    assert rep2.is_prediction_ready is False
    assert any("EXPOSURE_VALIDITY" in f.rule_id for f in rep2.findings)

    # Fault 3: Duplicate IDpol in policy dataset
    df_dups = pd.DataFrame([
        {"IDpol": 1001, "Area": "C", "VehPower": 6, "VehAge": 6, "DrivAge": 45, "BonusMalus": 50, "VehBrand": "B1", "VehGas": "Regular", "Density": 500, "Region": "R24", "Exposure": 1.0},
        {"IDpol": 1001, "Area": "C", "VehPower": 6, "VehAge": 6, "DrivAge": 45, "BonusMalus": 50, "VehBrand": "B1", "VehGas": "Regular", "Density": 500, "Region": "R24", "Exposure": 0.5}
    ])
    rep3 = gate.validate_frequency_dataset(df_dups)
    assert rep3.status == "FAILED"
    assert any("IDPOL_UNIQUENESS" in f.rule_id for f in rep3.findings)

    # Fault 4: Non-positive claim in severity
    df_sev_bad = pd.DataFrame([
        {"IDpol": 1001, "ClaimAmount": -500.0},
        {"IDpol": 1002, "ClaimAmount": 0.0}
    ])
    rep4 = gate.validate_severity_dataset(df_sev_bad)
    assert rep4.status == "FAILED"
    assert any("CLAIM_AMOUNT" in f.rule_id for f in rep4.findings)


def test_reconciliation_exactness_across_multiple_pairs():
    """
    Verify exact reconciliation Delta P = P_B - P_A == sum(Delta P_k) <= 10^-4
    across multiple distinct policyholder profiles and model combinations.
    """
    pairs = [
        # Pair 1: Prime vs Youth
        (
            PolicyInput(Area="C", VehPower=6, VehAge=6, DrivAge=45, BonusMalus=50, VehBrand="B1", VehGas="Regular", Density=500, Region="R24", Exposure=1.0),
            PolicyInput(Area="E", VehPower=9, VehAge=2, DrivAge=22, BonusMalus=100, VehBrand="B12", VehGas="Diesel", Density=4500, Region="R11", Exposure=0.75),
            "poisson", "nb2"
        ),
        # Pair 2: Low power rural vs High power urban
        (
            PolicyInput(Area="A", VehPower=4, VehAge=12, DrivAge=55, BonusMalus=50, VehBrand="B1", VehGas="Regular", Density=20, Region="R24", Exposure=1.0),
            PolicyInput(Area="F", VehPower=14, VehAge=1, DrivAge=35, BonusMalus=80, VehBrand="B14", VehGas="Diesel", Density=15000, Region="R11", Exposure=1.0),
            "poisson", "poisson"
        ),
        # Pair 3: Term scaling test (Exposure 1.5 yrs vs 0.25 yrs)
        (
            PolicyInput(Area="B", VehPower=7, VehAge=4, DrivAge=40, BonusMalus=60, VehBrand="B3", VehGas="Regular", Density=300, Region="R24", Exposure=1.5),
            PolicyInput(Area="B", VehPower=7, VehAge=4, DrivAge=40, BonusMalus=60, VehBrand="B3", VehGas="Regular", Density=300, Region="R24", Exposure=0.25),
            "nb2", "poisson"
        )
    ]

    for p_a, p_b, m_a, m_b in pairs:
        res = reconciliation_service.reconcile_policies(
            policy_a=p_a,
            policy_b=p_b,
            model_family_a=m_a,
            model_family_b=m_b
        )
        assert res.is_exact_reconciliation is True
        assert res.reconciliation_error <= 1e-4

        # Verify sum of steps matches rounded difference within display rounding
        step_sum = sum(s.dollar_impact for s in res.sequential_steps)
        assert abs(step_sum - res.total_difference) <= 0.05


def test_replay_reproducibility_1e6_tolerance():
    """
    Replay Reproducibility Test:
    Replaying an execution run must match stored unrounded premium difference within 10^-6.
    """
    p_a = PolicyInput(Area="A", VehPower=5, VehAge=8, DrivAge=50, BonusMalus=50, VehBrand="B1", VehGas="Regular", Density=80, Region="R24", Exposure=1.0)
    p_b = PolicyInput(Area="D", VehPower=8, VehAge=3, DrivAge=28, BonusMalus=70, VehBrand="B5", VehGas="Diesel", Density=1200, Region="R11", Exposure=0.5)

    recon = reconciliation_service.reconcile_policies(p_a, p_b)
    replay = run_registry.replay_run(recon.run_id)

    assert replay["is_reproducible"] is True
    assert replay["absolute_difference"] <= 1e-6
    assert replay["current_checksums_match"] is True


def test_heavy_tail_layering_non_double_counting():
    """
    Verify exact non-double counting identity:
    Total Claim Dollars == Attritional Layer (Y <= u) + Large Loss Layer (Y > u).
    """
    claims = np.array([150.0, 850.0, 2400.0, 15000.0, 35000.0, 85000.0, 450000.0])
    exposure = 1000.0
    analyzer = MeanExcessAnalyzer(candidate_thresholds=[10000.0, 30000.0, 50000.0])
    analyzer.fit(claims=claims, total_portfolio_exposure=exposure)

    u_star = analyzer.selected_threshold_
    raw_total = np.sum(claims)
    attritional_total = np.sum(np.minimum(claims, u_star))
    excess_total = np.sum(np.maximum(0.0, claims - u_star))

    assert abs(raw_total - (attritional_total + excess_total)) < 1e-6
    assert analyzer.results_["is_exact_decomposition"] is True
    assert analyzer.results_["reconciliation_leakage_eur"] == 0.0


def test_heterogeneous_portfolio_simulation_moment_convergence():
    """
    Verify portfolio simulation uses heterogeneous individual policy severity sampling
    and converges to theoretical compound Poisson-Gamma moments within 2.58 SEs.
    """
    sim_svc = SimulationService()
    req = PortfolioSimulateRequest(
        n_simulations=5000,
        random_seed=42,
        confidence_levels=[0.95, 0.99, 0.995]
    )
    res = sim_svc.simulate_portfolio(req)

    # 1. Moment convergence
    assert res.moment_convergence_verified is True
    assert res.moment_z_score <= 2.58

    # 2. Risk measures and MCSE
    assert len(res.risk_measures) == 3
    for rm in res.risk_measures:
        assert rm.var > 0.0
        assert rm.tvar >= rm.var
        assert rm.var_mcse is not None and rm.var_mcse > 0.0
        assert rm.tvar_mcse is not None and rm.tvar_mcse > 0.0


def test_fairness_audit_neutral_territories():
    """
    Verify fairness audit uses neutral geographic territorial codes (Area A-F)
    and reports sample sizes and 95% confidence intervals.
    """
    fairness_path = "models/fairness_audit_report.json"
    assert os.path.exists(fairness_path)

    with open(fairness_path, "r") as f:
        data = json.load(f)

    # 1. Demographic cohorts
    age_cohorts = data["demographic_cohort_audit"]["segments"]
    assert len(age_cohorts) >= 4
    for seg in age_cohorts:
        assert "policy_count" in seg
        assert "exposure_years" in seg
        assert "oe_ci_95" in seg
        assert seg["exposure_years"] > 0

    # 2. Neutral territorial codes (Area A through F)
    areas = data["geographic_territory_audit"]["segments"]
    assert len(areas) == 6
    area_names = [a["segment_name"] for a in areas]
    assert any("Area A" in name for name in area_names)
    assert any("Area F" in name for name in area_names)
    # Confirm no unsupported "rural" or "urban" labeling
    assert "rural" not in json.dumps(data["geographic_territory_audit"]).lower()
    assert "urban" not in json.dumps(data["geographic_territory_audit"]).lower()


def test_drift_monitoring_psi_thresholds():
    """
    Verify PSI calculation:
    - Identical distributions yield PSI < 0.10 (STABLE)
    - Shifted distribution yields PSI >= 0.25 (SIGNIFICANT_DRIFT)
    """
    np.random.seed(42)
    baseline = np.random.normal(loc=45.0, scale=12.0, size=5000)
    identical = np.random.normal(loc=45.0, scale=12.0, size=2000)
    shifted = np.random.normal(loc=22.0, scale=4.0, size=2000)  # Extreme shift to young drivers

    psi_stable = monitoring_service.compute_numerical_psi(baseline, identical)
    assert psi_stable < 0.10

    psi_shifted = monitoring_service.compute_numerical_psi(baseline, shifted)
    assert psi_shifted >= 0.25
