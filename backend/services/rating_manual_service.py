"""
Rating Manual Service.
Manages rating manual ingestion, validation, version diffing, and cryptographic checksums.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, Field

from rating.spec_schema import RatingManualSpec
from rating.spec_loader import load_rating_manual, compute_spec_hash


class RuleChange(BaseModel):
    component_type: str
    component_name: str
    change_type: str  # "ADDED", "REMOVED", "MODIFIED", "UNCHANGED"
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    description: str


class ManualComparisonSummary(BaseModel):
    old_manual_id: str
    old_version: str
    old_hash: str
    new_manual_id: str
    new_version: str
    new_hash: str
    currency: str
    base_rate_old: float
    base_rate_new: float
    base_rate_change_dollar: float
    base_rate_change_pct: float
    rule_changes: List[RuleChange] = Field(default_factory=list)


class RatingManualService:
    """
    Handles rating manual specifications, version management, and semantic comparison.
    """

    @staticmethod
    def load_manual(path_or_dict: Union[str, Path, Dict[str, Any]]) -> Tuple[RatingManualSpec, str]:
        """
        Loads and validates a rating manual from path or dictionary.
        """
        if isinstance(path_or_dict, (str, Path)):
            return load_rating_manual(path_or_dict)
        elif isinstance(path_or_dict, dict):
            spec = RatingManualSpec(**path_or_dict)
            spec_hash = compute_spec_hash(spec)
            return spec, spec_hash
        raise ValueError("path_or_dict must be a file path or a dictionary")

    @classmethod
    def compare_manuals(
        cls,
        old_spec: RatingManualSpec,
        new_spec: RatingManualSpec
    ) -> ManualComparisonSummary:
        """
        Compares two rating manuals and produces an audit diff of rule changes.
        """
        old_hash = compute_spec_hash(old_spec)
        new_hash = compute_spec_hash(new_spec)

        rule_changes: List[RuleChange] = []

        # 1. Base Rate Change
        base_delta = round(new_spec.base_rate - old_spec.base_rate, 4)
        base_pct = round((base_delta / old_spec.base_rate) * 100.0, 2) if old_spec.base_rate > 0 else 0.0

        if base_delta != 0:
            rule_changes.append(RuleChange(
                component_type="BASE_RATE",
                component_name="base_rate",
                change_type="MODIFIED",
                old_value=old_spec.base_rate,
                new_value=new_spec.base_rate,
                description=f"Base rate changed from {old_spec.base_rate:.2f} to {new_spec.base_rate:.2f} ({base_pct:+.2f}%)"
            ))

        # 2. Factor Tables Diff
        all_factor_vars = sorted(list(set(old_spec.factor_tables.keys()) | set(new_spec.factor_tables.keys())))
        for var in all_factor_vars:
            old_table = old_spec.factor_tables.get(var, {})
            new_table = new_spec.factor_tables.get(var, {})

            if var not in old_spec.factor_tables:
                rule_changes.append(RuleChange(
                    component_type="FACTOR_TABLE",
                    component_name=var,
                    change_type="ADDED",
                    old_value=None,
                    new_value=new_table,
                    description=f"Introduced new rating factor table for '{var}'"
                ))
            elif var not in new_spec.factor_tables:
                rule_changes.append(RuleChange(
                    component_type="FACTOR_TABLE",
                    component_name=var,
                    change_type="REMOVED",
                    old_value=old_table,
                    new_value=None,
                    description=f"Retired rating factor table for '{var}'"
                ))
            else:
                all_cats = sorted(list(set(old_table.keys()) | set(new_table.keys())))
                for cat in all_cats:
                    old_f = old_table.get(cat)
                    new_f = new_table.get(cat)
                    if old_f is None:
                        rule_changes.append(RuleChange(
                            component_type="FACTOR_ENTRY",
                            component_name=f"{var}[{cat}]",
                            change_type="ADDED",
                            old_value=None,
                            new_value=new_f,
                            description=f"Added category '{cat}' to '{var}' with factor {new_f}"
                        ))
                    elif new_f is None:
                        rule_changes.append(RuleChange(
                            component_type="FACTOR_ENTRY",
                            component_name=f"{var}[{cat}]",
                            change_type="REMOVED",
                            old_value=old_f,
                            new_value=None,
                            description=f"Removed category '{cat}' from '{var}' (was {old_f})"
                        ))
                    elif old_f != new_f:
                        rule_changes.append(RuleChange(
                            component_type="FACTOR_ENTRY",
                            component_name=f"{var}[{cat}]",
                            change_type="MODIFIED",
                            old_value=old_f,
                            new_value=new_f,
                            description=f"Factor '{var}[{cat}]' changed from {old_f:.4f} to {new_f:.4f}"
                        ))

        # 3. Additive Fees Diff
        all_fees = sorted(list(set(old_spec.additive_fees.keys()) | set(new_spec.additive_fees.keys())))
        for fee in all_fees:
            old_val = old_spec.additive_fees.get(fee)
            new_val = new_spec.additive_fees.get(fee)
            if old_val is None:
                rule_changes.append(RuleChange(
                    component_type="ADDITIVE_FEE",
                    component_name=fee,
                    change_type="ADDED",
                    old_value=None,
                    new_value=new_val,
                    description=f"Added fee '{fee}' of {new_val:.2f}"
                ))
            elif new_val is None:
                rule_changes.append(RuleChange(
                    component_type="ADDITIVE_FEE",
                    component_name=fee,
                    change_type="REMOVED",
                    old_value=old_val,
                    new_value=None,
                    description=f"Removed fee '{fee}' (was {old_val:.2f})"
                ))
            elif old_val != new_val:
                rule_changes.append(RuleChange(
                    component_type="ADDITIVE_FEE",
                    component_name=fee,
                    change_type="MODIFIED",
                    old_value=old_val,
                    new_value=new_val,
                    description=f"Fee '{fee}' changed from {old_val:.2f} to {new_val:.2f}"
                ))

        # 4. Limits & Clamping Diff
        if (old_spec.min_premium != new_spec.min_premium) or (old_spec.max_premium != new_spec.max_premium):
            rule_changes.append(RuleChange(
                component_type="STATUTORY_LIMITS",
                component_name="min_max_premium",
                change_type="MODIFIED",
                old_value={"min": old_spec.min_premium, "max": old_spec.max_premium},
                new_value={"min": new_spec.min_premium, "max": new_spec.max_premium},
                description=f"Statutory limits updated: min {old_spec.min_premium}->{new_spec.min_premium}, max {old_spec.max_premium}->{new_spec.max_premium}"
            ))

        return ManualComparisonSummary(
            old_manual_id=old_spec.manual_id,
            old_version=old_spec.version,
            old_hash=old_hash,
            new_manual_id=new_spec.manual_id,
            new_version=new_spec.version,
            new_hash=new_hash,
            currency=new_spec.currency,
            base_rate_old=old_spec.base_rate,
            base_rate_new=new_spec.base_rate,
            base_rate_change_dollar=base_delta,
            base_rate_change_pct=base_pct,
            rule_changes=rule_changes
        )
