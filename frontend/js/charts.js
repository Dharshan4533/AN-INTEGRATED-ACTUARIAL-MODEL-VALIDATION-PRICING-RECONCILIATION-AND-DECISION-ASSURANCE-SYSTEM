/**
 * Chart.js Visualizations for Actuarial Decision Support System.
 * Clean, responsive actuarial and machine learning calibration charts.
 */

const chartRegistry = {};

function destroyChart(canvasId) {
  if (chartRegistry[canvasId]) {
    chartRegistry[canvasId].destroy();
    delete chartRegistry[canvasId];
  }
}

const charts = {
  renderRiskDistribution(canvasId, riskDistribution) {
    destroyChart(canvasId);
    const ctx = document.getElementById(canvasId)?.getContext('2d');
    if (!ctx) return;

    chartRegistry[canvasId] = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: ['Low Risk', 'Moderate Risk', 'High Risk', 'Very High Risk'],
        datasets: [{
          data: riskDistribution || [30, 40, 20, 10],
          backgroundColor: ['#10b981', '#3b82f6', '#f59e0b', '#ef4444'],
          borderWidth: 2,
          borderColor: '#ffffff'
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'bottom' }
        },
        cutout: '70%'
      }
    });
  },

  renderCalibrationChart(canvasId, deciles, title, observedLabel, expectedLabel) {
    destroyChart(canvasId);
    const ctx = document.getElementById(canvasId)?.getContext('2d');
    if (!ctx || !deciles || deciles.length === 0) return;

    const labels = deciles.map(d => `D${d.decile}`);
    const obsData = deciles.map(d => d.observed_rate !== undefined ? d.observed_rate : d.observed_mean_severity);
    const expData = deciles.map(d => d.expected_rate !== undefined ? d.expected_rate : d.predicted_mean_severity);

    chartRegistry[canvasId] = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: observedLabel,
            data: obsData,
            borderColor: '#0f172a',
            backgroundColor: 'transparent',
            borderWidth: 2,
            pointBackgroundColor: '#0f172a',
            pointRadius: 4,
            tension: 0.1
          },
          {
            label: expectedLabel,
            data: expData,
            borderColor: '#4f46e5',
            backgroundColor: 'rgba(79, 70, 229, 0.08)',
            fill: true,
            borderWidth: 2,
            borderDash: [5, 5],
            pointBackgroundColor: '#4f46e5',
            pointRadius: 4,
            tension: 0.1
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'top' },
          tooltip: {
            callbacks: {
              afterBody(items) {
                const idx = items[0].dataIndex;
                const ratio = deciles[idx].oe_ratio || deciles[idx].ratio;
                return `O/E Ratio: ${ratio ? ratio.toFixed(4) : 'N/A'}`;
              }
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            grid: { color: '#f1f5f9' },
            title: { display: true, text: title }
          },
          x: {
            grid: { display: false },
            title: { display: true, text: 'Predicted Risk Decile (Low to High)' }
          }
        }
      }
    });
  },

  renderPortfolioHistogram(canvasId, histogramBins, var99, tvar99, currencySymbol = '€') {
    destroyChart(canvasId);
    const ctx = document.getElementById(canvasId)?.getContext('2d');
    if (!ctx || !histogramBins || histogramBins.length === 0) return;

    const labels = histogramBins.map(b => `${Math.round(b.bin_start / 1000)}k-${Math.round(b.bin_end / 1000)}k`);
    const dataCounts = histogramBins.map(b => b.frequency);

    chartRegistry[canvasId] = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: 'Simulated Loss Frequency',
          data: dataCounts,
          backgroundColor: histogramBins.map(b => b.bin_end >= var99 ? 'rgba(239, 68, 68, 0.7)' : 'rgba(79, 70, 229, 0.6)'),
          borderColor: histogramBins.map(b => b.bin_end >= var99 ? '#dc2626' : '#4338ca'),
          borderWidth: 1,
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
              title: (items) => `Loss Range: ${histogramBins[items[0].dataIndex].bin_start.toLocaleString()} - ${histogramBins[items[0].dataIndex].bin_end.toLocaleString()} ${currencySymbol}`,
              label: (item) => `Iterations: ${item.raw.toLocaleString()} trials`
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            grid: { color: '#f1f5f9' },
            title: { display: true, text: 'Simulation Count' }
          },
          x: {
            grid: { display: false },
            title: { display: true, text: `Aggregate Loss Range (${currencySymbol})` }
          }
        }
      }
    });
  },

  renderFeatureImportance(canvasId, featureData) {
    destroyChart(canvasId);
    const ctx = document.getElementById(canvasId)?.getContext('2d');
    if (!ctx || !featureData || featureData.length === 0) return;

    const labels = featureData.map(f => f.feature);
    const values = featureData.map(f => f.mean_abs_effect);

    chartRegistry[canvasId] = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: 'Mean Absolute Impact (SHAP Attribution)',
          data: values,
          backgroundColor: 'rgba(79, 70, 229, 0.7)',
          borderColor: '#4338ca',
          borderWidth: 1,
          borderRadius: 4
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false }
        },
        scales: {
          x: {
            beginAtZero: true,
            grid: { color: '#f1f5f9' },
            title: { display: true, text: 'Mean Absolute Effect on Log Rate' }
          },
          y: {
            grid: { display: false }
          }
        }
      }
    });
  },

  renderWhatIfComparison(canvasId, baseQuote, revQuote) {
    destroyChart(canvasId);
    const ctx = document.getElementById(canvasId)?.getContext('2d');
    if (!ctx || !baseQuote || !revQuote) return;

    const labels = ['Annual Pure Premium', 'Commercial Premium', 'Fixed Expense', 'Statutory Tax'];
    const curSym = baseQuote.currency_symbol || '€';

    const baseData = [
      baseQuote.annual_pure_premium,
      baseQuote.total_commercial_premium,
      baseQuote.pricing_breakdown.fixed_expense,
      baseQuote.pricing_breakdown.statutory_tax
    ];

    const revData = [
      revQuote.annual_pure_premium,
      revQuote.total_commercial_premium,
      revQuote.pricing_breakdown.fixed_expense,
      revQuote.pricing_breakdown.statutory_tax
    ];

    chartRegistry[canvasId] = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Baseline Policy Profile',
            data: baseData,
            backgroundColor: '#94a3b8',
            borderRadius: 4
          },
          {
            label: 'Revised What-If Profile',
            data: revData,
            backgroundColor: '#4f46e5',
            borderRadius: 4
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'top' },
          tooltip: {
            callbacks: {
              label: (item) => `${item.dataset.label}: ${item.raw.toLocaleString()} ${curSym}`
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            grid: { color: '#f1f5f9' },
            title: { display: true, text: `Amount (${curSym})` }
          }
        }
      }
    });
  }
};
