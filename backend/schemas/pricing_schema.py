"""
Pydantic Request and Response Schemas for Actuarial Pricing and Policy Quotation.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator


class PolicyInput(BaseModel):
    VehPower: int = Field(6, ge=4, le=15, description="Vehicle Power group (4 to 15)")
    VehAge: int = Field(6, ge=0, le=100, description="Vehicle age in years (0 to 100)")
    DrivAge: int = Field(45, ge=18, le=100, description="Driver age in years (18 to 100)")
    BonusMalus: int = Field(50, ge=50, le=230, description="French statutory rating score (50 to 230)")
    VehBrand: str = Field("B1", description="Vehicle brand category (B1 to B14)")
    VehGas: str = Field("Regular", description="Fuel category ('Regular' or 'Diesel')")
    Area: str = Field("C", description="Geographic area code (A, B, C, D, E, F)")
    Density: float = Field(500.0, ge=1.0, le=30000.0, description="Population density in persons/km²")
    Region: str = Field("R24", description="French administrative region code (e.g. R24, R11, R82)")
    Exposure: float = Field(1.0, ge=0.01, le=2.0, description="Policy exposure duration in years (0.01 to 2.0)")
    convert_to_inr: bool = Field(False, description="Whether to display illustrative amounts in INR")

    @field_validator("VehGas")
    @classmethod
    def validate_vehgas(cls, v: str) -> str:
        valid = ["Regular", "Diesel"]
        if v not in valid:
            raise ValueError(f"VehGas must be one of {valid}")
        return v

    @field_validator("Area")
    @classmethod
    def validate_area(cls, v: str) -> str:
        valid = ["A", "B", "C", "D", "E", "F"]
        if v not in valid:
            raise ValueError(f"Area must be one of {valid}")
        return v


class PricingAssumptionsInput(BaseModel):
    fixed_expense: Optional[float] = Field(None, ge=0.0, le=500.0, description="Fixed expense per policy (EUR)")
    variable_expense_ratio: Optional[float] = Field(None, ge=0.0, le=0.50, description="Variable expense ratio (0.0 to 0.50)")
    risk_margin: Optional[float] = Field(None, ge=0.0, le=0.30, description="Cost of capital risk margin ratio (0.0 to 0.30)")
    profit_margin: Optional[float] = Field(None, ge=0.0, le=0.30, description="Underwriting target profit margin (0.0 to 0.30)")
    tax_rate: Optional[float] = Field(None, ge=0.0, le=0.50, description="Statutory insurance tax rate (0.0 to 0.50)")


class QuoteRequest(BaseModel):
    policy: PolicyInput
    custom_assumptions: Optional[PricingAssumptionsInput] = None


class QuoteResponse(BaseModel):
    policy: PolicyInput
    annualized_frequency: float
    expected_claim_count_term: float
    expected_severity: float
    annual_pure_premium: float
    term_expected_loss: float
    commercial_premium_before_tax: float
    statutory_tax: float
    total_commercial_premium: float
    pricing_breakdown: Dict[str, float]
    risk_tier: Dict[str, Any]
    key_risk_drivers: List[Dict[str, Any]]
    currency: str
    currency_symbol: str
    is_converted_currency: bool
    conversion_rate_used: Optional[float] = None
    data_disclaimer: str
    run_id: Optional[str] = None


class ComparisonRequest(BaseModel):
    policies: List[PolicyInput] = Field(..., min_length=2, max_length=5, description="List of 2 to 5 policyholder profiles")
    custom_assumptions: Optional[PricingAssumptionsInput] = None


class ComparisonResponse(BaseModel):
    quotes: List[QuoteResponse]
    comparison_table: List[Dict[str, Any]]
    lowest_premium_index: int
    highest_premium_index: int


class WhatIfRequest(BaseModel):
    baseline_policy: PolicyInput
    revised_policy: PolicyInput
    custom_assumptions: Optional[PricingAssumptionsInput] = None


class WhatIfResponse(BaseModel):
    baseline_quote: QuoteResponse
    revised_quote: QuoteResponse
    differences: Dict[str, Any]
