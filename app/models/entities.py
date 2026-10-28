"""SQLAlchemy ORM models for every core table in the supply chain platform.

Table shapes follow the project spec exactly. Indexes are chosen for the
target scale (1,000+ stores, 10,000+ terminals, millions of inventory rows,
hundreds of thousands of products): every foreign key and every column used
as a lookup/filter key in later agents (store_id, product_id, date, location)
is indexed.
"""

import enum
from datetime import date as date_
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
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


class PlanningRunStatus(str, enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"


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
    # Populated by the Fleet Assignment Agent (Phase 2) - None if the fleet module
    # is disabled or this line couldn't be assigned a vehicle.
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("fleet.vehicle_id"), nullable=True)
    # Which PlanningRun produced this shipment - written atomically alongside that
    # run's audit row (see app/agents/graph.py::_persist_run).
    planning_run_id: Mapped[int | None] = mapped_column(ForeignKey("planning_runs.id"), nullable=True)

    terminal: Mapped["Terminal"] = relationship()
    store: Mapped["Store"] = relationship()
    product: Mapped["Product"] = relationship()

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_shipment_quantity_positive"),
        Index("ix_shipments_terminal_store", "terminal_id", "store_id"),
        Index("ix_shipments_status_date", "status", "shipment_date"),
        Index("ix_shipments_product", "product_id"),
        Index("ix_shipments_planning_run", "planning_run_id"),
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


class PlanningRun(TimestampMixin, Base):
    """One row per `run_planning_workflow()` invocation - the audit trail for
    every AI-generated plan: which reasoning engine produced it, the full
    input scope, every intermediate LangGraph stage's output, and a
    success/failure status. Written by the persistence hook in
    `app/agents/graph.py`, not by any repository (repositories never commit
    in this codebase - see `BaseRepository`).

    Stage columns are nullable because a *failed* run has no partial data to
    store: `graph.compile()` has no checkpointer configured, so when a node
    raises, the exception propagates straight out of `graph.ainvoke()` with
    no partial state returned - a failed row only ever gets scope/provider/error.
    """

    __tablename__ = "planning_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    planning_date: Mapped[date_] = mapped_column(nullable=False)
    store_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    product_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    demand_history_window_days: Mapped[int] = mapped_column(nullable=False)
    # SHA-256 of a canonical JSON scope (sorted store/product ids + window + date +
    # optimization_objective) - used for exact-match "has this scope already been
    # run?" lookups instead of comparing JSON columns directly (unreliable across
    # dialects - see graph.py).
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # SHA-256 of the actual loaded master-data snapshot (see
    # app/services/fingerprint.py) - lets a cache lookup tell "same scope, but has
    # the underlying data actually changed since last time?" apart from "same
    # scope, same data, safe to reuse the prior result."
    data_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    optimization_objective: Mapped[str] = mapped_column(String(32), nullable=False, default="minimize_cost")

    llm_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(128), nullable=False)

    status: Mapped[PlanningRunStatus] = mapped_column(
        Enum(PlanningRunStatus, name="planning_run_status_enum"), nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    trace: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    errors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    replanning_attempts: Mapped[int] = mapped_column(nullable=False, default=0)

    request_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Populated instead of master_data_snapshot when
    # Settings.persist_full_master_data_snapshot is False (row counts + business
    # rules only, not the full snapshot - see app/agents/graph.py::_persist_run).
    master_data_row_counts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    master_data_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    demand_forecast: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    inventory_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    supply_planning: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    allocation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cost_optimization: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    constraint_validation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Phase 2 (only populated when Settings.fleet_module_enabled is True):
    fleet_assignment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    route_planning: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    eta_prediction: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    decision_review: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    final_recommendation: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_planning_runs_scope_key", "scope_key"),
        Index("ix_planning_runs_created_at", "created_at"),
        # Hot lookup path on every run_planning_workflow() call (unlike the plain
        # scope_key index above, which only serves occasional history browsing).
        Index(
            "ix_planning_runs_cache_lookup", "scope_key", "data_fingerprint", "llm_provider", "llm_model"
        ),
    )


class PlanApproval(TimestampMixin, Base):
    __tablename__ = "plan_approvals"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    planning_run_id: Mapped[int] = mapped_column(ForeignKey("planning_runs.id"), unique=True, nullable=False)
    strategy: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    reviewer: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(Text)


class ReplanningEvent(TimestampMixin, Base):
    __tablename__ = "replanning_events"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    magnitude: Mapped[float] = mapped_column(Numeric(12, 5), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    planning_request: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    planning_run_id: Mapped[int | None] = mapped_column(ForeignKey("planning_runs.id"), nullable=True)


class ShipmentCreationClaim(TimestampMixin, Base):
    __tablename__ = "shipment_creation_claims"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    planning_run_id: Mapped[int] = mapped_column(ForeignKey("planning_runs.id"), unique=True, nullable=False)


class PlanningOutcome(TimestampMixin, Base):
    """Observed execution outcome; unique external reference prevents duplicate ingestion."""
    __tablename__ = "planning_outcomes"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    external_reference: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    planning_run_id: Mapped[int] = mapped_column(ForeignKey("planning_runs.id"), nullable=False)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.store_id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.product_id"), nullable=False)
    observation_date: Mapped[date_] = mapped_column(nullable=False)
    actual_demand_qty: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    fulfilled_qty: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    actual_cost: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    __table_args__ = (
        CheckConstraint("actual_demand_qty >= 0 AND fulfilled_qty >= 0 AND actual_cost >= 0",
                        name="ck_planning_outcomes_nonnegative"),
        Index("ix_planning_outcomes_run_date", "planning_run_id", "observation_date"),
    )
