"""initial schema: stores, terminals, products, inventory, demand_history, fleet, shipments, distance_matrix

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-30

"""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

location_type_enum = sa.Enum("store", "terminal", name="location_type_enum")
vehicle_status_enum = sa.Enum(
    "available", "in_transit", "maintenance", "out_of_service", name="vehicle_status_enum"
)
shipment_status_enum = sa.Enum(
    "planned", "confirmed", "in_transit", "delivered", "cancelled", "exception",
    name="shipment_status_enum",
)


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "stores",
        sa.Column("store_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("store_name", sa.String(255), nullable=False),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
        *_timestamp_columns(),
        sa.CheckConstraint("capacity >= 0", name="ck_store_capacity_non_negative"),
    )
    op.create_index("ix_stores_priority", "stores", ["priority"])

    op.create_table(
        "terminals",
        sa.Column("terminal_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("terminal_name", sa.String(255), nullable=False),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        *_timestamp_columns(),
        sa.CheckConstraint("capacity >= 0", name="ck_terminal_capacity_non_negative"),
    )

    op.create_table(
        "products",
        sa.Column("product_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sku", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(128), nullable=False),
        sa.Column("weight", sa.Numeric(10, 3), nullable=False),
        sa.Column("volume", sa.Numeric(10, 3), nullable=False),
        sa.Column("cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("expiry_days", sa.Integer(), nullable=True),
        *_timestamp_columns(),
    )
    op.create_index("ix_products_category", "products", ["category"])

    op.create_table(
        "inventory",
        sa.Column("inventory_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("location_type", location_type_enum, nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.product_id"), nullable=False),
        sa.Column("available_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("incoming_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("damaged_qty", sa.Integer(), nullable=False, server_default="0"),
        *_timestamp_columns(),
        sa.CheckConstraint("available_qty >= 0", name="ck_inventory_available_non_negative"),
        sa.CheckConstraint("reserved_qty >= 0", name="ck_inventory_reserved_non_negative"),
        sa.CheckConstraint("incoming_qty >= 0", name="ck_inventory_incoming_non_negative"),
        sa.CheckConstraint("damaged_qty >= 0", name="ck_inventory_damaged_non_negative"),
        sa.UniqueConstraint(
            "location_type", "location_id", "product_id", name="uq_inventory_location_product"
        ),
    )
    op.create_index("ix_inventory_location", "inventory", ["location_type", "location_id"])
    op.create_index("ix_inventory_product", "inventory", ["product_id"])

    op.create_table(
        "demand_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.store_id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.product_id"), nullable=False),
        sa.Column("sales_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("promotion", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("holiday", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("date", "store_id", "product_id", name="uq_demand_history_date_store_product"),
    )
    op.create_index("ix_demand_history_store_product", "demand_history", ["store_id", "product_id"])
    op.create_index("ix_demand_history_date", "demand_history", ["date"])

    op.create_table(
        "fleet",
        sa.Column("vehicle_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("terminal_id", sa.Integer(), sa.ForeignKey("terminals.terminal_id"), nullable=False),
        sa.Column("vehicle_type", sa.String(64), nullable=False),
        sa.Column("capacity_weight", sa.Numeric(10, 3), nullable=False),
        sa.Column("capacity_volume", sa.Numeric(10, 3), nullable=False),
        sa.Column("cost_per_km", sa.Numeric(10, 2), nullable=False),
        sa.Column("fixed_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", vehicle_status_enum, nullable=False, server_default="available"),
        *_timestamp_columns(),
    )
    op.create_index("ix_fleet_terminal_status", "fleet", ["terminal_id", "status"])

    op.create_table(
        "shipments",
        sa.Column("shipment_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("terminal_id", sa.Integer(), sa.ForeignKey("terminals.terminal_id"), nullable=False),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.store_id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.product_id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("shipment_date", sa.Date(), nullable=False),
        sa.Column("status", shipment_status_enum, nullable=False, server_default="planned"),
        *_timestamp_columns(),
        sa.CheckConstraint("quantity > 0", name="ck_shipment_quantity_positive"),
    )
    op.create_index("ix_shipments_terminal_store", "shipments", ["terminal_id", "store_id"])
    op.create_index("ix_shipments_status_date", "shipments", ["status", "shipment_date"])
    op.create_index("ix_shipments_product", "shipments", ["product_id"])

    op.create_table(
        "distance_matrix",
        sa.Column("terminal_id", sa.Integer(), sa.ForeignKey("terminals.terminal_id"), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.store_id"), primary_key=True),
        sa.Column("distance_km", sa.Numeric(10, 3), nullable=False),
        sa.Column("travel_time", sa.Numeric(10, 3), nullable=False),
        sa.CheckConstraint("distance_km >= 0", name="ck_distance_non_negative"),
        sa.CheckConstraint("travel_time >= 0", name="ck_travel_time_non_negative"),
    )
    op.create_index("ix_distance_matrix_store", "distance_matrix", ["store_id"])


def downgrade() -> None:
    op.drop_table("distance_matrix")
    op.drop_table("shipments")
    op.drop_table("fleet")
    op.drop_table("demand_history")
    op.drop_table("inventory")
    op.drop_table("products")
    op.drop_table("terminals")
    op.drop_table("stores")

    bind = op.get_bind()
    shipment_status_enum.drop(bind, checkfirst=True)
    vehicle_status_enum.drop(bind, checkfirst=True)
    location_type_enum.drop(bind, checkfirst=True)
