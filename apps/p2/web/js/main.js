/**
 * TrendWear Planner cockpit.
 *
 * The planning modules arrive in Tasks 16 to 21. For now this confirms the
 * backend is reachable, so a broken deployment looks broken rather than empty.
 */

import { get } from "/shared/api.js";

async function renderContext() {
  const line = document.getElementById("context-line");
  try {
    const health = await get("/api/health");
    line.classList.remove("skeleton");
    line.textContent = health.status === "ok" ? "Backend ready" : "Backend unavailable";
  } catch {
    line.classList.remove("skeleton");
    line.textContent = "Backend unavailable";
  }
}

renderContext();
