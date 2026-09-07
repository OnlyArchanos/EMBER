# AGENTS.md — SIH26162 Fire Detection Project

This file is intentionally short. It's the map, not the manual — read `RULES.md` for the actual coding standards, naming conventions, and domain-correctness rules before writing any code. This file just tells you where things are and what not to break.

## What this is

An AI-based system for India that ingests NASA satellite fire/thermal-hotspot data, classifies each detection (industrial / wildfire / agricultural / unclassified) against OpenStreetMap zone data, detects persistent (non-transient) heat sources over time, and flags unexplained persistent sources for human review. Built for Smart India Hackathon problem statement SIH26162 (sponsor: NTRO).

## Before you touch anything

1. Read `RULES.md` Section 1 (non-negotiables) and Section 2 (naming glossary). Every session, not just the first.
2. `docs/data-model.md` and `docs/api-contract.md` are frozen contracts. Code conforms to them; they don't get edited to match whatever code happened to be written.
3. If a name, field, or endpoint you need isn't in the contract docs or existing code, ask — do not invent one.
4. **If you're Antigravity specifically**: `RULES.md` is 13.9K characters, over the 12,000-char cap on files placed in `.agents/rules/`. It's meant to be read as a normal referenced doc per point 1 above, not dropped into `.agents/rules/` as-is — don't split it without checking with a human first, since section boundaries matter for how it's read.

## Tech stack

- **Backend:** Python, FastAPI, SQLAlchemy, SQLite (dev/demo), GeoPandas, scikit-learn.
- **Frontend:** React (Vite), Mapbox GL JS.
- **Scheduling:** APScheduler.
- Use current stable versions when installing — don't copy a version pin from an old doc without checking it's still current.

## Directory map

```
backend/app/
  main.py            entrypoint, router mounting, startup/shutdown
  config.py          env-driven settings, incl. demo-mode vs live-mode switch
  database.py        SQLAlchemy engine/session
  models.py          ORM tables — see RULES.md §2.1 for canonical field names
  schemas.py         Pydantic request/response models
  routers/           thin HTTP layer only — no business logic (RULES.md §3)
  services/          all business logic: ingestion clients, classifier,
                     persistence, flagging
  ml/                feature engineering, training (offline only), inference
  ml/known_sites_fixture.py — single source of truth for constructing the
                     known-industrial-sites test fixture; both train.py's
                     validation hook and scripts/validate_known_sites.py
                     import from here, never reimplement it locally
  scheduler.py       orchestrates when services run, contains no logic itself
backend/data/
  seed/              committed known-good dataset — the offline demo depends on this
  raw/ processed/    gitignored, built at runtime
backend/tests/        one test file per service module in RULES.md §5's list
backend/scripts/       seed_demo_data.py, fetch_historical.py, validate_known_sites.py
frontend/src/
  api/client.js       the only place that calls the backend
  components/map/     map, heatmap, zone overlay
  components/sidebar/ stats, filters, trend chart
  components/flags/   the Flagged Panel — the project's headline feature
  hooks/               data-fetching, kept separate from rendering
docs/
  architecture.md, api-contract.md, data-model.md   — frozen contracts + design
  build-order.md, validation-results.md, demo-script.md — living documents, expect churn
  build-order.md tracks exactly which file to prompt for next — check it first
  phase1-prompts.md, phase2-prompts.md, phase3-prompts.md, phase4-prompts.md,
  phase5-prompts.md — ready-to-use build + review prompts; later phases
  should get their own prompts file following the same pattern
  bootstrap-real-data.md — one-off operational runbook for producing the
  first real trained ML artifact and a real data/seed/ dataset from live
  NASA FIRMS / OSM data; run once when ready, not part of a build phase
  full-audit-prompt.md — whole-codebase checkpoint (does it run, naming
  consistency, future-proofing, cross-file logic bugs); re-run after every
  phase, not just once
```

## Common commands

```
# backend
uvicorn app.main:app --reload
pytest
python scripts/seed_demo_data.py
python scripts/validate_known_sites.py

# frontend
npm run dev
npm run build
```

(Confirm these against `backend/requirements.txt` / `frontend/package.json` once they exist — this list reflects the intended setup, not a verified one yet.)

## Non-negotiables (full list in RULES.md §1)

- Nothing in the demo path depends on a live external API call succeeding — everything must run against `data/seed/`.
- Classification/persistence/flagging changes require a test update in the same change.
- No silent default categories — unmatched cases are `unclassified`, never folded into the nearest-sounding bucket.
- Attribution (NASA / OpenStreetMap ODbL / Mapbox) stays visible in the UI, always.

## When you're done with a change

Run the relevant tests and report the actual result. If any doc under `docs/` is now stale, update it in the same change. If you made a judgment call the contract didn't specify, say so in the commit message.
