"""Declarative ViewSpec catalog and process render engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from fdai.core.reporting.engine import ReportEngine
from fdai.core.reporting.models import RenderedReport
from fdai.core.views import (
    ViewCatalogError,
    ViewEngine,
    WorkflowAppCatalogError,
    load_view_catalog,
    load_workflow_app_catalog,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.workflow import load_workflow_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.testing import InMemoryProcessRuntimeStore

_ROOT = Path(__file__).resolve().parents[3]
_NOW = datetime(2026, 7, 13, tzinfo=UTC)


def _workflow_names() -> set[str]:
    registry = PackageResourceSchemaRegistry()
    actions = load_action_type_catalog(
        _ROOT / "rule-catalog" / "action-types",
        schema_registry=registry,
        probes_root=_ROOT / "rule-catalog" / "probes",
    )
    workflows = load_workflow_catalog(
        _ROOT / "rule-catalog" / "workflows",
        schema_registry=registry,
        action_type_names={action.name for action in actions},
    )
    return {workflow.name for workflow in workflows}


def test_shipped_view_catalog_cross_references_workflow_and_report() -> None:
    specs = load_view_catalog(
        _ROOT / "rule-catalog" / "views",
        report_ids={"architecture-review-process"},
        workflow_names=_workflow_names(),
    )
    assert [spec.id for spec in specs] == ["architecture-review"]
    assert specs[0].applies_to.workflow_ref == "architecture-review"


def test_shipped_workflow_app_catalog_cross_references_workflow_and_view() -> None:
    manifests = load_workflow_app_catalog(
        _ROOT / "rule-catalog" / "operator-console",
        workflow_names=_workflow_names(),
        view_workflows={"architecture-review": "architecture-review"},
    )
    assert [manifest.id for manifest in manifests] == ["architecture-review"]
    assert manifests[0].route == "/workflow-apps/architecture-review"
    assert manifests[0].is_hub_visible is True


def test_workflow_app_rejects_mismatched_view_workflow(tmp_path: Path) -> None:
    (tmp_path / "app.yaml").write_text(
        """schema_version: 1.0.0
id: review-app
workflow_ref: architecture-review
view_ref: other-view
lifecycle: published
audience: reader
label: {en: Review, ko: Review}
description: {en: Review evidence, ko: Review evidence}
navigation: {exposure: hub, group: operations, order: 1}
""",
        encoding="utf-8",
    )
    with pytest.raises(WorkflowAppCatalogError, match="same workflow"):
        load_workflow_app_catalog(
            tmp_path,
            workflow_names={"architecture-review"},
            view_workflows={"other-view": "different-workflow"},
        )


def test_unknown_report_ref_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "view.yaml").write_text(
        """id: broken-view
version: 1.0.0
name: Broken
route: /processes/{process_id}
applies_to: {workflow_ref: architecture-review}
regions: [{id: main, report_ref: absent-report}]
""",
        encoding="utf-8",
    )
    with pytest.raises(ViewCatalogError, match="unknown report_ref"):
        load_view_catalog(
            tmp_path,
            report_ids=set(),
            workflow_names={"architecture-review"},
        )


class _StubReports:
    async def render(
        self,
        report_id: str,
        *,
        variables: dict[str, str],
    ) -> RenderedReport:
        assert variables == {"process_id": "process-1"}
        return RenderedReport(
            id=report_id,
            version="1.0.0",
            name="Architecture Review",
            description="",
            generated_at=_NOW,
            time_range=(_NOW - timedelta(days=1), _NOW),
            variables=variables,
            widgets=(),
        )


async def test_view_engine_selects_by_workflow_and_renders_envelope() -> None:
    process_store = InMemoryProcessRuntimeStore()
    snapshot, _ = await process_store.create(
        snapshot=ProcessSnapshot(
            process_id="process-1",
            workflow_ref="architecture-review",
            workflow_version="1.0.0",
            status=ProcessStatus.WAITING,
            current_step="evidence",
            target_resource_id="scope-1",
            started_at=_NOW,
            updated_at=_NOW,
            correlation_id="corr-1",
        ),
        event=ProcessEvent(
            event_id="event-1",
            process_id="process-1",
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key="process-1:create",
            recorded_at=_NOW,
            correlation_id="corr-1",
        ),
    )
    specs = load_view_catalog(
        _ROOT / "rule-catalog" / "views",
        report_ids={"architecture-review-process"},
        workflow_names={"architecture-review"},
    )
    engine = ViewEngine(
        specs=specs,
        reports=cast(ReportEngine, _StubReports()),
        processes=process_store,
    )

    rendered = await engine.render_process(snapshot.process_id)
    payload = rendered.to_dict()

    assert payload["id"] == "architecture-review"
    assert payload["process"]["status"] == "waiting"
    assert payload["process"]["current_step"] == "evidence"
    assert payload["regions"][0]["report"]["id"] == "architecture-review-process"
