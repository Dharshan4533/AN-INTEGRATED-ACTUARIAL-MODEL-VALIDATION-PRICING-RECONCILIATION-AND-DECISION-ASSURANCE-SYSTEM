"""
Pydantic Schemas for Rating Manual Specification.
Defines strict schema contracts for insurance rating rules.
"""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class RoundingMethod(str, Enum):
    ROUND_HALF_UP = "ROUND_HALF_UP"
    ROUND_HALF_EVEN = "ROUND_HALF_EVEN"
    ROUND_CEILING = "ROUND_CEILING"
    ROUND_FLOOR = "ROUND_FLOOR"


class RoundingRule(BaseModel):
    precision: int = Field(2, ge=0, le=6, description="Decimal places to round (default 2)")
    method: RoundingMethod = Field(RoundingMethod.ROUND_HALF_UP, description="Rounding convention")


class CalculationPipelineStep(str, Enum):
    BASE_RATE = "base_rate"
    MULTIPLICATIVE_FACTORS = "multiplicative_factors"
    ADDITIVE_FEES = "additive_fees"
    MIN_MAX_CLAMPING = "min_max_clamping"
    ROUNDING = "rounding"


class RatingManualSpec(BaseModel):
    manual_id: str = Field(..., description="Unique immutable rating manual identifier")
    name: str = Field(..., description="Descriptive title of the rating manual")
    version: str = Field(..., description="Semantic version string, e.g. 1.0.0")
    effective_date: str = Field(..., description="Effective date ISO format YYYY-MM-DD")
    line_of_business: str = Field("Personal Auto", description="Insurance line of business")
    currency: str = Field("USD", description="Currency ISO 4217 code")
    currency_symbol: str = Field("$", description="Display currency symbol")
    base_rate: float = Field(..., gt=0.0, description="Base unadjusted policy premium (must be > 0)")
    factor_tables: Dict[str, Dict[str, float]] = Field(
        default_factory=dict,
        description="Multiplicative rating factor tables keyed by rating variable"
    )
    additive_fees: Dict[str, float] = Field(
        default_factory=dict,
        description="Additive expense surcharges and policy fees"
    )
    min_premium: Optional[float] = Field(None, ge=0.0, description="Minimum policy premium statutory floor")
    max_premium: Optional[float] = Field(None, ge=0.0, description="Maximum policy premium regulatory ceiling")
    rounding_rule: RoundingRule = Field(default_factory=RoundingRule)
    calculation_order: List[CalculationPipelineStep] = Field(
        default=[
            CalculationPipelineStep.BASE_RATE,
            CalculationPipelineStep.MULTIPLICATIVE_FACTORS,
            CalculationPipelineStep.ADDITIVE_FEES,
            CalculationPipelineStep.MIN_MAX_CLAMPING,
            CalculationPipelineStep.ROUNDING,
        ],
        description="Ordered sequence of calculation execution"
    )

    @field_validator("factor_tables")
    @classmethod
    def validate_factor_tables(cls, v: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, float]]:
        for var_name, table in v.items():
            if not table:
                raise ValueError(f"Factor table '{var_name}' cannot be empty.")
            for category, factor in table.items():
                if factor <= 0.0:
                    raise ValueError(f"Factor for '{var_name}:{category}' must be > 0.0, got {factor}.")
        return v

    @field_validator("additive_fees")
    @classmethod
    def validate_additive_fees(cls, v: Dict[str, float]) -> Dict[str, float]:
        for fee_name, amount in v.items():
            if amount < 0.0:
                raise ValueError(f"Additive fee '{fee_name}' cannot be negative, got {amount}.")
        return v

    @field_validator("max_premium")
    @classmethod
    def validate_min_max(cls, v: Optional[float], info) -> Optional[float]:
        min_p = info.data.get("min_premium")
        if v is not None and min_p is not None and v < min_p:
            raise ValueError(f"max_premium ({v}) cannot be less than min_premium ({min_p}).")
        return v
