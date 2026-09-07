# Prototype Plan

## Why

Phases 1-4 took longer than planned (justified — real ML/clustering bugs were found) but that pace isn't repeatable for what's left on a 1-day budget. This scopes Phase 5+6 down to a working prototype.

**Unchanged:** Phases 1-4 code, all of RULES.md's domain-correctness rules, the real bootstrapped data/model. Prototype mode cuts scope on what's left to build, not rigor on what's already built.

**Changed:** process weight for new work — bigger, more directive prompts, one lighter review pass instead of per-file fresh-session audits. "Good enough for a demo" is acceptable here, clearly scoped to this phase only.

## Prototype Phase 5 — API

health, fires (simplified filters), zones, flags (GET only), stats (basic counts), main.py (model already exists, just load it). **Cut:** scheduler.py (not needed for seed-data-only demo), PATCH/export on flags, full pagination envelope.

## Prototype Phase 6 — Frontend

Dark, minimal UI. Recommend Tailwind for speed. Files: `api/client.js`, `FireMap.jsx` (map+markers+zones combined), `Sidebar.jsx` (stats combined), `FlaggedPanel.jsx` (the differentiator — keep this genuinely good), `Dashboard.jsx`. Everything else from the original plan (split hooks, FlagDetail, AttributionFooter as separate files) gets folded inline, not built separately.

## Path back to full project (when there's time)

1. Add `scheduler.py` — use `phase5-prompts.md` File 6 prompt unchanged.
2. Add PATCH/export to `flags.py` — use `phase5-prompts.md` File 5 prompt.
3. Add full pagination to `fires.py` — use `phase5-prompts.md` File 2 prompt.
4. Split combined frontend components back out per `AGENTS.md`'s original directory map, if the codebase grows enough to want it.
5. Run the deferred review/audit prompts against whatever the prototype actually built, since prototype build prompts are lighter than those reviews expect.

Nothing here invalidates the original full-project prompt files — they're deferred, not replaced.
