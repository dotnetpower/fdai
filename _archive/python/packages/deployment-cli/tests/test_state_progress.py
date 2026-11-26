from __future__ import annotations

import fcntl
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai_deployment_cli.compiler import GENESIS_MANIFEST_VERSION
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
    _acquire_exclusive_lock,
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


def test_journal_replays_legacy_v1_events_with_their_manifest_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "run.jsonl"
    legacy = replace(
        _event(1, GENESIS_HASH),
        evidence_digest=None,
        schema_version="fdai.provision-event.v1",
    )
    path.write_text(json.dumps(legacy.to_mapping()) + "\n", encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setattr("fdai_deployment_cli.state.GENESIS_MANIFEST_VERSION", "genesis.v2")

    replayed = read_journal(path)

    assert replayed == (replace(legacy, manifest_version="genesis.v1"),)
    assert replayed[0].manifest_version == "genesis.v1"
    assert "manifest_version" not in legacy.to_mapping()


def test_journal_v2_seals_manifest_version() -> None:
    event = replace(
        _event(1, GENESIS_HASH),
        evidence_digest=None,
        schema_version="fdai.provision-event.v2",
    )

    assert event.to_mapping()["schema_version"] == "fdai.provision-event.v2"
    assert event.to_mapping()["manifest_version"] == GENESIS_MANIFEST_VERSION
    assert "evidence_digest" not in event.to_mapping()


def test_journal_replays_but_never_appends_legacy_schema(tmp_path: Path) -> None:
    event = replace(
        _event(1, GENESIS_HASH),
        evidence_digest=None,
        schema_version="fdai.provision-event.v2",
    )

    with pytest.raises(ValueError, match="MUST use schema v3"):
        append_event(tmp_path / "run.jsonl", event)


def test_legacy_journal_is_replay_only(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    legacy = replace(
        _event(1, GENESIS_HASH),
        evidence_digest=None,
        schema_version="fdai.provision-event.v2",
    )
    path.write_text(json.dumps(legacy.to_mapping()) + "\n", encoding="utf-8")
    path.chmod(0o600)
    next_event = replace(
        _event(2, legacy.digest),
        stage="inspect-context",
        evidence_digest="b" * 64,
    )

    assert read_journal(path) == (legacy,)
    with pytest.raises(ValueError, match="replay-only"):
        append_event(path, next_event)


def test_journal_v3_binds_terminal_stage_evidence(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    completed = replace(
        _event(1, GENESIS_HASH, RunState.COMPLETED),
        stage="inspect-context",
        evidence_digest="b" * 64,
    )

    append_event(path, completed)

    assert read_journal(path)[0].evidence_digest == "b" * 64


def test_journal_v3_rejects_completed_stage_without_receipt(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="completed requires receipt evidence"):
        append_event(
            tmp_path / "run.jsonl",
            _event(1, GENESIS_HASH, RunState.COMPLETED),
        )


def test_journal_reader_never_follows_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.jsonl"
    target.write_text("", encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "run.jsonl"
    link.symlink_to(target)

    with pytest.raises(OSError):
        read_journal(link)


def test_journal_reader_rejects_fifo_without_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fifo = tmp_path / "run.jsonl"
    os.mkfifo(fifo, mode=0o600)
    real_open = os.open

    def open_nonblocking(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if path == fifo.name:
            assert flags & os.O_NONBLOCK
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", open_nonblocking)
    with pytest.raises(PermissionError, match="regular file"):
        read_journal(fifo)


def test_journal_lock_acquisition_has_a_monotonic_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def always_contended(descriptor: int, operation: int) -> None:
        assert descriptor == 42
        assert operation & fcntl.LOCK_NB
        raise BlockingIOError

    times = iter((10.0, 11.0))
    monkeypatch.setattr("fdai_deployment_cli.state.fcntl.flock", always_contended)
    monkeypatch.setattr("fdai_deployment_cli.state.time.monotonic", lambda: next(times))

    with pytest.raises(TimeoutError, match="lock timed out"):
        _acquire_exclusive_lock(42, timeout_seconds=1.0)


def test_journal_never_follows_parent_directory_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(target, target_is_directory=True)

    with pytest.raises(OSError):
        append_event(linked / "run.jsonl", _event(1, GENESIS_HASH))
    assert not (target / "run.jsonl").exists()


def test_journal_never_follows_earlier_ancestor_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    nested = target / "nested"
    nested.mkdir(parents=True, mode=0o700)
    target.chmod(0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(target, target_is_directory=True)

    with pytest.raises(OSError):
        append_event(linked / "nested" / "run.jsonl", _event(1, GENESIS_HASH))
    assert not (nested / "run.jsonl").exists()


def test_journal_descriptor_traversal_creates_private_parents(tmp_path: Path) -> None:
    path = tmp_path / "one" / "two" / "run.jsonl"

    append_event(path, _event(1, GENESIS_HASH))

    assert (tmp_path / "one").stat().st_mode & 0o777 == 0o700
    assert (tmp_path / "one" / "two").stat().st_mode & 0o777 == 0o700
    assert read_journal(path) == (_event(1, GENESIS_HASH),)


def test_journal_rejects_ready_without_readiness_evidence(tmp_path: Path) -> None:
    path = tmp_path / "runs" / "run.jsonl"
    with pytest.raises(ValueError, match="ready requires"):
        append_event(path, _event(1, GENESIS_HASH, RunState.READY))


def test_journal_replay_rejects_ready_without_readiness_evidence(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    event = _event(1, GENESIS_HASH, RunState.READY)
    path.write_text(json.dumps(event.to_mapping()) + "\n", encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(ValueError, match="ready requires"):
        read_journal(path)


def test_journal_rejects_out_of_order_completed_stage(tmp_path: Path) -> None:
    path = tmp_path / "runs" / "run.jsonl"
    completed = ProvisionEvent(
        run_id="run.test",
        context_digest="a" * 64,
        sequence=1,
        stage="system-readiness",
        attempt=1,
        state=RunState.COMPLETED,
        occurred_at="2026-08-29T00:00:00+00:00",
        previous_digest=GENESIS_HASH,
        evidence_digest="b" * 64,
    )
    with pytest.raises(ValueError, match="sealed manifest order"):
        append_event(path, completed)


def test_journal_rejects_event_after_terminal_state(tmp_path: Path) -> None:
    path = tmp_path / "runs" / "run.jsonl"
    first = _event(1, GENESIS_HASH, RunState.FAILED)
    append_event(path, first)
    with pytest.raises(ValueError, match="terminal"):
        append_event(path, _event(2, first.digest, RunState.PLANNING))


def test_journal_rejects_event_after_blocked_state(tmp_path: Path) -> None:
    path = tmp_path / "runs" / "run.jsonl"
    first = _event(1, GENESIS_HASH, RunState.BLOCKED)
    append_event(path, first)
    with pytest.raises(ValueError, match="terminal"):
        append_event(path, _event(2, first.digest, RunState.PLANNING))


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


def test_progress_optional_counters_are_monotonic_once_observed() -> None:
    started = datetime(2026, 8, 29, tzinfo=UTC)

    def snapshot(
        sequence: int,
        *,
        resources: tuple[int, int] | None,
        pages: tuple[int, int] | None,
    ) -> ProgressSnapshot:
        return ProgressSnapshot(
            sequence=sequence,
            state=ProgressState.RUNNING,
            stages_completed=1,
            stages_total=10,
            checkpoints_completed=2,
            checkpoints_total=20,
            started_at=started.isoformat(),
            last_progress_at=(started + timedelta(seconds=sequence)).isoformat(),
            resources_observed=None if resources is None else resources[0],
            resources_expected=None if resources is None else resources[1],
            pages_completed=None if pages is None else pages[0],
            pages_expected=None if pages is None else pages[1],
        )

    initial = snapshot(1, resources=None, pages=None)
    observed = snapshot(2, resources=(4, 10), pages=(2, 5))
    validate_progression(initial, observed)
    validate_progression(observed, snapshot(3, resources=(5, 12), pages=(3, 7)))

    with pytest.raises(ValueError, match="resources progress MUST NOT disappear"):
        validate_progression(observed, snapshot(3, resources=None, pages=(3, 5)))
    with pytest.raises(ValueError, match="resources progress MUST NOT regress"):
        validate_progression(observed, snapshot(3, resources=(3, 10), pages=(3, 5)))
    with pytest.raises(ValueError, match="pages progress MUST NOT regress"):
        validate_progression(observed, snapshot(3, resources=(5, 10), pages=(2, 4)))


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
