"""
Automated Test Suite for Hash-Chained Audit Ledger and Replay Token Generator.
Verifies RFC 8785 canonical serialization, linear hash chaining, HMAC authentication,
checkpoint anchoring, and tamper detection against altered, deleted, reordered, or truncated logs.
"""

import hashlib
import json
import os
import pytest
from backend.services.audit_ledger import (
    AuditLedger,
    GENESIS_HASH,
    canonical_json_dumps,
    compute_replay_token,
)
from backend.services.run_registry import RunRegistry


def test_genesis_hash_and_empty_ledger(tmp_path):
    ledger_file = tmp_path / "audit_ledger.jsonl"
    ledger = AuditLedger(str(ledger_file))

    assert GENESIS_HASH == hashlib.sha256(b"GENESIS_LEDGER_RECORD_v1.0").hexdigest()
    res = ledger.verify_ledger_integrity()
    assert res.is_valid is True
    assert res.total_records == 0
    assert res.tamper_detected is False


def test_linear_hash_chaining(tmp_path):
    ledger_file = tmp_path / "audit_ledger.jsonl"
    ledger = AuditLedger(str(ledger_file))

    # Append entry 1
    e1 = ledger.append_entry("run_001", "RATE_CHANGE", {"step": 1})
    assert e1["record_index"] == 1
    assert e1["prev_hash"] == GENESIS_HASH
    assert len(e1["entry_hash"]) == 64

    # Append entry 2
    e2 = ledger.append_entry("run_002", "RATE_CHANGE", {"step": 2})
    assert e2["record_index"] == 2
    assert e2["prev_hash"] == e1["entry_hash"]

    # Append entry 3
    e3 = ledger.append_entry("run_003", "RATE_CHANGE", {"step": 3})
    assert e3["record_index"] == 3
    assert e3["prev_hash"] == e2["entry_hash"]

    # Verify untampered ledger
    res = ledger.verify_ledger_integrity()
    assert res.is_valid is True
    assert res.total_records == 3
    assert res.tip_hash == e3["entry_hash"]
    assert res.tamper_detected is False


def test_tamper_detection_altered_record(tmp_path):
    ledger_file = tmp_path / "audit_ledger.jsonl"
    ledger = AuditLedger(str(ledger_file))

    ledger.append_entry("run_001", "RATE_CHANGE", {"val": 100})
    ledger.append_entry("run_002", "RATE_CHANGE", {"val": 200})
    ledger.append_entry("run_003", "RATE_CHANGE", {"val": 300})

    # Tamper: read lines, alter record 2's payload, write back
    lines = ledger_file.read_text(encoding="utf-8").strip().split("\n")
    rec2 = json.loads(lines[1])
    rec2["payload"]["val"] = 999  # malicious edit without valid hash update
    lines[1] = json.dumps(rec2)
    ledger_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    res = ledger.verify_ledger_integrity()
    assert res.is_valid is False
    assert res.tamper_detected is True
    assert res.tamper_type == "RECORD_PAYLOAD_ALTERATION"
    assert res.tamper_details["record_index"] == 2


def test_tamper_detection_deleted_record(tmp_path):
    ledger_file = tmp_path / "audit_ledger.jsonl"
    ledger = AuditLedger(str(ledger_file))

    ledger.append_entry("run_001", "RATE_CHANGE", {"val": 100})
    ledger.append_entry("run_002", "RATE_CHANGE", {"val": 200})
    ledger.append_entry("run_003", "RATE_CHANGE", {"val": 300})

    # Tamper: delete record 2
    lines = ledger_file.read_text(encoding="utf-8").strip().split("\n")
    del lines[1]
    ledger_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    res = ledger.verify_ledger_integrity()
    assert res.is_valid is False
    assert res.tamper_detected is True
    assert res.tamper_type in ["SEQUENCE_INDEX_MISMATCH", "BROKEN_HASH_CHAIN_LINK"]


def test_tamper_detection_reordered_records(tmp_path):
    ledger_file = tmp_path / "audit_ledger.jsonl"
    ledger = AuditLedger(str(ledger_file))

    ledger.append_entry("run_001", "RATE_CHANGE", {"val": 100})
    ledger.append_entry("run_002", "RATE_CHANGE", {"val": 200})

    # Tamper: swap records 1 and 2
    lines = ledger_file.read_text(encoding="utf-8").strip().split("\n")
    lines[0], lines[1] = lines[1], lines[0]
    ledger_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    res = ledger.verify_ledger_integrity()
    assert res.is_valid is False
    assert res.tamper_detected is True


def test_tamper_detection_truncation_via_checkpoint(tmp_path):
    ledger_file = tmp_path / "audit_ledger.jsonl"
    ledger = AuditLedger(str(ledger_file))

    ledger.append_entry("run_001", "RATE_CHANGE", {"val": 100})
    e2 = ledger.append_entry("run_002", "RATE_CHANGE", {"val": 200})
    checkpoint = ledger.generate_checkpoint()

    assert checkpoint["tip_hash"] == e2["entry_hash"]
    assert checkpoint["total_records"] == 2

    # Truncate record 2 from disk
    lines = ledger_file.read_text(encoding="utf-8").strip().split("\n")
    ledger_file.write_text(lines[0] + "\n", encoding="utf-8")

    # Verifying without expected tip would think record 1 is fine
    res_no_chk = ledger.verify_ledger_integrity()
    assert res_no_chk.is_valid is True

    # Verifying against signed external checkpoint reveals truncation!
    res_with_chk = ledger.verify_ledger_integrity(expected_tip_hash=checkpoint["tip_hash"])
    assert res_with_chk.is_valid is False
    assert res_with_chk.tamper_detected is True
    assert res_with_chk.tamper_type == "LEDGER_TRUNCATION_DETECTED"


def test_hmac_authentication(tmp_path):
    ledger_file = tmp_path / "audit_ledger.jsonl"
    ledger = AuditLedger(str(ledger_file))
    auth_key = "super_secret_actuarial_hmac_key"

    ledger.append_entry("run_001", "RATE_CHANGE", {"data": "verified"}, auth_key=auth_key)

    # Valid check
    res = ledger.verify_ledger_integrity(auth_key=auth_key)
    assert res.is_valid is True
    assert res.tamper_detected is False

    # Invalid check with wrong auth key
    res_wrong = ledger.verify_ledger_integrity(auth_key="wrong_key")
    assert res_wrong.is_valid is False
    assert res_wrong.tamper_type == "INVALID_HMAC_AUTHENTICATION"


def test_replay_token_computation():
    payload = {
        "old_manual_hash": "a" * 64,
        "new_manual_hash": "b" * 64,
        "census_hash": "c" * 64,
        "pipeline_configuration": [{"step_type": "BASE_RATE"}],
        "rounding_rule": {"method": "ROUND_HALF_UP", "precision": 2},
        "currency": "USD",
        "software_versions": {"python": "3.13.0", "rating_engine": "1.0.0"},
        "execution_settings": {"decimal_context_precision": 28},
    }

    token1 = compute_replay_token(payload)
    assert len(token1) == 64

    # Permute dictionary key order - canonical RFC 8785 serialization ensures same hash
    permuted = {k: payload[k] for k in reversed(list(payload.keys()))}
    token2 = compute_replay_token(permuted)
    assert token1 == token2

    # Incomplete payload raises ValueError
    incomplete = dict(payload)
    del incomplete["census_hash"]
    with pytest.raises(ValueError, match="missing deterministic parameters"):
        compute_replay_token(incomplete)


def test_run_registry_integration(tmp_path):
    registry = RunRegistry(str(tmp_path))

    old_spec = {"manual_id": "OLD-M", "base_rate": 500.0}
    new_spec = {"manual_id": "NEW-M", "base_rate": 550.0}
    census = [{"policy_id": "P1", "exposure": 1.0}]
    recon = {"total_delta": 50.0}

    res = registry.record_rate_change_run(
        old_manual_spec=old_spec,
        new_manual_spec=new_spec,
        census_records=census,
        reconciliation_summary=recon,
    )

    assert "run_id" in res
    assert "replay_token" in res
    assert "entry_hash" in res

    # Verify audit ledger through RunRegistry
    verif = registry.verify_audit_ledger()
    assert verif.is_valid is True
    assert verif.total_records == 1
    assert verif.tamper_detected is False
