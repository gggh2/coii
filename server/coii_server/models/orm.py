"""SQLAlchemy ORM models."""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Integer, String, Text, DateTime, Boolean, Numeric,
    ForeignKey, JSON, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from coii_server.db.database import Base


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    variants: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    outcome_events: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    attribution_window_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=168)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    exposures: Mapped[list["Exposure"]] = relationship("Exposure", back_populates="experiment")


class Exposure(Base):
    __tablename__ = "exposures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    experiment_id: Mapped[int] = mapped_column(Integer, ForeignKey("experiments.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    variant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    exposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    experiment: Mapped["Experiment"] = relationship("Experiment", back_populates="exposures")


class Trace(Base):
    __tablename__ = "traces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    session_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    spans: Mapped[list["Span"]] = relationship("Span", back_populates="trace")


class Span(Base):
    __tablename__ = "spans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    trace_id: Mapped[int] = mapped_column(Integer, ForeignKey("traces.id"), nullable=False)
    parent_span_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("spans.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 6), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trace: Mapped["Trace"] = relationship("Trace", back_populates="spans")


class Outcome(Base):
    __tablename__ = "outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_name: Mapped[str] = mapped_column(String(255), nullable=False)
    properties: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelPricing(Base):
    __tablename__ = "model_pricing"

    pricing_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    input_cost_per_mtok: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    output_cost_per_mtok: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="builtin")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
