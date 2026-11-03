/**
 * Pricing, Comparison, and What-If UI Handlers.
 */

const pricingModule = {
  currentQuote: null,

  getPolicyFromForm(formId) {
    const form = document.getElementById(formId);
    if (!form) return null;

    const convertInr = appState.currency === 'INR';
    return {
      VehPower: parseInt(form.elements['VehPower'].value, 10),
      VehAge: parseInt(form.elements['VehAge'].value, 10),
      DrivAge: parseInt(form.elements['DrivAge'].value, 10),
      BonusMalus: parseInt(form.elements['BonusMalus'].value, 10),
      VehBrand: form.elements['VehBrand'].value,
      VehGas: form.elements['VehGas'].value,
      Area: form.elements['Area'].value,
      Density: parseFloat(form.elements['Density'].value),
      Region: form.elements['Region'].value,
      Exposure: parseFloat(form.elements['Exposure'].value),
      convert_to_inr: convertInr
    };
  },

  setPolicyToForm(formId, policy) {
    const form = document.getElementById(formId);
    if (!form || !policy) return;

    for (const [key, value] of Object.entries(policy)) {
      if (form.elements[key]) {
        form.elements[key].value = value;
        // Trigger any badge update
        const badge = document.getElementById(`${formId}-${key}-val`);
        if (badge) badge.innerText = value;
      }
    }
  },

  async calculateSingleQuote() {
    const policy = this.getPolicyFromForm('pricing-form');
    if (!policy) return;

    const loadingElem = document.getElementById('pricing-loading');
    const resultElem = document.getElementById('pricing-result');
    if (loadingElem) loadingElem.style.display = 'flex';
    if (resultElem) resultElem.style.display = 'none';

    try {
      const quote = await apiClient.getQuote(policy);
      this.currentQuote = quote;
      this.renderQuoteResult(quote);
    } catch (err) {
      alert(`Quote calculation failed: ${err.message}`);
    } finally {
      if (loadingElem) loadingElem.style.display = 'none';
      if (resultElem) resultElem.style.display = 'block';
    }
  },

  renderQuoteResult(quote) {
    const cur = quote.currency_symbol || '€';
    
    // Header Hero values
    document.getElementById('res-total-premium').innerText = `${quote.total_commercial_premium.toLocaleString()} ${cur}`;
    document.getElementById('res-pure-premium-sub').innerText = `${quote.annual_pure_premium.toLocaleString()} ${cur}`;
    document.getElementById('res-expected-loss-sub').innerText = `${quote.term_expected_loss.toLocaleString()} ${cur}`;
    
    // Risk Tier Badge
    const tierBadge = document.getElementById('res-risk-tier-badge');
    if (tierBadge) {
      tierBadge.className = `badge badge-${quote.risk_tier.badge_color}`;
      tierBadge.innerText = `${quote.risk_tier.tier_name} Risk (Score: ${quote.risk_tier.risk_score}/100)`;
    }
    const tierDesc = document.getElementById('res-risk-tier-desc');
    if (tierDesc) tierDesc.innerText = quote.risk_tier.description;

    // KPI Tiles
    document.getElementById('res-kpi-freq').innerText = (quote.annualized_frequency * 100).toFixed(2) + '%';
    document.getElementById('res-kpi-sev').innerText = `${Math.round(quote.expected_severity).toLocaleString()} ${cur}`;
    document.getElementById('res-kpi-claims-term').innerText = quote.expected_claim_count_term.toFixed(3);
    document.getElementById('res-kpi-exposure').innerText = `${quote.policy.Exposure} Year(s)`;

    // Waterfall Breakdown Table
    const bd = quote.pricing_breakdown;
    document.getElementById('res-bd-pure').innerText = `${bd.annual_pure_premium.toLocaleString()} ${cur}`;
    document.getElementById('res-bd-loss').innerText = `${bd.term_expected_loss.toLocaleString()} ${cur}`;
    document.getElementById('res-bd-fixed').innerText = `${bd.fixed_expense.toLocaleString()} ${cur}`;
    document.getElementById('res-bd-var').innerText = `${bd.variable_expense.toLocaleString()} ${cur}`;
    document.getElementById('res-bd-risk').innerText = `${bd.risk_margin.toLocaleString()} ${cur}`;
    document.getElementById('res-bd-profit').innerText = `${bd.profit_margin.toLocaleString()} ${cur}`;
    document.getElementById('res-bd-pre-tax').innerText = `${bd.commercial_premium_before_tax.toLocaleString()} ${cur}`;
    document.getElementById('res-bd-tax').innerText = `${bd.statutory_tax.toLocaleString()} ${cur}`;
    document.getElementById('res-bd-total').innerText = `${bd.total_commercial_premium.toLocaleString()} ${cur}`;

    // Risk Drivers
    const driversList = document.getElementById('res-drivers-list');
    if (driversList && quote.key_risk_drivers) {
      driversList.innerHTML = quote.key_risk_drivers.map(d => `
        <div class="waterfall-item">
          <span><strong>${d.factor}</strong> (${d.input_value})</span>
          <span class="diff-pill ${d.impact_direction === 'Increases Risk' ? 'positive-bad' : 'negative-good'}">
            ${d.impact_direction}
          </span>
        </div>
      `).join('');
    }
  },

  // Comparison module
  comparisonProfiles: [],

  initComparison() {
    this.comparisonProfiles = [
      {
        VehPower: 4, VehAge: 10, DrivAge: 52, BonusMalus: 50,
        VehBrand: 'B1', VehGas: 'Regular', Area: 'A', Density: 80.0, Region: 'R24', Exposure: 1.0
      },
      {
        VehPower: 11, VehAge: 2, DrivAge: 22, BonusMalus: 115,
        VehBrand: 'B12', VehGas: 'Diesel', Area: 'E', Density: 4500.0, Region: 'R11', Exposure: 1.0
      }
    ];
    this.renderComparisonProfiles();
  },

  renderComparisonProfiles() {
    const container = document.getElementById('comparison-cards-container');
    if (!container) return;

    container.innerHTML = this.comparisonProfiles.map((p, idx) => `
      <div class="card col-6">
        <div class="card-header">
          <span class="card-title">Profile ${idx + 1}</span>
          ${this.comparisonProfiles.length > 2 ? `<button class="btn btn-outline btn-sm" onclick="pricingModule.removeComparisonProfile(${idx})">Remove</button>` : ''}
        </div>
        <div class="card-body">
          <form id="compare-form-${idx}" class="form-grid">
            <div class="form-group">
              <label class="form-label">Driver Age</label>
              <input type="number" class="form-control" name="DrivAge" value="${p.DrivAge}" min="18" max="100" onchange="pricingModule.updateComparisonProfileFromForm(${idx})">
            </div>
            <div class="form-group">
              <label class="form-label">Bonus-Malus</label>
              <input type="number" class="form-control" name="BonusMalus" value="${p.BonusMalus}" min="50" max="230" onchange="pricingModule.updateComparisonProfileFromForm(${idx})">
            </div>
            <div class="form-group">
              <label class="form-label">Veh Power</label>
              <input type="number" class="form-control" name="VehPower" value="${p.VehPower}" min="4" max="15" onchange="pricingModule.updateComparisonProfileFromForm(${idx})">
            </div>
            <div class="form-group">
              <label class="form-label">Veh Age</label>
              <input type="number" class="form-control" name="VehAge" value="${p.VehAge}" min="0" max="100" onchange="pricingModule.updateComparisonProfileFromForm(${idx})">
            </div>
            <div class="form-group">
              <label class="form-label">Area</label>
              <select class="form-control" name="Area" onchange="pricingModule.updateComparisonProfileFromForm(${idx})">
                ${['A', 'B', 'C', 'D', 'E', 'F'].map(a => `<option value="${a}" ${p.Area === a ? 'selected' : ''}>Area ${a}</option>`).join('')}
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Fuel</label>
              <select class="form-control" name="VehGas" onchange="pricingModule.updateComparisonProfileFromForm(${idx})">
                <option value="Regular" ${p.VehGas === 'Regular' ? 'selected' : ''}>Regular</option>
                <option value="Diesel" ${p.VehGas === 'Diesel' ? 'selected' : ''}>Diesel</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Density</label>
              <input type="number" class="form-control" name="Density" value="${p.Density}" min="1" max="30000" onchange="pricingModule.updateComparisonProfileFromForm(${idx})">
            </div>
            <div class="form-group">
              <label class="form-label">Exposure</label>
              <input type="number" step="0.1" class="form-control" name="Exposure" value="${p.Exposure}" min="0.1" max="2.0" onchange="pricingModule.updateComparisonProfileFromForm(${idx})">
            </div>
            <input type="hidden" name="VehBrand" value="${p.VehBrand}">
            <input type="hidden" name="Region" value="${p.Region}">
          </form>
        </div>
      </div>
    `).join('');
  },

  addComparisonProfile() {
    if (this.comparisonProfiles.length >= 5) {
      alert("Maximum 5 profiles can be compared simultaneously.");
      return;
    }
    this.comparisonProfiles.push({
      VehPower: 6, VehAge: 5, DrivAge: 40, BonusMalus: 50,
      VehBrand: 'B1', VehGas: 'Regular', Area: 'C', Density: 500.0, Region: 'R24', Exposure: 1.0
    });
    this.renderComparisonProfiles();
  },

  removeComparisonProfile(index) {
    if (this.comparisonProfiles.length <= 2) return;
    this.comparisonProfiles.splice(index, 1);
    this.renderComparisonProfiles();
  },

  updateComparisonProfileFromForm(idx) {
    const form = document.getElementById(`compare-form-${idx}`);
    if (!form) return;
    this.comparisonProfiles[idx] = {
      VehPower: parseInt(form.elements['VehPower'].value, 10),
      VehAge: parseInt(form.elements['VehAge'].value, 10),
      DrivAge: parseInt(form.elements['DrivAge'].value, 10),
      BonusMalus: parseInt(form.elements['BonusMalus'].value, 10),
      VehBrand: form.elements['VehBrand'].value,
      VehGas: form.elements['VehGas'].value,
      Area: form.elements['Area'].value,
      Density: parseFloat(form.elements['Density'].value),
      Region: form.elements['Region'].value,
      Exposure: parseFloat(form.elements['Exposure'].value),
      convert_to_inr: appState.currency === 'INR'
    };
  },

  async runComparison() {
    for (let i = 0; i < this.comparisonProfiles.length; i++) {
      this.updateComparisonProfileFromForm(i);
    }

    const policies = this.comparisonProfiles.map(p => ({
      ...p,
      convert_to_inr: appState.currency === 'INR'
    }));

    try {
      const res = await apiClient.compareQuotes(policies);
      this.renderComparisonResults(res);
    } catch (err) {
      alert(`Comparison failed: ${err.message}`);
    }
  },

  renderComparisonResults(response) {
    const tableBody = document.getElementById('comparison-results-tbody');
    const container = document.getElementById('comparison-results-card');
    if (!tableBody || !container) return;

    const cur = appState.currency === 'INR' ? '₹' : '€';

    tableBody.innerHTML = response.comparison_table.map((row, idx) => {
      const isLowest = idx === response.lowest_premium_index;
      const isHighest = idx === response.highest_premium_index;
      return `
        <tr style="${isLowest ? 'background-color: #f0fdf4;' : isHighest ? 'background-color: #fef2f2;' : ''}">
          <td><strong>${row.profile_id}</strong> ${isLowest ? '<span class="badge badge-low">Lowest Cost</span>' : isHighest ? '<span class="badge badge-very-high">Highest Risk</span>' : ''}</td>
          <td>Age ${row.driver_age} | BM ${row.bonus_malus}</td>
          <td>Pwr ${row.veh_power} | ${row.area}</td>
          <td class="table-num">${(row.annualized_frequency * 100).toFixed(2)}%</td>
          <td class="table-num">${Math.round(row.expected_severity).toLocaleString()} ${cur}</td>
          <td class="table-num">${row.annual_pure_premium.toLocaleString()} ${cur}</td>
          <td class="table-num"><strong>${row.total_commercial_premium.toLocaleString()} ${cur}</strong></td>
          <td><span class="badge badge-${row.risk_tier.toLowerCase().replace(' ', '-')}">${row.risk_tier}</span></td>
        </tr>
      `;
    }).join('');

    container.style.display = 'block';
  },

  // What-If Analysis
  async runWhatIf() {
    const basePolicy = this.getPolicyFromForm('what-if-base-form');
    const revPolicy = this.getPolicyFromForm('what-if-rev-form');

    if (!basePolicy || !revPolicy) return;

    try {
      const res = await apiClient.whatIfAnalysis(basePolicy, revPolicy);
      this.renderWhatIfResults(res);
    } catch (err) {
      alert(`What-If analysis failed: ${err.message}`);
    }
  },

  renderWhatIfResults(res) {
    const diff = res.differences;
    const cur = res.baseline_quote.currency_symbol || '€';
    const container = document.getElementById('what-if-results');
    if (!container) return;

    // Delta badges
    const formatDiff = (absVal, pctVal, isGoodIfNegative = true) => {
      const sign = absVal >= 0 ? '+' : '';
      const isGood = isGoodIfNegative ? absVal <= 0 : absVal >= 0;
      const cssClass = isGood ? 'negative-good' : 'positive-bad';
      return `<span class="diff-pill ${cssClass}">${sign}${absVal.toLocaleString()} ${cur} (${sign}${pctVal}%)</span>`;
    };

    document.getElementById('wi-base-premium').innerText = `${res.baseline_quote.total_commercial_premium.toLocaleString()} ${cur}`;
    document.getElementById('wi-rev-premium').innerText = `${res.revised_quote.total_commercial_premium.toLocaleString()} ${cur}`;
    document.getElementById('wi-delta-premium').innerHTML = formatDiff(diff.commercial_premium_abs_diff, diff.commercial_premium_pct_diff);

    document.getElementById('wi-base-pure').innerText = `${res.baseline_quote.annual_pure_premium.toLocaleString()} ${cur}`;
    document.getElementById('wi-rev-pure').innerText = `${res.revised_quote.annual_pure_premium.toLocaleString()} ${cur}`;
    document.getElementById('wi-delta-pure').innerHTML = formatDiff(diff.pure_premium_abs_diff, diff.pure_premium_pct_diff);

    document.getElementById('wi-base-freq').innerText = (res.baseline_quote.annualized_frequency * 100).toFixed(2) + '%';
    document.getElementById('wi-rev-freq').innerText = (res.revised_quote.annualized_frequency * 100).toFixed(2) + '%';
    document.getElementById('wi-delta-freq').innerHTML = `<span class="diff-pill ${diff.frequency_abs_diff <= 0 ? 'negative-good' : 'positive-bad'}">${diff.frequency_abs_diff >= 0 ? '+' : ''}${(diff.frequency_abs_diff * 100).toFixed(3)}% (${diff.frequency_pct_diff}%)</span>`;

    charts.renderWhatIfComparison('what-if-chart-canvas', res.baseline_quote, res.revised_quote);
    container.style.display = 'block';
  }
};
