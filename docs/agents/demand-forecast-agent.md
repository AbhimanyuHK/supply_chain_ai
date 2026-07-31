# Demand Forecast Agent

The second node (`load_master_data → forecast_demand → ...`), implemented
in `app/agents/demand_forecast_agent.py`. Still no LLM call — this agent
is pure ML inference via HuggingFace Chronos, a zero-shot time-series
foundation model (`app/forecast/chronos_forecaster.py`).

## How it forecasts

For every `(store, product)` pair present in the master data snapshot, its
historical `sales_qty` series (sorted by date) is fed directly to Chronos,
which returns 10th/50th/90th percentile forecasts for
`Settings.forecast_horizon_days` (default 14) ahead — no statistical
fallback, no synthetic stand-in. Pairs with zero sales history are recorded
in `skipped_pairs` rather than guessed at with an invented number.

The Chronos pipeline itself is cached process-wide via `lru_cache` (loading
it costs roughly 10 seconds), and series are batched through it in chunks
of `Settings.forecast_batch_size` (default 256) to bound memory at scale
rather than one call per series or one giant call for everything.

```{note}
Chronos forecasts by sampling roughly 20 random trajectories internally
and taking quantiles across them — without a fixed seed, identical
historical data could produce a slightly different forecast on every
call. `app/forecast/chronos_forecaster.py` seeds torch's RNG
(`Settings.chronos_random_seed`, default 42) before every `predict()`
call specifically to prevent this — see
{doc}`../features/idempotency-and-caching` for the real incident that
surfaced this gap.
```

## Model choice

`amazon/chronos-t5-tiny` by default — fast, CPU-friendly, about a 30-40MB
download on first use, cached under `~/.cache/huggingface`.
`Settings.chronos_model_name` can be bumped to `chronos-t5-small` or
`chronos-t5-base` for better accuracy once GPU infrastructure is
available; no code change is needed for that switch.

## Scope limitation, stated plainly

The original spec lists promotions, holidays, and weather as forecast
inputs. Chronos has no covariate mechanism for "this future date is a
promotion" — it forecasts purely from the historical series shape, which
already reflects whatever past promo/holiday spikes and weekly
seasonality actually happened. There is also no forward-looking
promotion/holiday calendar table anywhere in the data model
(`demand_history.promotion`/`.holiday` are historical flags, not future
ones), so this agent does not fabricate a calendar that doesn't exist.
Weather is out of scope entirely — no data source for it anywhere.

```{tip}
If a real promotions/holiday calendar is added later, the natural
integration point is documented directly in
`app/agents/demand_forecast_agent.py`'s module docstring.
```

## Manual run

```bash
venv\Scripts\python.exe scripts\run_planning_workflow.py
```

Prints the master data snapshot summary followed by a forecast sample —
this and the Master Data agent are the only two nodes that run with zero
external API keys configured.
