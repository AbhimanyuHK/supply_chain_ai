# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-07-31

First tagged release. Phase 1 of the spec's 13-agent list is complete: all ten
agents, orchestrated end to end by a single LangGraph workflow, with the
cross-cutting engineering (scalability, idempotency, determinism,
auditability, documentation, CI) needed to call it release-ready.

### Added

- **Nine-node LangGraph planning workflow**: Master Data → Demand Forecast
  (real HuggingFace Chronos) → Inventory Analysis → Supply Planning (LLM) →
  Allocation (LLM) → Cost Optimization (real fleet-based costing) →
  Constraint Validation (with a replanning feedback loop) → Decision Review
  (LLM) → Final Recommendation (LLM). Every number a stakeholder would rely
  on (cost, distance, delivery time, inventory levels, constraint pass/fail)
  is computed deterministically; the LLM is used only for judgment —
  proposing/scoring alternatives, ranking scenarios, holistic review, and
  narrative synthesis.
- **Three-provider reasoning-engine abstraction**: Groq (default), Google
  Gemini, and local Ollama, switchable via a single `.env` variable with no
  per-agent code changes.
- **Planning-run persistence and audit trail**: every workflow invocation is
  recorded as a `PlanningRun` row — full input scope, reasoning
  engine/model, every intermediate stage's real output, and a
  success/failure status with error detail on failure.
- **Idempotent, cache-first planning runs**: the same scope, run against
  unchanged data with the same reasoning engine, always returns the
  identical prior result rather than recomputing — keyed on a data
  fingerprint (not just the request scope), so genuinely changed data still
  triggers a fresh computation.
- **Configurable optimization objective**: `minimize_cost` or
  `maximize_service_level`, chosen per planning request.
- **Scalability fixes validated against the platform's target scale**
  (1,000+ stores, 10,000+ terminals, millions of inventory rows): scoped
  master-data loading instead of unconditionally fetching every terminal,
  chunked SQL `IN (...)` queries (SQLite's parameter-count limit was a real
  crash risk at scale), batched LLM calls with bounded concurrency instead
  of one call per shortage, pre-grouped inventory lookups, and an opt-in
  toggle to persist only row counts instead of a full master-data snapshot
  per run.
- **Streamlit demo dashboard** with input/intermediate/final-plan tabs, run
  history browsing, and a force-re-run override.
- **GitHub Actions CI**, one job per supported reasoning engine (Groq,
  Gemini, Ollama), so every provider path is actually exercised.
- **Full Read the Docs documentation site** (Sphinx + MyST): installation,
  configuration, architecture, a dedicated page per agent, cross-cutting
  features, interfaces, operations, and a troubleshooting/roadmap
  reference — replacing the original single-page architecture write-up
  (kept as a legacy reference page).
- Apache License 2.0.

### Fixed

- **Non-deterministic demand forecasts**: HuggingFace Chronos samples
  random trajectories internally with no fixed seed, so identical
  historical data could produce a different forecast — and therefore a
  different plan and total cost — on separate fresh runs of the same
  scope. Fixed by seeding torch's RNG before every forecast call.
- **"Event loop is closed" crash** on repeated Streamlit dashboard runs and
  in back-to-back real-LLM test runs, caused by process-wide LLM/DB client
  caches holding references bound to a since-closed event loop.
- **CI never actually triggering**: the workflow was wired to run on
  pushes/PRs to `main`, but the repository's branch is `master` — CI had
  never fired automatically on a real push until this was corrected.
- Incorrect Python version metadata (`pyproject.toml` required `>=3.12`
  while the tested, working environment is 3.10).
- Incorrect documentation claims about Gemini's free-tier rate limit.

### Known limitations (see `docs/reference/roadmap.md` for the full list)

- Phase 2 (Fleet Assignment, Route Planning, ETA Prediction/Exception
  Handling) is not started.
- Only the `/health` REST endpoint is implemented; `/optimize` and the
  other spec'd endpoints are scaffolded, not wired to the workflow.
- No forward-looking promotions/holiday calendar for demand forecasting.
- `safety_stock` and `product_restrictions` constraints are not
  implemented as no distinct data exists to check them against.
- Lint tooling (`ruff`) is configured in `pyproject.toml` but not yet wired
  into CI or a dev dependency — a planned follow-up, not a Phase 1 blocker.
