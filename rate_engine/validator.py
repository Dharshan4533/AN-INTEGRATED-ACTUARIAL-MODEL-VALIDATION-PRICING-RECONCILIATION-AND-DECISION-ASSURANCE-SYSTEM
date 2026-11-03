"""
Census Policy Data Validator.
Checks policy census records against rating manual schema requirements.
Identifies missing variables, unsupported categories, and invalid identifiers.
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from rate_engine.spec_schema import RatingManualSpec


class PolicyValidationResult(BaseModel):
    policy_id: str
    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    validated_record: Optional[Dict[str, Any]] = None


class CensusValidator:
    """Validates policy census data against a given RatingManualSpec."""

    def __init__(self, spec: RatingManualSpec):
        self.spec = spec
        self.required_factor_variables = set(spec.factor_tables.keys())

    def validate_policy(self, raw_policy: Dict[str, Any]) -> PolicyValidationResult:
        """Validate a single policy record against the rating manual."""
        errors: List[str] = []
        warnings: List[str] = []

        # 1. Policy ID validation
        raw_id = raw_policy.get("policy_id") or raw_policy.get("id") or raw_policy.get("IDpol")
        if not raw_id or str(raw_id).strip() == "":
            return PolicyValidationResult(
                policy_id="UNKNOWN",
                is_valid=False,
                errors=["Missing or empty required field 'policy_id'."],
                validated_record=None
            )
        policy_id = str(raw_id).strip()

        # 2. Factor variable validation
        cleaned: Dict[str, Any] = {"policy_id": policy_id}

        for var_name, factor_table in self.spec.factor_tables.items():
            if var_name not in raw_policy:
                errors.append(f"Missing required rating variable '{var_name}' required by manual '{self.spec.manual_id}'.")
                continue

            raw_val = raw_policy[var_name]
            if raw_val is None or str(raw_val).strip() == "":
                errors.append(f"Rating variable '{var_name}' has null or empty value.")
                continue

            val_str = str(raw_val).strip()
            if val_str not in factor_table:
                valid_options = list(factor_table.keys())
                errors.append(
                    f"Unsupported category '{val_str}' for rating variable '{var_name}'. "
                    f"Manual '{self.spec.manual_id}' only supports: {valid_options}."
                )
            else:
                cleaned[var_name] = val_str

        # Copy any remaining non-rating metadata
        for k, v in raw_policy.items():
            if k not in cleaned:
                cleaned[k] = v

        is_valid = len(errors) == 0
        return PolicyValidationResult(
            policy_id=policy_id,
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            validated_record=cleaned if is_valid else None
        )

    def validate_census(self, policies: List[Dict[str, Any]]) -> List[PolicyValidationResult]:
        """Validate an entire collection of census policies."""
        return [self.validate_policy(p) for p in policies]
