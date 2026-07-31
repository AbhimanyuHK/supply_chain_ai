"""Manually run the LangGraph planning workflow against whatever is in the
configured database, and print a summary of each node's output.

Currently runs: Load Master Data -> Demand Forecast -> Inventory Analysis ->
Supply Planning -> Allocation -> Cost Optimization -> Constraint Validation ->
Decision Review -> Final Recommendation, with a feedback loop from
Constraint Validation back to Supply Planning if nothing validates. Supply
Planning, Allocation, Decision Review, and Final Recommendation all call
Groq, so GROQ_API_KEY must be set in .env for those to complete (the other
nodes need no API key; the Groq-calling nodes make zero calls when there
are no shortages in scope).

Usage:
    venv/Scripts/python.exe scripts/run_planning_workflow.py
    venv/Scripts/python.exe scripts/run_planning_workflow.py --store-ids 1 2 --product-ids 1 2 3
"""

import argparse
import asyncio
import datetime
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.graph import run_planning_workflow
from app.schemas.planning import PlanningRequest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-ids", type=int, nargs="*", default=None)
    parser.add_argument("--product-ids", type=int, nargs="*", default=None)
    parser.add_argument("--demand-history-window-days", type=int, default=90)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    request = PlanningRequest(
        planning_date=datetime.date.today(),
        store_ids=args.store_ids,
        product_ids=args.product_ids,
        demand_history_window_days=args.demand_history_window_days,
    )

    result = await run_planning_workflow(request)

    print("Trace:")
    for line in result["trace"]:
        print(f"  - {line}")

    snapshot = result["master_data"]
    print("\nMaster data snapshot:")
    print(f"  Stores:           {len(snapshot.stores)}")
    print(f"  Terminals:        {len(snapshot.terminals)}")
    print(f"  Products:         {len(snapshot.products)}")
    print(f"  Inventory rows:   {len(snapshot.inventory)}")
    print(f"  Demand history:   {len(snapshot.demand_history)}")
    print(f"  Fleet vehicles:   {len(snapshot.fleet)}")
    print(f"  Distance entries: {len(snapshot.distance_matrix)}")
    print(f"  Business rules:   {snapshot.business_rules.model_dump()}")

    forecast = result["demand_forecast"]
    print("\nDemand forecast:")
    print(f"  Model:            {forecast.model_name}")
    print(f"  Horizon (days):   {forecast.horizon_days}")
    print(f"  Forecast points:  {len(forecast.forecasts)}")
    print(f"  Skipped pairs:    {len(forecast.skipped_pairs)} (no history)")

    by_pair: dict[tuple[int, int], list] = defaultdict(list)
    for point in forecast.forecasts:
        by_pair[(point.store_id, point.product_id)].append(point)

    print("\n  Sample (first store/product pair, first 5 days):")
    if by_pair:
        first_key = next(iter(by_pair))
        for point in sorted(by_pair[first_key], key=lambda p: p.date)[:5]:
            print(
                f"    store={point.store_id} product={point.product_id} date={point.date} "
                f"predicted={point.predicted_qty:.2f} (low={point.low_qty:.2f}, high={point.high_qty:.2f})"
            )

    inventory_analysis = result["inventory_analysis"]
    print("\nInventory analysis:")
    print(f"  Rows analyzed:    {len(inventory_analysis.records)}")
    print(f"  Below reorder:    {len(inventory_analysis.shortages)}")

    print("\n  Shortages (first 5):")
    for record in inventory_analysis.shortages[:5]:
        print(
            f"    {record.location_type.value}={record.location_id} product={record.product_id} "
            f"available={record.available_qty} incoming={record.incoming_qty} "
            f"reorder_point={record.reorder_point:.1f} shortage={record.shortage_qty:.1f}"
        )
    if not inventory_analysis.shortages:
        print("    (none)")

    supply_planning = result["supply_planning"]
    print("\nSupply planning:")
    print(f"  Candidate plans:  {len(supply_planning.candidate_plans)}")
    print(f"  Unresolved:       {len(supply_planning.unresolved_shortages)} (no candidate terminal)")

    print("\n  Candidate plans (first 10, sorted by score):")
    ranked = sorted(supply_planning.candidate_plans, key=lambda p: p.score, reverse=True)
    for plan in ranked[:10]:
        print(
            f"    terminal={plan.terminal_id} -> store={plan.store_id} product={plan.product_id} "
            f"qty={plan.quantity} cost={plan.estimated_transport_cost:.2f} "
            f"delivery={plan.estimated_delivery_hours:.1f}h score={plan.score:.0f}"
        )
        print(f"      rationale: {plan.rationale}")
    if not supply_planning.candidate_plans:
        print("    (none)")

    allocation = result["allocation"]
    print("\nAllocation scenarios (ranked best to worst):")
    if not allocation.scenarios:
        print("    (none - no shortages to allocate)")
    for scenario in allocation.scenarios:
        print(
            f"  #{scenario.rank} {scenario.strategy}: fulfillment={scenario.fulfillment_rate:.0%} "
            f"cost={scenario.total_estimated_cost:.2f} "
            f"high_priority={scenario.high_priority_shortages_fulfilled}/{scenario.high_priority_shortages_total} "
            f"lines={len(scenario.lines)}"
        )
        print(f"      rationale: {scenario.rationale}")
    if allocation.recommended_strategy:
        print(f"\n  Recommended strategy: {allocation.recommended_strategy}")

    cost_optimization = result["cost_optimization"]
    print("\nCost optimization (real fleet-based costing):")
    if not cost_optimization.scenarios:
        print("    (none - no allocation scenarios to cost)")
    for scenario in cost_optimization.scenarios:
        print(
            f"  {scenario.strategy}: total={scenario.total_cost:.2f} "
            f"(transport={scenario.total_transportation_cost:.2f}, "
            f"handling={scenario.total_handling_cost:.2f}, "
            f"holding={scenario.total_holding_cost:.2f}, "
            f"delay_penalty={scenario.total_delay_penalty:.2f}) "
            f"high_priority={scenario.high_priority_shortages_fulfilled}/{scenario.high_priority_shortages_total}"
        )
        exceeded = sum(1 for line in scenario.lines if line.vehicle_capacity_exceeded)
        if exceeded:
            print(f"      warning: {exceeded} line(s) exceed available vehicle capacity")
    if cost_optimization.recommended_strategy:
        print(f"\n  Recommended (cost-optimal): {cost_optimization.recommended_strategy}")
        print(f"  Rationale: {cost_optimization.recommendation_rationale}")

    validation = result["constraint_validation"]
    print("\nConstraint validation:")
    if not validation.scenario_validations:
        print("    (none - no allocation scenarios to validate)")
    for sv in validation.scenario_validations:
        status = "VALID" if sv.is_valid else f"{len(sv.violations)} violation(s)"
        print(f"  {sv.strategy}: {status}")
        for v in sv.violations:
            print(f"      [{v.constraint}] {v.message}")
    print(f"\n  Final strategy: {validation.final_strategy}")
    print(f"  Replanning attempts used: {result.get('replanning_attempts', 0)}")
    if validation.unresolved_violations:
        print(f"  UNRESOLVED ({len(validation.unresolved_violations)}):")
        for v in validation.unresolved_violations:
            print(f"    [{v.constraint}] {v.message}")

    if result["errors"]:
        print("\nErrors:")
        for err in result["errors"]:
            print(f"  - {err}")

    decision_review = result["decision_review"]
    print("\nDecision review (holistic scoring, valid scenarios only):")
    if decision_review.fell_back_to_invalid_scenario:
        print("  WARNING: no scenario passed constraint validation - reviewing best-effort pick only")
    for evaluation in sorted(decision_review.evaluations, key=lambda e: e.overall_score, reverse=True):
        print(
            f"  {evaluation.strategy}: score={evaluation.overall_score:.0f} "
            f"balance={evaluation.inventory_balance_score:.2f} "
            f"distance={evaluation.total_transportation_distance_km:.1f}km "
            f"fulfillment={evaluation.demand_fulfillment_rate:.0%} "
            f"risk={evaluation.future_inventory_risk_ratio:.2f} "
            f"cost={evaluation.total_cost:.2f} "
            f"high_priority={evaluation.high_priority_shortages_fulfilled}/{evaluation.high_priority_shortages_total}"
        )
        print(f"      rationale: {evaluation.rationale}")
    if decision_review.selected_strategy:
        print(f"\n  FINAL SELECTION: {decision_review.selected_strategy}")
        print(f"  Rationale: {decision_review.selection_rationale}")

    final = result["final_recommendation"]
    print("\n" + "=" * 70)
    print("FINAL RECOMMENDATION")
    print("=" * 70)
    if final.selected_strategy is None:
        print("  (none - nothing to recommend)")
    else:
        print(f"  Strategy: {final.selected_strategy}")
        print(f"  Confidence: {final.confidence_score:.0f}/100")
        print(f"  Expected total cost: {final.expected_total_cost:.2f}")
        print(f"  Expected service level: {final.expected_service_level:.0%}")
        if final.fell_back_to_invalid_scenario:
            print("  WARNING: this is a best-effort plan with unresolved constraint violations")
        if final.unresolved_shortages_count:
            print(f"  WARNING: {final.unresolved_shortages_count} shortage(s) had no candidate terminal at all")

        print(f"\n  Business explanation: {final.business_explanation}")
        print(f"\n  Risk assessment: {final.risk_assessment}")
        print("  Contingency actions:")
        for action in final.contingency_actions:
            print(f"    - {action}")

        print(f"\n  Shipment plan ({len(final.shipment_plan)} lines):")
        for line in final.shipment_plan[:10]:
            print(
                f"    terminal={line.terminal_id} -> store={line.store_id} product={line.product_id} "
                f"qty={line.quantity} total_cost={line.total_cost:.2f} delivery={line.estimated_delivery_hours:.1f}h"
            )
            print(f"      why: {line.explanation}")

        print(f"\n  Expected inventory after shipment ({len(final.expected_inventory_after_shipment)} entries):")
        for proj in final.expected_inventory_after_shipment[:10]:
            print(
                f"    {proj.location_type.value}={proj.location_id} product={proj.product_id}: "
                f"{proj.before_qty} -> {proj.after_qty}"
            )

        print(f"\n  Alternative recommendations ({len(final.alternative_recommendations)}):")
        for alt in final.alternative_recommendations:
            print(
                f"    {alt.strategy}: score={alt.overall_score:.0f} cost={alt.total_cost:.2f} "
                f"fulfillment={alt.fulfillment_rate:.0%}"
            )
            print(f"      {alt.reason_not_selected}")


if __name__ == "__main__":
    asyncio.run(main())
