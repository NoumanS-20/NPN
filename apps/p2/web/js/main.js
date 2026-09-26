/**
 * The S&OP cockpit.
 *
 * Where the cycle stands, what the business is committing to, and the number the
 * meeting exists to argue about: the gap between what merchandising wants to
 * sell and what the plants can make.
 */

import { get } from "/shared/api.js";
import { lineChart } from "/shared/chart.js";
import { money, pct, units } from "/shared/format.js";
import { renderRail, renderStages, showError, stat } from "/js/shell.js";

renderRail("/");

async function renderCycle() {
  const mount = document.getElementById("cycle");
  try {
    const body = await get("/api/cycles");
    renderStages(mount, body.stages, body.current_stage);

    const note = document.createElement("p");
    note.className = "small muted";
    note.style.marginTop = "var(--space-4)";
    note.textContent =
      `${body.cycles} monthly cycles planned, ${body.versions.length} versions stored. ` +
      "Each stage saves an immutable version; rejecting sends the plan back one stage.";
    mount.append(note);
  } catch (error) {
    showError(mount, error);
  }
}

async function renderKpis() {
  const mount = document.getElementById("kpis");
  try {
    const kpis = await get("/api/kpis");
    mount.innerHTML = [
      stat(
        "Committed revenue",
        money(kpis.revenue),
        `${pct(kpis.margin_pct)} gross margin · ${units(kpis.consensus_units)} units`,
      ),
      stat(
        "Unmet ambition",
        money(kpis.gap_value),
        `${units(kpis.gap_units)} units merchandising wants that supply cannot make`,
        kpis.gap_units > 0 ? "bad" : "good",
      ),
      stat(
        "Forecast error",
        pct(kpis.forecast_wape),
        `WAPE · seasonal naive is ${pct(kpis.forecast_wape_seasonal_naive)}`,
        kpis.forecast_wape < kpis.forecast_wape_seasonal_naive ? "good" : "bad",
      ),
      stat(
        "Styles needing attention",
        `${kpis.styles_at_stockout_risk + kpis.styles_marked_down}`,
        `${kpis.styles_at_stockout_risk} at stock-out risk · ${kpis.styles_marked_down} to mark down`,
      ),
    ].join("");
  } catch (error) {
    showError(mount, error);
  }
}

async function renderGap() {
  const mount = document.getElementById("gap-chart");
  try {
    const body = await get("/api/reconciliation");
    const weeks = body.by_week;

    mount.innerHTML = '<div class="chart-box"><canvas id="gap-canvas"></canvas></div>';
    lineChart(document.getElementById("gap-canvas"), {
      labels: weeks.map((row) => `wk ${row.week}`),
      series: [
        { label: "Merchandising plan", values: weeks.map((row) => row.merch_units) },
        { label: "Statistical forecast", values: weeks.map((row) => row.forecast_units) },
        { label: "What the plants can make", values: weeks.map((row) => row.supply_units) },
      ],
    });

    const summary = body.summary;
    const note = document.createElement("p");
    note.className = "small muted";
    note.style.marginTop = "var(--space-4)";
    note.textContent =
      `Merchandising is planning ${summary.ambition_vs_forecast_pct.toFixed(1)}% above the ` +
      `forecast. Supply falls short by ${units(summary.gap_units)} units across ` +
      `${summary.styles_short} styles, worth ${money(summary.gap_value)}.`;
    mount.append(note);
  } catch (error) {
    showError(mount, error);
  }
}

async function renderMoney() {
  const mount = document.getElementById("money");
  try {
    const body = await get("/api/financials");
    const totals = body.totals;

    const rows = [
      ["Revenue", money(totals.revenue)],
      ["Cost of sales", money(totals.cost_of_sales)],
      ["Gross margin", `${money(totals.gross_margin)} (${pct(totals.margin_pct)})`],
      ["Inventory at cost", money(totals.inventory_value)],
      ["Distribution (on the committed plan)", money(totals.distribution_cost)],
      ["Contribution", money(totals.contribution)],
    ];

    mount.innerHTML = `
      <div class="compare-grid">
        <div class="compare-card">
          <h3>The plan in money</h3>
          ${rows
            .map(
              ([label, value]) =>
                `<div class="compare-row"><span class="muted">${label}</span>
                 <span class="num">${value}</span></div>`,
            )
            .join("")}
        </div>
        <div class="compare-card">
          <h3>By category</h3>
          ${body.by_category
            .map(
              (row) =>
                `<div class="compare-row"><span class="muted">${row.category}</span>
                 <span class="num">${money(row.revenue)}</span></div>`,
            )
            .join("")}
        </div>
      </div>`;
  } catch (error) {
    showError(mount, error);
  }
}

renderCycle();
renderKpis();
renderGap();
renderMoney();
