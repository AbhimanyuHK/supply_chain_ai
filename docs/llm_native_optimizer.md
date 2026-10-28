# LLM-native allocation (development preview)

This branch adds an **opt-in experimental LLM allocation solver**. No OR-Tools, CBC, Gurobi, or Pyomo.

Set `LLM_NATIVE_OPTIMIZER_ENABLED=true` and optionally `LLM_OPTIMIZER_ITERATIONS=3` in your environment. The existing three Python allocation heuristics remain as baselines and the default behavior remains unchanged.

The LLM proposes full allocation quantities; Python independently rejects proposals that use unknown lanes, exceed terminal-product stock, or exceed store-product shortages. Accepted proposals join the existing cost optimization, constraint validation, and decision-review pipeline. The LLM gets objective feedback between bounded attempts.

**Important limitations:** This is an initial implementation, not a globally optimal solver. It does not yet implement a separate critic agent, persist cross-run best-solution memory, add fleet/route feasibility into the proposal loop, or perform full benchmark evaluation. The current objective feedback uses estimated allocation costs; final downstream costing and business validation remain authoritative. An invalid LLM proposal is discarded; the existing deterministic baselines remain available. LLM API errors are not silently suppressed.

## Testing

`pytest tests/test_llm_native_optimizer.py`

Run the existing suite before promoting this experimental mode. Do not enable for operational decisions without further validation.


## Critic-guided improvement (development)
The experimental solver now calls a separate structured-output Critic Agent between valid candidate attempts. Duplicate candidate fingerprints are detected and search stops after repeated stagnation. The existing deterministic allocation heuristics remain available as baselines.

## Benchmarking
`app/services/optimization_evaluator.py` reports each scenario's feasibility, source, fulfillment, priority coverage, estimated cost and delta against the priority-first baseline. It is a metric utility, not an automated end-to-end benchmark runner.

## Remaining work before the complete roadmap is delivered
- Real end-to-end tests and CI verification with mock LLMs and database fixtures.
- Stronger validator for shipment limits, store capacity, route feasibility and fleet constraints *before* candidate acceptance.
- Structured persistence of per-iteration proposals, critic feedback, feasibility and token/latency metrics.
- Robust multi-objective and uncertainty-aware optimization across forecast quantiles.
- LLM fleet and route proposals with independent operational validation.
- HITL approval and execution safeguards; do not persist recommendations as dispatched shipments.
- Event-triggered replanning, scenario simulation and control-tower visualization.
- Cache fingerprint must include optimizer configuration/prompt versions to avoid stale runs.
- True route optimization requires store-to-store distances; terminal-to-store distance sums are only proxies.

**Safety:** Experimental LLM proposals must not be automatically dispatched. No claim of global optimality is made.
