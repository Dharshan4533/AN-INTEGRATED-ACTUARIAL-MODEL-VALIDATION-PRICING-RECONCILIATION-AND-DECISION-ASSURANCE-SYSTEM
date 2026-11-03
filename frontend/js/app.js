/**
 * Main Application Manager.
 * Handles page navigation, global state, currency toggling, and page initializations.
 */

const appState = {
  currentPage: 'rate-change-overview',
  currency: 'USD',
  exchangeRate: 90.00,
  health: null,
  config: null
};

const app = {
  async init() {
    console.log("Initializing Actuarial Decision Support System...");
    this.setupNavigation();
    this.setupCurrencyToggle();
    this.setupFormRangeSync();

    // Default to Rate Change Assurance Workbench immediately for responsiveness
    this.navigateTo('rate-change-overview');

    // Fetch health and config asynchronously in background
    apiClient.getHealth().then(h => {
      appState.health = h;
      this.updateSystemStatusUI();
    }).catch(e => console.warn("Backend health check failed:", e));

    apiClient.getConfig().then(c => {
      appState.config = c;
      if (c && c.inr_conversion_rate) {
        appState.exchangeRate = c.inr_conversion_rate;
      }
    }).catch(e => console.warn("Backend config fetch failed:", e));
  },

  setupNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const targetPage = item.getAttribute('data-page');
        if (targetPage) {
          this.navigateTo(targetPage);
        }
      });
    });
  },

  navigateTo(pageId) {
    appState.currentPage = pageId;

    // Update sidebar active state
    document.querySelectorAll('.nav-item').forEach(item => {
      if (item.getAttribute('data-page') === pageId) {
        item.classList.add('active');
      } else {
        item.classList.remove('active');
      }
    });

    // Update views
    document.querySelectorAll('.page-view').forEach(view => {
      view.classList.remove('active');
    });

    const activeView = document.getElementById(`view-${pageId}`);
    if (activeView) {
      activeView.classList.add('active');
    }

    // Update page title
    const titles = {
      'rate-change-overview': 'Rate Change Assurance Overview',
      'rating-manuals': 'Rating Manuals & Specifications Comparison',
      'census-attribution': 'Policy Census & Sequential Factor Attribution',
      'dislocation-matrix': 'Policyholder Dislocation & Segment Analysis',
      'audit-ledger': 'Cryptographic Audit Ledger & Assurance Reports',
      'overview': 'Executive Actuarial Overview (GLM Subsystem)',
      'policy-pricing': 'Policyholder Risk Assessment & Pricing Engine',
      'policy-comparison': 'Multi-Profile Actuarial Comparison',
      'what-if': 'What-If & Sensitivity Analysis',
      'explainability': 'SHAP Model Explainability & Attribution',
      'portfolio': 'Portfolio Aggregate Loss & Tail Risk (VaR / TVaR)',
      'validation': 'Model Validation & ML Benchmarking',
      'stress-testing': 'Scenario Stress Testing & Solvency Buffer',
      'reconciliation': 'Statistical Model Reconciliation',
      'dossier': 'Actuarial Model Validation & Assurance Dossier',
      'assumptions': 'Actuarial Methodology & Assumptions'
    };
    const titleElem = document.getElementById('topbar-page-title');
    if (titleElem) titleElem.innerText = titles[pageId] || 'Actuarial Analytics';

    // Page-specific trigger
    this.onPageLoaded(pageId);
  },

  onPageLoaded(pageId) {
    switch (pageId) {
      case 'rate-change-overview':
      case 'rating-manuals':
      case 'census-attribution':
      case 'dislocation-matrix':
      case 'audit-ledger':
        if (typeof rateChangeWorkbench !== 'undefined') {
          rateChangeWorkbench.init();
        }
        break;
      case 'overview':
        this.loadOverviewData();
        break;
      case 'policy-pricing':
        pricingModule.calculateSingleQuote();
        break;
      case 'policy-comparison':
        if (pricingModule.comparisonProfiles.length === 0) {
          pricingModule.initComparison();
        }
        pricingModule.runComparison();
        break;
      case 'what-if':
        pricingModule.runWhatIf();
        break;
      case 'explainability':
        this.loadExplainabilityData();
        break;
      case 'portfolio':
        this.loadPortfolioData();
        break;
      case 'validation':
        this.loadValidationData();
        break;
      case 'stress-testing':
        this.loadStressTestData();
        break;
      case 'reconciliation':
        reconciliation.executeReconciliation();
        break;
    }
  },

  setupCurrencyToggle() {
    const btnUsd = document.getElementById('currency-btn-usd');
    const btnEur = document.getElementById('currency-btn-eur');
    const btnInr = document.getElementById('currency-btn-inr');
    const disclaimer = document.getElementById('currency-disclaimer-text');

    if (btnUsd) {
      btnUsd.addEventListener('click', () => {
        appState.currency = 'USD';
        btnUsd.classList.add('active');
        if (btnEur) btnEur.classList.remove('active');
        if (btnInr) btnInr.classList.remove('active');
        if (disclaimer) disclaimer.innerHTML = "⚖️ <strong>Rate Change Assurance Workbench:</strong> Active tariff comparison in US Dollar ($) with exact zero-residual reconciliation.";
        this.refreshActiveCalculations();
      });
    }

    if (btnEur && btnInr) {
      btnEur.addEventListener('click', () => {
        appState.currency = 'EUR';
        btnEur.classList.add('active');
        if (btnUsd) btnUsd.classList.remove('active');
        btnInr.classList.remove('active');
        if (disclaimer) disclaimer.innerHTML = "⚖️ <strong>Actuarial Modeling Subsystem:</strong> Base Currency: Euro (€) from French MTPL Research Benchmark.";
        this.refreshActiveCalculations();
      });

      btnInr.addEventListener('click', () => {
        appState.currency = 'INR';
        btnInr.classList.add('active');
        if (btnUsd) btnUsd.classList.remove('active');
        btnEur.classList.remove('active');
        if (disclaimer) disclaimer.innerHTML = `⚖️ <strong>INR Conversion:</strong> Illustrative INR (₹) Conversion @ 1 EUR = ${appState.exchangeRate} INR (ECB Ref).`;
        this.refreshActiveCalculations();
      });
    }
  },

  refreshActiveCalculations() {
    if (appState.currentPage === 'policy-pricing') {
      pricingModule.calculateSingleQuote();
    } else if (appState.currentPage === 'policy-comparison') {
      pricingModule.runComparison();
    } else if (appState.currentPage === 'what-if') {
      pricingModule.runWhatIf();
    } else if (appState.currentPage === 'portfolio') {
      this.loadPortfolioData();
    } else if (appState.currentPage === 'overview') {
      this.loadOverviewData();
    } else if (appState.currentPage === 'validation') {
      this.loadValidationData();
    } else if (appState.currentPage === 'stress-testing') {
      this.loadStressTestData();
    } else if (appState.currentPage === 'reconciliation') {
      reconciliation.executeReconciliation();
    }
  },

  setupFormRangeSync() {
    // Synchronize range sliders with their badges
    document.querySelectorAll('.range-slider').forEach(slider => {
      const badgeId = slider.getAttribute('data-badge');
      if (badgeId) {
        const badge = document.getElementById(badgeId);
        slider.addEventListener('input', () => {
          if (badge) badge.innerText = slider.value;
        });
      }
    });
  },

  updateSystemStatusUI() {
    const pill = document.getElementById('status-pill-text');
    if (pill && appState.health) {
      pill.innerText = appState.health.status === 'healthy' ? 'Models Active' : 'Degraded';
    }
  },

  // Overview Page
  async loadOverviewData() {
    try {
      const summary = await apiClient.getPortfolioSummary();
      const val = await apiClient.getModelValidation();
      const rate = appState.currency === 'INR' ? appState.exchangeRate : 1.0;
      const cur = appState.currency === 'INR' ? '₹' : '€';

      document.getElementById('ov-kpi-policies').innerText = summary.total_policies.toLocaleString();
      document.getElementById('ov-kpi-exposure').innerText = `${Math.round(summary.total_exposure_years).toLocaleString()} Yrs`;
      document.getElementById('ov-kpi-oe').innerText = val.frequency_model.evaluation_metrics.test_oe_ratio.toFixed(4);
      document.getElementById('ov-kpi-mean-sev').innerText = `${Math.round(val.severity_model.evaluation_metrics.test_mean_predicted_severity * rate).toLocaleString()} ${cur}`;

      charts.renderRiskDistribution('overview-risk-chart', [30, 40, 20, 10]);
    } catch (e) {
      console.warn("Overview data load error:", e);
    }
  },

  // Explainability Page
  async loadExplainabilityData() {
    try {
      const globalData = await apiClient.getGlobalExplainability();
      charts.renderFeatureImportance('shap-freq-importance-chart', globalData.frequency_importance);
      charts.renderFeatureImportance('shap-sev-importance-chart', globalData.severity_importance);
    } catch (e) {
      console.warn("Explainability load error:", e);
    }
  },

  // Portfolio Page
  async loadPortfolioData() {
    const req = {
      portfolio_source: 'benchmark',
      n_simulations: 5000,
      random_seed: 42,
      confidence_levels: [0.95, 0.99, 0.995],
      convert_to_inr: appState.currency === 'INR'
    };

    try {
      const res = await apiClient.simulatePortfolio(req);
      const cur = res.currency_symbol;

      document.getElementById('port-kpi-total-loss').innerText = `${res.expected_total_loss.toLocaleString()} ${cur}`;
      document.getElementById('port-kpi-mean-sim').innerText = `${res.mean_simulated_loss.toLocaleString()} ${cur}`;
      document.getElementById('port-kpi-std').innerText = `${res.std_simulated_loss.toLocaleString()} ${cur}`;
      document.getElementById('port-kpi-skew').innerText = res.loss_skewness.toFixed(3);

      // Render Table
      const tbody = document.getElementById('portfolio-var-tbody');
      if (tbody) {
        tbody.innerHTML = res.risk_measures.map(rm => `
          <tr>
            <td><strong>${rm.confidence_percent}</strong></td>
            <td class="table-num"><strong>${rm.var.toLocaleString()} ${cur}</strong></td>
            <td class="table-num"><span class="badge badge-very-high">${rm.tvar.toLocaleString()} ${cur}</span></td>
            <td>Solvency II / SST Benchmark</td>
          </tr>
        `).join('');
      }

      const var99 = res.risk_measures.find(r => r.confidence_level === 0.99)?.var || 0;
      const tvar99 = res.risk_measures.find(r => r.confidence_level === 0.99)?.tvar || 0;
      charts.renderPortfolioHistogram('portfolio-loss-histogram', res.loss_histogram, var99, tvar99, cur);

      document.getElementById('port-sim-assumptions').innerText = res.assumptions_summary;
    } catch (e) {
      console.warn("Portfolio simulation error:", e);
    }
  },

  // Model Validation Page
  async loadValidationData() {
    try {
      const val = await apiClient.getModelValidation();
      const comp = await apiClient.getMLComparison();

      const rate = appState.currency === 'INR' ? appState.exchangeRate : 1.0;
      const cur = appState.currency === 'INR' ? '₹' : '€';

      // Frequency GLM Metrics
      const fMeta = val.frequency_model.evaluation_metrics;
      document.getElementById('val-freq-oe').innerText = fMeta.test_oe_ratio.toFixed(4);
      document.getElementById('val-freq-dev').innerText = fMeta.test_poisson_deviance.toLocaleString();
      document.getElementById('val-freq-mae').innerText = fMeta.test_mae.toFixed(5);
      document.getElementById('val-freq-claims').innerText = `${fMeta.test_observed_claims} / ${Math.round(fMeta.test_expected_claims)}`;

      // Severity GLM Metrics
      const sMeta = val.severity_model.evaluation_metrics;
      document.getElementById('val-sev-dev').innerText = sMeta.test_gamma_deviance.toLocaleString();
      document.getElementById('val-sev-mae').innerText = `${Math.round(sMeta.test_mae * rate).toLocaleString()} ${cur}`;
      document.getElementById('val-sev-rmse').innerText = `${Math.round(sMeta.test_rmse * rate).toLocaleString()} ${cur}`;
      document.getElementById('val-sev-means').innerText = `${Math.round(sMeta.test_mean_observed_severity * rate).toLocaleString()} ${cur} / ${Math.round(sMeta.test_mean_predicted_severity * rate).toLocaleString()} ${cur}`;

      // Scaled deciles for calibration chart
      const scaledSevDeciles = val.severity_model.calibration_deciles.map(d => ({
        ...d,
        mean_observed_severity: d.mean_observed_severity * rate,
        mean_predicted_severity: d.mean_predicted_severity * rate
      }));

      // Calibration charts
      charts.renderCalibrationChart(
        'calibration-freq-chart',
        val.frequency_model.calibration_deciles,
        'Annual Claim Frequency Rate',
        'Observed Rate',
        'Expected GLM Rate'
      );

      charts.renderCalibrationChart(
        'calibration-sev-chart',
        scaledSevDeciles,
        `Mean Claim Severity (${cur})`,
        'Observed Mean Severity',
        'Predicted GLM Severity'
      );

      // ML Comparison Table
      const compTbody = document.getElementById('ml-comparison-tbody');
      if (compTbody && comp.comparison) {
        const fModels = comp.comparison.frequency;
        const sModels = comp.comparison.severity;
        compTbody.innerHTML = `
          <tr style="background:#f8fafc;"><td colspan="6"><strong>Frequency Models (Poisson Objective)</strong></td></tr>
          ${Object.values(fModels).map(m => `
            <tr>
              <td><strong>${m.model_name}</strong></td>
              <td>${m.type}</td>
              <td class="table-num">${m.poisson_deviance}</td>
              <td class="table-num">${m.mae}</td>
              <td class="table-num"><strong>${m.oe_ratio ? m.oe_ratio.toFixed(4) : 'N/A'}</strong></td>
              <td>${m.notes}</td>
            </tr>
          `).join('')}
          <tr style="background:#f8fafc;"><td colspan="6"><strong>Severity Models (Gamma Objective)</strong></td></tr>
          ${Object.values(sModels).map(m => `
            <tr>
              <td><strong>${m.model_name}</strong></td>
              <td>${m.type}</td>
              <td class="table-num">${m.gamma_deviance}</td>
              <td class="table-num">${Math.round(m.mae * rate).toLocaleString()} ${cur}</td>
              <td class="table-num">${Math.round(m.rmse * rate).toLocaleString()} ${cur}</td>
              <td>${m.notes}</td>
            </tr>
          `).join('')}
        `;
      }
    } catch (e) {
      console.warn("Validation data load error:", e);
    }
  },

  // Stress Testing Page
  async loadStressTestData() {
    this.runStressScenario(1.15, 1.10, 0.0, "Adverse Weather & Inflation Shock (+15% Freq, +10% Sev)");
  },

  async runStressScenario(freqMult, sevMult, bmShift, name) {
    const req = {
      name: name,
      frequency_multiplier: freqMult,
      severity_multiplier: sevMult,
      bonus_malus_shift: bmShift,
      n_simulations: 3000,
      random_seed: 42,
      convert_to_inr: appState.currency === 'INR'
    };

    try {
      const res = await apiClient.runStressTest(req);
      const cur = res.currency_symbol;

      document.getElementById('st-scenario-title').innerText = res.scenario_name;
      document.getElementById('st-base-loss').innerText = `${res.baseline_metrics.expected_loss.toLocaleString()} ${cur}`;
      document.getElementById('st-stress-loss').innerText = `${res.stressed_metrics.expected_loss.toLocaleString()} ${cur}`;
      document.getElementById('st-delta-loss').innerText = `+${res.absolute_impact.delta_expected_loss.toLocaleString()} ${cur} (+${res.percentage_impact.pct_expected_loss}%)`;

      document.getElementById('st-base-var').innerText = `${res.baseline_metrics.var_99.toLocaleString()} ${cur}`;
      document.getElementById('st-stress-var').innerText = `${res.stressed_metrics.var_99.toLocaleString()} ${cur}`;
      document.getElementById('st-delta-var').innerText = `+${res.absolute_impact.delta_var_99.toLocaleString()} ${cur} (+${res.percentage_impact.pct_var_99}%)`;

      document.getElementById('st-capital-summary').innerText = res.capital_strain_summary;
    } catch (e) {
      console.warn("Stress test error:", e);
    }
  }
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    app.init();
  });
} else {
  app.init();
}
