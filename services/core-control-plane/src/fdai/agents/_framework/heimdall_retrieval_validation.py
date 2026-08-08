"""Strict Heimdall projection for independent retrieval validation evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.rule_catalog.schema.rule_semantic_feedback import (
    build_feedback_candidate,
    query_failure_evidence_from_mapping,
    query_failure_evidence_to_mapping,
)

_VALIDATION_EVENT = "catalog.semantic_retrieval_failure.validated"


def retrieval_validation_from_event(payload: Mapping[str, Any]) -> dict[str, object] | None:
    """Validate one Huginn event and build Heimdall-owned retrieval evidence."""

    if payload.get("event_type") != _VALIDATION_EVENT:
        return None
    if payload.get("producer_principal") != "Huginn":
        raise ValueError("retrieval validation event MUST be published by Huginn")
    attributes = payload.get("attributes")
    if not isinstance(attributes, Mapping):
        raise ValueError("retrieval validation event MUST contain attributes")
    raw_failure = attributes.get("failure")
    if not isinstance(raw_failure, Mapping):
        raise ValueError("retrieval validation event MUST contain failure evidence")
    evidence = query_failure_evidence_from_mapping(raw_failure)
    candidate = build_feedback_candidate(evidence)
    correlation_id = str(payload.get("correlation_id") or evidence.attempt_id)
    return {
        "producer_principal": "Heimdall",
        "kind": "semantic_retrieval_failure_validation",
        "correlation_id": correlation_id,
        "idempotency_key": f"retrieval-validation:{candidate.candidate_id}",
        "candidate_id": candidate.candidate_id,
        "failure": query_failure_evidence_to_mapping(evidence),
    }


__all__ = ["retrieval_validation_from_event"]
