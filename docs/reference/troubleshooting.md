# Troubleshooting

Real issues hit during development of this platform, with root causes and
fixes — not hypothetical FAQ entries.

## `RuntimeError: Event loop is closed`

**Where it shows up**: a Streamlit error banner ("Workflow failed: Event
loop is closed"), or a pytest failure deep inside `grpc.aio._channel` when
two real-LLM tests run back-to-back.

**Root cause**: `@lru_cache`'d LLM clients (`get_chat_model()`, each
agent's `_get_structured_llm()`) and the SQLAlchemy async engine hold
connections/channels bound to whichever event loop was active when they
were first constructed. Streamlit runs each script rerun inside a fresh
`asyncio.run(...)`; `pytest-asyncio` gives each test function its own
event loop by default. Reusing a cached client across a *different* loop
than the one it was built on raises this error.

**Fix, already applied**: `streamlit_app.py::_run_async()` disposes the
DB engine and calls `reset_llm_client_caches()`
(`app/core/llm.py`) after every async call; `tests/conftest.py` has an
autouse fixture doing the same after every test. If you see this error
somewhere neither of those wrap, that's the actual bug to fix — route
that async entry point through the same reset pattern. See
{doc}`../interfaces/streamlit-dashboard` and {doc}`../operations/testing`
for the full detail on each side of this issue.

**Don't confuse it with**: a Gemini `429 RESOURCE_EXHAUSTED` sometimes
surfaces alongside secondary "Event loop is closed" noise in a traceback
— check the actual root exception before assuming this is the cache
issue again.

## `429` errors from Gemini

**Not a bug** — Gemini's free tier caps Flash models at 5
requests/minute (confirmed via Google AI Studio's own usage dashboard).
Since every shortage costs 4 LLM calls, even a single shortage can
approach this ceiling. Lower `Settings.llm_max_concurrent_requests` to
`1`, prefer Groq or Ollama for anything beyond a single-shortage smoke
test, or wait out the `retry_delay` the error reports (typically ~47s).
See {doc}`../features/reasoning-engines`.

## `ModuleNotFoundError: No module named 'asyncpg'`

**Cause**: `DATABASE_URL` points at a `postgresql+asyncpg://...` URL but
the active virtual environment doesn't have `asyncpg` installed — this
happens if `.env`'s `DATABASE_URL` was changed to Postgres (e.g. while
following {doc}`../operations/deployment`) but you're running from
`venv-ui/` (see {doc}`../interfaces/streamlit-dashboard` for why it's a
separate environment) or a fresh `venv/` that hasn't installed the full
`requirements.txt`.

**Fix**: either switch `DATABASE_URL` back to
`sqlite+aiosqlite:///./supply_chain.db` (`.env` is last-value-wins, so an
appended override line works if you don't want to edit the original), or
install into the environment that actually needs the Postgres driver.

## Wrong reasoning engine appears active despite `.env`

**Cause**: an OS-level environment variable (e.g. set explicitly when
launching a shell or process, such as `LLM_PROVIDER=ollama <command>`)
takes precedence over `.env` for that process's entire lifetime — a
stale background process started with such an override can keep running
against a different provider than `.env` currently says, especially
confusing with Streamlit's long-lived process.

**Fix**: find and stop the stale process, then restart cleanly without
any shell-level override, letting `Settings` read `.env` alone. Confirm
via whichever surface prints `Settings.llm_provider`/`get_active_model_name()`
(the Streamlit sidebar, or a trace line).

## `.env` changes not taking effect

**Cause**: `Settings` (and `get_business_rules()`) are process-wide
`@lru_cache`'d. Any change to `.env` or `config/business_rules.yaml`
requires **restarting** whichever process reads it — re-clicking around
in an already-running Streamlit session will never pick up a change.

## Documentation build

To verify the Sphinx build locally before pushing:

```bash
venv\Scripts\python.exe -m pip install -r docs\requirements.txt
venv\Scripts\python.exe -m sphinx -b html docs docs\_build\html
```

Open `docs\_build\html\index.html` to preview. Read the Docs itself
builds from `.readthedocs.yaml` on every push once the repo is connected
at [readthedocs.com](https://about.readthedocs.com/).
