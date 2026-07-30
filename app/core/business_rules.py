"""Business rules loader.

The spec lists "Business Rules" among the master data the Master Data Agent
loads, but defines no database table for it — so it's a small editable YAML
file (`config/business_rules.yaml`) rather than a hardcoded constant, letting
planners tune it without a code change or migration.
"""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

BUSINESS_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "business_rules.yaml"


class BusinessRules(BaseModel):
    default_safety_stock_days: int = 7
    default_lead_time_days: int = 2
    min_shipment_qty: int = 1
    max_shipment_qty_per_product: int = 5000
    reorder_point_multiplier: float = 1.5
    high_priority_store_threshold: int = 2
    estimated_transport_cost_per_km: float = 50.0
    warehouse_handling_cost_per_unit: float = 5.0
    inventory_holding_cost_rate: float = 0.0005
    delay_penalty_per_hour: float = 20.0
    max_lead_time_days: int = 5


@lru_cache
def get_business_rules() -> BusinessRules:
    if not BUSINESS_RULES_PATH.exists():
        return BusinessRules()

    with open(BUSINESS_RULES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return BusinessRules(**data)
