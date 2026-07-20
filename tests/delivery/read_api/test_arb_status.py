"""ARB status keeps contract, production, and runtime health distinct."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fdai.core.views import ViewEngine
from fdai.delivery.read_api.routes.arb_status import ArchitectureReviewStatusPanel
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.testing import InMemoryProcessRuntimeStore

_ROOT = Path(__file__).resolve().parents[3]
_NOW = datetime(2026, 7, 20, tzinfo=UTC)


class _NoReports:
    async def render(self, report_id: str, *, variables: dict[str, str]):  # type: ignore[no-untyped-def]
        raise AssertionError((report_id, variables))


def _panel(store: InMemoryProcessRuntimeStore) -> ArchitectureReviewStatusPanel:
    return ArchitectureReviewStatusPanel(
        manifest_path=_ROOT / "config" / "architecture-review.yaml",
        repo_root=_ROOT,
        engine=ViewEngine(specs=(), reports=_NoReports(), processes=store),  # type: ignore[arg-type]
    )


async def test_upstream_status_is_structurally_healthy_and_not_started() -> None:
    result = await _panel(InMemoryProcessRuntimeStore()).render(params={})

    assert result["contract"]["healthy"] is True
    assert result["production"]["ready"] is False
    assert result["runtime"] == {
        "health": "not_started",
        "process": None,
        "next_action": "start architecture-review workflow",
    }


async def test_waiting_process_is_healthy_and_exposes_next_action() -> None:
    store = InMemoryProcessRuntimeStore()
    await store.create(
        snapshot=ProcessSnapshot(
            process_id="arb-process-1",
            workflow_ref="architecture-review",
            workflow_version="1.0.0",
            status=ProcessStatus.WAITING,
            current_step="evidence",
            target_resource_id="fdai-control-plane",
            started_at=_NOW,
            updated_at=_NOW,
            correlation_id="arb-correlation-1",
        ),
        event=ProcessEvent(
            event_id="arb-created",
            process_id="arb-process-1",
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key="arb-created",
            recorded_at=_NOW,
            correlation_id="arb-correlation-1",
        ),
    )

    result = await _panel(store).render(params={})

    assert result["runtime"]["health"] == "healthy"
    assert result["runtime"]["process"]["status"] == "waiting"
    assert result["runtime"]["next_action"] == "publish evidence.updated"
