"""Deterministic scenario stress testing for shortage demand multipliers."""
from dataclasses import dataclass
from collections import defaultdict
from app.schemas.allocation import AllocationScenario


@dataclass(frozen=True)
class StressResult:
    demand_multiplier: float
    service_level: float
    uncovered_units: float


def stress_test(scenario: AllocationScenario, shortages, multipliers=(0.8, 1.0, 1.2)):
    delivered = defaultdict(int)
    for line in scenario.lines:
        delivered[(line.store_id, line.product_id)] += line.quantity
    results = []
    for multiplier in multipliers:
        if multiplier <= 0:
            raise ValueError("Demand multiplier must be positive")
        expected = {}
        for shortage in shortages:
            store_id = getattr(shortage, "location_id", None)
            if store_id is None:
                store_id = shortage.store_id
            key = (store_id, shortage.product_id)
            expected[key] = expected.get(key, 0.0) + max(0.0, shortage.shortage_qty * multiplier)
        total = sum(expected.values())
        covered = sum(min(quantity, delivered.get(key, 0)) for key, quantity in expected.items())
        results.append(StressResult(
            demand_multiplier=multiplier,
            service_level=covered / total if total else 1.0,
            uncovered_units=max(0.0, total - covered),
        ))
    return results
