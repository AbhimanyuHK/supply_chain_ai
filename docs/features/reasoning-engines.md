# Reasoning Engines: Groq, Gemini, and Ollama

All four LLM-calling agents get their model from one factory,
`app/core/llm.py`, rather than instantiating a client directly — this is
what makes switching providers a one-line `.env` change with zero code
differences per agent.

## Why three providers exist

Groq's free tier has a **100,000 tokens/day** cap, which normal
test-suite-plus-manual-run usage can exhaust mid-session — a 429 from
Groq during development is a quota limit, not a bug. Rather than block on
that external quota, `Settings.llm_provider` (`"groq"` default,
`"gemini"`, or `"ollama"`) selects which reasoning engine every agent
uses.

## `get_chat_model()`

Returns `ChatGroq(...)`, `ChatGoogleGenerativeAI(...)`, or `ChatOllama(...)`
depending on `Settings.llm_provider`, `@lru_cache`'d like the Chronos
pipeline. Every agent calls
`get_chat_model().with_structured_output(Schema)` — an identical
structured-output contract across all three, since `langchain-groq`,
`langchain-google-genai`, and `langchain-ollama` all implement the same
interface via tool-calling.

## `get_active_model_name()`

Returns a human-readable model name (e.g. `ollama/mistral`,
`gemini/gemini-2.5-flash`, or `llama-3.3-70b-versatile`) for trace/log
messages, so a run's trace never misattributes which engine actually
produced a result. This mattered in practice: earlier versions hardcoded
`settings.groq_model` in trace strings, which kept saying "via
llama-3.3-70b-versatile" even during a live Ollama run.

## Provider comparison

| Provider | Rate limit | Best for |
|---|---|---|
| **Groq** (default) | 100,000 tokens/day (free tier) | Heavier runs, higher throughput |
| **Gemini** (`gemini-2.5-flash`) | **5 requests/minute** on Flash models (confirmed via Google AI Studio's usage dashboard), reset per-minute | Quick single-shortage test runs only |
| **Ollama** (local) | None | Heavy runs with no external quota at all, once a tool-calling-capable model is pulled locally |

```{warning}
Since every shortage costs 4 LLM calls, a single shortage can bump into
Gemini's 5 RPM ceiling, and multiple shortages in one run almost
certainly will — a `429 RESOURCE_EXHAUSTED` with a roughly 47-second
`retry_delay` is expected there, not a platform bug. Lower
`Settings.llm_max_concurrent_requests` to `1` when using Gemini (see
{doc}`scalability`), and prefer Groq or Ollama for anything beyond a
single-shortage smoke test.
```

Local Ollama models need tool-calling support (the default method
`with_structured_output` uses) — check `ollama show <model>` lists
`tools` under its capabilities before using one here. `mistral` does;
some smaller models (e.g. `phi3`) may not.

## Tests

`tests/conftest.py::requires_llm_configured` replaces what used to be
five near-identical `requires_groq_key` markers (one per LLM-calling test
file). The shared marker skips only when *none* of the three engines are
configured
(`not (groq_api_key or gemini_api_key or llm_provider == "ollama")`), so
the same tests provide real coverage against whichever engine is actually
set up — this is what lets CI's Gemini and Ollama jobs
(see {doc}`../operations/ci-cd`) exercise real assertions instead of
every LLM-gated test silently skipping.

## Determinism note

`groq_temperature`/`gemini_temperature`/`ollama_temperature` all default
to `0.0` — a defense-in-depth measure for genuinely fresh computations,
not the primary determinism guarantee. See
{doc}`idempotency-and-caching` for what actually guarantees "same input →
same output."
