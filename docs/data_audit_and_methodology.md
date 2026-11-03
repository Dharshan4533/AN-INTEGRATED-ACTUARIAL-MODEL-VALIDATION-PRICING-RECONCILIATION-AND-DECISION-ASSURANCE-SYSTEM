# Data Audit and Actuarial Methodology Report

## 1. Executive Summary & Purpose

This document provides the formal data audit, methodological specification, and architecture definitions for the **AI-Powered Actuarial Risk and Insurance Decision Support System**.

The application models motor third-party liability (MTPL) insurance using the well-established French research benchmark datasets:
- `freMTPL2freq.csv` (Policy exposure, risk characteristics, and claim counts)
- `freMTPL2sev.csv` (Individual claim amounts)

The system is developed as an actuarial analytics, risk-tiering, what-if, portfolio simulation, and decision-support demonstration platform.

---

## 2. Mandatory Data Audit Findings

### 2.1 File Characteristics & Schema

| Dataset | File Size | Row Count | Column Count | Primary Key / Link Key |
|---|---|---|---|---|
| `freMTPL2freq.csv` | ~31.5 MB | 678,013 | 12 | `IDpol` (Unique policy ID) |
| `freMTPL2sev.csv` | ~376 KB | 26,639 | 2 | `IDpol` (Foreign key to policy) |

#### Frequency Dataset Schema (`freMTPL2freq`):
1. `IDpol` (numeric / float64, integer equivalent): Unique policy identifier. (Excluded from model features to prevent memorization).
2. `ClaimNb` (int64): Number of claims reported during the exposure period.
3. `Exposure` (float64): Duration of policy coverage in years (earned exposure).
4. `Area` (categorical: A, B, C, D, E, F): Urban/rural area classification.
5. `VehPower` (int64: 4 to 15): Vehicle power rating group.
6. `VehAge` (int64: 0 to 100): Age of the vehicle in years.
7. `DrivAge` (int64: 18 to 100): Age of the driver in years.
8. `BonusMalus` (int64: 50 to 230): French statutory rating scale (50 = 50% discount, 100 = baseline, 230 = 130% surcharge).
9. `VehBrand` (categorical: B1 to B14): Vehicle manufacturer brand category.
10. `VehGas` (categorical: 'Regular', 'Diesel'): Fuel type.
11. `Density` (int64: 1 to 27,000): Population density per km² in the policyholder's municipality.
12. `Region` (categorical: 22 French administrative regions, e.g., R24, R82, R93, R11).

#### Severity Dataset Schema (`freMTPL2sev`):
1. `IDpol` (int64): Policy identifier matching `freMTPL2freq`.
2. `ClaimAmount` (float64): Individual claim payout in Euros (€).

---

### 2.2 Data Quality & Missing Value Inspection

- **Missing Values**: Exactly **0 null values** across all 12 columns in `freMTPL2freq` and 0 null values in `freMTPL2sev`.
- **Exact Duplicates**:
  - `freMTPL2freq`: **0 duplicate rows**, all 678,013 `IDpol` entries are unique.
  - `freMTPL2sev`: 255 records share the exact same `(IDpol, ClaimAmount)` combination, representing multiple claims or distinct sub-claim settlement tranches under the same policy.
- **Exposure Integrity**:
  - Minimum exposure: `0.00273` years (~1 day).
  - Maximum exposure: `2.01` years.
  - Exactly **0 records** have non-positive (`<= 0`) exposure.
  - `1,224` records have `Exposure > 1.0` (policies written for multi-year terms or boundary overlaps). In line with standard actuarial practice, exposure is capped at 1.0 for annual frequency rate calculations, and used as an offset `log(Exposure)` during Poisson GLM regression.
- **Claim Count Distribution**:
  - `ClaimNb == 0`: 643,953 policies (94.98%).
  - `ClaimNb == 1`: 32,178 policies (4.75%).
  - `ClaimNb == 2`: 1,784 policies (0.26%).
  - `ClaimNb >= 3`: 98 policies (0.014%).
  - Maximum claim count: 16 claims.
- **Claim Amount Distribution**:
  - Exactly **0 records** have zero (`== 0`) or negative (`< 0`) amounts.
  - Minimum claim amount: `1.00 €`.
  - Median claim amount: `1,172.00 €`.
  - Mean claim amount: `2,278.54 €`.
  - 95th Percentile: `4,861.68 €`.
  - 99th Percentile: `16,793.70 €`.
  - Maximum claim amount: `4,075,400.56 €` (extreme bodily injury liability outlier).
  - Total claims > 100,000 €: 42 records.
  - Total claims > 1,000,000 €: 3 records.

---

### 2.3 Linkage Analysis (Frequency vs. Severity)

- Unique `IDpol` in severity dataset: 24,950 policies.
- Policies in `sev` found in `freq`: 24,944 policies.
- Orphan `IDpol` in `sev` not in `freq`: **6 policies** (discarded).
- Policies with `ClaimNb > 0` in `freq`: 34,060 policies.
- Policies with positive claims in `freq` that have matching severity records: 24,944 policies.
- Positive-claim policies without severity records: **9,116 policies**.
  - *Actuarial Rationale*: In statutory French MTPL claims processing, open claims without finalized settlements, zero-cost third-party claims, or administrative sub-claims are recorded in frequency logs before settlement tranches appear in the severity register.
- **One-to-Many Severity Relationship**:
  - 23,571 policies have 1 claim record in `sev`.
  - 1,298 policies have 2 claim records.
  - 62 policies have 3 claim records, up to 11+ records for fleet/multi-incident accounts.
- **Severity Modeling Population Strategy**:
  - We link each individual valid claim in `sev` with its corresponding policy risk covariates in `freq`.
  - To prevent extreme catastrophic losses (e.g., single 4M€ claims) from distorting the attritional Gamma GLM link, attritional severity is capped at the 99.5th percentile (~25,000 €) for base severity GLM fitting, with a separate documented large-loss loading, ensuring sound, robust estimation.

---

## 3. Important Data Limitation & International Disclaimer

1. **Origin of Data**: The datasets reflect French personal motor third-party liability insurance from 2003–2004.
2. **Regulatory & Geographic Scope**: Features such as `Region` (e.g., R24 Centre-Val de Loire, R11 Île-de-France), `BonusMalus` (French statutory coefficient), and `VehPower` reflect French insurance legal conventions.
3. **Not Representative of the Indian Insurance Market**:
   - These data do NOT represent Indian motor tariffs, IRDAI regulations, or Indian vehicle classes.
   - BonusMalus cannot be equated with Indian No Claim Bonus (NCB), as French BonusMalus ranges from 50 to 230 with legal surcharge rules.
   - Currency is officially Euros (€).
4. **Currency Display Rules**:
   - The primary currency of all actuarial models is **EUR (€)**.
   - If an illustrative conversion to **INR (₹)** is toggled in the UI, it uses a documented, transparent benchmark rate: **1 EUR = 90.00 INR** (documented in assumptions with timestamp). Values are never misrepresented as native Indian market data.

---

## 4. Actuarial Modeling Methodology

### 4.1 Claim Frequency Model (Poisson GLM)

We model the expected claim count $E[N_i]$ for policy $i$ using a Poisson GLM with canonical log link and log-exposure offset:
$$\log(E[N_i]) = \mathbf{X}_i \boldsymbol{\beta} + \log(\text{Exposure}_i)$$
which implies:
$$E[N_i] = \text{Exposure}_i \times \exp(\mathbf{X}_i \boldsymbol{\beta})$$

The **Annualized Expected Claim Frequency** (for 1 full year, Exposure = 1.0) is:
$$\lambda_i = \exp(\mathbf{X}_i \boldsymbol{\beta})$$

The **Expected Claim Count for Policy Term** with exposure $e_i$ is:
$$\hat{N}_i = \lambda_i \times e_i$$

*Exposure is never double-counted.*

### 4.2 Claim Severity Model (Gamma GLM)

We model the expected claim severity $E[Y_i | N_i > 0]$ for eligible positive claims using a Gamma GLM with log link:
$$\log(E[Y_i]) = \mathbf{X}_i \boldsymbol{\gamma} \implies \hat{Y}_i = \exp(\mathbf{X}_i \boldsymbol{\gamma})$$

The Gamma distribution accounts for strictly positive claim amounts and positive skewness (variance proportional to mean squared: $\text{Var}(Y) = \phi \mu^2$).

### 4.3 Expected Loss & Pure Premium

$$\text{Annual Pure Premium} = \lambda_i \times \hat{Y}_i$$
$$\text{Expected Loss for Policy Term} = \lambda_i \times \hat{Y}_i \times \text{Exposure}_i$$

### 4.4 Illustrative Commercial Premium

To convert pure risk cost into a commercial tariff, we apply a configurable, documented actuarial expense and margin loading:
$$\text{Commercial Premium} = \frac{\text{Expected Loss} + \text{Fixed Expense}}{1 - \text{Variable Expense Ratio} - \text{Risk Margin} - \text{Profit Margin}}$$

Validation Constraint:
$$1 - (\text{Variable Expense Ratio} + \text{Risk Margin} + \text{Profit Margin}) > 0$$
Default Benchmark Assumptions (Configurable):
- Fixed Expense per Policy: **30.00 €**
- Variable Expense Ratio: **15.0%** (0.15)
- Risk Margin: **5.0%** (0.05)
- Profit Margin: **5.0%** (0.05)
- Statutory Insurance Tax (applicable separately): **18.0%**

### 4.5 Risk Classification (Tiers)

Policies are categorized into four transparent risk tiers based on their predicted Annual Pure Premium quantiles derived from the training baseline:
- **Low Risk**: Pure Premium $\le 35.00\text{ €}$ (Bottom 30% of risk distribution)
- **Moderate Risk**: $35.00\text{ €} < \text{Pure Premium} \le 75.00\text{ €}$ (Next 40%)
- **High Risk**: $75.00\text{ €} < \text{Pure Premium} \le 160.00\text{ €}$ (Next 20%)
- **Very High Risk**: $\text{Pure Premium} > 160.00\text{ €}$ (Top 10% high-risk tail)

### 4.6 Machine Learning Comparison Models

- Frequency: Poisson GLM vs. Poisson Regressor (ElasticNet) vs. HistGradientBoostingRegressor (Poisson loss).
- Severity: Gamma GLM vs. Gamma Regressor vs. HistGradientBoostingRegressor (Gamma loss).
- Evaluated on identical 80/20 train/test held-out split using Poisson deviance, Gamma deviance, MAE, and RMSE.

### 4.7 Portfolio Risk & Monte Carlo Simulation

For aggregate portfolio risk analysis:
1. Frequency $N \sim \text{Poisson}(\sum \lambda_i \cdot e_i)$.
2. Individual claims $Y_k \sim \text{Gamma}(\alpha, \beta)$ or sampled from conditional severity distribution.
3. Total aggregate loss $S = \sum_{k=1}^N Y_k$.
4. Run $M = 10,000$ Monte Carlo simulations with fixed random seed for reproducibility.
5. Calculate empirical risk metrics:
   - $\text{VaR}_\alpha(S) = \inf \{ s : F_S(s) \ge \alpha \}$ for $\alpha \in \{0.95, 0.99, 0.995\}$
   - $\text{TVaR}_\alpha(S) = E[S \mid S \ge \text{VaR}_\alpha(S)] = \frac{1}{1-\alpha} \int_\alpha^1 \text{VaR}_u(S) du$
