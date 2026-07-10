"""Validation + property edge cases for chaos, IRP, knowledge, report-feed."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.chaos.contract import ExperimentOutcome, ExperimentResult, FaultScenario
from fdai.shared.contracts.models import Mode

_T = datetime(2026, 7, 10, tzinfo=UTC)


def test_fault_scenario_rejects_empty_scenario_id() -> None:
    with pytest.raises(ValueError, match="scenario_id"):
        FaultScenario(
            scenario_id="",
            fault_type="cpu",
            description="d",
            target_selector="t",
            expected_signal="s",
            blast_radius_cap=1,
            duration_seconds=1.0,
        )


def test_fault_scenario_rejects_empty_fault_type() -> None:
    with pytest.raises(ValueError, match="fault_type"):
        FaultScenario(
            scenario_id="x",
            fault_type="",
            description="d",
            target_selector="t",
            expected_signal="s",
            blast_radius_cap=1,
            duration_seconds=1.0,
        )


def test_fault_scenario_rejects_nonpositive_duration() -> None:
    with pytest.raises(ValueError, match="duration_seconds"):
        FaultScenario(
            scenario_id="x",
            fault_type="cpu",
            description="d",
            target_selector="t",
            expected_signal="s",
            blast_radius_cap=1,
            duration_seconds=0.0,
        )


def test_experiment_result_reverted_when_not_injected() -> None:
    result = ExperimentResult(
        experiment_id="e",
        scenario_id="s",
        mode=Mode.SHADOW,
        targets=("t",),
        outcome=ExperimentOutcome.SHADOWED,
        expected_signal="sig",
        detected=False,
        started_at=_T,
        ended_at=_T,
        injected=False,
        stopped=False,
    )
    assert result.reverted is True
