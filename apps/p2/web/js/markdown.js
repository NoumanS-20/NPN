/**
 * The markdown view: which styles to discount, when, and by how much.
 */

import { get } from "/shared/api.js";
import { money, pct, truncate } from "/shared/format.js";
import { createTable } from "/shared/table.js";
import { renderRail, showError, stat } from "/js/shell.js";

renderRail("/pages/markdown.html");

async function load() {
  try {
    const body = await get("/api/markdown");
    const summary = body.summary;
    const elasticity = body.elasticity;

    document.getElementById("md-stats").innerHTML = [
      stat("Styles to mark down", `${summary.marked_down}`, `of ${summary.styles} in the range`),
      stat("Left alone", `${summary.styles_on_track}`, "tracking to clear without a discount"),
      stat(
        "Median depth",
        pct(summary.median_depth ?? 0, 0),
        `starting week ${summary.median_week ?? 0}`,
      ),
      stat(
        "Revenue recovered",
        money(summary.margin_recovered ?? 0),
        "against leaving prices alone",
      ),
    ].join("");

    const measured = elasticity.source === "measured";
    document.getElementById("md-elasticity").innerHTML = `
      <div class="${measured ? "" : "note"}" style="margin-bottom: var(--space-4)">
        <strong>${measured ? "Measured from the data" : "Assumed, and labelled as such"}:</strong>
        elasticity ${elasticity.value}. ${elasticity.reason}
      </div>
      <p class="small muted" style="margin:0">
        At this elasticity a 20% discount sells about 1.5 times the units and a 40% discount about
        2.4 times. Because the season's stock is already bought, the decision is priced on revenue
        realised rather than margin: full price now, a discount later, or salvage at the end.
      </p>`;

    createTable(document.getElementById("md-table"), {
      columns: [
        { key: "name", label: "Style", format: (value) => truncate(value, 26) },
        { key: "category", label: "Category" },
        {
          key: "recommend",
          label: "Action",
          render: (value, row) => {
            const badge = document.createElement("span");
            badge.className = value ? "badge badge--medium" : "badge badge--positive";
            badge.textContent = value
              ? `${(row.depth_pct * 100).toFixed(0)}% from wk ${row.week}`
              : "Leave alone";
            return badge;
          },
        },
        {
          key: "projected_sell_through",
          label: "Projected",
          numeric: true,
          format: (value) => pct(value, 0),
        },
        {
          key: "target_sell_through",
          label: "Target",
          numeric: true,
          format: (value) => pct(value, 0),
        },
        {
          key: "projected_with_markdown",
          label: "With markdown",
          numeric: true,
          format: (value) => pct(value, 0),
        },
        { key: "margin_recovered", label: "Revenue gained", numeric: true, format: money },
        { key: "reason", label: "Why", sortable: false },
      ],
      rows: body.rows,
      pageSize: 20,
      sortKey: "margin_recovered",
      searchPlaceholder: "Search styles",
    });
  } catch (error) {
    for (const id of ["md-stats", "md-elasticity", "md-table"]) {
      showError(document.getElementById(id), error);
    }
  }
}

load();
