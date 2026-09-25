/**
 * The HTTP client both applications use.
 *
 * Small on purpose: a fetch wrapper that reports failures in words a user can
 * act on. A dashboard that silently shows stale numbers when the backend is
 * down is worse than one that says the backend is down — especially on stage.
 */

const BASE = "";

class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (cause) {
    throw new ApiError(
      "Cannot reach the server. Is it running on this port?",
      0,
      String(cause),
    );
  }

  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      detail = await response.text();
    }
    throw new ApiError(messageFor(response.status, detail), response.status, detail);
  }

  return response.json();
}

function messageFor(status, detail) {
  if (status === 404) return detail || "Nothing matches that selection.";
  if (status === 422) return "The server rejected those settings. Check the values and try again.";
  if (status >= 500) return "The server failed while planning. The details are in its log.";
  return detail || `Request failed (${status}).`;
}

export function get(path, params) {
  const query = params
    ? `?${new URLSearchParams(
        Object.entries(params).filter(([, value]) => value != null && value !== ""),
      )}`
    : "";
  return request(`${path}${query}`);
}

export function post(path, body) {
  return request(path, { method: "POST", body: JSON.stringify(body ?? {}) });
}

/**
 * Run a request with the usual three states rendered into one element.
 *
 * Every screen needs loading, error and empty handling, and doing it in one
 * place is what keeps a failure visible instead of leaving the last good
 * numbers on screen looking current.
 */
export async function withState(element, task, { loadingText = "Working…" } = {}) {
  const previous = element.innerHTML;
  element.innerHTML = `<div class="loading">${loadingText}</div>`;
  try {
    const result = await task();
    if (element.innerHTML.includes("loading")) element.innerHTML = previous;
    return result;
  } catch (error) {
    element.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
    throw error;
  }
}

export function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export { ApiError };
