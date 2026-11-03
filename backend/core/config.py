"""
Core Configuration and Environment Settings.
"""

import os
from pydantic import BaseModel


class Settings(BaseModel):
    APP_NAME: str = "AI-Powered Actuarial Risk and Insurance Decision Support System"
    API_V1_STR: str = "/api/v1"
    VERSION: str = "1.0.0"
    
    # Model Artifact Paths
    MODELS_DIR: str = "models"
    FREQ_MODEL_PATH: str = os.path.join("models", "frequency_glm.joblib")
    SEV_MODEL_PATH: str = os.path.join("models", "severity_glm.joblib")
    PREPROCESSOR_PATH: str = os.path.join("models", "preprocessor.joblib")
    FREQ_META_PATH: str = os.path.join("models", "frequency_metadata.json")
    SEV_META_PATH: str = os.path.join("models", "severity_metadata.json")
    ML_COMP_PATH: str = os.path.join("models", "ml_comparison.json")
    SHAP_GLOBAL_PATH: str = os.path.join("models", "shap_global.json")
    RISK_TIER_PATH: str = os.path.join("models", "risk_tier_config.json")
    
    # Data Paths
    BENCHMARK_PORTFOLIO_PATH: str = os.path.join("data", "processed", "benchmark_portfolio.csv")
    RAW_FREQ_PATH: str = os.path.join("data", "raw", "freMTPL2freq.csv")
    RAW_SEV_PATH: str = os.path.join("data", "raw", "freMTPL2sev.csv")

    # Defaults
    DEFAULT_CURRENCY: str = "EUR"
    INR_EXCHANGE_RATE: float = 90.00
    EXCHANGE_RATE_DATE: str = "October 2026 Reference"


settings = Settings()
