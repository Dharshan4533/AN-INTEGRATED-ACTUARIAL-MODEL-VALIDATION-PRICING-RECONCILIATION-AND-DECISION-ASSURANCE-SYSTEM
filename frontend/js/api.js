/**
 * API Client for Actuarial Decision Support System.
 * Communicates with the FastAPI backend at /api/v1/.
 */

const API_BASE = '/api/v1';

const apiClient = {
  async _request(endpoint, options = {}) {
    const url = `${API_BASE}${endpoint}`;
    const defaultHeaders = {
      'Content-Type': 'application/json',
      'Accept': 'application/json'
    };

    try {
      const response = await fetch(url, {
        ...options,
        headers: { ...defaultHeaders, ...options.headers }
      });

      if (!response.ok) {
        let errorDetail = 'API Request Failed';
        try {
          const errData = await response.json();
          errorDetail = errData.detail || JSON.stringify(errData);
        } catch (e) {
          errorDetail = response.statusText;
        }
        throw new Error(errorDetail);
      }

      return await response.json();
    } catch (err) {
      console.error(`API Error on ${url}:`, err);
      throw err;
    }
  },

  async getHealth() {
    return this._request('/health');
  },

  async getConfig() {
    return this._request('/config');
  },

  async getQuote(policy, customAssumptions = null) {
    return this._request('/quotes', {
      method: 'POST',
      body: JSON.stringify({ policy, custom_assumptions: customAssumptions })
    });
  },

  async compareQuotes(policies, customAssumptions = null) {
    return this._request('/quotes/compare', {
      method: 'POST',
      body: JSON.stringify({ policies, custom_assumptions: customAssumptions })
    });
  },

  async whatIfAnalysis(baselinePolicy, revisedPolicy, customAssumptions = null) {
    return this._request('/quotes/what-if', {
      method: 'POST',
      body: JSON.stringify({
        baseline_policy: baselinePolicy,
        revised_policy: revisedPolicy,
        custom_assumptions: customAssumptions
      })
    });
  },

  async getLocalExplanation(policy) {
    return this._request('/explain', {
      method: 'POST',
      body: JSON.stringify(policy)
    });
  },

  async getGlobalExplainability() {
    return this._request('/explain/global');
  },

  async simulatePortfolio(simulateRequest) {
    return this._request('/portfolio/simulate', {
      method: 'POST',
      body: JSON.stringify(simulateRequest)
    });
  },

  async getPortfolioSummary() {
    return this._request('/portfolio/summary');
  },

  async runStressTest(stressRequest) {
    return this._request('/stress-test', {
      method: 'POST',
      body: JSON.stringify(stressRequest)
    });
  },

  async getModelValidation() {
    return this._request('/model/validation');
  },

  async getMLComparison() {
    return this._request('/model/comparison');
  },

  // =========================================================================
  // RATE CHANGE ASSURANCE WORKBENCH ENDPOINTS
  // =========================================================================

  async getRatingManualSamples() {
    return this._request('/rating-manuals/samples');
  },

  async validateRatingManual(manual) {
    return this._request('/rating-manuals/validate', {
      method: 'POST',
      body: JSON.stringify(manual)
    });
  },

  async compareRatingManuals(oldManual, newManual) {
    return this._request('/rating-manuals/compare', {
      method: 'POST',
      body: JSON.stringify({ old_manual: oldManual, new_manual: newManual })
    });
  },

  async getSampleCensus() {
    return this._request('/rate-change/sample-census');
  },

  async evaluatePolicyRateChange(oldManual, newManual, policy) {
    return this._request('/rate-change/evaluate-policy', {
      method: 'POST',
      body: JSON.stringify({ old_manual: oldManual, new_manual: newManual, policy })
    });
  },

  async reconcilePortfolio(oldManual, newManual, census) {
    return this._request('/rate-change/reconcile-portfolio', {
      method: 'POST',
      body: JSON.stringify({ old_manual: oldManual, new_manual: newManual, census })
    });
  },

  async generateRateChangeReport(oldManual, newManual, census, outputFormat = 'markdown', recordInLedger = true) {
    return this._request('/rate-change/generate-report', {
      method: 'POST',
      body: JSON.stringify({
        old_manual: oldManual,
        new_manual: newManual,
        census,
        output_format: outputFormat,
        record_in_ledger: recordInLedger
      })
    });
  },

  async getAuditLedgerStatus() {
    return this._request('/rate-change/audit-ledger/status');
  },

  async verifyCensusDual(manual, census) {
    return this._request('/verification/verify-census', {
      method: 'POST',
      body: JSON.stringify({ manual, census })
    });
  }
};
