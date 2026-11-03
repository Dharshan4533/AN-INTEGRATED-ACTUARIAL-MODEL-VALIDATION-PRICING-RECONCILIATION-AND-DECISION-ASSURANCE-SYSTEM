"""
Actuarial Pricing Engine.
Computes annualized pure premium, exposure-adjusted expected loss,
commercial premium with loading assumptions, and statutory tax breakdown.
"""

from typing import Dict, Any


DEFAULT_PRICING_ASSUMPTIONS = {
    "fixed_expense": 30.00,        # Fixed acquisition and administrative cost per policy in EUR
    "variable_expense_ratio": 0.15, # 15% of gross premium for commissions and operations
    "risk_margin": 0.05,           # 5% cost of capital / solvency buffer
    "profit_margin": 0.05,         # 5% target underwriting profit
    "tax_rate": 0.18,              # 18% statutory insurance duty/tax
    "currency": "EUR",
    "inr_exchange_rate": 90.00,    # 1 EUR = 90.00 INR (Documented benchmark conversion)
    "exchange_rate_source": "ECB / Financial Reference Benchmark 2026",
    "market_context": "French Motor Third-Party Liability research models"
}


class ActuarialPricingEngine:
    def __init__(self, assumptions: Dict[str, Any] = None):
        self.assumptions = dict(DEFAULT_PRICING_ASSUMPTIONS)
        if assumptions:
            self.update_assumptions(assumptions)

    def update_assumptions(self, new_assumptions: Dict[str, Any]):
        """Validate and update pricing assumptions."""
        for k, v in new_assumptions.items():
            if k in self.assumptions:
                self.assumptions[k] = v
        self._validate_assumptions()

    def _validate_assumptions(self):
        """Validate denominator > 0 and positive expenses."""
        fixed = self.assumptions["fixed_expense"]
        var_exp = self.assumptions["variable_expense_ratio"]
        risk = self.assumptions["risk_margin"]
        profit = self.assumptions["profit_margin"]

        if fixed < 0:
            raise ValueError("Fixed expense cannot be negative.")
        if var_exp < 0 or risk < 0 or profit < 0:
            raise ValueError("Expense and margin ratios cannot be negative.")

        denominator = 1.0 - var_exp - risk - profit
        if denominator <= 0.05:
            raise ValueError(
                f"Invalid pricing assumptions: (1 - Variable Expense - Risk Margin - Profit Margin) = {denominator:.4f} <= 0.05. "
                "Total variable loadings exceed 95% of gross premium, making commercial pricing mathematically unstable."
            )

    def calculate_pricing(
        self,
        annualized_frequency: float,
        expected_severity: float,
        exposure: float,
        convert_to_inr: bool = False
    ) -> Dict[str, Any]:
        """
        Calculate complete actuarial pricing breakdown.
        
        Mathematical Formulas:
        - Annual Pure Premium = Annualized Frequency * Expected Severity
        - Term Expected Loss = Annual Pure Premium * Exposure
        - Commercial Premium = (Term Expected Loss + Fixed Expense) / (1 - VarExp - RiskMargin - ProfitMargin)
        - Tax Amount = Commercial Premium * Tax Rate
        - Total Payable Premium = Commercial Premium + Tax Amount
        """
        self._validate_assumptions()

        freq = max(0.0, float(annualized_frequency))
        sev = max(0.0, float(expected_severity))
        exp = max(0.001, float(exposure))

        # Core pure premium and term loss
        annual_pure_premium = freq * sev
        expected_loss = annual_pure_premium * exp

        # Commercial loading calculation
        fixed_exp = float(self.assumptions["fixed_expense"])
        var_exp_ratio = float(self.assumptions["variable_expense_ratio"])
        risk_margin_ratio = float(self.assumptions["risk_margin"])
        profit_margin_ratio = float(self.assumptions["profit_margin"])
        tax_rate = float(self.assumptions["tax_rate"])

        denominator = 1.0 - var_exp_ratio - risk_margin_ratio - profit_margin_ratio
        commercial_premium = (expected_loss + fixed_exp) / denominator

        variable_expense_amount = commercial_premium * var_exp_ratio
        risk_margin_amount = commercial_premium * risk_margin_ratio
        profit_margin_amount = commercial_premium * profit_margin_ratio
        tax_amount = commercial_premium * tax_rate
        total_payable = commercial_premium + tax_amount

        rate = float(self.assumptions["inr_exchange_rate"]) if convert_to_inr else 1.0
        currency_code = "INR" if convert_to_inr else "EUR"
        currency_symbol = "₹" if convert_to_inr else "€"

        return {
            "annualized_frequency": round(freq, 5),
            "expected_claim_count_term": round(freq * exp, 5),
            "expected_severity": round(sev * rate, 2),
            "exposure_years": round(exp, 4),
            "currency": currency_code,
            "currency_symbol": currency_symbol,
            "is_converted_currency": convert_to_inr,
            "conversion_rate_used": rate if convert_to_inr else None,
            "pricing_breakdown": {
                "annual_pure_premium": round(annual_pure_premium * rate, 2),
                "term_expected_loss": round(expected_loss * rate, 2),
                "fixed_expense": round(fixed_exp * rate, 2),
                "variable_expense": round(variable_expense_amount * rate, 2),
                "risk_margin": round(risk_margin_amount * rate, 2),
                "profit_margin": round(profit_margin_amount * rate, 2),
                "commercial_premium_before_tax": round(commercial_premium * rate, 2),
                "statutory_tax": round(tax_amount * rate, 2),
                "total_commercial_premium": round(total_payable * rate, 2)
            },
            "assumptions_applied": {
                "fixed_expense_eur": fixed_exp,
                "variable_expense_ratio": var_exp_ratio,
                "risk_margin_ratio": risk_margin_ratio,
                "profit_margin_ratio": profit_margin_ratio,
                "tax_rate": tax_rate,
                "denominator": round(denominator, 4)
            }
        }
