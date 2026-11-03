"""
Portfolio Simulation API Endpoints.
Simulates aggregate portfolio losses and calculates empirical VaR and TVaR.
"""

import os
import pandas as pd
from fastapi import APIRouter, HTTPException
from backend.core.config import settings
from backend.schemas.portfolio_schema import (
    PortfolioSimulateRequest, PortfolioSimulateResponse
)
from backend.services.simulation_service import simulation_service

router = APIRouter(prefix="/portfolio", tags=["Portfolio Risk & Simulation"])


@router.post("/simulate", response_model=PortfolioSimulateResponse)
def simulate_portfolio_losses(request: PortfolioSimulateRequest):
    """Run Monte Carlo simulation of aggregate portfolio losses using Compound Poisson-Gamma process."""
    try:
        return simulation_service.simulate_portfolio(request)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Simulation failed: {str(e)}")


@router.get("/summary")
def get_portfolio_summary():
    """Retrieve portfolio baseline overview statistics."""
    try:
        if not os.path.exists(settings.BENCHMARK_PORTFOLIO_PATH):
            raise HTTPException(status_code=404, detail="Benchmark portfolio dataset not found.")
        
        df = pd.read_csv(settings.BENCHMARK_PORTFOLIO_PATH)
        return {
            "portfolio_name": "French MTPL Benchmark Portfolio (1,000 Policies)",
            "total_policies": len(df),
            "total_exposure_years": round(float(df["Exposure"].sum()), 2),
            "average_exposure": round(float(df["Exposure"].mean()), 3),
            "average_driver_age": round(float(df["DrivAge"].mean()), 1),
            "average_bonus_malus": round(float(df["BonusMalus"].mean()), 1),
            "area_distribution": df["Area"].value_counts().to_dict(),
            "fuel_distribution": df["VehGas"].value_counts().to_dict(),
            "currency": "EUR"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
