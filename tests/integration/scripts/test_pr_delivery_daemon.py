from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import deque
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from scripts.automation import pr_delivery_daemon as daemon
from scripts.automation import pr_delivery_daemon_runtime as runtime
from scripts.automation import pr_delivery_daemon_support as support

pytestmark = pytest.mark.no_cover

_A = "a" * 40
_B = "b" * 40
_C = "c" * 40


def _payload(
    *,
    state: str = "OPEN",
    head: str = _A,
    base: str = _B,
    merge_state: str = "CLEAN",
    is_draft: bool = False,
    auto_merge: bool = True,
    checks: list[dict[str, str]] | None = None,
    merge_commit: str | None = None,
) -> dict[str, Any]:
    return {
        "state": state,
        "headRefName": "feat/example",
        "headRefOid": head,
        "baseRefName": "main",
        "baseRefOid": base,
        "mergeStateStatus": merge_state,
        "isDraft": is_draft,
        "autoMergeRequest": {} if auto_merge else None,
        "statusCheckRollup": checks
        if checks is not None
        else [{"status": "COMPLETED", "conclusion": "SUCCESS"}],
        "mergeCommit": {"oid": merge_commit} if merge_commit else None,
    }


class FakeRunner:
    def __init__(self, root: Path, snapshots: list[dict[str, Any]]) -> None:
        self.root = root
        self.common = root / "common"
        self.common.mkdir()
        self.git_dir = root / "git-dir"
        self.git_dir.mkdir()
        self.worktree = root / "worktree"
        self.worktree.mkdir()
        self.primary = root / "primary"
        self.primary.mkdir()
        self.snapshots = deque(snapshots)
        self.commands: list[tuple[str, ...]] = []
        self.head = _A
        self.merge_fails = False
        self.remote_sha: str | None = None
        self.remote_sha_after_push: str | None = None
        self.pushes = 0

    def __call__(
        self,
        command: Sequence[str],
        cwd: Path,
        timeout: int,
    ) -> support.CommandResult:
        del timeout
        assert cwd == self.worktree
        args = tuple(command)
        self.commands.append(args)
        if args[:3] == ("git", "rev-parse", "--path-format=absolute"):
            target = args[3]
            if target == "--git-common-dir":
                return support.CommandResult(0, f"{self.common}\n", "")
            if target == "--git-dir":
                return support.CommandResult(0, f"{self.git_dir}\n", "")
        if args == ("git", "rev-parse", "--show-toplevel"):
            return support.CommandResult(0, f"{self.worktree}\n", "")
        if args == ("git", "rev-parse", "HEAD"):
            return support.CommandResult(0, f"{self.head}\n", "")
        if args == ("git", "rev-parse", "refs/remotes/origin/main"):
            return support.CommandResult(0, f"{_B}\n", "")
        if args == ("git", "worktree", "list", "--porcelain"):
            return support.CommandResult(
                0,
                f"worktree {self.primary}\nHEAD {_B}\n\n"
                f"worktree {self.worktree}\nHEAD {self.head}\n"
                "branch refs/heads/feat/example\n",
                "",
            )
        if args == ("git", "symbolic-ref", "--short", "HEAD"):
            return support.CommandResult(0, "feat/example\n", "")
        if args[:3] == ("git", "check-ref-format", "--branch"):
            return support.CommandResult(0, f"{args[-1]}\n", "")
        if args == ("git", "status", "--porcelain"):
            return support.CommandResult(0, "", "")
        if args[:2] == ("git", "fetch"):
            return support.CommandResult(0, "", "")
        if args[:3] == ("git", "merge", "--no-edit"):
            if self.merge_fails:
                return support.CommandResult(1, "", "conflict")
            self.head = _B
            return support.CommandResult(0, "", "")
        if args[:3] == ("git", "merge", "--abort"):
            return support.CommandResult(0, "", "")
        if args[:2] == ("git", "push"):
            self.pushes += 1
            return support.CommandResult(0, "", "")
        if args[:2] == ("git", "ls-remote"):
            remote_sha = (
                self.remote_sha_after_push
                if self.pushes and self.remote_sha_after_push is not None
                else self.remote_sha or self.head
            )
            return support.CommandResult(0, f"{remote_sha}\t{args[-1]}\n", "")
        if args[:3] == ("git", "merge-base", "--is-ancestor"):
            return support.CommandResult(0, "", "")
        if args[:3] == ("gh", "pr", "view"):
            return support.CommandResult(0, json.dumps(self.snapshots.popleft()), "")
        if args[:3] == ("gh", "pr", "merge"):
            return support.CommandResult(0, "", "")
        raise AssertionError(f"unexpected command: {args}")


def _config(fake: FakeRunner, **overrides: object) -> support.DeliveryConfig:
    values: dict[str, object] = {
        "repository": "example/project",
        "pr_number": 42,
        "topic_branch": "feat/example",
        "base_branch": "main",
        "worktree": fake.worktree,
        "interval_seconds": 30,
        "total_timeout_seconds": 300,
        "no_progress_seconds": 300,
        "command_timeout_seconds": 300,
    }
    values.update(overrides)
    return support.DeliveryConfig(**values)  # type: ignore[arg-type]


def test_checks_state_requires_every_terminal_check_to_pass_or_skip() -> None:
    assert support.checks_state([]) == "pending"
    assert support.checks_state([{"status": "IN_PROGRESS", "conclusion": ""}]) == "pending"
    assert support.checks_state([{"status": "COMPLETED", "conclusion": "SUCCESS"}]) == "success"
    assert support.checks_state([{"status": "COMPLETED", "conclusion": "SKIPPED"}]) == "success"
    assert support.checks_state([{"status": "COMPLETED", "conclusion": "FAILURE"}]) == "failed"
    assert support.checks_state([{"status": "COMPLETED", "conclusion": "BOGUS"}]) == "failed"


def test_snapshot_rejects_missing_identity() -> None:
    payload = _payload()
    payload["headRefOid"] = "short"

    with pytest.raises(support.DeliveryError, match="head SHA"):
        support.snapshot(payload)


def test_config_rejects_primary_ambiguity_and_unbounded_intervals(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    config = support.DeliveryConfig(
        repository="not-a-repository",
        pr_number=0,
        topic_branch="main",
        base_branch="main",
        worktree=worktree,
        interval_seconds=1,
    )

    with pytest.raises(support.DeliveryError, match="owner/name"):
        config.validate()


def test_state_write_is_atomic_and_private(tmp_path: Path) -> None:
    path = tmp_path / "private" / "state.json"

    support.write_state(path, {"terminal": False, "phase": "watching"})

    assert support.read_state(path) == {"phase": "watching", "terminal": False}
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_daemon_verifies_a_reported_merge_on_remote_base(tmp_path: Path) -> None:
    fake = FakeRunner(tmp_path, [_payload(state="MERGED", merge_commit=_C)])
    coordinator = daemon.DeliveryDaemon(_config(fake), fake)

    assert coordinator.run() == 0

    state = support.read_state(coordinator.paths.state)
    assert state is not None
    assert state["phase"] == "merged"
    assert state["terminal"] is True
    assert state["merge_commit"] == _C
    assert ("git", "merge-base", "--is-ancestor", _C, "refs/remotes/origin/main") in fake.commands


def test_daemon_stops_without_mutating_when_a_required_check_fails(tmp_path: Path) -> None:
    failed = [{"status": "COMPLETED", "conclusion": "FAILURE"}]
    fake = FakeRunner(tmp_path, [_payload(checks=failed)])
    coordinator = daemon.DeliveryDaemon(_config(fake), fake)

    assert coordinator.run() == 4

    assert not any(command[:3] == ("git", "merge", "--no-edit") for command in fake.commands)
    assert not any(command[:3] == ("gh", "pr", "merge") for command in fake.commands)
    assert support.read_state(coordinator.paths.state)["reason"] == "required_check_failed"  # type: ignore[index]


def test_daemon_stops_without_enabling_auto_merge_for_a_draft(tmp_path: Path) -> None:
    fake = FakeRunner(tmp_path, [_payload(is_draft=True, auto_merge=False)])
    coordinator = daemon.DeliveryDaemon(_config(fake), fake)

    assert coordinator.run() == 6

    assert not any(command[:3] == ("gh", "pr", "merge") for command in fake.commands)
    assert support.read_state(coordinator.paths.state)["reason"] == "pull_request_is_draft"  # type: ignore[index]


def test_auto_merge_phase_records_enabled_state_immediately(tmp_path: Path) -> None:
    fake = FakeRunner(tmp_path, [])
    coordinator = daemon.DeliveryDaemon(_config(fake), fake)

    coordinator._enable_auto_merge(_A)

    state = support.read_state(coordinator.paths.state)
    assert state is not None
    assert state["phase"] == "auto_merge_enabled"
    assert state["auto_merge_enabled"] is True
    assert any(command[-2:] == ("--match-head-commit", _A) for command in fake.commands)


def test_daemon_locally_updates_a_behind_branch_and_restores_auto_merge(tmp_path: Path) -> None:
    fake = FakeRunner(
        tmp_path,
        [
            _payload(merge_state="BEHIND"),
            _payload(head=_B, auto_merge=False),
            _payload(state="MERGED", head=_B, merge_commit=_C),
        ],
    )
    coordinator = daemon.DeliveryDaemon(_config(fake), fake)
    coordinator._wait_for_query_slot = lambda: True  # type: ignore[method-assign]

    assert coordinator.run() == 0

    assert ("git", "merge", "--no-edit", "refs/remotes/origin/main") in fake.commands
    assert ("git", "push", "origin", "feat/example") in fake.commands
    assert any(
        command[:3] == ("gh", "pr", "merge") and "--auto" in command for command in fake.commands
    )


@pytest.mark.parametrize("delayed_observations", [1, 2])
def test_daemon_tolerates_only_bounded_delayed_head_snapshots_after_push(
    tmp_path: Path,
    delayed_observations: int,
) -> None:
    fake = FakeRunner(
        tmp_path,
        [
            _payload(merge_state="BEHIND"),
            *[_payload() for _ in range(delayed_observations)],
            _payload(state="MERGED", head=_B, merge_commit=_C),
        ],
    )
    coordinator = daemon.DeliveryDaemon(_config(fake), fake)
    coordinator._wait_for_query_slot = lambda: True  # type: ignore[method-assign]

    assert coordinator.run() == 0

    waiting_states = [
        command
        for command in fake.commands
        if command == ("git", "ls-remote", "origin", "refs/heads/feat/example")
    ]
    assert len(waiting_states) == delayed_observations + 2
    state = support.read_state(coordinator.paths.state)
    assert state is not None
    assert state["phase"] == "merged"
    assert state["projection_observations"] == delayed_observations
    assert state["pr_head_projection_pending"] is False


def test_daemon_rejects_a_third_pr_head_after_its_verified_push(tmp_path: Path) -> None:
    fake = FakeRunner(
        tmp_path,
        [_payload(merge_state="BEHIND"), _payload(head=_C)],
    )
    coordinator = daemon.DeliveryDaemon(_config(fake), fake)
    coordinator._wait_for_query_slot = lambda: True  # type: ignore[method-assign]

    with pytest.raises(support.DeliveryError, match="head differs"):
        coordinator.run()

    assert support.read_state(coordinator.paths.state)["phase"] == "failed"  # type: ignore[index]


def test_delayed_head_tolerance_stops_after_two_observations(tmp_path: Path) -> None:
    fake = FakeRunner(tmp_path, [])
    fake.head = _B
    coordinator = daemon.DeliveryDaemon(_config(fake), fake)
    coordinator.pending_head_projection = runtime._PendingHeadProjection(
        previous_head=_A,
        pushed_head=_B,
        started_at=coordinator.started,
    )
    delayed = support.snapshot(_payload())

    assert coordinator._verify_identity(delayed) is False
    assert coordinator._verify_identity(delayed) is False
    with pytest.raises(support.DeliveryError, match="did not converge"):
        coordinator._verify_identity(delayed)


def test_delayed_head_tolerance_stops_after_300_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRunner(tmp_path, [])
    fake.head = _B
    coordinator = daemon.DeliveryDaemon(_config(fake), fake)
    coordinator.pending_head_projection = runtime._PendingHeadProjection(
        previous_head=_A,
        pushed_head=_B,
        started_at=10.0,
    )
    monkeypatch.setattr(runtime.time, "monotonic", lambda: 310.01)

    with pytest.raises(support.DeliveryError, match="did not converge"):
        coordinator._verify_identity(support.snapshot(_payload()))


def test_daemon_keeps_the_existing_total_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime.time, "monotonic", lambda: 256.3)
    fake = FakeRunner(tmp_path, [_payload()])
    coordinator = daemon.DeliveryDaemon(_config(fake), fake)
    monkeypatch.setattr(
        runtime.time,
        "monotonic",
        lambda: coordinator.started + coordinator.config.total_timeout_seconds,
    )

    assert coordinator.run() == 2

    state = support.read_state(coordinator.paths.state)
    assert state is not None
    assert state["phase"] == "timeout"
    assert state["reason"] == "total_timeout"
    assert not any(command[:3] == ("gh", "pr", "view") for command in fake.commands)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("local", "local worktree head changed"),
        ("remote", "remote topic branch changed"),
        ("dirty", "delivery worktree became dirty"),
    ],
)
def test_delayed_head_tolerance_rechecks_local_remote_and_clean_state(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    fake = FakeRunner(tmp_path, [])
    fake.head = _C if mutation == "local" else _B
    if mutation == "remote":
        fake.remote_sha = _C
    original = fake.__call__

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> support.CommandResult:
        if mutation == "dirty" and tuple(command) == ("git", "status", "--porcelain"):
            return support.CommandResult(0, " M changed.py\n", "")
        return original(command, cwd, timeout)

    coordinator = daemon.DeliveryDaemon(_config(fake), runner)
    coordinator.pending_head_projection = runtime._PendingHeadProjection(
        previous_head=_A,
        pushed_head=_B,
        started_at=coordinator.started,
    )

    with pytest.raises(support.DeliveryError, match=message):
        coordinator._verify_identity(support.snapshot(_payload()))


def test_daemon_aborts_a_conflicting_local_base_merge(tmp_path: Path) -> None:
    fake = FakeRunner(tmp_path, [_payload(merge_state="BEHIND")])
    fake.merge_fails = True
    coordinator = daemon.DeliveryDaemon(_config(fake), fake)

    with pytest.raises(support.DeliveryError, match="base merge conflicted"):
        coordinator.run()

    assert ("git", "merge", "--abort") in fake.commands
    assert not any(command[:2] == ("git", "push") for command in fake.commands)
    assert support.read_state(coordinator.paths.state)["phase"] == "failed"  # type: ignore[index]


def test_daemon_rejects_a_pushed_sha_mismatch(tmp_path: Path) -> None:
    fake = FakeRunner(tmp_path, [_payload(merge_state="BEHIND")])
    fake.remote_sha_after_push = _C
    coordinator = daemon.DeliveryDaemon(_config(fake), fake)

    with pytest.raises(support.DeliveryError, match="does not match"):
        coordinator.run()

    assert not any(command[:3] == ("gh", "pr", "merge") for command in fake.commands)
    assert support.read_state(coordinator.paths.state)["terminal"] is True  # type: ignore[index]


def test_daemon_rejects_a_primary_checkout(tmp_path: Path) -> None:
    fake = FakeRunner(tmp_path, [_payload()])
    fake.primary = fake.worktree
    coordinator = daemon.DeliveryDaemon(_config(fake), fake)

    with pytest.raises(support.DeliveryError, match="primary checkout"):
        coordinator.run()


def test_daemon_rejects_topic_branch_owned_by_a_sibling_worktree(tmp_path: Path) -> None:
    fake = FakeRunner(tmp_path, [_payload()])
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    original = fake.__call__

    def duplicate_branch_runner(
        command: Sequence[str],
        cwd: Path,
        timeout: int,
    ) -> support.CommandResult:
        if tuple(command) == ("git", "worktree", "list", "--porcelain"):
            listing = original(command, cwd, timeout).stdout
            return support.CommandResult(
                0,
                f"{listing}\nworktree {sibling}\nHEAD {_C}\nbranch refs/heads/feat/example\n",
                "",
            )
        return original(command, cwd, timeout)

    coordinator = daemon.DeliveryDaemon(_config(fake), duplicate_branch_runner)

    with pytest.raises(support.DeliveryError, match="another worktree"):
        coordinator.run()


def test_start_reuses_a_live_nonterminal_daemon(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRunner(tmp_path, [])
    config = _config(fake)
    paths = daemon._paths(fake, config)
    support.write_state(paths.state, {"pid": os.getpid(), "terminal": False})
    monkeypatch.setattr(daemon, "_is_matching_process", lambda pid, selected: True)

    assert daemon._start(config, fake) == 0

    assert json.loads(capsys.readouterr().out) == {
        "event": "reused",
        "pid": os.getpid(),
        "state": str(paths.state),
    }


def test_process_reuse_requires_the_exact_daemon_command(tmp_path: Path) -> None:
    fake = FakeRunner(tmp_path, [])

    assert support.is_matching_process(os.getpid(), _config(fake)) is False


def test_pr_delivery_skill_owns_the_bounded_daemon_contract() -> None:
    root = Path(__file__).resolve().parents[3]
    skill = (root / ".github/skills/pr-delivery/SKILL.md").read_text(encoding="utf-8")
    instructions = (root / ".github/copilot-instructions.md").read_text(encoding="utf-8")
    conventions = (root / ".github/instructions/coding-conventions.instructions.md").read_text(
        encoding="utf-8"
    )

    for text in (skill, instructions, conventions):
        assert "scripts/automation/pr_delivery_daemon.py" in text
    assert "If the canonical\nscript is absent, first create it" in skill
    assert "The only\n   polling exception" in instructions
    assert "MUST NOT diagnose or\n  repair CI" in conventions


def test_daemon_entry_point_runs_by_repository_path() -> None:
    root = Path(__file__).resolve().parents[3]

    result = subprocess.run(
        [sys.executable, "scripts/automation/pr_delivery_daemon.py", "--help"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "{start,run,status}" in result.stdout
