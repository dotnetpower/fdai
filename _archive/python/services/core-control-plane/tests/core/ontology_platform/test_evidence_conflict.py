from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.mscp_profile import MscpAuthorityCeiling
from fdai.core.ontology_platform.evidence_conflict import (
    EvidenceConflictDisposition,
    EvidenceConflictStatus,
    build_cross_source_evidence_conflict,
    evidence_conflict_ceiling,
)
from fdai.core.ontology_platform.observation_adjudication import (
    CrossSourceStateAdjudication,
    StateEvidenceSnapshot,
    adjudicate_projected_state,
)
from fdai.delivery.evidence_conflict import (
    EvidenceConflictProjectionError,
    StateStoreEvidenceConflictProjection,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.models import OntologyActionType
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.state_evidence import (
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 8, 30, 1, tzinfo=UTC)


def _snapshot(
    *,
    authority: StateFactAuthority,
    state: str,
    source: str,
) -> StateEvidenceSnapshot:
    return StateEvidenceSnapshot(
        target_id="resource:example-vm",
        scope_ref="scope:example",
        state={"power_state": state},
        metadata=StateFactMetadata(
            lane=StateFactLane.OBSERVED,
            authority=authority,
            source_identity=source,
            source_revision="revision-1",
            effective_at=NOW - timedelta(seconds=30),
            recorded_at=NOW,
            evidence_cutoff=NOW - timedelta(seconds=30),
            freshness_ceiling_seconds=300,
            completeness=1.0,
            synthetic=False,
            evidence_refs=(f"evidence:{source}",),
        ),
    )


def _adjudication(*, agreed: bool) -> CrossSourceStateAdjudication:
    return adjudicate_projected_state(
        projection=_snapshot(
            authority=StateFactAuthority.PROVIDER,
            state="running",
            source="provider-inventory",
        ),
        telemetry=_snapshot(
            authority=StateFactAuthority.TELEMETRY,
            state="running" if agreed else "stopped",
            source="telemetry-query",
        ),
        evaluated_at=NOW,
    )


def _action(name: str) -> OntologyActionType:
    return next(
        item
        for item in load_action_type_catalog(
            REPO_ROOT / "rule-catalog" / "action-types",
            schema_registry=PackageResourceSchemaRegistry(),
        )
        if item.name == name
    )


def test_active_and_resolved_revisions_share_one_stable_slot() -> None:
    active = build_cross_source_evidence_conflict(
        _adjudication(agreed=False),
        generation_ref="inventory-generation:one",
        semantic_refs=("runtime.vm.power_state",),
    )
    resolved = build_cross_source_evidence_conflict(
        _adjudication(agreed=True),
        generation_ref="inventory-generation:one",
        semantic_refs=("runtime.vm.power_state",),
        supersedes_revision_ref=active.revision_ref,
    )

    assert active.status is EvidenceConflictStatus.ACTIVE
    assert resolved.status is EvidenceConflictStatus.RESOLVED
    assert active.id == resolved.id
    assert active.slot_ref == resolved.slot_ref
    assert active.revision_ref != resolved.revision_ref
    assert resolved.supersedes_revision_ref == active.revision_ref
    assert active.producer_principal == resolved.producer_principal == "Heimdall"
    assert active.execution_authority is resolved.execution_authority is False


async def test_muninn_projection_is_append_only_and_resolution_requires_current() -> None:
    store = InMemoryStateStore()
    projection = StateStoreEvidenceConflictProjection(store)
    active = build_cross_source_evidence_conflict(
        _adjudication(agreed=False),
        generation_ref="inventory-generation:one",
        semantic_refs=("runtime.vm.power_state",),
    )
    resolved = build_cross_source_evidence_conflict(
        _adjudication(agreed=True),
        generation_ref="inventory-generation:one",
        semantic_refs=("runtime.vm.power_state",),
        supersedes_revision_ref=active.revision_ref,
    )

    assert await projection.append(active) is True
    assert await projection.append(active) is False
    assert await projection.active_for(
        target_ref=active.target_ref,
        semantic_refs=frozenset(active.semantic_refs),
    ) == (active,)
    assert await projection.append(resolved) is True
    assert await projection.current(active.slot_ref) == resolved
    assert (
        await projection.active_for(
            target_ref=active.target_ref,
            semantic_refs=frozenset(active.semantic_refs),
        )
        == ()
    )

    with pytest.raises(EvidenceConflictProjectionError, match="does not supersede"):
        await projection.append(
            build_cross_source_evidence_conflict(
                _adjudication(agreed=False),
                generation_ref="inventory-generation:one",
                semantic_refs=("runtime.vm.power_state",),
                supersedes_revision_ref=active.revision_ref,
            )
        )


def test_only_intersecting_action_evidence_is_lowered_and_expiry_does_not_clear() -> None:
    conflict = build_cross_source_evidence_conflict(
        _adjudication(agreed=False),
        generation_ref="inventory-generation:one",
        semantic_refs=("runtime.vm.power_state",),
    )

    active = evidence_conflict_ceiling(
        (conflict,),
        action_type=_action("ops.start-vm"),
        target_ref=conflict.target_ref,
        evaluated_at=conflict.expires_at,
    )
    expired = evidence_conflict_ceiling(
        (conflict,),
        action_type=_action("ops.start-vm"),
        target_ref=conflict.target_ref,
        evaluated_at=conflict.expires_at + timedelta(microseconds=1),
    )
    unrelated = evidence_conflict_ceiling(
        (conflict,),
        action_type=_action("ops.scale-out"),
        target_ref=conflict.target_ref,
        evaluated_at=conflict.expires_at,
    )

    assert active == (
        MscpAuthorityCeiling.HOLD,
        EvidenceConflictDisposition.ACTIVE_CONFLICT,
    )
    assert expired == (
        MscpAuthorityCeiling.HOLD,
        EvidenceConflictDisposition.EXPIRED_UNRESOLVED,
    )
    assert unrelated == (
        MscpAuthorityCeiling.PRESERVE,
        EvidenceConflictDisposition.NOT_APPLICABLE,
    )
