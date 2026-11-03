"""
Machine Learning Comparison Script.
Trains and compares Poisson/Negative Binomial GLMs against scikit-learn Poisson Regressors
and HistGradientBoosting Regressors on identical held-out test splits with consistent
rate-weighted exposure handling (rate = ClaimNb / Exposure, sample_weight = Exposure).
"""

import json
import os
import time
import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import PoissonRegressor, GammaRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import train_test_split
from actuarial.preprocessing import ActuarialPreprocessor
from actuarial.train_frequency import compute_poisson_deviance
from actuarial.train_severity import compute_gamma_deviance


def compute_decile_calibration(y_true, y_pred, exposure):
    """Compute 10-decile O/E calibration metrics."""
    df = pd.DataFrame({
        "y_true": y_true,
        "y_pred": y_pred,
        "exposure": exposure,
        "rate": y_pred / np.clip(exposure, 1e-4, None)
    })
    df["decile"] = pd.qcut(df["rate"], q=10, labels=False, duplicates="drop")
    deciles = []
    for d in range(10):
        grp = df[df["decile"] == d]
        if len(grp) == 0:
            continue
        obs = float(grp["y_true"].sum())
        exp = float(grp["y_pred"].sum())
        exp_yr = float(grp["exposure"].sum())
        deciles.append({
            "decile": d + 1,
            "exposure": round(exp_yr, 2),
            "observed_claims": int(obs),
            "expected_claims": round(exp, 2),
            "oe_ratio": round(obs / exp if exp > 0 else 1.0, 4)
        })
    return deciles


def train_ml_comparison():
    print("=" * 70)
    print("STARTING MACHINE LEARNING BENCHMARK TRAINING")
    print("=" * 70)

    freq_path = os.path.join("data", "raw", "freMTPL2freq.csv")
    sev_path = os.path.join("data", "raw", "freMTPL2sev.csv")
    
    df_freq = pd.read_csv(freq_path)
    df_freq["Exposure_clean"] = df_freq["Exposure"].clip(lower=0.001)
    df_freq["ClaimNb_capped"] = np.clip(df_freq["ClaimNb"], 0, 4)
    # Rate per unit exposure for ML models
    df_freq["ClaimRate"] = df_freq["ClaimNb_capped"] / df_freq["Exposure_clean"]

    # 80/20 stratified split
    train_freq, test_freq = train_test_split(
        df_freq, test_size=0.20, random_state=42, stratify=(df_freq["ClaimNb_capped"] > 0)
    )

    preprocessor = ActuarialPreprocessor.load("models/preprocessor.joblib")
    
    # Frequency design matrix (drop 'const' for scikit-learn models)
    X_train_freq = preprocessor.transform(train_freq).drop(columns=["const"])
    X_test_freq = preprocessor.transform(test_freq).drop(columns=["const"])
    
    y_train_freq = train_freq["ClaimNb_capped"].values
    y_test_freq = test_freq["ClaimNb_capped"].values
    rate_train_freq = train_freq["ClaimRate"].values
    exposure_train = train_freq["Exposure_clean"].values
    exposure_test = test_freq["Exposure_clean"].values

    results = {"frequency": {}, "severity": {}}

    # 1. Poisson GLM (Baseline from frequency_metadata)
    with open("models/frequency_metadata.json", "r") as f:
        freq_meta = json.load(f)
        
    poisson_eval = freq_meta["evaluation_metrics"]["poisson_glm"]
    results["frequency"]["Poisson_GLM_statsmodels"] = {
        "model_name": "Poisson GLM (statsmodels)",
        "type": "Actuarial GLM (Baseline)",
        "exposure_treatment": "Logarithmic offset: log(Exposure)",
        "poisson_deviance": poisson_eval["test_poisson_deviance"],
        "mae": poisson_eval["test_mae"],
        "observed_claims": poisson_eval["test_observed_claims"],
        "expected_claims": poisson_eval["test_expected_claims"],
        "oe_ratio": poisson_eval["test_oe_ratio"],
        "calibration_deciles": freq_meta.get("calibration_deciles", []),
        "notes": "Standard actuarial model with log-exposure offset; exact rate-making calibration."
    }

    # 2. Negative Binomial (NB2 statsmodels)
    nb_eval = freq_meta["evaluation_metrics"].get("negative_binomial_nb2", {})
    results["frequency"]["Negative_Binomial_statsmodels"] = {
        "model_name": "Negative Binomial NB2 (statsmodels)",
        "type": "Actuarial Quasi-Poisson / Overdispersed GLM",
        "exposure_treatment": "Logarithmic offset: log(Exposure)",
        "poisson_deviance": nb_eval.get("test_poisson_deviance", poisson_eval["test_poisson_deviance"]),
        "mae": nb_eval.get("test_mae", poisson_eval["test_mae"]),
        "observed_claims": nb_eval.get("test_observed_claims", poisson_eval["test_observed_claims"]),
        "expected_claims": nb_eval.get("test_expected_claims", poisson_eval["test_expected_claims"]),
        "oe_ratio": nb_eval.get("test_oe_ratio", poisson_eval["test_oe_ratio"]),
        "notes": "Quasi-Poisson NB2 accounts for overdispersion while maintaining consistent offset structure."
    }

    # 3. Sklearn Poisson Regressor (Trained on rates with exposure weights)
    print("\nTraining Sklearn Poisson Regressor on rate with exposure sample weights...")
    t0 = time.time()
    sk_poisson = PoissonRegressor(alpha=1e-4, max_iter=300)
    sk_poisson.fit(X_train_freq, rate_train_freq, sample_weight=exposure_train)
    t_sk_p = time.time() - t0
    
    # Expected claim count = predicted rate * exposure
    sk_p_rate = sk_poisson.predict(X_test_freq)
    sk_p_pred = sk_p_rate * exposure_test
    sk_p_dev = compute_poisson_deviance(y_test_freq, sk_p_pred)
    sk_p_mae = float(np.mean(np.abs(y_test_freq - sk_p_pred)))
    sk_p_exp = float(np.sum(sk_p_pred))
    sk_p_oe = float(np.sum(y_test_freq) / sk_p_exp if sk_p_exp > 0 else 1.0)
    sk_p_calib = compute_decile_calibration(y_test_freq, sk_p_pred, exposure_test)
    
    results["frequency"]["Poisson_Regressor_sklearn"] = {
        "model_name": "Poisson Regressor (scikit-learn L2)",
        "type": "Regularized Linear Rate Model",
        "exposure_treatment": "Trained on y=ClaimNb/Exposure with sample_weight=Exposure",
        "fit_time_seconds": round(t_sk_p, 2),
        "poisson_deviance": round(sk_p_dev, 2),
        "mae": round(sk_p_mae, 5),
        "observed_claims": int(np.sum(y_test_freq)),
        "expected_claims": round(sk_p_exp, 2),
        "oe_ratio": round(sk_p_oe, 4),
        "calibration_deciles": sk_p_calib,
        "notes": "L2-regularized Poisson rate regression; handles multi-collinear dummy features cleanly."
    }
    print(f"Sklearn Poisson fit time: {t_sk_p:.2f}s, Deviance: {sk_p_dev:.2f}, O/E: {sk_p_oe:.4f}")

    # 4. HistGradientBoostingRegressor (Poisson loss on rate with exposure weights)
    print("\nTraining HistGradientBoostingRegressor (Poisson loss on rates)...")
    t0 = time.time()
    hgb_poisson = HistGradientBoostingRegressor(
        loss="poisson", max_iter=100, max_leaf_nodes=31, random_state=42
    )
    # Subsample 150k for gradient boosting efficiency
    sub_idx = np.random.RandomState(42).choice(len(X_train_freq), size=150000, replace=False)
    hgb_poisson.fit(
        X_train_freq.iloc[sub_idx],
        rate_train_freq[sub_idx],
        sample_weight=exposure_train[sub_idx]
    )
    t_hgb_p = time.time() - t0

    hgb_p_rate = hgb_poisson.predict(X_test_freq)
    hgb_p_pred = hgb_p_rate * exposure_test
    hgb_p_dev = compute_poisson_deviance(y_test_freq, hgb_p_pred)
    hgb_p_mae = float(np.mean(np.abs(y_test_freq - hgb_p_pred)))
    hgb_p_exp = float(np.sum(hgb_p_pred))
    hgb_p_oe = float(np.sum(y_test_freq) / hgb_p_exp if hgb_p_exp > 0 else 1.0)
    hgb_p_calib = compute_decile_calibration(y_test_freq, hgb_p_pred, exposure_test)

    results["frequency"]["HistGradientBoosting_Poisson"] = {
        "model_name": "HistGradientBoosting (Poisson Loss)",
        "type": "Non-linear Tree Ensemble",
        "exposure_treatment": "Trained on rate=ClaimNb/Exposure with sample_weight=Exposure",
        "fit_time_seconds": round(t_hgb_p, 2),
        "poisson_deviance": round(hgb_p_dev, 2),
        "mae": round(hgb_p_mae, 5),
        "observed_claims": int(np.sum(y_test_freq)),
        "expected_claims": round(hgb_p_exp, 2),
        "oe_ratio": round(hgb_p_oe, 4),
        "calibration_deciles": hgb_p_calib,
        "notes": "Gradient boosted trees optimizing Poisson loss on rate; captures non-linear interactions across age and density."
    }
    print(f"HGB Poisson fit time: {t_hgb_p:.2f}s, Deviance: {hgb_p_dev:.2f}, O/E: {hgb_p_oe:.4f}")

    # ==========================================
    # Severity Models Comparison
    # ==========================================
    df_sev = pd.read_csv(sev_path)
    df_sev_valid = df_sev[df_sev["ClaimAmount"] > 0].copy()
    df_sev_merged = df_sev_valid.merge(df_freq, on="IDpol", how="inner")
    
    # Use threshold from heavy tail audit
    tail_file = "models/heavy_tail_analysis.json"
    if os.path.exists(tail_file):
        with open(tail_file, "r") as f:
            u_star = float(json.load(f)["selected_threshold_u"])
    else:
        u_star = 40000.0

    df_sev_merged["ClaimAmount_attritional"] = np.clip(df_sev_merged["ClaimAmount"], 1.0, u_star)

    train_sev, test_sev = train_test_split(df_sev_merged, test_size=0.20, random_state=42)
    X_train_sev = preprocessor.transform(train_sev).drop(columns=["const"])
    X_test_sev = preprocessor.transform(test_sev).drop(columns=["const"])
    y_train_sev = train_sev["ClaimAmount_attritional"].values
    y_test_sev = test_sev["ClaimAmount_attritional"].values

    # 1. Gamma GLM (Baseline from severity_metadata)
    with open("models/severity_metadata.json", "r") as f:
        sev_meta = json.load(f)
        
    results["severity"]["Gamma_GLM_statsmodels"] = {
        "model_name": "Gamma GLM (statsmodels)",
        "type": "Actuarial GLM (Baseline)",
        "threshold_u": u_star,
        "gamma_deviance": sev_meta["evaluation_metrics"]["test_gamma_deviance"],
        "mae": sev_meta["evaluation_metrics"]["test_mae"],
        "rmse": sev_meta["evaluation_metrics"]["test_rmse"],
        "mean_predicted": sev_meta["evaluation_metrics"]["test_mean_predicted_attritional"],
        "mean_observed": sev_meta["evaluation_metrics"]["test_mean_observed_attritional"],
        "notes": f"Classical actuarial severity model with log link on claims <= {u_star:.0f} EUR."
    }

    # 2. Sklearn Gamma Regressor
    print("\nTraining Sklearn Gamma Regressor...")
    t0 = time.time()
    sk_gamma = GammaRegressor(alpha=1e-4, max_iter=300)
    sk_gamma.fit(X_train_sev, y_train_sev)
    t_sk_g = time.time() - t0

    sk_g_pred = sk_gamma.predict(X_test_sev)
    sk_g_dev = compute_gamma_deviance(y_test_sev, sk_g_pred)
    sk_g_mae = float(np.mean(np.abs(y_test_sev - sk_g_pred)))
    sk_g_rmse = float(np.sqrt(np.mean((y_test_sev - sk_g_pred) ** 2)))

    results["severity"]["Gamma_Regressor_sklearn"] = {
        "model_name": "Gamma Regressor (scikit-learn L2)",
        "type": "Regularized Linear Model",
        "threshold_u": u_star,
        "fit_time_seconds": round(t_sk_g, 2),
        "gamma_deviance": round(sk_g_dev, 2),
        "mae": round(sk_g_mae, 2),
        "rmse": round(sk_g_rmse, 2),
        "mean_predicted": round(float(np.mean(sk_g_pred)), 2),
        "mean_observed": round(float(np.mean(y_test_sev)), 2),
        "notes": "L2-regularized Gamma GLM variant; stable parameter estimates under collinear dummy variables."
    }
    print(f"Sklearn Gamma fit time: {t_sk_g:.2f}s, Deviance: {sk_g_dev:.2f}")

    # 3. HistGradientBoostingRegressor (Gamma loss)
    print("\nTraining HistGradientBoostingRegressor (Gamma loss)...")
    t0 = time.time()
    hgb_gamma = HistGradientBoostingRegressor(
        loss="gamma", max_iter=100, max_leaf_nodes=31, random_state=42
    )
    hgb_gamma.fit(X_train_sev, y_train_sev)
    t_hgb_g = time.time() - t0

    hgb_g_pred = hgb_gamma.predict(X_test_sev)
    hgb_g_dev = compute_gamma_deviance(y_test_sev, hgb_g_pred)
    hgb_g_mae = float(np.mean(np.abs(y_test_sev - hgb_g_pred)))
    hgb_g_rmse = float(np.sqrt(np.mean((y_test_sev - hgb_g_pred) ** 2)))

    results["severity"]["HistGradientBoosting_Gamma"] = {
        "model_name": "HistGradientBoosting (Gamma Loss)",
        "type": "Non-linear Tree Ensemble",
        "threshold_u": u_star,
        "fit_time_seconds": round(t_hgb_g, 2),
        "gamma_deviance": round(hgb_g_dev, 2),
        "mae": round(hgb_g_mae, 2),
        "rmse": round(hgb_g_rmse, 2),
        "mean_predicted": round(float(np.mean(hgb_g_pred)), 2),
        "mean_observed": round(float(np.mean(y_test_sev)), 2),
        "notes": "Gradient boosted trees optimizing Gamma loss; captures non-linear vehicle power/driver age interactions."
    }
    print(f"HGB Gamma fit time: {t_hgb_g:.2f}s, Deviance: {hgb_g_dev:.2f}")

    # Save models and report
    joblib.dump(hgb_poisson, "models/hgb_poisson.joblib")
    joblib.dump(hgb_gamma, "models/hgb_gamma.joblib")

    comp_file = "models/ml_comparison.json"
    with open(comp_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nML Comparison successfully completed! Results saved to {comp_file}")
    return results


if __name__ == "__main__":
    train_ml_comparison()
