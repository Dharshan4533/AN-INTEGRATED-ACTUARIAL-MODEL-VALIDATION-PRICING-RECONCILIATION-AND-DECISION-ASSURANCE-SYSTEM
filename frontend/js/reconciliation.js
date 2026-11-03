/**
 * Reconciliation Engine Frontend Module.
 * Calls /api/v1/reconcile, renders the 5-step exact waterfall attribution,
 * displays path-order sensitivity analysis, and executes execution replay.
 */

let reconciliationWaterfallChart = null;

const reconciliation = {
  presets: {
    standard_vs_young: {
      policy_a: { Area: "C", VehPower: 6, VehAge: 6, DrivAge: 45, BonusMalus: 50, VehBrand: "B1", VehGas: "Regular", Density: 500, Region: "R24", Exposure: 1.0 },
      policy_b: { Area: "E", VehPower: 9, VehAge: 2, DrivAge: 22, BonusMalus: 100, VehBrand: "B12", VehGas: "Diesel", Density: 4500, Region: "R11", Exposure: 0.75 }
    },
    vehicle_upgrade: {
      policy_a: { Area: "B", VehPower: 5, VehAge: 10, DrivAge: 38, BonusMalus: 60, VehBrand: "B2", VehGas: "Regular", Density: 200, Region: "R24", Exposure: 1.0 },
      policy_b: { Area: "B", VehPower: 12, VehAge: 1, DrivAge: 38, BonusMalus: 60, VehBrand: "B14", VehGas: "Diesel", Density: 200, Region: "R24", Exposure: 1.0 }
    },
    geographic_relocation: {
      policy_a: { Area: "A", VehPower: 6, VehAge: 5, DrivAge: 50, BonusMalus: 50, VehBrand: "B1", VehGas: "Regular", Density: 50, Region: "R24", Exposure: 1.0 },
      policy_b: { Area: "F", VehPower: 6, VehAge: 5, DrivAge: 50, BonusMalus: 50, VehBrand: "B1", VehGas: "Regular", Density: 15000, Region: "R11", Exposure: 1.0 }
    }
  },

  init() {
    this.bindEvents();
    this.loadPreset("standard_vs_young");
  },

  bindEvents() {
    const btnExecute = document.getElementById("btn-execute-reconciliation");
    if (btnExecute) {
      btnExecute.addEventListener("click", () => this.executeReconciliation());
    }

    const presetSelect = document.getElementById("reconciliation-preset-select");
    if (presetSelect) {
      presetSelect.addEventListener("change", (e) => this.loadPreset(e.target.value));
    }

    const btnReplay = document.getElementById("btn-replay-run");
    if (btnReplay) {
      btnReplay.addEventListener("click", () => this.replayCurrentRun());
    }
  },

  loadPreset(presetKey) {
    const preset = this.presets[presetKey];
    if (!preset) return;

    this.populateForm("recon-a", preset.policy_a);
    this.populateForm("recon-b", preset.policy_b);
  },

  populateForm(prefix, policy) {
    for (const [key, val] of Object.entries(policy)) {
      const el = document.getElementById(`${prefix}-${key.toLowerCase()}`);
      if (el) {
        el.value = val;
      }
    }
  },

  readPolicy(prefix) {
    return {
      Area: document.getElementById(`${prefix}-area`).value,
      VehPower: parseInt(document.getElementById(`${prefix}-vehpower`).value, 10),
      VehAge: parseInt(document.getElementById(`${prefix}-vehage`).value, 10),
      DrivAge: parseInt(document.getElementById(`${prefix}-drivage`).value, 10),
      BonusMalus: parseInt(document.getElementById(`${prefix}-bonusmalus`).value, 10),
      VehBrand: document.getElementById(`${prefix}-vehbrand`).value,
      VehGas: document.getElementById(`${prefix}-vehgas`).value,
      Density: parseFloat(document.getElementById(`${prefix}-density`).value),
      Region: document.getElementById(`${prefix}-region`).value,
      Exposure: parseFloat(document.getElementById(`${prefix}-exposure`).value),
      convert_to_inr: appState.currency === 'INR'
    };
  },

  async executeReconciliation() {
    const policyA = this.readPolicy("recon-a");
    const policyB = this.readPolicy("recon-b");

    const payload = {
      policy_a: policyA,
      policy_b: policyB,
      model_family_a: document.getElementById("recon-model-a").value,
      model_family_b: document.getElementById("recon-model-b").value,
      user_notes: "Frontend reconciliation execution",
      convert_to_inr: appState.currency === 'INR'
    };

    const container = document.getElementById("reconciliation-results-box");
    container.style.opacity = "0.5";

    try {
      const res = await fetch("/api/v1/reconcile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error("Reconciliation request failed");
      const data = await res.json();
      this.renderResults(data);
    } catch (err) {
      alert("Error executing reconciliation: " + err.message);
    } finally {
      container.style.opacity = "1";
    }
  },

  renderResults(data) {
    document.getElementById("reconciliation-results-box").style.display = "block";
    const cur = data.currency_symbol || (data.currency === 'INR' || appState.currency === 'INR' ? '₹' : '€');

    // Summary pills
    document.getElementById("recon-prem-a").innerText = `${data.policy_a_total_premium.toFixed(2)} ${cur}`;
    document.getElementById("recon-prem-b").innerText = `${data.policy_b_total_premium.toFixed(2)} ${cur}`;
    
    const diffSign = data.total_difference >= 0 ? "+" : "";
    document.getElementById("recon-total-diff").innerText = `${diffSign}${data.total_difference.toFixed(2)} ${cur}`;

    // Exactness badge
    const badgeExact = document.getElementById("recon-exact-badge");
    if (data.is_exact_reconciliation) {
      badgeExact.className = "badge badge-low";
      badgeExact.innerText = `Exact (Error = ${data.reconciliation_error.toFixed(6)} ${cur} ≤ 10⁻⁴)`;
    } else {
      badgeExact.className = "badge badge-very-high";
      badgeExact.innerText = `Leakage Detected (Error = ${data.reconciliation_error.toFixed(4)} ${cur})`;
    }

    // Run ID
    document.getElementById("recon-run-id").innerText = data.run_id;
    document.getElementById("btn-replay-run").setAttribute("data-run-id", data.run_id);
    document.getElementById("replay-status-box").style.display = "none";

    // Table rows
    const tbody = document.getElementById("reconciliation-steps-tbody");
    tbody.innerHTML = "";
    data.sequential_steps.forEach(step => {
      const tr = document.createElement("tr");
      const impactClass = step.dollar_impact >= 0 ? "text-danger" : "text-success";
      const sign = step.dollar_impact >= 0 ? "+" : "";
      tr.innerHTML = `
        <td><strong>Step ${step.step_number}</strong>: ${step.step_name}</td>
        <td>${step.starting_premium.toFixed(2)} ${cur}</td>
        <td class="${impactClass}" style="font-weight: 600;">${sign}${step.dollar_impact.toFixed(2)} ${cur} (${sign}${step.percentage_impact.toFixed(1)}%)</td>
        <td><strong>${step.ending_premium.toFixed(2)} ${cur}</strong></td>
        <td style="color: #64748b; font-size: 0.8rem;">${step.description}</td>
      `;
      tbody.appendChild(tr);
    });

    // Render Waterfall Chart
    this.renderWaterfallChart(data);

    // Order Sensitivity
    const sens = data.order_sensitivity_analysis;
    document.getElementById("recon-sens-divergence").innerText = `${sens.max_step_divergence.toFixed(2)} ${cur}`;
    document.getElementById("recon-sens-comment").innerText = sens.interaction_comment;
  },

  renderWaterfallChart(data) {
    const ctx = document.getElementById("reconciliation-waterfall-chart");
    if (!ctx) return;

    if (reconciliationWaterfallChart) {
      reconciliationWaterfallChart.destroy();
    }

    const labels = ["Baseline (Policy A)", "1. Pure Risk", "2. Model Spec", "3. Exposure", "4. Loading", "5. Tax", "Target (Policy B)"];
    
    // Bar values for waterfall
    const p0 = data.policy_a_total_premium;
    const steps = data.sequential_steps;
    const d1 = steps[0].dollar_impact;
    const d2 = steps[1].dollar_impact;
    const d3 = steps[2].dollar_impact;
    const d4 = steps[3].dollar_impact;
    const d5 = steps[4].dollar_impact;
    const p5 = data.policy_b_total_premium;

    // Floating bars [bottom, top]
    const dataBars = [
      [0, p0],
      [p0, p0 + d1],
      [p0 + d1, p0 + d1 + d2],
      [p0 + d1 + d2, p0 + d1 + d2 + d3],
      [p0 + d1 + d2 + d3, p0 + d1 + d2 + d3 + d4],
      [p0 + d1 + d2 + d3 + d4, p5],
      [0, p5]
    ];

    const backgroundColors = [
      "#3b82f6", // Baseline
      d1 >= 0 ? "#ef4444" : "#10b981",
      d2 >= 0 ? "#ef4444" : "#10b981",
      d3 >= 0 ? "#ef4444" : "#10b981",
      d4 >= 0 ? "#ef4444" : "#10b981",
      d5 >= 0 ? "#ef4444" : "#10b981",
      "#8b5cf6"  // Final Target
    ];

    const cur = data.currency_symbol || (data.currency === 'INR' || appState.currency === 'INR' ? '₹' : '€');

    reconciliationWaterfallChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [{
          label: `Premium Amount (${cur})`,
          data: dataBars,
          backgroundColor: backgroundColors,
          borderRadius: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const raw = ctx.raw;
                const diff = (raw[1] - raw[0]).toFixed(2);
                return `Level: ${raw[1].toFixed(2)} ${cur} (Change: ${diff} ${cur})`;
              }
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            title: { display: true, text: `Total Payable Premium (${cur})` }
          }
        }
      }
    });
  },

  async replayCurrentRun() {
    const btn = document.getElementById("btn-replay-run");
    const runId = btn.getAttribute("data-run-id");
    if (!runId) return;

    btn.disabled = true;
    btn.innerText = "Replaying...";

    try {
      const res = await fetch(`/api/v1/runs/${runId}/replay`, { method: "POST" });
      const replay = await res.json();
      
      const box = document.getElementById("replay-status-box");
      box.style.display = "block";
      if (replay.is_reproducible) {
        box.className = "alert alert-success";
        box.innerHTML = `✅ <strong>Replay Verified:</strong> Calculation reproduced exactly to within <strong>${replay.absolute_difference.toExponential(4)} €</strong> (tolerance ε = 10⁻⁶). Checksums confirmed.`;
      } else {
        box.className = "alert alert-danger";
        box.innerHTML = `⚠️ <strong>Replay Discrepancy:</strong> Absolute difference = ${replay.absolute_difference.toFixed(6)} € exceeds tolerance.`;
      }
    } catch (e) {
      alert("Replay error: " + e.message);
    } finally {
      btn.disabled = false;
      btn.innerText = "Replay & Verify Execution (10⁻⁶)";
    }
  }
};

document.addEventListener("DOMContentLoaded", () => {
  reconciliation.init();
});
