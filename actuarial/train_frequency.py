"""
Claim-Frequency Model Training Script.
Trains Poisson GLM and Negative Binomial (NB2) with log-exposure offset on French MTPL data,
conducts Cameron-Trivedi overdispersion diagnostic, evaluates on held-out test data,
and saves model artifacts and audit metadata.
"""

import json
import os
import joblib
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.model_selection import train_test_split
from actuarial.preprocessing import ActuarialPreprocessor


def compute_poisson_deviance(y_true, y_pred):
    """Compute Poisson deviance: 2 * sum(y * log(y / mu) - (y - mu))."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    y_pred = np.clip(y_pred, 1e-10, None)
    
    with np.errstate(divide="ignore", invalid="ignore"):
        term1 = np.where(y_true > 0, y_true * np.log(y_true / y_pred), 0.0)
    term2 = y_true - y_pred
    return float(2 * np.sum(term1 - term2))


def run_cameron_trivedi_test(y_true, y_pred):
    """
    Cameron & Trivedi (1990) regression-based test for overdispersion in Poisson model.
    Null Hypothesis H0: Var(Y|X) = mu (Equidispersion / Poisson)
    Alt Hypothesis H1: Var(Y|X) = mu + alpha * mu^2 (Overdispersion / NB2)
    Regresses ((y - mu)^2 - y) / mu on mu without intercept.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    y_pred = np.clip(y_pred, 1e-10, None)

    lhs = ((y_true - y_pred) ** 2 - y_true) / y_pred
    rhs = y_pred

    ols_model = sm.OLS(lhs, rhs).fit()
    alpha_hat = float(ols_model.params[0]) if hasattr(ols_model.params, "__len__") else float(ols_model.params)
    t_stat = float(ols_model.tvalues[0]) if hasattr(ols_model.tvalues, "__len__") else float(ols_model.tvalues)
    p_val = float(ols_model.pvalues[0]) if hasattr(ols_model.pvalues, "__len__") else float(ols_model.pvalues)

    return {
        "alpha": round(alpha_hat, 4),
        "t_statistic": round(t_stat, 4),
        "p_value": round(p_val, 6),
        "is_overdispersed": bool(alpha_hat > 0 and p_val < 0.05),
        "conclusion": (
            f"Cameron-Trivedi test yields alpha = {alpha_hat:.4f} (t = {t_stat:.2f}, p = {p_val:.4f}). "
            + ("Statistically significant overdispersion detected (NB2 indicated)."
               if (alpha_hat > 0 and p_val < 0.05)
               else "No statistically significant overdispersion; Poisson GLM is appropriate.")
        )
    }


def train_frequency_model():
    print("=" * 70)
    print("STARTING FREQUENCY MODEL TRAINING (Poisson GLM & Negative Binomial)")
    print("=" * 70)

    raw_path = os.path.join("data", "raw", "freMTPL2freq.csv")
    if not os.path.exists(raw_path):
        raise FileNotFoundError(f"Missing dataset at {raw_path}")

    print(f"Loading data from {raw_path}...")
    df = pd.read_csv(raw_path)
    n_total = len(df)
    print(f"Loaded {n_total} records.")

    # Actuarial exposure treatment:
    # Retain legitimate multi-year policies (Exposure > 1.0, up to 2.01).
    # Minimum clip at 0.001 for numerical stability of log(Exposure) offset.
    df["Exposure_clean"] = df["Exposure"].clip(lower=0.001)
    df["LogExposure"] = np.log(df["Exposure_clean"])
    
    # Cap ClaimNb at 4 to prevent extreme outlier leverage on GLM coefficients
    df["ClaimNb_capped"] = np.clip(df["ClaimNb"], 0, 4)

    # 80/20 train/test split with fixed seed, stratifying on claim occurrence to ensure representative test set
    train_df, test_df = train_test_split(
        df, test_size=0.20, random_state=42, stratify=(df["ClaimNb_capped"] > 0)
    )
    print(f"Train set: {len(train_df)} rows | Test set: {len(test_df)} rows")
    print(f"Train multi-year (>1.0 exposure): {(train_df['Exposure_clean'] > 1.0).sum()} policies")
    print(f"Test multi-year (>1.0 exposure): {(test_df['Exposure_clean'] > 1.0).sum()} policies")

    # Fit preprocessor on training data only
    preprocessor = ActuarialPreprocessor()
    preprocessor.fit(train_df)

    X_train = preprocessor.transform(train_df)
    X_test = preprocessor.transform(test_df)
    
    y_train = train_df["ClaimNb_capped"].values
    y_test = test_df["ClaimNb_capped"].values
    offset_train = train_df["LogExposure"].values
    offset_test = test_df["LogExposure"].values

    print(f"Design matrix shape: {X_train.shape}")
    print("Fitting Baseline Poisson GLM with log link and log-exposure offset...")
    
    glm_poisson = sm.GLM(
        y_train,
        X_train,
        family=sm.families.Poisson(),
        offset=offset_train
    )
    res_poisson = glm_poisson.fit()
    print("Poisson GLM converged successfully!")
    print(f"  Poisson Train AIC: {res_poisson.aic:.2f}, Deviance: {res_poisson.deviance:.2f}")

    # Overdispersion diagnostics on training data
    train_pred_poisson = res_poisson.predict(X_train, offset=offset_train)
    ct_results = run_cameron_trivedi_test(y_train, train_pred_poisson)
    pearson_phi = float(np.sum((y_train - train_pred_poisson) ** 2 / train_pred_poisson) / (len(y_train) - X_train.shape[1]))
    print(f"  Cameron-Trivedi Test: alpha = {ct_results['alpha']}, p-val = {ct_results['p_value']}")
    print(f"  Pearson Dispersion Phi: {pearson_phi:.4f}")

    # Fit Negative Binomial (NB2) model with offset
    nb_alpha = max(0.01, float(ct_results["alpha"])) if ct_results["is_overdispersed"] else 0.05
    print(f"Fitting Negative Binomial (NB2) GLM with alpha = {nb_alpha:.4f}...")
    glm_nb = sm.GLM(
        y_train,
        X_train,
        family=sm.families.NegativeBinomial(alpha=nb_alpha),
        offset=offset_train
    )
    res_nb = glm_nb.fit()
    print("Negative Binomial GLM converged successfully!")
    print(f"  NB2 Train Deviance: {res_nb.deviance:.2f}")

    # Evaluate both on held-out test data
    test_pred_count_poisson = res_poisson.predict(X_test, offset=offset_test)
    test_pred_count_nb = res_nb.predict(X_test, offset=offset_test)
    test_pred_annual_rate = res_poisson.predict(X_test, offset=np.zeros(len(X_test)))

    total_obs_claims = int(np.sum(y_test))
    total_exp_poisson = float(np.sum(test_pred_count_poisson))
    total_exp_nb = float(np.sum(test_pred_count_nb))
    
    oe_poisson = total_obs_claims / total_exp_poisson if total_exp_poisson > 0 else 1.0
    oe_nb = total_obs_claims / total_exp_nb if total_exp_nb > 0 else 1.0
    
    dev_poisson = compute_poisson_deviance(y_test, test_pred_count_poisson)
    dev_nb = compute_poisson_deviance(y_test, test_pred_count_nb)
    
    mae_poisson = float(np.mean(np.abs(y_test - test_pred_count_poisson)))
    mae_nb = float(np.mean(np.abs(y_test - test_pred_count_nb)))

    print("\nHeld-Out Test Evaluation:")
    print(f"  Observed Claims : {total_obs_claims}")
    print(f"  Poisson Expected: {total_exp_poisson:.2f} | O/E: {oe_poisson:.4f} | Dev: {dev_poisson:.2f} | MAE: {mae_poisson:.5f}")
    print(f"  NB2 Expected    : {total_exp_nb:.2f} | O/E: {oe_nb:.4f} | Dev: {dev_nb:.2f} | MAE: {mae_nb:.5f}")

    # Calibration across 10 predicted risk deciles (Poisson GLM)
    test_eval_df = pd.DataFrame({
        "y_true": y_test,
        "y_pred": test_pred_count_poisson,
        "exposure": test_df["Exposure_clean"].values,
        "annual_rate": test_pred_annual_rate
    })
    test_eval_df["decile"] = pd.qcut(test_eval_df["annual_rate"], q=10, labels=False, duplicates="drop")
    
    calibration_deciles = []
    for dec in range(10):
        group = test_eval_df[test_eval_df["decile"] == dec]
        if len(group) == 0:
            continue
        g_obs = float(group["y_true"].sum())
        g_exp = float(group["y_pred"].sum())
        g_oe = g_obs / g_exp if g_exp > 0 else 1.0
        g_exposure = float(group["exposure"].sum())
        calibration_deciles.append({
            "decile": dec + 1,
            "policy_count": len(group),
            "total_exposure": round(g_exposure, 2),
            "observed_claims": int(g_obs),
            "expected_claims": round(g_exp, 2),
            "observed_rate": round(g_obs / g_exposure if g_exposure > 0 else 0, 4),
            "expected_rate": round(g_exp / g_exposure if g_exposure > 0 else 0, 4),
            "oe_ratio": round(g_oe, 4)
        })

    # Save artifacts
    os.makedirs("models", exist_ok=True)
    preprocessor.save(os.path.join("models", "preprocessor.joblib"))
    
    # Save Poisson GLM artifact
    poisson_artifact = {
        "params": res_poisson.params.to_dict(),
        "bse": res_poisson.bse.to_dict(),
        "pvalues": res_poisson.pvalues.to_dict(),
        "cov_params": res_poisson.cov_params().to_dict(),
        "aic": float(res_poisson.aic),
        "bic": float(res_poisson.bic),
        "deviance": float(res_poisson.deviance),
        "df_resid": float(res_poisson.df_resid),
        "feature_columns": list(X_train.columns),
        "scale": float(res_poisson.scale)
    }
    joblib.dump(poisson_artifact, os.path.join("models", "frequency_glm.joblib"))

    # Save Negative Binomial GLM artifact
    nb_artifact = {
        "params": res_nb.params.to_dict(),
        "bse": res_nb.bse.to_dict(),
        "pvalues": res_nb.pvalues.to_dict(),
        "cov_params": res_nb.cov_params().to_dict(),
        "deviance": float(res_nb.deviance),
        "df_resid": float(res_nb.df_resid),
        "feature_columns": list(X_train.columns),
        "scale": float(res_nb.scale),
        "alpha": float(nb_alpha)
    }
    joblib.dump(nb_artifact, os.path.join("models", "frequency_nb2.joblib"))

    # Metadata report
    metadata = {
        "model_type": "Poisson GLM (Baseline) & Negative Binomial NB2 (Alternative)",
        "primary_model": "Poisson GLM",
        "family": "Poisson",
        "link": "Log",
        "offset": "log(Exposure)",
        "exposure_treatment": "Uncapped multi-year policies retained (Exposure in [0.001, 2.01])",
        "training_records": len(train_df),
        "test_records": len(test_df),
        "features": list(X_train.columns),
        "n_features": len(X_train.columns),
        "overdispersion_diagnostics": {
            "cameron_trivedi_test": ct_results,
            "pearson_dispersion_phi": round(pearson_phi, 4),
            "nb2_dispersion_alpha": round(nb_alpha, 4)
        },
        "evaluation_metrics": {
            "test_observed_claims": total_obs_claims,
            "test_expected_claims": round(total_exp_poisson, 2),
            "test_oe_ratio": round(oe_poisson, 4),
            "test_poisson_deviance": round(dev_poisson, 2),
            "test_mae": round(mae_poisson, 5),
            "train_aic": round(res_poisson.aic, 2),
            "train_deviance": round(res_poisson.deviance, 2),
            "poisson_glm": {
                "test_observed_claims": total_obs_claims,
                "test_expected_claims": round(total_exp_poisson, 2),
                "test_oe_ratio": round(oe_poisson, 4),
                "test_poisson_deviance": round(dev_poisson, 2),
                "test_mae": round(mae_poisson, 5),
                "train_aic": round(res_poisson.aic, 2),
                "train_deviance": round(res_poisson.deviance, 2)
            },
            "negative_binomial_nb2": {
                "test_observed_claims": total_obs_claims,
                "test_expected_claims": round(total_exp_nb, 2),
                "test_oe_ratio": round(oe_nb, 4),
                "test_poisson_deviance": round(dev_nb, 2),
                "test_mae": round(mae_nb, 5),
                "train_deviance": round(res_nb.deviance, 2)
            }
        },
        "calibration_deciles": calibration_deciles,
        "sample_coefficients": {
            k: round(v, 4) for k, v in list(res_poisson.params.items())[:10]
        }
    }
    with open(os.path.join("models", "frequency_metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    print("\nFrequency model artifacts and metadata saved successfully!")
    return metadata


if __name__ == "__main__":
    train_frequency_model()
