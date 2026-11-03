"""
Claim-Severity Model Training Script.
Trains an Attritional Gamma GLM with log link on eligible claims up to the
data-driven Mean Excess threshold u*, integrates portfolio large-loss loading,
evaluates on held-out test data, and saves artifacts with parameter covariance.
"""

import json
import os
import joblib
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.model_selection import train_test_split
from actuarial.preprocessing import ActuarialPreprocessor
from actuarial.heavy_tail import run_heavy_tail_audit


def compute_gamma_deviance(y_true, y_pred):
    """Compute Gamma deviance: 2 * sum(-log(y / mu) + (y - mu) / mu)."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    y_pred = np.clip(y_pred, 1e-10, None)
    
    dev = 2 * np.sum(-np.log(y_true / y_pred) + (y_true - y_pred) / y_pred)
    return float(dev)


def train_severity_model():
    print("=" * 70)
    print("STARTING SEVERITY MODEL TRAINING (Layered Gamma GLM & Large-Loss)")
    print("=" * 70)

    freq_path = os.path.join("data", "raw", "freMTPL2freq.csv")
    sev_path = os.path.join("data", "raw", "freMTPL2sev.csv")

    if not os.path.exists(freq_path) or not os.path.exists(sev_path):
        raise FileNotFoundError("Missing raw frequency or severity data file.")

    df_freq = pd.read_csv(freq_path)
    df_sev = pd.read_csv(sev_path)
    print(f"Loaded {len(df_freq)} frequency rows and {len(df_sev)} severity rows.")

    # 1. Heavy-tail audit to establish data-driven threshold u* and large loss loading
    heavy_tail_file = os.path.join("models", "heavy_tail_analysis.json")
    if os.path.exists(heavy_tail_file):
        with open(heavy_tail_file, "r") as f:
            tail_audit = json.load(f)
    else:
        tail_audit = run_heavy_tail_audit()

    threshold_u = float(tail_audit["selected_threshold_u"])
    large_loss_load = float(tail_audit["large_loss_load_per_exposure_eur"])
    print(f"Data-driven large loss threshold u* = {threshold_u:.2f} EUR")
    print(f"Large-loss loading = {large_loss_load:.4f} EUR/exposure-year")

    # 2. Filter strictly positive claims
    df_sev_valid = df_sev[df_sev["ClaimAmount"] > 0].copy()
    print(f"Valid positive claim records: {len(df_sev_valid)}")

    # 3. Merge individual claims with policy features on IDpol
    df_merged = df_sev_valid.merge(df_freq, on="IDpol", how="inner")
    print(f"Successfully linked claims to policy profiles: {len(df_merged)} records.")

    # 4. Attritional layer: cap at data-driven threshold u*
    df_merged["ClaimAmount_attritional"] = np.clip(df_merged["ClaimAmount"], 1.0, threshold_u)
    
    # 80/20 train/test split with fixed seed
    train_df, test_df = train_test_split(df_merged, test_size=0.20, random_state=42)
    print(f"Severity Train set: {len(train_df)} | Test set: {len(test_df)}")

    # Load or fit preprocessor
    prep_path = os.path.join("models", "preprocessor.joblib")
    if os.path.exists(prep_path):
        preprocessor = ActuarialPreprocessor.load(prep_path)
    else:
        preprocessor = ActuarialPreprocessor()
        preprocessor.fit(df_freq)
        preprocessor.save(prep_path)

    X_train = preprocessor.transform(train_df)
    X_test = preprocessor.transform(test_df)
    y_train = train_df["ClaimAmount_attritional"].values
    y_test = test_df["ClaimAmount_attritional"].values

    print(f"Design matrix shape: {X_train.shape}")
    print("Fitting Gamma GLM with log link on attritional claims...")

    glm_gamma = sm.GLM(
        y_train,
        X_train,
        family=sm.families.Gamma(link=sm.genmod.families.links.Log())
    )
    res_gamma = glm_gamma.fit()
    print("Gamma GLM converged successfully!")
    print(f"  Gamma Train AIC: {res_gamma.aic:.2f}, Deviance: {res_gamma.deviance:.2f}, Scale: {res_gamma.scale:.4f}")

    # Evaluate on held-out test data
    test_pred_sev = res_gamma.predict(X_test)

    mean_obs_sev = float(np.mean(y_test))
    mean_exp_sev = float(np.mean(test_pred_sev))
    gamma_dev = compute_gamma_deviance(y_test, test_pred_sev)
    mae = float(np.mean(np.abs(y_test - test_pred_sev)))
    rmse = float(np.sqrt(np.mean((y_test - test_pred_sev) ** 2)))

    print("\nHeld-Out Test Evaluation (Attritional Layer):")
    print(f"  Mean Observed Severity : {mean_obs_sev:.2f} EUR")
    print(f"  Mean Predicted Severity: {mean_exp_sev:.2f} EUR")
    print(f"  Gamma Deviance         : {gamma_dev:.2f}")
    print(f"  Mean Absolute Error    : {mae:.2f} EUR")
    print(f"  Root Mean Squared Error: {rmse:.2f} EUR")

    # Calibration across severity deciles
    test_eval_df = pd.DataFrame({
        "y_true": y_test,
        "y_pred": test_pred_sev
    })
    test_eval_df["decile"] = pd.qcut(test_eval_df["y_pred"], q=10, labels=False, duplicates="drop")
    
    calibration_deciles = []
    for dec in range(10):
        group = test_eval_df[test_eval_df["decile"] == dec]
        if len(group) == 0:
            continue
        g_obs_mean = float(group["y_true"].mean())
        g_exp_mean = float(group["y_pred"].mean())
        calibration_deciles.append({
            "decile": dec + 1,
            "claim_count": len(group),
            "observed_mean_severity": round(g_obs_mean, 2),
            "predicted_mean_severity": round(g_exp_mean, 2),
            "ratio": round(g_obs_mean / g_exp_mean if g_exp_mean > 0 else 1.0, 4)
        })

    # Save model artifact
    model_artifact = {
        "params": res_gamma.params.to_dict(),
        "bse": res_gamma.bse.to_dict(),
        "pvalues": res_gamma.pvalues.to_dict(),
        "cov_params": res_gamma.cov_params().to_dict(),
        "aic": float(res_gamma.aic),
        "bic": float(res_gamma.bic),
        "deviance": float(res_gamma.deviance),
        "df_resid": float(res_gamma.df_resid),
        "feature_columns": list(X_train.columns),
        "scale": float(res_gamma.scale),
        "threshold_u": threshold_u,
        "large_loss_load_per_exposure": large_loss_load
    }
    joblib.dump(model_artifact, os.path.join("models", "severity_glm.joblib"))

    # Metadata report
    metadata = {
        "model_type": "Two-Layer Severity Model (Attritional Gamma GLM + Large-Loss Layer)",
        "family": "Gamma",
        "link": "Log",
        "attritional_threshold_u": round(threshold_u, 2),
        "threshold_derivation": tail_audit["threshold_selection_rationale"],
        "large_loss_load_per_exposure_eur": round(large_loss_load, 4),
        "training_records": len(train_df),
        "test_records": len(test_df),
        "features": list(X_train.columns),
        "evaluation_metrics": {
            "test_mean_observed_attritional": round(mean_obs_sev, 2),
            "test_mean_predicted_attritional": round(mean_exp_sev, 2),
            "test_gamma_deviance": round(gamma_dev, 2),
            "test_mae": round(mae, 2),
            "test_rmse": round(rmse, 2),
            "train_aic": round(res_gamma.aic, 2),
            "train_deviance": round(res_gamma.deviance, 2),
            "dispersion_scale": round(res_gamma.scale, 4)
        },
        "two_layer_portfolio_reconciliation": {
            "attritional_cost_per_exposure": tail_audit["attritional_cost_per_exposure_eur"],
            "large_loss_cost_per_exposure": tail_audit["large_loss_load_per_exposure_eur"],
            "total_pure_cost_per_exposure": tail_audit["total_pure_cost_per_exposure_eur"],
            "is_exact_decomposition": tail_audit["is_exact_decomposition"]
        },
        "calibration_deciles": calibration_deciles,
        "sample_coefficients": {
            k: round(v, 4) for k, v in list(res_gamma.params.items())[:10]
        }
    }
    with open(os.path.join("models", "severity_metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    print("\nSeverity model artifacts and metadata saved successfully!")
    return metadata


if __name__ == "__main__":
    train_severity_model()

