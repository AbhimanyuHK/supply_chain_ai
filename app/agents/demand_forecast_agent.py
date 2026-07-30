"""Demand Forecast Agent — second LangGraph node.

Forecasts daily demand per store/product using HuggingFace Chronos, fed on
each store/product's historical `sales_qty` series from the master data
snapshot the previous node loaded.

Scope note on Promotions/Holiday/Weather (per the spec's forecast inputs):
Chronos is a zero-shot, univariate model — it has no covariate input for
"this future date is a promotion/holiday". Historical promotion/holiday
spikes are implicitly reflected in the forecast because Chronos sees the
actual `sales_qty` values (including those spikes) in the input context, and
weekly/seasonal patterns come through the same way. But there is no
forward-looking promotion/holiday calendar anywhere in the current data model
(no such table exists), so this agent cannot apply a *known future* uplift —
doing so would mean fabricating calendar data that doesn't exist. Weather is
out of scope entirely for the same reason (no data source). If a promotions
calendar is added later, the right place to layer it in is a post-hoc
multiplier on top of `predicted_qty` here.
"""

import datetime
from collections import defaultdict

from loguru import logger

from app.agents.state import PlanningState
from app.core.config import get_settings
from app.forecast.chronos_forecaster import forecast_series_batch
from app.schemas.forecast import DemandForecastPoint, DemandForecastResult, StoreProductRef


async def forecast_demand_node(state: PlanningState) -> dict:
    settings = get_settings()
    snapshot = state["master_data"]
    request = state["request"]

    series_by_pair: dict[tuple[int, int], list[tuple[datetime.date, float]]] = defaultdict(list)
    for row in snapshot.demand_history:
        series_by_pair[(row.store_id, row.product_id)].append((row.date, float(row.sales_qty)))

    pairs: list[tuple[int, int]] = []
    series_values: list[list[float]] = []
    skipped: list[StoreProductRef] = []

    for store in snapshot.stores:
        for product in snapshot.products:
            key = (store.store_id, product.product_id)
            points = series_by_pair.get(key, [])
            if not points:
                skipped.append(StoreProductRef(store_id=store.store_id, product_id=product.product_id))
                continue
            points.sort(key=lambda p: p[0])
            pairs.append(key)
            series_values.append([qty for _, qty in points])

    horizon = settings.forecast_horizon_days
    batch_results = forecast_series_batch(series_values, prediction_length=horizon)

    forecasts: list[DemandForecastPoint] = []
    for (store_id, product_id), result in zip(pairs, batch_results):
        for day_offset in range(horizon):
            forecast_date = request.planning_date + datetime.timedelta(days=day_offset + 1)
            forecasts.append(
                DemandForecastPoint(
                    store_id=store_id,
                    product_id=product_id,
                    date=forecast_date,
                    predicted_qty=result["median"][day_offset],
                    low_qty=result["low"][day_offset],
                    high_qty=result["high"][day_offset],
                )
            )

    demand_forecast = DemandForecastResult(
        horizon_days=horizon,
        model_name=settings.chronos_model_name,
        forecasts=forecasts,
        skipped_pairs=skipped,
    )

    message = (
        f"Forecasted demand for {len(pairs)} store/product pairs over {horizon} days "
        f"using {settings.chronos_model_name} ({len(skipped)} pairs skipped, no history)"
    )
    logger.info(message)

    return {"demand_forecast": demand_forecast, "trace": [message]}
