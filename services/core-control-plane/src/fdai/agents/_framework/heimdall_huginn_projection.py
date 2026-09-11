"""Typed Heimdall records projected from Huginn-normalized `object.event`.

Huginn is the sole ingress for external signals: it normalizes a raw source
signal into an `Event` payload whose free-form fields live under a bounded
``attributes`` map. Heimdall is the observer that turns such a normalized
signal into a Heimdall-owned typed record on a Heimdall-owned topic.

Every projection here is pure and total: it either returns the bounded record
or ``None``. Each one first proves the event really came from Huginn, because
only the bus-stamped ``producer_principal`` says who produced a record - a
payload can never nominate its own producer. A projection copies only declared
fields, so an external signal cannot smuggle an extra key onto an owned topic,
and it grants no judgement, verification, or execution authority: the durable
intake downstream re-validates everything it receives.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.ontology_platform.evidence_conflict import (
    EvidenceConflictRevision,
    EvidenceConflictStatus,
    EvidenceSourceLineage,
)
from fdai.core.workflow.recovery_effect_ingress import (
    RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE,
)

#: Observation fields Heimdall relays from a Huginn-normalized signal onto the
#: Heimdall-owned observation topic. The list is an allowlist, not a filter of
#: known-bad keys, and it deliberately excludes every envelope field the bus
#: stamps (`producer_principal`, `schema_version`) so a forged attribute can
#: never displace an authenticated one.
_RECOVERY_EFFECT_OBSERVATION_FIELDS = (
    "observation_schema_version",
    "process_id",
    "recovery_step_id",
    "attempt_identity_digest",
    "target_resource_id",
    "provider_receipt_digest",
    "observer_identity",
    "observer_authority_class",
    "provider_identity",
    "purpose_version",
    "method_version",
    "event_time",
    "recorded_time",
    "freshness_policy_seconds",
    "completeness",
    "provenance",
    "conflict_status",
    "synthetic",
    "evidence_digest",
    "expected_effect_digest",
    "approved_envelope_digest",
    "action_digest",
    "evidence_window_start",
    "evidence_window_end",
    "watermarks",
    "forbidden_effect_observed",
    "envelope_contained",
    "success",
)


def _huginn_attributes(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return the normalized attribute map, or ``None`` if Huginn did not send it."""

    attributes = payload.get("attributes")
    if payload.get("producer_principal") != "Huginn" or not isinstance(attributes, Mapping):
        return None
    return attributes


def evidence_conflict_record(
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Project the immutable revision one evidence-conflict candidate declares."""

    attributes = _huginn_attributes(payload)
    if attributes is None:
        return None
    try:
        revision = EvidenceConflictRevision.create(
            status=EvidenceConflictStatus(str(attributes.get("status") or "")),
            target_ref=str(attributes.get("target_ref") or ""),
            scope_ref=str(attributes.get("scope_ref") or ""),
            generation_ref=str(attributes.get("generation_ref") or ""),
            semantic_refs=tuple(attributes.get("semantic_refs") or ()),
            conflicting_fields=tuple(attributes.get("conflicting_fields") or ()),
            source_a=EvidenceSourceLineage.model_validate(attributes.get("source_a")),
            source_b=EvidenceSourceLineage.model_validate(attributes.get("source_b")),
            supersedes_revision_ref=(
                str(attributes["supersedes_revision_ref"])
                if attributes.get("supersedes_revision_ref") is not None
                else None
            ),
        )
    except (TypeError, ValueError):
        return None
    return {
        **revision.model_dump(mode="json"),
        "correlation_id": revision.slot_ref,
        "idempotency_key": revision.revision_ref,
        "resource_id": revision.target_ref,
    }


def recovery_effect_observation_record(
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Project one external recovery post-effect observation for republication.

    The record stays a claim. Heimdall proves only that Huginn normalized it
    and that the declared observation fields are present in a bounded form; the
    workflow intake still proves the reporting principal, observer
    independence, authority class, attempt binding, containment, finality, and
    freshness before anything becomes durable.
    """

    attributes = _huginn_attributes(payload)
    if attributes is None:
        return None
    record: dict[str, Any] = {
        name: attributes[name] for name in _RECOVERY_EFFECT_OBSERVATION_FIELDS if name in attributes
    }
    record["event_type"] = RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE
    record["correlation_id"] = str(payload.get("correlation_id") or "")
    record["idempotency_key"] = str(payload.get("idempotency_key") or "")
    record["resource_id"] = str(payload.get("resource_id") or "")
    return record


__all__ = [
    "RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE",
    "evidence_conflict_record",
    "recovery_effect_observation_record",
]
