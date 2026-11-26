"""Focused ObjectType evidence-health projection tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.delivery.ontology_evidence_health_projection import (
    OntologyEvidenceSourceStatus,
    build_object_type_evidence_health_projection,
)

DIGEST = f"sha256:{'a' * 64}"
NOW = datetime(2026, 8, 19, 0, 0, tzinfo=UTC)


def _source(**changes: object) -> OntologyEvidenceSourceStatus:
    values = {
        "source_kind": "provider_observation",
        "source_identity_alias": "inventory-projection",
        "generation": "generation-1",
        "ontology_release_digest": DIGEST,
        "observed_at": NOW - timedelta(minutes=5),
        "recorded_at": NOW - timedelta(minutes=4),
        "freshness_ceiling_seconds": 600,
        "complete": True,
        "truncated": False,
        "synthetic": False,
        "conflicts": (),
        "drop_reasons": (),
        "visible_instance_count": 3,
        "visible_link_count": 2,
        "evidence_refs": ("inventory-generation:generation-1",),
    }
    values.update(changes)
    return OntologyEvidenceSourceStatus(**values)  # type: ignore[arg-type]


def test_evidence_health_distinguishes_current_stale_and_degraded_source_state() -> None:
    current = build_object_type_evidence_health_projection(
        object_type="Resource",
        ontology_release_digest=DIGEST,
        now=NOW,
        source=_source(),
    )
    stale = build_object_type_evidence_health_projection(
        object_type="Resource",
        ontology_release_digest=DIGEST,
        now=NOW,
        source=_source(observed_at=NOW - timedelta(hours=1)),
    )
    degraded = build_object_type_evidence_health_projection(
        object_type="Resource",
        ontology_release_digest=DIGEST,
        now=NOW,
        source=_source(
            complete=False,
            truncated=True,
            synthetic=True,
            conflicts=("state-disagreement",),
            drop_reasons=("unverified-link",),
        ),
    )

    assert current["freshness_state"] == "current"
    assert current["complete"] is True
    assert stale["freshness_state"] == "stale"
    assert degraded["complete"] is False
    assert degraded["truncated"] is True
    assert degraded["synthetic"] is True
    assert degraded["conflicts"] == ["state-disagreement"]
    assert degraded["execution_authority"] is False
    assert degraded["mutation_authority"] is False


def test_unavailable_evidence_does_not_fabricate_zero_counts() -> None:
    result = build_object_type_evidence_health_projection(
        object_type="Decision",
        ontology_release_digest=DIGEST,
        now=NOW,
        source=None,
        unavailable_reason="object_type_evidence_source_not_bound",
    )

    assert result["availability"] == "unavailable"
    assert result["freshness_state"] == "unavailable"
    assert result["visible_instance_count"] is None
    assert result["visible_link_count"] is None
    assert result["complete"] is False
