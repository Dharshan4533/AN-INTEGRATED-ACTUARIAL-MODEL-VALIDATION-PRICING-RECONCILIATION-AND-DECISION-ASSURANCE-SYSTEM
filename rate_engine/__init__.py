"""
Rate Change Assurance Workbench: Core Deterministic Rating & Verification Engine.
"""

from rate_engine.spec_schema import RatingManualSpec, RoundingRule
from rate_engine.spec_loader import load_rating_manual, compute_spec_hash
from rate_engine.validator import CensusValidator, PolicyValidationResult
from rate_engine.calculation_trace import CalculationTrace, StepTrace
from rate_engine.rating_engine import DeterministicRatingEngine, RatingResult
from rate_engine.independent_verifier import DualIndependentCalculator, VerificationOutcome
from rate_engine.attribution import ExactFactorAttributor, PolicyAttributionResult
from rate_engine.portfolio_reconciler import PortfolioReconciler, PortfolioReconciliationReport

__all__ = [
    "RatingManualSpec",
    "RoundingRule",
    "load_rating_manual",
    "compute_spec_hash",
    "CensusValidator",
    "PolicyValidationResult",
    "CalculationTrace",
    "StepTrace",
    "DeterministicRatingEngine",
    "RatingResult",
    "DualIndependentCalculator",
    "VerificationOutcome",
    "ExactFactorAttributor",
    "PolicyAttributionResult",
    "PortfolioReconciler",
    "PortfolioReconciliationReport",
]
