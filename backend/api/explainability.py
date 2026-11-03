"""
Explainability API Endpoints.
Provides SHAP and actuarial feature attribution for individual quotes and global model rankings.
"""

from fastapi import APIRouter, HTTPException
from backend.schemas.pricing_schema import PolicyInput
from backend.services.pricing_service import pricing_service
from explainability.shap_service import ShapExplainabilityService

router = APIRouter(prefix="/explain", tags=["Model Explainability"])


@router.post("")
def explain_policy(policy: PolicyInput):
    """Compute local feature attributions and risk drivers for a policyholder."""
    if not pricing_service.is_ready or not pricing_service.shap_service:
        raise HTTPException(status_code=503, detail="Explainability models are not ready.")
    try:
        return pricing_service.shap_service.explain_local(policy.model_dump())
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Explainability calculation error: {str(e)}")


@router.get("/global")
def get_global_importance():
    """Retrieve pre-computed global feature importance rankings from held-out evaluations."""
    service = ShapExplainabilityService()
    return service.get_global_importance()
