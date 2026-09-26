/**
 * The inventory view: safety stock, reorder points, and whether the buffer holds.
 */

import { get } from "/shared/api.js";
import { pct, units } from "/shared/format.js";
import { createTable } from "/shared/table.js";
import { renderRail, showError, stat } from "/js/shell.js";

renderRail("/pages/inventory.html");

const FLAGS = {
  stockout_risk: ["high", "Stock-out risk"],
  below_reorder: ["medium", "Below reorder"],
  healthy: ["positive", "Healthy"],
  overstock: ["generated", "Overstock"],
};

async function load() {
  try {
    const body = await get("/api/inventory");
    const summary = body.summary;
    const check = body.backtest;

    document.getElementById("inv-stats").innerHTML = [
      stat(
        "At stock-out risk",
        `${summary.stockout_risk}`,
        "styles with under a week of cover",
        summary.stockout_risk ? "bad" : "good",
      ),
      stat("Below reorder point", `${summary.below_reorder}`, "styles needing replenishment"),
      stat("Safety stock held", units(summary.total_safety_stock), "units of buffer"),
      stat("Median cover", `${summary.median_weeks_of_cover} wk`, "weeks of demand on hand"),
    ].join("");

    document.getElementById("inv-backtest").innerHTML = `
      <div class="compare-grid">
        <div class="compare-card">
          <h3>Checked against what happened</h3>
          <div class="compare-row"><span class="muted">Weeks observed</span>
            <span class="num">${units(check.weeks_observed)}</span></div>
          <div class="compare-row"><span class="muted">Weeks demand beat the cover</span>
            <span class="num">${units(check.weeks_demand_exceeded_cover)}</span></div>
          <div class="compare-row"><span class="muted">Service level achieved</span>
            <span class="num">${pct(check.implied_service_level)}</span></div>
          <div class="compare-row"><span class="muted">Service level planned</span>
            <span class="num">95.0%</span></div>
        </div>
        <div class="compare-card">
          <h3>How the buffer is sized</h3>
          <p class="small muted" style="margin:0">
            z × sigma(forecast error) × the square root of the lead time. Sigma is measured from
            each style's own forecast residuals, so a style we predict badly carries more buffer.
            The square root is there because errors over several weeks partly cancel — multiplying
            by the lead time instead would roughly double the stock held for no extra service.
          </p>
        </div>
      </div>`;

    createTable(document.getElementById("inv-table"), {
      columns: [
        { key: "style_id", label: "Style" },
        {
          key: "flag",
          label: "State",
          render: (value) => {
            const [tone, label] = FLAGS[value] ?? ["generated", value];
            const badge = document.createElement("span");
            badge.className = `badge badge--${tone}`;
            badge.textContent = label;
            return badge;
          },
        },
        { key: "on_hand", label: "On hand", numeric: true, format: units },
        { key: "mean_weekly_demand", label: "Weekly demand", numeric: true, format: units },
        { key: "sigma_error", label: "Forecast error", numeric: true, format: units },
        { key: "safety_stock", label: "Safety stock", numeric: true, format: units },
        { key: "reorder_point", label: "Reorder at", numeric: true, format: units },
        {
          key: "weeks_of_cover",
          label: "Cover",
          numeric: true,
          format: (value) => (Number.isFinite(value) ? `${value.toFixed(1)} wk` : "—"),
        },
        { key: "gap_units", label: "Short of target", numeric: true, format: units },
      ],
      rows: body.rows,
      pageSize: 20,
      sortKey: "gap_units",
      searchPlaceholder: "Search styles",
    });
  } catch (error) {
    for (const id of ["inv-stats", "inv-backtest", "inv-table"]) {
      showError(document.getElementById(id), error);
    }
  }
}

load();
