"""Persist scoped replanning request for autonomous workers.

Revision ID: 0008_event_scope
Revises: 0007_replanning_recovery
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_event_scope"
down_revision = "0007_replanning_recovery"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("replanning_events", sa.Column("planning_request", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("replanning_events", "planning_request")
