# Installation

## Prerequisites

- **Python 3.12 recommended** (3.10+ works; some agents were developed and
  verified primarily on 3.10/3.12).
- **No Docker required for local development.** The application defaults to
  a local SQLite file — there is no external service to stand up before you
  can run the full pipeline.
- **Docker + Docker Compose only if you want PostgreSQL** (the
  production-shaped path). See {doc}`../operations/deployment`.
- **A reasoning engine.** You need at least one of:
  - A free [Groq](https://console.groq.com) API key (default provider), or
  - A free [Google AI Studio](https://aistudio.google.com/apikey) API key
    (Gemini), or
  - [Ollama](https://ollama.com) installed locally with a tool-calling-capable
    model pulled (e.g. `mistral`).

  See {doc}`../features/reasoning-engines` for the trade-offs between the
  three.

## Clone and set up the virtual environment

The application and the Streamlit demo dashboard use **two separate virtual
environments** — this is deliberate, not an oversight; see
{doc}`../interfaces/streamlit-dashboard` for exactly why.

```bash
cd path/to/suuply_chain_ai
python -m venv venv
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` chains `-r requirements.txt` and adds `pytest`,
`pytest-asyncio`, `pytest-cov`, and `httpx` on top — install this one (not
the bare `requirements.txt`) for local development so the test suite works
out of the box.

### What gets installed

| Package group | Purpose |
|---|---|
| `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings` | Web framework and settings/validation |
| `sqlalchemy[asyncio]`, `asyncpg`, `aiosqlite`, `alembic` | Async ORM, Postgres/SQLite drivers, migrations |
| `loguru`, `python-dotenv` | Structured logging, `.env` loading |
| `langgraph`, `langchain-core`, `langchain-groq`, `langchain-ollama`, `langchain-google-genai`, `groq` | Agent orchestration and the three reasoning-engine clients |
| `torch`, `transformers`, `accelerate`, `chronos-forecasting` | HuggingFace Chronos demand forecasting (CPU-only; first run downloads ~30-40MB of model weights) |

The first `torch`/`transformers` install is the heaviest part of this step —
budget a few minutes and a few GB of disk on a fresh machine.

## Verify the install

```bash
venv\Scripts\python.exe -c "import app.core.config; print('ok')"
```

If this prints `ok` with no traceback, the core dependency set resolved
correctly. Continue to {doc}`configuration` to set up your `.env` file, then
{doc}`quickstart` to seed sample data and run the pipeline end to end.

## Optional: the Streamlit dashboard's environment

If you also want the demo dashboard ({doc}`../interfaces/streamlit-dashboard`),
set up its **own** virtual environment once you've confirmed the core install
works:

```bash
python -m venv venv-ui
venv-ui\Scripts\python.exe -m pip install --upgrade pip
venv-ui\Scripts\python.exe -m pip install -r requirements-ui.txt
```

This is not optional friction — `requirements-ui.txt` deliberately does not
chain `-r requirements.txt`. See {doc}`../interfaces/streamlit-dashboard` for
the exact dependency conflict this avoids.
