/**
 * The model panel.
 *
 * Shows all three risk targets in the same words, including the two whose
 * labels did not support a model. Presenting the failures beside the success is
 * the point: it shows the gate exists and that it bites.
 */

import { get } from "/shared/api.js";
import { humanise, units } from "/shared/format.js";
import { renderRail } from "/js/shell.js";

renderRail("/pages/models.html");

const TITLES = {
  delay: "Late delivery",
  quality: "Quality problem",
  disruption: "Cancellation or partial delivery",
};

const METRICS = [
  ["precision", "Precision"],
  ["recall", "Recall"],
  ["f1", "F1"],
  ["roc_auc", "ROC-AUC"],
  ["pr_auc", "PR-AUC"],
];

function metricRow(label, value, comparison) {
  const compare = comparison == null ? "" : `<span class="num faint">vs ${comparison.toFixed(3)}</span>`;
  return `
    <div class="compare-row">
      <span class="muted">${label}</span>
      <span style="display:flex; gap:var(--space-3); align-items:baseline">
        ${compare}<span class="num">${value == null ? "—" : value.toFixed(3)}</span>
      </span>
    </div>`;
}

function candidateTable(candidates) {
  if (!candidates || Object.keys(candidates).length === 0) return "";

  const rows = Object.entries(candidates)
    .sort(([, a], [, b]) => (b.pr_auc ?? 0) - (a.pr_auc ?? 0))
    .map(
      ([name, scores]) => `
        <tr>
          <td>${humanise(name)}</td>
          <td class="numeric num">${(scores.precision ?? 0).toFixed(3)}</td>
          <td class="numeric num">${(scores.recall ?? 0).toFixed(3)}</td>
          <td class="numeric num">${(scores.roc_auc ?? 0).toFixed(3)}</td>
          <td class="numeric num">${(scores.pr_auc ?? 0).toFixed(3)}</td>
        </tr>`,
    )
    .join("");

  return `
    <h3 style="margin-top:var(--space-5)">Candidates compared</h3>
    <p class="small muted">Same features, same chronological split. The winner is kept; where the
      simpler model is within 0.01 PR-AUC, the simpler one wins.</p>
    <div class="table-wrap">
      <table class="data">
        <thead><tr>
          <th>Model</th><th class="numeric">Precision</th><th class="numeric">Recall</th>
          <th class="numeric">ROC-AUC</th><th class="numeric">PR-AUC</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function importanceList(importance) {
  const entries = Object.entries(importance ?? {}).slice(0, 6);
  if (entries.length === 0) return "";

  const rows = entries
    .map(
      ([name, value]) => `
      <div class="compare-row">
        <span class="muted">${humanise(name)}</span>
        <span class="num">${value.toFixed(3)}</span>
      </div>`,
    )
    .join("");

  return `<h3 style="margin-top:var(--space-5)">What it learned from</h3>${rows}`;
}

function renderModel(key, metrics) {
  const shipped = metrics.label_sufficient;
  const badge = shipped
    ? '<span class="badge badge--positive">Model in use</span>'
    : '<span class="badge badge--medium">Observed rate used instead</span>';

  return `
    <section class="panel">
      <div class="panel__head">
        <div>
          <h2>${TITLES[key] ?? humanise(key)}</h2>
          <p class="small muted" style="margin:4px 0 0">
            ${units(metrics.rows)} records · ${units(metrics.positives)} positives ·
            tested on ${units(metrics.support)} held-out orders
          </p>
        </div>
        ${badge}
      </div>
      <div class="panel__body">
        <p class="${shipped ? "small muted" : "note"}" style="margin-bottom:var(--space-4)">
          ${metrics.sufficiency_reason}
        </p>

        <div class="compare-grid">
          <div class="compare-card">
            <h3>Scores on unseen orders</h3>
            ${METRICS.map(([key_, label]) => metricRow(label, metrics[key_])).join("")}
          </div>
          <div class="compare-card">
            <h3>What it had to beat</h3>
            ${metricRow("Supplier's own history (PR-AUC)", metrics.baseline_prior_pr_auc)}
            ${metricRow("Predict the overall rate (PR-AUC)", metrics.baseline_majority_pr_auc)}
            ${metricRow("Decision threshold", metrics.threshold)}
            <div class="compare-row">
              <span class="muted">Tested on</span>
              <span class="small">${(metrics.test_start_date ?? "").slice(0, 10)} to
                ${(metrics.test_end_date ?? "").slice(0, 10)}</span>
            </div>
          </div>
        </div>

        ${candidateTable(metrics.candidates)}
        ${importanceList(metrics.feature_importance)}
      </div>
    </section>`;
}

async function load() {
  const mount = document.getElementById("models");
  try {
    const body = await get("/api/models/metrics");
    mount.innerHTML = ["delay", "quality", "disruption"]
      .filter((key) => body[key])
      .map((key) => renderModel(key, body[key]))
      .join("");
  } catch (error) {
    mount.innerHTML = `<div class="error">${error.message}</div>`;
  }
}

load();
