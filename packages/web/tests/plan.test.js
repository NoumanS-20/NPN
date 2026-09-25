/**
 * How an allocation response becomes what the screens draw.
 *
 * These are pure functions, so they are tested without a browser. The grouping
 * test in particular guards a mistake that would have been easy to miss by eye:
 * merging plants into one bar makes a supplier look less concentrated than it is.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  comparisonRows,
  concentration,
  describeChange,
  groupByRequirement,
  planTotals,
  requirementMeta,
} from "../plan.js";

const LINES = [
  { supplier_id: "a", material_id: "M1", plant_id: "plant-x", week: 1, qty: 600, origin: "real" },
  { supplier_id: "b", material_id: "M1", plant_id: "plant-x", week: 1, qty: 400, origin: "synthetic" },
  { supplier_id: "a", material_id: "M1", plant_id: "plant-y", week: 1, qty: 900, origin: "real" },
  { supplier_id: "c", material_id: "M2", plant_id: "plant-x", week: 2, qty: 200, origin: "real" },
];

test("lines group by material, plant and week together", () => {
  const groups = groupByRequirement(LINES);
  assert.equal(groups.length, 3, "the same material at two plants is two requirements");
  assert.equal(groups[0].qty, 1000, "groups are ordered by volume, largest first");
});

test("grouping by material alone would understate concentration", () => {
  const groups = groupByRequirement(LINES);
  const plantX = groups.find((g) => g.plant_id === "plant-x" && g.material_id === "M1");
  const plantY = groups.find((g) => g.plant_id === "plant-y");

  assert.equal(concentration(plantX.lines).share, 0.6);
  assert.equal(concentration(plantY.lines).share, 1, "one supplier serves that plant entirely");
});

test("an empty plan groups into nothing rather than throwing", () => {
  assert.deepEqual(groupByRequirement([]), []);
  assert.deepEqual(groupByRequirement(undefined), []);
});

test("totals report the generated share of volume", () => {
  const totals = planTotals({ lines: LINES, material_cost: 1000, total_cost: 1800 });
  assert.equal(totals.units, 2100);
  assert.equal(totals.suppliers, 3);
  assert.ok(Math.abs(totals.generatedShare - 400 / 2100) < 1e-9);
});

test("concentration names the supplier carrying the most volume", () => {
  const result = concentration(LINES);
  assert.equal(result.supplier, "a");
  assert.equal(result.units, 1500);
});

test("concentration of an empty plan is zero, not a division by zero", () => {
  assert.deepEqual(concentration([]), { share: 0, supplier: null });
});

test("comparison rows are ordered with the status quo first", () => {
  const rows = comparisonRows({
    cheapest_first: { invoice_delta_pct: 1.8, total_cost_delta_pct: 0.6, expected_late_delta_pct: -3.3, high_risk_delta_pp: -2.4 },
    equal_split: { invoice_delta_pct: -14.3, total_cost_delta_pct: -14.6, expected_late_delta_pct: -2.7, high_risk_delta_pp: -4.2 },
    historical_mix: { invoice_delta_pct: -16.6, total_cost_delta_pct: -19.4, expected_late_delta_pct: -9.5, high_risk_delta_pp: -1.7 },
  });

  assert.deepEqual(rows.map((r) => r.key), ["historical_mix", "equal_split", "cheapest_first"]);
  assert.equal(rows[0].label, "Last year's buying");
});

test("a rise in cost is marked as bad and a fall as good", () => {
  const rows = comparisonRows({
    cheapest_first: { invoice_delta_pct: 1.8, total_cost_delta_pct: 0.6, expected_late_delta_pct: -3.3, high_risk_delta_pp: -2.4 },
  });
  const [invoice, , late] = rows[0].metrics;
  assert.equal(invoice.good, false, "paying more is not good news");
  assert.equal(late.good, true);
});

test("describeChange states both sides of the trade", () => {
  const before = { material_cost: 100000, expected_late_units: 1000 };
  const after = { material_cost: 101300, expected_late_units: 930, lines: [{}] };
  const sentence = describeChange(before, after);

  assert.match(sentence, /\+1\.3% on the invoice/);
  assert.match(sentence, /-7\.0% expected late units/);
});

test("describeChange says plainly when nothing moved", () => {
  const plan = { material_cost: 100, expected_late_units: 10, lines: [{}] };
  assert.match(describeChange(plan, plan), /Same plan/);
});

test("requirement captions name the largest share", () => {
  const [group] = groupByRequirement(LINES);
  assert.match(requirementMeta(group), /Week 1 · 1,000 units · 2 suppliers · largest 60%/);
});
