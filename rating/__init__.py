"""
Rating Package.
Provides deterministic insurance rating, configurable pipelines, independent Decimal verification,
calculation traces, rule validation, and ISO 4217 currency quantization.
"""

from rating.rounding_policy import (
    RoundingMethod,
    get_currency_precision,
    quantize_currency,
    ISO_4217_MINOR_UNITS
)
from rating.spec_schema import (
    RatingManualSpec,
    RoundingRule,
    StepType,
    ClampStage,
    TaxBaseType,
    PipelineStepConfig
)
from rating.spec_loader import (
    load_rating_manual,
    compute_spec_hash,
    validate_spec_checksum,
    canonical_json_dumps
)
from rating.rule_validator import (
    RatingRuleValidator,
    RatingRuleValidationError,
    MissingRatingVariableError,
    UnsupportedCategoryError,
    InvalidPolicyIdentifierError,
    IneligiblePolicyError,
    PolicyValidationResult,
    CensusValidationSummary
)
from rating.calculation_trace import (
    CalculationTrace,
    TraceStep
)
from rating.rating_engine import (
    DeterministicRatingEngine,
    RatingCalculationError,
    UnsupportedRatingRuleError,
    PolicyRatingResult
)
from rating.independent_calculator import (
    IndependentCalculator,
    VerificationResult
)

__all__ = [
    "RoundingMethod",
    "get_currency_precision",
    "quantize_currency",
    "ISO_4217_MINOR_UNITS",
    "RatingManualSpec",
    "RoundingRule",
    "StepType",
    "ClampStage",
    "TaxBaseType",
    "PipelineStepConfig",
    "load_rating_manual",
    "compute_spec_hash",
    "validate_spec_checksum",
    "canonical_json_dumps",
    "RatingRuleValidator",
    "RatingRuleValidationError",
    "MissingRatingVariableError",
    "UnsupportedCategoryError",
    "InvalidPolicyIdentifierError",
    "IneligiblePolicyError",
    "PolicyValidationResult",
    "CensusValidationSummary",
    "CalculationTrace",
    "TraceStep",
    "DeterministicRatingEngine",
    "RatingCalculationError",
    "UnsupportedRatingRuleError",
    "PolicyRatingResult",
    "IndependentCalculator",
    "VerificationResult",
]
