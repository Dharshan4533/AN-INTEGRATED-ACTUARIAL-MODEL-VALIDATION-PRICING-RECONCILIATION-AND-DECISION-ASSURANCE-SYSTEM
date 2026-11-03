"""
Dual Independent Verification API Router.
Coordinates independent calculation verification, checks exact monetary equality and
intermediate tolerances, and reports discrepancy audits.
"""

from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from rating.spec_schema import RatingManualSpec
from rating.independent_calculator import VerificationResult
from backend.services.rating_manual_service import RatingManualService
from backend.services.verification_service import VerificationService, BatchVerificationSummary

router = APIRouter(prefix="/verification", tags=["Independent Verification"])


class VerifyPolicyRequest(BaseModel):
    manual: Dict[str, Any]
    policy: Dict[str, Any]


class VerifyCensusRequest(BaseModel):
    manual: Dict[str, Any]
    census: List[Dict[str, Any]]


@router.post("/verify-policy", response_model=VerificationResult)
def verify_policy(request: VerifyPolicyRequest):
    """
    Executes dual verification on a single policy using the primary rating engine
    and independent Decimal calculator (prec=28).
    """
    try:
        spec, _ = RatingManualService.load_manual(request.manual)
        service = VerificationService(spec)
        return service.verify_policy(request.policy)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Policy verification failed: {str(e)}")


@router.post("/verify-census", response_model=BatchVerificationSummary)
def verify_census(request: VerifyCensusRequest):
    """
    Executes dual verification across an entire policyholder census.
    Reports 100% agreement status, max monetary discrepancy, and any failing policies.
    """
    try:
        spec, _ = RatingManualService.load_manual(request.manual)
        service = VerificationService(spec)
        return service.verify_census(request.census)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Census verification failed: {str(e)}")
