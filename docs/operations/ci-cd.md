# CI/CD

`.github/workflows/ci.yml` runs on every push/PR to `main`, plus manual
dispatch, as **three independent jobs** — one per supported reasoning
engine, so every one of them gets genuinely exercised rather than just
the default.

## The three jobs

| Job | Provider | Secret needed | Notes |
|---|---|---|---|
| `test-groq` | Groq | `secrets.GROQ_API_KEY` | Missing secret → LLM-gated tests skip gracefully; job still passes |
| `test-gemini` | Gemini | `secrets.GEMINI_API_KEY` | Same graceful skip behavior |
| `test-ollama` | Ollama | None | Installs Ollama directly on the `ubuntu-latest` runner |

Each job installs `requirements-dev.txt`, sets `LLM_PROVIDER` (plus the
relevant API key) as an environment variable, and runs `pytest -v`. No
job can fail just because a secret is absent — see
{doc}`testing`'s `requires_llm_configured` for why.

## The Ollama job, in detail

Runs entirely without a secret, verifying the same fallback path a
developer would use locally during a Groq/Gemini outage:

```yaml
- name: Install Ollama
  run: curl -fsSL https://ollama.com/install.sh | sh

- name: Start Ollama server
  run: |
    nohup ollama serve > /tmp/ollama.log 2>&1 &
    for i in $(seq 1 30); do
      curl -sf http://localhost:11434/api/tags > /dev/null && exit 0
      sleep 2
    done
    echo "Ollama server did not become ready in time"; cat /tmp/ollama.log; exit 1

- name: Pull model
  run: ollama pull mistral
```

then runs the identical `pytest -v` command with `LLM_PROVIDER=ollama`,
`OLLAMA_MODEL=mistral`, `OLLAMA_BASE_URL=http://localhost:11434`.

## Dependency caching

All three jobs use `actions/setup-python`'s pip cache, keyed on
`requirements.txt` + `requirements-dev.txt`, to avoid re-installing
`torch`/`transformers`/`chronos-forecasting` from scratch on every run —
these are the heaviest packages in the dependency set (see
{doc}`../getting-started/installation`).

## What's not in CI yet

- No deployment step — CI is test-only today. See {doc}`deployment` for
  the manual production path.
- No documentation build check (`sphinx-build`) — see
  {doc}`../reference/troubleshooting` for how to run one locally; adding
  it as a CI job is a reasonable future addition, not built here.
- No linting/type-checking job — not yet part of this project's CI setup.
