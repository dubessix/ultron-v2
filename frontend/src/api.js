// Ultron shared frontend API client (Phase 6)
//
// Single source of truth for reaching the backend, so no widget uses a broken
// relative `/api` URL (which 404s in dev, where the backend runs on a different
// port/host than the Vite dev server). Backend base URL is resolved from
// VITE_API_URL with a localhost fallback, exactly like the widgets that already
// worked.

const API_BASE = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

export const apiBase = API_BASE;

/**
 * JSON request helper against the backend.
 * Throws on a non-2xx response so callers can surface real errors.
 */
export async function api(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    let detail = "";
    try {
      detail = (await res.json()).detail || "";
    } catch (_e) { /* ignore */ }
    throw new Error(`API ${path} failed (${res.status}): ${detail}`);
  }
  return res.json();
}

/**
 * Execute a backend tool through the validated REST executor.
 */
export function executeTool(toolId, args = {}, options = {}) {
  const { sessionId = "frontend_tools", confirmationToken = null } = options;
  return api("/api/tools/execute", {
    method: "POST",
    body: JSON.stringify({
      tool_id: toolId,
      arguments: args,
      session_id: sessionId,
      has_confirmed: Boolean(confirmationToken),
      confirmation_token: confirmationToken,
    }),
  });
}

/** Ask once, then return the exact token for the exact same tool arguments. */
export async function executeToolWithConfirmation(toolId, args = {}, sessionId = "frontend_tools") {
  const first = await executeTool(toolId, args, { sessionId });
  if (first.status !== "PENDING_CONFIRMATION") return first;
  const approved = typeof window !== "undefined" && window.confirm(first.message);
  if (!approved) return first;
  return executeTool(toolId, args, {
    sessionId,
    confirmationToken: first.confirmation_token,
  });
}
