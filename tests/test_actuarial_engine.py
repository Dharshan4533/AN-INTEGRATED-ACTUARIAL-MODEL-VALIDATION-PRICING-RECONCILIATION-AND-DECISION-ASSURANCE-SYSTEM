"""
Actuarial and Pricing Engine Unit Tests.
Verifies mathematical formulas, exposure handling, risk classification,
and invalid assumption protections.
"""

import pytest
import numpy as np
from actuarial.pricing import ActuarialPricingEngine, DEFAULT_PRICING_ASSUMPTIONS
from actuarial.risk_tiering import RiskTierClassifier
from actuarial.preprocessing import ActuarialPreprocessor


def test_pure_premium_calculation():
    """Verify Annual Pure Premium = Frequency * Severity."""
    engine = ActuarialPricingEngine()
    freq = 0.08
    sev = 1500.0
    res = engine.calculate_pricing(freq, sev, exposure=1.0)
    
    expected_pure = freq * sev  # 120.0
    assert abs(res["pricing_breakdown"]["annual_pure_premium"] - expected_pure) < 1e-4


def test_exposure_handling_no_double_counting():
    """
    CRITICAL TEST: Ensure the expected-loss formula does NOT double-count exposure!
    - Annual Pure Premium must NOT scale with exposure.
    - Policy Term Expected Loss MUST scale linearly with exposure.
    """
    engine = ActuarialPricingEngine()
    freq = 0.10
    sev = 2000.0

    # Policy 1: Full year (Exposure = 1.0)
    res_1yr = engine.calculate_pricing(freq, sev, exposure=1.0)
    # Policy 2: Half year (Exposure = 0.5)
    res_half_yr = engine.calculate_pricing(freq, sev, exposure=0.5)

    # Annual pure premium must be identical regardless of policy term exposure!
    assert res_1yr["pricing_breakdown"]["annual_pure_premium"] == res_half_yr["pricing_breakdown"]["annual_pure_premium"]

    # Term expected loss for half-year must be exactly 50% of 1-year term expected loss
    loss_1yr = res_1yr["pricing_breakdown"]["term_expected_loss"]
    loss_half = res_half_yr["pricing_breakdown"]["term_expected_loss"]
    assert abs(loss_half - (loss_1yr * 0.5)) < 1e-4

    # Expected claim count for half year must be 0.10 * 0.5 = 0.05
    assert abs(res_half_yr["expected_claim_count_term"] - 0.05) < 1e-5


def test_commercial_premium_formula():
    """
    Verify Commercial Premium formula:
    Commercial Premium = (Expected Loss + Fixed Expense) / (1 - VarExp - RiskMargin - ProfitMargin)
    """
    assumptions = {
        "fixed_expense": 40.0,
        "variable_expense_ratio": 0.10,
        "risk_margin": 0.05,
        "profit_margin": 0.05,
        "tax_rate": 0.0  # Zero tax to check pre-tax premium
    }
    engine = ActuarialPricingEngine(assumptions)
    freq = 0.05
    sev = 1000.0
    exp = 1.0

    expected_loss = freq * sev * exp  # 50.0
    # Denominator: 1 - 0.10 - 0.05 - 0.05 = 0.80
    expected_commercial = (50.0 + 40.0) / 0.80  # 90.0 / 0.80 = 112.50

    res = engine.calculate_pricing(freq, sev, exp)
    assert abs(res["pricing_breakdown"]["commercial_premium_before_tax"] - expected_commercial) < 1e-4


def test_invalid_assumption_denominators_rejected():
    """Verify that variable loadings totaling >= 95% raise a ValueError."""
    invalid_assumptions = {
        "variable_expense_ratio": 0.50,
        "risk_margin": 0.30,
        "profit_margin": 0.25  # Total variable loadings = 1.05 -> Denominator = -0.05 <= 0
    }
    with pytest.raises(ValueError) as excinfo:
        ActuarialPricingEngine(invalid_assumptions)
    assert "Invalid pricing assumptions" in str(excinfo.value)


def test_negative_expense_rejected():
    """Verify negative fixed expense is rejected."""
    with pytest.raises(ValueError):
        ActuarialPricingEngine({"fixed_expense": -10.0})


def test_risk_tier_classification():
    """Verify deterministic risk tiering based on pure premium."""
    classifier = RiskTierClassifier()

    # Low tier (<= 35 EUR)
    low = classifier.classify(25.0)
    assert low["tier_name"] == "Low"
    assert low["badge_color"] == "green"

    # Moderate tier (35 - 75 EUR)
    mod = classifier.classify(55.0)
    assert mod["tier_name"] == "Moderate"
    assert mod["badge_color"] == "blue"

    # High tier (75 - 160 EUR)
    high = classifier.classify(120.0)
    assert high["tier_name"] == "High"
    assert high["badge_color"] == "orange"

    # Very High tier (> 160 EUR)
    vhigh = classifier.classify(220.0)
    assert vhigh["tier_name"] == "Very High"
    assert vhigh["badge_color"] == "red"


def test_preprocessor_design_matrix_consistency():
    """Verify preprocessor produces valid design matrix with constant term."""
    preprocessor = ActuarialPreprocessor.load("models/preprocessor.joblib")
    policy = {
        "VehPower": 6,
        "VehAge": 5,
        "DrivAge": 42,
        "BonusMalus": 50,
        "VehBrand": "B1",
        "VehGas": "Regular",
        "Area": "C",
        "Density": 500,
        "Region": "R24",
        "Exposure": 1.0
    }
    X = preprocessor.transform_single(policy)
    assert "const" in X.columns
    assert X["const"].iloc[0] == 1.0
    assert X.shape[1] == len(preprocessor.feature_columns)
    assert not X.isnull().values.any()
