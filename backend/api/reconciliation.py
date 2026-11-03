"""
Reconciliation and Run-Registry API Router.
Exposes endpoints for 5-step exact sequential premium attribution,
immutable audit run logging, and reproducible execution replay.
"""

from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.schemas.pricing_schema import PolicyInput, PricingAssumptionsInput
from backend.services.reconciliation_service import reconciliation_service, ReconciliationResponse
from backend.services.run_registry import run_registry
from actuarial.data_gate import DataQualityGate, DataQualityReport

router = APIRouter(tags=["Model-Run Registry & Reconciliation"])
data_gate = DataQualityGate()


class ReconciliationRequest(BaseModel):
    policy_a: PolicyInput = Field(..., description="Baseline comparator policyholder profile (Policy A)")
    policy_b: PolicyInput = Field(..., description="Target policyholder profile to explain (Policy B)")
    assumptions_a: Optional[PricingAssumptionsInput] = Field(None, description="Commercial assumptions for Policy A")
    assumptions_b: Optional[PricingAssumptionsInput] = Field(None, description="Commercial assumptions for Policy B")
    model_family_a: str = Field("poisson", description="Model family for Policy A (poisson, nb2)")
    model_family_b: str = Field("poisson", description="Model family for Policy B (poisson, nb2)")
    user_notes: Optional[str] = Field(None, description="Actuarial audit notes explaining rationale for reconciliation")
    convert_to_inr: bool = Field(False, description="Whether to display reconciliation values in INR (₹)")


@router.post("/reconcile", response_model=ReconciliationResponse)
def reconcile_premium_difference(request: ReconciliationRequest):
    """
    Execute exact 5-step sequential arithmetic premium attribution.
    Decomposes the difference P_B - P_A into:
    1. Pure Risk Characteristics (Delta P_input)
    2. Model Specification (Delta P_model)
    3. Exposure Term Scaling (Delta P_exposure)
    4. Commercial Expenses & Margins (Delta P_assump)
    5. Statutory Insurance Tax (Delta P_tax)
    Verifies sum of deltas equals total difference within epsilon = 10^-4 and returns path-order sensitivity.
    """
    assump_a_dict = request.assumptions_a.model_dump(exclude_unset=True) if request.assumptions_a else None
    assump_b_dict = request.assumptions_b.model_dump(exclude_unset=True) if request.assumptions_b else None
    convert_inr = bool(request.convert_to_inr or request.policy_a.convert_to_inr or request.policy_b.convert_to_inr)

    return reconciliation_service.reconcile_policies(
        policy_a=request.policy_a,
        policy_b=request.policy_b,
        assumptions_a=assump_a_dict,
        assumptions_b=assump_b_dict,
        model_family_a=request.model_family_a,
        model_family_b=request.model_family_b,
        user_notes=request.user_notes,
        convert_to_inr=convert_inr
    )


@router.get("/runs")
def list_execution_runs(limit: int = Query(50, ge=1, le=200)):
    """List recent immutable model calculation and reconciliation runs."""
    return {
        "total_returned": len(run_registry.list_runs(limit=limit)),
        "runs": run_registry.list_runs(limit=limit)
    }


@router.get("/runs/{run_id}")
def get_execution_run_dossier(run_id: str):
    """Retrieve complete audit trace, unrounded intermediate values, and artifact checksums for a run."""
    run = run_registry.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found in registry.")
    return run


@router.post("/runs/{run_id}/replay")
def replay_execution_run(run_id: str):
    """
    Replay an execution run from its immutable input record.
    Asserts reproducibility within epsilon = 10^-6 against stored unrounded premium.
    """
    try:
        return run_registry.replay_run(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Replay execution failed: {str(e)}")


@router.post("/data-gate/validate", response_model=DataQualityReport)
def validate_policy_gate(policy: PolicyInput):
    """
    Evaluate policyholder input against the 10 automated pre-flight data-quality gate rules.
    Identifies schema conformity, range boundary compliance, and categorical integrity.
    """
    return data_gate.validate_policy(policy.model_dump())
