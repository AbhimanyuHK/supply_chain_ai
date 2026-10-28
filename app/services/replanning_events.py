"""Pure event-driven replanning gate; event transport and scheduling are external."""
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, Field


class SupplyChainEvent(BaseModel):
    event_id: str
    kind: str
    entity_id: str
    occurred_at: datetime
    magnitude: float = Field(default=0, ge=0)
    planning_request: dict | None = None


REPLAN_KINDS = {"inventory_changed", "demand_spike", "vehicle_unavailable", "delivery_delayed"}


def should_replan(event: SupplyChainEvent, *, last_planned_at: datetime | None,
                  minimum_interval_minutes: int = 15, threshold: float = 0.1) -> bool:
    if event.kind not in REPLAN_KINDS or event.magnitude < threshold:
        return False
    if last_planned_at is None:
        return True
    if event.occurred_at.tzinfo is None or last_planned_at.tzinfo is None:
        raise ValueError("Both timestamps must be timezone-aware")
    return event.occurred_at - last_planned_at >= timedelta(minutes=minimum_interval_minutes)
