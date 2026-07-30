"""Master Data Agent — the first LangGraph node.

Loads the full scoped master data snapshot (stores, terminals, products,
inventory, demand history, fleet, distance matrix, business rules) for the
planning run described in `state["request"]`. Pure data loading, no LLM
reasoning — Groq is first used starting with the Demand Forecast Agent.
"""

from loguru import logger

from app.agents.state import PlanningState
from app.database.session import AsyncSessionLocal
from app.services.master_data_service import MasterDataService


async def load_master_data_node(state: PlanningState) -> dict:
    request = state["request"]

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
