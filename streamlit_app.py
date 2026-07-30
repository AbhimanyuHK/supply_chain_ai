"""Streamlit demo dashboard for the supply chain planning workflow.

Run with:
    venv\\Scripts\\streamlit.exe run streamlit_app.py

Shows the full 9-node LangGraph pipeline's input data, intermediate agent
outputs, and final recommendation in one place - built for demoing the
system to business stakeholders (what data went in, what each agent did,
what the final plan is), not as a production UI. Read-only / no auth; it
just triggers `run_planning_workflow` directly against whatever is in the
configured database (see README.md for seeding sample data first).
"""

import asyncio
import datetime
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.agents.graph import run_planning_workflow  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.llm import get_active_model_name, reset_llm_client_caches  # noqa: E402
from app.database.repositories import (  # noqa: E402
    PlanningRunRepository,
    ProductRepository,
    StoreRepository,
    TerminalRepository,
)
from app.database.session import AsyncSessionLocal, engine  # noqa: E402
from app.models.entities import PlanningRunStatus  # noqa: E402
from app.schemas.planning import PlanningRequest  # noqa: E402
from app.schemas.planning_run import PlanningRunRead  # noqa: E402

st.set_page_config(page_title="Supply Chain Planning Demo", layout="wide")


def _run_async(coro):
    """Runs `coro` via a fresh `asyncio.run()` call, then tears down every
    cached async resource (DB engine pool, LLM clients) before returning.

    Streamlit reruns this whole script - and so calls `asyncio.run()` fresh -
    on every click within one long-lived process, unlike the CLI script or the
    FastAPI server, which each keep a single event loop alive for their whole
    lifetime. A DB connection or LLM client left over from one call would
    otherwise carry a stale reference into the next call's brand new loop,
    surfacing as a confusing "Event loop is closed" failure. Tearing down here,
    while this loop is still open, means cleanup happens now rather than being
    left to garbage collection at some later, unpredictable point (possibly
    after the loop has already closed) - so every async entry point in this
    file (`load_scope_options`, `run_workflow`) goes through this.
    """

    async def _wrapped():
        try:
            return await coro
        finally:
            await engine.dispose()
            reset_llm_client_caches()

    return asyncio.run(_wrapped())


@st.cache_data(ttl=60)
def load_scope_options():
    async def _load():
        async with AsyncSessionLocal() as session:
            stores = await StoreRepository(session).list_all()
            products = await ProductRepository(session).list_all()
            terminals = await TerminalRepository(session).list_all()
            return (
                [(s.store_id, s.store_name) for s in stores],
                [(p.product_id, p.name) for p in products],
                len(terminals),
            )

    return _run_async(_load())


def run_workflow(request: PlanningRequest, *, force_rerun: bool = False) -> dict:
    return _run_async(run_planning_workflow(request, force_rerun=force_rerun))


def find_matching_runs(request: PlanningRequest) -> list[PlanningRunRead]:
    """Past runs for this exact scope (any engine), most recent first.

    Not cached (unlike `load_scope_options`) so a run just triggered from this
    same session shows up immediately, rather than waiting out a TTL.
    """

    async def _find():
        async with AsyncSessionLocal() as session:
            runs = await PlanningRunRepository(session).find_by_scope_key(request.scope_key())
            return [PlanningRunRead.model_validate(r) for r in runs]

    return _run_async(_find())


def list_recent_runs(limit: int = 20) -> list[PlanningRunRead]:
    """Past runs across every scope, most recent first."""

    async def _list():
        async with AsyncSessionLocal() as session:
            runs = await PlanningRunRepository(session).list_recent(limit=limit)
            return [PlanningRunRead.model_validate(r) for r in runs]

    return _run_async(_list())


def _load_run_into_session(run: PlanningRunRead) -> None:
    """Populates session state from a historical run - a pure read, no LLM/DB-write
    side effects. A failed run has no stage data to render (see `PlanningRun`'s
    docstring), so it's surfaced the same way a live failure is."""
    if run.status == PlanningRunStatus.FAILED:
        st.session_state["result"] = None
        st.session_state["error"] = run.error_message or "This run failed (no error message recorded)."
    else:
        state_dict = run.to_state_dict()
        if run.master_data_row_counts is not None:
            # Summary-only mode (Settings.persist_full_master_data_snapshot=False) -
            # render_input_data falls back to this when "master_data" is absent.
            state_dict["master_data_row_counts"] = run.master_data_row_counts
        st.session_state["result"] = state_dict
        st.session_state["error"] = None
    st.session_state["result_source"] = ("historical", run.id, run.created_at, run.llm_provider, run.llm_model)


def _df(models: list) -> pd.DataFrame:
    return pd.DataFrame([m.model_dump() for m in models])


def render_input_data(result: dict) -> None:
    if "master_data" not in result:
        # Settings.persist_full_master_data_snapshot was False for this historical
        # run - only row counts + business rules were kept, not the full snapshot
        # (see app/agents/graph.py::_persist_run). Live runs always have this key.
        row_counts = result.get("master_data_row_counts")
        st.info("Full input data snapshot was not persisted for this run (large-scale mode).")
        if row_counts:
            st.json(row_counts)
        return

    snapshot = result["master_data"]
    st.subheader("Master data snapshot")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Stores", len(snapshot.stores))
    c2.metric("Terminals", len(snapshot.terminals))
    c3.metric("Products", len(snapshot.products))
    c4.metric("Inventory rows", len(snapshot.inventory))

    st.markdown("**Stores**")
    st.dataframe(_df(snapshot.stores), use_container_width=True)
    st.markdown("**Terminals**")
    st.dataframe(_df(snapshot.terminals), use_container_width=True)
    st.markdown("**Products**")
    st.dataframe(_df(snapshot.products), use_container_width=True)
    st.markdown(f"**Inventory** (showing up to 200 of {len(snapshot.inventory)} rows)")
    st.dataframe(_df(snapshot.inventory[:200]), use_container_width=True)
    st.markdown("**Business rules**")
    st.json(snapshot.business_rules.model_dump())


def render_intermediate_data(result: dict) -> None:
    forecast = result["demand_forecast"]
    st.subheader(f"Demand forecast — {forecast.model_name}, {forecast.horizon_days}-day horizon")
    if forecast.forecasts:
        st.dataframe(_df(forecast.forecasts), use_container_width=True)
        if forecast.skipped_pairs:
            st.caption(f"{len(forecast.skipped_pairs)} store/product pair(s) skipped (no history)")
    else:
        st.info("No forecast points (no shortages/history in scope).")

    inventory_analysis = result["inventory_analysis"]
    st.subheader(f"Inventory analysis — {len(inventory_analysis.shortages)} shortage(s) below reorder point")
    if inventory_analysis.shortages:
        st.dataframe(_df(inventory_analysis.shortages), use_container_width=True)
    else:
        st.success("No shortages — every store is at or above its reorder point.")
    with st.expander(f"All {len(inventory_analysis.records)} inventory analysis records"):
        st.dataframe(_df(inventory_analysis.records), use_container_width=True)

    supply_planning = result["supply_planning"]
    st.subheader(f"Supply planning — {len(supply_planning.candidate_plans)} candidate plan(s)")
    if supply_planning.candidate_plans:
        st.dataframe(_df(supply_planning.candidate_plans), use_container_width=True)
    if supply_planning.unresolved_shortages:
        st.warning(f"{len(supply_planning.unresolved_shortages)} shortage(s) had no candidate terminal at all.")

    allocation = result["allocation"]
    st.subheader("Allocation scenarios")
    if allocation.scenarios:
        summary = pd.DataFrame(
            [
                {
                    "strategy": s.strategy,
                    "rank": s.rank,
                    "fulfillment_rate": s.fulfillment_rate,
                    "total_estimated_cost": s.total_estimated_cost,
                    "high_priority_covered": f"{s.high_priority_shortages_fulfilled}/{s.high_priority_shortages_total}",
                    "rationale": s.rationale,
                }
                for s in allocation.scenarios
            ]
        )
        st.dataframe(summary, use_container_width=True)
        st.caption(f"Recommended (by Module 6): **{allocation.recommended_strategy}**")
    else:
        st.info("No allocation scenarios (nothing to allocate).")

    cost_optimization = result["cost_optimization"]
    st.subheader("Cost optimization — real fleet-based costing")
    if cost_optimization.scenarios:
        summary = pd.DataFrame(
            [
                {
                    "strategy": s.strategy,
                    "total_cost": s.total_cost,
                    "transport": s.total_transportation_cost,
                    "handling": s.total_handling_cost,
                    "holding": s.total_holding_cost,
                    "delay_penalty": s.total_delay_penalty,
                    "high_priority_covered": f"{s.high_priority_shortages_fulfilled}/{s.high_priority_shortages_total}",
                }
                for s in cost_optimization.scenarios
            ]
        )
        st.dataframe(summary, use_container_width=True)
        st.caption(
            f"Recommended (cost-optimal): **{cost_optimization.recommended_strategy}** — "
            f"{cost_optimization.recommendation_rationale}"
        )
    else:
        st.info("No scenarios to cost.")

    validation = result["constraint_validation"]
    st.subheader("Constraint validation")
    if validation.scenario_validations:
        for sv in validation.scenario_validations:
            status = "✅ VALID" if sv.is_valid else f"❌ {len(sv.violations)} violation(s)"
            st.markdown(f"**{sv.strategy}**: {status}")
            for v in sv.violations:
                st.caption(f"[{v.constraint}] {v.message}")
        st.caption(
            f"Final strategy: **{validation.final_strategy}** "
            f"(replanning attempts used: {result.get('replanning_attempts', 0)})"
        )
        if validation.unresolved_violations:
            st.warning(f"{len(validation.unresolved_violations)} unresolved violation(s) remain.")
    else:
        st.info("No scenarios to validate.")


def render_final_plan(result: dict) -> None:
    decision_review = result["decision_review"]
    st.subheader("Decision review — holistic scoring")
    if decision_review.evaluations:
        summary = pd.DataFrame(
            [
                {
                    "strategy": e.strategy,
                    "overall_score": e.overall_score,
                    "inventory_balance": e.inventory_balance_score,
                    "distance_km": e.total_transportation_distance_km,
                    "fulfillment": e.demand_fulfillment_rate,
                    "future_risk": e.future_inventory_risk_ratio,
                    "cost": e.total_cost,
                }
                for e in decision_review.evaluations
            ]
        )
        st.dataframe(summary, use_container_width=True)
        if decision_review.fell_back_to_invalid_scenario:
            st.warning("No scenario passed constraint validation — reviewing the best-effort pick only.")
    else:
        st.info("No scenarios to review.")

    final = result["final_recommendation"]
    if final.selected_strategy is None:
        st.info("Nothing to recommend — no shortages in scope, or nothing survived review.")
        return

    st.subheader(f"✅ Final recommendation: {final.selected_strategy}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Confidence", f"{final.confidence_score:.0f}/100")
    c2.metric("Expected total cost", f"{final.expected_total_cost:.2f}")
    c3.metric("Expected service level", f"{final.expected_service_level:.0%}")

    if final.fell_back_to_invalid_scenario:
        st.warning("This plan did not pass constraint validation — it's a best-effort fallback.")
    if final.unresolved_shortages_count:
        st.warning(f"{final.unresolved_shortages_count} shortage(s) had no candidate terminal at all.")

    st.markdown("**Business explanation**")
    st.write(final.business_explanation)
    st.markdown("**Risk assessment**")
    st.write(final.risk_assessment)
    st.markdown("**Recommended contingency actions**")
    for action in final.contingency_actions:
        st.write(f"- {action}")

    st.markdown("**Shipment plan**")
    st.dataframe(_df(final.shipment_plan), use_container_width=True)

    st.markdown("**Expected inventory after shipment**")
    st.dataframe(_df(final.expected_inventory_after_shipment), use_container_width=True)

    st.markdown("**Alternative recommendations**")
    if final.alternative_recommendations:
        st.dataframe(_df(final.alternative_recommendations), use_container_width=True)
    else:
        st.caption("No alternatives (only one scenario was reviewed).")


def main() -> None:
    st.title("AI Supply Chain Planning — Demo Dashboard")
    st.caption("Load master data → forecast demand → analyze inventory → plan, allocate, cost, "
               "validate, review, and recommend a shipment plan.")

    settings = get_settings()
    st.sidebar.header("Reasoning engine")
    st.sidebar.markdown(f"Provider: `{settings.llm_provider}`")
    if settings.llm_provider == "groq":
        st.sidebar.markdown(f"Model: `{settings.groq_model}`")
        if not settings.groq_api_key:
            st.sidebar.error("GROQ_API_KEY not set — LLM-calling nodes will fail.")
    elif settings.llm_provider == "gemini":
        st.sidebar.markdown(f"Model: `{settings.gemini_model}`")
        if not settings.gemini_api_key:
            st.sidebar.error("GEMINI_API_KEY not set — LLM-calling nodes will fail.")
        st.sidebar.caption(
            "Gemini's free tier caps Flash models at 5 requests/minute - fine for a single "
            "shortage, tight for a scope with several."
        )
    else:
        st.sidebar.markdown(f"Model: `{settings.ollama_model}` @ `{settings.ollama_base_url}`")
        st.sidebar.caption("Local inference is slower than Groq/Gemini - expect several minutes per run.")

    try:
        store_options, product_options, terminal_count = load_scope_options()
    except Exception as exc:
        st.error(f"Could not load data from the database: {exc}\n\nRun `alembic upgrade head` and "
                 "`scripts/seed_data.py` first.")
        return

    if not store_options:
        st.error("No stores in the database. Run `scripts/seed_data.py` first, then reload this page.")
        return

    st.sidebar.header("Planning scope")
    store_labels = {f"{store_id}: {name}": store_id for store_id, name in store_options}
    product_labels = {f"{product_id}: {name}": product_id for product_id, name in product_options}

    selected_stores = st.sidebar.multiselect("Stores (empty = all)", list(store_labels.keys()))
    selected_products = st.sidebar.multiselect("Products (empty = all)", list(product_labels.keys()))
    window_days = st.sidebar.number_input("Demand history window (days)", min_value=1, value=90)
    objective_label = st.sidebar.selectbox(
        "Optimization objective",
        ["Minimize cost", "Maximize service level"],
        help=(
            "Minimize cost: cheapest scenario that still fully covers every high-priority "
            "shortage. Maximize service level: highest demand fulfillment rate, cost only "
            "as a tiebreaker."
        ),
    )
    objective = "minimize_cost" if objective_label == "Minimize cost" else "maximize_service_level"

    st.sidebar.caption(f"{len(store_options)} stores, {len(product_options)} products, {terminal_count} terminals available.")

    current_request = PlanningRequest(
        store_ids=[store_labels[label] for label in selected_stores] or None,
        product_ids=[product_labels[label] for label in selected_products] or None,
        demand_history_window_days=int(window_days),
        optimization_objective=objective,
    )

    # Traceability: surface any prior run for this exact scope (any engine) so the
    # user can view it instantly instead of blindly re-running an expensive/
    # rate-limited LLM pipeline. This is a pure read - no LLM/DB-write side effects -
    # so it's safe to do on every rerun; "▶ Run planning workflow" below still always
    # forces a fresh computation regardless of what's already there.
    try:
        matching_runs = find_matching_runs(current_request)
    except Exception:
        matching_runs = []

    if matching_runs:
        st.sidebar.markdown(f"**{len(matching_runs)} previous run(s) for this exact scope:**")
        run_options = {
            f"#{r.id} · {r.created_at:%Y-%m-%d %H:%M} · {r.llm_model} · {r.status.value}": r
            for r in matching_runs
        }
        chosen_label = st.sidebar.selectbox(
            "View a previous run", ["(select one)"] + list(run_options.keys()), key="matching_run_select"
        )
        if chosen_label != "(select one)":
            _load_run_into_session(run_options[chosen_label])

    with st.sidebar.expander("🕘 Run history (all scopes)"):
        try:
            recent_runs = list_recent_runs(limit=20)
        except Exception:
            recent_runs = []
        if recent_runs:
            recent_options = {
                f"#{r.id} · {r.created_at:%Y-%m-%d %H:%M} · scope="
                f"{r.store_ids or 'all'}/{r.product_ids or 'all'} · {r.llm_model} · {r.status.value}": r
                for r in recent_runs
            }
            chosen_recent_label = st.selectbox(
                "View any recent run", ["(select one)"] + list(recent_options.keys()), key="recent_run_select"
            )
            if chosen_recent_label != "(select one)":
                _load_run_into_session(recent_options[chosen_recent_label])
        else:
            st.caption("No runs yet.")

    force_rerun = st.sidebar.checkbox(
        "🔁 Force re-run (ignore cached result)",
        help=(
            "By default, running the same scope against unchanged data with the same "
            "reasoning engine reuses the prior result instead of recomputing - no new "
            "LLM calls, guaranteed identical output. Check this to bypass that and "
            "compute fresh anyway."
        ),
    )

    if st.sidebar.button("▶ Run planning workflow", type="primary"):
        with st.spinner(
            "Running the 9-node planning pipeline... this can take a few minutes with a local Ollama model."
        ):
            try:
                st.session_state["result"] = run_workflow(current_request, force_rerun=force_rerun)
                st.session_state["error"] = None
                st.session_state["result_source"] = (
                    "live",
                    None,
                    datetime.datetime.now(),
                    settings.llm_provider,
                    get_active_model_name(),
                )
            except Exception as exc:
                st.session_state["result"] = None
                st.session_state["error"] = str(exc)

    if st.session_state.get("error"):
        st.error(f"Workflow failed: {st.session_state['error']}")

    result = st.session_state.get("result")
    if result is None:
        if not st.session_state.get("error"):
            st.info(
                "Configure the scope in the sidebar and click **Run planning workflow** to begin, "
                "or pick a previous run above."
            )
        return

    source = st.session_state.get("result_source")
    if source:
        kind, run_id, ts, _provider, model = source
        if kind == "historical":
            st.caption(f"📜 Viewing historical run #{run_id} — {ts:%Y-%m-%d %H:%M} — via {model}")
        else:
            st.caption(f"🟢 Live run just now — via {model}")

    st.subheader("Trace")
    st.code("\n".join(f"- {line}" for line in result["trace"]), language=None)
    if result["errors"]:
        for err in result["errors"]:
            st.warning(err)

    tab_input, tab_intermediate, tab_final = st.tabs(["📥 Input Data", "⚙️ Intermediate Data", "📋 Final Plan"])
    with tab_input:
        render_input_data(result)
    with tab_intermediate:
        render_intermediate_data(result)
    with tab_final:
        render_final_plan(result)


if __name__ == "__main__":
    main()
