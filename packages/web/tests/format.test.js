/**
 * Formatting rules, especially around missing data.
 *
 * A supplier with no trading history has no on-time rate. Showing "0%" there
 * would say they never deliver on time, which is the opposite of "we do not
 * know" — so every formatter has to keep that distinction.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { delta, days, humanise, money, pct, price, riskBand, truncate, units } from "../format.js";

test("money has no decimals, because procurement deals in whole units", () => {
  assert.equal(money(113408), "$113,408");
  assert.equal(money(0), "$0");
});

test("unit price keeps the fractions that matter", () => {
  assert.equal(price(0.1953), "0.1953");
  assert.equal(price(1.5), "1.50");
});

test("percentages are rounded, not truncated", () => {
  assert.equal(pct(0.1149), "11.5%");
  assert.equal(pct(0.4, 0), "40%");
});

test("deltas keep their sign, so a rise reads as a rise", () => {
  assert.equal(delta(1.79), "+1.8%");
  assert.equal(delta(-16.64), "-16.6%");
});

test("missing values show an em dash rather than a zero", () => {
  for (const format of [money, price, units, pct, delta, days]) {
    assert.equal(format(null), "—", `${format.name} turned a gap into a number`);
    assert.equal(format(undefined), "—");
  }
});

test("formatters survive being handed a row as their second argument", () => {
  // The table calls format(value, record). Passing money or pct by name then
  // puts a row object into the currency or digits slot; both must cope.
  const row = { style_id: "A", units: 10 };
  assert.equal(money(1234, row), "$1,234");
  assert.equal(pct(0.5, row), "50.0%");
  assert.equal(delta(1.25, row), "+1.3%");
});

test("risk bands match the optimiser's thresholds", () => {
  assert.equal(riskBand(0.1), "low");
  assert.equal(riskBand(0.25), "medium");
  assert.equal(riskBand(0.39), "medium");
  assert.equal(riskBand(0.4), "high");
  assert.equal(riskBand(null), "low");
});

test("long names are shortened with a real ellipsis", () => {
  const name = "SCMS from RDC — Hetero Unit III, Hyderabad, India";
  assert.equal(truncate(name, 20).length, 20);
  assert.ok(truncate(name, 20).endsWith("…"));
  assert.equal(truncate("Short", 20), "Short");
});

test("identifiers become readable labels", () => {
  assert.equal(humanise("cheapest_first"), "Cheapest first");
  assert.equal(humanise("historical_mix"), "Historical mix");
});

test("units are grouped for scanning", () => {
  assert.equal(units(1802167), "1,802,167");
});
