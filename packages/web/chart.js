/**
 * Charts, and the allocation split bar.
 *
 * Chart.js handles lines and bars from a local copy — no CDN, because the demo
 * may run without a network. Everything reads its colours from the CSS tokens,
 * so light and dark come free.
 *
 * The split bar is ours. It is the one piece of visual design that carries the
 * argument of the project: each segment is a supplier, its width is their share
 * of the requirement, and its colour is their delay risk. When the planner moves
 * the risk slider, the segments re-flow — you watch volume move off the
 * unreliable suppliers instead of reading that it did.
 */

import { pct, riskBand, truncate, units } from "./format.js";

function token(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function baseOptions() {
  const ink = token("--ink-muted");
  const line = token("--line");
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 220 },
    plugins: {
      legend: {
        labels: { color: ink, boxWidth: 10, boxHeight: 10, font: { size: 11 } },
      },
      tooltip: {
        backgroundColor: token("--ink"),
        titleFont: { size: 12 },
        bodyFont: { size: 12 },
        padding: 10,
        displayColors: false,
      },
    },
    scales: {
      x: { grid: { display: false }, ticks: { color: ink, font: { size: 11 } } },
      y: {
        grid: { color: line, drawBorder: false },
        ticks: { color: ink, font: { size: 11 } },
      },
    },
  };
}

function build(canvas, type, data, extra = {}) {
  if (!window.Chart) {
    canvas.replaceWith(
      Object.assign(document.createElement("div"), {
        className: "empty",
        textContent: "Charts need chart.min.js, which did not load.",
      }),
    );
    return null;
  }
  const existing = window.Chart.getChart(canvas);
  if (existing) existing.destroy();

  const options = baseOptions();
  return new window.Chart(canvas, {
    type,
    data,
    options: { ...options, ...extra, plugins: { ...options.plugins, ...(extra.plugins ?? {}) } },
  });
}

export function barChart(canvas, { labels, values, label = "", color }) {
  return build(canvas, "bar", {
    labels,
    datasets: [
      {
        label,
        data: values,
        backgroundColor: color ?? token("--accent"),
        borderRadius: 3,
        maxBarThickness: 34,
      },
    ],
  });
}

export function groupedBarChart(canvas, { labels, series }) {
  const palette = [token("--accent"), token("--risk-medium"), token("--risk-low")];
  return build(canvas, "bar", {
    labels,
    datasets: series.map((entry, index) => ({
      label: entry.label,
      data: entry.values,
      backgroundColor: entry.color ?? palette[index % palette.length],
      borderRadius: 3,
      maxBarThickness: 28,
    })),
  });
}

export function lineChart(canvas, { labels, series }) {
  const palette = [token("--accent"), token("--risk-medium"), token("--risk-low")];
  return build(canvas, "line", {
    labels,
    datasets: series.map((entry, index) => ({
      label: entry.label,
      data: entry.values,
      borderColor: entry.color ?? palette[index % palette.length],
      backgroundColor: "transparent",
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4,
      tension: 0.25,
    })),
  });
}

/**
 * Render an allocation as one bar per requirement.
 *
 * `lines` is the API's allocation lines. Segments are sorted largest first so
 * the eye lands on who carries the plan.
 */
export function splitBar(mount, lines, { showLabels = true } = {}) {
  mount.innerHTML = "";
  if (!lines || lines.length === 0) {
    mount.innerHTML = '<div class="empty">No allocation yet.</div>';
    return;
  }

  const total = lines.reduce((sum, line) => sum + line.qty, 0);
  const bar = document.createElement("div");
  bar.className = "split";
  bar.setAttribute("role", "img");
  bar.setAttribute(
    "aria-label",
    `Allocation across ${lines.length} suppliers, ${units(total)} units`,
  );

  for (const line of [...lines].sort((a, b) => b.qty - a.qty)) {
    const share = total ? line.qty / total : 0;
    const segment = document.createElement("div");
    segment.className = "split__seg";
    segment.style.flexGrow = String(Math.max(share, 0.004));
    segment.style.flexBasis = "0";
    segment.dataset.risk = riskBand(line.delay_probability);
    segment.dataset.origin = line.origin ?? "real";
    segment.title =
      `${line.supplier_name}\n` +
      `${units(line.qty)} units (${pct(share, 0)})\n` +
      `Delay risk ${pct(line.delay_probability, 0)} · ${line.unit_price} per unit\n` +
      line.reason;

    if (showLabels && share > 0.08) {
      segment.textContent = pct(share, 0);
    }
    bar.append(segment);
  }

  mount.append(bar);

  const legend = document.createElement("div");
  legend.className = "split-legend";
  legend.innerHTML = `
    <span><i class="swatch swatch--low"></i> Delay risk under 25%</span>
    <span><i class="swatch swatch--medium"></i> 25–40%</span>
    <span><i class="swatch swatch--high"></i> Over 40%</span>
    <span><i class="swatch swatch--low" style="background-image:repeating-linear-gradient(135deg,rgba(255,255,255,.4) 0 4px,transparent 4px 8px)"></i> Generated supplier</span>
  `;
  mount.append(legend);
}

/** A compact supplier list under a split bar. */
export function splitDetail(mount, lines, limit = 6) {
  mount.innerHTML = "";
  const total = lines.reduce((sum, line) => sum + line.qty, 0);
  const list = document.createElement("div");
  list.className = "split-detail";

  for (const line of [...lines].sort((a, b) => b.qty - a.qty).slice(0, limit)) {
    const row = document.createElement("div");
    row.className = "split-detail__row";
    row.innerHTML = `
      <span class="swatch swatch--${riskBand(line.delay_probability)}"></span>
      <span class="split-detail__name">${truncate(line.supplier_name, 46)}</span>
      <span class="num muted">${pct(total ? line.qty / total : 0, 0)}</span>
      <span class="num">${units(line.qty)}</span>
    `;
    list.append(row);
  }
  mount.append(list);
}
