/**
 * Pre-PO risk check.
 *
 * The use case asks for delivery delays to be predicted before the order is
 * released, so this page is deliberately the shape of a decision: pick the
 * order, get a verdict, see the reasons.
 */

import { get, post } from "/shared/api.js";
import { pct, truncate, units } from "/shared/format.js";
import { renderRail } from "/js/shell.js";

renderRail("/pages/risk-check.html");

const VERDICTS = {
  normal: { badge: "positive", title: "Safe to release" },
  elevated: { badge: "medium", title: "Releasable, with a buffer" },
  high: { badge: "high", title: "Hold for review" },
};

const elements = {
  material: document.getElementById("material"),
  plant: document.getElementById("plant"),
  supplier: document.getElementById("supplier"),
  quantity: document.getElementById("quantity"),
  check: document.getElementById("check"),
  verdict: document.getElementById("verdict"),
  factors: document.getElementById("factors"),
};

async function loadSuppliers() {
  const params = {
    material_id: elements.material.value,
    plant_id: elements.plant.value || null,
    limit: 500,
  };
  const body = await get("/api/suppliers", params);

  elements.supplier.innerHTML = "";
  for (const row of body.rows) {
    const option = document.createElement("option");
    option.value = row.supplier_id;
    const marker = row.origin === "synthetic" ? " (generated)" : "";
    option.textContent = `${truncate(row.name, 40)}${marker}`;
    elements.supplier.append(option);
  }

  if (body.rows.length === 0) {
    const option = document.createElement("option");
    option.textContent = "No supplier approved for this combination";
    option.value = "";
    elements.supplier.append(option);
  }
}

function renderVerdict(result) {
  const style = VERDICTS[result.verdict] ?? VERDICTS.normal;
  elements.verdict.innerHTML = `
    <div class="stats">
      <div class="stat">
        <div class="stat__label">Verdict</div>
        <div class="stat__value" style="font-size: var(--text-lg)">
          <span class="badge badge--${style.badge}">${style.title}</span>
        </div>
        <div class="stat__note">${result.supplier_name}</div>
      </div>
      <div class="stat">
        <div class="stat__label">Chance of late delivery</div>
        <div class="stat__value">${pct(result.delay_probability, 0)}</div>
        <div class="stat__note">${
          result.has_measured_risk
            ? "measured from their own delivery record"
            : "population average — no history with this supplier"
        }</div>
      </div>
      <div class="stat">
        <div class="stat__label">Chance of a quality problem</div>
        <div class="stat__value">${pct(result.quality_probability, 0)}</div>
        <div class="stat__note">observed defect rate</div>
      </div>
    </div>
    <div class="panel">
      <div class="panel__body">
        <p style="margin:0">${result.explanation}</p>
      </div>
    </div>`;
}

function renderFactors(result) {
  if (!result.top_factors.length) {
    elements.factors.innerHTML = '<div class="empty">No contributing factors recorded.</div>';
    return;
  }

  elements.factors.innerHTML = result.top_factors
    .map(
      (factor) => `
      <div class="compare-row" style="align-items:flex-start; padding: var(--space-3) 0">
        <span style="flex:0 0 200px"><strong>${factor.factor}</strong></span>
        <span class="muted" style="flex:1">${factor.explanation}</span>
      </div>`,
    )
    .join("");
}

async function check() {
  if (!elements.supplier.value) return;

  elements.check.disabled = true;
  elements.verdict.innerHTML = '<div class="loading">Scoring…</div>';
  try {
    const result = await post("/api/risk/score-po", {
      supplier_id: elements.supplier.value,
      material_id: elements.material.value,
      plant_id: elements.plant.value || null,
      quantity: Number(elements.quantity.value),
    });
    renderVerdict(result);
    renderFactors(result);
  } catch (error) {
    elements.verdict.innerHTML = `<div class="error">${error.message}</div>`;
  } finally {
    elements.check.disabled = false;
  }
}

elements.check.addEventListener("click", check);
for (const id of ["material", "plant"]) {
  document.getElementById(id).addEventListener("change", async () => {
    await loadSuppliers();
    check();
  });
}

async function start() {
  const [materials, plants] = await Promise.all([get("/api/materials"), get("/api/plants")]);

  for (const material of materials) {
    const option = document.createElement("option");
    option.value = material.material_id;
    option.textContent = truncate(material.material_id, 46);
    elements.material.append(option);
  }
  for (const plant of plants) {
    const option = document.createElement("option");
    option.value = plant.plant_id;
    option.textContent = plant.name;
    elements.plant.append(option);
  }

  await loadSuppliers();
  check();
}

start();
