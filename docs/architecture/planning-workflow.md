# The Planning Workflow

The whole platform is one LangGraph `StateGraph` with nine nodes and a single
conditional feedback loop, defined in `app/agents/graph.py`. This page
describes the graph shape and the state that flows through it; each node's
own logic has a dedicated page under {doc}`../agents/overview`.

## The graph

```text
START
  → load_master_data
  → forecast_demand
  → analyze_inventory
  → plan_supply  ←───────────────────┐
  → allocate                          │ (replan)
  → optimize_cost                     │
  → validate_constraints ─────────────┘
      │ (valid, or replanning exhausted)
      ↓
  → review_decision
  → recommend_final
  → END
```

Built by `build_graph()` and compiled once (no checkpointer configured — see
{doc}`../features/persistence-and-audit-trail` for what that trade-off
means for failed runs). Every edge except the one leaving Constraint
Validation is a plain, unconditional edge; that one is
`graph.add_conditional_edges(..., route_after_validation)`, which returns
either `"recommend_final"` (via a synthetic pass-through) or
`"plan_supply"` depending on the validation outcome — see
{doc}`../agents/constraint-validation-agent` for the exact decision tree.

## `PlanningState`

`app/agents/state.py` defines the `TypedDict` threaded through every node.
Each node reads whatever prior stages produced and returns a partial dict
LangGraph merges into the running state:

| Key | Populated by | Type |
|---|---|---|
| `request` | Caller (before the graph starts) | `PlanningRequest` |
| `master_data` | Load Master Data | `MasterDataSnapshot` |
| `demand_forecast` | Demand Forecast | `DemandForecastResult` |
| `inventory_analysis` | Inventory Analysis | `InventoryAnalysisResult` |
| `supply_planning` | Supply Planning | `SupplyPlanningResult` |
| `allocation` | Allocation | `AllocationResult` |
| `cost_optimization` | Cost Optimization | `CostOptimizationResult` |
| `constraint_validation` | Constraint Validation | `ConstraintValidationResult` |
| `decision_review` | Decision Review | `DecisionReviewResult` |
| `final_recommendation` | Final Recommendation | `FinalRecommendation` |
| `trace` | Every node, appended | `list[str]` |
| `errors` | Every node, appended | `list[str]` |
| `replanning_attempts` | Constraint Validation | `int` |

`trace` and `errors` use LangGraph's `operator.add` reducer, so each node
*appends* its own line rather than overwriting what the previous node wrote
— a full run ends with exactly nine trace lines (one per node), which is
what `tests/test_agents_graph.py` asserts on the happy path.

## `run_planning_workflow()`

The single public entry point (`app/agents/graph.py`), used identically by
`scripts/run_planning_workflow.py`, `streamlit_app.py`, and every test:

```python
async def run_planning_workflow(
    request: PlanningRequest, *, force_rerun: bool = False
) -> PlanningState:
```

Before touching the graph at all, it:

1. Loads master data once standalone (`load_master_data_node({"request": request})`)
   and computes a {doc}`data fingerprint <../features/idempotency-and-caching>`
   from the real snapshot.
2. Unless `force_rerun=True`, checks for a prior successful run with the same
   scope, data fingerprint, and reasoning engine — a hit returns instantly,
   with **no graph execution and no new LLM calls**.
3. On a miss, seeds the already-loaded snapshot into `initial_state`
   (`load_master_data_node` memoizes, so the graph's own execution of that
   node reuses it instead of querying the database again) and runs
   `graph.ainvoke(initial_state)`.
4. Persists the result (success or failure) as a `PlanningRun` row — see
   {doc}`../features/persistence-and-audit-trail`.

## LLM calls across the graph

Only four of the nine nodes ever call a reasoning engine — the rest are
pure deterministic computation against real data, following the
{doc}`overview`'s "LLM judges, code decides" principle:

| Node | Calls LLM? | What it asks the LLM to do |
|---|---|---|
| Load Master Data | No | — |
| Demand Forecast | No (calls HuggingFace Chronos instead) | — |
| Inventory Analysis | No | — |
| **Supply Planning** | Yes | Propose ranked candidate terminals per shortage batch |
| **Allocation** | Yes | Rank three already-computed scenarios with rationale |
| Cost Optimization | No | — |
| Constraint Validation | No | — |
| **Decision Review** | Yes | Score each valid scenario 0-100 across six real metrics |
| **Final Recommendation** | Yes | Synthesize a business explanation, risk assessment, and confidence score |

A scope with zero shortages makes **zero LLM calls** end to end — every
LLM-calling node short-circuits when there's nothing to reason about, which
is what lets {doc}`../getting-started/quickstart` verify the full pipeline
mechanically with no API key at all.

## The replanning loop, concretely

Constraint Validation is the only node that can send execution backward.
When none of the three allocation scenarios pass validation and replanning
attempts remain, it writes the violations onto
`state["constraint_validation"]` and routes back to `plan_supply`. Supply
Planning's `_prior_violation_messages_by_shortage` reads that on the next
pass, groups violations by `(store_id, product_id)`, and folds them into
that shortage's next LLM prompt — without this, a retry would just re-ask
the identical question and likely get the identical answer. See
{doc}`../agents/constraint-validation-agent` and
{doc}`../agents/supply-planning-agent` for the full detail on each side of
this loop.

`Settings.max_replanning_attempts` (default 2) bounds it — once exhausted,
Constraint Validation proceeds best-effort with its best-scoring scenario,
appends the unresolved violations to `state["errors"]`, and the graph
continues forward rather than looping forever.
