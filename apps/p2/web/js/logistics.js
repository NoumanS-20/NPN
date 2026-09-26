/**
 * The logistics view: lanes, transit times, and when stock reaches a shop floor.
 */

import { get } from "/shared/api.js";
import { barChart } from "/shared/chart.js";
import { days, money, units } from "/shared/format.js";
import { createTable } from "/shared/table.js";
import { renderRail, showError, stat } from "/js/shell.js";

renderRail("/pages/logistics.html");

async function load() {
  try {
    const body = await get("/api/logistics");
    const summary = body.summary;

    document.getElementById("log-stats").innerHTML = [
      stat("Units moving", units(summary.units ?? 0), `${summary.stores ?? 0} stores`),
      stat(
        "Distribution cost",
        money(summary.distribution_cost ?? 0),
        "to move everything the plants make — the cockpit costs the committed plan, which is smaller",
      ),
      stat("Average transit", days(summary.mean_transit_days ?? 0), "warehouse to shop floor"),
      stat("Slowest lane", days(summary.slowest_lane_days ?? 0), "the one that sets the date"),
    ].join("");

    createTable(document.getElementById("log-lanes"), {
      columns: [
        { key: "dc_id", label: "Warehouse" },
        { key: "store_id", label: "Store" },
        { key: "mode", label: "Mode" },
        {
          key: "transit_days",
          label: "Transit",
          numeric: true,
          format: days,
          ascendingFirst: true,
        },
        {
          key: "cost_per_unit",
          label: "Cost per unit",
          numeric: true,
          format: (value) => value.toFixed(2),
        },
      ],
      rows: body.lanes,
      pageSize: 10,
      searchable: false,
    });

    const byWeek = {};
    for (const row of body.by_store) {
      byWeek[row.week_available] = (byWeek[row.week_available] ?? 0) + row.units;
    }
    const weeks = Object.keys(byWeek).sort((a, b) => a - b);

    const chart = document.getElementById("log-chart");
    chart.innerHTML = '<div class="chart-box"><canvas id="log-canvas"></canvas></div>';
    barChart(document.getElementById("log-canvas"), {
      labels: weeks.map((week) => `wk ${week}`),
      values: weeks.map((week) => Math.round(byWeek[week])),
      label: "Units reaching stores",
    });
  } catch (error) {
    for (const id of ["log-stats", "log-lanes", "log-chart"]) {
      showError(document.getElementById(id), error);
    }
  }
}

load();
