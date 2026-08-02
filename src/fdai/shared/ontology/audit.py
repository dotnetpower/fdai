"""Projection audit event - one record per read that touched gated properties.

Every projection surface (Operator API panel, assurance twin, exported
report) that applies :mod:`fdai.shared.ontology.acl` MUST emit one
:class:`ProjectionAuditEvent` per query. The event captures WHO read
WHAT under WHICH purpose so an auditor can reconstruct the read.

The event dataclass lives in ``shared/`` so ``core/`` and
``delivery/`` both emit the same shape; the store binding is the
same :class:`~fdai.shared.providers.state_store.StateStore` used by
the action audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from fdai.shared.contracts.models import CeilingRole


@dataclass(frozen=True, slots=True)
class RedactedFieldRecord:
    """Audit record of one property that was redacted during projection.

    Carries only the metadata gate (reason + required role / purposes),
    never the underlying value.
    """

    property: str
    reason: str
    required_role: str | None = None
    required_purposes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectionAuditEvent:
    """One append-only audit row per read that touched the ACL layer."""

    audit_id: str
    """Idempotent event id; retry MUST reuse the same id."""

    observed_at: datetime
    """RFC 3339 UTC timestamp when the projection ran."""

    caller_id: str
    """Stable caller identifier (Entra object id, service principal id, ...)."""

    caller_role: CeilingRole
    """Effective role at the moment of projection."""

    declared_purposes: tuple[str, ...]
    """Purposes the caller declared (sorted for stable comparison)."""

    surface: str
    """Which projection surface fired the read (`operator-api:/panels/...`, `twin:query`, ...)."""

    object_type: str
    """PascalCase ObjectType `name` the projection targeted."""

    instance_key: str | None = None
    """Optional instance key (`Resource.id`, `Finding.id`); ``None`` for list projections."""

    redactions: tuple[RedactedFieldRecord, ...] = field(default_factory=tuple)
    """Per-property redaction records; empty tuple means the read was fully unlocked."""

    correlation_id: str | None = None
    """Optional upstream correlation id (HTTP request id, chat session id)."""

    @classmethod
    def make(
        cls,
        *,
        audit_id: str,
        caller_id: str,
        caller_role: CeilingRole,
        declared_purposes: frozenset[str],
        surface: str,
        object_type: str,
        instance_key: str | None = None,
        redactions: tuple[RedactedFieldRecord, ...] = (),
        correlation_id: str | None = None,
    ) -> ProjectionAuditEvent:
        return cls(
            audit_id=audit_id,
            observed_at=datetime.now(tz=UTC),
            caller_id=caller_id,
            caller_role=caller_role,
            declared_purposes=tuple(sorted(declared_purposes)),
            surface=surface,
            object_type=object_type,
            instance_key=instance_key,
            redactions=redactions,
            correlation_id=correlation_id,
        )


__all__ = [
    "ProjectionAuditEvent",
    "RedactedFieldRecord",
]
