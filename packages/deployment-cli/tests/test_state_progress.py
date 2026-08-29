from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai_deployment_cli.progress import (
    InventoryClosure,
    ProgressSnapshot,
    ProgressState,
    validate_progression,
)
from fdai_deployment_cli.state import (
    GENESIS_HASH,
    ProvisionEvent,
    ResumeAction,
    RunState,
    append_event,
    read_journal,
    resume_action,
)


def _event(sequence: int, previous: str, state: RunState = RunState.PLANNING) -> ProvisionEvent:
    return ProvisionEvent(
        run_id="run.test",
        context_digest="a" * 64,
        sequence=sequence,
        stage="foundation",
        attempt=1,
        state=state,
        occurred_at="2026-08-29T00:00:00+00:00",
        previous_digest=previous,
    )


def test_journal_is_hash_chained_and_private(tmp_path: Path) -> None:
    path = tmp_path / "runs" / "run.jsonl"
    first = _event(1, GENESIS_HASH)
    append_event(path, first)
    second = _event(2, first.digest, RunState.WAITING)
    append_event(path, second)

    assert path.stat().st_mode & 0o777 == 0o600
    assert read_journal(path) == (first, second)


def test_journal_rejects_sequence_gap_and_tamper(tmp_path: Path) -> None:
    path = tmp_path / "runs" / "run.jsonl"
    first = _event(1, GENESIS_HASH)
    append_event(path, first)
    with pytest.raises(ValueError, match="continue"):
        append_event(path, _event(3, first.digest))

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["stage"] = "application"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(ValueError, match="digest"):
        read_journal(path)


def test_journal_reader_never_follows_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.jsonl"
    target.write_text("", encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "run.jsonl"
    link.symlink_to(target)

    with pytest.raises(OSError):
        read_journal(link)


@pytest.mark.parametrize(
    ("claim", "receipt", "failed", "expected"),
    (
        ("absent", "absent", False, ResumeAction.REPLAN),
        ("present", "absent", False, ResumeAction.RESUME_VERIFICATION),
        ("present", "present", False, ResumeAction.COMPLETE),
        ("present", "absent", True, ResumeAction.REVIEW),
    ),
)
def test_resume_decision_never_retries_ambiguous_apply(
    claim: str,
    receipt: str,
    failed: bool,
    expected: ResumeAction,
) -> None:
    assert resume_action(claim=claim, receipt=receipt, failed=failed) is expected


def test_resume_rejects_failed_state_after_terminal_receipt() -> None:
    with pytest.raises(ValueError, match="cannot also be failed"):
        resume_action(claim="present", receipt="present", failed=True)


def _progress(
    sequence: int,
    stages: int,
    checkpoints: int,
    *,
    state: ProgressState = ProgressState.RUNNING,
    offset_seconds: int = 0,
) -> ProgressSnapshot:
    started = datetime(2026, 8, 29, tzinfo=UTC)
    return ProgressSnapshot(
        sequence=sequence,
        state=state,
        stages_completed=stages,
        stages_total=10,
        checkpoints_completed=checkpoints,
        checkpoints_total=20,
        started_at=started.isoformat(),
        last_progress_at=(started + timedelta(seconds=offset_seconds)).isoformat(),
    )


def test_progress_is_monotonic_and_complete_only_at_closure() -> None:
    first = _progress(1, 1, 2)
    second = _progress(2, 2, 3, offset_seconds=10)
    validate_progression(first, second)
    assert second.fraction > first.fraction
    assert _progress(3, 10, 20, state=ProgressState.COMPLETE).fraction == 1


def test_progress_rejects_regression_and_changed_totals() -> None:
    first = _progress(1, 2, 4)
    with pytest.raises(ValueError, match="regress"):
        validate_progression(first, _progress(2, 1, 4))
    changed = ProgressSnapshot(
        sequence=2,
        state=ProgressState.RUNNING,
        stages_completed=2,
        stages_total=11,
        checkpoints_completed=5,
        checkpoints_total=20,
        started_at="2026-08-29T00:00:00+00:00",
        last_progress_at="2026-08-29T00:00:10+00:00",
    )
    with pytest.raises(ValueError, match="totals"):
        validate_progression(first, changed)


def test_inventory_closure_requires_full_independent_readback() -> None:
    complete = InventoryClosure(
        subscription_root=True,
        resource_type_filter=False,
        final_fence=True,
        provider_coverage_complete=True,
        truncated=False,
        active_generation_matches=True,
        overlay_open=False,
        child_sources_complete=True,
        observer_distinct=True,
    )
    assert complete.complete
    assert not replace(complete, observer_distinct=False).complete
