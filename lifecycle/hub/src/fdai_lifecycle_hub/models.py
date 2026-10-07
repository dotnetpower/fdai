"""SQLAlchemy ORM models for the Hub data model.

Lifecycle I0 creates the schema with `metadata.create_all`. Versioned Alembic migrations
replace it in Lifecycle I1, before any Hub database holds data worth keeping.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, WriteOnlyMapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from fdai_lifecycle_hub.domain import OutcomeKind

Digest = String(71)
Identifier = String(160)


class UtcDateTime(TypeDecorator[datetime]):
    """Store aware datetimes as UTC and always read them back as aware UTC values."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Hub timestamps must be timezone-aware")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class PlanEventKind(enum.StrEnum):
    ISSUED = "issued"
    SUPERSEDED = "superseded"
    REPORTED = "reported"


class Base(DeclarativeBase):
    type_annotation_map = {
        datetime: UtcDateTime,
        dict[str, Any]: JSON().with_variant(JSONB(), "postgresql"),
        list[Any]: JSON().with_variant(JSONB(), "postgresql"),
        # Persist enum values ("issued"), not member names ("ISSUED").
        enum.Enum: Enum(
            enum.Enum, native_enum=False, values_callable=lambda e: [m.value for m in e]
        ),
    }


class ConfigurationRevision(Base):
    """A configuration package revision, addressed by its digest. Never updated."""

    __tablename__ = "lifecycle_configuration_revision"

    digest: Mapped[str] = mapped_column(Digest, primary_key=True)
    body: Mapped[dict[str, Any]]
    imported_at: Mapped[datetime]


class Installation(Base):
    __tablename__ = "lifecycle_installation"

    installation_id: Mapped[str] = mapped_column(Identifier, primary_key=True)
    settings: Mapped[dict[str, Any]]
    suppressions: Mapped[list[Any]]
    configuration_digest: Mapped[str] = mapped_column(ForeignKey(ConfigurationRevision.digest))
    last_sequence: Mapped[int] = mapped_column(default=0)
    enrolled_at: Mapped[datetime]
    recorded_at: Mapped[datetime]

    # An inner join keeps `SELECT ... FOR UPDATE` valid on PostgreSQL.
    configuration: Mapped[ConfigurationRevision] = relationship(lazy="joined", innerjoin=True)
    entities: Mapped[list[Entity]] = relationship(lazy="selectin")
    state_reports: WriteOnlyMapped[StateReport] = relationship()
    evaluations: WriteOnlyMapped[PlanEvaluation] = relationship()
    plans: WriteOnlyMapped[Plan] = relationship()


class Entity(Base):
    __tablename__ = "lifecycle_entity"

    installation_id: Mapped[str] = mapped_column(
        ForeignKey(Installation.installation_id), primary_key=True
    )
    entity_id: Mapped[str] = mapped_column(Identifier, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))
    managed: Mapped[bool]
    recorded_at: Mapped[datetime]


class StateReport(Base):
    """One lifecycle-state snapshot. The newest by `observed_at` is current."""

    __tablename__ = "lifecycle_state_report"

    id: Mapped[int] = mapped_column(primary_key=True)
    installation_id: Mapped[str] = mapped_column(
        ForeignKey(Installation.installation_id), index=True
    )
    digest: Mapped[str] = mapped_column(Digest)
    schema_revision: Mapped[int]
    observed_at: Mapped[datetime]
    recorded_at: Mapped[datetime]

    entity_states: Mapped[list[EntityReportedState]] = relationship(lazy="selectin")


class EntityReportedState(Base):
    __tablename__ = "lifecycle_entity_reported_state"
    __table_args__ = (
        ForeignKeyConstraint(
            ["installation_id", "entity_id"],
            [Entity.installation_id, Entity.entity_id],
        ),
    )

    report_id: Mapped[int] = mapped_column(ForeignKey(StateReport.id), primary_key=True)
    installation_id: Mapped[str] = mapped_column(Identifier)
    entity_id: Mapped[str] = mapped_column(Identifier, primary_key=True)
    release_id: Mapped[str] = mapped_column(String(64))
    artifact_digests: Mapped[list[Any]]
    health: Mapped[str] = mapped_column(String(32))


class PlanEvaluation(Base):
    """Why one recompute produced its outcome."""

    __tablename__ = "lifecycle_plan_evaluation"

    id: Mapped[int] = mapped_column(primary_key=True)
    installation_id: Mapped[str] = mapped_column(
        ForeignKey(Installation.installation_id), index=True
    )
    outcome: Mapped[OutcomeKind]
    target_release_id: Mapped[str | None] = mapped_column(String(64))
    plan_id: Mapped[str | None] = mapped_column(Identifier)
    evaluated_at: Mapped[datetime]

    results: Mapped[list[PlanConstraintResult]] = relationship()


class PlanConstraintResult(Base):
    """One blocking constraint, or a candidate that passed every constraint (no reason)."""

    __tablename__ = "lifecycle_plan_constraint_result"

    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_id: Mapped[int] = mapped_column(ForeignKey(PlanEvaluation.id), index=True)
    release_id: Mapped[str] = mapped_column(String(64))
    reason_code: Mapped[str | None] = mapped_column(String(96))
    details: Mapped[list[Any]]


class Plan(Base):
    """A signed Plan. Status changes live in `PlanEvent`."""

    __tablename__ = "lifecycle_plan"
    __table_args__ = (UniqueConstraint("installation_id", "sequence"),)

    plan_id: Mapped[str] = mapped_column(Identifier, primary_key=True)
    installation_id: Mapped[str] = mapped_column(ForeignKey(Installation.installation_id))
    sequence: Mapped[int]
    target_release_id: Mapped[str] = mapped_column(String(64))
    source_state_digest: Mapped[str] = mapped_column(Digest)
    configuration_digest: Mapped[str] = mapped_column(Digest)
    hub_key_id: Mapped[str] = mapped_column(String(64))
    entity_ids: Mapped[list[Any]]
    signed_payload: Mapped[bytes] = mapped_column(LargeBinary)
    signature: Mapped[bytes] = mapped_column(LargeBinary)
    issued_at: Mapped[datetime]
    expires_at: Mapped[datetime]

    events: WriteOnlyMapped[PlanEvent] = relationship()
    reports: WriteOnlyMapped[PlanReport] = relationship()


class PlanEvent(Base):
    __tablename__ = "lifecycle_plan_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey(Plan.plan_id), index=True)
    kind: Mapped[PlanEventKind]
    recorded_at: Mapped[datetime]


class PlanReport(Base):
    """One execution report for one Plan attempt. Never updated."""

    __tablename__ = "lifecycle_plan_execution_report"
    __table_args__ = (UniqueConstraint("plan_id", "attempt"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey(Plan.plan_id))
    attempt: Mapped[int]
    outcome: Mapped[str] = mapped_column(String(32))
    reason_code: Mapped[str] = mapped_column(String(96))
    exact_plan_digest: Mapped[str | None] = mapped_column(Digest)
    summary: Mapped[str] = mapped_column(String(2000))
    reported_at: Mapped[datetime]
    received_at: Mapped[datetime]


class AuditRecord(Base):
    """Hash-chained record of every Hub change. The sequence primary key forbids forks."""

    __tablename__ = "lifecycle_hub_audit"

    sequence: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    recorded_at: Mapped[datetime]
    action: Mapped[str] = mapped_column(String(64))
    installation_id: Mapped[str] = mapped_column(Identifier)
    subject: Mapped[str] = mapped_column(Identifier)
    payload: Mapped[dict[str, Any]]
    previous_hash: Mapped[str] = mapped_column(String(64))
    record_hash: Mapped[str] = mapped_column(String(64), unique=True)
