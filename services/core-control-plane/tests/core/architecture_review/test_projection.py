"""Architecture-review manifest to ontology graph projection."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from fdai.core.architecture_review import (
    ArchitectureReviewObservation,
    ArchitectureReviewProjector,
)
from fdai.core.workflow.projection import ProcessOntologyProjector
from fdai.rule_catalog.schema.link_type import load_link_type_catalog
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

_ROOT = Path(__file__).resolve().parents[5]
_CATALOG = _ROOT / "rule-catalog" / "vocabulary"
_NOW = datetime(2026, 7, 13, tzinfo=UTC)


def _manifest() -> dict[str, Any]:
    raw = yaml.safe_load((_ROOT / "config" / "architecture-review.yaml").read_text())
    assert isinstance(raw, dict)
    return raw


def _store() -> InMemoryOntologyInstanceStore:
    registry = PackageResourceSchemaRegistry()
    object_types = load_object_type_catalog(_CATALOG / "object-types", schema_registry=registry)
    link_types = load_link_type_catalog(
        _CATALOG / "link-types",
        schema_registry=registry,
        object_types=object_types,
    )
    return InMemoryOntologyInstanceStore(
        object_types=object_types,
        link_types=link_types,
    )


def _snapshot() -> ProcessSnapshot:
    return ProcessSnapshot(
        process_id="process-arb-1",
        workflow_ref="architecture-review",
        workflow_version="1.0.0",
        status=ProcessStatus.WAITING,
        current_step="evidence",
        target_resource_id="scope-1",
        started_at=_NOW,
        updated_at=_NOW,
        correlation_id="corr-arb-1",
        revision=3,
    )


def _observation(
    change_id: str,
    *,
    process_ref: str,
) -> ArchitectureReviewObservation:
    return ArchitectureReviewObservation(
        change_id=change_id,
        idempotency_key=f"{change_id}:key",
        correlation_id=f"{change_id}:correlation",
        target_ref="scope-1",
        change_digest=f"sha256:{'a' * 64}",
        recommendation="hold",
        reasons=("observation_only",),
        context=None,
        evidence=None,
        scenario=None,
        decision_case=None,
        impact_envelope=None,
        normalized_change=(
            ("id", change_id),
            ("change_kind", "planned_change"),
            ("target_ref", "scope-1"),
            ("actor_ref", "actor:example"),
            ("status", "proposed"),
            ("occurred_at", _NOW.isoformat()),
            ("evidence_ref", f"evidence:{change_id}"),
            ("process_ref", process_ref),
        ),
    )


async def test_manifest_projects_review_case_and_checks() -> None:
    store = _store()
    process_projector = ProcessOntologyProjector(
        store,
        domain_projectors={"architecture-review": ArchitectureReviewProjector(store, _manifest())},
    )
    await process_projector.project(_snapshot())

    graph = await store.traverse(root_ids=("process-arb-1",), max_depth=2, limit=100)
    by_type: dict[str, int] = {}
    for item in graph.objects:
        by_type[item.object_type] = by_type.get(item.object_type, 0) + 1
    review = await store.get_object("fdai-target-architecture-v1")
    manifest_review = _manifest()["architecture_review"]
    gate = manifest_review["production_gate"]
    expected_checks = (
        len(manifest_review["artifacts"])
        + len(manifest_review["blockers"])
        + len(gate["required_owner_slots"])
        + len(gate["required_evidence"])
    )

    assert review is not None
    assert review.properties["status"] == "evidence_pending"
    assert by_type == {"Process": 1, "ReviewCase": 1, "ReviewCheck": expected_checks}
    assert any(link.link_type == "runs_review" for link in graph.links)
    assert sum(link.link_type == "contains_check" for link in graph.links) == expected_checks


async def test_owner_and_evidence_bindings_materialize_typed_objects() -> None:
    manifest = deepcopy(_manifest())
    review = manifest["architecture_review"]
    gate = review["production_gate"]
    gate["owner_bindings"] = {
        "architecture-owner": {
            "subject": "group:architecture-reviewers",
            "escalation": "platform-maintainers",
        }
    }
    gate["evidence_bindings"] = {
        "production-terraform-plan": {
            "uri": "evidence://production-terraform-plan",
            "sha256": "a" * 64,
            "approved_by": "group:architecture-reviewers",
            "approved_at": "2026-07-13T00:00:00Z",
            "expires_at": "2099-07-13T00:00:00Z",
        }
    }
    store = _store()
    projector = ProcessOntologyProjector(
        store,
        domain_projectors={"architecture-review": ArchitectureReviewProjector(store, manifest)},
    )

    await projector.project(_snapshot())
    graph = await store.traverse(root_ids=("process-arb-1",), max_depth=3, limit=100)

    assert any(item.object_type == "Principal" for item in graph.objects)
    assert any(item.object_type == "EvidenceArtifact" for item in graph.objects)
    assert any(link.link_type == "assigned_to" for link in graph.links)
    assert any(link.link_type == "supported_by" for link in graph.links)


async def test_approval_and_decision_events_materialize_governance_objects() -> None:
    store = _store()
    projector = ProcessOntologyProjector(
        store,
        domain_projectors={"architecture-review": ArchitectureReviewProjector(store, _manifest())},
    )
    snapshot = _snapshot()
    await projector.project(snapshot)
    await projector.project(
        snapshot,
        event=ProcessEvent(
            event_id="approval-requested",
            process_id=snapshot.process_id,
            kind=ProcessEventKind.APPROVAL_REQUESTED,
            idempotency_key="approval-requested",
            recorded_at=_NOW,
            correlation_id=snapshot.correlation_id,
            step_id="board_approval",
            payload={"required_role": "approver", "quorum": 2, "no_self_approval": True},
        ),
    )
    await projector.project(
        snapshot,
        event=ProcessEvent(
            event_id="approval-recorded",
            process_id=snapshot.process_id,
            kind=ProcessEventKind.APPROVAL_RECORDED,
            idempotency_key="approval-recorded",
            recorded_at=_NOW,
            correlation_id=snapshot.correlation_id,
            step_id="board_approval",
            payload={
                "decision": "approved",
                "required_role": "approver",
                "quorum": 2,
                "no_self_approval": True,
            },
        ),
    )
    await projector.project(
        snapshot,
        event=ProcessEvent(
            event_id="decision-recorded",
            process_id=snapshot.process_id,
            kind=ProcessEventKind.DECISION_RECORDED,
            idempotency_key="decision-recorded",
            recorded_at=_NOW,
            correlation_id=snapshot.correlation_id,
            step_id="board_decision",
            payload={"decision": "conditional", "reason": "evidence accepted"},
        ),
    )

    approval = await store.get_object("fdai-target-architecture-v1:approval:board_approval")
    decision = await store.get_object("fdai-target-architecture-v1:decision:board_decision")
    graph = await store.traverse(root_ids=("fdai-target-architecture-v1",), max_depth=2, limit=100)

    assert approval is not None
    assert approval.properties["status"] == "approved"
    assert approval.properties["quorum"] == 2
    assert decision is not None
    assert decision.properties["outcome"] == "conditional"
    assert any(link.link_type == "has_approval" for link in graph.links)
    assert any(link.link_type == "resolved_by" for link in graph.links)


async def test_observation_projection_preserves_change_when_process_is_missing() -> None:
    store = _store()
    projector = ArchitectureReviewProjector(store, {})

    await projector.project_observation(
        _observation("change-missing-process", process_ref="process-missing")
    )

    assert await store.get_object("change-missing-process") is not None
    assert await store.get_object("arb-review:change-missing-process") is not None
    graph = await store.traverse(
        root_ids=("change-missing-process",),
        max_depth=1,
        limit=10,
    )
    assert not any(link.link_type == "change_instantiates_process" for link in graph.links)


async def test_observation_projection_does_not_reassign_reused_process() -> None:
    store = _store()
    process_projector = ProcessOntologyProjector(store)
    await process_projector.project(_snapshot())
    projector = ArchitectureReviewProjector(store, {})

    await projector.project_observation(
        _observation("change-primary", process_ref=_snapshot().process_id)
    )
    await projector.project_observation(
        _observation("change-conflicting", process_ref=_snapshot().process_id)
    )

    assert await store.get_object("change-primary") is not None
    assert await store.get_object("change-conflicting") is not None
    assert await store.get_object("arb-review:change-conflicting") is not None
    graph = await store.traverse(
        root_ids=("change-primary",),
        max_depth=1,
        limit=20,
    )
    process_links = [
        link for link in graph.links if link.link_type == "change_instantiates_process"
    ]
    assert len(process_links) == 1
    assert process_links[0].from_id == "change-primary"
