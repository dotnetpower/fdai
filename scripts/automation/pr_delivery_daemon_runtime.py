"""Lock-owned lifecycle for one bounded pull request delivery coordinator."""

from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

from scripts.automation.pr_delivery_daemon_support import (
    DeliveryConfig,
    DeliveryError,
    PullRequestSnapshot,
    Runner,
    default_runner,
    delivery_paths,
    git,
    require_success,
    snapshot,
    utc_now,
    write_state,
)

_MAX_DELAYED_HEAD_OBSERVATIONS = 2
_MAX_DELAYED_HEAD_SECONDS = 300.0


@dataclass(frozen=True)
class _PendingHeadProjection:
    """Bound one GitHub projection delay to the coordinator's verified push."""

    previous_head: str
    pushed_head: str
    started_at: float
    observations: int = 0


class DeliveryDaemon:
    """Advance one pull request until a terminal or bounded wait outcome."""

    def __init__(self, config: DeliveryConfig, runner: Runner = default_runner) -> None:
        config.validate()
        self.config = config
        self.runner = runner
        self.paths = delivery_paths(runner, config)
        self.stop_event = threading.Event()
        self.started = time.monotonic()
        self.total_deadline = self.started + config.total_timeout_seconds
        self.last_progress = self.started
        self.last_fingerprint: tuple[object, ...] | None = None
        self.last_query: float | None = None
        self.pending_head_projection: _PendingHeadProjection | None = None
        self.state: dict[str, object] = {
            "schema_version": 1,
            "repository": config.repository,
            "pr_number": config.pr_number,
            "topic_branch": config.topic_branch,
            "base_branch": config.base_branch,
            "worktree": str(config.worktree),
            "pid": os.getpid(),
            "phase": "starting",
            "reason": None,
            "terminal": False,
            "started_at": utc_now(),
            "updated_at": utc_now(),
        }

    def _record(self, phase: str, *, reason: str | None = None, terminal: bool = False) -> None:
        self.state.update(
            phase=phase,
            reason=reason,
            terminal=terminal,
            updated_at=utc_now(),
        )
        write_state(self.paths.state, self.state)
        print(f"pr_delivery event={phase} pr={self.config.pr_number}", flush=True)

    def _preflight(self) -> None:
        """Require one clean, non-primary worktree with exclusive branch ownership."""
        top = Path(git(self.runner, self.config, "rev-parse", "--show-toplevel"))
        if top.resolve() != self.config.worktree.resolve():
            raise DeliveryError("worktree does not match its Git top level")
        listing = git(self.runner, self.config, "worktree", "list", "--porcelain")
        worktrees = [
            line.removeprefix("worktree ")
            for line in listing.splitlines()
            if line.startswith("worktree ")
        ]
        if not worktrees or Path(worktrees[0]).resolve() == self.config.worktree.resolve():
            raise DeliveryError("the primary checkout cannot host the delivery daemon")
        for record in listing.strip().split("\n\n"):
            fields = dict(
                line.split(" ", 1)
                for line in record.splitlines()
                if " " in line and line.split(" ", 1)[0] in {"branch", "worktree"}
            )
            if fields.get("branch") != f"refs/heads/{self.config.topic_branch}":
                continue
            owner = fields.get("worktree")
            if owner is None or Path(owner).resolve() != self.config.worktree.resolve():
                raise DeliveryError("topic branch is checked out by another worktree")
        branch = git(self.runner, self.config, "symbolic-ref", "--short", "HEAD")
        if branch != self.config.topic_branch:
            raise DeliveryError("worktree is not on the pinned topic branch")
        git(self.runner, self.config, "check-ref-format", "--branch", self.config.topic_branch)
        git(self.runner, self.config, "check-ref-format", "--branch", self.config.base_branch)
        if git(self.runner, self.config, "status", "--porcelain"):
            raise DeliveryError("delivery worktree must be clean")
        git_dir = Path(
            git(self.runner, self.config, "rev-parse", "--path-format=absolute", "--git-dir")
        )
        incomplete = (git_dir / "MERGE_HEAD", git_dir / "rebase-merge", git_dir / "rebase-apply")
        if any(path.exists() for path in incomplete):
            raise DeliveryError("delivery worktree has an incomplete Git operation")

    def _query(self) -> PullRequestSnapshot:
        """Read one bounded PR snapshot using existing GitHub CLI authentication."""
        fields = (
            "state,headRefName,headRefOid,baseRefName,baseRefOid,mergeStateStatus,"
            "isDraft,autoMergeRequest,statusCheckRollup,mergeCommit"
        )
        output = require_success(
            self.runner(
                (
                    "gh",
                    "pr",
                    "view",
                    str(self.config.pr_number),
                    "--repo",
                    self.config.repository,
                    "--json",
                    fields,
                ),
                self.config.worktree,
                45,
            ),
            "GitHub pull request query",
        )
        try:
            return snapshot(json.loads(output))
        except json.JSONDecodeError as error:
            raise DeliveryError("pull request response is invalid JSON") from error

    def _wait_for_query_slot(self) -> bool:
        """Keep every GitHub observation at least one configured interval apart."""
        if self.last_query is None:
            return True
        now = time.monotonic()
        elapsed = now - self.last_query
        remaining = max(0.0, self.config.interval_seconds - elapsed)
        total_remaining = max(0.0, self.total_deadline - now)
        progress_remaining = max(
            0.0,
            self.last_progress + self.config.no_progress_seconds - now,
        )
        remaining = min(remaining, total_remaining, progress_remaining)
        if remaining:
            self.stop_event.wait(remaining)
        return not self.stop_event.is_set()

    def _remote_topic_head(self) -> str:
        """Read the exact Git remote topic ref without trusting the PR projection."""
        remote_line = git(
            self.runner,
            self.config,
            "ls-remote",
            self.config.remote,
            f"refs/heads/{self.config.topic_branch}",
            timeout=60,
        )
        return remote_line.split(maxsplit=1)[0] if remote_line else ""

    def _verify_identity(self, current: PullRequestSnapshot) -> bool:
        """Validate identity or hold one bounded coordinator-owned projection delay."""
        if current.head_branch != self.config.topic_branch:
            raise DeliveryError("pull request head branch changed")
        if current.base_branch != self.config.base_branch:
            raise DeliveryError("pull request base branch changed")
        local_head = git(self.runner, self.config, "rev-parse", "HEAD")
        pending = self.pending_head_projection
        if (
            pending is not None
            and current.head_sha == local_head
            and local_head == pending.pushed_head
        ):
            self.pending_head_projection = None
            self.state["pr_head_projection_pending"] = False
        if current.state != "OPEN":
            return True
        if git(self.runner, self.config, "status", "--porcelain"):
            raise DeliveryError("delivery worktree became dirty")
        remote_head = self._remote_topic_head()
        expected_remote_head = pending.pushed_head if pending is not None else local_head
        if local_head != expected_remote_head:
            raise DeliveryError("local worktree head changed after topic branch push")
        if remote_head != expected_remote_head:
            raise DeliveryError("remote topic branch changed after verified push")
        if current.head_sha == local_head:
            return True

        pending = self.pending_head_projection
        if pending is None or current.head_sha != pending.previous_head:
            raise DeliveryError("remote pull request head differs from the local worktree")
        elapsed = time.monotonic() - pending.started_at
        if (
            pending.observations >= _MAX_DELAYED_HEAD_OBSERVATIONS
            or elapsed > _MAX_DELAYED_HEAD_SECONDS
        ):
            raise DeliveryError("pull request head projection did not converge after push")

        observations = pending.observations + 1
        self.pending_head_projection = replace(pending, observations=observations)
        self.state.update(
            pr_head_projection_pending=True,
            projected_head_sha=current.head_sha,
            pushed_head_sha=pending.pushed_head,
            projection_observations=observations,
        )
        self._record("waiting_for_pr_head")
        return False

    def _sync_base(self, previous_pr_head: str) -> None:
        """Merge the latest base locally, push without force, and verify exact SHA."""
        self._record("syncing_base")
        if git(self.runner, self.config, "status", "--porcelain"):
            raise DeliveryError("delivery worktree became dirty")
        refspec = (
            f"+refs/heads/{self.config.base_branch}:"
            f"refs/remotes/{self.config.remote}/{self.config.base_branch}"
        )
        git(self.runner, self.config, "fetch", "--quiet", self.config.remote, refspec, timeout=120)
        base_ref = f"refs/remotes/{self.config.remote}/{self.config.base_branch}"
        merge = self.runner(
            ("git", "merge", "--no-edit", base_ref),
            self.config.worktree,
            self.config.command_timeout_seconds,
        )
        if merge.returncode != 0:
            self.runner(("git", "merge", "--abort"), self.config.worktree, 60)
            raise DeliveryError("base merge conflicted or failed")
        local_head = git(self.runner, self.config, "rev-parse", "HEAD")
        base_head = git(self.runner, self.config, "rev-parse", base_ref)
        push = self.runner(
            ("git", "push", self.config.remote, self.config.topic_branch),
            self.config.worktree,
            self.config.command_timeout_seconds,
        )
        require_success(push, "topic branch push")
        remote_sha = self._remote_topic_head()
        if remote_sha != local_head:
            raise DeliveryError("pushed topic branch does not match the local commit")
        self.last_progress = time.monotonic()
        if local_head != previous_pr_head:
            self.pending_head_projection = _PendingHeadProjection(
                previous_head=previous_pr_head,
                pushed_head=local_head,
                started_at=self.last_progress,
            )
        else:
            self.pending_head_projection = None
        self.state.update(
            head_sha=local_head,
            base_sha=base_head,
            pr_head_projection_pending=self.pending_head_projection is not None,
            projected_head_sha=previous_pr_head,
            pushed_head_sha=local_head,
            projection_observations=0,
        )
        self._record("base_synced")

    def _enable_auto_merge(self, expected_head: str) -> None:
        """Restore protected auto-merge only for the identity-verified PR head."""
        flag = f"--{self.config.merge_method}"
        result = self.runner(
            (
                "gh",
                "pr",
                "merge",
                str(self.config.pr_number),
                "--repo",
                self.config.repository,
                "--auto",
                flag,
                "--delete-branch",
                "--match-head-commit",
                expected_head,
            ),
            self.config.worktree,
            60,
        )
        require_success(result, "enable protected auto-merge")
        self.last_progress = time.monotonic()
        self.state["auto_merge_enabled"] = True
        self._record("auto_merge_enabled")

    def _verify_merge(self, current: PullRequestSnapshot) -> None:
        """Require the reported merge commit to be contained by the remote base."""
        if current.merge_commit is None:
            raise DeliveryError("merged pull request has no merge commit")
        refspec = (
            f"+refs/heads/{self.config.base_branch}:"
            f"refs/remotes/{self.config.remote}/{self.config.base_branch}"
        )
        git(self.runner, self.config, "fetch", "--quiet", self.config.remote, refspec, timeout=120)
        base_ref = f"refs/remotes/{self.config.remote}/{self.config.base_branch}"
        result = self.runner(
            ("git", "merge-base", "--is-ancestor", current.merge_commit, base_ref),
            self.config.worktree,
            60,
        )
        if result.returncode != 0:
            raise DeliveryError("remote base does not contain the reported merge commit")

    def _run_owned(self) -> int:
        """Advance the state machine while the caller holds the per-PR lock."""
        self._preflight()
        self._record("watching")
        while not self.stop_event.is_set():
            now = time.monotonic()
            if now >= self.total_deadline:
                self._record("timeout", reason="total_timeout", terminal=True)
                return 2
            if now >= self.last_progress + self.config.no_progress_seconds:
                self._record("no_progress", reason="no_progress_timeout", terminal=True)
                return 2
            if not self._wait_for_query_slot():
                continue
            now = time.monotonic()
            if (
                now >= self.total_deadline
                or now >= self.last_progress + self.config.no_progress_seconds
            ):
                continue
            self.last_query = time.monotonic()
            current = self._query()
            if not self._verify_identity(current):
                continue
            self.state.update(
                pr_state=current.state.lower(),
                head_sha=current.head_sha,
                base_sha=current.base_sha,
                merge_state=current.merge_state.lower(),
                checks_state=current.checks_state,
                auto_merge_enabled=current.auto_merge_enabled,
            )
            if current.fingerprint != self.last_fingerprint:
                self.last_fingerprint = current.fingerprint
                self.last_progress = now
                self._record("watching")
            if current.state == "MERGED":
                self._verify_merge(current)
                self.state["merge_commit"] = current.merge_commit
                self._record("merged", terminal=True)
                return 0
            if current.state == "CLOSED":
                self._record("closed", reason="pull_request_closed", terminal=True)
                return 3
            if current.is_draft:
                self._record("blocked", reason="pull_request_is_draft", terminal=True)
                return 6
            if current.checks_state == "failed":
                self._record("blocked", reason="required_check_failed", terminal=True)
                return 4
            if current.merge_state == "DIRTY":
                self._record("blocked", reason="merge_conflict", terminal=True)
                return 5
            if current.merge_state == "BEHIND":
                self._sync_base(current.head_sha)
                continue
            if not current.auto_merge_enabled:
                self._enable_auto_merge(current.head_sha)
                continue
            self.stop_event.wait(self.config.interval_seconds)
        self._record("interrupted", reason="signal", terminal=True)
        return 130

    def run(self) -> int:
        """Run until merge or a fail-closed bounded outcome and return a stable code."""
        self.paths.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.paths.directory, 0o700)
        with self.paths.lock.open("a+", encoding="utf-8") as lock:
            os.chmod(self.paths.lock, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DeliveryError("another daemon already owns this pull request") from None
            try:
                return self._run_owned()
            except DeliveryError as error:
                self._record("failed", reason=str(error), terminal=True)
                raise
