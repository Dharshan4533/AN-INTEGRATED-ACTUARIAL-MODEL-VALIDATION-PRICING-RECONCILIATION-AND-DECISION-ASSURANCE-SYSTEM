"""
Data Audit Script for French Motor TPL Datasets
Performs all 10 mandatory data audit tasks specified in the Actuarial Implementation Plan:
1. Inspect files and column names
2. Data types and missing values
3. Duplicate records
4. Claim count and exposure validation
5. Non-negative claim counts and positive exposure checks
6. Distribution of claim counts and amounts
7. Zero, negative, and extreme claim amounts
8. Policy IDs and policy-to-claim relationships
9. Policy-level records and individual claim linkage analysis
10. Documentation of filtering and preprocessing decisions
"""

import json
import os
import numpy as np
import pandas as pd

def run_audit():
    freq_path = os.path.join("data", "raw", "freMTPL2freq.csv")
    sev_path = os.path.join("data", "raw", "freMTPL2sev.csv")

    print(f"Loading datasets...\nFreq: {freq_path}\nSev: {sev_path}")
    df_freq = pd.read_csv(freq_path)
    df_sev = pd.read_csv(sev_path)

    results = {}

    # Task 1: Inspect files and column names
    results["files"] = {
        "freq_columns": list(df_freq.columns),
        "sev_columns": list(df_sev.columns),
        "freq_shape": list(df_freq.shape),
        "sev_shape": list(df_sev.shape)
    }

    # Task 2: Data types and missing values
    results["types_and_nulls"] = {
        "freq_dtypes": {col: str(dtype) for col, dtype in df_freq.dtypes.items()},
        "sev_dtypes": {col: str(dtype) for col, dtype in df_sev.dtypes.items()},
        "freq_null_counts": df_freq.isnull().sum().to_dict(),
        "sev_null_counts": df_sev.isnull().sum().to_dict()
    }

    # Task 3: Duplicate records
    freq_exact_dups = int(df_freq.duplicated().sum())
    freq_id_dups = int(df_freq["IDpol"].duplicated().sum())
    sev_exact_dups = int(df_sev.duplicated().sum())
    
    results["duplicates"] = {
        "freq_exact_duplicates": freq_exact_dups,
        "freq_id_duplicates": freq_id_dups,
        "sev_exact_duplicates": sev_exact_dups
    }

    # Task 4 & 5: Validate Claim counts and Exposure
    claimnb_counts = df_freq["ClaimNb"].value_counts().sort_index().to_dict()
    exposure_stats = {
        "min": float(df_freq["Exposure"].min()),
        "max": float(df_freq["Exposure"].max()),
        "mean": float(df_freq["Exposure"].mean()),
        "median": float(df_freq["Exposure"].median()),
        "exposure_le_0": int((df_freq["Exposure"] <= 0).sum()),
        "exposure_gt_1": int((df_freq["Exposure"] > 1.0).sum()),
        "exposure_gt_2": int((df_freq["Exposure"] > 2.0).sum()),
        "claimnb_negative": int((df_freq["ClaimNb"] < 0).sum())
    }
    results["claim_and_exposure"] = {
        "claimnb_distribution": claimnb_counts,
        "exposure_stats": exposure_stats,
        "total_exposure": float(df_freq["Exposure"].sum()),
        "total_claims_freq": int(df_freq["ClaimNb"].sum()),
        "zero_claim_policies": int((df_freq["ClaimNb"] == 0).sum()),
        "positive_claim_policies": int((df_freq["ClaimNb"] > 0).sum())
    }

    # Task 6 & 7: Claim amounts in severity dataset
    sev_stats = {
        "count": int(len(df_sev)),
        "min": float(df_sev["ClaimAmount"].min()),
        "max": float(df_sev["ClaimAmount"].max()),
        "mean": float(df_sev["ClaimAmount"].mean()),
        "median": float(df_sev["ClaimAmount"].median()),
        "quantiles": {
            "p50": float(df_sev["ClaimAmount"].quantile(0.50)),
            "p75": float(df_sev["ClaimAmount"].quantile(0.75)),
            "p90": float(df_sev["ClaimAmount"].quantile(0.90)),
            "p95": float(df_sev["ClaimAmount"].quantile(0.95)),
            "p99": float(df_sev["ClaimAmount"].quantile(0.99)),
            "p99.9": float(df_sev["ClaimAmount"].quantile(0.999))
        },
        "zero_amounts": int((df_sev["ClaimAmount"] == 0).sum()),
        "negative_amounts": int((df_sev["ClaimAmount"] < 0).sum()),
        "amounts_le_0": int((df_sev["ClaimAmount"] <= 0).sum()),
        "extreme_amounts_gt_100k": int((df_sev["ClaimAmount"] > 100000).sum()),
        "extreme_amounts_gt_1m": int((df_sev["ClaimAmount"] > 1000000).sum())
    }
    results["severity_distribution"] = sev_stats

    # Task 8: Policy IDs and Relationships
    unique_freq_ids = set(df_freq["IDpol"])
    unique_sev_ids = set(df_sev["IDpol"])

    sev_ids_in_freq = len(unique_sev_ids.intersection(unique_freq_ids))
    sev_ids_not_in_freq = len(unique_sev_ids - unique_freq_ids)
    
    # Check claim counts per ID in sev vs ClaimNb in freq
    sev_counts_per_id = df_sev.groupby("IDpol").size().to_dict()
    claims_comparison = []
    
    # Distribution of number of claims per policy in sev
    claims_per_policy_in_sev = pd.Series(list(sev_counts_per_id.values())).value_counts().to_dict()

    # Match check on policies with claims
    freq_pos_claims = df_freq[df_freq["ClaimNb"] > 0].set_index("IDpol")["ClaimNb"].to_dict()
    
    matched_exact = 0
    sev_gt_freq = 0
    freq_gt_sev = 0
    not_in_sev = 0

    for pol_id, freq_claims in freq_pos_claims.items():
        if pol_id not in sev_counts_per_id:
            not_in_sev += 1
        else:
            sev_c = sev_counts_per_id[pol_id]
            if sev_c == freq_claims:
                matched_exact += 1
            elif sev_c > freq_claims:
                sev_gt_freq += 1
            else:
                freq_gt_sev += 1

    results["linkage_analysis"] = {
        "unique_freq_ids": len(unique_freq_ids),
        "unique_sev_ids": len(unique_sev_ids),
        "sev_ids_in_freq": sev_ids_in_freq,
        "sev_ids_not_in_freq": sev_ids_not_in_freq,
        "claims_per_policy_distribution_in_sev": claims_per_policy_in_sev,
        "positive_freq_policy_matches": {
            "total_positive_in_freq": len(freq_pos_claims),
            "matched_exact": matched_exact,
            "sev_records_greater_than_freq_claimnb": sev_gt_freq,
            "freq_claimnb_greater_than_sev_records": freq_gt_sev,
            "in_freq_with_claims_but_no_sev_record": not_in_sev
        }
    }

    # Categorical distributions in freq
    categorical_cols = ["Area", "VehPower", "VehBrand", "VehGas", "Region"]
    results["categoricals"] = {}
    for col in categorical_cols:
        results["categoricals"][col] = df_freq[col].value_counts().to_dict()

    # Numerical feature stats
    numerical_cols = ["VehAge", "DrivAge", "BonusMalus", "Density"]
    results["numericals"] = {}
    for col in numerical_cols:
        results["numericals"][col] = {
            "min": float(df_freq[col].min()),
            "max": float(df_freq[col].max()),
            "mean": float(df_freq[col].mean()),
            "median": float(df_freq[col].median()),
            "q25": float(df_freq[col].quantile(0.25)),
            "q75": float(df_freq[col].quantile(0.75)),
            "q99": float(df_freq[col].quantile(0.99))
        }

    # Save summary report as JSON
    out_file = os.path.join("docs", "data_audit_report.json")
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)

    print("\n--- DATA AUDIT SUMMARY ---")
    print(f"Freq records: {df_freq.shape[0]}, Columns: {df_freq.shape[1]}")
    print(f"Sev records: {df_sev.shape[0]}, Columns: {df_sev.shape[1]}")
    print(f"Freq zero claims: {results['claim_and_exposure']['zero_claim_policies']} ({results['claim_and_exposure']['zero_claim_policies']/len(df_freq)*100:.2f}%)")
    print(f"Freq positive claims: {results['claim_and_exposure']['positive_claim_policies']} ({results['claim_and_exposure']['positive_claim_policies']/len(df_freq)*100:.2f}%)")
    print(f"Exposure > 1.0 count: {results['claim_and_exposure']['exposure_stats']['exposure_gt_1']}")
    print(f"Exposure <= 0 count: {results['claim_and_exposure']['exposure_stats']['exposure_le_0']}")
    print(f"Sev <= 0 ClaimAmount count: {results['severity_distribution']['amounts_le_0']}")
    print(f"Sev ClaimAmount min: {results['severity_distribution']['min']}, median: {results['severity_distribution']['median']}, mean: {results['severity_distribution']['mean']:.2f}, max: {results['severity_distribution']['max']:.2f}")
    print(f"Report saved to {out_file}")

if __name__ == "__main__":
    run_audit()
