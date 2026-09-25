/**
 * A sortable, filterable, paginated table. About 150 lines, written here rather
 * than pulled from a library.
 *
 * That is a deliberate trade. A third-party grid would have more features, but
 * every member of the team has to be able to read and defend the front end on
 * 30 September, and you cannot defend code you have never opened.
 *
 * Usage:
 *
 *   const table = createTable(element, {
 *     columns: [
 *       { key: "name", label: "Supplier" },
 *       { key: "on_time_rate", label: "On time", numeric: true, format: pct },
 *     ],
 *     rows,
 *     pageSize: 25,
 *     rowBadge: (row) => (row.origin === "synthetic" ? "Generated" : null),
 *   });
 *
 *   table.setRows(nextRows);
 */

const DEFAULTS = {
  pageSize: 25,
  searchable: true,
  searchPlaceholder: "Search",
  emptyMessage: "Nothing to show yet.",
};

export function createTable(mount, options) {
  const config = { ...DEFAULTS, ...options };
  const state = {
    rows: config.rows ?? [],
    filter: "",
    sortKey: config.sortKey ?? null,
    sortAscending: config.sortAscending ?? false,
    page: 0,
  };

  mount.innerHTML = "";
  mount.classList.add("table-host");

  let toolbar = null;
  let search = null;
  if (config.searchable) {
    toolbar = document.createElement("div");
    toolbar.className = "table-toolbar";
    search = document.createElement("input");
    search.type = "search";
    search.placeholder = config.searchPlaceholder;
    search.setAttribute("aria-label", config.searchPlaceholder);
    search.addEventListener("input", () => {
      state.filter = search.value.trim().toLowerCase();
      state.page = 0;
      render();
    });
    toolbar.append(search);
    mount.append(toolbar);
  }

  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const table = document.createElement("table");
  table.className = "data";
  const thead = document.createElement("thead");
  const tbody = document.createElement("tbody");
  table.append(thead, tbody);
  wrap.append(table);
  mount.append(wrap);

  const foot = document.createElement("div");
  foot.className = "table-foot";
  const count = document.createElement("span");
  const pager = document.createElement("div");
  pager.className = "pager";
  const previous = document.createElement("button");
  previous.type = "button";
  previous.textContent = "Previous";
  const next = document.createElement("button");
  next.type = "button";
  next.textContent = "Next";
  const position = document.createElement("span");
  position.className = "num";
  pager.append(previous, position, next);
  foot.append(count, pager);
  mount.append(foot);

  previous.addEventListener("click", () => {
    state.page = Math.max(0, state.page - 1);
    render();
  });
  next.addEventListener("click", () => {
    state.page += 1;
    render();
  });

  function matches(row) {
    if (!state.filter) return true;
    return config.columns.some((column) => {
      const value = row[column.key];
      return value != null && String(value).toLowerCase().includes(state.filter);
    });
  }

  function visibleRows() {
    const filtered = state.rows.filter(matches);
    if (!state.sortKey) return filtered;

    const direction = state.sortAscending ? 1 : -1;
    return [...filtered].sort((left, right) => {
      const a = left[state.sortKey];
      const b = right[state.sortKey];
      // Missing values sort last whichever way the column is pointing: a
      // supplier with no on-time rate should never top the reliability table.
      if (a == null && b == null) return 0;
      if (a == null) return 1;
      if (b == null) return -1;
      if (typeof a === "number" && typeof b === "number") return (a - b) * direction;
      return String(a).localeCompare(String(b)) * direction;
    });
  }

  function renderHead() {
    thead.innerHTML = "";
    const row = document.createElement("tr");

    for (const column of config.columns) {
      const cell = document.createElement("th");
      cell.textContent = column.label;
      if (column.numeric) cell.classList.add("numeric");
      if (column.title) cell.title = column.title;

      if (column.sortable !== false) {
        cell.dataset.sortable = "true";
        cell.tabIndex = 0;
        if (state.sortKey === column.key) {
          cell.setAttribute("aria-sort", state.sortAscending ? "ascending" : "descending");
          const arrow = document.createElement("span");
          arrow.className = "sort-arrow";
          arrow.textContent = state.sortAscending ? "↑" : "↓";
          cell.append(arrow);
        }
        const sort = () => {
          if (state.sortKey === column.key) {
            state.sortAscending = !state.sortAscending;
          } else {
            state.sortKey = column.key;
            // First click opens a numeric column best-first (descending) and a
            // text column A–Z. Clicking "On time" and seeing the worst supplier
            // at the top would be the wrong answer to the question being asked.
            state.sortAscending = column.ascendingFirst ?? !column.numeric;
          }
          state.page = 0;
          render();
        };
        cell.addEventListener("click", sort);
        cell.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            sort();
          }
        });
      }
      row.append(cell);
    }
    thead.append(row);
  }

  function renderBody(rows) {
    tbody.innerHTML = "";

    if (rows.length === 0) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = config.columns.length;
      cell.className = "empty";
      cell.textContent = state.filter
        ? `No rows match “${search.value}”.`
        : config.emptyMessage;
      row.append(cell);
      tbody.append(row);
      return;
    }

    for (const record of rows) {
      const row = document.createElement("tr");
      if (config.rowKey) row.dataset.key = config.rowKey(record);

      for (const [index, column] of config.columns.entries()) {
        const cell = document.createElement("td");
        const value = record[column.key];

        if (column.render) {
          const rendered = column.render(value, record);
          if (rendered instanceof Node) cell.append(rendered);
          else cell.innerHTML = rendered ?? "";
        } else {
          cell.textContent = column.format ? column.format(value, record) : (value ?? "—");
        }

        if (column.numeric) cell.classList.add("numeric", "num");

        // The origin badge rides on the first column, so a generated row is
        // obvious wherever the table is sorted.
        if (index === 0 && config.rowBadge) {
          const label = config.rowBadge(record);
          if (label) {
            const badge = document.createElement("span");
            badge.className = "badge badge--generated";
            badge.textContent = label;
            badge.style.marginLeft = "8px";
            cell.append(badge);
          }
        }
        row.append(cell);
      }

      if (config.onRowClick) {
        row.style.cursor = "pointer";
        row.addEventListener("click", () => config.onRowClick(record));
      }
      tbody.append(row);
    }
  }

  function render() {
    const rows = visibleRows();
    const pages = Math.max(1, Math.ceil(rows.length / config.pageSize));
    state.page = Math.min(state.page, pages - 1);

    const start = state.page * config.pageSize;
    renderHead();
    renderBody(rows.slice(start, start + config.pageSize));

    const shown = Math.min(rows.length, start + config.pageSize);
    count.textContent = rows.length
      ? `${start + 1}–${shown} of ${rows.length.toLocaleString()}`
      : "No rows";
    position.textContent = `${state.page + 1} / ${pages}`;
    previous.disabled = state.page === 0;
    next.disabled = state.page >= pages - 1;
    foot.style.display = rows.length > config.pageSize ? "" : "";
  }

  render();

  return {
    setRows(rows) {
      state.rows = rows ?? [];
      state.page = 0;
      render();
    },
    getState() {
      return { ...state };
    },
    destroy() {
      mount.innerHTML = "";
    },
  };
}
