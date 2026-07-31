# Supply Planning Agent

The fourth node (`analyze_inventory → plan_supply → ...`), implemented in
`app/agents/supply_planning_agent.py`. **The first node to call a
reasoning engine** — via `get_chat_model().with_structured_output(...)`,
cached process-wide the same way the Chronos pipeline is.

## Finding candidates

For every shortage from the Inventory Analysis agent, candidate supplying
terminals are found from real master data: terminal inventory rows for
that product with stock greater than zero, joined against the distance
matrix for `(terminal, store)`. Terminals with no distance-matrix entry to
that store are skipped outright — there's no basis to estimate cost or
delivery time for them. Remaining candidates are sorted by distance and
capped at `Settings.supply_planning_max_candidate_terminals` (default 5)
to bound prompt size at the platform's target scale (10,000+ terminals).

Inventory is pre-grouped into `dict[product_id, list[InventoryRead]]` once
per run rather than re-scanned per shortage — see
{doc}`../features/scalability` (Fix 3).

## Division of labor with the LLM

The reasoning engine is prompted to propose one alternative candidate plan
per candidate terminal, each with a `quantity`, a one-sentence
`rationale`, and a `score` (0-100). It does **not** decide
`estimated_transport_cost` or `estimated_delivery_hours` — those are
computed here from the real distance matrix and
`business_rules.estimated_transport_cost_per_km` (a rough proxy rate; real
fleet-based costing is the {doc}`Cost Optimization Agent <cost-optimization-agent>`'s
job), then attached to whichever terminal the LLM picked. The LLM cannot
hallucinate a distance or cost number into existence — it only ever
judges options it's shown real numbers for.

The agent clamps each returned `quantity` to `[0, terminal.available_qty]`
— the only validation performed on this first pass. It deliberately does
**not** hard-enforce other business/capacity constraints here (lead time,
store/terminal capacity, max shipment quantity) — per the spec's own
agent breakdown, that's the {doc}`Constraint Validation Agent <constraint-validation-agent>`'s
job, which rejects invalid plans and sends them back here for replanning
(see below). It also doesn't arbitrate cross-store priority trade-offs
when terminal stock is scarce across many stores — that's the
{doc}`Allocation Agent <allocation-agent>`'s job.

Shortages with zero candidate terminals go straight to
`unresolved_shortages` with no LLM call at all.

## Batching — the biggest scalability change

At scale (thousands of shortages), calling the LLM once per shortage
sequentially would mean thousands of sequential round-trips per run,
easily exceeding a tight per-minute rate cap (Gemini's confirmed real
limit is 5 requests/minute on Flash models). Shortages are grouped into
batches of `Settings.supply_planning_batch_size` (default 25); one prompt
covers a whole batch, with each shortage keeping its own block inside that
prompt (including its own retry-violation note — see below). Batches are
matched back to their originating shortage by `(store_id, product_id)`,
and any shortage a batch response omits entirely is logged as a warning —
distinct from `unresolved_shortages`, which means "no candidate terminal
existed in the data" rather than "the LLM didn't respond for this one."

Batches run concurrently, bounded by
`asyncio.Semaphore(Settings.llm_max_concurrent_requests)` (default 3 —
Groq, the default provider, has generous limits; Gemini free-tier
operators should override this to 1 via `.env`). See
{doc}`../features/scalability` (Fix 4) for the full rationale, including
the documented gap this doesn't solve (a semaphore bounds simultaneity,
not requests-per-minute).

## Closing the replanning loop

When the Constraint Validation agent rejects every scenario and routes
back here, `_prior_violation_messages_by_shortage` reads
`state["constraint_validation"]`, groups violation messages by
`(store_id, product_id)`, and folds them into that shortage's next prompt
("a previous proposal was rejected for these reasons: ... adjust
accordingly"). Without this, a retry would just re-ask the identical
question and likely get the identical answer — this is what makes the
replanning loop an actual correction attempt rather than a no-op retry.
See {doc}`constraint-validation-agent` for the other side of this loop.

## Manual run

```bash
venv\Scripts\python.exe scripts\run_planning_workflow.py
```

Requires `GROQ_API_KEY` (or the equivalent for whichever provider is
configured — see {doc}`../features/reasoning-engines`); the first three
nodes don't need one. Prints ranked candidate plans with rationale per
shortage.
