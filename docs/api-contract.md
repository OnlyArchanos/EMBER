# API Contract — FROZEN CONTRACT

**Status:** frozen. Adding, renaming, or reshaping an endpoint requires updating this file first and getting explicit human sign-off (see `RULES.md` §1, rule 2).

**Conventions:**
- JSON in, JSON out. Field names are `snake_case` everywhere, matching `data-model.md` exactly.
- Errors return a JSON body with a `detail` string and an appropriate 4xx/5xx status — no ad hoc error shapes per endpoint.
- Any endpoint returning a list of `FireDetection`-scale data uses the paginated envelope: `{"results": [...], "total": int, "limit": int, "offset": int}`. Endpoints returning a small, bounded set (zones, flags) return a bare array — they don't need the envelope because the dataset is never large enough to need paging.

## `GET /api/fires`

Filterable, paginated list of classified detections, for the map and list views. Rows still in `fire_type = pending` are excluded from this endpoint by default (they haven't been processed yet — see `data-model.md`).

- Query params (all optional): `fire_type`, `state`, `date_from`, `date_to`, `is_persistent`, `min_confidence`, `limit` (default 500, max 5000), `offset` (default 0), `sort` (default `acq_date_desc`).
- Response: paginated envelope of `FireDetection` objects.

## `GET /api/fires/{fire_id}`

Full detail for one detection, for the map popup.

- Path param: `fire_id` (integer).
- Response: a single `FireDetection` object, or 404.

## `GET /api/zones`

Cached zone polygons for the map overlay. Returned as a bare, unpaginated array — the zone dataset is small (a few thousand polygons, refreshed periodically, not per-request), so pagination/viewport filtering is deliberately skipped for this build rather than left unaddressed by accident.

- Query params (optional): `zone_type`.
- Response: array of `Zone` objects.

## `GET /api/stats`

Aggregate numbers for the sidebar. Accepts the **same filters as `/api/fires`** so a filtered map view and the sidebar summary never disagree.

- Query params (all optional, same semantics as `/api/fires`): `fire_type`, `state`, `date_from`, `date_to`, `trend_days` (default 30 — governs the `trend` field below; the field name itself doesn't hardcode a window length).
- Response object fields: `total_fires`, `by_type` (counts per `fire_type` value), `by_state` (counts per state), `trend` (array of `{date, count}` covering `trend_days`), `persistent_active_count`, `persistent_ended_count`, `flagged_open_count`.

## `GET /api/flags`

List of currently flagged Unexplained Persistent Sources.

- Query params (optional): `status` (defaults to `open`).
- Response: array of `FlaggedCase` objects, each including its linked `PersistentSource` summary (`first_seen`, `last_seen`, `days_active`, `member_count`, `status`).

## `GET /api/flags/{flag_id}`

Full detail for one flagged case.

- Path param: `flag_id` (integer).
- Response: a single `FlaggedCase` object with its full linked `PersistentSource` and the list of member `FireDetection` records, or 404.

## `PATCH /api/flags/{flag_id}`

Updates a flagged case — this is what `FlagDetail.jsx` calls when an analyst reviews, dismisses, or annotates a case.

- Path param: `flag_id` (integer).
- Body (all optional, at least one required): `status` (`open` \| `reviewed` \| `dismissed`), `case_note` (string).
- Response: the updated `FlaggedCase` object, or 404. Updates `updated_at`.

## `GET /api/flags/export` (should-have, not MVP-blocking)

Returns currently flagged cases as CSV, for handing off to an analyst outside the dashboard. Documented now so that if it gets built later, it doesn't need its own naming decisions made from scratch.

- Query params (optional): `status` (defaults to `open`).
- Response: `text/csv` body, one row per `FlaggedCase`, columns matching its field names in `data-model.md`.

## `GET /api/health`

Liveness check. Also exposes which data mode the backend is currently running in, since that's central to the offline-demo strategy — worth being able to confirm at a glance during a live demo.

- Response: `{"status": "ok", "mode": "seed" | "live"}`.
