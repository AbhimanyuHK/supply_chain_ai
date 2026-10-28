"""Human approval state machine for recommendations, without dispatch side effects."""
from enum import Enum
from pydantic import BaseModel, Field


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalDecision(BaseModel):
    run_id: int
    strategy: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    reviewer: str | None = None
    reason: str | None = None


def decide(current: ApprovalDecision, *, reviewer: str, approve: bool, reason: str) -> ApprovalDecision:
    if current.status != ApprovalStatus.PENDING:
        raise ValueError("Decision is already final")
    if not reviewer.strip() or not reason.strip():
        raise ValueError("Reviewer and reason are required")
    return current.model_copy(update={
        "status": ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED,
        "reviewer": reviewer, "reason": reason,
    })
