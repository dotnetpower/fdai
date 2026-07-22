from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.shared.providers.read_investigation import (
    ActorKind,
    EvidenceFreshness,
    EvidenceStatus,
    ReadEvidenceEnvelope,
    ReadEvidenceRecord,
    ResolvedResource,
    ResourceCandidate,
    ResourceResolution,
    ResourceResolutionStatus,
)

NOW = datetime(2026, 7, 22, tzinfo=UTC)


def test_resolution_requires_one_exact_or_bounded_ambiguous_resources() -> None:
    resource = ResolvedResource(
        resource_ref="resource:one",
        scope_ref="scope:allowed",
        name="vm-01",
        resource_type="compute.vm",
        resource_group="rg-example",
    )
    matched = ResourceResolution(status=ResourceResolutionStatus.MATCHED, resource=resource)
    assert matched.resource == resource

    candidates = tuple(
        ResourceCandidate(
            resource_ref=f"resource:{index}",
            name="vm-01",
            resource_type="compute.vm",
            resource_group=f"rg-{index}",
        )
        for index in range(2)
    )
    ambiguous = ResourceResolution(
        status=ResourceResolutionStatus.AMBIGUOUS,
        candidates=candidates,
    )
    assert len(ambiguous.candidates) == 2

    with pytest.raises(ValueError, match="matched resolution"):
        ResourceResolution(status=ResourceResolutionStatus.MATCHED)
    with pytest.raises(ValueError, match="at least two"):
        ResourceResolution(
            status=ResourceResolutionStatus.AMBIGUOUS,
            candidates=candidates[:1],
        )


def test_evidence_envelope_keeps_actor_and_refs_bounded() -> None:
    record = ReadEvidenceRecord(
        operation_kind="deallocate",
        status="succeeded",
        actor_ref="principal:opaque",
        actor_kind=ActorKind.USER,
        occurred_at=NOW,
        correlation_ref="correlation:opaque",
    )
    envelope = ReadEvidenceEnvelope(
        status=EvidenceStatus.MATCHED,
        authority="control_plane_activity",
        resource_ref="resource:one",
        observed_at=NOW,
        freshness=EvidenceFreshness.LIVE,
        truncated=False,
        records=(record,),
        evidence_refs=("evidence:sha256:abc",),
    )
    assert envelope.records == (record,)

    with pytest.raises(ValueError, match="set together"):
        ReadEvidenceRecord(
            operation_kind="deallocate",
            status="succeeded",
            actor_ref="principal:opaque",
            occurred_at=NOW,
        )
    with pytest.raises(ValueError, match="non-matched"):
        ReadEvidenceEnvelope(
            status=EvidenceStatus.NONE,
            authority="control_plane_activity",
            resource_ref="resource:one",
            observed_at=NOW,
            freshness=EvidenceFreshness.LIVE,
            truncated=False,
            records=(record,),
            evidence_refs=(),
        )
