"""
Rating Manual Specification Loader and RFC 8785 Canonical Checksum Generator.
Loads rating specifications from JSON files and computes immutable canonical hashes.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Tuple, Union
from rating.spec_schema import RatingManualSpec


def canonical_json_dumps(obj: Any) -> str:
    """
    Serializes a Python object to canonical JSON string following RFC 8785 principles:
    - UTF-8 representation
    - Strict lexicographical key sorting
    - Minimal whitespace (no trailing spaces, standard separators)
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False
    )


def compute_spec_hash(spec_data: Union[Dict[str, Any], RatingManualSpec]) -> str:
    """
    Computes a deterministic SHA-256 digest of a RatingManualSpec.
    """
    if isinstance(spec_data, RatingManualSpec):
        raw_dict = spec_data.model_dump(mode="json")
    else:
        raw_dict = dict(spec_data)

    canonical_str = canonical_json_dumps(raw_dict)
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


def load_rating_manual(file_path: Union[str, Path]) -> Tuple[RatingManualSpec, str]:
    """
    Loads and validates a rating manual JSON specification from disk.
    Returns:
        Tuple[RatingManualSpec, str]: Validated Pydantic manual object and canonical SHA-256 hash.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Rating manual file not found: {path.resolve()}")

    with open(path, "r", encoding="utf-8") as f:
        raw_dict = json.load(f)

    # Compute checksum on raw normalized JSON representation
    spec_hash = compute_spec_hash(raw_dict)
    validated_spec = RatingManualSpec(**raw_dict)
    return validated_spec, spec_hash


def validate_spec_checksum(file_path: Union[str, Path], expected_hash: str) -> bool:
    """
    Verifies that the file on disk matches the expected canonical SHA-256 checksum.
    """
    _, actual_hash = load_rating_manual(file_path)
    return actual_hash.lower() == expected_hash.lower()
