"""
Rating Manuals API Router.
Handles rating manual validation, semantic version diffing, and spec retrieval.
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field

from rating.spec_schema import RatingManualSpec
from rating.spec_loader import compute_spec_hash, load_rating_manual
from backend.services.rating_manual_service import RatingManualService, ManualComparisonSummary

router = APIRouter(prefix="/rating-manuals", tags=["Rating Manuals"])


class ValidationResponse(BaseModel):
    is_valid: bool
    manual_id: str
    version: str
    currency: str
    currency_precision: int
    canonical_sha256: str
    total_pipeline_steps: int
    factor_variables: list[str]


class CompareRequest(BaseModel):
    old_manual: Dict[str, Any] = Field(..., description="Old rating manual specification JSON")
    new_manual: Dict[str, Any] = Field(..., description="New rating manual specification JSON")


@router.post("/validate", response_model=ValidationResponse)
def validate_manual(spec_data: Dict[str, Any] = Body(...)):
    """
    Validates a submitted rating manual JSON against the Pydantic specification schema
    and returns its canonical RFC 8785 SHA-256 integrity hash.
    """
    try:
        spec, spec_hash = RatingManualService.load_manual(spec_data)
        return ValidationResponse(
            is_valid=True,
            manual_id=spec.manual_id,
            version=spec.version,
            currency=spec.currency,
            currency_precision=spec.currency_precision,
            canonical_sha256=spec_hash,
            total_pipeline_steps=len(spec.calculation_pipeline or []),
            factor_variables=sorted(list(spec.factor_tables.keys()))
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Rating manual validation failed: {str(e)}")


@router.post("/compare", response_model=ManualComparisonSummary)
def compare_manuals(request: CompareRequest):
    """
    Compares old and new rating manuals, returning an audit report of base rate, factor,
    fee, and limit changes.
    """
    try:
        old_spec, _ = RatingManualService.load_manual(request.old_manual)
        new_spec, _ = RatingManualService.load_manual(request.new_manual)
        return RatingManualService.compare_manuals(old_spec, new_spec)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Comparison failed: {str(e)}")


@router.get("/samples")
def get_sample_manuals():
    """
    Returns baseline and revision sample rating manual specifications from disk.
    """
    try:
        old_spec, old_hash = load_rating_manual("rating_specs/manual_v1_old.json")
        new_spec, new_hash = load_rating_manual("rating_specs/manual_v2_new.json")
        return {
            "old_manual": old_spec.model_dump(),
            "old_sha256": old_hash,
            "new_manual": new_spec.model_dump(),
            "new_sha256": new_hash
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not load sample manuals: {str(e)}")
