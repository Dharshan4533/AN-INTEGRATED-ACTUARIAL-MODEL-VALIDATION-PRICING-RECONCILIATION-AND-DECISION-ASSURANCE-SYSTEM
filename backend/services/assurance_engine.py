"""
Unified Actuarial Decision Assurance Engine.
Synthesizes findings across Data-Quality Gate, Model Validation, Parameter Uncertainty,
Reconciliation Exactness, Portfolio Simulation Convergence, and Distribution Drift into
traceable, evidence-backed assurance warnings.
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class AssuranceWarning(BaseModel):
    rule_id: str
    category: str  # "DATA_GATE", "MODEL_VALIDATION", "UNCERTAINTY", "RECONCILIATION", "SIMULATION", "DRIFT"
    severity: str  # "CRITICAL", "WARNING", "ADVISORY"
    title: str
    evidence: str
    remediation: str


class AssuranceEvaluationResult(BaseModel):
    overall_assurance_status: str  # "ASSURED", "CONDITIONAL_APPROVAL", "ACTION_REQUIRED"
    is_decision_ready: bool
    critical_warnings_count: int
    warning_count: int
    advisory_count: int
    warnings: List[AssuranceWarning]
    signoff_statement: str


class AssuranceEngine:
    """
    Evaluates execution context and produces unified assurance assessment.
    """

    def evaluate_assurance(
        self,
        data_report: Optional[Dict[str, Any]] = None,
        uncertainty_assessment: Optional[Dict[str, Any]] = None,
        reconciliation_response: Optional[Dict[str, Any]] = None,
        simulation_response: Optional[Dict[str, Any]] = None,
        drift_report: Optional[Dict[str, Any]] = None
    ) -> AssuranceEvaluationResult:
        warnings: List[AssuranceWarning] = []

        # 1. Data-Quality Gate evaluation
        if data_report:
            if not data_report.get("is_prediction_ready", True):
                warnings.append(AssuranceWarning(
                    rule_id="ASSURE_DATA_01_BLOCKED",
                    category="DATA_GATE",
                    severity="CRITICAL",
                    title="Data Quality Gate Rejection",
                    evidence=f"Data gate reported {data_report.get('critical_count', 0)} critical data-quality violations.",
                    remediation="Resolve critical input errors before generating actuarial quotes or training models."
                ))
            for f in data_report.get("findings", []):
                if f.get("severity") == "WARNING":
                    warnings.append(AssuranceWarning(
                        rule_id=f"ASSURE_DATA_WARN_{f.get('rule_id', 'GENERIC')}",
                        category="DATA_GATE",
                        severity="WARNING",
                        title=f.get("title", "Data Warning"),
                        evidence=f.get("description", ""),
                        remediation=f.get("recommended_remediation", "")
                    ))

        # 2. Uncertainty evaluation
        if uncertainty_assessment:
            pp_ci = uncertainty_assessment.get("pure_premium_ci", {})
            if pp_ci.get("is_excessive_uncertainty", False):
                margin = pp_ci.get("relative_margin_of_error_pct", 0.0)
                warnings.append(AssuranceWarning(
                    rule_id="ASSURE_UNCERT_01_WIDE_CI",
                    category="UNCERTAINTY",
                    severity="WARNING",
                    title="Elevated Parameter Estimation Uncertainty",
                    evidence=f"Pure premium 95% confidence interval relative margin is +/-{margin:.1f}% (> 35% threshold).",
                    remediation="Apply underwriting margin buffer or request additional risk verification for this rare segment profile."
                ))

        # 3. Reconciliation exactness evaluation
        if reconciliation_response:
            if not reconciliation_response.get("is_exact_reconciliation", True):
                err = reconciliation_response.get("reconciliation_error", 0.0)
                warnings.append(AssuranceWarning(
                    rule_id="ASSURE_RECON_01_LEAKAGE",
                    category="RECONCILIATION",
                    severity="CRITICAL",
                    title="Reconciliation Arithmetic Non-Exactness",
                    evidence=f"Premium difference attribution error = {err:.6f} EUR exceeds tolerance epsilon = 1e-4.",
                    remediation="Audit sequential arithmetic decomposition and check for floating point truncation leakage."
                ))
            sensitivity = reconciliation_response.get("order_sensitivity_analysis", {})
            max_div = sensitivity.get("max_step_divergence", 0.0)
            if max_div > 50.0:
                warnings.append(AssuranceWarning(
                    rule_id="ASSURE_RECON_02_PATH_DEPENDENCE",
                    category="RECONCILIATION",
                    severity="ADVISORY",
                    title="Significant Step Order Interaction Divergence",
                    evidence=f"Forward vs. reverse sequence step divergence is {max_div:.2f} EUR due to compounding loadings.",
                    remediation="Document the sequential factor attribution order in formal underwriting rate filings."
                ))

        # 4. Simulation convergence evaluation
        if simulation_response:
            if not simulation_response.get("moment_convergence_verified", True):
                z = simulation_response.get("moment_z_score", 0.0)
                warnings.append(AssuranceWarning(
                    rule_id="ASSURE_SIM_01_CONVERGENCE",
                    category="SIMULATION",
                    severity="WARNING",
                    title="Monte Carlo Moment Convergence Divergence",
                    evidence=f"Simulated mean diverges from theoretical expected loss by z-score = {z:.2f} (> 2.58 SE).",
                    remediation="Increase Monte Carlo simulation trials to at least 10,000 runs to reduce sampling variance."
                ))

        # 5. Distribution drift evaluation
        if drift_report:
            max_psi = drift_report.get("max_feature_psi", 0.0)
            if max_psi >= 0.25:
                warnings.append(AssuranceWarning(
                    rule_id="ASSURE_DRIFT_01_SIGNIFICANT",
                    category="DRIFT",
                    severity="CRITICAL",
                    title="Significant Covariate Distribution Drift Detected",
                    evidence=f"Maximum feature PSI = {max_psi:.4f} >= 0.25 threshold indicates major population shift.",
                    remediation="Initiate formal model recalibration and assess whether new business mix diverges from training portfolio."
                ))
            elif max_psi >= 0.10:
                warnings.append(AssuranceWarning(
                    rule_id="ASSURE_DRIFT_02_MODERATE",
                    category="DRIFT",
                    severity="WARNING",
                    title="Moderate Covariate Distribution Shift Detected",
                    evidence=f"Maximum feature PSI = {max_psi:.4f} in [0.10, 0.25) suggests emerging population changes.",
                    remediation="Increase monitoring frequency for drifting features and track segment-level claim development."
                ))

        crit_count = sum(1 for w in warnings if w.severity == "CRITICAL")
        warn_count = sum(1 for w in warnings if w.severity == "WARNING")
        adv_count = sum(1 for w in warnings if w.severity == "ADVISORY")

        if crit_count > 0:
            overall_status = "ACTION_REQUIRED"
            ready = False
            statement = f"Rejected: {crit_count} critical assurance conditions failed. Action required prior to decision execution."
        elif warn_count > 0:
            overall_status = "CONDITIONAL_APPROVAL"
            ready = True
            statement = f"Conditional Approval: Passed with {warn_count} warning(s) requiring actuarial analyst review."
        else:
            overall_status = "ASSURED"
            ready = True
            statement = "Fully Assured: All data quality, model calibration, reconciliation, and stability rules verified."

        return AssuranceEvaluationResult(
            overall_assurance_status=overall_status,
            is_decision_ready=ready,
            critical_warnings_count=crit_count,
            warning_count=warn_count,
            advisory_count=adv_count,
            warnings=warnings,
            signoff_statement=statement
        )


# Global singleton instance
assurance_engine = AssuranceEngine()
