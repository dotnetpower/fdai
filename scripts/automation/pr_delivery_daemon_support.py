"""Validated inputs, command boundaries, and private state for PR delivery."""

from __future__ import annotations

import dataclasses
import json
import os
import re
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_FAILED_CONCLUSIONS = {
    "ACTION_REQUIRED",
    "CANCELLED",
    "FAILURE",
    "STALE",
    "STARTUP_FAILURE",
    "TIMED_OUT",
}
_SUCCESS_CONCLUSIONS = {"NEUTRAL", "SKIPPED", "SUCCESS"}


class DeliveryError(RuntimeError):
    """Report a fail-closed delivery condition without exposing command output."""


@dataclasses.dataclass(frozen=True)
class CommandResult:
    """Contain the bounded, captured result of one local command."""

    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str], Path, int], CommandResult]


@dataclasses.dataclass(frozen=True)
class DeliveryConfig:
    """Pin one daemon invocation to a repository, PR, branches, and worktree."""

    repository: str
    pr_number: int
    topic_branch: str
    base_branch: str
    worktree: Path
    remote: str = "origin"
    merge_method: str = "squash"
    interval_seconds: int = 60
    total_timeout_seconds: int = 3600
    no_progress_seconds: int = 1200
    command_timeout_seconds: int = 900

    def validate(self) -> None:
        """Reject unbounded or ambiguous coordinator inputs."""
        if not _REPO_RE.fullmatch(self.repository):
            raise DeliveryError("repository must use the owner/name form")
        if self.pr_number < 1:
            raise DeliveryError("pr-number must be positive")
        if self.topic_branch == self.base_branch:
            raise DeliveryError("topic and base branches must differ")
        for label, value in (
            ("topic-branch", self.topic_branch),
            ("base-branch", self.base_branch),
            ("remote", self.remote),
        ):
            if not value or value.startswith("-") or any(char.isspace() for char in value):
                raise DeliveryError(f"{label} is invalid")
        if self.merge_method not in {"merge", "rebase", "squash"}:
            raise DeliveryError("merge-method is invalid")
        if not 30 <= self.interval_seconds <= 300:
            raise DeliveryError("interval-seconds must be between 30 and 300")
        if not 300 <= self.total_timeout_seconds <= 7200:
            raise DeliveryError("total-timeout-seconds must be between 300 and 7200")
        if not 300 <= self.no_progress_seconds <= self.total_timeout_seconds:
            raise DeliveryError("no-progress-seconds must be bounded by the total timeout")
        if not 30 <= self.command_timeout_seconds <= self.total_timeout_seconds:
            raise DeliveryError("command-timeout-seconds must be bounded by the total timeout")
        if not self.worktree.is_absolute() or not self.worktree.is_dir():
            raise DeliveryError("worktree must be an existing absolute directory")


@dataclasses.dataclass(frozen=True)
class Paths:
    """Name private state, lock, and log files under the Git common directory."""

    directory: Path
    state: Path
    lock: Path
    launch_lock: Path
    log: Path


@dataclasses.dataclass(frozen=True)
class PullRequestSnapshot:
    """Retain only the GitHub fields required for deterministic delivery routing."""

    state: str
    head_branch: str
    head_sha: str
    base_branch: str
    base_sha: str
    merge_state: str
    is_draft: bool
    auto_merge_enabled: bool
    checks_state: str
    merge_commit: str | None

    @property
    def fingerprint(self) -> tuple[object, ...]:
        """Return the fields whose change counts as external progress."""
        return dataclasses.astuple(self)


def utc_now() -> str:
    """Return one stable UTC timestamp for private coordinator state."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
    """Run one argument-only command with prompts disabled and bounded output."""
    env = os.environ.copy()
    env.update({"GH_PROMPT_DISABLED": "1", "GIT_TERMINAL_PROMPT": "0"})
    try:
        completed = subprocess.run(  # noqa: S603 - arguments are validated and never use a shell.
            list(command),
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise DeliveryError(f"command timed out: {command[0]}") from error
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def require_success(result: CommandResult, label: str) -> str:
    """Return captured stdout or fail without echoing potentially sensitive output."""
    if result.returncode != 0:
        raise DeliveryError(f"{label} failed with exit code {result.returncode}")
    return result.stdout.strip()


def git(runner: Runner, config: DeliveryConfig, *arguments: str, timeout: int = 60) -> str:
    """Run one bounded Git operation in the pinned delivery worktree."""
    return require_success(
        runner(("git", *arguments), config.worktree, timeout),
        f"git {arguments[0]}",
    )


def common_git_dir(runner: Runner, config: DeliveryConfig) -> Path:
    """Resolve and validate the shared Git metadata directory."""
    value = git(runner, config, "rev-parse", "--path-format=absolute", "--git-common-dir")
    path = Path(value)
    if not path.is_absolute() or not path.is_dir():
        raise DeliveryError("Git common directory is unavailable")
    return path


def delivery_paths(runner: Runner, config: DeliveryConfig) -> Paths:
    """Build private per-PR paths outside the worktree."""
    directory = common_git_dir(runner, config) / "fdai-pr-delivery"
    stem = f"pr-{config.pr_number}"
    return Paths(
        directory=directory,
        state=directory / f"{stem}.json",
        lock=directory / f"{stem}.lock",
        launch_lock=directory / f"{stem}.launch.lock",
        log=directory / f"{stem}.log",
    )


def write_state(path: Path, payload: dict[str, object]) -> None:
    """Atomically persist private state with owner-only permissions."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def read_state(path: Path) -> dict[str, Any] | None:
    """Read one private state object or report that it does not exist."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as error:
        raise DeliveryError("delivery state is unreadable") from error
    if not isinstance(payload, dict):
        raise DeliveryError("delivery state must be an object")
    return payload


def is_matching_process(pid: object, config: DeliveryConfig) -> bool:
    """Reject stale or recycled PIDs before reusing a daemon."""
    if not isinstance(pid, int) or pid < 1:
        return False
    try:
        arguments = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    decoded = [argument.decode(errors="replace") for argument in arguments if argument]
    script = str(Path(__file__).with_name("pr_delivery_daemon.py").resolve())
    required = {script, "run", str(config.pr_number), config.topic_branch, str(config.worktree)}
    return required.issubset(decoded)


def checks_state(checks: object) -> str:
    """Reduce Check Runs to pending, success, or failure without interpreting names."""
    if not isinstance(checks, list) or not checks:
        return "pending"
    pending = False
    for check in checks:
        if not isinstance(check, dict):
            return "failed"
        status = str(check.get("status", "")).upper()
        conclusion = str(check.get("conclusion", "")).upper()
        if conclusion in _FAILED_CONCLUSIONS:
            return "failed"
        if status != "COMPLETED" or not conclusion:
            pending = True
        elif conclusion not in _SUCCESS_CONCLUSIONS:
            return "failed"
    return "pending" if pending else "success"


def snapshot(payload: object) -> PullRequestSnapshot:
    """Validate the minimum GitHub PR response used by the coordinator."""
    if not isinstance(payload, dict):
        raise DeliveryError("pull request response must be an object")
    merge_commit = payload.get("mergeCommit")
    merge_oid = merge_commit.get("oid") if isinstance(merge_commit, dict) else None
    values = {
        "state": str(payload.get("state", "")).upper(),
        "head_branch": str(payload.get("headRefName", "")),
        "head_sha": str(payload.get("headRefOid", "")),
        "base_branch": str(payload.get("baseRefName", "")),
        "base_sha": str(payload.get("baseRefOid", "")),
        "merge_state": str(payload.get("mergeStateStatus", "")).upper(),
    }
    if values["state"] not in {"CLOSED", "MERGED", "OPEN"}:
        raise DeliveryError("pull request state is unavailable")
    if values["state"] != "CLOSED" and not _SHA_RE.fullmatch(values["head_sha"]):
        raise DeliveryError("pull request head SHA is unavailable")
    if not _SHA_RE.fullmatch(values["base_sha"]):
        raise DeliveryError("pull request base SHA is unavailable")
    if merge_oid is not None and not _SHA_RE.fullmatch(str(merge_oid)):
        raise DeliveryError("pull request merge SHA is invalid")
    return PullRequestSnapshot(
        **values,
        is_draft=payload.get("isDraft") is True,
        auto_merge_enabled=isinstance(payload.get("autoMergeRequest"), dict),
        checks_state=checks_state(payload.get("statusCheckRollup")),
        merge_commit=str(merge_oid) if merge_oid is not None else None,
    )
