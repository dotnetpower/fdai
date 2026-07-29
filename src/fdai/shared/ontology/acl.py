"""Ontology property-level ACL projection.

Applies :attr:`~fdai.shared.contracts.models.PropertyDecl.access_scope`
and :attr:`~fdai.shared.contracts.models.PropertyDecl.purpose_binding`
declared on an :class:`~fdai.shared.contracts.models.OntologyObjectType`
to an instance's property bag. Redacted values are replaced by a
sentinel so the audit trail can note "field X was redacted for caller
Y with purpose set Z" without leaking the real value.

Why it lives in ``shared/``
--------------------------
Every projection surface - the read-API panels, the assurance twin
answer renderer, exported JSON reports, chat responses - MUST apply
the same redaction so a caller cannot bypass the ACL by choosing a
different surface. Keeping the function in ``shared/`` lets ``core/``
(assurance twin, control loop) and ``delivery/`` (read-API) both call
it without either side depending on the other.

Design invariants
-----------------
- **Fail-closed**: an unknown property (not declared on the
  ObjectType) is redacted, never passed through raw. A projection
  MUST NOT expose a property the ontology has not declared.
- **Two independent gates**: access_scope (role rank) AND
  purpose_binding (purpose set intersection). BOTH must pass for the
  value to appear; either failure redacts. The reason string in the
  redacted result records which gate failed so an audit reviewer can
  reconstruct why.
- **No value-based leaks**: the sentinel MUST NOT include the
  underlying value even in an error path (no
  ``f"redacted: value was {v}"`` shortcuts).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from fdai.shared.contracts.models import (
    CEILING_ROLE_RANK,
    CeilingRole,
    OntologyObjectType,
)
from fdai.shared.ontology.audit import ProjectionAuditEvent, RedactedFieldRecord
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)


class RedactionReason(StrEnum):
    """Why a property was redacted."""

    ACCESS_SCOPE = "access_scope"
    """Caller's role is below the property's declared ``access_scope``."""

    PURPOSE_BINDING = "purpose_binding"
    """Property declares purposes and the caller did not name a matching one."""

    UNDECLARED_PROPERTY = "undeclared_property"
    """Property not present in the ObjectType declaration; fail-closed."""


@dataclass(frozen=True, slots=True)
class RedactedField:
    """Sentinel placed in the projected mapping in place of a redacted value.

    ``reason`` records which gate failed. ``required_role`` and
    ``required_purposes`` are informational and MAY be surfaced to
    the caller so they know what would unlock the field; they carry
    no data about the underlying value.
    """

    reason: RedactionReason
    required_role: CeilingRole | None = None
    required_purposes: tuple[str, ...] = ()


REDACTED_PLACEHOLDER = "[redacted]"
"""Public-facing placeholder emitted in serialised payloads.

The :class:`RedactedField` sentinel is the machine-readable form; when
a projection ships JSON to a browser, replace the sentinel with this
string plus a sibling ``__redactions__`` object if the client needs
the reasons. Never ship the underlying value alongside a placeholder.
"""


@dataclass(frozen=True, slots=True)
class ProjectionRequest:
    """Caller identity + declared purposes for one projection call.

    Kept immutable so a projection cannot silently escalate midway
    through a batch by mutating the request.
    """

    caller_role: CeilingRole
    declared_purposes: frozenset[str] = frozenset()


class OntologyProjectionError(ValueError):
    """A graph cannot be projected without a complete ObjectType registry."""


def redact_properties(
    object_type: OntologyObjectType,
    instance_props: Mapping[str, Any],
    request: ProjectionRequest,
) -> dict[str, Any]:
    """Return ``instance_props`` with per-property ACL applied.

    - Undeclared properties are replaced by a
      :class:`RedactedField` with reason
      :attr:`RedactionReason.UNDECLARED_PROPERTY`.
    - Properties whose ``access_scope`` outranks the caller's role are
      replaced with reason :attr:`RedactionReason.ACCESS_SCOPE`.
    - Properties with a non-empty ``purpose_binding`` whose set does
      not intersect ``request.declared_purposes`` are replaced with
      reason :attr:`RedactionReason.PURPOSE_BINDING`.
    """
    result: dict[str, Any] = {}
    caller_rank = CEILING_ROLE_RANK[request.caller_role]

    for key, value in instance_props.items():
        decl = object_type.properties.get(key)
        if decl is None:
            result[key] = RedactedField(reason=RedactionReason.UNDECLARED_PROPERTY)
            continue
        required_role = decl.access_scope
        if CEILING_ROLE_RANK[required_role] > caller_rank:
            result[key] = RedactedField(
                reason=RedactionReason.ACCESS_SCOPE,
                required_role=required_role,
            )
            continue
        if decl.purpose_binding:
            allowed = frozenset(decl.purpose_binding)
            if not (allowed & request.declared_purposes):
                result[key] = RedactedField(
                    reason=RedactionReason.PURPOSE_BINDING,
                    required_purposes=tuple(sorted(allowed)),
                )
                continue
        result[key] = value

    return result


def serialize_projection(
    projected: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Split a projected mapping into (client-safe values, redaction map).

    The first return is a JSON-serialisable dict where every
    :class:`RedactedField` has been replaced by :data:`REDACTED_PLACEHOLDER`.
    The second return is a ``{property_name: {reason, required_role,
    required_purposes}}`` map suitable for a UI to render "unlock this
    field by X" hints. Neither carries the underlying value.
    """
    values: dict[str, Any] = {}
    redactions: dict[str, dict[str, Any]] = {}
    for key, value in projected.items():
        if isinstance(value, RedactedField):
            values[key] = REDACTED_PLACEHOLDER
            redactions[key] = {
                "reason": value.reason.value,
                "required_role": (
                    value.required_role.value if value.required_role is not None else None
                ),
                "required_purposes": list(value.required_purposes),
            }
        else:
            values[key] = value
    return values, redactions


def project_graph_snapshot(
    snapshot: OntologyGraphSnapshot,
    *,
    object_types: Mapping[str, OntologyObjectType],
    request: ProjectionRequest,
) -> OntologyGraphSnapshot:
    """Apply ObjectType property ACLs to every object in a graph snapshot."""

    projected_objects: list[OntologyObjectRecord] = []
    projected_ids: dict[str, str] = {}
    for index, record in enumerate(snapshot.objects, start=1):
        declaration = object_types.get(record.object_type)
        if declaration is None:
            raise OntologyProjectionError(
                f"missing ObjectType declaration for projection: {record.object_type!r}"
            )
        projected = redact_properties(declaration, record.properties, request)
        values, redactions = serialize_projection(projected)
        if redactions:
            values["__redactions__"] = redactions
        projected_id = (
            f"redacted-object-{index}"
            if values.get(declaration.key) == REDACTED_PLACEHOLDER
            else record.id
        )
        projected_ids[record.id] = projected_id
        projected_objects.append(
            OntologyObjectRecord(
                id=projected_id,
                object_type=record.object_type,
                properties=values,
                revision=record.revision,
            )
        )
    return OntologyGraphSnapshot(
        objects=tuple(projected_objects),
        links=tuple(
            OntologyLinkRecord(
                link_type=link.link_type,
                from_id=projected_ids[link.from_id],
                to_id=projected_ids[link.to_id],
                properties=link.properties,
            )
            for link in snapshot.links
            if link.from_id in projected_ids and link.to_id in projected_ids
        ),
        truncated=snapshot.truncated,
    )


def declared_purposes_from_iterable(purposes: Iterable[str]) -> frozenset[str]:
    """Normalize an incoming purpose list (from HTTP query or CLI) to a frozenset.

    Empty strings and duplicates are dropped; whitespace is stripped.
    A caller MUST NOT pass ``None`` values in; the type says ``str``.
    """
    return frozenset({p.strip() for p in purposes if p and p.strip()})


def redactions_for_audit(projected: Mapping[str, Any]) -> tuple[RedactedFieldRecord, ...]:
    """Extract audit-shaped :class:`RedactedFieldRecord` entries from a projection.

    Returns an empty tuple when nothing was redacted so the caller can
    branch cheaply on "did the ACL fire".
    """
    records: list[RedactedFieldRecord] = []
    for key, value in projected.items():
        if isinstance(value, RedactedField):
            records.append(
                RedactedFieldRecord(
                    property=key,
                    reason=value.reason.value,
                    required_role=(
                        value.required_role.value if value.required_role is not None else None
                    ),
                    required_purposes=value.required_purposes,
                )
            )
    return tuple(records)


def build_projection_audit_event(
    *,
    audit_id: str,
    request: ProjectionRequest,
    caller_id: str,
    surface: str,
    object_type: str,
    projected: Mapping[str, Any],
    instance_key: str | None = None,
    correlation_id: str | None = None,
) -> ProjectionAuditEvent:
    """Convenience: pair :func:`redact_properties` output with an audit event."""
    return ProjectionAuditEvent.make(
        audit_id=audit_id,
        caller_id=caller_id,
        caller_role=request.caller_role,
        declared_purposes=request.declared_purposes,
        surface=surface,
        object_type=object_type,
        instance_key=instance_key,
        redactions=redactions_for_audit(projected),
        correlation_id=correlation_id,
    )


__all__ = [
    "REDACTED_PLACEHOLDER",
    "ProjectionRequest",
    "OntologyProjectionError",
    "RedactedField",
    "RedactionReason",
    "build_projection_audit_event",
    "declared_purposes_from_iterable",
    "project_graph_snapshot",
    "redact_properties",
    "redactions_for_audit",
    "serialize_projection",
]
