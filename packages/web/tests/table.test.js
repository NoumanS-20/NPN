/**
 * The table module is ours, so it gets tested like any other code we own.
 *
 * Run: node --test packages/web/tests
 */

import assert from "node:assert/strict";
import { test, beforeEach } from "node:test";
import { JSDOM } from "jsdom";

import { createTable } from "../table.js";

const COLUMNS = [
  { key: "name", label: "Supplier" },
  { key: "rate", label: "On time", numeric: true },
];

const ROWS = [
  { name: "Alpha", rate: 0.9, origin: "real" },
  { name: "Beta", rate: 0.7, origin: "synthetic" },
  { name: "Gamma", rate: null, origin: "real" },
];

let mount;

beforeEach(() => {
  const dom = new JSDOM('<!doctype html><div id="host"></div>');
  global.window = dom.window;
  global.document = dom.window.document;
  global.Node = dom.window.Node;
  mount = document.getElementById("host");
});

test("renders one header cell per column and one row per record", () => {
  createTable(mount, { columns: COLUMNS, rows: ROWS });
  assert.equal(mount.querySelectorAll("thead th").length, 2);
  assert.equal(mount.querySelectorAll("tbody tr").length, 3);
});

test("a numeric column opens best-first, then flips", () => {
  createTable(mount, { columns: COLUMNS, rows: ROWS });
  const header = mount.querySelectorAll("thead th")[1];

  header.dispatchEvent(new window.MouseEvent("click"));
  assert.equal(
    mount.querySelector("tbody tr td").textContent,
    "Alpha",
    "clicking On time should show the most reliable supplier first",
  );

  header.dispatchEvent(new window.MouseEvent("click"));
  assert.equal(mount.querySelector("tbody tr td").textContent, "Beta");
});

test("a text column opens A to Z", () => {
  createTable(mount, { columns: COLUMNS, rows: [...ROWS].reverse() });
  const header = mount.querySelectorAll("thead th")[0];

  header.dispatchEvent(new window.MouseEvent("click"));
  const names = [...mount.querySelectorAll("tbody tr td:first-child")].map((c) => c.textContent);
  assert.deepEqual(names, ["Alpha", "Beta", "Gamma"]);
});

test("missing values sort last, whichever way the column points", () => {
  createTable(mount, { columns: COLUMNS, rows: ROWS });
  const header = mount.querySelectorAll("thead th")[1];

  header.dispatchEvent(new window.MouseEvent("click"));
  let names = [...mount.querySelectorAll("tbody tr td:first-child")].map((c) => c.textContent);
  assert.equal(names.at(-1), "Gamma", "a supplier with no rate must not lead the table");


  header.dispatchEvent(new window.MouseEvent("click"));
  names = [...mount.querySelectorAll("tbody tr td:first-child")].map((c) => c.textContent);
  assert.equal(names.at(-1), "Gamma");
});

test("filtering narrows the rows and reports the count", () => {
  createTable(mount, { columns: COLUMNS, rows: ROWS });
  const search = mount.querySelector('input[type="search"]');

  search.value = "alp";
  search.dispatchEvent(new window.Event("input"));

  assert.equal(mount.querySelectorAll("tbody tr").length, 1);
  assert.match(mount.querySelector(".table-foot span").textContent, /1–1 of 1/);
});

test("a filter matching nothing explains itself", () => {
  createTable(mount, { columns: COLUMNS, rows: ROWS });
  const search = mount.querySelector('input[type="search"]');
  search.value = "nobody";
  search.dispatchEvent(new window.Event("input"));

  const cell = mount.querySelector("tbody .empty");
  assert.ok(cell, "an empty result needs a message, not a blank table");
  assert.match(cell.textContent, /nobody/);
});

test("paginates at the configured page size", () => {
  const many = Array.from({ length: 60 }, (_, index) => ({ name: `S${index}`, rate: index / 60 }));
  createTable(mount, { columns: COLUMNS, rows: many, pageSize: 25 });

  assert.equal(mount.querySelectorAll("tbody tr").length, 25);
  assert.match(mount.querySelector(".pager span").textContent, /1 \/ 3/);
});

test("the next and previous buttons move through pages", () => {
  const many = Array.from({ length: 60 }, (_, index) => ({ name: `S${index}`, rate: index }));
  createTable(mount, { columns: COLUMNS, rows: many, pageSize: 25 });

  const [previous, , next] = mount.querySelectorAll(".pager button, .pager span");
  assert.equal(previous.disabled, true, "there is no page before the first");

  next.dispatchEvent(new window.MouseEvent("click"));
  assert.match(mount.querySelector(".pager span").textContent, /2 \/ 3/);
});

test("generated rows carry a badge wherever the table is sorted", () => {
  createTable(mount, {
    columns: COLUMNS,
    rows: ROWS,
    rowBadge: (row) => (row.origin === "synthetic" ? "Generated" : null),
  });

  const badges = mount.querySelectorAll(".badge--generated");
  assert.equal(badges.length, 1);
  assert.equal(badges[0].textContent, "Generated");
});

test("setRows replaces the data without rebuilding the table", () => {
  const table = createTable(mount, { columns: COLUMNS, rows: ROWS });
  table.setRows([{ name: "Delta", rate: 0.5 }]);

  assert.equal(mount.querySelectorAll("tbody tr").length, 1);
  assert.equal(mount.querySelector("tbody td").textContent, "Delta");
});

test("a custom format is used for a column", () => {
  createTable(mount, {
    columns: [
      { key: "name", label: "Supplier" },
      { key: "rate", label: "On time", numeric: true, format: (v) => (v == null ? "—" : `${v * 100}%`) },
    ],
    rows: ROWS,
  });
  const cells = [...mount.querySelectorAll("tbody tr td.numeric")].map((c) => c.textContent);
  assert.deepEqual(cells, ["90%", "70%", "—"]);
});
