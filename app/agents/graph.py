"""LangGraph workflow definition.

Nine nodes, with the first feedback loop: Load Master Data -> Demand
Forecast -> Inventory Analysis -> Supply Planning -> Allocation -> Cost
Optimization -> Constraint Validation -> Decision Review -> Final
Recommendation. If Constraint Validation can't find any valid scenario, it
routes back to Supply Planning (capped by `max_replanning_attempts`) instead
of on to Decision Review - see
`constraint_validation_agent.route_after_validation`.

This completes every Phase 1 agent in the spec's 13-agent list. Only Phase
2's Fleet Assignment, Route Planning, and ETA Prediction/Exception Handling
agents remain, gated behind `Settings.fleet_module_enabled`.
"""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.allocation_agent import allocate_node
from app.agents.constraint_validation_agent import route_after_validation, validate_constraints_node
from app.agents.cost_optimization_agent import optimize_cost_node
from app.agents.decision_review_agent import review_decision_node
from app.agents.demand_forecast_agent import forecast_demand_node
from app.agents.final_recommendation_agent import recommend_final_node
from app.agents.inventory_analysis_agent import analyze_inventory_node
from app.agents.master_data_agent import load_master_data_node
from app.agents.state import PlanningState
from app.agents.supply_planning_agent import plan_supply_node
from app.schemas.planning import PlanningRequest


def build_graph() -> CompiledStateGraph:
    graph = StateGraph(PlanningState)

    graph.add_node("load_master_data", load_master_data_node)
    graph.add_node("forecast_demand", forecast_demand_node)
    graph.add_node("analyze_inventory", analyze_inventory_node)
    graph.add_node("plan_supply", plan_supply_node)
    graph.add_node("allocate", allocate_node)
    graph.add_node("optimize_cost", optimize_cost_node)
    graph.add_node("validate_constraints", validate_constraints_node)
    graph.add_node("review_decision", review_decision_node)
    graph.add_node("recommend_final", recommend_final_node)

    graph.add_edge(START, "load_master_data")
    graph.add_edge("load_master_data", "forecast_demand")
    graph.add_edge("forecast_demand", "analyze_inventory")
    graph.add_edge("analyze_inventory", "plan_supply")
    graph.add_edge("plan_supply", "allocate")
    graph.add_edge("allocate", "optimize_cost")
    graph.add_edge("optimize_cost", "validate_constraints")
    graph.add_conditional_edges(
        "validate_constraints", route_after_validation, {"replan": "plan_supply", "end": "review_decision"}
    )
    graph.add_edge("review_decision", "recommend_final")
    graph.add_edge("recommend_final", END)

    return graph.compile()


async def run_planning_workflow(request: PlanningRequest) -> PlanningState:
    graph = build_graph()
    initial_state: PlanningState = {"request": request, "trace": [], "errors": [], "replanning_attempts": 0}
    return await graph.ainvoke(initial_state)
