"""
Stress Testing API Endpoints.
Evaluates portfolio solvency and capital adequacy under adverse actuarial scenarios.
"""

from fastapi import APIRouter, HTTPException
from backend.schemas.portfolio_schema import (
    StressTestScenarioInput, StressTestResponse
)
from backend.services.simulation_service import simulation_service

router = APIRouter(prefix="/stress-test", tags=["Stress Testing & Scenario Analysis"])


@router.post("", response_model=StressTestResponse)
def run_stress_test(scenario: StressTestScenarioInput):
    """Evaluate capital strain under adverse frequency, severity, or rating drift scenarios."""
    try:
        return simulation_service.run_stress_test(scenario)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Stress test execution failed: {str(e)}")
