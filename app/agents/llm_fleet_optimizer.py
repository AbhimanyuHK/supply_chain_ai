"""LLM-proposed vehicle assignment, verified against independent capacity checks.

This is an optional planning primitive, not a dispatch or reservation action.
"""
from collections import defaultdict
from functools import lru_cache
from pydantic import BaseModel, Field
from app.core.llm import get_chat_model
from app.models.entities import VehicleStatus


class ProposedVehicleAssignment(BaseModel):
    line_index: int = Field(ge=0)
    vehicle_id: int


class ProposedFleetPlan(BaseModel):
    assignments: list[ProposedVehicleAssignment]
    rationale: str


@lru_cache
def _model():
    return get_chat_model().with_structured_output(ProposedFleetPlan)


def validate_fleet_plan(plan, lines, fleet, products):
    vehicles = {v.vehicle_id: v for v in fleet if v.status == VehicleStatus.AVAILABLE}
    product_by_id = {p.product_id: p for p in products}
    assignments = {}
    weights = defaultdict(float)
    volumes = defaultdict(float)
    for item in plan.assignments:
        if item.line_index >= len(lines) or item.line_index in assignments:
            return None
        line = lines[item.line_index]
        vehicle = vehicles.get(item.vehicle_id)
        product = product_by_id.get(line.product_id)
        if vehicle is None or product is None or vehicle.terminal_id != line.terminal_id:
            return None
        assignments[item.line_index] = item.vehicle_id
        weights[item.vehicle_id] += float(product.weight) * line.quantity
        volumes[item.vehicle_id] += float(product.volume) * line.quantity
        if weights[item.vehicle_id] > float(vehicle.capacity_weight):
            return None
        if volumes[item.vehicle_id] > float(vehicle.capacity_volume):
            return None
    return assignments if len(assignments) == len(lines) else None


async def propose_fleet_plan(lines, fleet, products):
    if not lines:
        return {}
    prompt = (
        "Propose a complete vehicle assignment for all indexed shipment lines. "
        "Each vehicle must be AVAILABLE at the source terminal, and total assigned "
        "weight and volume must not exceed its capacity. Minimize vehicle fixed "
        "cost and travel cost without inventing vehicles. "
        f"Lines: {[{'index': i, 'terminal_id': x.terminal_id, 'product_id': x.product_id, 'quantity': x.quantity} for i, x in enumerate(lines)]}. "
        f"Vehicles: {[{'id': v.vehicle_id, 'terminal_id': v.terminal_id, 'status': str(v.status), 'weight': float(v.capacity_weight), 'volume': float(v.capacity_volume)} for v in fleet]}. "
        f"Products: {[{'id': p.product_id, 'weight': float(p.weight), 'volume': float(p.volume)} for p in products]}."
    )
    result = await _model().ainvoke(prompt)
    return validate_fleet_plan(result, lines, fleet, products)
