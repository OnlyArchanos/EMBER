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
- **The scheduler** (`app/scheduler.py`) only orchestrates *when* ingestion and recomputation happen; it must not contain the ingestion or analysis logic itself — it calls into `services/`.
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
- **Classification must perform a real spatial join against the farmland/orchard layer, not a default fallback.** `agricultural` is a positive classification, not "whatever's left over." Anything matching none of industrial/forest/farmland becomes `unclassified` — a real, first-class category — never silently mislabeled.
- **Ingestion must query all three current VIIRS sources (Suomi NPP, NOAA-20, NOAA-21), never one alone.** Suomi NPP's expected end-of-life means single-source ingestion is a known, foreseeable failure, not a hypothetical one.
- **A `FlaggedCase` must always store why it was flagged** — its anomaly score and the nearest zone type/distance that made it "unclassified" in the first place. A flag with no stored reasoning is not acceptable; the whole point of the feature is being able to explain a flag to a human analyst.
- **The known-industrial-sites validation list is a required, standing check**, not a one-time sanity test. Re-run `scripts/validate_known_sites.py` and update `docs/validation-results.md` after any change to `classifier.py`, and before any demo or rehearsal.

---

## 6. Working with external data

- NASA FIRMS: respect the published rate limit (5,000 transactions per 10-minute window). Scheduled fetches, not on-demand ones triggered by user requests.
- Overpass: assume it can time out or rate-limit on large queries. Zone polygons are fetched and cached ahead of time, never re-fetched live in a request path a user or a judge is waiting on.
- Nominatim: max 1 request/second, and every request must set an identifying `User-Agent` — this is a term of their usage policy, not an optional nicety.
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
- Commit messages describe *what changed and why*, not just what file was touched — "fix persistence noise-cluster bug" not "update persistence.py."
- Trained model artifacts, raw downloaded data, and anything in `data/raw/` are gitignored. `data/seed/` is the one data directory that *is* committed, because the whole offline-demo strategy depends on it being present in every checkout.
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
