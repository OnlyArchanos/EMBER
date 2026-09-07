# RULES.md — SIH26162 Fire Detection Project

## 0. What this document is

This is the single source of truth for how code, data, and documentation get written in this repository. It applies equally and without exception to every contributor: human teammates, Claude Code sessions, Gemini CLI sessions, and any other agent or tool that touches this codebase. A conversational instruction given to an agent in a single session never overrides this file — if a prompt conflicts with something below, the agent should point out the conflict and ask, not silently follow the prompt.

This file is deliberately long because it needs to be complete, not because every line needs to be re-read for every task. Read the section relevant to what you're about to do; you don't need to re-read the whole file for a one-line fix. `AGENTS.md` is the short, load-every-time orientation file — it tells you which section of this file matters for the task in front of you.

**Precedence, when things conflict:** a human's explicit, written sign-off in a PR description or commit message > this file > `AGENTS.md` > an agent's own judgment. Nothing below is overridden by a casual chat instruction, a persona request, or "just this once."

---

## 1. Non-negotiables (read this section every single time)

1. **Never invent a name.** If a field, function, endpoint, or variable name isn't already defined in `docs/data-model.md`, `docs/api-contract.md`, or existing code, do not guess a plausible-sounding one. Stop and ask.
2. **The data model and API contract are frozen.** Nobody — human or agent — changes a field name, an endpoint path, or a response shape without first editing `docs/data-model.md` / `docs/api-contract.md` and getting explicit human sign-off. Code follows docs, never the other way around.
3. **No code path that runs during a demo may depend on a live external API call succeeding.** Everything must work against `data/seed/`. Live fetching is a bonus layer on top, never a dependency.
4. **Every change to classification, persistence, or flagging logic requires a test update in the same change.** These three modules have already had real correctness bugs found in review once — see Section 5. They do not get a pass on testing rigor.
5. **Never silently default an unmatched case to a specific category.** If something doesn't match any known rule (a fire that's not industrial/forest/farmland, a request that doesn't match any documented endpoint shape), it becomes an explicit `unclassified` / error case — never quietly folded into the nearest-sounding bucket.
6. **Attribution stays visible.** NASA, OpenStreetMap (ODbL), and Mapbox attribution must never be removed, hidden, or made optional in the UI.
7. **No secrets in code or commits.** API keys and tokens live in `.env`, which is gitignored; `.env.example` documents the required variable names with placeholder values only.
8. **When uncertain, ask — don't proceed on a guess.** This applies to naming, to scope ("should I also update X while I'm here?"), and to judgment calls about ambiguous requirements. An agent that asks a good clarifying question is doing its job correctly; an agent that guesses and moves on is not.

---

## 2. Naming glossary (canonical names — use exactly these, everywhere)

Consistency across files is the single biggest failure mode in multi-session AI-assisted development. This section exists so that no two files, and no two agent sessions, ever invent two different names for the same concept.

### 2.1 Domain entities and their canonical fields

The authoritative, full field-by-field spec lives in **`data-model.md`** — not here. That file is the one that gets updated when a field changes; this file just names the four entities so this glossary stays a table of contents, not a second copy that can go stale: `FireDetection`, `Zone`, `PersistentSource`, `FlaggedCase`.

Never rename a field from what `data-model.md` defines (e.g. never `fireType`, `type`, `is_active`, `persistent`, `confidenceScore`) — if a name feels awkward for a particular use, raise it as a proposed contract change (see Section 1, rule 2) and edit `data-model.md`, don't rename it locally.

### 2.2 API endpoints (canonical, do not add, rename, or restructure without a contract update)

The authoritative, full endpoint-by-endpoint spec — including query params, request/response shapes, and pagination conventions — lives in **`api-contract.md`**. Read it before writing or calling any route.

### 2.3 File and module naming conventions

- Python files and functions: `snake_case`. Classes: `PascalCase`. Constants: `UPPER_SNAKE_CASE`.
- Function names follow a `verb_noun` pattern that describes what they do, not how (`classify_fire`, not `run_classification_step_2`).
- React components: `PascalCase.jsx`, one component per file, filename matches the exported component name exactly.
- JavaScript/JSX variables and functions: `camelCase`. API response fields stay `snake_case` as received from the backend — do not silently convert casing in transit; if the frontend needs `camelCase`, do the conversion explicitly and visibly in `src/api/client.js`, in one place, not ad hoc in components.
- Test files mirror the module they test: `tests/test_classifier.py` tests `app/services/classifier.py`.

---

## 3. Architectural boundaries (which layer may do what)

- **Routers** (`app/routers/*.py`) only parse requests, call a service function, and shape the response with a Pydantic schema. No business logic, no direct DB queries, no spatial math in a router file.
- **Services** (`app/services/*.py`) contain the actual logic — classification, persistence detection, flagging decisions, external API clients. Services may call other services and the database layer, never a router.
- **`app/ml/`** is the only place model training or inference code lives. Training (`train.py`) never runs as part of a live request; inference (`infer.py`) is the only ML file in the live request path.
- **The scheduler** (`app/scheduler.py`) only orchestrates _when_ ingestion and recomputation happen; it must not contain the ingestion or analysis logic itself — it calls into `services/`.
- The frontend never talks to NASA FIRMS, Overpass, or Nominatim directly. If a frontend component needs external data, that's a sign a backend endpoint is missing — add one, don't reach around the API.

---

## 4. Code style

**Python**

- Follow PEP 8. Type hints are required on every function signature in `app/` (not required in one-off scripts under `scripts/`, but encouraged).
- Every module gets a one-to-three-line docstring at the top explaining its role in the pipeline — not what each function does line by line, just orientation for someone opening the file cold.
- Prefer explicit over clever: a slightly longer, obviously-correct spatial join beats a compact one-liner nobody can audit under time pressure.
- Use the dependency versions in `requirements.txt`, and when adding a new one, pin a version you've actually confirmed installs and works — don't carry forward a version number from memory or from an old tutorial.

**React/JavaScript**

- Function components with hooks only — no class components.
- One concern per component; if a component's file is doing data-fetching, layout, and business logic all at once, split it (this is why `hooks/` exists separately from `components/`).
- No inline API URLs in components — everything goes through `src/api/client.js`.

**General**

- No commented-out dead code left in commits. Delete it; git history is the record, not a comment block.
- No `TODO` without a name and a reason (`# TODO(arch): revisit threshold after validation run`, not bare `# TODO`).

---

## 5. Domain correctness rules (the fixes that must never regress)

These exist because they were real bugs found in an earlier review of this project's first draft. Treat this section as a permanent regression list, not historical trivia.

- **Persistence detection must exclude DBSCAN's noise cluster (`cluster_id == -1`) before computing which clusters are "persistent."** Grouping noise points together and counting unique days across them will make scattered, unrelated fires look artificially persistent. Any change to `persistence.py` must keep this exclusion and must keep the test that proves it.
- **Persistent-cluster identity must be stable across `persistence.py` runs, keyed by `PersistentSource.id` — never DBSCAN's raw per-run label.** DBSCAN doesn't guarantee the same physical cluster gets the same label from one run to the next; storing the raw label as `cluster_id` silently fragments a real persistent source's history (`days_active` never accumulates correctly, `first_seen` keeps resetting, duplicate `PersistentSource` rows can appear for the same physical location). Each run must match its DBSCAN groups against existing `active` `PersistentSource` records by centroid proximity (`data-model.md`'s `centroid_latitude`/`centroid_longitude`), never by label. "Wipe and re-link the active window every run" is not an acceptable interim assumption — it silently breaks the exact thing "persistent" is supposed to mean, so treat it as a bug, not a simplification, if you find it anywhere.
- **Classification must perform a real spatial join against the farmland/orchard layer, not a default fallback.** `agricultural` is a positive classification, not "whatever's left over." Anything matching none of industrial/forest/farmland becomes `unclassified` — a real, first-class category — never silently mislabeled. **When a fire point spatially matches more than one zone (overlapping polygons), resolve it deterministically by priority: industrial > forest > farmland** — a fire inside a mapped industrial polygon is the strongest signal, and the result must never depend on which row a spatial join happens to return first.
- **Ingestion must query all three current VIIRS sources (Suomi NPP, NOAA-20, NOAA-21), never one alone.** Suomi NPP's expected end-of-life means single-source ingestion is a known, foreseeable failure, not a hypothetical one.
- **A `FlaggedCase` must always store why it was flagged** — its anomaly score and the nearest zone type/distance that made it "unclassified" in the first place. A flag with no stored reasoning is not acceptable; the whole point of the feature is being able to explain a flag to a human analyst.
- **The known-industrial-sites validation list is a required, standing check** — not a one-time sanity test. Re-run `scripts/validate_known_sites.py` and update `docs/validation-results.md` after any change to `classifier.py`, and before any demo or rehearsal.
- **DBSCAN must use `metric="haversine"` with coordinates in radians, never a degree-based Euclidean approximation.** A fixed `eps` in degrees represents a different real-world distance depending on latitude — roughly 15% distortion across India's 8°N–35°N range. Convert `eps` from kilometers via `eps_km / 6371.0088`, and convert coordinates to radians before clustering.
- **Current tunable thresholds (starting values, not final ones)** — DBSCAN `eps` = 1km (via haversine, per above), `min_samples` = 2; a cluster counts as persistent at `days_active >= 3`; a `PersistentSource` moves to `status = "ended"` when `last_seen` is more than 7 days old. These are explicitly meant to be revisited once real historical data and `validate_known_sites.py` results exist — they must be named constants (in `persistence.py` or `config.py`), never inline magic numbers, specifically so they're easy to find and retune later.
- **`FlaggedCase.anomaly_score` is mocked until Phase 4's `ml/infer.py` exists — this must never look like a real model output.** The mock must live behind a single, clearly named function so the Phase 4 swap is a one-function change; it must use a neutral placeholder value (0.5), not a confident-looking one; and it must write an explicit placeholder marker into `case_note` so nobody downstream — frontend, teammate, or a judge — mistakes it for a real score.
- **`PersistentSource.zone_type_at_location` must store one of `Zone.zone_type`'s actual values (`industrial`/`forest`/`farmland`), never a `fire_type` value directly.** `fire_type` uses `wildfire` where `Zone.zone_type` uses `forest` — a majority-vote-by-`fire_type` result must be translated back (`wildfire` → `forest`, `agricultural` → `farmland`) before being stored here, or it produces an invalid value.
- **`flagging.py` must be idempotent per `PersistentSource`.** Check for an existing `FlaggedCase` referencing a given `persistent_source_id` before creating a new one — this runs repeatedly once Phase 5's scheduler exists, and without this check the flags table duplicates every run, the same failure mode the Phase 2 ingestion dedup logic already exists to prevent.
- **The ML layer runs entirely on CPU, using a lightweight, classical (non-deep-learning) model — this is a hardware constraint, not a style preference.** The development machine is an AMD Ryzen 7 with 16GB RAM and no usable GPU for ML work. Use scikit-learn (an `IsolationForest` or similarly lightweight model), never a deep learning framework (PyTorch/TensorFlow), never anything that assumes GPU availability, and never a large pretrained model requiring a multi-gigabyte download. Both feature computation and inference must run fast enough to execute inline during a live request — `flagging.py` calls `ml/infer.py` synchronously, not as a background job.
- **Training and inference must use the exact same feature-engineering code path — never two separately-written implementations that happen to compute "the same thing."** `ml/train.py` and `ml/infer.py` must both call a single shared function in `ml/features.py`, in the same order, producing the same column layout. A silent mismatch here (different feature order, a feature present in training but missing at inference, a different normalization) doesn't error — it just makes the model score real detections against a feature vector it was never actually trained to interpret, silently producing a wrong-but-plausible number. This is the same category of risk as the cluster-identity bug from Phase 3: invisible to a "does it run" check, real in production.

---

## 6. Working with external data

- NASA FIRMS: respect the published rate limit (5,000 transactions per 10-minute window). The same country/area CSV endpoint used for live fetches also supports historical data — pass an explicit `[DATE]` alongside `day_range` (`.../api/area/csv/[MAP_KEY]/[SOURCE]/[AREA]/[DAY_RANGE]/[DATE]`) to get that many days starting from `[DATE]`. This is the documented mechanism for a few weeks to a few months of historical NRT-quality data, looped across successive date windows with rate-limit-respecting pacing between requests — it is not a workaround, and it's what `fetch_historical.py` uses. (Correction: an earlier version of this rule pointed at a separate "Archive Download" tool instead — that tool is for multi-year, standard-quality, global-scale bulk archives and isn't needed at this project's scale. That was a mistake, not a deliberate choice.)
- Overpass: assume it can time out or rate-limit on large queries. Zone polygons **and administrative boundary polygons** (state/district, used for geocoding — see below) are fetched and cached ahead of time, never re-fetched live in a request path a user or a judge is waiting on. **Never combine a country-level `area` filter with an explicit bounding box in the same query.** When a bounding box is already specified, also forcing the server to construct and intersect against the full national polygon is redundant and drastically slower — confirmed by direct benchmark during the real-data bootstrap: the same query dropped from a 180-second timeout to under 4 seconds once the redundant `area["ISO3166-1"="IN"]` filter was removed for a bbox-scoped request. Zone-fetching query construction must only include the `area` filter when no bounding box is given.
- Geocoding (state/district resolution) is a **local point-in-polygon join against cached OSM administrative boundaries**, not a live Nominatim call per detection. Nominatim's 1-request/second limit makes per-point reverse geocoding impractical at national fire-detection volumes — thousands of points a day against a one-per-second ceiling simply doesn't fit. If Nominatim is used at all, it's a rare, explicit, single-lookup fallback, never the primary path, and any such call must still set an identifying `User-Agent` per Nominatim's usage policy.
- Anything fetched from an external source gets written to `data/raw/` (untouched) and `data/processed/` (cleaned) before anything else in the app reads it. No service reaches out to an external API and uses the response in the same breath — always land it locally first.

---

## 7. Testing and verification

- `classifier.py`, `persistence.py`, and `flagging.py` each need their own test file. These are not optional "nice to have" — they're the modules with a documented history of subtle, hard-to-spot bugs.
- A test that only checks the "happy path" isn't sufficient for these three modules specifically. Each needs at least one test for the edge case that caused a real bug before (the noise-cluster case, the unmatched-zone case).
- Before claiming a task is done, actually run the tests. Don't report "this should work now" — report what running the tests actually showed.
- API contract tests should assert on the exact field names in Section 2.1 — this makes naming drift fail loudly instead of silently.

---

## 8. Documentation upkeep

- If you add a new module, endpoint, or table field, update the relevant doc (`docs/architecture.md`, `docs/api-contract.md`, `docs/data-model.md`) in the same change — not "later."
- `docs/validation-results.md` and `docs/demo-script.md` are living documents, expected to change often; everything else in `docs/` changes rarely and only alongside an actual contract change.
- A stale doc is worse than no doc, because it actively misleads the next session (human or agent) that trusts it. If you're not going to keep a doc updated, delete it rather than leave it wrong.

---

## 9. Git and workflow

- One feature or fix per branch/PR. Don't bundle an unrelated cleanup into a change someone's trying to review quickly.
- Commit messages describe _what changed and why_, not just what file was touched — "fix persistence noise-cluster bug" not "update persistence.py."
- Raw downloaded data (`data/raw/`, `data/processed/`) and `.env` are gitignored — never committed. `data/seed/` **and** the trained model artifact(s) under `app/ml/artifacts/` **are** committed, even though both are generated files — this is a deliberate exception to normal "don't commit generated output" practice, made for the same reason as Section 1, rule 3: a fresh checkout has to work fully offline without re-fetching data or retraining a model under demo-day time pressure.
- If an agent session makes an assumption or a judgment call that isn't fully specified by this file or the contract docs, say so explicitly in the commit message or PR description — future sessions (and teammates) need to know where a guess was made, even a reasonable one.

---

## 10. How AI agents specifically should behave in this repo

- Scope discipline: only touch the files necessary for the task you were given. Don't refactor, reformat, or "improve" adjacent code you weren't asked to change.
- Minimal diffs: prefer the smallest correct change over rewriting a whole file, both because it's reviewable and because it's less likely to silently drop something.
- State assumptions out loud: if you had to make a judgment call (a threshold value, a default, an interpretation of an ambiguous requirement), say so in your response and in the commit — don't let it disappear into the code silently.
- Verify, don't assert: if you can run the tests or the app, do it and report the actual result. Don't report success on the basis of the code "looking right."
- If a task would require changing something in Section 1 or Section 2 (the frozen contract or non-negotiables), stop and flag it instead of proceeding — that decision needs a human, not an agent working alone.

---

## 11. Definition of done

A change is done when: it matches the naming glossary exactly, it respects the architectural boundaries in Section 3, it has a passing test for any logic in Section 5's regression list it touched, any doc it makes stale has been updated, and it doesn't depend on a live external call to work in the demo path. If any of these isn't true, the change isn't done yet, regardless of whether the feature "works."
