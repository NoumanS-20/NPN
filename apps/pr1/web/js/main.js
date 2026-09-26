/**
 * SupplyGuard overview.
 *
 * Loads the headline numbers, plans the first few requirement lines, and shows
 * the plan against the three alternatives. Everything else lives on its own
 * page; this one exists to answer "is it working, and is it worth it?" in the
 * first ten seconds.
 */

import { get, post } from "/shared/api.js";
import { splitBar, splitLegend } from "/shared/chart.js";
import { delta, money, pct, seconds, truncate, units } from "/shared/format.js";

const PREVIEW_LINES = 4;

function stat(label, value, note, tone) {
  const toneClass = tone ? ` delta--${tone}` : "";
  return `
    <div class="stat">
      <div class="stat__label">${label}</div>
      <div class="stat__value${toneClass}">${value}</div>
      ${note ? `<div class="stat__note">${note}</div>` : ""}
    </div>`;
}

async function renderKpis() {
  const mount = document.getElementById("kpis");
  try {
    const kpis = await get("/api/kpis");
    mount.innerHTML = [
      stat(
        "Total cost of the plan",
        money(kpis.plan_total_cost),
        `${units(kpis.plan_invoice)} invoice · ${kpis.suppliers_used} suppliers`,
      ),
      stat(
        "Against last year's buying",
        delta(kpis.vs_historical_total_cost_pct),
        "total cost, same requirement",
        kpis.vs_historical_total_cost_pct < 0 ? "good" : "bad",
      ),
      stat(
        "Volume on high-risk suppliers",
        pct(kpis.plan_high_risk_share),
        `${delta(kpis.vs_cheapest_high_risk_pp).replace("%", "pp")} against buying on price alone`,
        kpis.vs_cheapest_high_risk_pp <= 0 ? "good" : "bad",
      ),
      stat(
        "Delay model",
        kpis.delay_model_roc_auc.toFixed(3),
        `ROC-AUC · ${kpis.delay_model.replace("_", " ")}`,
      ),
    ].join("");
  } catch (error) {
    mount.innerHTML = `<div class="error">${error.message}</div>`;
  }
}

async function renderPlan() {
  const mount = document.getElementById("plan-preview");
  const timing = document.getElementById("plan-solve");

  try {
    const plants = await get("/api/plants");
    const plan = await post("/api/allocate", { plant_id: plants[0].plant_id, weeks: 1 });

    timing.textContent = `${plants[0].name} · week 1 · solved in ${seconds(plan.solve_seconds)}`;

    if (!plan.lines.length) {
      mount.innerHTML = `<div class="empty">${plan.message || "No plan for this selection."}</div>`;
      return;
    }

    const byRequirement = new Map();
    for (const line of plan.lines) {
      const key = `${line.material_id}`;
      if (!byRequirement.has(key)) byRequirement.set(key, []);
      byRequirement.get(key).push(line);
    }

    mount.innerHTML = "";
    mount.append(splitLegend());
    const shown = [...byRequirement].slice(0, PREVIEW_LINES);
    for (const [material, lines] of shown) {
      const total = lines.reduce((sum, line) => sum + line.qty, 0);

      const head = document.createElement("div");
      head.className = "req";
      head.innerHTML = `
        <span class="req__name">${truncate(material, 52)}</span>
        <span class="req__meta">${units(total)} units · ${lines.length} suppliers</span>`;

      const bar = document.createElement("div");
      bar.className = "req-bar";

      mount.append(head, bar);
      splitBar(bar, lines);
    }

    // The cockpit shows a handful of bars, not the plan. Saying so is the
    // difference between a preview and a screen that quietly hides four
    // materials — the allocation page makes the same disclosure.
    const hidden = byRequirement.size - shown.length;
    if (hidden > 0) {
      const note = document.createElement("p");
      note.className = "small muted";
      note.style.marginTop = "var(--space-4)";
      note.textContent =
        `Showing ${shown.length} of ${byRequirement.size} materials in this plant-week. `
        + `The planner has all ${byRequirement.size}.`;
      mount.append(note);
    }

    if (plan.message) {
      const note = document.createElement("div");
      note.className = "note";
      note.style.marginTop = "var(--space-4)";
      note.textContent = plan.message;
      mount.append(note);
    }
  } catch (error) {
    mount.innerHTML = `<div class="error">${error.message}</div>`;
  }
}

async function renderBaselines() {
  const mount = document.getElementById("baseline-preview");
  try {
    const plants = await get("/api/plants");
    const body = await post("/api/allocate/compare", {
      plant_id: plants[0].plant_id,
      weeks: 1,
    });

    const cards = Object.entries(body.comparison).map(([name, metrics]) => {
      const label = name.replace(/_/g, " ");
      const rows = [
        ["Invoice", delta(metrics.invoice_delta_pct), metrics.invoice_delta_pct <= 0],
        ["Total cost", delta(metrics.total_cost_delta_pct), metrics.total_cost_delta_pct <= 0],
        ["Expected late", delta(metrics.expected_late_delta_pct), metrics.expected_late_delta_pct <= 0],
        ["High-risk volume", `${metrics.high_risk_delta_pp.toFixed(1)}pp`, metrics.high_risk_delta_pp <= 0],
      ];
      return `
        <div class="compare-card">
          <h3>Versus ${label}</h3>
          ${rows
            .map(
              ([key, value, good]) => `
            <div class="compare-row">
              <span class="muted">${key}</span>
              <span class="num ${good ? "delta--good" : "delta--bad"}">${value}</span>
            </div>`,
            )
            .join("")}
        </div>`;
    });

    mount.innerHTML = `<div class="compare-grid">${cards.join("")}</div>
      <p class="small muted" style="margin-top:var(--space-4)">
        Negative is better. Against cheapest-first we knowingly pay a little more and take
        less risk — the trade is on the allocation page.
      </p>`;
  } catch (error) {
    mount.innerHTML = `<div class="error">${error.message}</div>`;
  }
}

async function renderContext() {
  const line = document.getElementById("context-line");
  try {
    const summary = await get("/api/summary");
    line.classList.remove("skeleton");
    line.textContent = `${summary.suppliers} suppliers · ${summary.plants} plants · ${summary.materials} materials`;
  } catch {
    line.classList.remove("skeleton");
    line.textContent = "Backend unavailable";
  }
}

renderContext();
renderKpis();
renderPlan();
renderBaselines();
