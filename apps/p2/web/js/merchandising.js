/**
 * The merchandising view: the catalogue and where revenue comes from.
 */

import { get } from "/shared/api.js";
import { barChart } from "/shared/chart.js";
import { money, pct, price, units } from "/shared/format.js";
import { createTable } from "/shared/table.js";
import { renderRail, showError, stat } from "/js/shell.js";

renderRail("/pages/merchandising.html");

async function load() {
  try {
    const [styles, financials, models] = await Promise.all([
      get("/api/styles", { limit: 1000 }),
      get("/api/financials"),
      get("/api/models/metrics"),
    ]);

    const forecast = models.forecast;
    const cold = models.cold_start;

    document.getElementById("merch-stats").innerHTML = [
      stat("Styles", `${styles.total}`, "20 real, the rest generated for the calendar"),
      stat(
        "Revenue",
        money(financials.totals.revenue),
        `${pct(financials.totals.margin_pct)} gross margin`,
      ),
      stat(
        "Forecast error",
        pct(forecast.wape),
        `WAPE on real styles · seasonal naive is ${pct(forecast.wape_seasonal_naive)}`,
        forecast.wape < forecast.wape_seasonal_naive ? "good" : "bad",
      ),
      stat(
        "New-style forecast",
        cold.scored ? pct(cold.results.analog.wape) : "—",
        cold.scored
          ? `held out ${cold.held_out_name} and forecast it from nothing`
          : "not scored",
        cold.analog_beats_baseline ? "good" : "bad",
      ),
    ].join("");

    const chart = document.getElementById("merch-chart");
    chart.innerHTML = '<div class="chart-box"><canvas id="merch-canvas"></canvas></div>';
    barChart(document.getElementById("merch-canvas"), {
      labels: financials.by_category.map((row) => row.category),
      values: financials.by_category.map((row) => row.revenue),
      label: "Revenue",
    });

    createTable(document.getElementById("merch-table"), {
      columns: [
        { key: "name", label: "Style" },
        { key: "category", label: "Category" },
        { key: "season", label: "Season" },
        { key: "launch_week", label: "Launch", numeric: true, ascendingFirst: true },
        { key: "price", label: "Price", numeric: true, format: price },
        { key: "margin_pct", label: "Margin", numeric: true, format: (value) => pct(value) },
        { key: "forecast_units", label: "13-wk forecast", numeric: true, format: units },
        {
          key: "markdown_recommended",
          label: "Markdown",
          format: (value, row) => (value ? `week ${row.markdown_week}` : "—"),
        },
      ],
      rows: styles.rows,
      pageSize: 20,
      sortKey: "forecast_units",
      searchPlaceholder: "Search styles",
      rowBadge: (row) => (row.origin === "synthetic" ? "Generated" : null),
    });
  } catch (error) {
    for (const id of ["merch-stats", "merch-chart", "merch-table"]) {
      showError(document.getElementById(id), error);
    }
  }
}

load();
