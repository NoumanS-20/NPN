/**
 * The reconciliation screen — the heart of the S&OP cycle.
 */

import { get } from "/shared/api.js";
import { lineChart } from "/shared/chart.js";
import { money, truncate, units } from "/shared/format.js";
import { createTable } from "/shared/table.js";
import { renderRail, showError, stat } from "/js/shell.js";

renderRail("/pages/reconcile.html");

async function load() {
  try {
    const body = await get("/api/reconciliation");
    const summary = body.summary;

    document.getElementById("recon-stats").innerHTML = [
      stat("Merchandising wants", units(summary.merch_units), "the commercial ambition"),
      stat("Supply can make", units(summary.supply_units), "after capacity and fabric"),
      stat(
        "The gap",
        money(summary.gap_value),
        `${units(summary.gap_units)} units across ${summary.styles_short} styles`,
        summary.gap_units > 0 ? "bad" : "good",
      ),
      stat("Agreed", units(summary.consensus_units), "the number the business commits to"),
    ].join("");

    const chart = document.getElementById("recon-chart");
    chart.innerHTML = '<div class="chart-box"><canvas id="recon-canvas"></canvas></div>';
    lineChart(document.getElementById("recon-canvas"), {
      labels: body.by_week.map((row) => `wk ${row.week}`),
      series: [
        { label: "Merchandising", values: body.by_week.map((row) => row.merch_units) },
        { label: "Forecast", values: body.by_week.map((row) => row.forecast_units) },
        { label: "Supply", values: body.by_week.map((row) => row.supply_units) },
        { label: "Consensus", values: body.by_week.map((row) => row.consensus_units) },
      ],
    });

    createTable(document.getElementById("recon-gaps"), {
      columns: [
        { key: "name", label: "Style", format: (value) => truncate(value, 30) },
        { key: "category", label: "Category" },
        { key: "merch_units", label: "Wanted", numeric: true, format: units },
        { key: "supply_units", label: "Possible", numeric: true, format: units },
        { key: "gap_units", label: "Short by", numeric: true, format: units },
        { key: "gap_value", label: "Value", numeric: true, format: money },
      ],
      rows: body.biggest_gaps,
      pageSize: 10,
      searchable: false,
      emptyMessage: "Supply covers the plan in full.",
    });

    createTable(document.getElementById("recon-table"), {
      columns: [
        { key: "style_id", label: "Style" },
        { key: "week", label: "Week", numeric: true, ascendingFirst: true },
        { key: "merch_units", label: "Merchandising", numeric: true, format: units },
        { key: "forecast_units", label: "Forecast", numeric: true, format: units },
        { key: "supply_units", label: "Supply", numeric: true, format: units },
        { key: "consensus_units", label: "Consensus", numeric: true, format: units },
        { key: "consensus_source", label: "Set by" },
      ],
      rows: body.rows,
      pageSize: 20,
      sortKey: "gap_value",
      searchPlaceholder: "Search by style",
    });
  } catch (error) {
    for (const id of ["recon-stats", "recon-chart", "recon-gaps", "recon-table"]) {
      showError(document.getElementById(id), error);
    }
  }
}

load();
