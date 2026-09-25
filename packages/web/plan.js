/**
 * Turning an allocation response into what the screens draw.
 *
 * The page scripts do DOM work; the decisions about how a plan is grouped,
 * totalled and described live here, where they can be tested without a browser.
 */

import { pct, units } from "./format.js";

/**
 * Group allocation lines by the requirement they serve.
 *
 * One bar is drawn per requirement, so the grouping key has to be the full
 * requirement — material, plant and week. Grouping by material alone would merge
 * three plants into one bar and quietly overstate how concentrated a supplier is.
 */
export function groupByRequirement(lines) {
  const groups = new Map();
  for (const line of lines ?? []) {
    const key = `${line.material_id}||${line.plant_id}||${line.week}`;
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        material_id: line.material_id,
        plant_id: line.plant_id,
        week: line.week,
        lines: [],
        qty: 0,
      });
    }
    const group = groups.get(key);
    group.lines.push(line);
    group.qty += line.qty;
  }
  return [...groups.values()].sort((a, b) => b.qty - a.qty);
}

/** Headline totals for a plan. */
export function planTotals(plan) {
  const lines = plan?.lines ?? [];
  const qty = lines.reduce((sum, line) => sum + line.qty, 0);
  const suppliers = new Set(lines.map((line) => line.supplier_id));
  const generated = lines.filter((line) => line.origin === "synthetic");

  return {
    units: qty,
    lines: lines.length,
    suppliers: suppliers.size,
    generatedShare: qty ? generated.reduce((sum, line) => sum + line.qty, 0) / qty : 0,
    invoice: plan?.material_cost ?? 0,
    totalCost: plan?.total_cost ?? 0,
    expectedLate: plan?.expected_late_units ?? 0,
    highRiskShare: plan?.high_risk_share ?? 0,
  };
}

/**
 * The rows of the "versus the alternatives" panel.
 *
 * Every metric carries whether lower is better, because on this comparison a
 * negative invoice delta is good news and a negative supplier count is not
 * obviously either — so the caller should never have to guess.
 */
export function comparisonRows(comparison) {
  const order = ["historical_mix", "equal_split", "cheapest_first"];
  const labels = {
    historical_mix: "Last year's buying",
    equal_split: "Equal split",
    cheapest_first: "Cheapest first",
  };

  return order
    .filter((key) => comparison?.[key])
    .map((key) => {
      const metrics = comparison[key];
      return {
        key,
        label: labels[key],
        metrics: [
          { label: "Invoice", value: metrics.invoice_delta_pct, good: metrics.invoice_delta_pct <= 0 },
          {
            label: "Total cost",
            value: metrics.total_cost_delta_pct,
            good: metrics.total_cost_delta_pct <= 0,
          },
          {
            label: "Expected late",
            value: metrics.expected_late_delta_pct,
            good: metrics.expected_late_delta_pct <= 0,
          },
        ],
        highRiskDelta: metrics.high_risk_delta_pp,
      };
    });
}

/**
 * A sentence describing what a change of weights did.
 *
 * Shown above the plan after a re-solve, because a panel watching bars shift
 * needs to be told what they are looking at — the shift is the point, but the
 * numbers are the evidence.
 */
export function describeChange(before, after) {
  if (!before || !after?.lines?.length) return "";

  const costDelta = before.material_cost
    ? ((after.material_cost - before.material_cost) / before.material_cost) * 100
    : 0;
  const lateDelta = before.expected_late_units
    ? ((after.expected_late_units - before.expected_late_units) / before.expected_late_units) * 100
    : 0;

  if (Math.abs(costDelta) < 0.05 && Math.abs(lateDelta) < 0.05) {
    return "Same plan: nothing in the weighting changed the answer.";
  }

  const cost = `${costDelta >= 0 ? "+" : ""}${costDelta.toFixed(1)}% on the invoice`;
  const late = `${lateDelta >= 0 ? "+" : ""}${lateDelta.toFixed(1)}% expected late units`;
  return `${cost}, ${late}.`;
}

/** How concentrated a plan is: the largest supplier's share of all volume. */
export function concentration(lines) {
  const total = (lines ?? []).reduce((sum, line) => sum + line.qty, 0);
  if (!total) return { share: 0, supplier: null };

  const bySupplier = new Map();
  for (const line of lines) {
    bySupplier.set(line.supplier_id, (bySupplier.get(line.supplier_id) ?? 0) + line.qty);
  }

  let supplier = null;
  let largest = 0;
  for (const [id, qty] of bySupplier) {
    if (qty > largest) {
      largest = qty;
      supplier = id;
    }
  }
  return { share: largest / total, supplier, units: largest };
}

/** A short label for a requirement, used above each split bar. */
export function requirementLabel(group) {
  return `${group.material_id} · ${group.plant_id.replace("plant-", "")} · week ${group.week}`;
}

/**
 * The right-hand caption for a requirement.
 *
 * The week is first because a plan covering several weeks draws one bar per
 * week, and two identical-looking bars for the same material read as a bug
 * until you can see which week each belongs to.
 */
export function requirementMeta(group) {
  const suppliers = new Set(group.lines.map((line) => line.supplier_id)).size;
  const largest = concentration(group.lines);
  return `Week ${group.week} · ${units(group.qty)} units · ${suppliers} suppliers · ` +
    `largest ${pct(largest.share, 0)}`;
}
