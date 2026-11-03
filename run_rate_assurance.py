"""
Rate Change Assurance Workbench: CLI Audit & Verification Runner.
Executes deterministic rate comparison, independent dual verification, exact attribution,
and aggregate reconciliation on policy census datasets.
"""

import sys
import json
from pathlib import Path

from rate_engine.spec_loader import load_rating_manual
from rate_engine.portfolio_reconciler import PortfolioReconciler


def run_rate_change_audit(
    old_spec_path: str = "rating_specs/manual_v1_old.json",
    new_spec_path: str = "rating_specs/manual_v2_new.json",
    census_path: str = "sample_data/policies_5_sample.json"
):
    print("=" * 80)
    print("RATE CHANGE ASSURANCE WORKBENCH: DETERMINISTIC CALCULATION PROVER")
    print("=" * 80)

    # 1. Load & Hash Rating Manuals
    print("\n[Phase 1 & 2] Loading Rating Manual Specifications...")
    old_spec, old_hash = load_rating_manual(old_spec_path)
    new_spec, new_hash = load_rating_manual(new_spec_path)

    print(f"  Old Manual : {old_spec.name} (v{old_spec.version})")
    print(f"    Base Rate: {old_spec.currency_symbol}{old_spec.base_rate:.2f} | Fee: {old_spec.currency_symbol}{old_spec.additive_fees.get('policy_fee', 0.0):.2f}")
    print(f"    SHA-256  : {old_hash[:16]}...{old_hash[-8:]}")

    print(f"  New Manual : {new_spec.name} (v{new_spec.version})")
    print(f"    Base Rate: {new_spec.currency_symbol}{new_spec.base_rate:.2f} | Fee: {new_spec.currency_symbol}{new_spec.additive_fees.get('policy_fee', 0.0):.2f}")
    print(f"    SHA-256  : {new_hash[:16]}...{new_hash[-8:]}")

    # 2. Load Census
    print(f"\n[Phase 3 & 4] Ingesting Policyholder Census: {census_path}")
    with open(census_path, "r", encoding="utf-8") as f:
        census = json.load(f)
    print(f"  Total policy records submitted: {len(census)}")

    # 3. Execute Deterministic Reconciliation
    reconciler = PortfolioReconciler(old_spec, new_spec)
    report = reconciler.reconcile_census(census)

    # 4. Policy-Level Comparison & Verification Table
    print("\n" + "-" * 80)
    print("POLICY-LEVEL CALCULATION & DUAL INDEPENDENT VERIFICATION TABLE")
    print("-" * 80)
    print(f"{'Policy ID':<10} | {'Territory':<10} | {'Old Prem':<10} | {'New Prem':<10} | {'Delta ($)':<11} | {'% Change':<10} | {'Verified?':<10}")
    print("-" * 80)

    for r in report.policy_records:
        t_val = r.attributes.get("territory", "N/A")
        old_str = f"{report.currency_symbol}{r.old_premium:.2f}"
        new_str = f"{report.currency_symbol}{r.new_premium:.2f}"
        delta_str = f"{r.dollar_change:+.2f}"
        pct_str = f"{r.percentage_change:+.2f}%" if r.percentage_change is not None else "N/A"
        ver_str = "PASS [0.00]" if r.is_verified_by_independent_calc else "FAIL"

        print(f"{r.policy_id:<10} | {t_val:<10} | {old_str:<10} | {new_str:<10} | {delta_str:<11} | {pct_str:<10} | {ver_str:<10}")

    # 5. Exact Factor Attribution Breakdown
    print("\n" + "-" * 80)
    print("EXACT STEPWISE FACTOR ATTRIBUTION (ZERO-RESIDUAL PROOF)")
    print("-" * 80)
    for r in report.policy_records:
        attr = r.attribution
        steps_summary = " + ".join(
            f"{s.component_name}={s.dollar_impact:+.2f}"
            for s in attr.steps
        )
        print(f"  [{r.policy_id}] Delta {attr.absolute_change:+.2f} = {steps_summary} | Residual: {attr.attribution_residual:.6f}")

    # 6. Aggregate Portfolio Reconciliation Proof
    print("\n" + "=" * 80)
    print("AGGREGATE PORTFOLIO RECONCILIATION & DISLOCATION SUMMARY")
    print("=" * 80)
    print(f"  Total Valid Policies       : {report.total_valid_policies} / {report.total_policies_submitted}")
    print(f"  Total Old Portfolio Premium: {report.currency_symbol}{report.total_old_premium:,.2f}")
    print(f"  Total New Portfolio Premium: {report.currency_symbol}{report.total_new_premium:,.2f}")
    print(f"  Aggregate Rate Impact      : {report.currency_symbol}{report.aggregate_dollar_change:+,.2f} ({report.aggregate_percentage_change:+.2f}%)")
    print(f"  Policies Increasing Rate   : {report.policies_increasing_count} ({report.policies_increasing_pct:.1f}%)")
    print(f"  Policies Decreasing Rate   : {report.policies_decreasing_count} ({report.policies_decreasing_pct:.1f}%)")
    print(f"  Policies Unchanged         : {report.policies_unchanged_count} ({report.policies_unchanged_pct:.1f}%)")
    print(f"  Dual Calculator Agreement  : {'100% PASSED' if report.all_independent_checks_passed else 'DISCREPANCY DETECTED'}")
    print(f"  Aggregate Sum Reconciled   : {'VERIFIED EXACT' if report.is_aggregate_reconciled else 'LEAKAGE DETECTED'}")
    print(f"  Arithmetic Leakage Error   : {report.currency_symbol}{report.reconciliation_error:.6f}")
    print("=" * 80)


if __name__ == "__main__":
    old_p = sys.argv[1] if len(sys.argv) > 1 else "rating_specs/manual_v1_old.json"
    new_p = sys.argv[2] if len(sys.argv) > 2 else "rating_specs/manual_v2_new.json"
    cen_p = sys.argv[3] if len(sys.argv) > 3 else "sample_data/policies_5_sample.json"
    run_rate_change_audit(old_p, new_p, cen_p)
