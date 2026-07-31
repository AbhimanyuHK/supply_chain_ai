"""Shared "which scenarios are reviewable" selection, used by both the Fleet
Assignment Agent and the Decision Review Agent - extracted so a future change to
the fallback rule only needs updating in one place, not copy-pasted twice.
"""

from app.schemas.allocation import AllocationResult, AllocationScenario
from app.schemas.constraint_validation import ConstraintValidationResult


def select_reviewable_scenarios(
    allocation: AllocationResult, constraint_validation: ConstraintValidationResult
) -> tuple[list[AllocationScenario], bool]:
    """Returns (scenarios_to_process, fell_back).

    Normally every scenario that passed Constraint Validation. If none passed
    (replanning attempts exhausted), falls back to the single scenario matching
    `constraint_validation.final_strategy` - Constraint Validation's own
    best-effort pick - and `fell_back=True` so callers can say so explicitly
    rather than implying a confident choice was made among alternatives.
    """
    validity_by_strategy = {v.strategy: v.is_valid for v in constraint_validation.scenario_validations}
    reviewable = [s for s in allocation.scenarios if validity_by_strategy.get(s.strategy, False)]

    if reviewable:
        return reviewable, False

    fallback = [s for s in allocation.scenarios if s.strategy == constraint_validation.final_strategy]
    return fallback, True
