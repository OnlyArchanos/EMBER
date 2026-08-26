# SIH26162 — 1-Week Must-Learn Plan (By Role)

Scope rule for this whole document: if it isn't something someone will actually touch in this specific codebase (per `AGENTS.md`/`RULES.md`), it's not on the list, no matter how "good to know" it generally is. A week is enough to get someone from zero to genuinely useful on one workstream — not enough to also teach them things the project doesn't need.

## 0. Everyone, before anything else (half a day, max)

- **Git essentials**: clone, branch, commit, push, opening a pull request, and resolving a basic merge conflict. This isn't optional — six people committing to one repo without this will lose more time than the whole rest of this plan saves.
- **Command line basics**: moving around directories, running a Python script, activating a virtual environment (`venv`), running an npm command. Whatever OS someone's on, they need to be comfortable in a terminal, not just an IDE's GUI buttons.
- **The REST mental model**: what a GET request is, what JSON looks like, what status codes like 200/404/500 mean. Every single workstream below touches this at some point, even the ones that don't "do" the API.
- **Read `AGENTS.md` and `RULES.md` once, fully.** Not a technical skill, but it's the thing that keeps five people's work from silently diverging — treat it as mandatory reading, not optional context.

---

## A. Data & Ingestion workstream

*(pulls NASA FIRMS + OpenStreetMap data, hands it downstream)*

**Must-learn**
1. **Python fundamentals** (if not already solid): functions, dictionaries/lists, list comprehensions, `try/except` error handling, f-strings, reading environment variables.
2. **The `requests` library**: making a GET request, passing query parameters, handling a failed/timed-out request gracefully.
3. **Pandas basics**: what a DataFrame is, filtering rows, merging two DataFrames, reading a CSV into one — NASA FIRMS data arrives as CSV.
4. **GeoPandas fundamentals** — the single highest-leverage skill on this list for this role: what a GeoDataFrame is, the geometry column, reading GeoJSON, converting between coordinate reference systems (WGS84 lat/lon vs. a projected CRS), and spatial predicates (`within`, `intersects`). Nearly everything this workstream produces feeds directly into a spatial join later.
5. **Why CRS conversion matters**: lat/lon degrees can't be used directly for distance/buffer calculations — someone on this workstream needs to actually understand why, not just copy a `.to_crs()` call.
6. **Overpass QL basics**: enough to write a simple query pulling polygons by tag (e.g. `landuse=industrial`). Narrow, but there's no way around it for `osm_client.py`.

**Skip**: full GIS software (QGIS), raster/satellite imagery processing, anything Sentinel-related — that's explicitly cut from this project's scope.

---

## B. Analysis Engine workstream

*(classification, persistence detection, the ML layer — the project's actual differentiator)*

**Must-learn**
1. Everything in Data & Ingestion's Python/Pandas/GeoPandas list above — this role can't function without that foundation, so it's a shared prerequisite, not a separate track.
2. **DBSCAN, specifically**: what `eps` and `min_samples` control, and critically — what the `-1` "noise" label means and why it has to be excluded before scoring persistence. This isn't generic ML trivia here; it's the exact bug this project already had once.
3. **Basic clustering/anomaly-detection vocabulary**: the difference between a clustering algorithm (DBSCAN) and an anomaly-scoring model (e.g. Isolation Forest), what a "feature" is, and the difference between training and inference.
4. **Haversine/geodesic distance basics**: why `eps` needs to be in radians rather than raw degrees when clustering lat/lon points.
5. **Plain-language precision/recall**: enough to reason about "how many of our known industrial sites did we correctly classify," not a formal statistics course.

**Skip**: deep learning, PyTorch/TensorFlow, anything neural-network-shaped. The project deliberately uses lightweight, explainable models — a week spent on deep learning here is a week wasted.

---

## C. Backend/API workstream

**Must-learn**
1. **Python fundamentals + basic OOP** (classes) — both SQLAlchemy models and Pydantic schemas are class-based.
2. **FastAPI basics**: defining a path operation, path vs. query parameters, request/response validation with Pydantic, running the app with `uvicorn`, and the auto-generated `/docs` page (genuinely useful for testing endpoints without a frontend).
3. **SQLAlchemy ORM basics**: defining a model, opening a session, basic queries (filter, join). Nothing fancier is needed at this project's scale.
4. **Pytest basics**: writing a test function and an assertion. `RULES.md` requires tests on the core logic modules — whoever's on this workstream needs to actually be able to write them, not just call them "someone else's job."

**Skip**: Alembic migrations (overkill for a SQLite hackathon build), async DB drivers, and anything auth/middleware-related — authentication is explicitly out of scope for this build.

---

## D. Frontend workstream

**Must-learn**
1. **Modern JavaScript essentials**: `let`/`const`, arrow functions, destructuring, template literals, `async`/`await`, and `fetch` with Promises.
2. **React fundamentals**: components, JSX, props, `useState`, `useEffect`, conditional rendering, rendering lists with keys. That's genuinely the whole list for a dashboard this size — don't chase more than that.
3. **Mapbox GL JS basics**: initializing a map, adding a GeoJSON source and a layer, markers, popups, and click event handling — this is the map, the heatmap layer, and the zone overlay, which is most of this workstream's actual output.
4. **Flexbox/Grid CSS** — just enough for a dashboard layout (sidebar + map + panels). Not a deep CSS course.
5. **Consuming a REST API from React**: fetch, parsing JSON, basic loading/error states.

**Skip**: Redux or any state-management library (unnecessary at this app's size), TypeScript (adds friction this week unless someone's already fluent in it — don't pick it up mid-hackathon), Next.js/server-side rendering (this is a client-only dashboard against a separate API), and don't "learn a CSS framework" as a project — if you want Tailwind, pick it up by using it, not by studying it first.

---

## E. Presentation & Validation workstream

This role isn't really a "language to learn" — it's the ability to read and explain the system convincingly, so the time budget looks different:

1. Enough Python/pandas literacy to actually run `scripts/validate_known_sites.py` and read its output — not write new logic, just interpret results.
2. Plain-language precision/recall/confidence-score literacy, so a technical result can be translated into one clean sentence for a judge.
3. Enough comfort reading `docs/architecture.md` and `docs/api-contract.md` to field an unscripted "why did you build it this way" question.

Most of this person's week should actually go toward drafting the pitch deck and demo script alongside everyone else's build work, not toward a technical curriculum — see the Presentation & Pitch Strategy section of the implementation plan.

---

## Suggested pacing (applies to A–D)

- **Day 1**: Section 0 (everyone) + start the core language for your track (Python for A/B/C, JS for D).
- **Days 2–3**: the core framework fundamentals for your track (GeoPandas/scikit-learn for A/B, FastAPI/SQLAlchemy for C, React/Mapbox for D).
- **Days 4–5**: a small throwaway exercise that mirrors the real task — cluster a handful of made-up lat/lon points with DBSCAN (B), stand up one FastAPI endpoint backed by SQLite (C), render a few hardcoded markers on a Mapbox map (D), pull and print one page of real FIRMS data (A). Doing beats reading past this point.
- **Day 6**: re-read `RULES.md` now that the concepts actually mean something, and check your Day 4–5 exercise against the naming glossary and architectural boundaries in it.
- **Day 7**: pair up with whoever's one layer over or under you (e.g. frontend with backend) and do one real dry run across that connection point — this is where naming/contract mismatches surface early, while they're still cheap to fix.
