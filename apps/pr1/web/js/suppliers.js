/**
 * The supplier comparison screen.
 *
 * The table a buyer works in: price, lead time, delivery record and predicted
 * risk for every approved supplier, sortable on any column.
 */

import { get } from "/shared/api.js";
import { days, humanise, pct, price, riskBand, truncate, units } from "/shared/format.js";
import { createTable } from "/shared/table.js";
import { renderRail } from "/js/shell.js";

renderRail("/pages/suppliers.html");

const mount = document.getElementById("supplier-table");
const summary = document.getElementById("filter-summary");
let table = null;

function riskCell(value, row) {
  if (value == null) return "—";
  const badge = document.createElement("span");
  badge.className = `badge badge--${riskBand(value)}`;
  badge.textContent = pct(value, 0);

  if (!row.has_measured_risk) {
    // Marked, not hidden. A buyer deciding on this number deserves to know it
    // is a population average rather than anything about this supplier.
    badge.textContent += " *";
    badge.title = "No trading history: this is the population average, not a prediction.";
  }
  return badge;
}

function leadCell(value, row) {
  if (value == null) return "—";
  const text = days(value);
  return row.lead_days_source === "supplier" ? text : `${text} *`;
}

const COLUMNS = [
  { key: "name", label: "Supplier", format: (value) => truncate(value, 40) },
  { key: "country", label: "Country", format: (value) => value ?? "—" },
  { key: "product_group", label: "Group", format: humanise },
  { key: "orders", label: "Orders", numeric: true, format: units },
  {
    key: "on_time_rate",
    label: "On time",
    numeric: true,
    format: (value) => pct(value),
    title: "Share of their recorded orders that arrived by the promised date",
  },
  {
    key: "avg_lead_days",
    label: "Lead time",
    numeric: true,
    render: leadCell,
    ascendingFirst: true,
    title: "Median promised lead time. An asterisk means it came from their product group.",
  },
  { key: "avg_unit_price", label: "Avg price", numeric: true, format: price, ascendingFirst: true },
  { key: "capacity_per_week", label: "Capacity", numeric: true, format: units },
  { key: "moq", label: "Min order", numeric: true, format: units },
  {
    key: "delay_probability",
    label: "Delay risk",
    numeric: true,
    render: riskCell,
    title: "Predicted probability this supplier delivers late",
  },
];

async function loadFilters() {
  const [materials, plants] = await Promise.all([get("/api/materials"), get("/api/plants")]);

  const materialSelect = document.getElementById("filter-material");
  for (const material of materials) {
    const option = document.createElement("option");
    option.value = material.material_id;
    option.textContent = truncate(material.material_id, 46);
    materialSelect.append(option);
  }

  const plantSelect = document.getElementById("filter-plant");
  for (const plant of plants) {
    const option = document.createElement("option");
    option.value = plant.plant_id;
    option.textContent = plant.name;
    plantSelect.append(option);
  }
}

async function load() {
  const params = {
    material_id: document.getElementById("filter-material").value,
    plant_id: document.getElementById("filter-plant").value,
    origin: document.getElementById("filter-origin").value,
    limit: 1000,
  };

  try {
    const body = await get("/api/suppliers", params);
    const real = body.rows.filter((row) => row.origin === "real").length;
    summary.textContent =
      `${body.total} suppliers · ${real} with a real trading record · ${body.total - real} generated`;

    if (table) {
      table.setRows(body.rows);
    } else {
      mount.innerHTML = "";
      table = createTable(mount, {
        columns: COLUMNS,
        rows: body.rows,
        pageSize: 25,
        sortKey: "on_time_rate",
        searchPlaceholder: "Search by supplier or country",
        emptyMessage: "No supplier is approved for that combination.",
        rowBadge: (row) => (row.origin === "synthetic" ? "Generated" : null),
      });
    }
  } catch (error) {
    mount.innerHTML = `<div class="error">${error.message}</div>`;
  }
}

for (const id of ["filter-material", "filter-plant", "filter-origin"]) {
  document.getElementById(id).addEventListener("change", load);
}

loadFilters().then(load);
