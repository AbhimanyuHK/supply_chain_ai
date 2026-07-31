"""Chronos-based zero-shot demand forecaster.

Wraps HuggingFace's `chronos-forecasting` pipeline. Chronos is univariate and
zero-shot: each store/product's forecast comes purely from the shape of its
own historical sales series (which implicitly captures weekly/seasonal
patterns if enough history is present). It has no covariate mechanism to
accept "day N is a promotion/holiday" for a *future* date — see
`app/agents/demand_forecast_agent.py` for why that's out of scope for now
rather than faked.
"""

from functools import lru_cache

import torch
from chronos import ChronosPipeline

from app.core.config import get_settings

_QUANTILE_LEVELS = torch.tensor([0.1, 0.5, 0.9])


@lru_cache
def _get_pipeline() -> ChronosPipeline:
    settings = get_settings()
    return ChronosPipeline.from_pretrained(
        settings.chronos_model_name,
        device_map=settings.chronos_device,
        dtype=torch.float32,
    )


def forecast_series_batch(
    series_list: list[list[float]],
    prediction_length: int,
    batch_size: int | None = None,
) -> list[dict[str, list[float]]]:
    """Forecast many independent series in one or more batched Chronos calls.

    Returns, per input series (same order), {"low", "median", "high"} lists of
    length `prediction_length` (the 10th/50th/90th percentile forecast),
    clipped at 0 since demand can't be negative.
    """
    if not series_list:
        return []

    settings = get_settings()
    batch_size = batch_size or settings.forecast_batch_size
    pipeline = _get_pipeline()

    results: list[dict[str, list[float]]] = []
    for start in range(0, len(series_list), batch_size):
        chunk = series_list[start : start + batch_size]
        context = [torch.tensor(series, dtype=torch.float32) for series in chunk]
        # Chronos samples multiple random trajectories internally and takes
        # quantiles across them; without a fixed seed, identical input produces
        # a different forecast on every call, which can flip a borderline
        # store/product pair across the reorder-point threshold between two
        # otherwise-identical runs. Seeding immediately before each predict()
        # call makes this deterministic regardless of any other torch RNG
        # usage elsewhere in the process.
        torch.manual_seed(settings.chronos_random_seed)
        forecasts = pipeline.predict(context=context, prediction_length=prediction_length)

        for sample_forecast in forecasts:
            low, median, high = torch.quantile(sample_forecast, _QUANTILE_LEVELS, dim=0)
            results.append(
                {
                    "low": [max(0.0, v) for v in low.tolist()],
                    "median": [max(0.0, v) for v in median.tolist()],
                    "high": [max(0.0, v) for v in high.tolist()],
                }
            )

    return results
