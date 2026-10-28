"""Replanning execution metadata and recovery fields.

Revision ID: 0007_replanning_recovery
Revises: 0006_shipment_creation_claims
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_replanning_recovery"
down_revision = "0006_shipment_creation_claims"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("replanning_events", sa.Column(
        "processing_started_at", sa.DateTime(timezone=True), nullable=True
    ))
    op.add_column("replanning_events", sa.Column(
        "attempt_count", sa.Integer(), nullable=False, server_default="0"
    ))
    op.add_column("replanning_events", sa.Column(
        "last_error", sa.Text(), nullable=True
    ))
    op.add_column("replanning_events", sa.Column(
        "planning_run_id", sa.Integer(), sa.ForeignKey("planning_runs.id"), nullable=True
    ))


def downgrade():
    op.drop_column("replanning_events", "planning_run_id")
    op.drop_column("replanning_events", "last_error")
    op.drop_column("replanning_events", "attempt_count")
    op.drop_column("replanning_events", "processing_started_at")
