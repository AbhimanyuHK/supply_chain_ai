# Streamlit Demo Dashboard

`streamlit_app.py` — a read-only dashboard over `run_planning_workflow`
for demoing the system to business stakeholders. **Not a production UI**
— no authentication, no multi-user concerns, single process.

## Layout

Three tabs mirror the three things a stakeholder would actually ask to
see:

1. **Input data** — the loaded `MasterDataSnapshot` (or, for a
   summary-only historical run, an informational notice — see
   {doc}`../features/persistence-and-audit-trail`).
2. **Intermediate agent output** — one section per pipeline stage, in
   order, so the whole reasoning chain is visible, not just the final
   answer.
3. **Final recommendation** — the shipment plan, expected inventory,
   business explanation, risk assessment, contingency actions, confidence
   score, and alternatives.

## Running it

Requires its own environment — see the next section for why:

```bash
venv-ui\Scripts\streamlit.exe run streamlit_app.py
```

Pick a scope, an optimization objective (see
{doc}`../features/cost-objectives`), and click **▶ Run planning
workflow**. A **🔁 Force re-run** checkbox bypasses the
{doc}`idempotency cache <../features/idempotency-and-caching>` when a
genuinely fresh computation is wanted.

## History and caching in the UI

Selecting a scope that already has prior runs surfaces them — picking one
is a pure read (no LLM call, no new database row); running the identical
scope again on the same engine returns instantly from the cache rather
than recomputing. A "🕘 Run history (all scopes)" expander browses beyond
the currently selected scope. A caption above the results always states
plainly whether what's on screen is a **live** run or a specific
**historical** one, so it's never ambiguous which is being viewed.

## Why a separate virtual environment (`venv-ui/`)

`fastapi==0.115.6` pins `starlette<0.42`, but Streamlit 1.60's own
dashboard server code imports `DEFAULT_EXCLUDED_CONTENT_TYPES` from
`starlette.middleware.gzip` — a symbol only added well after 0.42.
Streamlit's own package metadata under-declares its real floor as
`>=0.40`, so `pip` alone won't catch this conflict at install time; it
only ever surfaces as an `ImportError` at runtime, when the dashboard
actually starts.

The two constraints — FastAPI's ceiling, Streamlit's real floor — can't
both be satisfied in one environment. Fortunately, `streamlit_app.py`
only imports `app.agents.graph` / `app.core.config` / `app.database.*` /
`app.schemas.planning` — none of which touch FastAPI (confirmed: only
`app/api/main.py` and `app/api/routers/health.py` import `fastapi`
anywhere in this codebase, and neither is on that import path). So the
dashboard doesn't need FastAPI installed at all. Its own
`requirements-ui.txt` lists real runtime dependencies directly rather
than chaining `-r requirements.txt`, letting `pip` resolve a modern
starlette freely. See {doc}`../getting-started/installation` for the
setup steps.

## `_run_async()` — why every call goes through it

Streamlit reruns the whole script top-to-bottom on every interaction,
each time inside a fresh `asyncio.run(...)` call. Two module-level
caches — the SQLAlchemy async engine and every `@lru_cache`'d LLM client
(`get_chat_model()`, each agent's `_get_structured_llm()`) — hold
connections/channels bound to whatever event loop was active when they
were first constructed. Reusing them from a *different* rerun's event
loop raises `RuntimeError: Event loop is closed` deep inside
`grpc.aio`/`httpx`.

`streamlit_app.py`'s `_run_async()` wrapper disposes the DB engine and
calls `reset_llm_client_caches()` (`app/core/llm.py`) after every async
call, so the next rerun always builds fresh clients bound to its own new
loop. This is the same root cause — and the same fix — as a
event-loop-scoping issue found independently in the pytest suite; see
{doc}`../operations/testing`.

```{note}
An error banner reading "Workflow failed: Event loop is closed" is this
specific, fixed issue if it recurs somewhere `_run_async` isn't used, but
in practice it's more often secondary noise wrapping a **Gemini rate
limit** (a `429`) than a fresh instance of the loop bug itself — check
the full traceback before assuming it's the cache issue again.
```

## Switching reasoning engines

`Settings` is `@lru_cache`'d process-wide, and Streamlit keeps one
long-lived process across reruns — changing `LLM_PROVIDER` in `.env`
requires **stopping and restarting** the Streamlit process, not just
re-clicking around in an already-running session.
