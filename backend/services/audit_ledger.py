"""
Cryptographic Hash-Chained Audit Ledger Service.
Provides append-only local storage with linear SHA-256 hash chaining,
RFC 8785 canonical JSON serialization, optional HMAC authentication,
external checkpoint anchoring, and comprehensive tamper detection.
"""

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


GENESIS_HASH: str = hashlib.sha256(b"GENESIS_LEDGER_RECORD_v1.0").hexdigest()


def canonical_json_dumps(obj: Any) -> str:
    """
    Serializes a Python object to canonical JSON string adhering to RFC 8785 principles:
    - UTF-8 representation
    - Strict lexicographical key sorting
    - Minimal whitespace (no trailing spaces, standard separators)
    - Deterministic float and integer serialization
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False
    )


class LedgerVerificationResult(BaseModel):
    is_valid: bool = Field(..., description="True if the entire hash chain is unbroken and untampered.")
    total_records: int = Field(..., description="Total number of evaluated records in the ledger.")
    genesis_hash: str = Field(..., description="The fixed root genesis hash.")
    tip_hash: Optional[str] = Field(None, description="The latest record entry hash (tip of the chain).")
    tamper_detected: bool = Field(False, description="True if corruption, alteration, or deletion is detected.")
    tamper_type: Optional[str] = Field(None, description="Categorization of detected tampering.")
    tamper_details: Optional[Dict[str, Any]] = Field(None, description="Diagnostic details on the detected flaw.")
    errors: List[str] = Field(default_factory=list, description="Descriptive error messages if verification failed.")


class AuditLedger:
    """
    Cryptographic Hash-Chained Audit Ledger implementing an append-only JSONL chain.
    Formula:
        H_0 = SHA-256("GENESIS_LEDGER_RECORD_v1.0")
        H_t = SHA-256( JCS(Record_t_body) || H_{t-1} )
    """

    def __init__(self, ledger_path: str = "runs/audit_ledger.jsonl"):
        self.ledger_path = Path(ledger_path)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_last_entry(self) -> Optional[Dict[str, Any]]:
        """Reads the last line of the ledger to obtain the previous record index and tip hash."""
        if not self.ledger_path.exists() or self.ledger_path.stat().st_size == 0:
            return None

        last_line = None
        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    last_line = stripped

        if not last_line:
            return None

        try:
            return json.loads(last_line)
        except Exception:
            return None

    def append_entry(
        self,
        run_id: str,
        run_type: str,
        payload: Dict[str, Any],
        auth_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Appends a new record to the audit ledger, linking it to the prior entry hash.
        """
        last_entry = self._get_last_entry()
        if last_entry is None:
            record_index = 1
            prev_hash = GENESIS_HASH
        else:
            record_index = int(last_entry.get("record_index", 0)) + 1
            prev_hash = str(last_entry.get("entry_hash", GENESIS_HASH))

        timestamp = datetime.now(timezone.utc).isoformat()

        body = {
            "record_index": record_index,
            "run_id": run_id,
            "timestamp": timestamp,
            "run_type": run_type,
            "payload": payload,
            "prev_hash": prev_hash,
        }

        # RFC 8785 Canonical serialization of the body
        canonical_body = canonical_json_dumps(body)

        # Hash chaining formula: SHA-256( canonical_body || prev_hash )
        chain_input = (canonical_body + prev_hash).encode("utf-8")
        entry_hash = hashlib.sha256(chain_input).hexdigest()

        # Optional HMAC message authentication signature
        hmac_signature = None
        if auth_key:
            hmac_signature = hmac.new(
                auth_key.encode("utf-8"),
                entry_hash.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()

        complete_record = {
            **body,
            "entry_hash": entry_hash,
            "hmac_signature": hmac_signature,
        }

        # Append single canonical JSON line
        with open(self.ledger_path, "a", encoding="utf-8") as f:
            f.write(canonical_json_dumps(complete_record) + "\n")

        return complete_record

    def verify_ledger_integrity(
        self,
        auth_key: Optional[str] = None,
        expected_tip_hash: Optional[str] = None
    ) -> LedgerVerificationResult:
        """
        Traverses the audit ledger from genesis to tip, verifying:
        1. Correct sequential record numbering (1, 2, ... N)
        2. Exact previous hash continuity (prev_hash matches preceding entry_hash)
        3. Canonical body recalculation match (entry_hash matches SHA-256(JCS(body) || prev_hash))
        4. Optional HMAC authentication check
        5. Optional expected tip hash matching against external signed checkpoint
        """
        if not self.ledger_path.exists() or self.ledger_path.stat().st_size == 0:
            if expected_tip_hash:
                return LedgerVerificationResult(
                    is_valid=False,
                    total_records=0,
                    genesis_hash=GENESIS_HASH,
                    tip_hash=None,
                    tamper_detected=True,
                    tamper_type="LEDGER_TRUNCATED_OR_EMPTY",
                    tamper_details={"expected_tip_hash": expected_tip_hash},
                    errors=["Ledger is empty but an external tip hash was expected."]
                )
            return LedgerVerificationResult(
                is_valid=True,
                total_records=0,
                genesis_hash=GENESIS_HASH,
                tip_hash=None,
                tamper_detected=False
            )

        expected_prev = GENESIS_HASH
        records_count = 0
        last_entry_hash = None

        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line_idx, line in enumerate(f, start=1):
                raw = line.strip()
                if not raw:
                    continue

                records_count += 1
                try:
                    record = json.loads(raw)
                except Exception as e:
                    return LedgerVerificationResult(
                        is_valid=False,
                        total_records=records_count,
                        genesis_hash=GENESIS_HASH,
                        tip_hash=last_entry_hash,
                        tamper_detected=True,
                        tamper_type="MALFORMED_JSON_LINE",
                        tamper_details={"line_number": line_idx, "error": str(e)},
                        errors=[f"Line {line_idx} contains malformed non-JSON data."]
                    )

                idx = record.get("record_index")
                if idx != records_count:
                    return LedgerVerificationResult(
                        is_valid=False,
                        total_records=records_count,
                        genesis_hash=GENESIS_HASH,
                        tip_hash=last_entry_hash,
                        tamper_detected=True,
                        tamper_type="SEQUENCE_INDEX_MISMATCH",
                        tamper_details={
                            "line_number": line_idx,
                            "expected_index": records_count,
                            "actual_index": idx
                        },
                        errors=[f"Record index mismatch at line {line_idx}: expected {records_count}, found {idx}."]
                    )

                record_prev_hash = record.get("prev_hash")
                if record_prev_hash != expected_prev:
                    return LedgerVerificationResult(
                        is_valid=False,
                        total_records=records_count,
                        genesis_hash=GENESIS_HASH,
                        tip_hash=last_entry_hash,
                        tamper_detected=True,
                        tamper_type="BROKEN_HASH_CHAIN_LINK",
                        tamper_details={
                            "record_index": idx,
                            "expected_prev_hash": expected_prev,
                            "actual_prev_hash": record_prev_hash
                        },
                        errors=[f"Chain broken at record {idx}: prev_hash does not match preceding entry_hash."]
                    )

                # Reconstruct body
                body = {
                    "record_index": record["record_index"],
                    "run_id": record["run_id"],
                    "timestamp": record["timestamp"],
                    "run_type": record["run_type"],
                    "payload": record["payload"],
                    "prev_hash": record["prev_hash"],
                }

                canonical_body = canonical_json_dumps(body)
                expected_hash = hashlib.sha256((canonical_body + record["prev_hash"]).encode("utf-8")).hexdigest()
                actual_hash = record.get("entry_hash")

                if actual_hash != expected_hash:
                    return LedgerVerificationResult(
                        is_valid=False,
                        total_records=records_count,
                        genesis_hash=GENESIS_HASH,
                        tip_hash=last_entry_hash,
                        tamper_detected=True,
                        tamper_type="RECORD_PAYLOAD_ALTERATION",
                        tamper_details={
                            "record_index": idx,
                            "expected_entry_hash": expected_hash,
                            "actual_entry_hash": actual_hash
                        },
                        errors=[f"Record {idx} entry hash mismatch: payload or fields have been modified."]
                    )

                if auth_key and record.get("hmac_signature"):
                    expected_hmac = hmac.new(
                        auth_key.encode("utf-8"),
                        actual_hash.encode("utf-8"),
                        hashlib.sha256
                    ).hexdigest()
                    if record["hmac_signature"] != expected_hmac:
                        return LedgerVerificationResult(
                            is_valid=False,
                            total_records=records_count,
                            genesis_hash=GENESIS_HASH,
                            tip_hash=last_entry_hash,
                            tamper_detected=True,
                            tamper_type="INVALID_HMAC_AUTHENTICATION",
                            tamper_details={"record_index": idx},
                            errors=[f"HMAC authentication failed for record {idx}."]
                        )

                expected_prev = actual_hash
                last_entry_hash = actual_hash

        # External checkpoint verification against truncation
        if expected_tip_hash and last_entry_hash != expected_tip_hash:
            return LedgerVerificationResult(
                is_valid=False,
                total_records=records_count,
                genesis_hash=GENESIS_HASH,
                tip_hash=last_entry_hash,
                tamper_detected=True,
                tamper_type="LEDGER_TRUNCATION_DETECTED",
                tamper_details={
                    "expected_tip_hash": expected_tip_hash,
                    "actual_tip_hash": last_entry_hash
                },
                errors=["Tip hash does not match expected external checkpoint; ledger may have been truncated."]
            )

        return LedgerVerificationResult(
            is_valid=True,
            total_records=records_count,
            genesis_hash=GENESIS_HASH,
            tip_hash=last_entry_hash,
            tamper_detected=False
        )

    def generate_checkpoint(self, auth_key: Optional[str] = None) -> Dict[str, Any]:
        """
        Generates an exportable signed checkpoint representing the current ledger state.
        This checkpoint can be anchored externally to guarantee non-repudiation against truncation.
        """
        last_entry = self._get_last_entry()
        total_records = int(last_entry.get("record_index", 0)) if last_entry else 0
        tip_hash = str(last_entry.get("entry_hash", GENESIS_HASH)) if last_entry else GENESIS_HASH

        checkpoint_data = {
            "checkpoint_id": f"chk_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{total_records}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_records": total_records,
            "genesis_hash": GENESIS_HASH,
            "tip_hash": tip_hash,
        }

        canonical_chk = canonical_json_dumps(checkpoint_data)
        checkpoint_hash = hashlib.sha256(canonical_chk.encode("utf-8")).hexdigest()

        hmac_sig = None
        if auth_key:
            hmac_sig = hmac.new(
                auth_key.encode("utf-8"),
                checkpoint_hash.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()

        return {
            **checkpoint_data,
            "checkpoint_hash": checkpoint_hash,
            "signature": hmac_sig,
        }


def compute_replay_token(payload: Dict[str, Any]) -> str:
    """
    Computes a canonical SHA-256 replay token from a complete deterministic rating run payload.
    Enforces the presence of all deterministic inputs affecting calculation.
    """
    required_keys = [
        "old_manual_hash",
        "new_manual_hash",
        "census_hash",
        "pipeline_configuration",
        "rounding_rule",
        "currency",
        "software_versions",
        "execution_settings",
    ]
    missing = [k for k in required_keys if k not in payload]
    if missing:
        raise ValueError(f"Replay payload is incomplete; missing deterministic parameters: {missing}")

    canonical_str = canonical_json_dumps(payload)
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


# Default singleton instance
audit_ledger = AuditLedger()
