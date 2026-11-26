"""Content commitments carried by one Core-to-Operator semantic projection.

Core binds every ``core-operator-projection`` event to two commitments before it publishes.
``evidence_digest`` covers the evidence the terminal answer renders: the complete semantic result
for a semantic query, or the assessment, trace receipt, and Pantheon diagnostic for a Pantheon
assurance turn. ``projection_id`` covers the complete immutable event. The Operator recomputes both
with these functions before durable projection, so an event whose result, manifest, receipts, or
payload no longer matches what Core committed is never rendered.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Final
from uuid import UUID, uuid5

from fdai_service_contracts.ontology_query import content_digest

SEMANTIC_PROJECTION_ID_NAMESPACE: Final = UUID("00000000-0000-0000-0000-000000000000")
SEMANTIC_QUERY_REQUEST_KIND: Final = "semantic_query"
PANTHEON_ASSURANCE_REQUEST_KIND: Final = "pantheon_conversation_assurance"
_PANTHEON_EVIDENCE_FIELDS: Final = ("assessment_id", "trace_receipt_id", "pantheon_diagnostic")


def semantic_projection_id(projection: Mapping[str, object]) -> str:
    """Return the identity that binds a projection to its complete immutable content.

    Any ``projection_id`` already present is excluded, so the producer and a verifier compute the
    same value. Raises ``ValueError`` when ``request_id`` is not a string or the content is not
    JSON-serializable.
    """
    request_id = projection.get("request_id")
    if not isinstance(request_id, str):
        raise ValueError("semantic projection request_id MUST be a string")
    content = {key: value for key, value in projection.items() if key != "projection_id"}
    encoded = json.dumps(
        content,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    projection_digest = hashlib.sha256(encoded).hexdigest()
    return str(uuid5(SEMANTIC_PROJECTION_ID_NAMESPACE, f"{request_id}\0{projection_digest}"))


def pantheon_assurance_evidence_digest(result: Mapping[str, object]) -> str:
    """Return the evidence commitment of one Pantheon assurance result."""
    missing = [field for field in _PANTHEON_EVIDENCE_FIELDS if field not in result]
    if missing:
        raise ValueError(f"Pantheon assurance result is missing {', '.join(missing)}")
    return content_digest({field: result[field] for field in _PANTHEON_EVIDENCE_FIELDS})


def semantic_projection_evidence_digest(projection: Mapping[str, object]) -> str:
    """Return the evidence commitment Core computes for a projection's request kind.

    Raises ``ValueError`` for an unknown request kind or a missing committed body, so a verifier
    fails closed instead of accepting content it cannot recompute.
    """
    payload = projection.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("semantic projection payload MUST be an object")
    request_kind = payload.get("request_kind")
    if request_kind == SEMANTIC_QUERY_REQUEST_KIND:
        semantic_result = projection.get("semantic_result")
        if not isinstance(semantic_result, Mapping):
            raise ValueError("semantic projection MUST contain semantic_result")
        return content_digest(semantic_result)
    if request_kind == PANTHEON_ASSURANCE_REQUEST_KIND:
        result = payload.get("pantheon_assurance")
        if not isinstance(result, Mapping):
            raise ValueError("Pantheon assurance projection MUST contain its result")
        return pantheon_assurance_evidence_digest(result)
    raise ValueError("semantic projection request_kind is unsupported")


def semantic_projection_commitment_violation(projection: Mapping[str, object]) -> str | None:
    """Return why a received projection breaks its commitments, or ``None`` when both hold."""
    try:
        evidence_digest = semantic_projection_evidence_digest(projection)
        projection_id = semantic_projection_id(projection)
    except (TypeError, ValueError):
        return "commitment_uncomputable"
    if projection.get("evidence_digest") != evidence_digest:
        return "evidence_digest_mismatch"
    if projection.get("projection_id") != projection_id:
        return "projection_id_mismatch"
    return None


__all__ = [
    "PANTHEON_ASSURANCE_REQUEST_KIND",
    "SEMANTIC_PROJECTION_ID_NAMESPACE",
    "SEMANTIC_QUERY_REQUEST_KIND",
    "pantheon_assurance_evidence_digest",
    "semantic_projection_commitment_violation",
    "semantic_projection_evidence_digest",
    "semantic_projection_id",
]
