/**
 * The reconciliation screen — the heart of the S&OP cycle.
 */

import { escapeHtml, get, post } from "/shared/api.js";
import { lineChart } from "/shared/chart.js";
import { money, truncate, units } from "/shared/format.js";
import { createTable } from "/shared/table.js";
import { renderRail, showError, stat } from "/js/shell.js";

renderRail("/pages/reconcile.html");

// Agreeing a number reloads the screen so every panel reflects it. That reload
// rebuilds this form, so the confirmation has to survive it — otherwise the one
// moment the screen exists to show flashes past and is gone.
let lastAgreed = null;

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
    renderOverride(body);
  } catch (error) {
    for (const id of ["recon-stats", "recon-override", "recon-chart", "recon-gaps", "recon-table"]) {
      showError(document.getElementById(id), error);
    }
  }
}

/**
 * Agree a number by hand, the way Pre-S&OP would.
 *
 * The rule this exists to demonstrate: a meeting can commit to less than the
 * plants can make, never more. Type a number above supply and the server caps
 * it and says so — the cap lives in the API, not in this form, so it holds
 * however the endpoint is called.
 */
function renderOverride(body) {
  const mount = document.getElementById("recon-override");
  const rows = body.rows ?? [];
  if (!rows.length) {
    mount.innerHTML = '<p class="small muted">Nothing to agree yet.</p>';
    return;
  }

  // Open on the largest shortfall that still has supply to cap against. A row
  // where supply is zero caps every number to zero, which demonstrates nothing.
  const candidates = rows.filter((row) => row.supply_units > 0 && row.gap_units > 0);
  const biggest = [...(candidates.length ? candidates : rows)]
    .sort((a, b) => (b.gap_value ?? 0) - (a.gap_value ?? 0))[0];
  const shortest = lastAgreed
    ? rows.find((r) => r.style_id === lastAgreed.style_id && r.week === lastAgreed.week) ?? biggest
    : biggest;

  // The table of biggest gaps carries the readable names; the row feed does not.
  const names = new Map((body.biggest_gaps ?? []).map((row) => [row.style_id, row.name]));
  const label = (id) => (names.has(id) ? `${id} — ${names.get(id)}` : id);
  const styles = [...new Set(rows.map((row) => row.style_id))].sort();

  mount.innerHTML = `
    <div class="controls">
      <label class="field">
        <span class="field__label">Style</span>
        <select id="ov-style">
          ${styles.map((id) => `<option value="${escapeHtml(id)}"${
            id === shortest.style_id ? " selected" : ""
          }>${escapeHtml(label(id))}</option>`).join("")}
        </select>
      </label>
      <label class="field">
        <span class="field__label">Week</span>
        <select id="ov-week"></select>
      </label>
      <label class="field">
        <span class="field__label">
          <span>Units to commit</span>
          <span class="field__value" id="ov-supply"></span>
        </span>
        <input type="number" id="ov-units" min="0" step="1">
      </label>
      <label class="field">
        <span class="field__label">&nbsp;</span>
        <button type="button" class="primary" id="ov-apply">Agree this number</button>
      </label>
    </div>
    <p class="small muted" id="ov-result" style="margin-top: var(--space-4)"></p>`;

  const styleSelect = document.getElementById("ov-style");
  const weekSelect = document.getElementById("ov-week");
  const unitsInput = document.getElementById("ov-units");
  const supplyNote = document.getElementById("ov-supply");
  const result = document.getElementById("ov-result");

  const rowsFor = (styleId) =>
    rows.filter((row) => row.style_id === styleId).sort((a, b) => a.week - b.week);

  function fillWeeks() {
    const mine = rowsFor(styleSelect.value);
    weekSelect.innerHTML = mine
      .map((row) => `<option value="${row.week}">week ${row.week}</option>`)
      .join("");
    if (styleSelect.value === shortest.style_id) weekSelect.value = String(shortest.week);
    fillUnits();
  }

  function current() {
    return rowsFor(styleSelect.value).find((row) => String(row.week) === weekSelect.value);
  }

  function fillUnits() {
    const row = current();
    if (!row) return;
    supplyNote.textContent = `supply can make ${units(row.supply_units)}`;
    unitsInput.value = Math.round(row.consensus_units);
  }

  function clearResult() {
    lastAgreed = null;
    result.textContent = "";
    result.className = "small muted";
  }

  if (lastAgreed) {
    result.className = lastAgreed.capped ? "small bad" : "small good";
    result.textContent = lastAgreed.message;
  }

  styleSelect.addEventListener("change", () => { clearResult(); fillWeeks(); });
  weekSelect.addEventListener("change", () => { clearResult(); fillUnits(); });

  document.getElementById("ov-apply").addEventListener("click", async () => {
    const row = current();
    if (!row) return;
    const wanted = Number(unitsInput.value);
    const query = new URLSearchParams({
      style_id: styleSelect.value,
      week: weekSelect.value,
      units: String(wanted),
    });
    result.textContent = "Agreeing…";
    try {
      const out = await post(`/api/reconciliation/consensus?${query}`);
      const capped = out.consensus_source.includes("capped");
      lastAgreed = {
        style_id: out.style_id,
        week: out.week,
        capped,
        message: capped
          ? `Capped at ${units(out.consensus_units)} — supply can only make that much. `
            + `You asked for ${units(wanted)}. A meeting can commit to less than the plants `
            + `can make, never more.`
          : `Agreed ${units(out.consensus_units)} for ${out.style_id} in week ${out.week}.`,
      };
      await load();
    } catch (error) {
      result.className = "small bad";
      result.textContent = error.message;
    }
  });

  fillWeeks();
}

load();
