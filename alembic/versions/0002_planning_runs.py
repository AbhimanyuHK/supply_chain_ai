"""planning_runs: audit trail for every AI-generated plan (scope, engine, status, full stage data)

Revision ID: 0002_planning_runs
Revises: 0001_initial_schema
Create Date: 2026-07-30

"""

import sqlalchemy as sa

from alembic import op

revision = "0002_planning_runs"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

planning_run_status_enum = sa.Enum("success", "failed", name="planning_run_status_enum")


def upgrade() -> None:
    op.create_table(
        "planning_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("planning_date", sa.Date(), nullable=False),
        sa.Column("store_ids", sa.JSON(), nullable=True),
        sa.Column("product_ids", sa.JSON(), nullable=True),
        sa.Column("demand_history_window_days", sa.Integer(), nullable=False),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("llm_provider", sa.String(32), nullable=False),
        sa.Column("llm_model", sa.String(128), nullable=False),
        sa.Column("status", planning_run_status_enum, nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("trace", sa.JSON(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.Column("replanning_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("request_payload", sa.JSON(), nullable=True),
        sa.Column("master_data_snapshot", sa.JSON(), nullable=True),
        sa.Column("demand_forecast", sa.JSON(), nullable=True),
        sa.Column("inventory_analysis", sa.JSON(), nullable=True),
        sa.Column("supply_planning", sa.JSON(), nullable=True),
        sa.Column("allocation", sa.JSON(), nullable=True),
        sa.Column("cost_optimization", sa.JSON(), nullable=True),
        sa.Column("constraint_validation", sa.JSON(), nullable=True),
        sa.Column("decision_review", sa.JSON(), nullable=True),
        sa.Column("final_recommendation", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_planning_runs_scope_key", "planning_runs", ["scope_key"])
    op.create_index("ix_planning_runs_created_at", "planning_runs", ["created_at"])


def downgrade() -> None:
    op.drop_table("planning_runs")

    bind = op.get_bind()
    planning_run_status_enum.drop(bind, checkfirst=True)
