# Planning-Run Persistence & Audit Trail

Every `run_planning_workflow()` invocation is persisted as a
`PlanningRun` row — full traceability for which reasoning engine produced
a plan, the exact input scope, every intermediate stage's real output,
and a success/failure status. Before this feature, every run was fully
in-memory: the result was rendered once (by the CLI script or Streamlit)
and then discarded.

This is standard practice for an auditable AI-decision system — model and
version provenance, reproducibility, and incident investigation are
genuine requirements once an LLM is making real business recommendations,
not scope creep for this project.

## Scope matching via `scope_key`, not JSON equality

`PlanningRequest.scope_key()` (`app/schemas/planning.py`) hashes a
canonical JSON of the sorted scope (store/product ids, window,
`planning_date`, `optimization_objective`) with SHA-256, stored in
`PlanningRun.scope_key` and compared via plain string equality.

This is deliberate, not incidental. Comparing JSON columns directly for
equality is outright broken on Postgres (a plain `json` column has no
`=` operator — only `jsonb` does, and generic `sqlalchemy.JSON` doesn't
map to `jsonb`) and fragile on SQLite (byte-identical only for as long as
JSON serialization settings never change). A string-hash column
sidesteps both problems on every backend this project supports.

```{important}
This was a real bug caught by an independent plan-review pass before any
code was written — the original design compared JSON columns directly.
```

## The persistence hook

`app/agents/graph.py::run_planning_workflow` wraps `graph.ainvoke(...)`
in a try/except:

- **On success**: every stage's `.model_dump(mode="json")` is stored,
  along with `status=SUCCESS`, `scope_key`, `data_fingerprint`,
  `optimization_objective`, `llm_provider`/`llm_model`, and the full
  `trace`/`errors`/`replanning_attempts`.
- **On failure**: only scope/provider/error is stored — `error_message`
  is populated, every stage column stays `NULL`.

```{note}
No LangGraph checkpointer is configured, so a mid-run exception leaves no
partial state to persist — a failed row can only ever record what was
known *before* the graph started (scope, provider) plus the error itself.
Capturing partial trace data on failure would need a real
checkpointer/`astream`-based architecture change; not built, since the
failure itself (with its message) is already the actionable signal for
investigation.
```

The write itself is wrapped in its own try/except that only
`logger.warning(...)`s on failure — a database hiccup must never crash or
mask the actual planning result. The function's return value is
byte-identical to before this feature existed, so no caller needed to
change when it shipped.

## Writing real `Shipment` rows (Phase 2)

On a successful run with a non-empty `final_recommendation.shipment_plan`,
`_persist_run` also writes one real `Shipment` row per `ShipmentPlanLine`
— unconditionally, on **every** successful run, not gated behind
`Settings.fleet_module_enabled` or some future "approve this plan" step
(a deliberate business decision — this table should reflect what the
platform actually recommended). Each row is linked back via
`planning_run_id`, with `vehicle_id` from
{doc}`../agents/fleet-assignment-agent` (`None` when the fleet module is
disabled, or if a line couldn't be assigned a vehicle).

```{important}
This happens **inside the same transaction** as the `PlanningRun` audit
row itself, atomically — a deliberate trade-off, not an oversight. A
Shipment-insert failure now rolls back the whole transaction, meaning a
successful plan could end up with no audit row at all. This matches the
existing "never break the real run" philosophy (the caller's actual
result is still returned either way) but is a new failure mode worth
knowing about.
```

This only ever runs on a genuinely fresh computation — the idempotency
cache-hit path (see {doc}`idempotency-and-caching`) returns before
`_persist_run` is ever called, so a repeat call for the same scope never
writes a second, duplicate batch of Shipment rows for a `PlanningRun`
that already has them.

## Reconstructing a historical run

`PlanningRunRead.to_state_dict()` (`app/schemas/planning_run.py`)
rebuilds a dict shaped exactly like `PlanningState` from the stored JSON
columns (`MasterDataSnapshot.model_validate(...)` per non-null stage
column, etc.). This means `streamlit_app.py`'s render functions — for
input data, intermediate agent output, and the final plan — work
completely unchanged on a historical run. They index into whatever dict
they're handed and never know or care whether it came from a live run or
the database.

When `Settings.persist_full_master_data_snapshot=False` (see
{doc}`scalability`, Fix 5), `to_state_dict()` omits the `"master_data"`
key entirely rather than reconstructing a snapshot from row counts alone
— `streamlit_app.py::render_input_data` shows an informational message in
that case instead of crashing.

## Streamlit integration

Picking a scope with existing history shows those runs in the sidebar
(any engine, any objective); selecting one is a pure read — no LLM call,
no new `PlanningRun` row (see {doc}`idempotency-and-caching` for why
"Run" itself no longer always recomputes either). A
"🕘 Run history (all scopes)" expander browses beyond the currently
selected scope. A caption always states plainly whether the results on
screen are live or a specific historical run, so it's never ambiguous
which one is being viewed. See {doc}`../interfaces/streamlit-dashboard`.
