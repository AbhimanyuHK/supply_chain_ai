"""Unique shipment creation claim.

Revision ID: 0006_shipment_creation_claims
Revises: 0005_decision_workflows
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_shipment_creation_claims"
down_revision = "0005_decision_workflows"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "shipment_creation_claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("planning_run_id", sa.Integer(), sa.ForeignKey("planning_runs.id"),
                  nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("shipment_creation_claims")
