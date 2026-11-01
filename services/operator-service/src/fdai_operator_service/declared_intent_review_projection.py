"""Protected exact-diff review projection for declared-intent document graph proposals.

Enforces explicit reviewer role (`Approver` or `Owner`), independence from the
uploader and requester, explicit scope authorization, and current source ACL
membership (which `Owner` never bypasses). General-topic summaries remain
strictly content-free and never disclose private `BusinessService` properties or
source document coordinates. Every projection sets ``read_only=True`` and
``authority="none"``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from fdai_service_contracts.document_intent import (
    DocumentIntentDiff,
    DocumentIntentEvent,
    IntentServiceProperties,
)

_REVIEW_ROLES: Final = frozenset({"approver", "owner"})
_FORBIDDEN_GENERAL_TOPIC_KEYS: Final = frozenset(
    {
        "properties",
        "before_properties",
        "after_properties",
        "property_changes",
        "name",
        "criticality",
        "effective_from",
        "effective_to",
        "source_ref",
        "document_id",
        "version_id",
        "document_bytes",
        "raw_text",
    }
)


class DeclaredIntentReviewAccessError(PermissionError, ValueError):
    """Raised when reviewer role, independence, scope, or source ACL checks fail."""

    def __init__(self, code: str, message: str, *, status_code: int = 403) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class DeclaredIntentReviewerContext:
    """Authenticated reviewer context for protected exact-diff inspection."""

    principal_id: str
    roles: frozenset[str]
    allowed_scopes: frozenset[str]
    group_ids: frozenset[str]
    current_as_of: datetime | None = None

    def __post_init__(self) -> None:
        if self.current_as_of is not None and (
            self.current_as_of.tzinfo is None or self.current_as_of.utcoffset() is None
        ):
            raise ValueError("reviewer.current_as_of MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class DeclaredIntentSourceAccessMetadata:
    """Current governed source metadata required before disclosing any diff property."""

    document_id: str
    version_id: str
    revision: int
    uploader_id: str
    reader_groups: frozenset[str]
    active: bool = True
    available: bool = True
    state: str = "ready"
    disposition: str = "governed_knowledge"
    index_state: str = "active"
    retention_state: str = "live"
    protection_state: str = "none"
    purposes: frozenset[str] = frozenset({"manual_distillation"})

    def __post_init__(self) -> None:
        if not isinstance(self.document_id, str) or not self.document_id.strip():
            raise DeclaredIntentReviewAccessError(
                "invalid_source_metadata",
                "source.document_id MUST be a non-empty string",
                status_code=400,
            )
        if not isinstance(self.version_id, str) or not self.version_id.strip():
            raise DeclaredIntentReviewAccessError(
                "invalid_source_metadata",
                "source.version_id MUST be a non-empty string",
                status_code=400,
            )
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 1
        ):
            raise DeclaredIntentReviewAccessError(
                "invalid_source_revision",
                "source.revision MUST be a positive integer >= 1",
                status_code=400,
            )


@dataclass(frozen=True, slots=True)
class DeclaredIntentPropertyChange:
    """Exact before/after scalar property comparison for one BusinessService field."""

    field_name: str
    before_value: str | None
    after_value: str | None
    changed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "field_name": self.field_name,
            "before_value": self.before_value,
            "after_value": self.after_value,
            "changed": self.changed,
        }


def build_declared_intent_review_projection(
    *,
    diff: DocumentIntentDiff,
    source: DeclaredIntentSourceAccessMetadata,
    reviewer: DeclaredIntentReviewerContext | None,
    prior_properties: IntentServiceProperties | None = None,
) -> dict[str, object]:
    """Build the protected exact-diff review projection for an authorized independent reviewer."""
    if reviewer is None or not reviewer.principal_id.strip():
        raise DeclaredIntentReviewAccessError(
            "unauthenticated",
            "authenticated reviewer principal is required",
            status_code=401,
        )
    if reviewer.current_as_of is not None and (
        reviewer.current_as_of.tzinfo is None or reviewer.current_as_of.utcoffset() is None
    ):
        raise ValueError("reviewer.current_as_of MUST be timezone-aware")
    reviewer_id = reviewer.principal_id.strip()
    normalized_roles = {role.strip().lower() for role in reviewer.roles if role.strip()}
    if not (normalized_roles & _REVIEW_ROLES):
        raise DeclaredIntentReviewAccessError(
            "missing_review_role",
            "declared-intent diff review requires Approver or Owner role",
            status_code=403,
        )
    if reviewer_id == diff.requester_ref or reviewer_id == source.uploader_id:
        raise DeclaredIntentReviewAccessError(
            "non_independent_reviewer",
            "requester and source uploader MUST NOT review or approve their own declared intent",
            status_code=403,
        )
    if diff.scope_ref not in reviewer.allowed_scopes:
        raise DeclaredIntentReviewAccessError(
            "scope_denied",
            f"reviewer lacks explicit scope authorization for {diff.scope_ref}",
            status_code=403,
        )
    _verify_current_source_posture(diff=diff, source=source)

    # Owner never bypasses source ACL on private declared-intent documents.
    if not (reviewer.group_ids & source.reader_groups):
        raise DeclaredIntentReviewAccessError(
            "source_acl_denied",
            "reviewer lacks current source ACL group access; Owner role cannot bypass source ACL",
            status_code=403,
        )

    if diff.operation == "add" and prior_properties is not None:
        raise ValueError("add operation MUST NOT supply prior_properties")
    if diff.operation == "update" and prior_properties is not None:
        if prior_properties.id != diff.properties.id:
            raise ValueError("prior_properties.id MUST match diff.properties.id")

    before_map = _serialize_properties(prior_properties) if prior_properties is not None else None
    after_map = _serialize_properties(diff.properties)
    changes = _compute_property_changes(before_map=before_map, after_map=after_map)
    changed_field_count = sum(1 for change in changes if change.changed)
    intent_digest = diff.digest

    projection: dict[str, object] = {
        "type": "declared-intent.review-projection",
        "schema_version": "1.0.0",
        "read_only": True,
        "authority": "none",
        "execution_authority": False,
        "protected_surface": True,
        "general_topic_safe": False,
        "action_type": "document.review-intent-diff",
        "intent_digest": intent_digest,
        "resource_id": f"document-intent:{intent_digest[7:]}",
        "object_type": diff.object_type,
        "operation": diff.operation,
        "expected_revision": diff.expected_revision,
        "scope_ref": diff.scope_ref,
        "requester_ref": diff.requester_ref,
        "reviewer_id": reviewer_id,
        "independent_reviewer": True,
        "source_revision": diff.source_revision,
        "source_digest": diff.source_digest,
        "envelope_digest": diff.envelope_digest,
        "acl_digest": diff.acl_digest,
        "ontology_release": diff.ontology_release,
        "before_properties": before_map,
        "after_properties": after_map,
        "property_changes": [change.to_dict() for change in changes],
        "changed_field_count": changed_field_count,
    }
    canonical = json.dumps(projection, sort_keys=True, separators=(",", ":"))
    projection["review_projection_digest"] = (
        f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
    )
    return projection


def build_declared_intent_general_topic_summary(
    *,
    event: DocumentIntentEvent,
    extra_fields: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """Build a content-free general-topic summary that never discloses source properties."""
    if extra_fields is not None:
        leaked = _FORBIDDEN_GENERAL_TOPIC_KEYS & set(extra_fields.keys())
        if leaked:
            raise ValueError(
                f"general topic summary MUST NOT disclose source property fields: {sorted(leaked)}"
            )
    payload: dict[str, object] = {
        "type": "declared-intent.general-topic-summary",
        "schema_version": "1.0.0",
        "read_only": True,
        "authority": "none",
        "execution_authority": False,
        "protected_surface": False,
        "general_topic_safe": True,
        "discloses_source_properties": False,
        "intent_digest": event.intent_digest,
        "resource_id": event.resource_id,
        "correlation_id": event.correlation_id,
        "phase": event.phase,
        "producer_principal": event.producer_principal,
        "outcome": event.outcome,
        "applied_revision": event.applied_revision,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["summary_digest"] = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
    _assert_no_source_properties_disclosed(payload)
    return payload


def _verify_current_source_posture(
    *,
    diff: DocumentIntentDiff,
    source: DeclaredIntentSourceAccessMetadata,
) -> None:
    if (
        str(diff.document_id) != source.document_id
        or str(diff.version_id) != source.version_id
        or diff.source_revision != source.revision
    ):
        raise DeclaredIntentReviewAccessError(
            "source_revision_mismatch",
            "source document identity or revision no longer matches the proposed diff",
            status_code=409,
        )
    if (
        not source.active
        or not source.available
        or source.state not in {"ready", "ready_with_warnings"}
        or source.disposition != "governed_knowledge"
        or source.index_state != "active"
        or source.retention_state != "live"
        or source.protection_state != "none"
        or "manual_distillation" not in source.purposes
    ):
        raise DeclaredIntentReviewAccessError(
            "source_not_admissible",
            "declared-intent source is no longer current, active, unprotected governed knowledge",
            status_code=403,
        )


def _serialize_properties(props: IntentServiceProperties) -> dict[str, str | None]:
    return {
        "id": props.id,
        "name": props.name,
        "criticality": props.criticality,
        "effective_from": props.effective_from.astimezone(UTC).isoformat(),
        "effective_to": (
            props.effective_to.astimezone(UTC).isoformat()
            if props.effective_to is not None
            else None
        ),
        "source_ref": props.source_ref,
    }


def _compute_property_changes(
    *,
    before_map: Mapping[str, str | None] | None,
    after_map: Mapping[str, str | None],
) -> tuple[DeclaredIntentPropertyChange, ...]:
    ordered_fields = (
        "id",
        "name",
        "criticality",
        "effective_from",
        "effective_to",
        "source_ref",
    )
    items: list[DeclaredIntentPropertyChange] = []
    for field_name in ordered_fields:
        before_val = before_map.get(field_name) if before_map is not None else None
        after_val = after_map.get(field_name)
        items.append(
            DeclaredIntentPropertyChange(
                field_name=field_name,
                before_value=before_val,
                after_value=after_val,
                changed=(before_map is None) or (before_val != after_val),
            )
        )
    return tuple(items)


def _assert_no_source_properties_disclosed(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in _FORBIDDEN_GENERAL_TOPIC_KEYS:
                raise ValueError(f"general topic payload leaked forbidden property key {key}")
            _assert_no_source_properties_disclosed(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            _assert_no_source_properties_disclosed(item)


__all__ = [
    "DeclaredIntentPropertyChange",
    "DeclaredIntentReviewAccessError",
    "DeclaredIntentReviewerContext",
    "DeclaredIntentSourceAccessMetadata",
    "build_declared_intent_general_topic_summary",
    "build_declared_intent_review_projection",
]
