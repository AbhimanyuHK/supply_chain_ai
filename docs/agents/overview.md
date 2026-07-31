# Agents Overview

Ten Phase 1 agents (Master Data counts as the first), plus three Phase 2
agents — Fleet Assignment, Route Planning, ETA Prediction/Exception
Handling — gated behind `Settings.fleet_module_enabled` (default `False`).
See {doc}`../architecture/planning-workflow` for the full graph, both
with the flag off (9 nodes) and on (12 nodes).

## The "LLM judges, code decides" split, agent by agent

| Agent | Calls an LLM? | What's delegated to the LLM | What stays deterministic Python |
|---|---|---|---|
| {doc}`master-data-agent` | No | — | Everything |
| {doc}`demand-forecast-agent` | No (HuggingFace Chronos) | — | Everything except the ML inference itself |
| {doc}`inventory-analysis-agent` | No | — | Everything |
| {doc}`supply-planning-agent` | Yes | Rank/propose candidate terminals with a rationale, per shortage | Distance, cost, quantity clamping |
| {doc}`allocation-agent` | Yes | Rank three finished scenarios with a rationale | The three allocation strategies themselves (stock conservation math) |
| {doc}`cost-optimization-agent` | No | — | Everything (real fleet/product cost arithmetic + selection) |
| {doc}`constraint-validation-agent` | No | — | Everything (a decision tree against real data) |
| {doc}`fleet-assignment-agent` (Phase 2) | No | — | Everything (deterministic bin-packing) |
| {doc}`route-planning-agent` (Phase 2) | No | — | Everything (nearest-first sequencing, route cost) |
| {doc}`eta-prediction-agent` (Phase 2) | No | — | Everything (real thresholds, not a prose judgment) |
| {doc}`decision-review-agent` | Yes | Score each valid scenario 0-100 across six real metrics | The six metrics themselves, and the final `argmax` selection |
| {doc}`final-recommendation-agent` | Yes | Synthesize a business explanation, risk assessment, confidence score | Shipment plan, expected inventory, alternatives |

Every LLM call is scoped narrowly to *judgment on real, already-computed
data* — never arithmetic, distance, or the actual final selection. This
is deliberate and consistent everywhere in this codebase: LLMs are
unreliable at exact multi-step arithmetic (e.g. conserving scarce stock
across many shipment lines without over-allocating it), while scoring or
explaining a finished, code-verified option is exactly what they're good
at and where getting it "slightly wrong" has no correctness consequence —
worst case, a mediocre rationale, never a broken plan.

## Which agents can call an LLM in a single run

Four nodes ever reach a reasoning engine — Supply Planning, Allocation,
Decision Review, Final Recommendation — and each does so through the same
factory (`app/core/llm.py::get_chat_model()`), so switching providers is a
one-line `.env` change with zero code differences per agent. See
{doc}`../features/reasoning-engines` for the full Groq/Gemini/Ollama
trade-off.

A scope with no shortages triggers zero LLM calls anywhere in the graph —
every LLM-calling agent short-circuits before reasoning about nothing.

## Pages in this section

```{toctree}
:maxdepth: 1

master-data-agent
demand-forecast-agent
inventory-analysis-agent
supply-planning-agent
allocation-agent
cost-optimization-agent
constraint-validation-agent
fleet-assignment-agent
route-planning-agent
eta-prediction-agent
decision-review-agent
final-recommendation-agent
```
