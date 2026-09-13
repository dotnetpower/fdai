from __future__ import annotations

import os
from pathlib import Path

import pytest
from fdai.core.conversation_assurance import (
    CampaignHoldError,
    CampaignState,
    PantheonCampaignController,
    PantheonCensusCase,
    PantheonDiagnosticVerdict,
    PantheonRubric,
    PantheonRubricResult,
    PantheonTurnDiagnostic,
    PrivateJsonlLedger,
    T2Expectation,
    plan_campaign_series,
    touch_private_marker,
)


def _case(index: int) -> PantheonCensusCase:
    return PantheonCensusCase(
        case_id=f"case-{index}",
        suite="agent",
        locale="en",
        question=f"Odin, explain case {index}.",
        expected_primary_agent="Odin",
        expected_routing_method="explicit",
        allowed_contributors=(),
        expected_handoff=False,
        expected_handoff_owner=None,
        t2_expectation=T2Expectation.FORBIDDEN,
    )


def _diagnostic(case: PantheonCensusCase) -> PantheonTurnDiagnostic:
    results = tuple(
        PantheonRubricResult(
            item_id=index,
            rubric=rubric,
            passed=True,
            reason="observed_pass",
        )
        for index, rubric in enumerate(PantheonRubric, start=1)
    )
    return PantheonTurnDiagnostic(
        case_id=case.case_id,
        agent="Odin",
        locale=case.locale,
        score=30,
        verdict=PantheonDiagnosticVerdict.PASS,
        results=results,
        hard_zero_violations=(),
        trace_receipt_digest="a" * 64,
    )


class _Evaluator:
    def __init__(self, *, hold_at: int | None = None) -> None:
        self.calls = 0
        self.hold_at = hold_at

    async def evaluate(
        self,
        case: PantheonCensusCase,
        *,
        campaign_id: str,
    ) -> PantheonTurnDiagnostic:
        assert campaign_id.startswith("campaign-")
        self.calls += 1
        if self.calls == self.hold_at:
            raise CampaignHoldError("provider_unavailable")
        return _diagnostic(case)


async def test_child_campaign_is_bounded_and_private(tmp_path: Path) -> None:
    evaluator = _Evaluator()
    controller = PantheonCampaignController(state_root=tmp_path, evaluator=evaluator)

    result = await controller.run_child(tuple(_case(index) for index in range(20)))

    assert result.state is CampaignState.COMPLETED
    assert result.evaluated == 20
    assert evaluator.calls == 20
    assert (os.stat(tmp_path / "campaigns.jsonl").st_mode & 0o777) == 0o600
    assert (os.stat(tmp_path / "evaluations.jsonl").st_mode & 0o777) == 0o600
    assert len(PrivateJsonlLedger(tmp_path / "evaluations.jsonl").read()) == 20


async def test_child_campaign_rejects_more_than_twenty_questions(tmp_path: Path) -> None:
    controller = PantheonCampaignController(state_root=tmp_path, evaluator=_Evaluator())

    with pytest.raises(ValueError, match="between 1 and 20"):
        await controller.run_child(tuple(_case(index) for index in range(21)))


async def test_series_stops_after_first_held_child(tmp_path: Path) -> None:
    evaluator = _Evaluator(hold_at=22)
    controller = PantheonCampaignController(state_root=tmp_path, evaluator=evaluator)

    results = await controller.run_series(tuple(_case(index) for index in range(45)))

    assert len(results) == 2
    assert results[0].state is CampaignState.COMPLETED
    assert results[1].state is CampaignState.HELD
    assert results[1].evaluated == 1
    assert evaluator.calls == 22
    series_rows = tuple(
        row
        for row in PrivateJsonlLedger(tmp_path / "campaigns.jsonl").read()
        if row["event"] in {"series_started", "series_completed"}
    )
    assert [row["event"] for row in series_rows] == ["series_started", "series_completed"]
    assert series_rows[0]["corpus_digest"] == series_rows[1]["corpus_digest"]
    assert series_rows[1]["state"] == "held"
    assert series_rows[1]["evaluated"] == 21


def test_thousand_question_series_plans_fifty_bounded_children() -> None:
    plan = plan_campaign_series(tuple(_case(index) for index in range(1_000)))

    assert plan.question_count == 1_000
    assert plan.child_count == 50
    assert plan.child_sizes == (20,) * 50
    assert len(plan.corpus_digest) == 64


def test_series_plan_rejects_duplicate_case_ids() -> None:
    with pytest.raises(ValueError, match="unique case ids"):
        plan_campaign_series((_case(1), _case(1)))


async def test_stop_file_prevents_measurement(tmp_path: Path) -> None:
    evaluator = _Evaluator()
    controller = PantheonCampaignController(state_root=tmp_path, evaluator=evaluator)
    (tmp_path / "STOP").touch()

    result = await controller.run_child((_case(1),))

    assert result.state is CampaignState.STOPPED
    assert result.evaluated == 0
    assert evaluator.calls == 0


def test_ledger_rejects_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target.jsonl"
    target.touch()
    link = tmp_path / "ledger.jsonl"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="symlink"):
        PrivateJsonlLedger(link).append({"event": "test"})


def test_ledger_rejects_symlinked_parent_directory(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(OSError):
        PrivateJsonlLedger(link / "ledger.jsonl").append({"event": "test"})


def test_stop_marker_rejects_symlinked_leaf(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.touch()
    marker = tmp_path / "STOP"
    marker.symlink_to(target)

    with pytest.raises(OSError):
        touch_private_marker(marker)
