# AI Supply Chain Planning Platform

An enterprise supply chain planning system that forecasts demand, analyzes
inventory, plans supply, allocates scarce stock across stores, optimizes
cost, validates business constraints, and synthesizes a final shipment
recommendation — orchestrated end to end by a nine-node
[LangGraph](https://www.langchain.com/langgraph) agent workflow reasoning
through a swappable LLM backend (Groq, Google Gemini, or a fully local Ollama
model).

This is not a thin LLM wrapper. Every number a stakeholder would actually
rely on — cost, distance, delivery time, inventory levels, constraint
pass/fail — is computed deterministically from real data. The LLM is used
only where genuine judgment is the point: proposing and scoring alternative
sourcing plans, ranking allocation scenarios, holistic multi-dimension
scenario review, and writing the final business narrative. See
{doc}`architecture/planning-workflow` for exactly where that line is drawn,
agent by agent.

```{admonition} What this documentation covers
:class: tip

This site is a complete reference for the platform as built: how to install
and run it, how each of the nine agents works and why it was designed that
way, how the reasoning-engine, idempotency, scalability, and cost-objective
systems fit together, and how to operate it (testing, CI, deployment,
troubleshooting).
```

## At a glance

| | |
|---|---|
| **Orchestration** | LangGraph `StateGraph`, 9 nodes, 1 conditional feedback loop |
| **Reasoning engines** | Groq (default), Google Gemini, local Ollama — one-line `.env` switch |
| **Forecasting** | HuggingFace Chronos (zero-shot time series, real model inference) |
| **Database** | SQLite (local dev) or PostgreSQL (staging/production) via one connection string |
| **API layer** | FastAPI — `/health`, `POST /optimize`, `GET /planning-runs`(`/{id}`); a few endpoints beyond that still scaffolded |
| **Demo UI** | Streamlit dashboard with run history and idempotent caching |
| **Persistence** | Every run is an auditable `PlanningRun` row — full traceability |
| **CI** | GitHub Actions — a hard-blocking lint job, plus one test job per reasoning engine |

## Where to start

- New to the project? Start with {doc}`getting-started/installation` and
  {doc}`getting-started/quickstart`.
- Want to understand the design? Read {doc}`architecture/overview` and
  {doc}`architecture/planning-workflow`.
- Looking for how a specific agent works? Jump straight to
  {doc}`agents/overview` and the agent's own page.
- Operating this in CI/production? See {doc}`operations/deployment` and
  {doc}`operations/ci-cd`.

```{toctree}
:maxdepth: 2
:caption: Getting Started

getting-started/installation
getting-started/configuration
getting-started/quickstart
```

```{toctree}
:maxdepth: 2
:caption: Architecture

architecture/overview
architecture/database-schema
architecture/planning-workflow
```

```{toctree}
:maxdepth: 2
:caption: Agents Reference

agents/overview
agents/master-data-agent
agents/demand-forecast-agent
agents/inventory-analysis-agent
agents/supply-planning-agent
agents/allocation-agent
agents/cost-optimization-agent
agents/constraint-validation-agent
agents/decision-review-agent
agents/final-recommendation-agent
```

```{toctree}
:maxdepth: 2
:caption: Cross-Cutting Features

features/reasoning-engines
features/idempotency-and-caching
features/scalability
features/cost-objectives
features/persistence-and-audit-trail
```

```{toctree}
:maxdepth: 2
:caption: Interfaces

interfaces/streamlit-dashboard
interfaces/rest-api
```

```{toctree}
:maxdepth: 2
:caption: Operations

operations/business-rules
operations/testing
operations/ci-cd
operations/deployment
```

```{toctree}
:maxdepth: 2
:caption: Reference

reference/troubleshooting
reference/roadmap
ARCHITECTURE
```
