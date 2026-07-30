"""SQLAlchemy ORM models for every core table in the supply chain platform.

Table shapes follow the project spec exactly. Indexes are chosen for the
target scale (1,000+ stores, 10,000+ terminals, millions of inventory rows,
hundreds of thousands of products): every foreign key and every column used
as a lookup/filter key in later agents (store_id, product_id, date, location)
is indexed.
"""

import enum
from datetime import date as date_, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class LocationType(str, enum.Enum):
    STORE = "store"
    TERMINAL = "terminal"


class VehicleStatus(str, enum.Enum):
    AVAILABLE = "available"
    IN_TRANSIT = "in_transit"
    MAINTENANCE = "maintenance"
    OUT_OF_SERVICE = "out_of_service"


class ShipmentStatus(str, enum.Enum):
    PLANNED = "planned"
    CONFIRMED = "confirmed"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    EXCEPTION = "exception"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Store(TimestampMixin, Base):
    __tablename__ = "stores"

    store_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    store_name: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    longitude: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    capacity: Mapped[int] = mapped_column(nullable=False)
    priority: Mapped[int] = mapped_column(nullable=False, default=3)

    __table_args__ = (
        CheckConstraint("capacity >= 0", name="ck_store_capacity_non_negative"),
        Index("ix_stores_priority", "priority"),
    )


class Terminal(TimestampMixin, Base):
    __tablename__ = "terminals"

    terminal_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    terminal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    longitude: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    capacity: Mapped[int] = mapped_column(nullable=False)

    __table_args__ = (CheckConstraint("capacity >= 0", name="ck_terminal_capacity_non_negative"),)


class Product(TimestampMixin, Base):
    __tablename__ = "products"

    product_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    weight: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    volume: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    cost: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    expiry_days: Mapped[int | None] = mapped_column(nullable=True)

    __table_args__ = (Index("ix_products_category", "category"),)


class Inventory(TimestampMixin, Base):
    __tablename__ = "inventory"

    inventory_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    location_type: Mapped[LocationType] = mapped_column(
        Enum(LocationType, name="location_type_enum"), nullable=False
    )
    location_id: Mapped[int] = mapped_column(nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.product_id"), nullable=False)
    available_qty: Mapped[int] = mapped_column(nullable=False, default=0)
    reserved_qty: Mapped[int] = mapped_column(nullable=False, default=0)
    incoming_qty: Mapped[int] = mapped_column(nullable=False, default=0)
    damaged_qty: Mapped[int] = mapped_column(nullable=False, default=0)

    product: Mapped["Product"] = relationship()

    __table_args__ = (
        CheckConstraint("available_qty >= 0", name="ck_inventory_available_non_negative"),
        CheckConstraint("reserved_qty >= 0", name="ck_inventory_reserved_non_negative"),
        CheckConstraint("incoming_qty >= 0", name="ck_inventory_incoming_non_negative"),
        CheckConstraint("damaged_qty >= 0", name="ck_inventory_damaged_non_negative"),
        UniqueConstraint(
            "location_type", "location_id", "product_id", name="uq_inventory_location_product"
        ),
        Index("ix_inventory_location", "location_type", "location_id"),
        Index("ix_inventory_product", "product_id"),
    )


class DemandHistory(Base):
    __tablename__ = "demand_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    date: Mapped[date_] = mapped_column(nullable=False)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.store_id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.product_id"), nullable=False)
    sales_qty: Mapped[int] = mapped_column(nullable=False, default=0)
    promotion: Mapped[bool] = mapped_column(nullable=False, default=False)
    holiday: Mapped[bool] = mapped_column(nullable=False, default=False)

    store: Mapped["Store"] = relationship()
    product: Mapped["Product"] = relationship()

    __table_args__ = (
        UniqueConstraint("date", "store_id", "product_id", name="uq_demand_history_date_store_product"),
        Index("ix_demand_history_store_product", "store_id", "product_id"),
        Index("ix_demand_history_date", "date"),
    )


class Fleet(TimestampMixin, Base):
    __tablename__ = "fleet"

    vehicle_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    terminal_id: Mapped[int] = mapped_column(ForeignKey("terminals.terminal_id"), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(64), nullable=False)
    capacity_weight: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    capacity_volume: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    cost_per_km: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    fixed_cost: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[VehicleStatus] = mapped_column(
        Enum(VehicleStatus, name="vehicle_status_enum"), nullable=False, default=VehicleStatus.AVAILABLE
    )

    terminal: Mapped["Terminal"] = relationship()

    __table_args__ = (Index("ix_fleet_terminal_status", "terminal_id", "status"),)


class Shipment(TimestampMixin, Base):
    __tablename__ = "shipments"

    shipment_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    terminal_id: Mapped[int] = mapped_column(ForeignKey("terminals.terminal_id"), nullable=False)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.store_id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.product_id"), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    shipment_date: Mapped[date_] = mapped_column(nullable=False)
    status: Mapped[ShipmentStatus] = mapped_column(
        Enum(ShipmentStatus, name="shipment_status_enum"), nullable=False, default=ShipmentStatus.PLANNED
    )

    terminal: Mapped["Terminal"] = relationship()
    store: Mapped["Store"] = relationship()
    product: Mapped["Product"] = relationship()

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_shipment_quantity_positive"),
        Index("ix_shipments_terminal_store", "terminal_id", "store_id"),
        Index("ix_shipments_status_date", "status", "shipment_date"),
        Index("ix_shipments_product", "product_id"),
    )


class DistanceMatrix(Base):
    __tablename__ = "distance_matrix"

    terminal_id: Mapped[int] = mapped_column(ForeignKey("terminals.terminal_id"), primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.store_id"), primary_key=True)
    distance_km: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    travel_time: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)

    terminal: Mapped["Terminal"] = relationship()
    store: Mapped["Store"] = relationship()

    __table_args__ = (
        CheckConstraint("distance_km >= 0", name="ck_distance_non_negative"),
        CheckConstraint("travel_time >= 0", name="ck_travel_time_non_negative"),
        Index("ix_distance_matrix_store", "store_id"),
    )
