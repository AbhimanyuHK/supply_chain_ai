"""Inventory Analysis Agent — third LangGraph node.

For every (location, product) row in the master data snapshot, reports the
raw inventory picture (on-hand, available, reserved, incoming, damaged), and
for STORE locations only, computes safety stock / reorder point / shortage
using the Demand Forecast Agent's output as the demand signal.

Why stores only: safety stock and reorder point are replenishment triggers
driven by consumer demand, and only stores have a demand forecast (terminals
don't sell to consumers — a terminal's demand is the sum of the stores it
supplies, which is the Supply Planning Agent's concern in a later module, not
this one's). Computing a store-inventory concept for terminals would mean
inventing a number nothing backs.

Formulas (documented since the spec doesn't prescribe exact ones):
    avg_daily_demand = mean of the Demand Forecast Agent's median forecast
                        over the horizon, for that store/product
    safety_stock     = avg_daily_demand * business_rules.default_safety_stock_days
    lead_time_demand = avg_daily_demand * business_rules.default_lead_time_days
    reorder_point    = lead_time_demand * business_rules.reorder_point_multiplier
                        + safety_stock
    shortage_qty     = max(0, reorder_point - (available_qty + incoming_qty))
"""

from collections import defaultdict

from loguru import logger

from app.agents.state import PlanningState
from app.models.entities import LocationType
from app.schemas.inventory_analysis import InventoryAnalysisRecord, InventoryAnalysisResult


async def analyze_inventory_node(state: PlanningState) -> dict:
    snapshot = state["master_data"]
    forecast = state["demand_forecast"]
    business_rules = snapshot.business_rules

    avg_daily_demand_by_pair: dict[tuple[int, int], float] = {}
    demand_by_pair: dict[tuple[int, int], list[float]] = defaultdict(list)
    for point in forecast.forecasts:
        demand_by_pair[(point.store_id, point.product_id)].append(point.predicted_qty)
    for pair, values in demand_by_pair.items():
        avg_daily_demand_by_pair[pair] = sum(values) / len(values)

    records: list[InventoryAnalysisRecord] = []
    for row in snapshot.inventory:
        on_hand = row.available_qty + row.reserved_qty + row.damaged_qty

        avg_daily_demand = None
        safety_stock = None
        reorder_point = None
        shortage_qty = 0.0
        below_reorder_point = False

        if row.location_type == LocationType.STORE:
            avg_daily_demand = avg_daily_demand_by_pair.get((row.location_id, row.product_id))
            if avg_daily_demand is not None:
                safety_stock = avg_daily_demand * business_rules.default_safety_stock_days
                lead_time_demand = avg_daily_demand * business_rules.default_lead_time_days
                reorder_point = lead_time_demand * business_rules.reorder_point_multiplier + safety_stock
                position = row.available_qty + row.incoming_qty
                shortage_qty = max(0.0, reorder_point - position)
                below_reorder_point = position < reorder_point

        records.append(
            InventoryAnalysisRecord(
                location_type=row.location_type,
                location_id=row.location_id,
                product_id=row.product_id,
                on_hand_qty=on_hand,
                available_qty=row.available_qty,
                reserved_qty=row.reserved_qty,
                incoming_qty=row.incoming_qty,
                damaged_qty=row.damaged_qty,
                avg_daily_demand=avg_daily_demand,
                safety_stock=safety_stock,
                reorder_point=reorder_point,
                shortage_qty=shortage_qty,
                below_reorder_point=below_reorder_point,
            )
        )

    shortages = [r for r in records if r.shortage_qty > 0]
    result = InventoryAnalysisResult(records=records, shortages=shortages)

    message = (
        f"Analyzed {len(records)} inventory rows "
        f"({sum(1 for r in records if r.location_type == LocationType.STORE)} store, "
        f"{sum(1 for r in records if r.location_type == LocationType.TERMINAL)} terminal); "
        f"{len(shortages)} below reorder point"
    )
    logger.info(message)

    return {"inventory_analysis": result, "trace": [message]}
