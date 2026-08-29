# Data Model — FROZEN CONTRACT

**Status:** frozen. Changing a field name, type, or table here requires updating this file first and getting explicit human sign-off (see `RULES.md` §1, rule 2) — code conforms to this document, never the reverse.

## FireDetection

One row per raw NASA FIRMS detection.

| Field           | Type              | Notes                                                                                                                                                                                                                                                                                                                                                                                                                      |
| --------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`            | integer, PK       |                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `latitude`      | float             | WGS84                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `longitude`     | float             | WGS84                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `brightness`    | float             | brightness temperature (Kelvin)                                                                                                                                                                                                                                                                                                                                                                                            |
| `frp`           | float             | fire radiative power                                                                                                                                                                                                                                                                                                                                                                                                       |
| `acq_date`      | date              | acquisition date                                                                                                                                                                                                                                                                                                                                                                                                           |
| `acq_time`      | string            | acquisition time (HHMM, as FIRMS reports it)                                                                                                                                                                                                                                                                                                                                                                               |
| `daynight`      | enum              | `d` \| `n` — required input for the ML day/night-ratio feature (see `RULES.md` §5)                                                                                                                                                                                                                                                                                                                                         |
| `satellite`     | enum              | `snpp` \| `noaa20` \| `noaa21`                                                                                                                                                                                                                                                                                                                                                                                             |
| `confidence`    | string            | raw FIRMS confidence value (`l`/`n`/`h` for VIIRS)                                                                                                                                                                                                                                                                                                                                                                         |
| `fire_type`     | enum              | `pending` \| `industrial` \| `wildfire` \| `agricultural` \| `unclassified`. Default on insert is `pending`. `classifier.py` moves it to one of the other four values. `pending` and `unclassified` are NOT the same thing — `pending` means "not yet checked," `unclassified` means "checked, matched no zone." Anything still `pending` must be excluded from persistence/flagging logic, not treated as `unclassified`. |
| `state`         | string, nullable  | resolved via `geocode.py`; nullable until resolved                                                                                                                                                                                                                                                                                                                                                                         |
| `district`      | string, nullable  | resolved via `geocode.py`; nullable until resolved                                                                                                                                                                                                                                                                                                                                                                         |
| `cluster_id`    | integer, nullable | set by `persistence.py`; `null` until clustering has run, `-1` reserved for DBSCAN noise (excluded from persistence logic per `RULES.md` §5)                                                                                                                                                                                                                                                                               |
| `is_persistent` | boolean           | default `false`; set by `persistence.py`                                                                                                                                                                                                                                                                                                                                                                                   |
| `created_at`    | timestamp         | when this row was ingested — used for dedup-window logic and debugging, not shown in the UI                                                                                                                                                                                                                                                                                                                                |

**Deduplication:** FIRMS has no stable per-detection ID, and scheduled fetches use overlapping date windows by design (yesterday's near-real-time detections get re-reported today, sometimes with an updated confidence). Before insert, treat `(round(latitude, 4), round(longitude, 4), acq_date, acq_time, satellite)` as the natural dedup key — round first, since two fetches of "the same" detection can differ in the last float digit. On a match, update the existing row's `confidence`/`brightness`/`frp` rather than inserting a new one.

## Zone

Cached OSM polygons used both for classification and the map overlay.

| Field       | Type             | Notes                                                                                                 |
| ----------- | ---------------- | ----------------------------------------------------------------------------------------------------- |
| `id`        | integer, PK      |                                                                                                       |
| `osm_id`    | string, nullable | the OSM way/relation ID — used to upsert on refresh instead of wiping and reinserting the whole table |
| `zone_type` | enum             | `industrial` \| `forest` \| `farmland`                                                                |
| `name`      | string, nullable | OSM name tag if present                                                                               |
| `geometry`  | polygon          | stored as WKT/GeoJSON in the DB                                                                       |
| `source`    | string           | always `osm` for now                                                                                  |

## PersistentSource

One row per physical, spatially-tracked persistent cluster that passed the
(noise-excluded) persistence check. A single `PersistentSource` can span many
`persistence.py` runs over many days — see the cluster-identity note below.

| Field                   | Type           | Notes                                                                                                                                                                                                |
| ----------------------- | -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                    | integer, PK    | this row's own stable identity — see the cluster-identity note below                                                                                                                                 |
| `cluster_id`            | integer        | **always equal to this row's own `id`**, duplicated here only so `FireDetection.cluster_id` and `PersistentSource.cluster_id` join the same way; never `-1`                                          |
| `centroid_latitude`     | float          | representative location of the cluster, recomputed as new members join; used to match a new run's DBSCAN group back to this same physical source                                                     |
| `centroid_longitude`    | float          | see `centroid_latitude`                                                                                                                                                                              |
| `first_seen`            | date           |                                                                                                                                                                                                      |
| `last_seen`             | date           |                                                                                                                                                                                                      |
| `days_active`           | integer        | unique acquisition days for this cluster                                                                                                                                                             |
| `member_count`          | integer        | number of `FireDetection` rows in this cluster                                                                                                                                                       |
| `zone_type_at_location` | enum, nullable | one of `Zone.zone_type`'s values, or `null` for unclassified                                                                                                                                         |
| `status`                | enum           | `active` (detections still recent) \| `ended` (nothing new in the cluster for a defined window). Needed so `/api/stats` can report "currently persistent" separately from "historically persistent." |

**Cluster identity must be stable across runs — it is never DBSCAN's raw
output.** DBSCAN's per-run labels (0, 1, 2...) are an internal computation
detail of a single `persistence.py` run and must never be stored directly —
the same physical cluster can get a different label on the next run. The
stable identity stored in both `FireDetection.cluster_id` and
`PersistentSource.cluster_id` is always `PersistentSource.id`. Each run must
spatially match its newly-computed DBSCAN groups against existing `active`
`PersistentSource.centroid_latitude/longitude` — not by label — to decide
whether a group continues a known source or starts a new one.

Aggregate intensity values (avg/max FRP, FRP trend) are deliberately **not** stored here — `ml/features.py` computes them on demand from the member `FireDetection` rows via `cluster_id`, both for flagged and not-yet-flagged clusters, since the model needs negative examples (persistent-but-explained clusters) during training, not just the ones that ended up flagged.

## FlaggedCase

One row per persistent source that is also unclassified and above the ML confidence threshold — the promoted, first-class "Unexplained Persistent Source" record.

| Field                     | Type                                | Notes                                                                                                                           |
| ------------------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `id`                      | integer, PK                         |                                                                                                                                 |
| `persistent_source_id`    | integer, FK → `PersistentSource.id` |                                                                                                                                 |
| `anomaly_score`           | float                               | output of `ml/infer.py`                                                                                                         |
| `nearest_zone_type`       | enum, nullable                      | closest known zone type, even though it didn't contain the point                                                                |
| `nearest_zone_distance_m` | float                               | distance in metres to that nearest zone                                                                                         |
| `status`                  | enum                                | `open` \| `reviewed` \| `dismissed`; default `open`                                                                             |
| `case_note`               | text, nullable                      | free-text analyst note                                                                                                          |
| `created_at`              | timestamp                           | when this case was first flagged — this is the number that supports the "flagged N days ago, still unexplained" pitch narrative |
| `updated_at`              | timestamp                           | last time `status` or `case_note` changed                                                                                       |

## Relationships

`FireDetection.cluster_id` → groups into `PersistentSource.cluster_id` (not a formal FK, since not every detection belongs to a persistent cluster).
`FlaggedCase.persistent_source_id` → `PersistentSource.id` (formal FK; every `FlaggedCase` must reference a real persistent source).
Zone membership for `FireDetection.fire_type` and `PersistentSource.zone_type_at_location` comes from a spatial join against `Zone.geometry`, not a stored FK.

## Explicitly out of scope for this schema

- **Known-industrial-sites validation list** (used by `scripts/validate_known_sites.py`) is a static fixture file, not a database table — it's ground truth for testing the pipeline, not data the pipeline produces.
- **ML model version/metadata tracking** is not modeled. There is exactly one active trained artifact under `ml/artifacts/` at a time; retraining replaces it. If reproducibility across model versions becomes a real need later, that's a deliberate future addition, not an oversight now.
