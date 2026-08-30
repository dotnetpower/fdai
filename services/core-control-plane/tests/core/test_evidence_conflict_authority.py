from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fdai.core.control_loop import ControlLoop
from fdai.core.executor import ExecutorOutcome
from fdai.core.hil_resume import HilResumeCoordinator
from fdai.core.ontology_platform.evidence_conflict import (
    EvidenceConflictRevision,
    EvidenceConflictStatus,
    EvidenceSourceLineage,
)
from fdai.delivery.evidence_conflict import StateStoreEvidenceConflictProjection
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.models import Action, OntologyActionType
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.state_evidence import StateFactAuthority
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.core.mscp_profile.test_control_loop_shadow import _action, _rule

REPO_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 8, 30, 4, tzinfo=UTC)
TARGET = "resource:example-vm"


def _action_type(name: str) -> OntologyActionType:
    return next(
        item
        for item in load_action_type_catalog(
            REPO_ROOT / "rule-catalog" / "action-types",
            schema_registry=PackageResourceSchemaRegistry(),
        )
        if item.name == name
    )


def _conflict() -> EvidenceConflictRevision:
    projection = EvidenceSourceLineage(
        source_identity="provider-inventory",
        source_revision="revision-1",
        claim_digest="sha256:" + "a" * 64,
        authority=StateFactAuthority.PROVIDER,
        evidence_cutoff=NOW - timedelta(seconds=30),
        recorded_at=NOW,
        freshness_ceiling_seconds=300,
        evidence_refs=("evidence:provider",),
    )
    telemetry = EvidenceSourceLineage(
        source_identity="telemetry-query",
        source_revision="revision-1",
        claim_digest="sha256:" + "b" * 64,
        authority=StateFactAuthority.TELEMETRY,
        evidence_cutoff=NOW - timedelta(seconds=30),
        recorded_at=NOW,
        freshness_ceiling_seconds=300,
        evidence_refs=("evidence:telemetry",),
    )
    return EvidenceConflictRevision.create(
        status=EvidenceConflictStatus.ACTIVE,
        target_ref=TARGET,
        scope_ref="scope:example",
        generation_ref="inventory-generation:one",
        semantic_refs=("runtime.vm.power_state",),
        conflicting_fields=("power_state",),
        source_a=projection,
        source_b=telemetry,
        supersedes_revision_ref=None,
    )


async def _reader() -> StateStoreEvidenceConflictProjection:
    reader = StateStoreEvidenceConflictProjection(InMemoryStateStore())
    await reader.append(_conflict())
    return reader


def _vm_action() -> Action:
    return _action().model_copy(
        update={
            "action_type": "ops.start-vm",
            "target_resource_ref": TARGET,
        }
    )


async def test_control_loop_rechecks_conflict_before_executor_io() -> None:
    executor = MagicMock()
    executor.execute = AsyncMock()
    action_type = _action_type("ops.start-vm")
    loop = ControlLoop(
        event_ingest=MagicMock(),
        trust_router=MagicMock(),
        t0_engine=MagicMock(),
        action_builder=MagicMock(),
        executor=executor,
        audit_store=InMemoryStateStore(),
        rules_by_id={_rule().id: _rule()},
        action_types_by_name={action_type.name: action_type},
        evidence_conflict_reader=await _reader(),
    )

    result = await loop._dispatch_action(
        action=_vm_action(),
        rule=_rule(),
        correlation_id="correlation:conflict",
    )

    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT
    assert result.reason == "evidence conflict requires shadow-only: expired_unresolved"
    executor.execute.assert_not_awaited()


async def test_hil_resume_rechecks_conflict_after_human_approval() -> None:
    executor = MagicMock()
    executor.execute = AsyncMock()
    action_type = _action_type("ops.start-vm")
    coordinator = HilResumeCoordinator(
        state_store=InMemoryStateStore(),
        executor=executor,
        hil_channel=None,
        rules_by_id={_rule().id: _rule()},
        action_types_by_name={action_type.name: action_type},
        evidence_conflict_reader=await _reader(),
    )

    result = await coordinator._dispatch(
        action=_vm_action(),
        rule=_rule(),
        correlation_id="correlation:conflict",
    )

    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT
    assert result.reason == "evidence conflict requires shadow-only: expired_unresolved"
    executor.execute.assert_not_awaited()
