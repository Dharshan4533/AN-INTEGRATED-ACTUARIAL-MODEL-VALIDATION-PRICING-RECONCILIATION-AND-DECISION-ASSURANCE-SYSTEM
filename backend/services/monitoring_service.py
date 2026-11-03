"""
Distribution Drift and Portfolio Monitoring Service.
Computes Population Stability Index (PSI) and Wasserstein-1 distance to track
input covariate drift between baseline reference portfolio and new incoming policies.
"""

import json
import os
from typing import Dict, List, Any, Optional
import numpy as np
import pandas as pd
from scipy.stats import wasserstein_distance
from pydantic import BaseModel


class FeatureDriftMetric(BaseModel):
    feature_name: str
    feature_type: str  # "NUMERICAL", "CATEGORICAL"
    psi_value: float
    wasserstein_dist: Optional[float] = None
    drift_status: str  # "STABLE", "MODERATE_SHIFT", "SIGNIFICANT_DRIFT"
    alert_level: str  # "INFO", "WARNING", "CRITICAL"
    interpretation: str


class DriftMonitoringReport(BaseModel):
    total_baseline_records: int
    total_target_records: int
    overall_portfolio_drift_status: str
    max_feature_psi: float
    feature_drifts: List[FeatureDriftMetric]
    regulatory_notes: str
    timestamp: str


class MonitoringService:
    PSI_STABLE_THRESHOLD = 0.10
    PSI_SIGNIFICANT_THRESHOLD = 0.25

    def compute_categorical_psi(self, baseline_series: pd.Series, target_series: pd.Series) -> float:
        """Compute PSI across discrete categorical frequencies."""
        cats = sorted(list(set(baseline_series.dropna().unique()) | set(target_series.dropna().unique())))
        p_counts = baseline_series.value_counts(normalize=True).to_dict()
        q_counts = target_series.value_counts(normalize=True).to_dict()

        psi = 0.0
        for cat in cats:
            p = max(1e-4, p_counts.get(cat, 1e-4))
            q = max(1e-4, q_counts.get(cat, 1e-4))
            psi += (q - p) * np.log(q / p)
        return float(psi)

    def compute_numerical_psi(self, baseline_vals: np.ndarray, target_vals: np.ndarray, bins: int = 10) -> float:
        """Compute PSI across numerical quantile bins."""
        b_clean = np.asarray(baseline_vals[~np.isnan(baseline_vals)], dtype=float)
        t_clean = np.asarray(target_vals[~np.isnan(target_vals)], dtype=float)

        if len(b_clean) == 0 or len(t_clean) == 0:
            return 0.0

        quantiles = np.linspace(0, 100, bins + 1)
        bin_edges = np.percentile(b_clean, quantiles)
        bin_edges = np.unique(bin_edges)  # Prevent duplicate edges
        if len(bin_edges) < 2:
            return 0.0

        bin_edges[0] = -np.inf
        bin_edges[-1] = np.inf

        p_counts, _ = np.histogram(b_clean, bins=bin_edges)
        q_counts, _ = np.histogram(t_clean, bins=bin_edges)

        p_pct = np.clip(p_counts / len(b_clean), 1e-4, None)
        q_pct = np.clip(q_counts / len(t_clean), 1e-4, None)

        psi = np.sum((q_pct - p_pct) * np.log(q_pct / p_pct))
        return float(psi)

    def evaluate_portfolio_drift(
        self,
        target_df: pd.DataFrame,
        baseline_df: Optional[pd.DataFrame] = None
    ) -> DriftMonitoringReport:
        """
        Evaluate drift of target_df against baseline reference portfolio.
        """
        from datetime import datetime, timezone
        from backend.core.config import settings

        if baseline_df is None:
            if os.path.exists(settings.BENCHMARK_PORTFOLIO_PATH):
                baseline_df = pd.read_csv(settings.BENCHMARK_PORTFOLIO_PATH)
            else:
                baseline_df = pd.read_csv(settings.RAW_FREQ_PATH, nrows=1000)

        num_features = ["VehPower", "VehAge", "DrivAge", "BonusMalus", "Density", "Exposure"]
        cat_features = ["Area", "VehBrand", "VehGas", "Region"]

        feature_metrics: List[FeatureDriftMetric] = []
        max_psi = 0.0

        # Evaluate continuous features
        for f in num_features:
            if f in target_df.columns and f in baseline_df.columns:
                b_vals = pd.to_numeric(baseline_df[f], errors="coerce").dropna().values
                t_vals = pd.to_numeric(target_df[f], errors="coerce").dropna().values
                
                psi = self.compute_numerical_psi(b_vals, t_vals)
                w_dist = float(wasserstein_distance(b_vals, t_vals)) if len(b_vals) > 0 and len(t_vals) > 0 else 0.0
                max_psi = max(max_psi, psi)

                if psi >= self.PSI_SIGNIFICANT_THRESHOLD:
                    status = "SIGNIFICANT_DRIFT"
                    alert = "CRITICAL"
                    interp = f"PSI={psi:.3f} >= 0.25 indicates significant structural distribution shift in '{f}'. Recalibration required."
                elif psi >= self.PSI_STABLE_THRESHOLD:
                    status = "MODERATE_SHIFT"
                    alert = "WARNING"
                    interp = f"PSI={psi:.3f} in [0.10, 0.25) indicates moderate drift in '{f}'. Ongoing monitoring recommended."
                else:
                    status = "STABLE"
                    alert = "INFO"
                    interp = f"PSI={psi:.3f} < 0.10 indicates stable population distribution in '{f}'."

                feature_metrics.append(FeatureDriftMetric(
                    feature_name=f,
                    feature_type="NUMERICAL",
                    psi_value=round(psi, 4),
                    wasserstein_dist=round(w_dist, 4),
                    drift_status=status,
                    alert_level=alert,
                    interpretation=interp
                ))

        # Evaluate categorical features
        for f in cat_features:
            if f in target_df.columns and f in baseline_df.columns:
                psi = self.compute_categorical_psi(baseline_df[f], target_df[f])
                max_psi = max(max_psi, psi)

                if psi >= self.PSI_SIGNIFICANT_THRESHOLD:
                    status = "SIGNIFICANT_DRIFT"
                    alert = "CRITICAL"
                    interp = f"Categorical PSI={psi:.3f} >= 0.25 reflects major composition change in '{f}'."
                elif psi >= self.PSI_STABLE_THRESHOLD:
                    status = "MODERATE_SHIFT"
                    alert = "WARNING"
                    interp = f"Categorical PSI={psi:.3f} in [0.10, 0.25) reflects moderate shift in '{f}'."
                else:
                    status = "STABLE"
                    alert = "INFO"
                    interp = f"Categorical PSI={psi:.3f} < 0.10 confirms stable distribution in '{f}'."

                feature_metrics.append(FeatureDriftMetric(
                    feature_name=f,
                    feature_type="CATEGORICAL",
                    psi_value=round(psi, 4),
                    wasserstein_dist=None,
                    drift_status=status,
                    alert_level=alert,
                    interpretation=interp
                ))

        if max_psi >= self.PSI_SIGNIFICANT_THRESHOLD:
            overall = "SIGNIFICANT_DRIFT"
        elif max_psi >= self.PSI_STABLE_THRESHOLD:
            overall = "MODERATE_SHIFT"
        else:
            overall = "STABLE"

        return DriftMonitoringReport(
            total_baseline_records=len(baseline_df),
            total_target_records=len(target_df),
            overall_portfolio_drift_status=overall,
            max_feature_psi=round(max_psi, 4),
            feature_drifts=feature_metrics,
            regulatory_notes=(
                "PSI thresholds (<0.10 stable, 0.10-0.25 moderate shift, >=0.25 significant drift) are actuarial heuristics. "
                "Shifts should trigger underwriting investigation and segmentation review rather than automatic rate adjustments."
            ),
            timestamp=datetime.now(timezone.utc).isoformat()
        )


# Global singleton instance
monitoring_service = MonitoringService()
