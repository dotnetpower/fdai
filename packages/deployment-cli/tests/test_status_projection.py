from __future__ import annotations

from dataclasses import replace

import pytest

from fdai_deployment_cli.compiler import GENESIS_ENTRY_IDS, GENESIS_MANIFEST_VERSION
from fdai_deployment_cli.state import GENESIS_HASH, ProvisionEvent, RunState
from fdai_deployment_cli.status_projection import project_status


def _event(
    sequence: int,
    stage: str,
    state: RunState,
    *,
    previous: str = GENESIS_HASH,
) -> ProvisionEvent:
    return ProvisionEvent(
        run_id="run.test",
        context_digest="a" * 64,
        sequence=sequence,
        stage=stage,
        attempt=1,
        state=state,
        occurred_at=f"2026-08-31T00:00:0{sequence}+00:00",
        previous_digest=previous,
        evidence_digest="b" * 64 if state in {RunState.COMPLETED, RunState.READY} else None,
        manifest_version=GENESIS_MANIFEST_VERSION,
    )


def test_status_separates_stage_completion_from_terminal_readiness() -> None:
    database = _event(1, "database", RunState.COMPLETED)
    semantic = _event(2, "semantic-defaults", RunState.COMPLETED, previous=database.digest)
    console = _event(3, "console", RunState.COMPLETED, previous=semantic.digest)

    status = project_status((database, semantic, console))

    assert status["type"] == "provision.snapshot"
    assert status["ready"] is False
    assert status["readiness"] == {
        "database": True,
        "semantic": True,
        "models": False,
        "runtime": True,
        "inventory": False,
        "system": False,
    }
    stages = {item["id"]: item["status"] for item in status["stages"]}  # type: ignore[index]
    assert stages["console"] == "completed"
    assert stages["initial-inventory"] == "pending"


def test_status_marks_ready_only_from_the_ready_event() -> None:
    completed = _event(1, "system-readiness", RunState.COMPLETED)
    ready = _event(2, "system-readiness", RunState.READY, previous=completed.digest)

    assert project_status((completed,))["ready"] is False
    assert project_status((completed, ready))["ready"] is True


def test_status_rejects_mixed_runs() -> None:
    first = _event(1, GENESIS_ENTRY_IDS[0], RunState.PLANNING)
    second = replace(first, run_id="run.other", sequence=2)

    with pytest.raises(ValueError, match="multiple run ids"):
        project_status((first, second))


def test_latest_failure_overrides_prior_stage_completion() -> None:
    completed = _event(1, "database", RunState.COMPLETED)
    failed = _event(2, "database", RunState.FAILED, previous=completed.digest)

    status = project_status((completed, failed))
    stages = {item["id"]: item["status"] for item in status["stages"]}  # type: ignore[index]

    assert status["state"] == "failed"
    assert stages["database"] == "failed"
