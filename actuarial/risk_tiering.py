"""
Actuarial Risk Classification and Tiering Module.
Defines documented risk tiers based on predicted annual pure premium quantiles,
supporting both business underwriting bands and empirical training quantiles.
"""

import json
import os
from typing import Dict, Any, Optional


DEFAULT_TIER_CONFIG = {
    "version": "2.0",
    "methodology": "Actuarial pure premium classification",
    "currency": "EUR",
    "business_tiers": [
        {
            "name": "Low",
            "min_val": 0.0,
            "max_val": 35.00,
            "badge_color": "green",
            "description": "Favorable risk profile; low frequency and clean bonus-malus rating.",
            "target_percentile": "Bottom 30% underwriting tier"
        },
        {
            "name": "Moderate",
            "min_val": 35.00,
            "max_val": 75.00,
            "badge_color": "blue",
            "description": "Standard market risk profile; typical claim frequency and vehicle characteristics.",
            "target_percentile": "30th to 70th percentile"
        },
        {
            "name": "High",
            "min_val": 75.00,
            "max_val": 160.00,
            "badge_color": "orange",
            "description": "Elevated risk profile; higher claim likelihood due to dense urban environment, youthful driver, or malus.",
            "target_percentile": "70th to 90th percentile"
        },
        {
            "name": "Very High",
            "min_val": 160.00,
            "max_val": 100000.0,
            "badge_color": "red",
            "description": "Substantially heightened risk; high frequency exposure, significant malus, or adverse vehicle power.",
            "target_percentile": "Top 10% risk tail"
        }
    ],
    "empirical_tiers": [
        {
            "name": "Low",
            "min_val": 0.0,
            "max_val": 125.71,
            "badge_color": "green",
            "description": "Favorable risk profile; lower pure risk than 70% of empirical portfolio.",
            "target_percentile": "Bottom 30% empirical quantile"
        },
        {
            "name": "Moderate",
            "min_val": 125.71,
            "max_val": 207.73,
            "badge_color": "blue",
            "description": "Standard market risk profile; 30th to 70th empirical quantile.",
            "target_percentile": "30th to 70th percentile"
        },
        {
            "name": "High",
            "min_val": 207.73,
            "max_val": 310.02,
            "badge_color": "orange",
            "description": "Elevated risk profile; 70th to 90th empirical quantile.",
            "target_percentile": "70th to 90th percentile"
        },
        {
            "name": "Very High",
            "min_val": 310.02,
            "max_val": 100000.0,
            "badge_color": "red",
            "description": "Substantially heightened risk; top 10% empirical risk tail.",
            "target_percentile": "Top 10% risk tail"
        }
    ]
}


class RiskTierClassifier:
    def __init__(self, config_path: Optional[str] = None, mode: str = "business"):
        self.mode = mode
        self.config = dict(DEFAULT_TIER_CONFIG)
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    loaded = json.load(f)
                    if "tiers" in loaded:
                        self.config["business_tiers"] = loaded["tiers"]
                    if "empirical_tiers" in loaded:
                        self.config["empirical_tiers"] = loaded["empirical_tiers"]
            except Exception:
                pass

    def classify(self, annual_pure_premium: float, mode: Optional[str] = None) -> Dict[str, Any]:
        """Classify policy into a documented actuarial risk tier."""
        tier_mode = mode or self.mode
        premium = max(0.0, float(annual_pure_premium))

        tier_list = (
            self.config["empirical_tiers"]
            if tier_mode == "empirical"
            else self.config.get("business_tiers", self.config.get("tiers", []))
        )

        selected_tier = tier_list[-1]  # Default to highest if unbounded
        for tier in tier_list:
            if tier["min_val"] <= premium <= tier["max_val"]:
                selected_tier = tier
                break

        # Normalized risk score (0 to 100 scale)
        risk_score = round(min(100.0, max(0.0, (premium / 300.0) * 100.0)), 1)

        return {
            "tier_name": selected_tier["name"],
            "badge_color": selected_tier["badge_color"],
            "risk_score": risk_score,
            "tier_mode": tier_mode,
            "description": selected_tier["description"],
            "target_percentile": selected_tier["target_percentile"],
            "threshold_min": selected_tier["min_val"],
            "threshold_max": selected_tier["max_val"]
        }
