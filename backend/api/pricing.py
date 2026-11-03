"""
Pricing API Endpoints.
Handles single policy quotes, multi-policy comparisons, and what-if sensitivity analysis.
"""

from fastapi import APIRouter, HTTPException
from backend.schemas.pricing_schema import (
    QuoteRequest, QuoteResponse,
    ComparisonRequest, ComparisonResponse,
    WhatIfRequest, WhatIfResponse, PolicyInput
)
from backend.services.pricing_service import pricing_service

router = APIRouter(prefix="/quotes", tags=["Pricing & Quotation"])


@router.post("", response_model=QuoteResponse)
def create_quote(request: QuoteRequest):
    """Generate actuarial quote including pure premium, expected loss, commercial loadings, and risk tier."""
    if not pricing_service.is_ready:
        raise HTTPException(
            status_code=503,
            detail="Models not ready. Offline training must be completed before issuing quotes."
        )
    try:
        return pricing_service.predict_quote(request.policy, request.custom_assumptions)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Pricing calculation failed: {str(e)}")


@router.post("/compare", response_model=ComparisonResponse)
def compare_quotes(request: ComparisonRequest):
    """Compare 2 to 5 policyholder profiles using identical actuarial models and assumptions."""
    if not pricing_service.is_ready:
        raise HTTPException(status_code=503, detail="Models not ready for comparison.")
    try:
        return pricing_service.compare_policies(request)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Comparison failed: {str(e)}")


@router.post("/what-if", response_model=WhatIfResponse)
def what_if_analysis(request: WhatIfRequest):
    """Evaluate impact of modifying policyholder characteristics against a baseline profile."""
    if not pricing_service.is_ready:
        raise HTTPException(status_code=503, detail="Models not ready for what-if analysis.")
    try:
        return pricing_service.what_if_analysis(request)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"What-if analysis failed: {str(e)}")
