"""Persistent approval decisions and event audit

Revision ID: 0005_decision_workflows
Revises: 0004_fleet_route_eta_and_shipment_links
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_decision_workflows"
down_revision = "0004_fleet_route_eta_and_shipment_links"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "plan_approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("planning_run_id", sa.Integer(), sa.ForeignKey("planning_runs.id"), unique=True, nullable=False),
        sa.Column("strategy", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reviewer", sa.String(128)),
        sa.Column("reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "replanning_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(128), unique=True, nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("magnitude", sa.Numeric(12, 5), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("replanning_events")
    op.drop_table("plan_approvals")
