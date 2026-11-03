"""
Immutable Model-Run Registry Service.
Records execution provenance, input snapshots, model artifact hashes,
unrounded calculation traces, and verifies replay reproducibility within 10^-6.
"""

import hashlib
import json
import os
import platform
import sys
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import numpy as np

from backend.services.audit_ledger import (
    audit_ledger,
    AuditLedger,
    compute_replay_token,
    canonical_json_dumps,
    LedgerVerificationResult,
)


class RunRegistry:
    def __init__(self, runs_dir: str = "runs"):
        self.runs_dir = runs_dir
        os.makedirs(self.runs_dir, exist_ok=True)
        self.audit_ledger = AuditLedger(os.path.join(self.runs_dir, "audit_ledger.jsonl"))

    @staticmethod
    def compute_file_hash(filepath: str) -> str:
        """Compute SHA-256 hash of a file."""
        if not os.path.exists(filepath):
            return "FILE_NOT_FOUND"
        hasher = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def get_environment_metadata(self) -> Dict[str, Any]:
        """Capture Python runtime and library versions."""
        import pandas as pd
        import sklearn
        import statsmodels

        return {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "packages": {
                "numpy": np.__version__,
                "pandas": pd.__version__,
                "statsmodels": statsmodels.__version__,
                "scikit_learn": sklearn.__version__,
            }
        }

    def get_artifact_checksums(self) -> Dict[str, str]:
        """Compute SHA-256 hashes for all deployed actuarial models and datasets."""
        paths = {
            "preprocessor": os.path.join("models", "preprocessor.joblib"),
            "frequency_glm": os.path.join("models", "frequency_glm.joblib"),
            "severity_glm": os.path.join("models", "severity_glm.joblib"),
            "frequency_nb2": os.path.join("models", "frequency_nb2.joblib"),
            "hgb_poisson": os.path.join("models", "hgb_poisson.joblib"),
            "hgb_gamma": os.path.join("models", "hgb_gamma.joblib"),
            "freMTPL2freq": os.path.join("data", "raw", "freMTPL2freq.csv"),
            "freMTPL2sev": os.path.join("data", "raw", "freMTPL2sev.csv"),
        }
        return {k: self.compute_file_hash(p) for k, p in paths.items()}

    def record_run(
        self,
        run_type: str,
        inputs: Dict[str, Any],
        assumptions: Dict[str, Any],
        calculation_trace: Dict[str, float],
        outputs: Dict[str, Any],
        user_notes: Optional[str] = None
    ) -> str:
        """
        Record an immutable execution run with unrounded calculation trace.
        Returns the generated Run ID.
        """
        now = datetime.now(timezone.utc)
        run_id = f"run_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        
        record = {
            "run_id": run_id,
            "timestamp": now.isoformat(),
            "run_type": run_type,
            "user_notes": user_notes or "Standard actuarial execution",
            "artifact_checksums": self.get_artifact_checksums(),
            "environment": self.get_environment_metadata(),
            "inputs": inputs,
            "assumptions": assumptions,
            "unrounded_calculation_trace": calculation_trace,
            "outputs": outputs
        }

        run_file = os.path.join(self.runs_dir, f"{run_id}.json")
        with open(run_file, "w") as f:
            json.dump(record, f, indent=2)

        # Append to hash-chained audit ledger
        self.audit_ledger.append_entry(
            run_id=run_id,
            run_type=run_type,
            payload={
                "inputs": inputs,
                "assumptions": assumptions,
                "unrounded_calculation_trace": calculation_trace,
                "outputs": outputs,
                "artifact_checksums": record["artifact_checksums"],
                "environment": record["environment"],
            }
        )

        return run_id

    def record_rate_change_run(
        self,
        old_manual_spec: Dict[str, Any],
        new_manual_spec: Dict[str, Any],
        census_records: List[Dict[str, Any]],
        reconciliation_summary: Dict[str, Any],
        verification_summary: Optional[Dict[str, Any]] = None,
        auth_key: Optional[str] = None,
        user_notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Record a Rate Change Assurance run in both run storage and hash-chained audit ledger.
        Generates canonical replay token and returns run summary with hash.
        """
        from rating.spec_loader import compute_spec_hash

        now = datetime.now(timezone.utc)
        run_id = f"rate_change_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

        old_manual_hash = compute_spec_hash(old_manual_spec)
        new_manual_hash = compute_spec_hash(new_manual_spec)
        census_canonical = canonical_json_dumps(census_records)
        census_hash = hashlib.sha256(census_canonical.encode("utf-8")).hexdigest()

        # Build replay payload to enforce deterministic reproducibility
        pipeline_conf = new_manual_spec.get("calculation_pipeline", [])
        replay_payload = {
            "schema_version": "1.0.0",
            "old_manual_hash": old_manual_hash,
            "new_manual_hash": new_manual_hash,
            "census_hash": census_hash,
            "pipeline_configuration": pipeline_conf,
            "rounding_rule": {
                "method": new_manual_spec.get("rounding_rule", "ROUND_HALF_UP"),
                "precision": new_manual_spec.get("rounding_precision", 2),
            },
            "currency": new_manual_spec.get("currency", "USD"),
            "software_versions": {
                "python": sys.version.split()[0],
                "rating_engine": "1.0.0",
            },
            "execution_settings": {
                "decimal_context_precision": 28,
            }
        }
        replay_token = compute_replay_token(replay_payload)

        record_payload = {
            "old_manual_id": old_manual_spec.get("manual_id"),
            "old_manual_hash": old_manual_hash,
            "new_manual_id": new_manual_spec.get("manual_id"),
            "new_manual_hash": new_manual_hash,
            "census_count": len(census_records),
            "census_hash": census_hash,
            "replay_token": replay_token,
            "replay_payload": replay_payload,
            "reconciliation_summary": reconciliation_summary,
            "verification_summary": verification_summary or {},
            "environment": self.get_environment_metadata(),
        }

        # Write run record file
        full_record = {
            "run_id": run_id,
            "timestamp": now.isoformat(),
            "run_type": "RATE_CHANGE_ASSURANCE",
            "user_notes": user_notes or "Rate change assurance evaluation",
            **record_payload
        }
        run_file = os.path.join(self.runs_dir, f"{run_id}.json")
        with open(run_file, "w", encoding="utf-8") as f:
            json.dump(full_record, f, indent=2)

        # Append to hash-chained audit ledger
        ledger_entry = self.audit_ledger.append_entry(
            run_id=run_id,
            run_type="RATE_CHANGE_ASSURANCE",
            payload=record_payload,
            auth_key=auth_key,
        )

        return {
            "run_id": run_id,
            "timestamp": full_record["timestamp"],
            "replay_token": replay_token,
            "entry_hash": ledger_entry["entry_hash"],
            "prev_hash": ledger_entry["prev_hash"],
            "record_index": ledger_entry["record_index"],
        }

    def verify_audit_ledger(
        self,
        auth_key: Optional[str] = None,
        expected_tip_hash: Optional[str] = None
    ) -> LedgerVerificationResult:
        """Verifies the cryptographic integrity of the entire audit ledger."""
        return self.audit_ledger.verify_ledger_integrity(
            auth_key=auth_key,
            expected_tip_hash=expected_tip_hash
        )

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve stored run record by ID."""
        run_file = os.path.join(self.runs_dir, f"{run_id}.json")
        if not os.path.exists(run_file):
            return None
        with open(run_file, "r") as f:
            return json.load(f)

    def list_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List summary of recorded runs sorted by recency."""
        files = [f for f in os.listdir(self.runs_dir) if f.endswith(".json")]
        files.sort(reverse=True)
        summaries = []
        for fn in files[:limit]:
            p = os.path.join(self.runs_dir, fn)
            try:
                with open(p, "r") as f:
                    rec = json.load(f)
                    summaries.append({
                        "run_id": rec.get("run_id"),
                        "timestamp": rec.get("timestamp"),
                        "run_type": rec.get("run_type"),
                        "total_premium": rec.get("outputs", {}).get("total_payable_premium") or rec.get("outputs", {}).get("premium_b"),
                        "currency": rec.get("outputs", {}).get("currency", "EUR")
                    })
            except Exception:
                continue
        return summaries

    def replay_run(self, run_id: str) -> Dict[str, Any]:
        """
        Replay an execution run from its inputs, re-evaluating the actuarial pipeline
        and asserting reproducibility within epsilon = 10^-6.
        """
        rec = self.get_run(run_id)
        if not rec:
            raise KeyError(f"Run ID '{run_id}' not found.")

        from backend.services.pricing_service import pricing_service
        from actuarial.pricing import ActuarialPricingEngine
        from backend.schemas.pricing_schema import PolicyInput

        inputs = rec["inputs"]
        assumptions = rec["assumptions"]
        stored_trace = rec["unrounded_calculation_trace"]
        run_type = rec.get("run_type", "QUOTE")

        if run_type == "RECONCILIATION":
            from backend.services.reconciliation_service import reconciliation_service
            p_a = PolicyInput(**inputs["policy_a"])
            p_b = PolicyInput(**inputs["policy_b"])
            assump_a = assumptions.get("assumptions_a", {})
            assump_b = assumptions.get("assumptions_b", {})
            m_a = inputs.get("model_family_a", "poisson")
            m_b = inputs.get("model_family_b", "poisson")

            p0, _ = reconciliation_service._evaluate_state(p_a, m_a, float(p_a.Exposure), assump_a)
            p5, _ = reconciliation_service._evaluate_state(p_b, m_b, float(p_b.Exposure), assump_b)
            replayed_unrounded_diff = p5 - p0

            stored_diff = stored_trace.get("total_difference", 0.0)
            abs_diff = abs(replayed_unrounded_diff - stored_diff)
            is_reproducible = bool(abs_diff <= 1e-6)

            return {
                "run_id": run_id,
                "run_type": run_type,
                "replayed_timestamp": datetime.now(timezone.utc).isoformat(),
                "stored_total_premium": stored_diff,
                "replayed_total_premium": replayed_unrounded_diff,
                "absolute_difference": abs_diff,
                "tolerance_epsilon": 1e-6,
                "is_reproducible": is_reproducible,
                "current_checksums_match": bool(
                    self.get_artifact_checksums()["frequency_glm"] == rec["artifact_checksums"].get("frequency_glm")
                ),
                "replayed_components": {
                    "policy_a_premium": round(p0, 2),
                    "policy_b_premium": round(p5, 2),
                    "total_difference": round(replayed_unrounded_diff, 2),
                    "unrounded_difference": replayed_unrounded_diff
                }
            }

        # Single policy quote replay
        policy_data = inputs.get("policy", inputs.get("policy_a"))
        policy = PolicyInput(**policy_data)
        assump = assumptions if "fixed_expense" in assumptions else assumptions.get("assumptions_a", {})
        engine = ActuarialPricingEngine(assump)

        X_design = pricing_service.preprocessor.transform_single(policy.model_dump())
        freq_params = np.array([pricing_service.freq_model["params"].get(col, 0.0) for col in X_design.columns])
        lin_pred_freq = float(np.dot(X_design.values[0], freq_params))
        replayed_freq = float(np.exp(lin_pred_freq))

        sev_params = np.array([pricing_service.sev_model["params"].get(col, 0.0) for col in X_design.columns])
        lin_pred_sev = float(np.dot(X_design.values[0], sev_params))
        replayed_sev = float(np.exp(lin_pred_sev))

        exposure = float(policy.Exposure)
        replayed_pricing = engine.calculate_pricing(replayed_freq, replayed_sev, exposure)

        # Unrounded calculations for comparison
        replayed_pure_prem = replayed_freq * replayed_sev
        replayed_expected_loss = replayed_pure_prem * exposure
        var_exp = assumptions["variable_expense_ratio"]
        risk_m = assumptions["risk_margin"]
        prof_m = assumptions["profit_margin"]
        fixed_e = assumptions["fixed_expense"]
        tax_r = assumptions["tax_rate"]

        denom = 1.0 - var_exp - risk_m - prof_m
        replayed_comm_prem = (replayed_expected_loss + fixed_e) / denom
        replayed_tax = replayed_comm_prem * tax_r
        replayed_total = replayed_comm_prem + replayed_tax

        stored_total = stored_trace.get("total_premium", 0.0)
        abs_diff = abs(replayed_total - stored_total)
        is_reproducible = bool(abs_diff <= 1e-6)

        return {
            "run_id": run_id,
            "replayed_timestamp": datetime.now(timezone.utc).isoformat(),
            "stored_total_premium": stored_total,
            "replayed_total_premium": replayed_total,
            "absolute_difference": abs_diff,
            "tolerance_epsilon": 1e-6,
            "is_reproducible": is_reproducible,
            "current_checksums_match": bool(
                self.get_artifact_checksums()["frequency_glm"] == rec["artifact_checksums"].get("frequency_glm")
            ),
            "replayed_components": {
                "annualized_frequency": replayed_freq,
                "expected_severity": replayed_sev,
                "pure_premium": replayed_pure_prem,
                "expected_loss": replayed_expected_loss,
                "commercial_premium": replayed_comm_prem,
                "statutory_tax": replayed_tax,
                "total_premium": replayed_total
            }
        }


# Global singleton instance
run_registry = RunRegistry()
