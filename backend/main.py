"""
FastAPI Application Entry Point.
AI-Powered Actuarial Risk and Insurance Decision Support System.
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.core.config import settings
from backend.services.pricing_service import pricing_service
from backend.api.pricing import router as pricing_router
from backend.api.explainability import router as explain_router
from backend.api.portfolio import router as portfolio_router
from backend.api.stress_testing import router as stress_router
from backend.api.validation import router as validation_router
from backend.api.reconciliation import router as reconciliation_router
from backend.api.rating_manuals import router as rating_manuals_router
from backend.api.rate_change import router as rate_change_router
from backend.api.verification import router as verification_router
from actuarial.preprocessing import FEATURE_RANGES, VALID_CATEGORIES
from actuarial.pricing import DEFAULT_PRICING_ASSUMPTIONS

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="Actuarial Risk Assessment, GLM Modeling, Pure Premium Rating, and Portfolio Loss Simulation Engine."
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    """Ensure static web assets and HTML are never served with stale browser cache."""
    response = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Include API Routers under /api/v1
api_v1_prefix = settings.API_V1_STR
app.include_router(pricing_router, prefix=api_v1_prefix)
app.include_router(explain_router, prefix=api_v1_prefix)
app.include_router(portfolio_router, prefix=api_v1_prefix)
app.include_router(stress_router, prefix=api_v1_prefix)
app.include_router(validation_router, prefix=api_v1_prefix)
app.include_router(reconciliation_router, prefix=api_v1_prefix)
app.include_router(rating_manuals_router, prefix=api_v1_prefix)
app.include_router(rate_change_router, prefix=api_v1_prefix)
app.include_router(verification_router, prefix=api_v1_prefix)


@app.get(f"{api_v1_prefix}/health", tags=["System Health"])
def health_check():
    """Verify backend service operational status and model readiness."""
    models_ready = pricing_service.is_ready
    return {
        "status": "healthy" if models_ready else "degraded",
        "app_name": settings.APP_NAME,
        "version": settings.VERSION,
        "models_loaded": {
            "preprocessor": os.path.exists(settings.PREPROCESSOR_PATH),
            "frequency_glm": os.path.exists(settings.FREQ_MODEL_PATH),
            "severity_glm": os.path.exists(settings.SEV_MODEL_PATH),
            "hgb_poisson": os.path.exists(os.path.join(settings.MODELS_DIR, "hgb_poisson.joblib")),
            "hgb_gamma": os.path.join(settings.MODELS_DIR, "hgb_gamma.joblib")
        },
        "datasets_available": {
            "frequency_raw": os.path.exists(settings.RAW_FREQ_PATH),
            "severity_raw": os.path.exists(settings.RAW_SEV_PATH),
            "benchmark_portfolio": os.path.exists(settings.BENCHMARK_PORTFOLIO_PATH)
        }
    }


@app.get(f"{api_v1_prefix}/config", tags=["System Configuration"])
def get_system_config():
    """Return supported features, categorical choices, input constraints, and default pricing assumptions."""
    return {
        "version": settings.VERSION,
        "dataset_context": "French Motor Third-Party Liability Insurance (freMTPL2)",
        "currency_base": "EUR",
        "currency_symbol": "€",
        "inr_conversion_rate": settings.INR_EXCHANGE_RATE,
        "inr_reference_date": settings.EXCHANGE_RATE_DATE,
        "feature_ranges": FEATURE_RANGES,
        "valid_categories": VALID_CATEGORIES,
        "default_pricing_assumptions": DEFAULT_PRICING_ASSUMPTIONS,
        "disclaimer": (
            "This application is an educational and actuarial research decision-support tool. "
            "Underlying models are trained on French motor data and do not represent Indian insurer tariffs."
        )
    }


# Mount frontend static files
frontend_dir = os.path.abspath("frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    def serve_index():
        return FileResponse(os.path.join(frontend_dir, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
