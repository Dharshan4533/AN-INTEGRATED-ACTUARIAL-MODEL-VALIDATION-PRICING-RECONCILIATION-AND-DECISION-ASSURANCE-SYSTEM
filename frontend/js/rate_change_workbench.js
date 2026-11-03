/**
 * Rate Change Assurance Workbench Manager.
 * Orchestrates rating manual comparison, portfolio census reconciliation,
 * stepwise factor attribution, dislocation profiling, and audit ledger governance.
 */

const rateChangeWorkbench = {
  state: {
    oldManual: null,
    newManual: null,
    census: [],
    reconciliationReport: null,
    comparisonReport: null,
    verificationSummary: null,
    auditLedgerStatus: null,
    selectedPolicyId: null,
    selectedPolicyAttribution: null,
    isInitialized: false,
    dislocationChart: null,
  },
  _initPromise: null,

  async init() {
    if (this.state.isInitialized) return;
    if (this._initPromise) return this._initPromise;
    console.log("Initializing Rate Change Assurance Workbench...");
    this._initPromise = this.loadSampleData().then(() => {
      this.state.isInitialized = true;
    }).finally(() => {
      this._initPromise = null;
    });
    return this._initPromise;
  },

  async loadSampleData() {
    try {
      this.showGlobalLoading(true);
      // 1. Load sample rating manuals
      const sampleManuals = await apiClient.getRatingManualSamples();
      this.state.oldManual = sampleManuals.old_manual;
      this.state.newManual = sampleManuals.new_manual;

      // 2. Load sample policy census
      this.state.census = await apiClient.getSampleCensus();

      // 3. Run initial portfolio reconciliation
      await this.runReconciliation();

      // 4. Compare rating manuals
      await this.compareManuals();

      // 5. Dual independent verification
      await this.runDualVerification();

      // 6. Fetch audit ledger status
      await this.loadAuditLedgerStatus();

      this.showGlobalLoading(false);
    } catch (err) {
      console.error("Error loading sample data:", err);
      this.showGlobalLoading(false);
      alert("Failed to initialize Rate Change Workbench: " + err.message);
    }
  },

  async runReconciliation() {
    if (!this.state.oldManual || !this.state.newManual || !this.state.census.length) return;

    try {
      const report = await apiClient.reconcilePortfolio(
        this.state.oldManual,
        this.state.newManual,
        this.state.census
      );
      this.state.reconciliationReport = report;
      this.renderOverviewKPIs();
      this.renderCensusTable();
      this.renderDislocationView();
      this.renderSegmentTable();

      // Select first policy by default
      if (report.policy_results && report.policy_results.length > 0) {
        this.selectPolicy(report.policy_results[0].policy_id);
      }
    } catch (err) {
      console.error("Portfolio reconciliation failed:", err);
    }
  },

  async compareManuals() {
    if (!this.state.oldManual || !this.state.newManual) return;
    try {
      const diff = await apiClient.compareRatingManuals(this.state.oldManual, this.state.newManual);
      this.state.comparisonReport = diff;
      this.renderManualDiffs();
    } catch (err) {
      console.error("Manual comparison failed:", err);
    }
  },

  async runDualVerification() {
    if (!this.state.newManual || !this.state.census.length) return;
    try {
      const verif = await apiClient.verifyCensusDual(this.state.newManual, this.state.census);
      this.state.verificationSummary = verif;
      this.renderVerificationBadges();
    } catch (err) {
      console.error("Dual verification failed:", err);
    }
  },

  async loadAuditLedgerStatus() {
    try {
      const status = await apiClient.getAuditLedgerStatus();
      this.state.auditLedgerStatus = status;
      this.renderAuditLedgerView();
    } catch (err) {
      console.error("Audit ledger fetch failed:", err);
    }
  },

  renderOverviewKPIs() {
    const r = this.state.reconciliationReport;
    if (!r) return;

    const curr = r.currency || "USD";
    const currSym = curr === "USD" ? "$" : (curr === "EUR" ? "€" : (curr === "INR" ? "₹" : curr));

    const setElem = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.innerText = val;
    };

    setElem("rc-kpi-new-prem", `${currSym} ${r.total_new_premium.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`);
    setElem("rc-kpi-old-prem", `${currSym} ${r.total_old_premium.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`);
    
    const deltaSign = r.aggregate_dollar_change >= 0 ? "+" : "";
    setElem("rc-kpi-dollar-delta", `${deltaSign}${currSym} ${r.aggregate_dollar_change.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`);
    setElem("rc-kpi-pct-delta", `${deltaSign}${r.aggregate_percentage_change.toFixed(2)}%`);
    setElem("rc-kpi-policies", `${r.total_valid_policies} In-Force`);
    setElem("rc-kpi-displaced", `${r.total_ineligible_policies} Displaced`);

    // Zero residual guarantee badge
    const resElem = document.getElementById("rc-kpi-residual-badge");
    if (resElem) {
      if (r.is_aggregate_reconciled && Math.abs(r.aggregate_reconciliation_residual) < 1e-6) {
        resElem.innerHTML = `<span class="badge-success" style="font-family: var(--font-mono); font-size: 0.85rem; padding: 0.35rem 0.75rem; border-radius: 9999px; background: #10b981; color: white;">
          ✓ ZERO RESIDUAL GUARANTEED ($0.000000)
        </span>`;
      } else {
        resElem.innerHTML = `<span class="badge-danger" style="background: #ef4444; color: white; padding: 0.35rem 0.75rem; border-radius: 9999px;">
          ⚠ RECONCILIATION LEAKAGE (${r.aggregate_reconciliation_residual})
        </span>`;
      }
    }
  },

  renderManualDiffs() {
    const c = this.state.comparisonReport;
    const oldM = this.state.oldManual;
    const newM = this.state.newManual;
    if (!c || !oldM || !newM) return;

    const setElem = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.innerText = val;
    };

    setElem("rc-manual-old-id", `${oldM.manual_id} (v${oldM.version})`);
    setElem("rc-manual-old-eff", `${oldM.effective_date_start} to ${oldM.effective_date_end || 'Open'}`);
    setElem("rc-manual-old-filing", oldM.filing_reference || "N/A");
    const oldHash = c.old_hash || c.old_canonical_sha256 || "";
    setElem("rc-manual-old-hash", oldHash ? `${oldHash.substring(0, 16)}...` : "--");

    setElem("rc-manual-new-id", `${newM.manual_id} (v${newM.version})`);
    setElem("rc-manual-new-eff", `${newM.effective_date_start} to ${newM.effective_date_end || 'Open'}`);
    setElem("rc-manual-new-filing", newM.filing_reference || "SERFF-PENDING");
    const newHash = c.new_hash || c.new_canonical_sha256 || "";
    setElem("rc-manual-new-hash", newHash ? `${newHash.substring(0, 16)}...` : "--");

    const tbody = document.getElementById("rc-manual-diff-tbody");
    if (!tbody) return;

    let html = "";
    // Base rate shift
    const baseOld = c.base_rate_old !== undefined ? c.base_rate_old : (c.old_base_rate !== undefined ? c.old_base_rate : 0);
    const baseNew = c.base_rate_new !== undefined ? c.base_rate_new : (c.new_base_rate !== undefined ? c.new_base_rate : 0);
    const baseDollar = c.base_rate_change_dollar !== undefined ? c.base_rate_change_dollar : (baseNew - baseOld);
    const baseSign = baseDollar >= 0 ? "+" : "";
    html += `
      <tr>
        <td><strong>BASE RATE</strong></td>
        <td><code>base_rate</code></td>
        <td>$${baseOld.toFixed(2)}</td>
        <td>$${baseNew.toFixed(2)}</td>
        <td><span class="${baseDollar >= 0 ? 'text-danger' : 'text-success'}"><strong>${baseSign}$${baseDollar.toFixed(2)}</strong></span></td>
        <td>Baseline premium anchor adjustment</td>
      </tr>
    `;

    // Factor rule changes
    if (c.rule_changes && c.rule_changes.length > 0) {
      c.rule_changes.forEach(rc => {
        const cat = (rc.component_type || rc.rule_category || "RULE").replace(/_/g, ' ').toUpperCase();
        const key = rc.component_name || rc.rule_key || "--";
        
        let oldValStr = rc.old_value !== null && rc.old_value !== undefined ? (typeof rc.old_value === 'object' ? JSON.stringify(rc.old_value) : String(rc.old_value)) : '<em class="text-muted">None</em>';
        let newValStr = rc.new_value !== null && rc.new_value !== undefined ? (typeof rc.new_value === 'object' ? JSON.stringify(rc.new_value) : String(rc.new_value)) : '<em class="text-muted">None</em>';
        
        let shiftDisplay = "--";
        if (typeof rc.old_value === 'number' && typeof rc.new_value === 'number' && rc.old_value !== 0) {
          const shift = ((rc.new_value - rc.old_value) / rc.old_value) * 100;
          const shiftSign = shift >= 0 ? "+" : "";
          const shiftClass = shift > 0 ? "text-danger" : (shift < 0 ? "text-success" : "");
          shiftDisplay = `<span class="${shiftClass}"><strong>${shiftSign}${shift.toFixed(1)}%</strong></span>`;
        } else if (rc.relative_shift !== undefined && rc.relative_shift !== null) {
          const shift = rc.relative_shift * 100;
          const shiftSign = shift >= 0 ? "+" : "";
          const shiftClass = shift > 0 ? "text-danger" : (shift < 0 ? "text-success" : "");
          shiftDisplay = `<span class="${shiftClass}"><strong>${shiftSign}${shift.toFixed(1)}%</strong></span>`;
        }

        const nature = rc.description || rc.change_type || "MODIFIED";

        html += `
          <tr>
            <td><strong>${cat}</strong></td>
            <td><code>${key}</code></td>
            <td>${oldValStr}</td>
            <td>${newValStr}</td>
            <td>${shiftDisplay}</td>
            <td>${nature}</td>
          </tr>
        `;
      });
    }

    tbody.innerHTML = html;
  },

  renderVerificationBadges() {
    const v = this.state.verificationSummary;
    if (!v) return;

    const badgeElem = document.getElementById("rc-verification-badge");
    if (badgeElem) {
      if (v.is_100_percent_verified) {
        badgeElem.innerHTML = `
          <div style="background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 8px; padding: 0.75rem 1rem; display: flex; align-items: center; justify-content: space-between;">
            <div>
              <strong style="color: #065f46;">✓ DUAL VERIFICATION: CHECKS PASSED (100% Agreement)</strong>
              <div style="font-size: 0.8rem; color: #047857; margin-top: 2px;">
                Exact Cent Match: ${v.total_passed}/${v.total_policies_checked} policies (ΔP = $0.00). Max intermediate diff: ${v.max_intermediate_discrepancy.toExponential(2)} (Standard ≤ 1e-4).
              </div>
            </div>
            <span style="font-size: 1.25rem;">🛡️</span>
          </div>
        `;
      } else {
        badgeElem.innerHTML = `
          <div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 0.75rem 1rem; color: #991b1b;">
            <strong>⚠ VERIFICATION FAILED: ${v.total_failed} policy discrepancies detected.</strong>
          </div>
        `;
      }
    }
  },

  renderCensusTable() {
    const r = this.state.reconciliationReport;
    if (!r || !r.policy_results) return;

    const tbody = document.getElementById("rc-census-tbody");
    if (!tbody) return;

    let html = "";
    r.policy_results.forEach((p, idx) => {
      const isSelected = p.policy_id === this.state.selectedPolicyId ? "class='table-row-selected'" : "";
      const deltaSign = p.absolute_change >= 0 ? "+" : "";
      const pctDisplay = p.percentage_change !== null ? `${deltaSign}${p.percentage_change.toFixed(2)}%` : '<em class="text-muted">Undefined (Zero Baseline)</em>';
      const pctClass = (p.percentage_change || 0) > 0 ? "text-danger" : ((p.percentage_change || 0) < 0 ? "text-success" : "");

      html += `
        <tr ${isSelected} style="cursor: pointer;" onclick="rateChangeWorkbench.selectPolicy('${p.policy_id}')">
          <td><strong>${p.policy_id}</strong></td>
          <td><span class="badge ${p.eligibility_status === 'ELIGIBLE' ? 'badge-low' : 'badge-high'}">${p.eligibility_status}</span></td>
          <td>$${p.old_premium.toFixed(2)}</td>
          <td>$${p.new_premium.toFixed(2)}</td>
          <td><strong>${deltaSign}$${p.absolute_change.toFixed(2)}</strong></td>
          <td><span class="${pctClass}"><strong>${pctDisplay}</strong></span></td>
          <td><span class="badge ${p.is_exact_reconciliation ? 'badge-low' : 'badge-high'}">${p.is_exact_reconciliation ? '✓ $0.00' : 'Mismatch'}</span></td>
        </tr>
      `;
    });

    tbody.innerHTML = html;
  },

  async selectPolicy(policyId) {
    this.state.selectedPolicyId = policyId;
    this.renderCensusTable(); // update selection highlight

    const r = this.state.reconciliationReport;
    const policyResult = r ? r.policy_results.find(p => p.policy_id === policyId) : null;
    if (!policyResult) return;

    this.state.selectedPolicyAttribution = policyResult;

    // Update detail header
    const setElem = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.innerText = val;
    };

    setElem("rc-selected-policy-id", policyResult.policy_id);
    setElem("rc-selected-old-prem", `$${policyResult.old_premium.toFixed(2)}`);
    setElem("rc-selected-new-prem", `$${policyResult.new_premium.toFixed(2)}`);
    const sign = policyResult.absolute_change >= 0 ? "+" : "";
    setElem("rc-selected-delta", `${sign}$${policyResult.absolute_change.toFixed(2)}`);
    setElem("rc-selected-pct", policyResult.percentage_change !== null ? `${sign}${policyResult.percentage_change.toFixed(2)}%` : "Undefined");

    // Render Stepwise Factor Attribution Waterfall Table
    const tbody = document.getElementById("rc-attribution-tbody");
    if (!tbody) return;

    let html = "";
    if (policyResult.steps && policyResult.steps.length > 0) {
      policyResult.steps.forEach(step => {
        const stepSign = step.dollar_impact >= 0 ? "+" : "";
        const stepClass = step.dollar_impact > 0 ? "text-danger" : (step.dollar_impact < 0 ? "text-success" : "");
        html += `
          <tr>
            <td><strong>#${step.step_number}</strong></td>
            <td><code>${step.component_name}</code></td>
            <td><span class="badge ${step.component_type === 'UNALLOCATED_INTERACTION' ? 'badge-mod' : 'badge-low'}">${step.component_type}</span></td>
            <td>$${step.starting_premium.toFixed(2)}</td>
            <td>$${step.ending_premium.toFixed(2)}</td>
            <td><span class="${stepClass}"><strong>${stepSign}$${step.dollar_impact.toFixed(2)}</strong></span></td>
            <td>${step.description}</td>
          </tr>
        `;
      });
    }

    tbody.innerHTML = html;

    // Show unallocated interaction disclosure
    const disclElem = document.getElementById("rc-interaction-disclosure");
    if (disclElem) {
      disclElem.innerHTML = `
        <div style="font-size: 0.825rem; color: #475569; background: #f8fafc; border-left: 3px solid #6366f1; padding: 0.6rem 0.85rem; border-radius: 4px; margin-top: 1rem;">
          <strong>Factor Attribution Path-Dependency Disclosure:</strong>
          Sequential order: <code>Base Rate → Factors → Fees → Limits → Rounding</code>.<br/>
          Unallocated interaction adjustment: <strong>$${policyResult.unallocated_interaction_adjustment.toFixed(4)}</strong> (Captures non-linear cross-product interaction terms).
        </div>
      `;
    }
  },

  renderDislocationView() {
    const r = this.state.reconciliationReport;
    if (!r) return;

    const setElem = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.innerText = val;
    };

    const p = r.pct_change_percentiles || {};
    setElem("rc-pct-min", r.min_pct_change !== null ? `${r.min_pct_change.toFixed(2)}%` : "--");
    setElem("rc-pct-p10", p.p10 !== undefined ? `${p.p10.toFixed(2)}%` : "--");
    setElem("rc-pct-p25", p.p25 !== undefined ? `${p.p25.toFixed(2)}%` : "--");
    setElem("rc-pct-p50", p.p50 !== undefined ? `${p.p50.toFixed(2)}%` : "--");
    setElem("rc-pct-p75", p.p75 !== undefined ? `${p.p75.toFixed(2)}%` : "--");
    setElem("rc-pct-p90", p.p90 !== undefined ? `${p.p90.toFixed(2)}%` : "--");
    setElem("rc-pct-max", r.max_pct_change !== null ? `${r.max_pct_change.toFixed(2)}%` : "--");

    // Directional counts
    setElem("rc-dir-inc", `${r.count_rate_increase} (${r.pct_rate_increase.toFixed(1)}%)`);
    setElem("rc-dir-dec", `${r.count_rate_decrease} (${r.pct_rate_decrease.toFixed(1)}%)`);
    setElem("rc-dir-unch", `${r.count_rate_unchanged} (${r.pct_rate_unchanged.toFixed(1)}%)`);

    // Chart.js dislocation bar chart
    this.renderDislocationChart(r);
  },

  renderDislocationChart(report) {
    const canvas = document.getElementById("rc-dislocation-chart");
    if (!canvas || typeof Chart === 'undefined') return;

    if (this.state.dislocationChart) {
      this.state.dislocationChart.destroy();
    }

    const ctx = canvas.getContext("2d");
    this.state.dislocationChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: ["Rate Increase (> 0%)", "Unchanged (0%)", "Rate Decrease (< 0%)"],
        datasets: [{
          label: "Number of Policyholders",
          data: [report.count_rate_increase, report.count_rate_unchanged, report.count_rate_decrease],
          backgroundColor: ["#ef4444", "#94a3b8", "#10b981"],
          borderRadius: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false }
        },
        scales: {
          y: { beginAtZero: true, grid: { color: "#f1f5f9" } },
          x: { grid: { display: false } }
        }
      }
    });
  },

  renderSegmentTable() {
    const r = this.state.reconciliationReport;
    if (!r || !r.segment_impacts) return;

    const tbody = document.getElementById("rc-segment-tbody");
    if (!tbody) return;

    let html = "";
    r.segment_impacts.forEach(s => {
      const deltaSign = s.dollar_change >= 0 ? "+" : "";
      const pctSign = s.percentage_change >= 0 ? "+" : "";
      const pctClass = s.percentage_change > 0 ? "text-danger" : (s.percentage_change < 0 ? "text-success" : "");

      html += `
        <tr>
          <td><code>${s.segment_variable}</code></td>
          <td><strong>${s.segment_value}</strong></td>
          <td>${s.policy_count.toLocaleString()}</td>
          <td>$${s.total_old_premium.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
          <td>$${s.total_new_premium.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
          <td><strong>${deltaSign}$${s.dollar_change.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</strong></td>
          <td><span class="${pctClass}"><strong>${pctSign}${s.percentage_change.toFixed(2)}%</strong></span></td>
        </tr>
      `;
    });

    tbody.innerHTML = html;
  },

  renderAuditLedgerView() {
    const s = this.state.auditLedgerStatus;
    if (!s) return;

    const setElem = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.innerText = val;
    };

    setElem("rc-ledger-records", s.total_records.toString());
    setElem("rc-ledger-genesis", s.genesis_hash ? `${s.genesis_hash.substring(0, 16)}...` : "--");
    setElem("rc-ledger-tip", s.tip_hash ? `${s.tip_hash.substring(0, 16)}...` : "Empty (Genesis)");

    const statusElem = document.getElementById("rc-ledger-status-badge");
    if (statusElem) {
      if (s.is_valid && !s.tamper_detected) {
        statusElem.innerHTML = `
          <span style="background: #10b981; color: white; padding: 0.35rem 0.75rem; border-radius: 9999px; font-weight: 600; font-size: 0.85rem;">
            ✓ UNBROKEN CRYPTOGRAPHIC HASH CHAIN
          </span>
        `;
      } else {
        statusElem.innerHTML = `
          <span style="background: #ef4444; color: white; padding: 0.35rem 0.75rem; border-radius: 9999px; font-weight: 600; font-size: 0.85rem;">
            ⚠ CHAIN TAMPER DETECTED: ${s.tamper_type || 'CORRUPTED'}
          </span>
        `;
      }
    }
  },

  async downloadReport(format = "markdown") {
    try {
      if (!this.state.oldManual || !this.state.newManual || !this.state.census.length) {
        await this.loadSampleData();
      }
      this.showGlobalLoading(true);
      const res = await apiClient.generateRateChangeReport(
        this.state.oldManual,
        this.state.newManual,
        this.state.census,
        format,
        true
      );
      this.showGlobalLoading(false);

      // Refresh audit ledger view
      await this.loadAuditLedgerStatus();

      // Open Modal or Download File
      if (format === "markdown" || format === "md") {
        this.showReportModal("Rate Change Assurance Report (Markdown)", res.report, "text/markdown", "rate_change_assurance_report.md");
      } else if (format === "html") {
        // Open HTML in new tab or download
        const blob = new Blob([res.report], { type: "text/html" });
        const url = URL.createObjectURL(blob);
        const win = window.open(url, "_blank");
        if (!win) {
          const a = document.createElement("a");
          a.href = url;
          a.download = "rate_change_assurance_report.html";
          a.click();
        }
      }
    } catch (err) {
      this.showGlobalLoading(false);
      alert("Failed to generate report: " + err.message);
    }
  },

  showReportModal(title, content, mimeType, filename) {
    let modal = document.getElementById("rc-report-modal");
    if (!modal) {
      modal = document.createElement("div");
      modal.id = "rc-report-modal";
      modal.className = "modal-backdrop";
      document.body.appendChild(modal);
    }

    modal.innerHTML = `
      <div class="modal-card" style="max-width: 900px; max-height: 85vh; display: flex; flex-direction: column;">
        <div class="modal-header" style="display: flex; justify-content: space-between; align-items: center; padding: 1.25rem 1.5rem; border-bottom: 1px solid var(--border-color);">
          <h3 style="margin: 0; font-size: 1.15rem; font-weight: 700;">${title}</h3>
          <button class="btn btn-secondary" onclick="document.getElementById('rc-report-modal').style.display='none'">✕</button>
        </div>
        <div class="modal-body" style="flex: 1; overflow-y: auto; padding: 1.5rem; background: #f8fafc;">
          <pre style="white-space: pre-wrap; font-family: var(--font-mono); font-size: 0.85rem; line-height: 1.5; color: #1e293b; background: white; padding: 1.25rem; border: 1px solid var(--border-color); border-radius: 6px;">${content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</pre>
        </div>
        <div class="modal-footer" style="padding: 1rem 1.5rem; border-top: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center;">
          <span style="font-size: 0.8rem; color: var(--text-muted);">Generated via RFC 8785 Canonical Spec</span>
          <div>
            <button class="btn btn-secondary" onclick="navigator.clipboard.writeText(document.querySelector('#rc-report-modal pre').innerText); alert('Report copied to clipboard!');">Copy to Clipboard</button>
            <button class="btn btn-primary" onclick="rateChangeWorkbench.triggerDownload('${mimeType}', '${filename}')">Download File</button>
          </div>
        </div>
      </div>
    `;
    modal.style.display = "flex";
  },

  triggerDownload(mimeType, filename) {
    const content = document.querySelector("#rc-report-modal pre").innerText;
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  },

  showGlobalLoading(show) {
    let loader = document.getElementById("rc-global-loader");
    if (!loader) {
      loader = document.createElement("div");
      loader.id = "rc-global-loader";
      loader.style.cssText = "position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(15, 23, 42, 0.4); z-index: 9999; display: flex; align-items: center; justify-content: center; backdrop-filter: blur(2px);";
      loader.innerHTML = `
        <div style="background: white; border-radius: 12px; padding: 1.5rem 2.5rem; box-shadow: 0 10px 25px rgba(0,0,0,0.15); display: flex; flex-direction: column; align-items: center; gap: 0.75rem;">
          <div class="spinner" style="width: 36px; height: 36px; border: 3px solid #e2e8f0; border-top-color: #4f46e5; border-radius: 50%; animation: spin 0.8s linear infinite;"></div>
          <span style="font-weight: 600; color: #1e293b; font-size: 0.9rem;">Evaluating Rate Change Specification...</span>
        </div>
      `;
      document.body.appendChild(loader);
    }
    loader.style.display = show ? "flex" : "none";
  }
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    rateChangeWorkbench.init();
  });
} else {
  rateChangeWorkbench.init();
}
