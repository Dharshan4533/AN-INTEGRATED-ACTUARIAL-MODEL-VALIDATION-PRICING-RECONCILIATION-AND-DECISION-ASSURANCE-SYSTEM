"""
Rate Change Assurance API Router.
Handles policy-level factor attribution, portfolio reconciliation, and census dislocation analysis.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field

from rating.spec_schema import RatingManualSpec
from backend.services.rating_manual_service import RatingManualService
from backend.services.rate_change_service import RateChangeService, PolicyAttributionResult
from backend.services.impact_analysis_service import ImpactAnalysisService, PortfolioReconciliationReport
from backend.services.reporting_service import reporting_service
from backend.services.run_registry import run_registry
from backend.services.verification_service import VerificationService

router = APIRouter(prefix="/rate-change", tags=["Rate Change Assurance"])


class PolicyRateChangeRequest(BaseModel):
    old_manual: Dict[str, Any]
    new_manual: Dict[str, Any]
    policy: Dict[str, Any]


class PortfolioReconcileRequest(BaseModel):
    old_manual: Dict[str, Any]
    new_manual: Dict[str, Any]
    census: List[Dict[str, Any]]


class ReportGenerationRequest(BaseModel):
    old_manual: Dict[str, Any]
    new_manual: Dict[str, Any]
    census: List[Dict[str, Any]]
    output_format: str = Field("markdown", description="'markdown', 'html', or 'dict'")
    record_in_ledger: bool = Field(True, description="Whether to record execution in hash-chained audit ledger")


@router.post("/evaluate-policy", response_model=PolicyAttributionResult)
def evaluate_single_policy(request: PolicyRateChangeRequest):
    """
    Evaluates policy premium under old and new rating manuals and returns
    step-by-step sequential factor attribution with unallocated interaction reporting.
    """
    try:
        old_spec, _ = RatingManualService.load_manual(request.old_manual)
        new_spec, _ = RatingManualService.load_manual(request.new_manual)
        service = RateChangeService(old_spec, new_spec)
        return service.evaluate_policy_change(request.policy)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Policy evaluation failed: {str(e)}")


@router.post("/reconcile-portfolio", response_model=PortfolioReconciliationReport)
def reconcile_portfolio(request: PortfolioReconcileRequest):
    """
    Performs full portfolio reconciliation across submitted census.
    Verifies aggregate reconciliation identity via Decimal arithmetic ($0.00 residual)
    and computes dislocation distributions.
    """
    try:
        old_spec, _ = RatingManualService.load_manual(request.old_manual)
        new_spec, _ = RatingManualService.load_manual(request.new_manual)
        service = ImpactAnalysisService(old_spec, new_spec)
        return service.reconcile_census(request.census)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Portfolio reconciliation failed: {str(e)}")


@router.get("/sample-census")
def get_sample_census():
    """
    Returns the 5 hand-calculated benchmark policies.
    """
    path = Path("sample_data/policies_5_sample.json")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Sample policy census file not found.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@router.post("/generate-report")
def generate_rate_change_report_endpoint(request: ReportGenerationRequest):
    """
    Generates a Rate Change Assurance report across the portfolio.
    Reconciles census, runs dual independent verification, optionally records
    the run to the hash-chained audit ledger, and outputs Markdown, HTML, or structured JSON.
    """
    try:
        old_spec, _ = RatingManualService.load_manual(request.old_manual)
        new_spec, _ = RatingManualService.load_manual(request.new_manual)

        # 1. Portfolio impact & reconciliation
        impact_svc = ImpactAnalysisService(old_spec, new_spec)
        summary = impact_svc.reconcile_census(request.census)

        # 2. Dual verification on census
        verif_svc = VerificationService(new_spec)
        verif_summary = verif_svc.verify_census(request.census).model_dump()

        # 3. Optional Hash-Chained Audit Ledger recording
        audit_trail = None
        if request.record_in_ledger:
            ledger_rec = run_registry.record_rate_change_run(
                old_manual_spec=old_spec.model_dump(),
                new_manual_spec=new_spec.model_dump(),
                census_records=request.census,
                reconciliation_summary=summary.model_dump(exclude={"policy_results"}),
                verification_summary=verif_summary,
            )
            audit_trail = {
                "run_id": ledger_rec["run_id"],
                "replay_token": ledger_rec["replay_token"],
                "entry_hash": ledger_rec["entry_hash"],
                "prev_hash": ledger_rec["prev_hash"],
                "record_index": ledger_rec["record_index"],
                "timestamp": ledger_rec["timestamp"],
            }

        # 4. Generate report
        report_content = reporting_service.generate_rate_change_report(
            summary=summary,
            old_spec=old_spec,
            new_spec=new_spec,
            verification_summary=verif_summary,
            audit_trail=audit_trail,
            output_format=request.output_format,
        )

        return {
            "status": "SUCCESS",
            "format": request.output_format,
            "report": report_content,
            "audit_trail": audit_trail,
            "is_aggregate_reconciled": summary.is_aggregate_reconciled,
            "verification_passed": verif_summary.get("is_100_percent_verified", False),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Report generation failed: {str(e)}")


@router.get("/audit-ledger/status")
def get_audit_ledger_status():
    """
    Returns the cryptographic verification status and tip hash of the Hash-Chained Audit Ledger.
    """
    try:
        verif = run_registry.verify_audit_ledger()
        return verif.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audit ledger check failed: {str(e)}")

