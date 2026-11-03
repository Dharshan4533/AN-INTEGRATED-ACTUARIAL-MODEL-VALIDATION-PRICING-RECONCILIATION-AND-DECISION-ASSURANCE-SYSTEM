"""
Actuarial Fairness and Segment Calibration Audit Module.
Evaluates model calibration (O/E), rate disparities, and statistical confidence bounds
across Driver Age cohorts and Geographic Rating Territories on held-out test data.
"""

import json
import os
from typing import Dict, List, Any
import numpy as np
import pandas as pd
from actuarial.preprocessing import ActuarialPreprocessor


def compute_segment_metrics(
    df_eval: pd.DataFrame,
    segment_col: str,
    benchmark_level: str = None
) -> List[Dict[str, Any]]:
    """
    Compute segment-level actuarial metrics:
    - Policy count (n)
    - Total Exposure (years)
    - Observed claims (O)
    - Expected claims (E)
    - Calibration O/E ratio with 95% Poisson confidence interval
    - Mean predicted annualized pure premium
    - Disparity ratio relative to benchmark group
    """
    results = []
    
    # Calculate benchmark mean premium if specified
    overall_mean_prem = float(df_eval["pure_premium"].mean())
    benchmark_mean_prem = overall_mean_prem
    if benchmark_level and benchmark_level in df_eval[segment_col].values:
        benchmark_mean_prem = float(df_eval.loc[df_eval[segment_col] == benchmark_level, "pure_premium"].mean())

    for val, grp in df_eval.groupby(segment_col):
        n = len(grp)
        exp = float(grp["exposure"].sum())
        obs = float(grp["y_true"].sum())
        expected = float(grp["y_pred"].sum())
        oe = obs / expected if expected > 0 else 1.0
        
        # 95% Poisson confidence interval for observed rate: obs / exp
        # Using exact chi-squared / gamma or normal approximation
        rate = obs / exp if exp > 0 else 0.0
        se_rate = np.sqrt(obs) / exp if exp > 0 else 0.0
        rate_lower = max(0.0, rate - 1.96 * se_rate)
        rate_upper = rate + 1.96 * se_rate

        # 95% CI for O/E ratio
        se_oe = np.sqrt(obs) / expected if expected > 0 else 0.0
        oe_lower = max(0.0, oe - 1.96 * se_oe)
        oe_upper = oe + 1.96 * se_oe

        mean_prem = float(grp["pure_premium"].mean())
        disparity_ratio = mean_prem / benchmark_mean_prem if benchmark_mean_prem > 0 else 1.0

        results.append({
            "segment_name": str(val),
            "policy_count": n,
            "exposure_years": round(exp, 2),
            "observed_claims": int(obs),
            "expected_claims": round(expected, 2),
            "observed_claim_rate": round(rate, 4),
            "rate_ci_95": [round(rate_lower, 4), round(rate_upper, 4)],
            "oe_ratio": round(oe, 4),
            "oe_ci_95": [round(oe_lower, 4), round(oe_upper, 4)],
            "mean_annual_pure_premium": round(mean_prem, 2),
            "disparity_ratio_vs_benchmark": round(disparity_ratio, 4),
            "sample_size_adequate": bool(n >= 100 and obs >= 10)
        })

    return results


def run_fairness_audit(output_path: str = "models/fairness_audit_report.json") -> Dict[str, Any]:
    """Execute complete demographic and territorial fairness audit."""
    print("=" * 70)
    print("STARTING ACTUARIAL FAIRNESS & SEGMENT CALIBRATION AUDIT")
    print("=" * 70)

    import joblib
    from sklearn.model_selection import train_test_split

    freq_path = os.path.join("data", "raw", "freMTPL2freq.csv")
    if not os.path.exists(freq_path):
        raise FileNotFoundError(f"Missing {freq_path}")

    df_freq = pd.read_csv(freq_path)
    df_freq["Exposure_clean"] = df_freq["Exposure"].clip(lower=0.001)
    df_freq["LogExposure"] = np.log(df_freq["Exposure_clean"])
    df_freq["ClaimNb_capped"] = np.clip(df_freq["ClaimNb"], 0, 4)

    # Held-out 20% test partition (exact seed 42)
    _, test_df = train_test_split(
        df_freq, test_size=0.20, random_state=42, stratify=(df_freq["ClaimNb_capped"] > 0)
    )

    preprocessor = ActuarialPreprocessor.load("models/preprocessor.joblib")
    freq_model = joblib.load("models/frequency_glm.joblib")
    sev_model = joblib.load("models/severity_glm.joblib")

    X_test = preprocessor.transform(test_df)
    
    # Predict frequencies and severities
    f_params = np.array([freq_model["params"].get(col, 0.0) for col in X_test.columns])
    s_params = np.array([sev_model["params"].get(col, 0.0) for col in X_test.columns])

    lin_f = np.dot(X_test.values, f_params)
    lin_s = np.dot(X_test.values, s_params)

    pred_rates = np.exp(lin_f)
    pred_counts = pred_rates * test_df["Exposure_clean"].values
    pred_sevs = np.exp(lin_s)
    pure_prems = pred_rates * pred_sevs

    # Construct evaluation dataframe
    eval_df = test_df.copy()
    eval_df["y_true"] = test_df["ClaimNb_capped"].values
    eval_df["y_pred"] = pred_counts
    eval_df["exposure"] = test_df["Exposure_clean"].values
    eval_df["pure_premium"] = pure_prems

    # Create age cohorts
    eval_df["AgeCohort"] = pd.cut(
        eval_df["DrivAge"],
        bins=[17, 25, 45, 65, 120],
        labels=["Youth (<25)", "Prime (25-45)", "Mature (45-65)", "Senior (65+)"]
    )

    # Neutral territorial labels: Area A to Area F
    eval_df["AreaNeutral"] = "Territory Area " + eval_df["Area"].astype(str)

    # Run segment audits
    age_audit = compute_segment_metrics(eval_df, "AgeCohort", benchmark_level="Prime (25-45)")
    area_audit = compute_segment_metrics(eval_df, "AreaNeutral", benchmark_level="Territory Area C")

    report = {
        "dataset_origin": "French Motor Third-Party Liability Insurance (freMTPL2)",
        "evaluation_partition": "Held-out 20% test set (135,603 policyholders)",
        "audit_objective": "Model calibration (O/E) and segment parity auditing across demographic and geographic cohorts",
        "regulatory_disclaimer": (
            "Fairness and disparity metrics represent diagnostic signals for actuarial model validation and segment auditing. "
            "They do not constitute legal determinations of discrimination under insurance law."
        ),
        "demographic_cohort_audit": {
            "factor_name": "Driver Age Cohorts",
            "benchmark_group": "Prime (25-45)",
            "segments": age_audit
        },
        "geographic_territory_audit": {
            "factor_name": "Geographic Rating Territories (Neutral Territorial Codes)",
            "benchmark_group": "Territory Area C",
            "segments": area_audit,
            "neutrality_note": (
                "Area codes A through F reflect neutral administrative density and geographic classifications "
                "adhering strictly to neutral territorial code reporting standards."
            )
        }
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Fairness audit complete. Saved to {output_path}")
    return report


if __name__ == "__main__":
    run_fairness_audit()
