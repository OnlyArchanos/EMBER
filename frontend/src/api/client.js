/**
 * API client — the only place in the frontend that talks to the backend.
 * One function per endpoint, matching docs/api-contract.md.
 * Field names stay snake_case as received from the backend (RULES.md §2.3).
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

/**
 * Build a full URL from a path and optional query params object.
 * Filters out undefined/null values so callers don't need to pre-clean.
 */
function buildUrl(path, params = {}) {
  const url = new URL(`${BASE_URL}${path}`);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/**
 * Shared fetch wrapper with structured error handling.
 * - Network failure → rejects with a readable connection error.
 * - Non-2xx → reads the response body for a `detail` field (FastAPI convention),
 *   with a try/catch so a JSON-parse failure doesn't mask the HTTP error.
 * - Success → returns parsed JSON.
 */
async function request(url) {
  let response;
  try {
    response = await fetch(url);
  } catch (err) {
    throw new Error(
      `Network error: could not reach the backend at ${BASE_URL}. Is it running? (${err.message})`
    );
  }

  if (!response.ok) {
    let detail;
    try {
      const body = await response.json();
      detail = body.detail;
    } catch {
      // JSON parse failed — fall back to status-only message
    }
    if (detail) {
      throw new Error(`API error ${response.status}: ${detail}`);
    }
    throw new Error(`API error ${response.status}`);
  }

  return response.json();
}

// --- Endpoint functions ---

/** GET /api/health */
export function getHealth() {
  return request(buildUrl('/health'));
}

/**
 * GET /api/fires — paginated, filtered list of classified detections.
 * @param {Object} [filters] - {fire_type, state, date_from, date_to,
 *   is_persistent, min_confidence, limit, offset, sort}
 */
export function getFires(filters = {}) {
  return request(buildUrl('/fires', filters));
}

/**
 * GET /api/fires/{fire_id} — full detail for one detection.
 * @param {number} fireId
 */
export function getFire(fireId) {
  return request(buildUrl(`/fires/${fireId}`));
}

/**
 * GET /api/zones — cached zone polygons for the map overlay.
 * @param {string} [zoneType] - optional filter: 'industrial', 'forest', 'farmland'
 */
export function getZones(zoneType) {
  return request(buildUrl('/zones', { zone_type: zoneType }));
}

/**
 * GET /api/flags — list of flagged unexplained persistent sources.
 * Read-only in the prototype (no PATCH).
 * @param {string} [status='open'] - filter by status
 */
export function getFlags(status) {
  return request(buildUrl('/flags', { status }));
}

/**
 * GET /api/flags/{flag_id} — full detail for one flagged case.
 * @param {number} flagId
 */
export function getFlag(flagId) {
  return request(buildUrl(`/flags/${flagId}`));
}

/**
 * GET /api/stats — aggregate numbers for the sidebar.
 * Accepts the same filters as /api/fires (minus trend_days, cut for prototype).
 * @param {Object} [filters] - {fire_type, state, date_from, date_to}
 */
export function getStats(filters = {}) {
  return request(buildUrl('/stats', filters));
}
