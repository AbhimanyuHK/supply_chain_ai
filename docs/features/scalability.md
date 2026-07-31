# Scalability at Target Scale

The original spec's target scale — 1,000+ stores, 10,000+ terminals,
millions of inventory rows — surfaced six real bottlenecks once actually
analyzed against the running code, not just theorized about. All six were
fixed together, since several share the same root cause (over-fetching
data the run doesn't actually need).

## Fix 1 — Master data over-fetched every terminal regardless of scope

`app/services/master_data_service.py::load()` ran `terminal_repo.list_all()`
unconditionally, then loaded inventory/fleet/distance-matrix for *every*
terminal — even for a 5-store scope, at 10,000+ terminals this meant
loading up to roughly a million inventory rows for a run that only needed
a handful.

**Fix**: when `request.store_ids` is set, query `distance_matrix` scoped
by those store ids *first* (`DistanceMatrixRepository.list_by_store_ids`),
derive the actually-relevant `terminal_ids` from that result, then load
terminals/fleet/inventory from the narrowed set — reusing the
already-fetched distance rows as the snapshot's `distance_matrix` rather
than re-querying them.

This is **behavior-preserving, not just faster**: the
{doc}`Supply Planning Agent <../agents/supply-planning-agent>` already
excludes any terminal with no `distance_matrix` route to a shortage's
store from candidacy, so a terminal unreachable from every scoped store
was never usable anyway. When `store_ids` is unset ("all stores"), the
old `list_all()` path is kept unchanged — correctly, since there's no
scope to narrow by.

## Fix 2 — Unbounded SQL `IN (...)` clauses (a real bug, not just slow)

`app/database/repositories/base.py::_list_by_column_in` and the custom
multi-`.in_()` queries in `inventory_repository.py`,
`distance_matrix_repository.py`, and `demand_history_repository.py` all
bound `.in_(values)` with no batching. SQLite's default ~999
bound-parameter limit per statement means passing 10,000 ids would
**outright fail** — not degrade gracefully, fail.

**Fix**: a `chunked(seq, size)` generator in `base.py`.

| Call site | Lists bound per statement | Chunk size |
|---|---|---|
| `StoreRepository.list_by_ids`, `TerminalRepository.list_by_ids`, `ProductRepository.list_by_ids`, `FleetRepository.list_by_terminal_ids` | 1 | 500 |
| `InventoryRepository.list_for_locations_and_products` | 3 (terminal/store/product ids) | 300 each |
| `DistanceMatrixRepository.list_by_terminal_and_store_ids`, `DemandHistoryRepository.list_recent` | 2 | 450 each |

No de-duplication is needed when merging chunked results — each id lives
in exactly one chunk of its own list, so chunk-pair result sets are
disjoint by construction. Terminal and store rows are queried in separate
statements per location type rather than OR'd together, so chunking
independently can't produce duplicate rows either.

## Fix 3 — In-memory O(shortages × inventory) scan in Supply Planning

`supply_planning_agent.py` re-scanned the full inventory list for every
shortage. **Fix**: pre-group `snapshot.inventory` into
`dict[product_id, list[InventoryRead]]` once per run instead.

## Fix 4 — Sequential per-shortage LLM calls (the biggest single change)

`plan_supply_node` called the LLM once per shortage, sequentially. At
scale (thousands of shortages) this means thousands of sequential
round-trips per run — instantly exceeding a tight per-minute cap. Gemini's
confirmed real limit is 5 requests/minute for Flash models; it choked on
a *single* shortage's 3 calls during earlier testing on this project.

**Fix**: batch multiple shortages into one LLM prompt/response instead of
one call per shortage (`Settings.supply_planning_batch_size`, default 25)
— new `_LLMShortagePlan`/`_LLMBatchPlanningResponse` schemas, one prompt
per batch with each shortage keeping its own block (including its own
retry-violation note), matched back by `(store_id, product_id)`. Batches
run with bounded concurrency
(`asyncio.Semaphore(Settings.llm_max_concurrent_requests)`, default 3 —
not 1, since Groq, the default provider, has generous limits; Gemini
free-tier operators should override this to 1 via `.env`). See
{doc}`../agents/supply-planning-agent` for the full mechanics.

```{note}
**Documented gap, not solved**: a semaphore bounds *simultaneity*, not
requests-per-minute. Many batches at concurrency=1 can still fire
sequentially within one minute and exceed a tight RPM cap. True RPM
pacing (a token-bucket/sleep helper) is a reasonable follow-up, out of
scope here since Groq — the primary path — doesn't need it.
```

## Fix 5 — `PlanningRun.master_data_snapshot` size at scale

Storing the full input snapshot as one JSON column per run is fine at a
few KB (demo-scale data) but could be many MB at millions of inventory
rows — and master data is re-derivable from the database anyway, unlike
the genuinely unique LLM-driven stage outputs.

**Fix**: `Settings.persist_full_master_data_snapshot` (default `True`).
When set to `False` at real scale, a `master_data_row_counts` column
(row counts + `business_rules.model_dump()`) is stored instead, leaving
`master_data_snapshot` `NULL`. See
{doc}`persistence-and-audit-trail` for how this interacts with viewing
historical runs.

## Fix 6 — No task queue for concurrent runs

Confirmed via `app/api/routers/` that no `/optimize`-style endpoint
exists yet — the only current callers of `run_planning_workflow` are the
single-process/single-user Streamlit dashboard and tests, so this isn't a
currently-exposed problem. This project also has an explicit prior
decision not to add Redis speculatively, and a real task queue typically
needs a broker.

**Decision: documented, not built.** When the REST `/optimize` endpoint
is eventually built, use FastAPI `BackgroundTasks` to kick off the run
and return `202` immediately with the run's id, with the client polling
`GET /planning-runs/{id}`
(`PlanningRunRepository.get_by_id` already exists) for status — zero new
infrastructure, since `PlanningRun` already tracks status transitions.
Running multiple ASGI worker processes (an ops decision, not new code)
gives real process-level concurrency on top of that. A real queue (`arq`
+ a lightweight broker) is the right call only once that's genuinely not
enough.
