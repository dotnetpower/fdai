"""Build bounded ObjectType evidence health without exposing runtime instances."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class OntologyEvidenceSourceStatus:
    """Sanitized source metadata used to project one ObjectType health summary."""

    source_kind: str
    source_identity_alias: str
    generation: str
    ontology_release_digest: str
    observed_at: datetime
    recorded_at: datetime
    freshness_ceiling_seconds: int | None
    complete: bool
    truncated: bool
    synthetic: bool
    conflicts: tuple[str, ...]
    drop_reasons: tuple[str, ...]
    visible_instance_count: int
    visible_link_count: int
    evidence_refs: tuple[str, ...]


def build_object_type_evidence_health_projection(
    *,
    object_type: str,
    ontology_release_digest: str,
    now: datetime,
    source: OntologyEvidenceSourceStatus | None,
    unavailable_reason: str | None = None,
) -> dict[str, object]:
    """Project source health or an explicit unavailable state with zero authority."""

    if now.tzinfo is None:
        raise ValueError("ontology evidence health now MUST be timezone-aware")
    if source is None:
        if not unavailable_reason:
            raise ValueError("unavailable ontology evidence health requires a reason")
        payload: dict[str, object] = {
            "schema_version": "1.0.0",
            "ontology_release_digest": ontology_release_digest,
            "object_type": object_type,
            "availability": "unavailable",
            "unavailable_reason": unavailable_reason,
            "source": None,
            "freshness_state": "unavailable",
            "complete": False,
            "truncated": False,
            "synthetic": None,
            "conflicts": [],
            "drop_reasons": [],
            "visible_instance_count": None,
            "visible_link_count": None,
            "evidence_refs": [],
            "execution_authority": False,
            "mutation_authority": False,
        }
        payload["_revision"] = _digest(payload)
        return payload
    if source.ontology_release_digest != ontology_release_digest:
        raise ValueError("ontology evidence health source release does not match active release")
    if source.observed_at.tzinfo is None or source.recorded_at.tzinfo is None:
        raise ValueError("ontology evidence health timestamps MUST be timezone-aware")
    if source.observed_at > source.recorded_at:
        raise ValueError("ontology evidence health observation MUST NOT follow its record time")
    if source.visible_instance_count < 0 or source.visible_link_count < 0:
        raise ValueError("ontology evidence health counts MUST be non-negative")
    if source.freshness_ceiling_seconds is None:
        freshness_state = "unknown"
    elif source.freshness_ceiling_seconds < 1:
        raise ValueError("ontology evidence freshness ceiling MUST be positive")
    elif source.observed_at < now - timedelta(seconds=source.freshness_ceiling_seconds):
        freshness_state = "stale"
    else:
        freshness_state = "current"
    payload = {
        "schema_version": "1.0.0",
        "ontology_release_digest": ontology_release_digest,
        "object_type": object_type,
        "availability": "available",
        "unavailable_reason": None,
        "source": {
            "kind": source.source_kind,
            "identity_alias": source.source_identity_alias,
            "generation": source.generation,
            "observed_at": source.observed_at.isoformat(),
            "recorded_at": source.recorded_at.isoformat(),
            "freshness_ceiling_seconds": source.freshness_ceiling_seconds,
        },
        "freshness_state": freshness_state,
        "complete": source.complete,
        "truncated": source.truncated,
        "synthetic": source.synthetic,
        "conflicts": list(source.conflicts),
        "drop_reasons": list(source.drop_reasons),
        "visible_instance_count": source.visible_instance_count,
        "visible_link_count": source.visible_link_count,
        "evidence_refs": list(source.evidence_refs),
        "execution_authority": False,
        "mutation_authority": False,
    }
    payload["_revision"] = _digest(payload)
    return payload


def _digest(value: dict[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "OntologyEvidenceSourceStatus",
    "build_object_type_evidence_health_projection",
]
