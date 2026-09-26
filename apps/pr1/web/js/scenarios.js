/**
 * Scenario analysis.
 *
 * The page a panel drives. Before and after are drawn as split bars from the
 * same optimiser, so a shift in volume is visible rather than described.
 */

import { get, post } from "/shared/api.js";
import { splitBar, splitLegend } from "/shared/chart.js";
import { delta, money, pct, seconds, units } from "/shared/format.js";
import { groupByRequirement } from "/shared/plan.js";
import { renderRail } from "/js/shell.js";

renderRail("/pages/scenarios.html");

const elements = {
  scenario: document.getElementById("scenario"),
  param: document.getElementById("param"),
  paramField: document.getElementById("param-field"),
  paramLabel: document.getElementById("param-label"),
  plant: document.getElementById("plant"),
  run: document.getElementById("run"),
  description: document.getElementById("scenario-description"),
  timing: document.getElementById("scenario-timing"),
  narrative: document.getElementById("narrative"),
  deltas: document.getElementById("deltas"),
  splits: document.getElementById("compare-splits"),
};

let scenarios = [];

function currentScenario() {
  return scenarios.find((scenario) => scenario.key === elements.scenario.value);
}

function syncParameter() {
  const scenario = currentScenario();
  if (!scenario) return;

  elements.description.textContent = scenario.description;

  // A supplier outage names a supplier rather than taking a number, and the
  // server picks the plan's largest supplier when none is given.
  const isOutage = scenario.key === "supplier_outage";
  elements.paramField.style.display = isOutage ? "none" : "";
  elements.paramLabel.textContent = scenario.parameter_label;
  if (!isOutage) elements.param.value = scenario.default;
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

function renderDeltas(result) {
  const deltas = result.deltas;
  const broken = result.after.status !== "optimal";

  elements.deltas.innerHTML = [
    stat(
      "Total cost",
      broken ? "—" : delta(deltas.total_cost_pct),
      broken ? "no plan exists" : money(result.after.total_cost),
      broken ? null : deltas.total_cost_pct <= 0 ? "good" : "bad",
    ),
    stat(
      "Expected late units",
      broken ? "—" : delta(deltas.expected_late_pct),
      broken ? "" : units(result.after.expected_late_units),
      broken ? null : deltas.expected_late_pct <= 0 ? "good" : "bad",
    ),
    stat(
      "High-risk volume",
      broken ? "—" : `${deltas.high_risk_pp.toFixed(1)}pp`,
      broken ? "" : pct(result.after.high_risk_share),
      broken ? null : deltas.high_risk_pp <= 0 ? "good" : "bad",
    ),
    stat(
      "Suppliers used",
      broken ? "—" : String(result.after.suppliers_used),
      broken ? "" : `${deltas.suppliers_delta >= 0 ? "+" : ""}${deltas.suppliers_delta} against the base plan`,
    ),
  ].join("");
}

function renderSplits(result) {
  elements.splits.innerHTML = "";

  if (result.after.status !== "optimal") {
    elements.splits.innerHTML =
      `<div class="note">${result.after.message || "No plan satisfies every constraint."}</div>`;
    return;
  }

  const before = groupByRequirement(result.before.lines).slice(0, 3);
  const after = groupByRequirement(result.after.lines);

  elements.splits.append(splitLegend());

  for (const group of before) {
    const match = after.find(
      (other) =>
        other.material_id === group.material_id &&
        other.plant_id === group.plant_id &&
        other.week === group.week,
    );

    const head = document.createElement("div");
    head.className = "req";
    head.innerHTML = `<span class="req__name">${group.material_id}</span>
      <span class="req__meta">week ${group.week}</span>`;
    elements.splits.append(head);

    for (const [label, lines] of [["Before", group.lines], ["After", match?.lines ?? []]]) {
      const caption = document.createElement("p");
      caption.className = "small faint";
      caption.style.margin = "var(--space-3) 0 var(--space-1)";
      caption.textContent = label;

      const bar = document.createElement("div");
      bar.style.marginBottom = "var(--space-3)";

      elements.splits.append(caption, bar);
      splitBar(bar, lines);
    }
  }
}

async function run() {
  const scenario = currentScenario();
  if (!scenario) return;

  elements.run.disabled = true;
  elements.timing.textContent = "Re-planning…";
  elements.narrative.innerHTML = "";

  const parameters = {};
  if (scenario.key !== "supplier_outage") {
    parameters[scenario.parameter] = Number(elements.param.value);
  }

  try {
    const result = await post(`/api/scenarios/${scenario.key}`, {
      parameters,
      allocation: { plant_id: elements.plant.value, weeks: 2 },
    });

    elements.timing.textContent = `re-planned in ${seconds(result.after.solve_seconds)}`;
    elements.narrative.innerHTML =
      `<div class="panel"><div class="panel__body"><p style="margin:0">${result.narrative}</p></div></div>`;
    renderDeltas(result);
    renderSplits(result);
  } catch (error) {
    elements.timing.textContent = "";
    elements.narrative.innerHTML = `<div class="error">${error.message}</div>`;
  } finally {
    elements.run.disabled = false;
  }
}

elements.scenario.addEventListener("change", syncParameter);
elements.run.addEventListener("click", run);

async function start() {
  const [list, plants] = await Promise.all([get("/api/scenarios"), get("/api/plants")]);
  scenarios = list;

  for (const scenario of scenarios) {
    const option = document.createElement("option");
    option.value = scenario.key;
    option.textContent = scenario.name;
    elements.scenario.append(option);
  }
  for (const plant of plants) {
    const option = document.createElement("option");
    option.value = plant.plant_id;
    option.textContent = plant.name;
    elements.plant.append(option);
  }

  syncParameter();
  run();
}

start();
