"""Architecture-review manifest to ontology graph projection."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from fdai.core.architecture_review import ArchitectureReviewProjector
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

_ROOT = Path(__file__).resolve().parents[3]
_CATALOG = _ROOT / "rule-catalog" / "vocabulary"
_NOW = datetime(2026, 7, 13, tzinfo=UTC)


def _manifest() -> dict[str, Any]:
    raw = yaml.safe_load((_ROOT / "config" / "architecture-review.yaml").read_text())
    assert isinstance(raw, dict)
    return raw


def _store() -> InMemoryOntologyInstanceStore:
    registry = PackageResourceSchemaRegistry()
    object_types = load_object_type_catalog(
        _CATALOG / "object-types", schema_registry=registry
    )
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


async def test_manifest_projects_review_case_and_checks() -> None:
    store = _store()
    process_projector = ProcessOntologyProjector(
        store,
        domain_projectors={
            "architecture-review": ArchitectureReviewProjector(store, _manifest())
        },
    )
    await process_projector.project(_snapshot())

    graph = await store.traverse(root_ids=("process-arb-1",), max_depth=2, limit=100)
    by_type: dict[str, int] = {}
    for item in graph.objects:
        by_type[item.object_type] = by_type.get(item.object_type, 0) + 1
    review = await store.get_object("fdai-target-architecture-v1")

    assert review is not None
    assert review.properties["status"] == "evidence_pending"
    assert by_type == {"Process": 1, "ReviewCase": 1, "ReviewCheck": 35}
    assert any(link.link_type == "runs_review" for link in graph.links)
    assert sum(link.link_type == "contains_check" for link in graph.links) == 35


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
        }
    }
    store = _store()
    projector = ProcessOntologyProjector(
        store,
        domain_projectors={
            "architecture-review": ArchitectureReviewProjector(store, manifest)
        },
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
        domain_projectors={
            "architecture-review": ArchitectureReviewProjector(store, _manifest())
        },
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
    graph = await store.traverse(
        root_ids=("fdai-target-architecture-v1",), max_depth=2, limit=100
    )

    assert approval is not None
    assert approval.properties["status"] == "approved"
    assert approval.properties["quorum"] == 2
    assert decision is not None
    assert decision.properties["outcome"] == "conditional"
    assert any(link.link_type == "has_approval" for link in graph.links)
    assert any(link.link_type == "resolved_by" for link in graph.links)