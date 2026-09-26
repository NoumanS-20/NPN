/**
 * The production view: capacity, shortfalls, and the fabric that must be ordered.
 */

import { get } from "/shared/api.js";
import { barChart } from "/shared/chart.js";
import { money, pct, units } from "/shared/format.js";
import { createTable } from "/shared/table.js";
import { renderRail, showError, stat } from "/js/shell.js";

renderRail("/pages/production.html");

async function load() {
  try {
    const [production, fabric] = await Promise.all([get("/api/production"), get("/api/fabric")]);
    const summary = production.summary;

    document.getElementById("prod-stats").innerHTML = [
      stat("Units planned", units(summary.units_planned), `${summary.styles} styles`),
      stat(
        "Peak capacity use",
        pct(summary.peak_utilisation),
        `${summary.weeks_at_capacity} plant-weeks at the limit`,
        summary.peak_utilisation > 0.98 ? "bad" : "good",
      ),
      stat(
        "Demand not met",
        units(summary.shortfall_units),
        summary.shortfall_units > 0
          ? `${money(summary.shortfall_value)} of margin`
          : "capacity and fabric cover the plan",
        summary.shortfall_units > 0 ? "bad" : "good",
      ),
      stat(
        "Fabric to order",
        `${units(fabric.summary.metres)} m`,
        `${money(fabric.summary.cost)} · ${fabric.summary.orders_already_due} already due`,
      ),
    ].join("");

    // Utilisation is averaged across the three plants for the week view.
    const byWeek = {};
    const plantCount = new Set(production.capacity_use.map((row) => row.plant_id)).size || 1;
    for (const row of production.capacity_use) {
      byWeek[row.week] = (byWeek[row.week] ?? 0) + row.utilisation / plantCount;
    }
    const weeks = Object.keys(byWeek).sort((a, b) => a - b);

    const chart = document.getElementById("prod-chart");
    chart.innerHTML = '<div class="chart-box"><canvas id="prod-canvas"></canvas></div>';
    barChart(document.getElementById("prod-canvas"), {
      labels: weeks.map((week) => `wk ${week}`),
      values: weeks.map((week) => Math.round(byWeek[week] * 100)),
      label: "Capacity used (%)",
    });

    createTable(document.getElementById("prod-shortfalls"), {
      columns: [
        { key: "style_id", label: "Style" },
        { key: "week", label: "Week", numeric: true, ascendingFirst: true },
        { key: "demand", label: "Wanted", numeric: true, format: units },
        { key: "units_short", label: "Short by", numeric: true, format: units },
        { key: "margin_lost", label: "Margin lost", numeric: true, format: money },
      ],
      rows: production.shortfalls,
      pageSize: 10,
      searchable: false,
      emptyMessage: "Capacity and fabric cover the plan in full.",
    });

    createTable(document.getElementById("fabric-table"), {
      columns: [
        { key: "fabric_id", label: "Fabric" },
        { key: "order_week", label: "Order in week", numeric: true, ascendingFirst: true },
        { key: "arrival_week", label: "Arrives", numeric: true, ascendingFirst: true },
        { key: "metres", label: "Metres", numeric: true, format: units },
        { key: "cost", label: "Cost", numeric: true, format: money },
      ],
      rows: fabric.orders,
      pageSize: 15,
      sortKey: "order_week",
      sortAscending: true,
      searchPlaceholder: "Search fabrics",
    });
  } catch (error) {
    for (const id of ["prod-stats", "prod-chart", "prod-shortfalls", "fabric-table"]) {
      showError(document.getElementById(id), error);
    }
  }
}

load();
