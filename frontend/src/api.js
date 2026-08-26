// Ultron shared frontend API client.
// Normal local installs use a loopback backend. Explicit Codespaces Web Mode
// sets VITE_API_URL=. so browser traffic remains relative and Vite proxies it
// to the internal FastAPI server.

const configuredApiBase = import.meta.env.VITE_API_URL;
const API_BASE = (configuredApiBase === undefined
  ? 'http://127.0.0.1:8000'
  : configuredApiBase
).replace(/\/+$/, '');

export const apiBase = API_BASE;

export function websocketBase() {
  if (/^https?:\/\//.test(API_BASE)) return API_BASE.replace(/^http/, 'ws');
  if (typeof window !== 'undefined') {
    return `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`;
  }
  return 'ws://127.0.0.1:8000';
}

/**
 * JSON request helper against the backend.
 * Throws on a non-2xx response so callers can surface real errors.
 */
export async function api(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    let detail = '';
    try {
      detail = (await res.json()).detail || '';
    } catch (_error) { /* response was not JSON */ }
    throw new Error(`API ${path} failed (${res.status}): ${detail}`);
  }
  return res.json();
}

/** Execute a backend tool through the validated REST executor. */
export function executeTool(toolId, args = {}, options = {}) {
  const { sessionId = 'frontend_tools', confirmationToken = null } = options;
  return api('/api/tools/execute', {
    method: 'POST',
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
export async function executeToolWithConfirmation(toolId, args = {}, sessionId = 'frontend_tools') {
  const first = await executeTool(toolId, args, { sessionId });
  if (first.status !== 'PENDING_CONFIRMATION') return first;
  const approved = typeof window !== 'undefined' && window.confirm(first.message);
  if (!approved) return first;
  return executeTool(toolId, args, {
    sessionId,
    confirmationToken: first.confirmation_token,
  });
}
