"""
Pydantic Request and Response Schemas for Portfolio Loss Simulation and Stress Testing.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from backend.schemas.pricing_schema import PolicyInput


class PortfolioSimulateRequest(BaseModel):
    portfolio_source: str = Field("benchmark", description="Portfolio source: 'benchmark' or 'custom'")
    n_simulations: int = Field(5000, ge=500, le=20000, description="Monte Carlo simulation count (500 to 20,000)")
    random_seed: int = Field(42, description="Random seed for reproducible stochastic simulation")
    custom_policies: Optional[List[PolicyInput]] = Field(None, description="Optional custom list of policyholder profiles")
    confidence_levels: List[float] = Field([0.95, 0.99, 0.995], description="VaR / TVaR confidence levels")
    convert_to_inr: bool = Field(False, description="Convert output currency to INR")


class HistogramBin(BaseModel):
    bin_start: float
    bin_end: float
    frequency: int
    density: float


class RiskMeasureItem(BaseModel):
    confidence_level: float
    confidence_percent: str
    var: float
    tvar: float
    var_mcse: Optional[float] = None
    tvar_mcse: Optional[float] = None


class PortfolioSimulateResponse(BaseModel):
    n_policies: int
    total_exposure_years: float
    expected_claim_count: float
    expected_total_loss: float
    mean_simulated_loss: float
    std_simulated_loss: float
    loss_skewness: float
    risk_measures: List[RiskMeasureItem]
    loss_histogram: List[HistogramBin]
    simulation_count: int
    random_seed: int
    runtime_seconds: float
    currency: str
    currency_symbol: str
    assumptions_summary: str
    theoretical_expected_loss: Optional[float] = None
    theoretical_variance: Optional[float] = None
    moment_convergence_verified: Optional[bool] = None
    moment_z_score: Optional[float] = None


class StressTestScenarioInput(BaseModel):
    name: str = Field("Adverse Frequency & Severity Shock", description="Scenario descriptive name")
    frequency_multiplier: float = Field(1.15, ge=0.5, le=2.5, description="Factor applied to expected claim frequency (e.g., 1.15 = +15%)")
    severity_multiplier: float = Field(1.10, ge=0.5, le=2.5, description="Factor applied to expected severity (e.g., 1.10 = +10%)")
    bonus_malus_shift: float = Field(0.0, ge=-20.0, le=50.0, description="Average upward shift in BonusMalus scores across the portfolio")
    n_simulations: int = Field(3000, ge=500, le=10000, description="Simulation trials for stress evaluation")
    random_seed: int = Field(42, description="Random seed")
    convert_to_inr: bool = Field(False, description="Convert currency to INR")


class StressTestResponse(BaseModel):
    scenario_name: str
    n_policies: int
    baseline_metrics: Dict[str, float]
    stressed_metrics: Dict[str, float]
    absolute_impact: Dict[str, float]
    percentage_impact: Dict[str, float]
    capital_strain_summary: str
    currency: str
    currency_symbol: str
