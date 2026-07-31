"""LangGraph workflow definition.

Nine nodes, with the first feedback loop: Load Master Data -> Demand
Forecast -> Inventory Analysis -> Supply Planning -> Allocation -> Cost
Optimization -> Constraint Validation -> Decision Review -> Final
Recommendation. If Constraint Validation can't find any valid scenario, it
routes back to Supply Planning (capped by `max_replanning_attempts`) instead
of on to Decision Review - see
`constraint_validation_agent.route_after_validation`.

This completes every Phase 1 agent in the spec's 13-agent list. Only Phase
2's Fleet Assignment, Route Planning, and ETA Prediction/Exception Handling
agents remain, gated behind `Settings.fleet_module_enabled`.

Every invocation of `run_planning_workflow` is persisted as a `PlanningRun`
audit row (see `app/models/entities.py` and `_persist_run` below) - which
reasoning engine produced it, the full input scope, every intermediate
stage's output, and a success/failure status. This is unconditional and
transparent to callers: the return value is unchanged, and a persistence
failure never masks the real result or exception.

`run_planning_workflow` is also idempotent by default: it loads master data
once up front, fingerprints it (`app/services/fingerprint.py`), and - unless
`force_rerun=True` - looks for an existing successful `PlanningRun` for the
exact same scope + data + reasoning engine before doing any real work. A hit
returns that prior result immediately, with zero new LLM calls and no new
row written (nothing was computed). This is a business requirement, not
just an optimization: the same scope run against unchanged data with the
same engine should always produce the same plan, never a different one due
to LLM sampling randomness or simply because someone clicked "Run" twice.
Known limitation, not solved here: the fingerprint captures data
determinism, not code/prompt/settings version - a stale hit could still
serve a plan computed under different application logic if the app was
redeployed between two calls.
"""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from loguru import logger

from app.agents.allocation_agent import allocate_node
from app.agents.constraint_validation_agent import route_after_validation, validate_constraints_node
from app.agents.cost_optimization_agent import optimize_cost_node
from app.agents.decision_review_agent import review_decision_node
from app.agents.demand_forecast_agent import forecast_demand_node
from app.agents.final_recommendation_agent import recommend_final_node
from app.agents.inventory_analysis_agent import analyze_inventory_node
from app.agents.master_data_agent import load_master_data_node
from app.agents.state import PlanningState
from app.agents.supply_planning_agent import plan_supply_node
from app.core.config import get_settings
from app.core.llm import get_active_model_name
from app.database.repositories import PlanningRunRepository
from app.database.session import AsyncSessionLocal
from app.models.entities import PlanningRun, PlanningRunStatus
from app.schemas.planning import PlanningRequest
from app.schemas.planning_run import PlanningRunRead
from app.services.fingerprint import compute_data_fingerprint


def build_graph() -> CompiledStateGraph:
    graph = StateGraph(PlanningState)

    graph.add_node("load_master_data", load_master_data_node)
    graph.add_node("forecast_demand", forecast_demand_node)
    graph.add_node("analyze_inventory", analyze_inventory_node)
    graph.add_node("plan_supply", plan_supply_node)
    graph.add_node("allocate", allocate_node)
    graph.add_node("optimize_cost", optimize_cost_node)
    graph.add_node("validate_constraints", validate_constraints_node)
    graph.add_node("review_decision", review_decision_node)
    graph.add_node("recommend_final", recommend_final_node)

    graph.add_edge(START, "load_master_data")
    graph.add_edge("load_master_data", "forecast_demand")
    graph.add_edge("forecast_demand", "analyze_inventory")
    graph.add_edge("analyze_inventory", "plan_supply")
    graph.add_edge("plan_supply", "allocate")
    graph.add_edge("allocate", "optimize_cost")
    graph.add_edge("optimize_cost", "validate_constraints")
    graph.add_conditional_edges(
        "validate_constraints", route_after_validation, {"replan": "plan_supply", "end": "review_decision"}
    )
    graph.add_edge("review_decision", "recommend_final")
    graph.add_edge("recommend_final", END)

    return graph.compile()


_STAGE_KEYS = (
    "master_data",
    "demand_forecast",
    "inventory_analysis",
    "supply_planning",
    "allocation",
    "cost_optimization",
    "constraint_validation",
    "decision_review",
    "final_recommendation",
)


async def _persist_run(
    request: PlanningRequest,
    *,
    state: PlanningState | None,
    error: Exception | None,
    data_fingerprint: str | None,
) -> PlanningRun | None:
    """Writes one `PlanningRun` audit row for this invocation, returning the
    created row (or `None` if persistence itself failed).

    On success, every stage's real output is stored (`state[key].model_dump(mode="json")`
    per stage) - except `master_data`, which is stored in full only if
    `Settings.persist_full_master_data_snapshot` is True (the default); when False
    (opt-in at real scale, where the full snapshot could be many MB), only row
    counts + business rules are stored instead (`master_data_row_counts`),
    leaving `master_data_snapshot` NULL. On failure, only scope/provider/error
    are stored - `graph.ainvoke()` has no checkpointer configured, so a mid-run
    exception propagates with no partial state to persist (see `PlanningRun`'s
    docstring).

    Never raises: a DB write hiccup must not crash or mask the actual planning
    result/exception, so any failure here is only logged.
    """
    try:
        settings = get_settings()
        fields: dict = {
            "planning_date": request.planning_date,
            "store_ids": sorted(request.store_ids) if request.store_ids else None,
            "product_ids": sorted(request.product_ids) if request.product_ids else None,
            "demand_history_window_days": request.demand_history_window_days,
            "scope_key": request.scope_key(),
            "data_fingerprint": data_fingerprint,
            "optimization_objective": request.optimization_objective,
            "llm_provider": settings.llm_provider,
            "llm_model": get_active_model_name(),
            "request_payload": request.model_dump(mode="json"),
        }

        if error is not None:
            fields["status"] = PlanningRunStatus.FAILED
            fields["error_message"] = str(error)
        else:
            assert state is not None
            fields["status"] = PlanningRunStatus.SUCCESS
            fields["trace"] = state.get("trace", [])
            fields["errors"] = state.get("errors", [])
            fields["replanning_attempts"] = state.get("replanning_attempts", 0)
            for key in _STAGE_KEYS:
                value = state.get(key)
                if value is None:
                    continue
                if key == "master_data" and not settings.persist_full_master_data_snapshot:
                    fields["master_data_row_counts"] = {
                        "stores": len(value.stores),
                        "terminals": len(value.terminals),
                        "products": len(value.products),
                        "inventory": len(value.inventory),
                        "demand_history": len(value.demand_history),
                        "fleet": len(value.fleet),
                        "distance_matrix": len(value.distance_matrix),
                        "business_rules": value.business_rules.model_dump(mode="json"),
                    }
                    continue  # master_data_snapshot stays NULL in this mode
                column = "master_data_snapshot" if key == "master_data" else key
                fields[column] = value.model_dump(mode="json")

        async with AsyncSessionLocal() as session:
            run = await PlanningRunRepository(session).create(**fields)
            await session.commit()
            return run
    except Exception as exc:  # noqa: BLE001 - persistence must never break a real run
        logger.warning(f"Failed to persist planning run audit row: {exc}")
        return None


async def run_planning_workflow(request: PlanningRequest, *, force_rerun: bool = False) -> PlanningState:
    # Load master data once, standalone, before deciding whether to run the
    # graph at all - both to fingerprint it for the idempotency cache lookup
    # below, and (on a cache miss) to seed the graph's initial state so
    # `load_master_data_node` doesn't load it a second time (see that node's
    # docstring in master_data_agent.py). Wrapped in its own try/except since
    # a failure here (e.g. a bad DATABASE_URL) is just as real a failed run as
    # one raised mid-graph, and needs the same FAILED audit row.
    try:
        preload = await load_master_data_node({"request": request})
    except Exception as exc:
        await _persist_run(request, state=None, error=exc, data_fingerprint=None)
        raise

    snapshot = preload["master_data"]
    data_fingerprint = compute_data_fingerprint(snapshot)

    if not force_rerun:
        cached = await _find_cached_success(request, data_fingerprint)
        if cached is not None:
            logger.info(
                f"Idempotent hit: reusing PlanningRun #{cached.id} for this exact scope, data, "
                "and reasoning engine - no new computation, no new LLM calls."
            )
            cached_state = cached.to_state_dict()
            cached_state["planning_run_id"] = cached.id
            return cached_state

    graph = build_graph()
    initial_state: PlanningState = {
        "request": request,
        "master_data": snapshot,
        "trace": [],
        "errors": [],
        "replanning_attempts": 0,
    }

    try:
        result = await graph.ainvoke(initial_state)
    except Exception as exc:
        await _persist_run(request, state=None, error=exc, data_fingerprint=data_fingerprint)
        raise

    run = await _persist_run(request, state=result, error=None, data_fingerprint=data_fingerprint)
    result["planning_run_id"] = run.id if run is not None else None
    return result


async def _find_cached_success(request: PlanningRequest, data_fingerprint: str) -> PlanningRunRead | None:
    """The idempotency cache lookup, isolated so a DB hiccup here can never
    block a run - on failure this just logs and falls through to a fresh
    computation, same "never break the real run" philosophy as `_persist_run`.
    """
    try:
        settings = get_settings()
        async with AsyncSessionLocal() as session:
            row = await PlanningRunRepository(session).find_success_by_scope_data_and_engine(
                scope_key=request.scope_key(),
                data_fingerprint=data_fingerprint,
                llm_provider=settings.llm_provider,
                llm_model=get_active_model_name(),
            )
        return PlanningRunRead.model_validate(row) if row is not None else None
    except Exception as exc:  # noqa: BLE001 - see docstring
        logger.warning(f"Idempotency cache lookup failed, proceeding with a fresh run: {exc}")
        return None
