"""
Rating Manual Specification Loader.
Loads, parses, validates, and computes cryptographic hashes of rating manual files.
"""

import json
import hashlib
from pathlib import Path
from typing import Tuple, Union, Dict, Any
from rate_engine.spec_schema import RatingManualSpec


def compute_spec_hash(spec_dict: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 checksum over canonically sorted JSON representation."""
    canonical = json.dumps(spec_dict, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def load_rating_manual(file_path_or_dict: Union[str, Path, Dict[str, Any]]) -> Tuple[RatingManualSpec, str]:
    """
    Load a rating manual from a file path or in-memory dictionary.
    Returns (validated_spec, sha256_checksum).
    """
    if isinstance(file_path_or_dict, (str, Path)):
        path = Path(file_path_or_dict)
        if not path.exists():
            raise FileNotFoundError(f"Rating manual file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    elif isinstance(file_path_or_dict, dict):
        raw_data = file_path_or_dict
    else:
        raise TypeError(f"Expected str, Path, or dict, got {type(file_path_or_dict)}")

    spec = RatingManualSpec(**raw_data)
    spec_hash = compute_spec_hash(raw_data)
    return spec, spec_hash
