# Context — Read This First

## Mode: PROTOTYPE (not full project)

Pivoted after Phase 4 to a 1-day prototype, dark minimal UI. See `prototype-plan.md` for exact scope. Full-project plan is deferred, not deleted (`build-order.md`'s "-full" sections, `phase5-prompts.md`).

## Done — do not redo

Phases 1-4 complete and correctness-audited: config/db/models/schemas, ingestion (firms/osm/geocode), analysis (classifier/persistence/flagging), ML (features/train/infer). Real NASA FIRMS data bootstrapped for Gujarat + zone data for 5 states. Real trained model at `app/ml/artifacts/isolation_forest.pkl`, passes validation on all 5 known sites. Real seed data (249 fires, 41 zones) verified end-to-end on a fresh DB, zero live calls. 95/95 tests passing.

## Next

Prototype Phase 5 (API) then Prototype Phase 6 (frontend) — see `prototype-plan.md`, `build-order.md`.

## Key rules that still fully apply (see RULES.md)

- Cluster identity keyed by `PersistentSource.id`, never a raw DBSCAN label.
- Train/infer must share one feature code path.
- Overpass: never combine area filter + bbox.
- Fresh-session review, report-only, no in-flight fixes.
