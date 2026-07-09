"""Control-loop wiring for the shadow workflow coordinator.

Covers ``fdai.__main__._build_workflow_coordinator``: the opt-in gate
(FDAI_WORKFLOW_SHADOW) and that the assembled coordinator fires the shipped
Workflows off a matching Event.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from fdai.__main__ import _build_workflow_coordinator, _resolve_catalog_root
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.workflow import load_workflow_catalog
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_TS = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)


def _load() -> tuple[Path, dict, tuple]:
    root = _resolve_catalog_root()
    registry = PackageResourceSchemaRegistry()
    probes = root / "probes"
    action_types = load_action_type_catalog(
        root / "action-types",
        schema_registry=registry,
        probes_root=probes if probes.is_dir() else None,
    )
    workflows = load_workflow_catalog(
        root / "workflows",
        schema_registry=registry,
        action_type_names={a.name for a in action_types},
    )
    return root, {a.name: a for a in action_types}, workflows


def test_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FDAI_WORKFLOW_SHADOW", raising=False)
    root, atbn, workflows = _load()
    coord = _build_workflow_coordinator(
        catalog_root=root,
        workflows=workflows,
        action_types_by_name=atbn,
        audit_store=InMemoryStateStore(),
    )
    assert coord is None


def test_enabled_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_WORKFLOW_SHADOW", "1")
    root, atbn, workflows = _load()
    coord = _build_workflow_coordinator(
        catalog_root=root,
        workflows=workflows,
        action_types_by_name=atbn,
        audit_store=InMemoryStateStore(),
    )
    assert coord is not None


def test_empty_workflows_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_WORKFLOW_SHADOW", "1")
    root, atbn, _ = _load()
    coord = _build_workflow_coordinator(
        catalog_root=root,
        workflows=(),
        action_types_by_name=atbn,
        audit_store=InMemoryStateStore(),
    )
    assert coord is None


async def test_enabled_coordinator_fires_on_shipped_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_WORKFLOW_SHADOW", "1")
    root, atbn, workflows = _load()
    audit = InMemoryStateStore()
    coord = _build_workflow_coordinator(
        catalog_root=root,
        workflows=workflows,
        action_types_by_name=atbn,
        audit_store=audit,
    )
    assert coord is not None
    event = Event(
        schema_version="1.0.0",
        event_id=uuid4(),
        idempotency_key="idem-1",
        source="test",
        event_type="object.drift",  # cost-aware-remediation trigger
        resource_ref="res-1",
        payload={},
        detected_at=_TS,
        ingested_at=_TS,
        mode=Mode.SHADOW,
    )
    runs = await coord.on_event(event)
    assert runs, "the object.drift signal should fire at least one shipped workflow"
    kinds = {row["entry"]["action_kind"] for row in audit.audit_entries}
    assert "workflow.process-plan" in kinds
