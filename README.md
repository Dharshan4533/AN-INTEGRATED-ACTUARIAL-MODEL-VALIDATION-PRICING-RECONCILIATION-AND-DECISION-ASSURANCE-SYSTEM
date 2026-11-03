# AI-Powered Actuarial Risk and Insurance Decision Support System

A complete web-based actuarial risk assessment, generalized linear modeling (GLM), pure premium pricing, what-if sensitivity, explainability, and stochastic portfolio loss decision-support system.

Built from scratch using **Python**, **FastAPI**, **statsmodels**, **scikit-learn**, **SHAP**, **Vanilla JavaScript**, **CSS3**, and **Chart.js**.

---

## 1. Executive Summary & Problem Context

Insurance rate-making and underwriting decision support require rigorous actuarial modeling grounded in Generalized Linear Models (GLMs), correct exposure treatment, compound loss distributions, and transparent capital requirements.

This system solves key actuarial workflows:
1. **Claim Frequency Modeling**: Poisson GLM with canonical log link and log-exposure offset ($\log(E[N_i]) = \mathbf{X}_i \boldsymbol{\beta} + \log(\text{Exposure}_i)$).
2. **Claim Severity Modeling**: Gamma GLM with log link for eligible positive claims ($\log(E[Y_i]) = \mathbf{X}_i \boldsymbol{\gamma}$).
3. **Pure Premium & Commercial Tariffs**: Consistent mathematical pricing without exposure double-counting, incorporating configurable administrative loadings, risk margins, profit margins, and statutory insurance duties.
4. **Multi-Profile Comparison & What-If Analysis**: Sensitivity analysis evaluating how changes in vehicle rating, age, or statutory rating affect risk and pricing.
5. **SHAP & Statistical Explainability**: Local attribution identifying top risk drivers and mitigators, and global feature importance rankings.
6. **Portfolio Aggregate Loss & Tail Risk (VaR / TVaR)**: Monte Carlo compound Poisson-Gamma stochastic loss simulations computing Value at Risk (VaR 95%, 99%, 99.5%) and Tail Value at Risk (TVaR / Expected Shortfall).
7. **Empirical Model Validation**: Real held-out 80/20 test partition evaluations, decile calibration curves, and GLM vs. Machine Learning benchmarks.

---

## 2. Dataset Audit & Essential Data Limitations

The system models motor third-party liability (MTPL) insurance using the canonical research benchmark datasets:
- `data/raw/freMTPL2freq.csv` (678,013 policies, 12 features)
- `data/raw/freMTPL2sev.csv` (26,639 individual claim records)

### Mandatory Data Audit Summary

| Check | Frequency Dataset (`freMTPL2freq`) | Severity Dataset (`freMTPL2sev`) |
|---|---|---|
| **Records** | 678,013 | 26,639 |
| **Columns** | 12 | 2 (`IDpol`, `ClaimAmount`) |
| **Missing Values** | Exactly 0 nulls | Exactly 0 nulls |
| **Duplicates** | 0 exact duplicate rows | 255 multi-claim records under identical policy |
| **Exposure** | Min: 0.00273 yrs, Max: 2.01 yrs, strictly $> 0$ | Linked to policyholder characteristics |
| **Claim Counts** | 0 claims: 643,953 (94.98%), $\ge 1$ claim: 34,060 (5.02%) | -- |
| **Claim Amounts** | -- | Min: 1.00 €, Median: 1,172.00 €, Mean: 2,278.54 €, Max: 4,075,400.56 € |
| **Linkage** | 34,060 policies with claims; 24,944 match severity records | 24,944 matched; 6 orphan records removed |

### International Market Disclaimer
- **Origin**: French personal motor third-party liability insurance.
- **Regulatory Framework**: Features such as French `BonusMalus` (50–230 statutory coefficient), `VehPower`, and administrative regions (`Region`) are specific to the French motor market.
- **Not Indian Motor Tariffs**: This dataset does not represent Indian motor insurance tariffs or IRDAI regulations. French BonusMalus is not equivalent to Indian No Claim Bonus (NCB).
- **Currency**: Official model currency is **Euro (€)**. An illustrative **INR (₹)** toggle is provided for currency presentation using a benchmark rate of **1 EUR = 90.00 INR** (documented in assumptions). Values are never misrepresented as native Indian data.

---

## 3. Technology Stack

- **Backend**: Python 3.13+, FastAPI, Pydantic v2, Uvicorn.
- **Statistical & ML Models**: statsmodels (Poisson GLM, Gamma GLM), scikit-learn (Poisson Regressor, Gamma Regressor, HistGradientBoostingRegressor), SHAP.
- **Data & Computation**: pandas, NumPy, SciPy.
- **Frontend**: HTML5, CSS3 (Fintech design system), Vanilla JavaScript (ES6+), Chart.js.
- **Testing**: pytest (16 unit and API integration tests passing).

---

## 4. Project Architecture

```
actuarial-insurance-system/
├── backend/
│   ├── api/
│   │   ├── explainability.py      # /api/v1/explain
│   │   ├── portfolio.py           # /api/v1/portfolio/simulate & summary
│   │   ├── pricing.py             # /api/v1/quotes, compare, what-if
│   │   ├── stress_testing.py      # /api/v1/stress-test
│   │   └── validation.py          # /api/v1/model/validation & comparison
│   ├── core/
│   │   └── config.py              # Application settings and paths
│   ├── schemas/
│   │   ├── portfolio_schema.py    # Pydantic simulation & stress models
│   │   └── pricing_schema.py      # Pydantic policy & quote models
│   ├── services/
│   │   ├── pricing_service.py     # GLM inference & quotation engine
│   │   └── simulation_service.py  # Monte Carlo loss & VaR/TVaR simulator
│   └── main.py                    # FastAPI entry point & static file mount
│
├── actuarial/
│   ├── preprocessing.py           # ActuarialPreprocessor & design matrix
│   ├── pricing.py                 # Pure & commercial premium formulas
│   ├── risk_tiering.py            # Documented empirical risk tiers
│   ├── train_frequency.py         # Offline Poisson GLM training
│   ├── train_severity.py          # Offline Gamma GLM training
│   ├── train_ml.py                # GLM vs ML comparison models
│   └── data_audit.py              # 10 mandatory audit checks
│
├── explainability/
│   └── shap_service.py            # Local & global feature attribution
│
├── data/
│   ├── raw/
│   │   ├── freMTPL2freq.csv       # Frequency dataset
│   │   └── freMTPL2sev.csv        # Severity dataset
│   └── processed/
│       └── benchmark_portfolio.csv# 1,000 policy benchmark portfolio
│
├── models/                        # Saved artifacts & metadata
│   ├── frequency_glm.joblib
│   ├── frequency_metadata.json
│   ├── severity_glm.joblib
│   ├── severity_metadata.json
│   ├── preprocessor.joblib
│   ├── preprocessor_schema.json
│   ├── ml_comparison.json
│   ├── shap_global.json
│   └── risk_tier_config.json
│
├── frontend/
│   ├── index.html                 # Master responsive layout
│   ├── pages/                     # Page template fragments (1 to 9)
│   ├── css/
│   │   ├── main.css
│   │   ├── components.css
│   │   └── responsive.css
│   └── js/
│       ├── api.js                 # Asynchronous API client
│       ├── app.js                 # State & navigation router
│       ├── charts.js              # Chart.js visualizations
│       └── pricing.js             # Quote & what-if form handlers
│
├── tests/
│   ├── test_actuarial_engine.py   # Unit tests for formulas & exposure
│   └── test_api_endpoints.py      # Integration tests for FastAPI
├── docs/
│   ├── data_audit_and_methodology.md
│   └── data_audit_report.json
├── requirements.txt
├── .env.example
└── README.md
```

---

## 5. Quickstart & Installation

### Step 1: Initialize Virtual Environment & Install Dependencies
```bash
# Clone or navigate to repository
cd "c:\Users\dhars\Desktop\final lean project"

# Activate virtual environment
.venv\Scripts\activate

# Install dependencies (already prepared in requirements.txt)
pip install -r requirements.txt
```

### Step 2: (Optional) Retrain Actuarial Models
Models are pre-trained and saved in `models/`. To reproduce training:
```bash
python -m actuarial.train_frequency
python -m actuarial.train_severity
python -m actuarial.train_ml
python -m actuarial.generate_shap_cache
```

### Step 3: Run the Verification Test Suite
```bash
pytest -v
```
*Result: 16 passed tests covering pure premium, exposure non-double counting, commercial loading denominators, risk tiers, and API endpoints.*

### Step 4: Launch the Web Application
```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```
Open your browser at: **[http://localhost:8000](http://localhost:8000)**

---

## 6. Key Actuarial Validation Results

### Frequency Model (Poisson GLM with Log-Exposure Offset)
- **Observed Test Claims**: 7,225
- **Expected Test Claims**: 7,206.98
- **Observed / Expected (O/E) Ratio**: **1.0025** *(virtually 1.0000, perfect calibration)*
- **Poisson Deviance**: 43,278.10
- **Mean Absolute Error**: 0.09873

### Severity Model (Gamma GLM with Log Link)
- **Observed Mean Severity**: 1,684.22 €
- **Predicted Mean Severity**: 1,693.49 €
- **Gamma Deviance**: 6,080.37
- **Mean Absolute Error**: 1,279.51 €
- **RMSE**: 3,184.51 €

### Actuarial GLM vs. ML Benchmark Comparison
- Poisson GLM with offset achieved an O/E ratio of **1.0025**, outperforming unconstrained gradient boosted trees (O/E ~1.57), demonstrating the actuarial requirement for explicit exposure offset parameterization.

---

## 7. Interactive Decision Support Pages

1. **Executive Overview**: Portfolio risk composition donut chart, aggregate exposure, frequency O/E ratio, and system health status.
2. **Policy Pricing**: Real-time slider and dropdown policy entry, frequency and severity GLM prediction, pure premium, exposure term expected loss, commercial loadings waterfall, risk tier badge, and top attributed risk factors.
3. **Profile Comparison**: Side-by-side comparison of 2 to 5 policy profiles with automated identification of lowest cost and highest risk policyholders.
4. **What-If Analysis**: Elasticity analysis evaluating how driver age, bonus-malus rating, or vehicle power modifications alter frequency, severity, and commercial premium.
5. **SHAP Explainability**: Global feature importance horizontal bar charts and local attributions identifying risk drivers and mitigators.
6. **Portfolio Loss & Tail Risk (VaR / TVaR)**: 5,000-run Monte Carlo compound Poisson-Gamma stochastic simulation generating loss histograms and empirical VaR (95%, 99%, 99.5%) and TVaR for Solvency II capital assessment.
7. **Stress Testing**: Adverse scenario testing (weather shock, inflation surge, rating drift) evaluating capital buffer additions.
8. **Model Validation**: Real held-out 80/20 test metrics, 10-decile calibration curves for frequency and severity, and comprehensive ML model comparison tables.
9. **Methodology & Assumptions**: Mathematical formulas, exposure rules, configurable expense ratios, and documented empirical risk tier thresholds.

---

## 8. License & Attribution

Designed and implemented in Antigravity as an advanced actuarial analytics, Generalized Linear Model rate-making, and stochastic decision-support demonstration.
Dataset: French Motor Third-Party Liability (`freMTPL2`) published by Charpentier & Dutang.
