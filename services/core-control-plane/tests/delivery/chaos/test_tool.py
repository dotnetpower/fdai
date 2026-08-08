from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fdai.core.chaos.factory import ScenarioFactory
from fdai.core.chaos.scenario_catalog import CatalogEntry
from fdai.delivery.chaos.tool import ChaosExperimentToolExecutor
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallRequest, ToolPreconditionError


def _entry() -> CatalogEntry:
    return CatalogEntry(
        id="chaos.example",
        source_path=Path("example.yaml"),
        spec={
            "fault_family": "stop",
            "description": "example",
            "target_type": "pod",
            "expected_signal": "pod_restart",
            "blast_radius_cap": 1,
            "duration_seconds": 1.0,
            "params": {},
            "rollback_note": "stop",
            "injector": "needs-injector",
        },
    )


def _request(*, mode: Mode, targets: list[str] | None = None) -> ToolCallRequest:
    return ToolCallRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000001"),
        idempotency_key="chaos-example-1",
        action_type_name="tool.run-chaos-experiment",
        rule_ids=("example.rule",),
        tool_ref="chaos.example",
        arguments={"scenario_id": "chaos.example", "targets": targets or ["pod-a"]},
        labels=("enforce",) if mode is Mode.ENFORCE else ("shadow",),
        mode=mode,
    )


async def test_shadow_runs_without_live_injector() -> None:
    executor = ChaosExperimentToolExecutor(
        entries=(_entry(),), promoted_ids=frozenset(), factory=ScenarioFactory()
    )
    receipt = await executor.execute(_request(mode=Mode.SHADOW))
    assert receipt.outcome is ToolCallOutcome.SUCCEEDED
    assert receipt.detail == "shadowed"


async def test_blast_radius_is_stopped_before_injection() -> None:
    executor = ChaosExperimentToolExecutor(
        entries=(_entry(),), promoted_ids=frozenset(), factory=ScenarioFactory()
    )
    receipt = await executor.execute(_request(mode=Mode.SHADOW, targets=["pod-a", "pod-b"]))
    assert receipt.outcome is ToolCallOutcome.STOPPED
    assert receipt.detail == "blast_radius_exceeded"


async def test_enforce_refuses_raw_harness_without_governed_executor() -> None:
    executor = ChaosExperimentToolExecutor(
        entries=(_entry(),),
        promoted_ids=frozenset({"chaos.example"}),
        factory=ScenarioFactory(),
    )

    with pytest.raises(ToolPreconditionError, match="governed impact and recovery"):
        await executor.execute(_request(mode=Mode.ENFORCE))
