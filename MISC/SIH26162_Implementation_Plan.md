# EMBER — Implementation Plan

### AI-Based Detection and Classification of Industrial Fires and Persistent Thermal Sources

**Sponsor:** National Technical Research Organisation (NTRO) · **Track:** Software · **Theme:** Space Technology

---

## 1. Executive Summary

We are building a system that ingests NASA satellite fire/thermal-hotspot data for India, classifies each detection by _what kind of thing is actually burning or radiating heat_ (industrial facility, forest, farmland, or unexplained), flags detections that recur persistently in places that shouldn't have a persistent heat signature, and presents all of this on a dashboard.

The honest framing, and the one we should carry into every design decision: **the interesting part of this problem is not the map — it's the flagging.** Anyone can plot NASA FIRMS points on a dark Mapbox style in a weekend. What NTRO would actually get value from is a system that quietly does nothing for 99% of detections (because they're obviously wildfires or obviously known industrial sites) and raises its hand for the 1% that don't fit any known pattern — because _that_ 1% is what an analyst can't currently find without manually cross-referencing satellite data, OSM, and news reports by hand. Everything in this plan is built to make that flagging pipeline as credible as possible, because that's what will separate us from the other teams who picked this same problem statement and built "a map with dots on it."

This document covers: how we're reading a problem statement that currently has no official detailed brief, how we intend to score well against SIH's actual evaluation rubric, what we are and are not building, the full system architecture and file structure, the data model, the API surface, a phased build timeline mapped to the real SIH calendar, team workstream allocation, and a risk register.

---

## 2. Re-Reading the Problem Statement

### 2.1 What we know for certain

- Title, PS code, track, and sponsor (NTRO) are confirmed against the official SIH 2026 catalogue.
- As of now, NTRO has not published an expanded "Background / Problem Statement / Expected Solution" for this PS the way it has for several neighboring NTRO statements. We are working from five words of scope (the title) rather than a paragraph of intent.
- This is a _risk_, but also an _opportunity_: since NTRO hasn't over-specified the solution shape, we get to define what "good" looks like — and we should define it in a way that plays to a strong story, not just to what's technically easiest.

### 2.2 Reading between the lines — what NTRO's institutional lens tells us

NTRO is a signals-and-technical-intelligence organisation. Every other NTRO problem statement in this year's catalogue is about _detecting anomalies a human analyst would otherwise miss_ — cyber traffic anomalies, dark-web attribution, forensic recovery, network compliance auditing. That's the pattern this PS almost certainly belongs to as well, even though it's dressed up in a "fire dashboard" costume. NTRO does not need another way to look at a map. It plausibly needs a way to know when a heat signature doesn't match any explanation on file — because an unexplained, persistent, high-intensity thermal source in a spot with no known industrial activity is a legitimate signal of interest (illicit industrial activity, an undeclared facility, a fire at a site that should have been reported and wasn't, etc.).

**Working interpretation we will build toward:** this is a _decision-support and anomaly-surfacing tool_, and the map dashboard is the delivery mechanism, not the point.

### 2.3 What we are explicitly assuming (flag these in the pitch as assumptions, not facts)

- Scope is India-only (matches the "IND" NASA FIRMS country code and OSM query pattern).
- "Persistent Thermal Sources" in the title refers to non-fire, continuously-radiating heat sources (flares, furnaces, kilns) as distinct from one-off fire events — this is the natural reading and it's what makes DBSCAN-over-time a sensible technique.
- A browser dashboard is an acceptable deliverable format (title doesn't specify a delivery channel, but "dashboard" is the standard SIH software-track deliverable and is safe to assume).
- We should re-check sih.gov.in for an updated, expanded description before the internal hackathon deadline — if NTRO publishes more detail later, this plan gets revised, not discarded.

---

## 3. Judging Strategy — How We Actually Win This

SIH's evaluation rubric (both at the internal-hackathon stage and the national stage) consistently scores on five axes: **Innovation, Technical Feasibility, Architecture, Impact/Benefits, and Presentation clarity.** Evaluators reportedly spend on the order of 2–3 minutes per submission at the shortlisting stage — clarity beats cleverness there. Here's how we map our effort to each axis, deliberately, rather than hoping it comes together naturally.

### 3.1 Innovation

The map-and-classify-by-polygon idea is the _obvious_ build for this PS — expect most competing teams to arrive at some version of it, because it's the natural first reading of the title. Our differentiator has to be the **flagging/investigation layer**: a detection that is (a) persistent over time, (b) not inside any known industrial/forest/farmland polygon, and (c) has an intensity profile inconsistent with typical background heat, gets promoted to an explicit "Unexplained Persistent Source" case, with its own record, its own investigative trail (what OSM data was checked, what confidence score it got, why it wasn't auto-classified), and its own place in the UI. This turns "we made a map" into "we made an analyst's triage queue," which is a materially different pitch.

### 3.2 Technical Feasibility

We deliberately avoid promising anything we can't demo live in 36 hours at the finale. Every "should-have" in Section 4 has a documented fallback. The whole system is designed to run convincingly **offline**, from pre-fetched data, because live dependence on NASA/OSM public APIs during a judged demo is a real failure risk (see Section 12) — and because "works fully on cached/local data" doubles as an on-device/offline-capable story, which reviewers have been explicitly noting as a bonus point this cycle.

### 3.3 Architecture

We're not over-engineering this into microservices — a 6-person student team building this in a few weeks plus a 36-hour sprint should have one deployable backend, one frontend, and a clean internal separation of concerns (ingestion vs. classification vs. ML vs. API vs. presentation). Section 7 walks through exactly why the structure is shaped the way it is. Judges evaluating "Architecture" are checking whether the team understands _why_ the system is built the way it is, not whether it's the most complex thing on the floor.

### 3.4 Impact & Benefits

We should be explicit and numbers-driven in the pitch: X known industrial sites correctly classified as a validation baseline (Section 6.5), a concrete before/after framing ("today an analyst would have to manually cross-reference three separate data sources by hand; this does it continuously and only surfaces the cases that need a human"), and a realistic path to production (swap SQLite for Postgres, swap the free Mapbox tier for an enterprise agreement, add auth — all called out as "future work," not built, because pretending to have solved deployment/security in a hackathon demo undermines credibility more than admitting it's out of scope).

### 3.5 Presentation

Build the demo script and the pitch deck in parallel with the code, not after it (Section 13). The 2–3 minute shortlisting read and the 36-hour finale pitch are different artifacts — prepare both.

### 3.6 Competitive awareness

NTRO/technical problem statements are reported to draw fewer teams but a higher technical bar than oversaturated categories like generic agriculture or healthcare apps — that cuts both ways: less crowd noise, but the teams that do show up here are likely to be stronger. Assume competent competition and build for it.

---

## 4. Scope Decisions

### 4.1 Must-have (MVP — this is what gets demoed no matter what)

1. Data pipeline pulling NASA FIRMS VIIRS data for India (multi-satellite, see 6.4) on a schedule, with a cached/seeded fallback dataset.
2. OSM-derived industrial/forest/farmland polygons for India, cached locally (not re-fetched live during the demo).
3. Corrected spatial-join classification (industrial / wildfire / agricultural / **unclassified** — see 6.1 for why "unclassified" has to exist as a real category).
4. Corrected persistence detection (DBSCAN over time, with the noise-cluster bug fixed — see 6.2).
5. The "Unexplained Persistent Source" flagging logic as its own explicit feature, not a side effect.
6. A dark, interactive map dashboard: hotspot layer, zone overlay, filters, stats sidebar, and a dedicated "Flagged for Review" panel.
7. A validation view showing classification performance against the known-industrial-site list (Section 6.5) — this is our proof-of-accuracy story for judges.
8. Required data attribution (NASA, OpenStreetMap ODbL, Mapbox) visible in the UI.

### 4.2 Should-have (build if time allows, in this order of priority)

1. A genuine ML layer beyond rule-based classification (Section 6.3) — this is high-value for the "AI-Based" framing in the title and worth prioritizing over polish.
2. Trend charts (30-day fire counts, persistent-source counts over time).
3. CSV/report export of flagged sources (an NTRO analyst would want to hand this off, not just look at it).
4. A basic case-note field on flagged sources (so the team can narrate "an analyst could annotate this" during the pitch, even if it's just a text field with no backing workflow).

### 4.3 Explicitly out of scope (state this proactively in the pitch — it reads as maturity, not as a gap)

- User authentication / role-based access. We will _say_ this is a hard requirement for any real NTRO deployment and describe how we'd add it (e.g., SSO integration point in the API layer), but we will not build it — it adds risk for zero demo value.
- Real Sentinel-2 imagery thumbnails. Nice-to-have visually, but it's a third external dependency with its own auth/quota story, and it doesn't touch the core "flagging" value proposition. Cut it unless everything else is done early.
- Mobile app / native clients. Web dashboard only.
- Multi-country support. India only, matching the title and NASA FIRMS country-code approach.
- Automated model retraining pipelines. We train once, offline, before the demo, and ship the trained artifact.

---

## 5. System Architecture Overview

Three logical layers, one physical backend process, one physical frontend process:

**Ingestion & caching layer.** Scheduled jobs pull NASA FIRMS hotspot data and OSM zone polygons, normalize them, and write them to local storage (both a database and a flat-file cache for offline fallback). This layer is the only part of the system that talks to the outside internet, and it's built so the rest of the system never notices whether that data came from a live fetch five minutes ago or a cached seed file from last week.

**Analysis layer.** This is where classification, persistence detection, the ML-based anomaly scoring, and the flagging decision happen. It reads from the database, writes derived fields back (fire_type, is_persistent, flag_status, confidence), and is the layer most worth showing off in the technical deep-dive, since it's where our actual differentiation lives.

**Presentation layer.** A FastAPI backend exposes read-only endpoints over the analyzed data; a React frontend renders the map, stats, and the flagged-review panel. The frontend never talks to NASA/OSM directly — everything it needs has already been computed and stored by the time it asks for it. This decoupling is also what makes offline-demo-mode trivial: point the frontend at a backend running against seeded data, and it behaves identically to a "live" backend.

Data flows one direction: external APIs → ingestion → database → analysis → API → frontend. No component reaches backward across that chain, which is the main thing keeping this simple enough for a small team to reason about under deadline pressure.

---

## 6. Technical Decisions (Fixes and Upgrades from the Handoff Review)

### 6.1 Classification logic: add the missing farmland join and a real "unclassified" bucket

The original handoff's classification defaulted anything not industrial or forest to "agricultural," without ever actually checking the farmland layer it loaded. We fix this by adding a genuine third spatial join against farmland/orchard polygons, and introducing a fourth category — **unclassified** — for anything that lands in none of the three zone types. This isn't just a bug fix: the unclassified bucket is the _raw material_ for our flagging feature (Section 6.6). Priority order stays industrial > forest > farmland > unclassified, since a fire physically inside a mapped industrial polygon is the strongest signal.

### 6.2 Persistence detection: exclude the DBSCAN noise cluster before scoring

DBSCAN labels ungrouped points as a single noise cluster. Naively counting "unique days a cluster appears on" over that noise cluster will make nearly every scattered, one-off fire look artificially "persistent," because the noise bucket aggregates unrelated fires from all over the country across many different days. The fix is to exclude the noise cluster before computing persistence, so "persistent" only ever describes a genuine, spatially tight, recurring cluster — which is the only kind of persistence that's actually interesting (e.g., a flare stack that shows up in roughly the same 500m for weeks).

### 6.3 A genuine ML layer, not just spatial joins

Spatial-join classification plus DBSCAN clustering is legitimate engineering but it's rules, not learning — thin ground for a PS titled "AI-Based." We add one real learned component: an anomaly/confidence score for the "unclassified + persistent" cases, trained on features like fire radiative power trend over time, day/night detection ratio, distance to nearest mapped zone of any kind, and detection frequency — using a lightweight model (e.g. an Isolation Forest or a gradient-boosted classifier) trained on the historical FIRMS download rather than hand-set thresholds. The goal isn't a state-of-the-art model — it's being able to say, honestly, "we trained a model on historical detections, here's what features it uses, here's how we validated it" instead of "if not X and not Y, then Z."

### 6.4 Multi-satellite resilience

Suomi NPP (the satellite behind the VIIRS_SNPP_NRT dataset) is expected to reach end-of-life around October 2026 — plausibly within our own build/demo window. We query **all three current VIIRS sources** (Suomi NPP, NOAA-20, NOAA-21) and merge them, rather than depending on one. This is also a stronger technical story: "we designed for satellite handover, not just for today's data source" is exactly the kind of forward-thinking detail that plays well in a technical Q&A.

### 6.5 Accuracy validation methodology

We keep a small, hand-verified table of known major Indian industrial sites (steel plants, refineries) as ground truth. Before every demo, we run classification against current data and report how many of these known sites are correctly classified as "industrial" — this becomes a simple, honest precision statement we can put on a slide ("N/N known industrial sites correctly identified"), instead of an unverifiable accuracy claim. This is a cheap, high-value addition: it's the difference between "we think it works" and "here's the number."

### 6.6 The flagging feature, made real

The original handoff mentioned "flag for NTRO investigation" as a talking point but never gave it a data model, an endpoint, or a UI surface. We fix that structurally: unclassified + persistent + above a minimum anomaly-confidence threshold is a first-class object in our data model (Section 8) with its own API endpoint and its own dedicated panel in the UI, not a filter on the general fire list.

### 6.7 Attribution and compliance

OpenStreetMap data is ODbL-licensed and requires visible attribution ("© OpenStreetMap contributors"); Mapbox likewise requires attribution unless on a paid plan that waives it; NASA requests citation when its data is used in a derived product. We bake a persistent attribution footer into the dashboard from day one rather than bolting it on later — it's a five-minute task now and a credibility point with any judge who happens to know these licenses.

### 6.8 Demo resilience

The ingestion layer always writes to a local cache before anything downstream touches the data, and we maintain a checked-in "seed" dataset (a known-good snapshot of FIRMS + OSM data) that the whole system can run against with zero network access. The demo runs off this seed by default; live fetching is a "look, it's actually live" bonus we can show only if venue wifi cooperates.

---

## 7. File & Project Structure

The structure below is deliberately **layered by responsibility, not by data source** — routers, services, ML, and scheduling are separated so that a judge (or a teammate six weeks from now) can find "where does classification actually happen" without reading the whole codebase. It's also deliberately **not** microservices — one FastAPI process, one frontend build — because that's the right level of complexity for what a 6-person student team can build, test, and confidently explain in a live Q&A.

```
EMBER-fire-detection/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── routers/
│   │   │   ├── fires.py
│   │   │   ├── zones.py
│   │   │   ├── stats.py
│   │   │   ├── flags.py
│   │   │   └── health.py
│   │   ├── services/
│   │   │   ├── firms_client.py
│   │   │   ├── osm_client.py
│   │   │   ├── geocode.py
│   │   │   ├── classifier.py
│   │   │   ├── persistence.py
│   │   │   └── flagging.py
│   │   ├── ml/
│   │   │   ├── features.py
│   │   │   ├── train.py
│   │   │   ├── infer.py
│   │   │   └── artifacts/
│   │   ├── scheduler.py
│   │   └── core/
│   │       ├── logging.py
│   │       └── cache.py
│   ├── data/
│   │   ├── seed/
│   │   ├── raw/
│   │   └── processed/
│   ├── tests/
│   │   ├── test_classifier.py
│   │   ├── test_persistence.py
│   │   ├── test_flagging.py
│   │   └── test_api.py
│   ├── scripts/
│   │   ├── seed_demo_data.py
│   │   ├── fetch_historical.py
│   │   └── validate_known_sites.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── main.jsx
│   │   ├── App.jsx
│   │   ├── api/
│   │   │   └── client.js
│   │   ├── components/
│   │   │   ├── map/
│   │   │   │   ├── FireMap.jsx
│   │   │   │   ├── HeatmapLayer.jsx
│   │   │   │   └── ZoneOverlay.jsx
│   │   │   ├── sidebar/
│   │   │   │   ├── Sidebar.jsx
│   │   │   │   ├── StatsCards.jsx
│   │   │   │   ├── FilterPanel.jsx
│   │   │   │   └── TrendChart.jsx
│   │   │   ├── popup/
│   │   │   │   └── FirePopup.jsx
│   │   │   ├── flags/
│   │   │   │   ├── FlaggedPanel.jsx
│   │   │   │   └── FlagDetail.jsx
│   │   │   └── common/
│   │   │       └── AttributionFooter.jsx
│   │   ├── pages/
│   │   │   └── Dashboard.jsx
│   │   └── hooks/
│   │       ├── useFires.js
│   │       └── useFlags.js
│   ├── public/
│   └── package.json
└── docs/
    ├── architecture.md
    ├── api-contract.md
    ├── validation-results.md
    └── demo-script.md
```

### 7.1 Backend — file-by-file rationale

**`app/main.py`** — the FastAPI application object itself: mounts all routers, configures CORS (frontend needs to call it from a different port/origin), and registers startup/shutdown hooks (e.g., starting the scheduler when the app boots, closing the DB connection cleanly on shutdown). This file should stay thin — it's composition, not logic.

**`app/config.py`** — a single source of truth for environment-driven settings (API keys, database URL, fetch interval, feature flags like "use seed data only"). Centralizing this means the demo-mode-vs-live-mode switch (Section 6.8) is one setting, not something scattered across the codebase.

**`app/database.py`** — the SQLAlchemy engine and session setup. SQLite for development and the demo (zero setup, file-based, trivial to reset between rehearsals); the connection string is the only thing that would need to change to point at Postgres later, which is exactly the "scalability path" we want to be able to describe to judges without having actually built it.

**`app/models.py`** — the ORM table definitions (Section 8 describes these conceptually). This is the shape of what we persist, independent of how it's exposed over the API.

**`app/schemas.py`** — Pydantic request/response models. Kept separate from `models.py` deliberately: the database shape and the API's public shape are allowed to diverge (e.g., we might store more internal debug fields than we ever expose), and that separation is a basic hygiene point worth having ready if asked about it.

**`app/routers/fires.py`** — the general fire-listing and single-fire-detail endpoints; the main data feed for the map.

**`app/routers/zones.py`** — serves the cached industrial/forest/farmland polygons so the frontend can draw zone overlays on the map without re-querying Overpass.

**`app/routers/stats.py`** — aggregate numbers for the sidebar (counts by type, by state, trend over time).

**`app/routers/flags.py`** — the dedicated endpoint(s) for "Unexplained Persistent Sources" — deliberately its own router, not a filtered view inside `fires.py`, because this is our headline feature and it should be structurally visible as its own concern, both in the code and in a code walkthrough with judges.

**`app/routers/health.py`** — a basic liveness check; useful during the finale to quickly confirm the backend is up before a demo, and it's an easy, expected piece of API hygiene.

**`app/services/firms_client.py`** — everything related to talking to the NASA FIRMS API: building the request URLs for each satellite source, parsing the returned CSV, and merging multi-satellite results into one normalized frame.

**`app/services/osm_client.py`** — Overpass query construction and execution for industrial/forest/farmland polygons, plus conversion of the returned data into a format GeoPandas can consume. Includes retry/timeout handling, since public Overpass instances are known to be unreliable on large queries.

**`app/services/geocode.py`** — Nominatim reverse-geocoding calls (to resolve state/district names), with the required rate limiting (max 1 request/second) and local caching so we never re-geocode a coordinate we've already resolved.

**`app/services/classifier.py`** — the corrected spatial-join classification logic described in 6.1: industrial / wildfire / agricultural / unclassified, in that priority order, with the farmland join actually implemented this time.

**`app/services/persistence.py`** — the corrected DBSCAN-based persistence detection described in 6.2, with the noise-cluster exclusion fixed.

**`app/services/flagging.py`** — the decision logic that takes "unclassified + persistent" candidates, runs them through the ML confidence score (from `app/ml/infer.py`), and decides whether a case is promoted to a first-class flagged record. This is where the classification, persistence, and ML layers actually converge into our headline feature — kept separate from all three so that "why was this flagged" is answerable by reading one file.

**`app/ml/features.py`** — feature engineering for the anomaly-scoring model described in 6.3 (FRP trend, day/night ratio, distance to nearest zone, detection frequency).

**`app/ml/train.py`** — the offline training script, run once before the demo against the historical FIRMS download, producing a saved model artifact. Not run live during the demo.

**`app/ml/infer.py`** — loads the trained artifact and scores new detections at request time; this is the only ML file that runs in the live request path.

**`app/ml/artifacts/`** — the trained model file(s) themselves, checked in (or documented as a build step) so the demo never depends on retraining under pressure.

**`app/scheduler.py`** — the periodic job definitions (fetch FIRMS, refresh OSM zones, recompute stats) using APScheduler, with the "use seed data instead of live fetch" switch respected here.

**`app/core/logging.py`** — consistent logging setup across the app; small, but genuinely useful during a live demo when something needs debugging fast.

**`app/core/cache.py`** — the local-cache read/write helpers that back the offline-resilience strategy in 6.8 — this is the piece of infrastructure that makes "seed data" and "live data" interchangeable from the rest of the app's point of view.

**`data/seed/`** — a checked-in, known-good snapshot of processed FIRMS + OSM data, used as the default data source for the demo. This directory is our single biggest insurance policy against a bad-wifi finale.

**`data/raw/`** — untouched downloads from external sources, kept only for debugging/re-processing, not committed to version control.

**`data/processed/`** — cleaned, normalized data ready to load into the database.

**`tests/`** — unit tests specifically targeting the two bugs we fixed (`test_classifier.py`, `test_persistence.py`) plus the flagging logic and basic API contract tests. This doesn't need to be exhaustive, but having tests that explicitly prove the noise-cluster bug is fixed is a good, concrete thing to point to if a judge asks about code quality.

**`scripts/seed_demo_data.py`** — a one-command script that populates the database from `data/seed/`, meant to be run right before any demo or rehearsal so the state is always known-good.

**`scripts/fetch_historical.py`** — the one-off bulk historical download used to build training data for the ML layer and to build the seed dataset in the first place.

**`scripts/validate_known_sites.py`** — runs classification against the known-industrial-sites table (Section 6.5) and prints/exports the accuracy summary used in the pitch deck.

### 7.2 Frontend — file-by-file rationale

**`src/App.jsx` / `src/main.jsx`** — application entry point and top-level layout.

**`src/api/client.js`** — a single place that knows the backend's base URL and handles all HTTP calls; keeps components free of fetch/error-handling boilerplate.

**`src/components/map/FireMap.jsx`** — the core Mapbox map instance and fire-point layer.

**`src/components/map/HeatmapLayer.jsx`** — the heatmap visualization layered under the point markers.

**`src/components/map/ZoneOverlay.jsx`** — renders the industrial/forest/farmland polygons on the map so a viewer can visually see _why_ a point was classified the way it was — this directly supports the "here's our reasoning, not a black box" narrative.

**`src/components/sidebar/*`** — the stats cards, filter controls, and trend chart, each isolated so they can be built and tested independently by different teammates.

**`src/components/popup/FirePopup.jsx`** — the click-to-inspect detail popup for an individual detection.

**`src/components/flags/FlaggedPanel.jsx` and `FlagDetail.jsx`** — the dedicated UI surface for our headline feature: a list of currently flagged "Unexplained Persistent Sources" and a detail view showing why each one was flagged (confidence score, nearest known zone and its distance, detection history). This is the component pair most worth polishing, since it's what we'll spend the most demo time on.

**`src/components/common/AttributionFooter.jsx`** — the persistent NASA/OSM/Mapbox attribution described in 6.7, present on every view.

**`src/pages/Dashboard.jsx`** — composes the map, sidebar, and flagged panel into the single main view.

**`src/hooks/useFires.js` / `useFlags.js`** — data-fetching hooks that isolate the "how do we get and refresh this data" concern from the components that just render it.

### 7.3 `docs/`

**`architecture.md`** — a short, judge-readable version of Section 5, kept in the repo so a judge who clones it (or an evaluator reading the submission) doesn't have to reconstruct the design from code alone.

**`api-contract.md`** — the endpoint list from Section 9, kept in sync with the actual routers.

**`validation-results.md`** — the output of `validate_known_sites.py`, i.e. our accuracy story, kept as a living document updated before each demo/rehearsal.

**`demo-script.md`** — the actual click-by-click script for the live demo (Section 13.2), rehearsed against, not written once and forgotten.

---

## 8. Data Model (Conceptual)

We keep this to four core tables/entities, deliberately minimal:

- **Fire detections** — one row per NASA FIRMS record: coordinates, brightness/FRP values, acquisition date/time, satellite/source, confidence, and the derived fields our analysis layer writes back (`fire_type`, `state`, `cluster_id`, `is_persistent`).
- **Zones** — cached OSM polygons (industrial, forest, farmland), each with a name where available, used both for classification and for the map overlay.
- **Persistent sources** — one row per DBSCAN cluster that passed the (corrected) persistence check, aggregating its member detections, first/last seen dates, and days-active count.
- **Flagged cases** — one row per persistent source that is _also_ unclassified and above the ML confidence threshold: the promoted, first-class "Unexplained Persistent Source" record, carrying the anomaly score, the nearest known zone and its distance, and an optional analyst case-note field.

Keeping "persistent sources" and "flagged cases" as separate entities (rather than collapsing everything into one boolean flag on the fire table, as the original handoff did) is what makes the flagging feature demonstrable as its own thing in the UI and defensible as its own thing in a technical Q&A.

---

## 9. API Surface (Conceptual)

| Endpoint              | Purpose                                                                                       |
| --------------------- | --------------------------------------------------------------------------------------------- |
| `GET /api/fires`      | Filterable list of classified fire detections (by type, state, date, confidence, persistence) |
| `GET /api/fires/{id}` | Full detail for one detection, for the map popup                                              |
| `GET /api/zones`      | Cached industrial/forest/farmland polygons, for the map overlay                               |
| `GET /api/stats`      | Aggregate counts, by-state breakdown, and trend data for the sidebar                          |
| `GET /api/flags`      | List of currently flagged Unexplained Persistent Sources                                      |
| `GET /api/flags/{id}` | Full detail for one flagged case, including its confidence score and reasoning                |
| `GET /api/health`     | Liveness check                                                                                |

This table doubles as `docs/api-contract.md` and should be kept accurate as the source of truth the frontend team builds against — updating one without the other is a common source of last-minute integration pain.

---

## 10. Development Roadmap

Mapped against the real SIH calendar: team/PS registration closes **6 September 2026**, internal college hackathons run **September–October 2026**, and the national Grand Finale is a **36-hour non-stop build-demo-pitch**. That means almost everything below needs to exist _before_ the finale — the 36 hours are for integration, polish, and rehearsal, not for building the core pipeline from scratch.

**Phase 0 — Before internal hackathon registration.** Confirm PS choice, re-check sih.gov.in for any expanded official description, form the team, assign workstreams (Section 11), and get NASA FIRMS + Mapbox API keys.

**Phase 1 — Data foundation.** Build `firms_client.py`, `osm_client.py`, `geocode.py`, the database schema, and the seed-data pipeline. Run `fetch_historical.py` early — this data feeds both the seed dataset and the ML training set, so it's a blocking dependency for later phases.

**Phase 2 — Classification & persistence engine.** Implement the corrected `classifier.py` and `persistence.py`, with unit tests specifically proving the two bugs from Section 6 are fixed. Run `validate_known_sites.py` for the first time here and iterate until the known-sites accuracy number is something we're proud to put on a slide.

**Phase 3 — ML layer.** Feature engineering, offline training, and `infer.py`. This can run partly in parallel with Phase 2 once the historical dataset exists.

**Phase 4 — Flagging logic.** `flagging.py` ties classification, persistence, and the ML confidence score together into the flagged-cases table. This is the last backend piece before the API is fully meaningful, since flags are downstream of everything else.

**Phase 5 — API layer.** Wire up all routers against the now-complete analysis layer.

**Phase 6 — Frontend.** Map, sidebar, popup, and — with real priority — the Flagged Panel. Build against the API contract in Section 9 from day one so backend and frontend can proceed in parallel rather than serially.

**Phase 7 — Integration & offline hardening.** Confirm the whole stack runs cleanly off `data/seed/` with zero network access. This phase is not optional and should not be left until the finale.

**Phase 8 — Demo rehearsal & pitch.** Build the deck and demo script in parallel with Phase 6–7, not after. Rehearse the actual click-path multiple times, including a rehearsal with wifi deliberately disabled.

**During the 36-hour finale itself:** integration fixes, visual polish, live-vs-seed-data toggling rehearsal, and pitch practice — not new core features. If the team arrives at the finale still building classification logic, that's a scope-management failure, not a time-management one.

---

## 11. Team & Workstream Allocation

SIH requires a 6-member team with at least one female member — a fixed eligibility rule, not a suggestion. Rather than assigning names (adjust to your actual team), here's a workstream split that keeps the critical path moving without anyone blocking on anyone else for too long:

- **Data & ingestion (1–2 people):** `firms_client.py`, `osm_client.py`, `geocode.py`, seed pipeline. This has to start first, since Phases 2–4 all depend on it.
- **Analysis engine (1–2 people):** classifier, persistence, flagging logic, and the ML layer. This is the technically hardest and most differentiating work — pair your strongest problem-solvers here.
- **Backend/API (1 person, can overlap with analysis):** routers, schemas, database wiring.
- **Frontend (1–2 people):** map, sidebar, and — with priority — the Flagged Panel.
- **Presentation & validation (1 person, ideally someone comfortable presenting):** owns `validate_known_sites.py` output, the pitch deck, and the demo script from day one — not assembled at the last minute from whatever the other four workstreams produce.

Everyone should be able to explain the whole architecture in the Q&A, not just their own piece — judges do ask individual team members questions outside their stated role.

---

## 12. Risk Register

| Risk                                                                                           | Likelihood  | Impact                       | Mitigation                                                                                              |
| ---------------------------------------------------------------------------------------------- | ----------- | ---------------------------- | ------------------------------------------------------------------------------------------------------- |
| Public Overpass API times out or rate-limits on large India-wide queries                       | Medium–High | High if hit live during demo | Fetch zone polygons well in advance, cache them, never re-fetch live during a demo                      |
| NASA FIRMS rate limit (5,000 transactions/10 min) hit during development                       | Low         | Low                          | Batch/schedule fetches; not a concern at hackathon data volumes if respected                            |
| Suomi NPP satellite end-of-life disrupts VIIRS_SNPP_NRT mid-project                            | Medium      | Medium                       | Multi-satellite ingestion from day one (6.4)                                                            |
| Venue wifi fails or is too slow for live API calls during the finale                           | Medium      | High                         | Full offline seed-data mode, rehearsed in advance (6.8, Phase 7)                                        |
| Classification accuracy looks weak/unconvincing to judges                                      | Medium      | High                         | Known-sites validation baseline built and iterated on early (6.5), not produced last-minute             |
| "AI" component seen as too thin for the PS title                                               | Medium      | High                         | Genuine trained ML layer built in Phase 3, with an honest explanation of its features and training data |
| A judge notices the official PS has no detailed brief and asks how we chose our interpretation | Low–Medium  | Low if handled well          | Section 2.3's assumptions are stated proactively in the pitch, framed as deliberate scoping decisions   |
| Team member unavailable at finale                                                              | Low         | Medium                       | Everyone understands the full architecture (Section 11), not just their own piece                       |

---

## 13. Presentation & Pitch Strategy

### 13.1 Idea/shortlisting PPT (the 2–3-minute read)

Structure: problem (in NTRO's own institutional terms, per Section 2.2) → why existing approaches (manual cross-referencing) fall short → our approach, led with the flagging feature, not the map → a concrete number from the validation baseline → architecture diagram (from `docs/architecture.md`) → honest scope/future-work slide. Follow whatever official SIH PPT template is current at submission time — evaluators are reading dozens of these back-to-back and reward exactly the structure they expect.

### 13.2 Grand Finale demo script

Lead with the Flagged Panel, not the map. Show one specific flagged case end-to-end: where it is, why it's unclassified, why it's persistent, what its anomaly score is, and what an analyst would do next. Only after that, zoom out to the full map and stats view to show breadth. Close with the known-sites validation number and the honest scope/future-work slide. Rehearse this exact path — including a run with wifi off — at least twice before the finale.

---

## 14. Open Questions to Resolve Before/During Build

- Has NTRO published an expanded description for EMBER since this plan was written? Check before finalizing scope.
- What confidence threshold should promote a persistent-unclassified case to a full "flag"? This needs to be tuned against real data in Phase 3/4, not guessed in advance.
- Do we have a Mapbox account tier that permits keeping the free attribution requirement, or do we need a specific plan? Confirm before frontend work starts on `AttributionFooter.jsx`.
- Final call on SQLite vs. a lightweight Postgres for the actual demo environment — SQLite is recommended for simplicity unless a specific reason (e.g. concurrent write load during rehearsal) argues otherwise.
