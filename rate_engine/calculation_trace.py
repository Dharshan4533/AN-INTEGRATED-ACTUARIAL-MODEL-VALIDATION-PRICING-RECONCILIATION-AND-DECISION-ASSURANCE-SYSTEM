"""
Calculation Trace Data Structures.
Records intermediate values, factors applied, fees, bounds, and rounding for transparent auditability.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class FactorApplicationTrace(BaseModel):
    variable_name: str
    selected_category: str
    factor_value: float
    running_subtotal: float


class FeeApplicationTrace(BaseModel):
    fee_name: str
    fee_amount: float
    running_subtotal: float


class StepTrace(BaseModel):
    step_number: int
    step_name: str
    operation: str
    value_in: float
    operand: Any
    value_out: float
    formula_description: str


class CalculationTrace(BaseModel):
    policy_id: str
    manual_id: str
    manual_version: str
    base_rate: float
    factors_applied: List[FactorApplicationTrace] = Field(default_factory=list)
    cumulative_factor: float
    subtotal_after_factors: float
    fees_applied: List[FeeApplicationTrace] = Field(default_factory=list)
    total_fees: float
    subtotal_after_fees: float
    clamped_by: Optional[str] = None
    subtotal_after_clamping: float
    unrounded_premium: float
    rounded_premium: float
    precision: int
    rounding_method: str
    steps: List[StepTrace] = Field(default_factory=list)
