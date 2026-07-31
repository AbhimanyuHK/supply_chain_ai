# Testing

100+ tests under `tests/`, one module per component, run with:

```bash
venv\Scripts\python.exe -m pytest -v
```

The full suite passes with **zero API keys configured** — every
LLM-gated test skips gracefully rather than failing when no reasoning
engine is set up.

## Test files

| File | Covers |
|---|---|
| `test_config.py` | `Settings` loading, defaults, env var overrides |
| `test_models.py` | ORM constraints — FK violations raise, unique constraints enforced |
| `test_health_api.py` | `/health` endpoint |
| `test_repositories.py` | Repository layer, including chunked `IN (...)` queries (see {doc}`../features/scalability`) |
| `test_master_data_service.py` | Scoped loading, store-scoped terminal narrowing (Fix 1) |
| `test_agents_graph.py` | Full graph execution, trace length, idempotency cache hits/misses, persistence hook success/failure paths |
| `test_chronos_forecaster.py` | Chronos forecasting wrapper |
| `test_inventory_analysis_agent.py` | Shortage/reorder-point math |
| `test_supply_planning_agent.py` | Candidate finding, quantity clamping, batching/match-back (mocked), plus two real-LLM tests |
| `test_allocation_agent.py` | The three deterministic allocation strategies, LLM ranking |
| `test_cost_optimization_agent.py` | Real cost breakdown math, `minimize_cost`/`maximize_service_level` selection |
| `test_constraint_validation_agent.py` | The full decision tree, every implemented constraint |
| `test_decision_review_agent.py` | The six review metrics, `argmax` selection |
| `test_final_recommendation_agent.py` | Shipment plan construction, expected inventory arithmetic |

## `conftest.py`

Two fixtures shared across the whole suite:

- **`requires_llm_configured`** — a marker that skips a test only when
  *none* of the three reasoning engines (`groq_api_key`, `gemini_api_key`,
  or `llm_provider == "ollama"`) are configured. Replaces what used to be
  five near-identical `requires_groq_key` markers, one per LLM-calling
  test file — the shared marker means the same tests exercise real
  coverage against whichever engine CI or a developer actually has set up.
- **`_reset_llm_client_caches_between_tests`** (autouse) — calls
  `reset_llm_client_caches()` (`app/core/llm.py`) after every test.

### Why the cache-reset fixture exists

`@lru_cache`'d LLM clients (`get_chat_model()`, each agent's
`_get_structured_llm()`) hold gRPC/httpx channels bound to whatever event
loop was active when they were first constructed. `pytest-asyncio` gives
each test function its own event loop by default — only fixtures honor
the session-scoped `asyncio_default_fixture_loop_scope` setting in
`pyproject.toml`. Running two real-LLM tests back-to-back (e.g.
`test_supply_planning_agent.py`'s two `@requires_llm_configured` tests)
without resetting the cache between them causes the **second** test to
fail with `RuntimeError: Event loop is closed` deep inside
`grpc.aio._channel` — the first test's cached client leaked a channel
bound to a now-closed loop into the second test's fresh one.

This is the identical root cause (and identical fix) as the Streamlit
"Event loop is closed" issue — see
{doc}`../interfaces/streamlit-dashboard`'s `_run_async()` section for the
UI-side version of the same problem.

## Real vs. mocked LLM tests

Each LLM-calling agent's test file has both:

- **Mocked tests** (stubbing `_get_structured_llm`/`get_chat_model`) —
  always run, cover deterministic logic (candidate finding, cost math,
  quantity clamping, batching/match-back) without needing an API key or
  network access.
- **Real-LLM tests** (gated behind `requires_llm_configured`) — actually
  call whichever engine is configured, verifying the real prompt/response
  contract still holds. These are what CI's three jobs (see
  {doc}`ci-cd`) are for.

## Database in tests

Tests run against a real SQLite database with a per-test rollback
transaction (via each repository's constructor-injected `AsyncSession`) —
never against mocks of the database layer itself. `APP_ENV=test`
(forced by `conftest.py`) is the only environment where this matters
differently from local development.
