"""Master Data Agent — the first LangGraph node.

Loads the full scoped master data snapshot (stores, terminals, products,
inventory, demand history, fleet, distance matrix, business rules) for the
planning run described in `state["request"]`. Pure data loading, no LLM
reasoning — Groq is first used starting with the Demand Forecast Agent.

Memoizes on `state["master_data"]`: `run_planning_workflow` (see
`app/agents/graph.py`) loads the snapshot once standalone before the graph
runs, to compute an idempotency fingerprint before deciding whether to skip
the expensive LLM stages entirely. Reusing that already-loaded snapshot here
(rather than loading it a second time) avoids doubling this node's DB cost
on every single run - the whole point of this workstream is fixing
over-fetching, so re-fetching here just to satisfy the graph's normal
START -> load_master_data entry point would be a strange thing to leave in.
"""

from loguru import logger

from app.agents.state import PlanningState
from app.database.session import AsyncSessionLocal
from app.services.master_data_service import MasterDataService


async def load_master_data_node(state: PlanningState) -> dict:
    request = state["request"]

    snapshot = state.get("master_data")
    if snapshot is None:
        async with AsyncSessionLocal() as session:
            service = MasterDataService(session)
            snapshot = await service.load(request)

    message = (
        f"Loaded master data: {len(snapshot.stores)} stores, {len(snapshot.terminals)} terminals, "
        f"{len(snapshot.products)} products, {len(snapshot.inventory)} inventory rows, "
        f"{len(snapshot.demand_history)} demand history rows, {len(snapshot.fleet)} vehicles, "
        f"{len(snapshot.distance_matrix)} distance matrix entries"
    )
    logger.info(message)

    return {"master_data": snapshot, "trace": [message]}
