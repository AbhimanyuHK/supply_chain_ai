"""shipments: vehicle_id/planning_run_id links; planning_runs: fleet_assignment,
route_planning, eta_prediction stage columns (Phase 2)

Revision ID: 0004_fleet_route_eta_and_shipment_links
Revises: 0003_planning_run_idempotency_and_objective
Create Date: 2026-07-31

"""

import sqlalchemy as sa

from alembic import op

revision = "0004_fleet_route_eta_and_shipment_links"
down_revision = "0003_planning_run_idempotency_and_objective"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite can't ALTER a foreign-key constraint onto an existing column directly
    # (only plain ADD COLUMN) - batch mode does the copy-and-move table rebuild
    # this needs. Runs as a no-op wrapper (recreate_table="never") on Postgres.
    with op.batch_alter_table("shipments") as batch_op:
        batch_op.add_column(sa.Column("vehicle_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("planning_run_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_shipments_vehicle_id_fleet", "fleet", ["vehicle_id"], ["vehicle_id"]
        )
        batch_op.create_foreign_key(
            "fk_shipments_planning_run_id_planning_runs", "planning_runs", ["planning_run_id"], ["id"]
        )
    op.create_index("ix_shipments_planning_run", "shipments", ["planning_run_id"])

    op.add_column("planning_runs", sa.Column("fleet_assignment", sa.JSON(), nullable=True))
    op.add_column("planning_runs", sa.Column("route_planning", sa.JSON(), nullable=True))
    op.add_column("planning_runs", sa.Column("eta_prediction", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("planning_runs", "eta_prediction")
    op.drop_column("planning_runs", "route_planning")
    op.drop_column("planning_runs", "fleet_assignment")

    op.drop_index("ix_shipments_planning_run", table_name="shipments")
    with op.batch_alter_table("shipments") as batch_op:
        batch_op.drop_constraint("fk_shipments_planning_run_id_planning_runs", type_="foreignkey")
        batch_op.drop_constraint("fk_shipments_vehicle_id_fleet", type_="foreignkey")
        batch_op.drop_column("planning_run_id")
        batch_op.drop_column("vehicle_id")
