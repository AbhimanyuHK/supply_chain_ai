# Idempotency and Caching

`run_planning_workflow` is idempotent by default, not just persisted: the
same scope run against unchanged data with the same reasoning engine
always returns the identical prior result rather than recomputing. This
is a business requirement, not an optimization — traceability implies
reproducibility, so a re-run of "the same thing" shouldn't produce a
different answer just because an LLM happened to sample differently. It's
also a practical one: no wasted LLM calls or quota on a redundant repeat.

## Data fingerprint, not just scope

A naive cache keyed only on the request's scope (store/product ids,
window, date) would incorrectly serve a stale plan if the underlying data
changed between two calls with the identical scope. Instead,
`app/services/fingerprint.py::compute_data_fingerprint` hashes the
**actual loaded** `MasterDataSnapshot` — SHA-256, excluding `loaded_at`
(the only non-deterministic field anywhere in the snapshot or anything it
embeds).

### Why every nested list is sorted first

`json.dumps(..., sort_keys=True)` only sorts dict keys — it never touches
list order — and no repository applies `ORDER BY` anywhere. Without
normalizing list order before hashing, the cache would spuriously *miss*
even when nothing about the data actually changed, silently defeating the
whole feature. Each nested list is sorted by its natural identity key
before hashing:

| List | Sort key |
|---|---|
| `stores`, `terminals`, `products` | id |
| `inventory` | `(location_type, location_id, product_id)` — matches its real unique constraint |
| `demand_history` | `(store_id, product_id, date)` |
| `fleet` | `vehicle_id` |
| `distance_matrix` | `(terminal_id, store_id)` — its actual composite primary key |

```{important}
This was caught, and fixed, *before* it shipped: the scalability work's
Fix 1 ({doc}`scalability`) changes how terminals are ordered when a store
scope is set, which would otherwise have made a naive (unsorted)
fingerprint unstable the moment that change landed. A plan-review pass
independently re-derived this dependency before any code was written —
see the project's decision history for how this was caught.
```

Fingerprinting the *data* itself (not just request parameters) also means
a scope where inventory has genuinely changed since the last run
correctly triggers a fresh computation rather than serving a stale plan.

## Cache lookup, step by step

1. `run_planning_workflow` loads master data once standalone (via the
   memoizing `load_master_data_node` — see
   {doc}`../agents/master-data-agent`) and computes the fingerprint.
2. Unless `force_rerun=True`, it calls
   `PlanningRunRepository.find_success_by_scope_data_and_engine(scope_key,
   data_fingerprint, llm_provider, llm_model)` — filters `status ==
   SUCCESS` explicitly, unlike `find_by_scope_key`, which is for history
   browsing and shows failed runs too.
3. **A hit** returns `PlanningRunRead.model_validate(row).to_state_dict()`
   immediately — no new LLM calls, no new row written (nothing was
   computed; the existing row remains the record).
4. **A miss** proceeds through the graph as before, seeding the
   already-loaded snapshot into the initial state so the graph's own
   execution of `load_master_data_node` doesn't load it a second time.

Both the standalone preload and the cache lookup are wrapped in their own
try/except — a DB hiccup must never block or crash a real run, the same
philosophy applied to the persistence hook itself (see
{doc}`persistence-and-audit-trail`).

## The cost objective is part of the cache key

`PlanningRequest.optimization_objective` is folded into `scope_key()` — a
different objective represents a genuinely different desired plan, so
it's correctly treated as a cache miss rather than an equivalent request.
See {doc}`cost-objectives`.

## Streamlit

The "▶ Run planning workflow" button benefits from this cache by default,
with no special-casing needed — it calls the same
`run_planning_workflow` every caller goes through. A "🔁 Force re-run"
checkbox passes `force_rerun=True` to bypass the cache when a genuinely
fresh computation is wanted regardless (e.g. suspecting a stale hit, or
comparing timing). See {doc}`../interfaces/streamlit-dashboard`.

## A fresh computation must also be deterministic on its own

The cache above guarantees "same scope + data + engine → same *cached*
result" — but it only ever prevents a *second* computation. The very
first run of a scope, and any run made with `force_rerun=True`, still
executes the full graph for real, and that computation needs to be
internally deterministic too, or two people running the identical
scenario independently could still get two different answers with
neither one being a cache hit.

```{important}
This was a real bug, not a hypothetical: two runs of the exact same
(all-stores) scope, same data fingerprint, same engine, produced
**different** total costs (\$38,130.33 vs. \$42,629.03) because the
shortage count itself differed (10 vs. 11) between the runs. Root cause:
{doc}`../agents/demand-forecast-agent`'s HuggingFace Chronos model
forecasts by sampling roughly 20 random trajectories internally and
taking quantiles across them
(`app/forecast/chronos_forecaster.py::forecast_series_batch`), using
PyTorch's global RNG with no fixed seed anywhere in the original code.
Identical historical sales data could therefore produce a slightly
different median forecast on every call, occasionally flipping a
borderline store/product pair across the reorder-point threshold and
cascading into a genuinely different shipment plan.

**Fixed** by seeding torch's RNG (`torch.manual_seed(Settings.chronos_random_seed)`,
default `42`) immediately before every `pipeline.predict()` call — verified
by calling `forecast_series_batch` with identical input across three
calls in the same process *and* across three separate fresh process
invocations, confirming byte-identical output every time.
```

This closes the forecasting half of the "fresh run" determinism gap.
LLM sampling is the other half: `groq_temperature`/`gemini_temperature`/
`ollama_temperature` are all `0.0` (see {doc}`reasoning-engines`), which
minimizes but — for hosted cloud APIs specifically — does not
mathematically *guarantee* bit-exact output across separate calls (batched
GPU inference on the provider's side can introduce tiny floating-point
differences even at temperature 0). In practice this matters far less
than the Chronos gap did, since the cache means most repeat requests
never re-invoke the LLM at all; a fully bit-exact guarantee there would
require a fully local, deterministic engine (Ollama on CPU) rather than
any cloud provider.

## Known limitation, not solved here

The fingerprint captures *data* determinism, not code/prompt/settings
version. A stale hit could still serve a plan computed under different
application logic if the app was redeployed between two calls with
identical data and scope. Solving this would mean folding a
code/prompt-version identifier into the cache key — a reasonable future
step, not built now.
