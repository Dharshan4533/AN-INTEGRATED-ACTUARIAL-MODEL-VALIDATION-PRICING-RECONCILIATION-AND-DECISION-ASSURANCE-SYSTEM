"""
FastAPI REST API Integration Tests.
Verifies all endpoints, input validation, and expected responses.
"""

import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_health_check_endpoint():
    """Verify GET /api/v1/health returns 200 and model status."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["models_loaded"]["frequency_glm"] is True
    assert data["models_loaded"]["severity_glm"] is True


def test_system_config_endpoint():
    """Verify GET /api/v1/config returns valid categories, ranges, and assumptions."""
    response = client.get("/api/v1/config")
    assert response.status_code == 200
    data = response.json()
    assert "feature_ranges" in data
    assert "valid_categories" in data
    assert data["currency_base"] == "EUR"
    assert data["inr_conversion_rate"] == 90.00


def test_quote_generation_endpoint():
    """Verify POST /api/v1/quotes returns complete actuarial pricing breakdown."""
    payload = {
        "policy": {
            "VehPower": 6,
            "VehAge": 4,
            "DrivAge": 38,
            "BonusMalus": 50,
            "VehBrand": "B1",
            "VehGas": "Regular",
            "Area": "C",
            "Density": 600.0,
            "Region": "R24",
            "Exposure": 1.0,
            "convert_to_inr": False
        }
    }
    response = client.post("/api/v1/quotes", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["annualized_frequency"] > 0
    assert data["expected_severity"] > 0
    assert data["annual_pure_premium"] > 0
    assert data["total_commercial_premium"] > data["annual_pure_premium"]
    assert "risk_tier" in data
    assert "tier_name" in data["risk_tier"]


def test_quote_input_validation_rejection():
    """Verify that invalid inputs (e.g. driver age < 18 or invalid Area) are rejected with 422."""
    invalid_payload = {
        "policy": {
            "VehPower": 6,
            "VehAge": 4,
            "DrivAge": 15,  # Invalid: Driver age < 18
            "BonusMalus": 50,
            "VehBrand": "B1",
            "VehGas": "Regular",
            "Area": "Z",    # Invalid area
            "Density": 600.0,
            "Region": "R24",
            "Exposure": 1.0
        }
    }
    response = client.post("/api/v1/quotes", json=invalid_payload)
    assert response.status_code == 422


def test_policy_comparison_endpoint():
    """Verify POST /api/v1/quotes/compare compares multiple policy profiles."""
    payload = {
        "policies": [
            {
                "VehPower": 4,
                "VehAge": 10,
                "DrivAge": 55,
                "BonusMalus": 50,
                "VehBrand": "B1",
                "VehGas": "Regular",
                "Area": "A",
                "Density": 50.0,
                "Region": "R24",
                "Exposure": 1.0
            },
            {
                "VehPower": 12,
                "VehAge": 1,
                "DrivAge": 21,
                "BonusMalus": 120,
                "VehBrand": "B12",
                "VehGas": "Diesel",
                "Area": "E",
                "Density": 5000.0,
                "Region": "R11",
                "Exposure": 1.0
            }
        ]
    }
    response = client.post("/api/v1/quotes/compare", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert len(data["quotes"]) == 2
    assert "comparison_table" in data
    # High-risk profile 2 must have higher premium than low-risk profile 1
    assert data["comparison_table"][1]["total_commercial_premium"] > data["comparison_table"][0]["total_commercial_premium"]


def test_what_if_endpoint():
    """Verify POST /api/v1/quotes/what-if evaluates baseline vs revised policy."""
    payload = {
        "baseline_policy": {
            "VehPower": 6,
            "VehAge": 5,
            "DrivAge": 30,
            "BonusMalus": 80,
            "VehBrand": "B1",
            "VehGas": "Regular",
            "Area": "C",
            "Density": 500.0,
            "Region": "R24",
            "Exposure": 1.0
        },
        "revised_policy": {
            "VehPower": 6,
            "VehAge": 5,
            "DrivAge": 30,
            "BonusMalus": 50,  # Improved bonus-malus
            "VehBrand": "B1",
            "VehGas": "Regular",
            "Area": "C",
            "Density": 500.0,
            "Region": "R24",
            "Exposure": 1.0
        }
    }
    response = client.post("/api/v1/quotes/what-if", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "differences" in data
    # Lower bonus-malus should reduce frequency and premium
    assert data["differences"]["commercial_premium_abs_diff"] < 0


def test_portfolio_simulate_endpoint():
    """Verify POST /api/v1/portfolio/simulate returns loss simulation and risk measures."""
    payload = {
        "portfolio_source": "benchmark",
        "n_simulations": 1000,
        "random_seed": 42,
        "confidence_levels": [0.95, 0.99]
    }
    response = client.post("/api/v1/portfolio/simulate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["n_policies"] > 0
    assert data["expected_total_loss"] > 0
    assert len(data["risk_measures"]) == 2
    # VaR 99% must be greater than or equal to VaR 95%
    var_95 = data["risk_measures"][0]["var"]
    var_99 = data["risk_measures"][1]["var"]
    assert var_99 >= var_95
    # TVaR 99% must be >= VaR 99%
    tvar_99 = data["risk_measures"][1]["tvar"]
    assert tvar_99 >= var_99


def test_stress_test_endpoint():
    """Verify POST /api/v1/stress-test calculates capital strain."""
    payload = {
        "name": "Severe Adverse Frequency Shock",
        "frequency_multiplier": 1.25,
        "severity_multiplier": 1.10,
        "bonus_malus_shift": 10.0,
        "n_simulations": 1000,
        "random_seed": 42
    }
    response = client.post("/api/v1/stress-test", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["stressed_metrics"]["expected_loss"] > data["baseline_metrics"]["expected_loss"]
    assert data["absolute_impact"]["delta_var_99"] > 0


def test_model_validation_endpoint():
    """Verify GET /api/v1/model/validation returns real held-out metrics."""
    response = client.get("/api/v1/model/validation")
    assert response.status_code == 200
    data = response.json()
    assert "frequency_model" in data
    assert "severity_model" in data
    assert data["frequency_model"]["evaluation_metrics"]["test_oe_ratio"] > 0.95


def test_quote_inr_conversion():
    """Verify POST /api/v1/quotes with convert_to_inr=True scales values by benchmark rate 90.0."""
    policy_base = {
        "VehPower": 6, "VehAge": 4, "DrivAge": 38, "BonusMalus": 50,
        "VehBrand": "B1", "VehGas": "Regular", "Area": "C",
        "Density": 600.0, "Region": "R24", "Exposure": 1.0,
        "convert_to_inr": False
    }
    res_eur = client.post("/api/v1/quotes", json={"policy": policy_base}).json()
    res_inr = client.post("/api/v1/quotes", json={"policy": {**policy_base, "convert_to_inr": True}}).json()

    assert res_eur["currency"] == "EUR"
    assert res_inr["currency"] == "INR"
    assert res_inr["currency_symbol"] == "₹"
    assert abs(res_inr["total_commercial_premium"] - (res_eur["total_commercial_premium"] * 90.0)) < 1.0
    assert abs(res_inr["expected_severity"] - (res_eur["expected_severity"] * 90.0)) < 1.0


def test_reconciliation_inr_conversion():
    """Verify POST /api/v1/reconcile with convert_to_inr=True converts reconciliation outputs to INR."""
    p_a = {
        "VehPower": 6, "VehAge": 4, "DrivAge": 38, "BonusMalus": 50,
        "VehBrand": "B1", "VehGas": "Regular", "Area": "C",
        "Density": 600.0, "Region": "R24", "Exposure": 1.0,
        "convert_to_inr": True
    }
    p_b = {**p_a, "DrivAge": 22, "BonusMalus": 100}

    res = client.post("/api/v1/reconcile", json={"policy_a": p_a, "policy_b": p_b, "convert_to_inr": True})
    assert res.status_code == 200
    data = res.json()
    assert data["currency"] == "INR"
    assert data["currency_symbol"] == "₹"
    assert data["is_exact_reconciliation"] is True
    assert data["policy_a_total_premium"] > 1000.0
