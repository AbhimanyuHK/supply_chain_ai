# LLM-native allocation (development preview)

This branch adds an **opt-in experimental LLM allocation solver**. No OR-Tools, CBC, Gurobi, or Pyomo.

Set `LLM_NATIVE_OPTIMIZER_ENABLED=true` and optionally `LLM_OPTIMIZER_ITERATIONS=3` in your environment. The existing three Python allocation heuristics remain as baselines and the default behavior remains unchanged.

The LLM proposes full allocation quantities; Python independently rejects proposals that use unknown lanes, exceed terminal-product stock, or exceed store-product shortages. Accepted proposals join the existing cost optimization, constraint validation, and decision-review pipeline. The LLM gets objective feedback between bounded attempts.

**Important limitations:** This is an initial implementation, not a globally optimal solver. It does not yet implement a separate critic agent, persist cross-run best-solution memory, add fleet/route feasibility into the proposal loop, or perform full benchmark evaluation. The current objective feedback uses estimated allocation costs; final downstream costing and business validation remain authoritative. An invalid LLM proposal is discarded; the existing deterministic baselines remain available. LLM API errors are not silently suppressed.

## Testing

`pytest tests/test_llm_native_optimizer.py`

Run the existing suite before promoting this experimental mode. Do not enable for operational decisions without further validation.
