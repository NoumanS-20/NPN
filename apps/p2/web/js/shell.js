/**
 * The rail, the cycle stages, and a few things every P2 page needs.
 */

import { get } from "/shared/api.js";

const PAGES = [
  { href: "/", label: "Cockpit" },
  { href: "/pages/reconcile.html", label: "Reconciliation" },
  { href: "/pages/merchandising.html", label: "Merchandising" },
  { href: "/pages/production.html", label: "Production" },
  { href: "/pages/logistics.html", label: "Logistics" },
  { href: "/pages/inventory.html", label: "Inventory" },
  { href: "/pages/markdown.html", label: "Markdown" },
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
      <span class="brand__name">TrendWear Planner</span>
      <span class="brand__case">P2 · Planning</span>
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
      `${summary.styles} styles · ${summary.plants} plants · ${summary.horizon_weeks}-week horizon`;
  } catch {
    line.classList.remove("skeleton");
    line.textContent = "Backend unavailable";
  }
}

export function stat(label, value, note, tone) {
  const toneClass = tone ? ` delta--${tone}` : "";
  return `
    <div class="stat">
      <div class="stat__label">${label}</div>
      <div class="stat__value${toneClass}">${value}</div>
      ${note ? `<div class="stat__note">${note}</div>` : ""}
    </div>`;
}

/** The four stages, drawn as a path the plan moves along. */
export function renderStages(mount, stages, currentStage) {
  const currentIndex = stages.findIndex((stage) => stage.key === currentStage);
  mount.innerHTML = `<div class="stages">${stages
    .map((stage, index) => {
      const state = index < currentIndex ? "done" : index === currentIndex ? "current" : "pending";
      return `<div class="stage" data-state="${state}">
        <div class="small">${index + 1}. ${stage.label}</div>
      </div>`;
    })
    .join("")}</div>`;
}

export function showError(mount, error) {
  mount.innerHTML = `<div class="error">${error.message}</div>`;
}
