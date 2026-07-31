"""planning_runs: data_fingerprint (idempotent caching), optimization_objective, master_data_row_counts

Revision ID: 0003_planning_run_idempotency_and_objective
Revises: 0002_planning_runs
Create Date: 2026-07-30

"""

import sqlalchemy as sa

from alembic import op

revision = "0003_planning_run_idempotency_and_objective"
down_revision = "0002_planning_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("planning_runs", sa.Column("data_fingerprint", sa.String(64), nullable=True))
    op.add_column(
        "planning_runs",
        sa.Column("optimization_objective", sa.String(32), nullable=False, server_default="minimize_cost"),
    )
    op.add_column("planning_runs", sa.Column("master_data_row_counts", sa.JSON(), nullable=True))
    op.create_index(
        "ix_planning_runs_cache_lookup",
        "planning_runs",
        ["scope_key", "data_fingerprint", "llm_provider", "llm_model"],
    )


def downgrade() -> None:
    op.drop_index("ix_planning_runs_cache_lookup", table_name="planning_runs")
    op.drop_column("planning_runs", "master_data_row_counts")
    op.drop_column("planning_runs", "optimization_objective")
    op.drop_column("planning_runs", "data_fingerprint")
