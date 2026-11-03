"""
Step-by-Step Calculation Trace Recorder.
Captures intermediate unrounded linear predictors, applied factors, fee adjustments,
and statutory clamping steps for every rated policy.
"""

from typing import Any, List, Optional
from pydantic import BaseModel, Field


class TraceStep(BaseModel):
    step_number: int
    step_type: str
    rule_name: str
    input_value: Optional[Any] = None
    factor_or_rate: Optional[float] = None
    starting_amount: float
    ending_amount: float
    dollar_delta: float
    description: str


class CalculationTrace(BaseModel):
    policy_id: str
    manual_id: str
    manual_version: str
    currency: str
    currency_precision: int
    steps: List[TraceStep] = Field(default_factory=list)
    unrounded_final_premium: float
    final_quantized_premium: float
    is_ineligible: bool = False
    ineligibility_reasons: List[str] = Field(default_factory=list)

    def add_step(
        self,
        step_number: int,
        step_type: str,
        rule_name: str,
        starting_amount: float,
        ending_amount: float,
        description: str,
        input_value: Optional[Any] = None,
        factor_or_rate: Optional[float] = None
    ) -> None:
        delta = round(ending_amount - starting_amount, 6)
        self.steps.append(TraceStep(
            step_number=step_number,
            step_type=step_type,
            rule_name=rule_name,
            input_value=input_value,
            factor_or_rate=factor_or_rate,
            starting_amount=round(starting_amount, 6),
            ending_amount=round(ending_amount, 6),
            dollar_delta=delta,
            description=description
        ))
