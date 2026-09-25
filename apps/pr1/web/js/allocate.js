/**
 * The allocation screen — where the argument of the project is on screen.
 *
 * Drag the risk weight and the split bars re-flow. The plan below them is the
 * same optimiser the API serves; nothing here is a mock-up or a canned result.
 *
 * Re-solving takes about half a second, so the sliders debounce rather than
 * firing on every pixel of movement: a request per frame would queue up behind
 * itself and make the page feel slower than the solver actually is.
 */

import { get, post } from "/shared/api.js";
import { splitBar, splitLegend } from "/shared/chart.js";
import { delta, money, pct, price, seconds, truncate, units } from "/shared/format.js";
import {
  comparisonRows,
  describeChange,
  groupByRequirement,
  planTotals,
  requirementMeta,
} from "/shared/plan.js";
import { createTable } from "/shared/table.js";
import { renderRail } from "/js/shell.js";

renderRail("/pages/allocate.html");

const DEBOUNCE_MS = 220;
const MAX_BARS = 8;

const PRESETS = {
  cost: { cost: 1, risk: 0, quality: 0 },
  balanced: { cost: 1, risk: 1, quality: 1 },
  risk: { cost: 1, risk: 3, quality: 1 },
};

const elements = {
  plant: document.getElementById("plant"),
  weeks: document.getElementById("weeks"),
  share: document.getElementById("share"),
  shareValue: document.getElementById("share-value"),
  stats: document.getElementById("plan-stats"),
  splits: document.getElementById("splits"),
  comparison: document.getElementById("comparison"),
  lines: document.getElementById("lines"),
  solve: document.getElementById("solve-time"),
  change: document.getElementById("change-note"),
  relaxation: document.getElementById("relaxation-note"),
};

const weights = {
  cost: document.getElementById("w-cost"),
  risk: document.getElementById("w-risk"),
  quality: document.getElementById("w-quality"),
};

let previousPlan = null;
let linesTable = null;
let timer = null;
let inFlight = 0;

function currentRequest() {
  return {
    plant_id: elements.plant.value || null,
    weeks: Number(elements.weeks.value),
    max_supplier_share: Number(elements.share.value) / 100,
    weights: {
      cost: Number(weights.cost.value),
      risk: Number(weights.risk.value),
      quality: Number(weights.quality.value),
    },
  };
}

function syncLabels() {
  elements.shareValue.textContent = `${elements.share.value}%`;
  for (const [name, input] of Object.entries(weights)) {
    document.getElementById(`w-${name}-value`).textContent = Number(input.value).toFixed(1);
  }
}

function stat(label, value, note, tone) {
  const toneClass = tone ? ` delta--${tone}` : "";
  return `
    <div class="stat">
      <div class="stat__label">${label}</div>
      <div class="stat__value${toneClass}">${value}</div>
      ${note ? `<div class="stat__note">${note}</div>` : ""}
    </div>`;
}

function renderStats(plan) {
  const totals = planTotals(plan);
  elements.stats.innerHTML = [
    stat("Invoice", money(totals.invoice), `${units(totals.units)} units`),
    stat("Total cost", money(totals.totalCost), "invoice plus priced risk"),
    stat(
      "Expected late units",
      units(totals.expectedLate),
      "units × probability of lateness",
    ),
    stat(
      "On high-risk suppliers",
      pct(totals.highRiskShare),
      `${totals.suppliers} suppliers used`,
      totals.highRiskShare <= 0.05 ? "good" : "bad",
    ),
  ].join("");
}

function renderSplits(plan) {
  const groups = groupByRequirement(plan.lines);
  elements.splits.innerHTML = "";

  if (groups.length === 0) {
    elements.splits.innerHTML = `<div class="empty">${plan.message || "No plan for this selection."}</div>`;
    return;
  }

  elements.splits.append(splitLegend());

  for (const group of groups.slice(0, MAX_BARS)) {
    const head = document.createElement("div");
    head.className = "req";
    head.innerHTML = `
      <span class="req__name">${truncate(group.material_id, 50)}</span>
      <span class="req__meta">${requirementMeta(group)}</span>`;

    const bar = document.createElement("div");
    bar.className = "req-bar";

    elements.splits.append(head, bar);
    splitBar(bar, group.lines);
  }

  if (groups.length > MAX_BARS) {
    const more = document.createElement("p");
    more.className = "small faint";
    more.style.marginTop = "var(--space-4)";
    more.textContent = `${groups.length - MAX_BARS} more requirements are in the table below.`;
    elements.splits.append(more);
  }
}

function renderComparison(comparison) {
  const rows = comparisonRows(comparison);
  if (rows.length === 0) {
    elements.comparison.innerHTML = '<div class="empty">No comparison available.</div>';
    return;
  }

  const cards = rows.map((row) => {
    const metrics = row.metrics
      .map(
        (metric) => `
        <div class="compare-row">
          <span class="muted">${metric.label}</span>
          <span class="num ${metric.good ? "delta--good" : "delta--bad"}">${delta(metric.value)}</span>
        </div>`,
      )
      .join("");

    return `
      <div class="compare-card">
        <h3>Versus ${row.label}</h3>
        ${metrics}
        <div class="compare-row">
          <span class="muted">High-risk volume</span>
          <span class="num ${row.highRiskDelta <= 0 ? "delta--good" : "delta--bad"}">
            ${row.highRiskDelta.toFixed(1)}pp
          </span>
        </div>
      </div>`;
  });

  elements.comparison.innerHTML = `<div class="compare-grid">${cards.join("")}</div>
    <p class="small muted" style="margin-top:var(--space-4)">
      Cheapest-first ignores the concentration cap and contract limits that this plan obeys, so it
      can come out slightly cheaper. What the difference buys is in the high-risk row.
    </p>`;
}

const LINE_COLUMNS = [
  { key: "supplier_name", label: "Supplier", format: (value) => truncate(value, 34) },
  { key: "material_id", label: "Material", format: (value) => truncate(value, 30) },
  { key: "week", label: "Week", numeric: true, ascendingFirst: true },
  { key: "qty", label: "Quantity", numeric: true, format: units },
  { key: "share_of_requirement", label: "Share", numeric: true, format: (v) => pct(v, 0) },
  { key: "unit_price", label: "Price", numeric: true, format: price, ascendingFirst: true },
  {
    key: "delay_probability",
    label: "Delay risk",
    numeric: true,
    format: (value) => pct(value, 0),
  },
  { key: "reason", label: "Why", sortable: false, format: (value) => value },
];

function renderLines(plan) {
  if (plan.lines.length === 0) {
    elements.lines.innerHTML = '<div class="empty">Nothing allocated.</div>';
    linesTable = null;
    return;
  }

  if (linesTable) {
    linesTable.setRows(plan.lines);
  } else {
    elements.lines.innerHTML = "";
    linesTable = createTable(elements.lines, {
      columns: LINE_COLUMNS,
      rows: plan.lines,
      pageSize: 15,
      sortKey: "qty",
      searchPlaceholder: "Search the plan",
      rowBadge: (row) => (row.origin === "synthetic" ? "Generated" : null),
    });
  }
}

async function solve() {
  const request = currentRequest();
  const token = ++inFlight;

  elements.solve.textContent = "Planning…";
  try {
    const body = await post("/api/allocate/compare", request);
    // A slow response from an earlier drag must not overwrite a newer plan.
    if (token !== inFlight) return;

    const plan = body.plan;
    elements.solve.textContent =
      `${plan.lines.length} lines · solved in ${seconds(plan.solve_seconds)}`;

    renderStats(plan);
    renderSplits(plan);
    renderComparison(body.comparison);
    renderLines(plan);

    elements.change.textContent = describeChange(previousPlan, plan);
    elements.relaxation.innerHTML = plan.message
      ? `<div class="note">${plan.message}</div>`
      : "";
    previousPlan = plan;
  } catch (error) {
    if (token !== inFlight) return;
    elements.solve.textContent = "";
    elements.splits.innerHTML = `<div class="error">${error.message}</div>`;
  }
}

function scheduleSolve() {
  syncLabels();
  clearTimeout(timer);
  timer = setTimeout(solve, DEBOUNCE_MS);
}

for (const input of [elements.share, ...Object.values(weights)]) {
  input.addEventListener("input", scheduleSolve);
}
for (const select of [elements.plant, elements.weeks]) {
  select.addEventListener("change", scheduleSolve);
}

for (const button of document.querySelectorAll("[data-preset]")) {
  button.addEventListener("click", () => {
    const preset = PRESETS[button.dataset.preset];
    for (const [name, value] of Object.entries(preset)) {
      weights[name].value = String(value);
    }
    scheduleSolve();
  });
}

async function start() {
  const plants = await get("/api/plants");
  for (const plant of plants) {
    const option = document.createElement("option");
    option.value = plant.plant_id;
    option.textContent = plant.name;
    elements.plant.append(option);
  }
  syncLabels();
  solve();
}

start();
