/**
 * The rail and page chrome, rendered from one place.
 *
 * Six pages share a navigation list. Without a framework the choice is between
 * repeating it in six HTML files — where it will drift — or rendering it from a
 * module. This is the module.
 */

import { get } from "/shared/api.js";

const PAGES = [
  { href: "/", label: "Overview" },
  { href: "/pages/suppliers.html", label: "Suppliers" },
  { href: "/pages/allocate.html", label: "Allocation" },
  { href: "/pages/risk-check.html", label: "Pre-PO check" },
  { href: "/pages/scenarios.html", label: "Scenarios" },
  { href: "/pages/models.html", label: "Models" },
];

export function renderRail(currentHref) {
  const rail = document.querySelector(".rail");
  if (!rail) return;

  const current = currentHref ?? window.location.pathname;
  const links = PAGES.map((page) => {
    const active = page.href === current ? ' aria-current="page"' : "";
    return `<a href="${page.href}"${active}>${page.label}</a>`;
  }).join("");

  rail.innerHTML = `
    <div class="brand">
      <span class="brand__name">SupplyGuard</span>
      <span class="brand__case">PR1 · Procurement</span>
    </div>
    <nav class="nav" aria-label="Sections">${links}</nav>
    <div class="rail__foot">
      <span id="context-line" class="skeleton" style="width:80%"></span>
      <span>Team Vortex5</span>
    </div>`;

  loadContext();
}

async function loadContext() {
  const line = document.getElementById("context-line");
  if (!line) return;
  try {
    const summary = await get("/api/summary");
    line.classList.remove("skeleton");
    line.textContent =
      `${summary.suppliers} suppliers · ${summary.plants} plants · ${summary.materials} materials`;
  } catch {
    line.classList.remove("skeleton");
    line.textContent = "Backend unavailable";
  }
}
