from pydantic import BaseModel


class StopETA(BaseModel):
    vehicle_id: int
    store_id: int
    sequence: int
    predicted_eta_hours: float
    at_risk: bool
    # Which of the real risk signals fired: "exceeds_max_lead_time",
    # "vehicle_capacity_exceeded", "replanning_triggered".
    risk_reasons: list[str]
    suggested_contingency: str | None


class ScenarioETAPrediction(BaseModel):
    strategy: str
    stop_etas: list[StopETA]
    at_risk_count: int


class ETAPredictionResult(BaseModel):
    scenario_predictions: list[ScenarioETAPrediction]
