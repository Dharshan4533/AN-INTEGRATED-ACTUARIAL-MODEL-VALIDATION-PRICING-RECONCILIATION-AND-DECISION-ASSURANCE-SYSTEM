"""
Automated Data-Quality and Prediction-Readiness Gate.
Enforces 10 explicit actuarial data-quality verification rules before model training,
prediction, premium calculation, or portfolio simulation.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from actuarial.preprocessing import FEATURE_RANGES, VALID_CATEGORIES


class DataQualityFinding(BaseModel):
    rule_id: str
    severity: str  # "CRITICAL", "WARNING", "INFO"
    title: str
    description: str
    affected_records_count: int = 0
    sample_affected_indices: List[Any] = Field(default_factory=list)
    recommended_remediation: str


class DataQualityReport(BaseModel):
    status: str  # "PASSED", "WARNINGS", "FAILED"
    is_prediction_ready: bool
    total_records_checked: int
    total_findings: int
    critical_count: int
    warning_count: int
    info_count: int
    findings: List[DataQualityFinding]
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DataQualityGate:
    """
    Actuarial Data-Quality Gate evaluating datasets or individual policies
    against 10 pre-flight validation rules.
    """

    REQUIRED_FREQ_COLUMNS = [
        "Area", "VehPower", "VehAge", "DrivAge", "BonusMalus",
        "VehBrand", "VehGas", "Density", "Region", "Exposure"
    ]

    REQUIRED_SEV_COLUMNS = ["IDpol", "ClaimAmount"]

    def __init__(self, reference_schema: Optional[Dict[str, Any]] = None):
        self.reference_schema = reference_schema

    def validate_policy(self, policy: Dict[str, Any]) -> DataQualityReport:
        """Validate a single policy input dictionary before rating or what-if calculation."""
        df = pd.DataFrame([policy])
        return self.validate_frequency_dataset(df, is_single_policy=True)

    def validate_frequency_dataset(
        self,
        df: pd.DataFrame,
        is_single_policy: bool = False
    ) -> DataQualityReport:
        """
        Validate frequency / policy portfolio dataset against 10 pre-flight rules.
        """
        findings: List[DataQualityFinding] = []
        n_records = len(df)

        # ----------------------------------------------------
        # Rule 1: SCHEMA_CONFORMITY
        # ----------------------------------------------------
        missing_cols = [c for c in self.REQUIRED_FREQ_COLUMNS if c not in df.columns]
        if missing_cols:
            findings.append(DataQualityFinding(
                rule_id="RULE_01_SCHEMA_CONFORMITY",
                severity="CRITICAL",
                title="Missing Required Columns",
                description=f"Dataset is missing required feature columns: {missing_cols}",
                affected_records_count=n_records,
                sample_affected_indices=[],
                recommended_remediation=f"Ensure input contains all required columns: {self.REQUIRED_FREQ_COLUMNS}."
            ))

        # ----------------------------------------------------
        # Rule 2: MISSING_VALUES
        # ----------------------------------------------------
        null_counts = df.isnull().sum()
        cols_with_nulls = null_counts[null_counts > 0]
        if not cols_with_nulls.empty:
            for col, count in cols_with_nulls.items():
                pct = (count / n_records) * 100.0
                sev = "CRITICAL" if is_single_policy or pct > 1.0 else "WARNING"
                null_indices = df[df[col].isnull()].index[:5].tolist()
                findings.append(DataQualityFinding(
                    rule_id="RULE_02_MISSING_VALUES",
                    severity=sev,
                    title=f"Missing Values in '{col}'",
                    description=f"Column '{col}' has {count} missing records ({pct:.2f}%).",
                    affected_records_count=int(count),
                    sample_affected_indices=null_indices,
                    recommended_remediation="Impute missing values using reference mode/median or rectify data ingestion pipeline."
                ))

        # ----------------------------------------------------
        # Rule 3: IDPOL_UNIQUENESS
        # ----------------------------------------------------
        if "IDpol" in df.columns and not is_single_policy:
            dup_mask = df["IDpol"].duplicated()
            dup_count = int(dup_mask.sum())
            if dup_count > 0:
                sample_dups = df.loc[dup_mask, "IDpol"].head(5).tolist()
                findings.append(DataQualityFinding(
                    rule_id="RULE_03_IDPOL_UNIQUENESS",
                    severity="CRITICAL",
                    title="Duplicate Policy Identifiers",
                    description=f"Found {dup_count} duplicate IDpol records in policy dataset.",
                    affected_records_count=dup_count,
                    sample_affected_indices=sample_dups,
                    recommended_remediation="Deduplicate policy records or consolidate multi-period exposures before model estimation."
                ))

        # ----------------------------------------------------
        # Rule 4: EXPOSURE_VALIDITY
        # ----------------------------------------------------
        if "Exposure" in df.columns:
            try:
                exp_vals = pd.to_numeric(df["Exposure"], errors="coerce")
                neg_zero_mask = (exp_vals <= 0) | exp_vals.isnull()
                neg_zero_count = int(neg_zero_mask.sum())
                if neg_zero_count > 0:
                    findings.append(DataQualityFinding(
                        rule_id="RULE_04_EXPOSURE_VALIDITY",
                        severity="CRITICAL",
                        title="Non-Positive Policy Exposure",
                        description=f"Found {neg_zero_count} records with Exposure <= 0 or non-numeric values.",
                        affected_records_count=neg_zero_count,
                        sample_affected_indices=df.index[neg_zero_mask][:5].tolist(),
                        recommended_remediation="Filter or correct policies with non-positive exposure; log-link offset requires exposure > 0."
                    ))

                multi_year_mask = exp_vals > 1.0
                multi_year_count = int(multi_year_mask.sum())
                if multi_year_count > 0:
                    findings.append(DataQualityFinding(
                        rule_id="RULE_04_EXPOSURE_MULTI_YEAR",
                        severity="INFO",
                        title="Multi-Year Policy Exposure Detected",
                        description=f"{multi_year_count} policies have Exposure > 1.0 (up to {exp_vals.max():.2f} years).",
                        affected_records_count=multi_year_count,
                        sample_affected_indices=df.index[multi_year_mask][:5].tolist(),
                        recommended_remediation="Informational: Multi-year policies are retained and offset correctly; verify term coverage."
                    ))
            except Exception as e:
                findings.append(DataQualityFinding(
                    rule_id="RULE_04_EXPOSURE_PARSE_ERROR",
                    severity="CRITICAL",
                    title="Exposure Column Parse Error",
                    description=str(e),
                    affected_records_count=n_records,
                    recommended_remediation="Ensure Exposure column contains valid floating point numbers."
                ))

        # ----------------------------------------------------
        # Rule 5: CLAIM_COUNT_VALIDITY
        # ----------------------------------------------------
        if "ClaimNb" in df.columns:
            try:
                claim_vals = pd.to_numeric(df["ClaimNb"], errors="coerce")
                neg_claim_mask = (claim_vals < 0) | claim_vals.isnull()
                neg_claim_count = int(neg_claim_mask.sum())
                if neg_claim_count > 0:
                    findings.append(DataQualityFinding(
                        rule_id="RULE_05_CLAIM_COUNT_VALIDITY",
                        severity="CRITICAL",
                        title="Negative or Invalid Claim Count",
                        description=f"Found {neg_claim_count} records with ClaimNb < 0.",
                        affected_records_count=neg_claim_count,
                        sample_affected_indices=df.index[neg_claim_mask][:5].tolist(),
                        recommended_remediation="Claim counts must be non-negative integers."
                    ))

                high_claim_mask = claim_vals > 4
                high_claim_count = int(high_claim_mask.sum())
                if high_claim_count > 0:
                    findings.append(DataQualityFinding(
                        rule_id="RULE_05_HIGH_CLAIM_OUTLIERS",
                        severity="WARNING",
                        title="High Claim Count Outliers",
                        description=f"Found {high_claim_count} records with ClaimNb > 4 (max = {claim_vals.max()}).",
                        affected_records_count=high_claim_count,
                        sample_affected_indices=df.index[high_claim_mask][:5].tolist(),
                        recommended_remediation="Consider capping at 4 claims during GLM training to prevent extreme outlier leverage."
                    ))
            except Exception as e:
                findings.append(DataQualityFinding(
                    rule_id="RULE_05_CLAIM_PARSE_ERROR",
                    severity="CRITICAL",
                    title="ClaimNb Parse Error",
                    description=str(e),
                    affected_records_count=n_records,
                    recommended_remediation="Ensure ClaimNb column contains valid integer values."
                ))

        # ----------------------------------------------------
        # Rule 8: FEATURE_RANGE_BOUNDS
        # ----------------------------------------------------
        for col, bounds in FEATURE_RANGES.items():
            if col in df.columns and col != "Exposure":
                try:
                    num_s = pd.to_numeric(df[col], errors="coerce")
                    b_min = bounds["min"]
                    b_max = bounds["max"]
                    out_mask = (num_s < b_min) | (num_s > b_max)
                    out_count = int(out_mask.sum())
                    if out_count > 0:
                        sev = "WARNING" if not is_single_policy else "CRITICAL"
                        findings.append(DataQualityFinding(
                            rule_id=f"RULE_08_RANGE_{col.upper()}",
                            severity=sev,
                            title=f"Out of Range Feature: '{col}'",
                            description=(
                                f"{out_count} records for '{col}' fall outside actuarial domain range [{b_min}, {b_max}]. "
                                f"Observed values range from {num_s.min()} to {num_s.max()}."
                            ),
                            affected_records_count=out_count,
                            sample_affected_indices=df.index[out_mask][:5].tolist(),
                            recommended_remediation=f"Clip or validate '{col}' to legitimate bounds [{b_min}, {b_max}]."
                        ))
                except Exception:
                    pass

        # ----------------------------------------------------
        # Rule 9: CATEGORICAL_DOMAIN_VALIDITY
        # ----------------------------------------------------
        for col, valid_set in VALID_CATEGORIES.items():
            if col in df.columns:
                str_s = df[col].astype(str)
                valid_str_set = set(str(v) for v in valid_set)
                unseen_mask = ~str_s.isin(valid_str_set)
                unseen_count = int(unseen_mask.sum())
                if unseen_count > 0:
                    sample_unseen = str_s[unseen_mask].unique()[:5].tolist()
                    sev = "WARNING"
                    findings.append(DataQualityFinding(
                        rule_id=f"RULE_09_CATEGORY_{col.upper()}",
                        severity=sev,
                        title=f"Unseen Categorical Levels in '{col}'",
                        description=f"Found {unseen_count} records with categories not in training domain: {sample_unseen}.",
                        affected_records_count=unseen_count,
                        sample_affected_indices=sample_unseen,
                        recommended_remediation=f"Map unexpected categories in '{col}' to baseline modal level ({valid_set[0]})."
                    ))

        # ----------------------------------------------------
        # Rule 10: SCHEMA_DRIFT
        # ----------------------------------------------------
        if self.reference_schema:
            ref_cols = set(self.reference_schema.get("feature_columns", []))
            curr_cols = set(df.columns)
            diff = ref_cols - curr_cols
            if diff:
                findings.append(DataQualityFinding(
                    rule_id="RULE_10_SCHEMA_DRIFT",
                    severity="CRITICAL",
                    title="Schema Drift: Missing Reference Columns",
                    description=f"Input is missing columns required by trained reference model: {list(diff)}",
                    affected_records_count=n_records,
                    recommended_remediation="Align input schema with model reference specification."
                ))

        # Aggregate summary
        criticals = sum(1 for f in findings if f.severity == "CRITICAL")
        warnings = sum(1 for f in findings if f.severity == "WARNING")
        infos = sum(1 for f in findings if f.severity == "INFO")

        if criticals > 0:
            status = "FAILED"
            ready = False
        elif warnings > 0:
            status = "WARNINGS"
            ready = True
        else:
            status = "PASSED"
            ready = True

        return DataQualityReport(
            status=status,
            is_prediction_ready=ready,
            total_records_checked=n_records,
            total_findings=len(findings),
            critical_count=criticals,
            warning_count=warnings,
            info_count=infos,
            findings=findings
        )

    def validate_severity_dataset(
        self,
        df_sev: pd.DataFrame,
        df_freq: Optional[pd.DataFrame] = None
    ) -> DataQualityReport:
        """
        Validate severity claim dataset (ClaimAmount, linkage to frequency table).
        """
        findings: List[DataQualityFinding] = []
        n_records = len(df_sev)

        # Rule 1: Schema conformity
        missing_cols = [c for c in self.REQUIRED_SEV_COLUMNS if c not in df_sev.columns]
        if missing_cols:
            findings.append(DataQualityFinding(
                rule_id="RULE_01_SCHEMA_CONFORMITY",
                severity="CRITICAL",
                title="Missing Required Severity Columns",
                description=f"Missing columns: {missing_cols}",
                affected_records_count=n_records,
                recommended_remediation=f"Severity file must contain columns: {self.REQUIRED_SEV_COLUMNS}."
            ))

        # Rule 6: CLAIM_AMOUNT_VALIDITY
        if "ClaimAmount" in df_sev.columns:
            amounts = pd.to_numeric(df_sev["ClaimAmount"], errors="coerce")
            non_pos_mask = (amounts <= 0) | amounts.isnull()
            non_pos_count = int(non_pos_mask.sum())
            if non_pos_count > 0:
                findings.append(DataQualityFinding(
                    rule_id="RULE_06_CLAIM_AMOUNT_NON_POSITIVE",
                    severity="CRITICAL",
                    title="Non-Positive Claim Amounts",
                    description=f"Found {non_pos_count} claims with ClaimAmount <= 0. Gamma GLM requires strictly positive values.",
                    affected_records_count=non_pos_count,
                    sample_affected_indices=df_sev.index[non_pos_mask][:5].tolist(),
                    recommended_remediation="Filter out zero and negative claim adjustment records before severity modeling."
                ))

            # Extreme bodily injury claims check (> 1,000,000 EUR)
            extreme_mask = amounts > 1000000.0
            extreme_count = int(extreme_mask.sum())
            if extreme_count > 0:
                findings.append(DataQualityFinding(
                    rule_id="RULE_06_EXTREME_BODILY_INJURY",
                    severity="INFO",
                    title="Extreme Bodily Injury Claims (> €1,000,000)",
                    description=f"Found {extreme_count} catastrophic claims exceeding 1,000,000 EUR (max = {amounts.max():.2f} EUR).",
                    affected_records_count=extreme_count,
                    sample_affected_indices=df_sev.index[extreme_mask][:5].tolist(),
                    recommended_remediation="Isolate catastrophic bodily injury claims above threshold u* for non-overlapping large-loss loading."
                ))

        # Rule 7: LINKAGE_INTEGRITY
        if df_freq is not None and "IDpol" in df_sev.columns and "IDpol" in df_freq.columns:
            freq_ids = set(df_freq["IDpol"].unique())
            sev_ids = set(df_sev["IDpol"].unique())
            orphan_ids = sev_ids - freq_ids
            orphan_count = len(orphan_ids)
            if orphan_count > 0:
                findings.append(DataQualityFinding(
                    rule_id="RULE_07_LINKAGE_INTEGRITY",
                    severity="WARNING",
                    title="Orphan Claim Records Without Policy Profile",
                    description=f"{orphan_count} claim IDpol identifiers do not exist in the policyholder frequency dataset.",
                    affected_records_count=orphan_count,
                    sample_affected_indices=list(orphan_ids)[:5],
                    recommended_remediation="Review data ingestion joins; orphan claims cannot be conditioned on policyholder risk features."
                ))

        criticals = sum(1 for f in findings if f.severity == "CRITICAL")
        warnings = sum(1 for f in findings if f.severity == "WARNING")
        infos = sum(1 for f in findings if f.severity == "INFO")

        return DataQualityReport(
            status="FAILED" if criticals > 0 else ("WARNINGS" if warnings > 0 else "PASSED"),
            is_prediction_ready=bool(criticals == 0),
            total_records_checked=n_records,
            total_findings=len(findings),
            critical_count=criticals,
            warning_count=warnings,
            info_count=infos,
            findings=findings
        )
