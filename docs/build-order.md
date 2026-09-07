# Build Order — Living Progress Tracker

This is the actual, file-by-file execution order for the solo build. Update the checkboxes as you go — this document is meant to change constantly, unlike `data-model.md`/`api-contract.md`, which are frozen.

**Rule for every phase:** don't start prompting for the next phase's files until the current phase's tests pass and you've re-checked its files against the naming glossary. Checkpoints happen between phases, not between every single file — that's granular enough to catch drift without slowing you to a crawl.

**Rule for every prompt within a phase:** feed it (1) `data-model.md` and/or `api-contract.md`, whichever is relevant, (2) the literal, already-written code of the 1–3 files it directly imports from or calls — never a description of them, (3) the relevant `RULES.md` section, and (4) an explicit instruction that if a name it needs isn't defined in what you gave it, it should ask rather than invent one.

## Phase 0 — Foundation docs

- [x] `AGENTS.md`
- [x] `RULES.md`
- [x] `data-model.md`
- [x] `api-contract.md`

## Phase 1 — Backend foundation (nothing else can start before this)

- [x] `app/config.py`
- [x] `app/database.py`
- [x] `app/models.py` — build directly from `data-model.md`, field for field
- [x] `app/schemas.py`

## Phase 2 — Ingestion

- [x] `app/services/firms_client.py`
- [x] `app/services/osm_client.py`
- [x] `app/services/geocode.py`
- [x] `scripts/fetch_historical.py`
- [x] `scripts/seed_demo_data.py`

## Phase 3 — Analysis engine

- [x] `app/services/classifier.py` — must include the farmland join and the `pending`/`unclassified` distinction from `data-model.md`
- [x] `app/services/persistence.py` — must exclude the DBSCAN noise cluster (`cluster_id == -1`) before scoring, per `RULES.md` §5
- [x] `app/services/flagging.py`
- [x] `scripts/validate_known_sites.py`

## Phase 4 — ML layer

- [x] `app/ml/features.py` — implemented and fixed across a full review round; holding unchecked pending the Phase 4 final audit, same gate every other phase got
- [x] `app/ml/known_sites_fixture.py` — shared fixture-construction module for `train.py` and `scripts/validate_known_sites.py`; not part of the original file list, added here since it exists and needs the same audit
- [x] `app/ml/train.py` (run once, offline, against the historical data from Phase 2)
- [x] `app/ml/infer.py`

## PROTOTYPE MODE ACTIVE — see docs/context.md and docs/prototype-plan.md

Phases below (5-full, 6-full) are the original full-project scope, DEFERRED not deleted. Active work is the two "Prototype" sections just below.

## Prototype Phase 5 — API (1-day scope)

- [ ] `app/routers/health.py`
- [ ] `app/routers/fires.py` (simplified filters, no full pagination envelope)
- [ ] `app/routers/zones.py`
- [ ] `app/routers/flags.py` (GET only, no PATCH/export)
- [ ] `app/routers/stats.py` (basic counts only)
- [ ] `app/main.py` (model artifact already exists — just load it)
- `app/scheduler.py` — CUT for prototype, see prototype-plan.md

## Prototype Phase 6 — Frontend (1-day scope, dark minimal UI)

- [ ] `src/api/client.js`
- [ ] `src/components/FireMap.jsx` (map + markers + zone overlay, combined)
- [ ] `src/components/Sidebar.jsx` (stats, combined)
- [ ] `src/components/FlaggedPanel.jsx`
- [ ] `src/pages/Dashboard.jsx`

## Phase 5-full — API (deferred, original prompts in docs/phase5-prompts.md)

- [ ] `app/routers/fires.py`
- [ ] `app/routers/zones.py`
- [ ] `app/routers/stats.py`
- [ ] `app/routers/flags.py`
- [ ] `app/routers/health.py`
- [ ] `app/main.py`
- [ ] `app/scheduler.py`

## Phase 6-full — Frontend (deferred)

- [ ] `src/api/client.js` (everything else in the frontend depends on this one)
- [ ] `src/hooks/useFires.js`, `src/hooks/useFlags.js`
- [ ] `src/components/map/FireMap.jsx`, `HeatmapLayer.jsx`, `ZoneOverlay.jsx`
- [ ] `src/components/sidebar/*`
- [ ] `src/components/flags/FlaggedPanel.jsx`, `FlagDetail.jsx`
- [ ] `src/components/common/AttributionFooter.jsx`
- [ ] `src/pages/Dashboard.jsx`

## Phase 7 — Integration & offline hardening

- [ ] Confirm the whole stack runs with zero network access, purely off `data/seed/`
- [ ] Confirm `/api/health` correctly reports `mode: seed` vs `mode: live`

## Phase 8 — Demo rehearsal & pitch

- [ ] `docs/demo-script.md` drafted and rehearsed at least twice, including once with wifi off
- [ ] `docs/validation-results.md` current as of the latest `classifier.py` change
