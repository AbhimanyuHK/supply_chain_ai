"""Persist observed planning outcomes.

Revision ID: 0009_planning_outcomes
Revises: 0008_event_scope
"""
import sqlalchemy as sa
from alembic import op

revision = "0009_planning_outcomes"
down_revision = "0008_event_scope"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "planning_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_reference", sa.String(128), nullable=False, unique=True),
        sa.Column("planning_run_id", sa.Integer(), sa.ForeignKey("planning_runs.id"), nullable=False),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.store_id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.product_id"), nullable=False),
        sa.Column("observation_date", sa.Date(), nullable=False),
        sa.Column("actual_demand_qty", sa.Numeric(18, 4), nullable=False),
        sa.Column("fulfilled_qty", sa.Numeric(18, 4), nullable=False),
        sa.Column("actual_cost", sa.Numeric(18, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("actual_demand_qty >= 0 AND fulfilled_qty >= 0 AND actual_cost >= 0",
                           name="ck_planning_outcomes_nonnegative"),
    )
    op.create_index("ix_planning_outcomes_run_date", "planning_outcomes",
                    ["planning_run_id", "observation_date"])


def downgrade():
    op.drop_index("ix_planning_outcomes_run_date", table_name="planning_outcomes")
    op.drop_table("planning_outcomes")
