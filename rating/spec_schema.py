"""
Pydantic Schemas for Rating Manual Specification.
Defines strict schema contracts for insurance rating rules, configurable pipelines,
statutory limits, and ISO 4217 currency standards.
"""

from enum import Enum
from typing import Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator
from rating.rounding_policy import RoundingMethod, get_currency_precision


class StepType(str, Enum):
    BASE_RATE = "BASE_RATE"
    MULTIPLICATIVE_FACTOR = "MULTIPLICATIVE_FACTOR"
    DISCOUNT_CREDIT = "DISCOUNT_CREDIT"
    ADDITIVE_FEE = "ADDITIVE_FEE"
    STATUTORY_CLAMPING = "STATUTORY_CLAMPING"
    STATUTORY_TAX = "STATUTORY_TAX"
    INTERMEDIATE_ROUNDING = "INTERMEDIATE_ROUNDING"
    FINAL_ROUNDING = "FINAL_ROUNDING"


class ClampStage(str, Enum):
    PRE_TAX = "PRE_TAX"
    POST_TAX = "POST_TAX"
    GROSS_FINAL = "GROSS_FINAL"


class TaxBaseType(str, Enum):
    TAXABLE_BASE = "TAXABLE_BASE"
    GROSS_PREMIUM = "GROSS_PREMIUM"


class PipelineStepConfig(BaseModel):
    step_type: StepType
    variable: Optional[str] = None
    fee_name: Optional[str] = None
    is_taxable: Optional[bool] = None
    is_taxable_deduction: Optional[bool] = None
    tax_rate: Optional[float] = None
    tax_base: Optional[TaxBaseType] = None
    min_premium: Optional[float] = None
    max_premium: Optional[float] = None
    clamp_stage: Optional[ClampStage] = None
    rule: Optional[RoundingMethod] = None
    precision: Optional[int] = None
    precision_source: Optional[str] = None


class RoundingRule(BaseModel):
    precision: Optional[int] = Field(None, ge=0, le=8, description="Explicit precision override")
    method: RoundingMethod = Field(RoundingMethod.ROUND_HALF_UP, description="Rounding convention")
    use_iso_minor_units: bool = Field(True, description="Whether to inherit ISO 4217 minor units")


class RatingManualSpec(BaseModel):
    manual_id: str = Field(..., description="Unique immutable rating manual identifier")
    name: str = Field(..., description="Descriptive title of the rating manual")
    version: str = Field(..., description="Semantic version string, e.g. 1.0.0")
    effective_date_start: str = Field("2025-01-01", description="Effective start date ISO YYYY-MM-DD")
    effective_date_end: Optional[str] = Field(None, description="Effective end date ISO YYYY-MM-DD")
    jurisdiction: str = Field("US-OH", description="Jurisdiction code e.g. US-OH, FR-MTPL, IN-MA")
    filing_reference: Optional[str] = Field(None, description="Regulatory filing ID e.g. SERFF")
    line_of_business: str = Field("Personal Auto", description="Insurance line of business")
    currency: str = Field("USD", description="Currency ISO 4217 code")
    currency_symbol: str = Field("$", description="Display currency symbol")
    currency_precision_override: Optional[int] = Field(None, ge=0, le=8)
    base_rate: float = Field(..., gt=0.0, description="Base unadjusted policy premium (> 0)")
    factor_tables: Dict[str, Dict[str, float]] = Field(
        default_factory=dict,
        description="Multiplicative rating factor tables keyed by rating variable"
    )
    discount_tables: Dict[str, Dict[str, float]] = Field(
        default_factory=dict,
        description="Multiplicative discount tables (< 1.00) or negative additive adjustments"
    )
    additive_fees: Dict[str, float] = Field(
        default_factory=dict,
        description="Additive expense surcharges and policy fees"
    )
    fee_taxability: Dict[str, bool] = Field(
        default_factory=dict,
        description="Taxability flag per additive fee (True = taxable, False = tax-exempt)"
    )
    min_premium: Optional[float] = Field(None, ge=0.0, description="Minimum policy premium statutory floor")
    max_premium: Optional[float] = Field(None, ge=0.0, description="Maximum policy premium regulatory ceiling")
    clamp_stage: ClampStage = Field(ClampStage.PRE_TAX, description="When statutory clamping applies")
    tax_rate: float = Field(0.0, ge=0.0, le=1.0, description="Statutory insurance premium tax rate")
    tax_base: TaxBaseType = Field(TaxBaseType.TAXABLE_BASE, description="Definition of tax base")
    rounding_rule: RoundingRule = Field(default_factory=RoundingRule)
    calculation_pipeline: Optional[List[PipelineStepConfig]] = Field(
        None,
        description="Explicit ordered calculation pipeline sequence"
    )
    eligibility_rules: Dict[str, List[Union[str, float, int]]] = Field(
        default_factory=dict,
        description="Underwriting eligibility criteria mapping field to allowed categories or numeric ranges"
    )

    @property
    def currency_precision(self) -> int:
        """Determines currency precision via ISO 4217 standard or explicit override."""
        if self.rounding_rule.precision is not None:
            return self.rounding_rule.precision
        return get_currency_precision(self.currency, self.currency_precision_override)

    @model_validator(mode="after")
    def validate_spec_coherence(self) -> "RatingManualSpec":
        # Validate min <= max if both present
        if self.min_premium is not None and self.max_premium is not None:
            if self.min_premium > self.max_premium:
                raise ValueError(f"min_premium ({self.min_premium}) cannot exceed max_premium ({self.max_premium})")

        # Validate positive factors in factor tables
        for var_name, table in self.factor_tables.items():
            for cat, factor in table.items():
                if factor <= 0.0:
                    raise ValueError(f"Factor '{var_name}[{cat}]' must be strictly positive (> 0), got {factor}")

        # Validate non-negative fees
        for fee_name, fee_val in self.additive_fees.items():
            if fee_val < 0.0:
                raise ValueError(f"Additive fee '{fee_name}' cannot be negative, got {fee_val}")

        # Synthesize or synchronize default pipeline if not explicitly customized
        if self.calculation_pipeline is None:
            self.calculation_pipeline = self._build_default_pipeline()
        else:
            # Clean up fee steps that no longer exist in additive_fees
            self.calculation_pipeline = [
                s for s in self.calculation_pipeline
                if not (s.step_type == StepType.ADDITIVE_FEE and s.fee_name not in self.additive_fees)
            ]
            has_clamping = any(s.step_type == StepType.STATUTORY_CLAMPING for s in self.calculation_pipeline)
            has_tax = any(s.step_type == StepType.STATUTORY_TAX for s in self.calculation_pipeline)

            # Insert clamping before final rounding if specified but missing
            if (self.min_premium is not None or self.max_premium is not None) and not has_clamping:
                insert_idx = len(self.calculation_pipeline) - 1 if self.calculation_pipeline and self.calculation_pipeline[-1].step_type == StepType.FINAL_ROUNDING else len(self.calculation_pipeline)
                self.calculation_pipeline.insert(insert_idx, PipelineStepConfig(
                    step_type=StepType.STATUTORY_CLAMPING,
                    min_premium=self.min_premium,
                    max_premium=self.max_premium,
                    clamp_stage=self.clamp_stage
                ))

            # Insert tax before final rounding if specified but missing
            if self.tax_rate > 0.0 and not has_tax:
                insert_idx = len(self.calculation_pipeline) - 1 if self.calculation_pipeline and self.calculation_pipeline[-1].step_type == StepType.FINAL_ROUNDING else len(self.calculation_pipeline)
                self.calculation_pipeline.insert(insert_idx, PipelineStepConfig(
                    step_type=StepType.STATUTORY_TAX,
                    tax_rate=self.tax_rate,
                    tax_base=self.tax_base
                ))

        return self

    def _build_default_pipeline(self) -> List[PipelineStepConfig]:
        steps: List[PipelineStepConfig] = [PipelineStepConfig(step_type=StepType.BASE_RATE)]
        for var_name in sorted(self.factor_tables.keys()):
            steps.append(PipelineStepConfig(step_type=StepType.MULTIPLICATIVE_FACTOR, variable=var_name))
        for var_name in sorted(self.discount_tables.keys()):
            steps.append(PipelineStepConfig(step_type=StepType.DISCOUNT_CREDIT, variable=var_name))
        for fee_name in sorted(self.additive_fees.keys()):
            is_tax = self.fee_taxability.get(fee_name, False)
            steps.append(PipelineStepConfig(step_type=StepType.ADDITIVE_FEE, fee_name=fee_name, is_taxable=is_tax))
        if self.min_premium is not None or self.max_premium is not None:
            steps.append(PipelineStepConfig(
                step_type=StepType.STATUTORY_CLAMPING,
                min_premium=self.min_premium,
                max_premium=self.max_premium,
                clamp_stage=self.clamp_stage
            ))
        if self.tax_rate > 0.0:
            steps.append(PipelineStepConfig(
                step_type=StepType.STATUTORY_TAX,
                tax_rate=self.tax_rate,
                tax_base=self.tax_base
            ))
        steps.append(PipelineStepConfig(
            step_type=StepType.FINAL_ROUNDING,
            rule=self.rounding_rule.method,
            precision=self.currency_precision
        ))
        return steps
