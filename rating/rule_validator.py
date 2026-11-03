"""
Rating Rule and Policy Census Validator.
Enforces pre-flight rating integrity, mandatory feature presence, categorical domain
boundaries, and underwriting eligibility rules.
"""

from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from rating.spec_schema import RatingManualSpec


class RatingRuleValidationError(Exception):
    """Base exception for rating rule and census validation failures."""
    pass


class MissingRatingVariableError(RatingRuleValidationError):
    """Raised when a policy is missing a mandatory rating variable."""
    pass


class UnsupportedCategoryError(RatingRuleValidationError):
    """Raised when a policy contains an unmapped categorical level."""
    pass


class InvalidPolicyIdentifierError(RatingRuleValidationError):
    """Raised when a policy record lacks a valid unique policy identifier."""
    pass


class IneligiblePolicyError(RatingRuleValidationError):
    """Raised when a policy violates underwriting eligibility conditions."""
    pass


class PolicyValidationResult(BaseModel):
    policy_id: str
    is_valid: bool
    is_eligible: bool = True
    errors: List[str] = Field(default_factory=list)
    rejection_reasons: List[str] = Field(default_factory=list)


class CensusValidationSummary(BaseModel):
    total_records: int
    valid_records: int
    invalid_records: int
    ineligible_records: int
    errors_by_field: Dict[str, int] = Field(default_factory=dict)
    sample_failures: List[Dict[str, Any]] = Field(default_factory=list)


class RatingRuleValidator:
    """
    Validates policyholder census records against a specific rating manual contract.
    """

    def __init__(self, spec: RatingManualSpec):
        self.spec = spec
        # Variables required by factor tables and discount tables
        self.required_factor_variables = set(spec.factor_tables.keys())
        self.required_discount_variables = set(spec.discount_tables.keys())
        self.all_required_variables = self.required_factor_variables | self.required_discount_variables

    def validate_policy(self, policy: Dict[str, Any]) -> PolicyValidationResult:
        """
        Validates a single policyholder record against the rating manual specification.
        """
        errors: List[str] = []
        rejection_reasons: List[str] = []

        # 1. Policy Identifier Check
        p_id = policy.get("policy_id") or policy.get("IDpol")
        if not p_id or str(p_id).strip() == "":
            errors.append("Missing mandatory 'policy_id' or 'IDpol' identifier.")
            return PolicyValidationResult(
                policy_id="UNKNOWN",
                is_valid=False,
                is_eligible=False,
                errors=errors
            )

        policy_id_str = str(p_id).strip()

        # 2. Check for missing mandatory rating variables
        for var in sorted(self.all_required_variables):
            if var not in policy or policy[var] is None or str(policy[var]).strip() == "":
                errors.append(f"Missing mandatory rating variable '{var}' required by manual '{self.spec.manual_id}'.")

        # 3. Check for unsupported categorical levels in factor tables
        for var, factor_table in self.spec.factor_tables.items():
            if var in policy and policy[var] is not None:
                val = str(policy[var]).strip()
                if val not in factor_table:
                    allowed = list(factor_table.keys())
                    errors.append(
                        f"Unsupported category '{val}' for variable '{var}'. "
                        f"Supported categories in manual '{self.spec.manual_id}': {allowed}."
                    )

        # 4. Check for unsupported categorical levels in discount tables
        for var, disc_table in self.spec.discount_tables.items():
            if var in policy and policy[var] is not None:
                val = str(policy[var]).strip()
                if val not in disc_table:
                    allowed = list(disc_table.keys())
                    errors.append(
                        f"Unsupported discount category '{val}' for variable '{var}'. "
                        f"Supported categories in manual '{self.spec.manual_id}': {allowed}."
                    )

        # 5. Underwriting Eligibility Rules
        for field, allowed_values in self.spec.eligibility_rules.items():
            if field in policy and policy[field] is not None:
                val = policy[field]
                # If numeric range: e.g. [min_val, max_val]
                if len(allowed_values) == 2 and all(isinstance(x, (int, float)) for x in allowed_values) and isinstance(val, (int, float)):
                    min_val, max_val = allowed_values[0], allowed_values[1]
                    if not (min_val <= val <= max_val):
                        rejection_reasons.append(
                            f"Field '{field}' with value {val} is outside eligible range [{min_val}, {max_val}]."
                        )
                else:
                    str_allowed = [str(x).strip() for x in allowed_values]
                    if str(val).strip() not in str_allowed:
                        rejection_reasons.append(
                            f"Field '{field}' value '{val}' violates eligibility criteria: allowed {str_allowed}."
                        )

        is_valid = len(errors) == 0
        is_eligible = len(rejection_reasons) == 0

        return PolicyValidationResult(
            policy_id=policy_id_str,
            is_valid=is_valid,
            is_eligible=is_eligible,
            errors=errors,
            rejection_reasons=rejection_reasons
        )

    def validate_census(self, census: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], CensusValidationSummary]:
        """
        Validates an entire policyholder census list.
        Returns:
            Tuple[List[Dict[str, Any]], CensusValidationSummary]: List of valid policies and summary audit report.
        """
        valid_policies: List[Dict[str, Any]] = []
        errors_by_field: Dict[str, int] = {}
        sample_failures: List[Dict[str, Any]] = []
        invalid_count = 0
        ineligible_count = 0

        for row in census:
            res = self.validate_policy(row)
            if res.is_valid and res.is_eligible:
                valid_policies.append(row)
            else:
                if not res.is_valid:
                    invalid_count += 1
                if not res.is_eligible:
                    ineligible_count += 1

                for err in res.errors + res.rejection_reasons:
                    field_key = err.split("'")[1] if "'" in err else "general"
                    errors_by_field[field_key] = errors_by_field.get(field_key, 0) + 1

                if len(sample_failures) < 10:
                    sample_failures.append({
                        "policy_id": res.policy_id,
                        "errors": res.errors,
                        "rejections": res.rejection_reasons,
                        "raw_record": row
                    })

        summary = CensusValidationSummary(
            total_records=len(census),
            valid_records=len(valid_policies),
            invalid_records=invalid_count,
            ineligible_records=ineligible_count,
            errors_by_field=errors_by_field,
            sample_failures=sample_failures
        )

        return valid_policies, summary
