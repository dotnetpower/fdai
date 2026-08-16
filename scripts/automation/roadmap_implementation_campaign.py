#!/usr/bin/env python3
"""Run one explicitly enabled randomized roadmap implementation batch."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import secrets
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, TextIO

import project_board_support as project_board
import roadmap_verification_agent as agent
import roadmap_verification_inventory as inventory
import roadmap_verification_watchdog as watchdog

# A batch is all-or-nothing: one rejected field discards every commit in it, and the branch
# head cannot advance until the whole batch is validated. Ten documents made each failure cost
# an hour of work; two converge far faster and lose almost nothing when a batch is rejected.
BATCH_SIZE = 2
MIN_HARDENING_ROUNDS = 20
STATE_DIRECTORY = "fdai-roadmap-implementation"
REFUSAL_FILE = "refused-folders.json"
REFUSAL_TTL_SECONDS = 12 * 3600
ELIGIBLE_PROJECT_STATUSES = frozenset({"Ready", "In progress"})
DEFAULT_AGENT_TIMEOUT_SECONDS = 3_600
CHANGED_TEST_TIMEOUT_SECONDS = 900
QUALITY_CHECK_TIMEOUT_SECONDS = 120

# Repository-wide gates that no diff-selected check ever runs. A violation therefore reaches
# central validation, where it rejects the whole snapshot and is discovered hours later by the
# lane it blocks rather than by the batch that caused it. Five separate incidents in one day
# came from this single shape, each fixed by adding one more gate here, so the list is now
# declared in one place: adding a gate is one line, and the reason lives with it. Measured
# together at under five seconds against batches that run for fifteen minutes or more.
BATCH_OWNED_GATES: tuple[tuple[str, ...], ...] = (
    ("python3", "scripts/quality/localization/check-readable-hangul.py"),
    ("bash", "scripts/quality/repository/check-guids.sh"),
    ("bash", "scripts/quality/repository/check-punctuation.sh"),
    ("python3", "scripts/quality/documentation/check-display-terminology.py"),
    ("python3", "scripts/quality/architecture/check-document-size.py"),
    ("python3", "scripts/quality/localization/check-translation-quality.py"),
    ("python3", "scripts/quality/localization/check-derived-sources.py"),
    ("python3", "scripts/quality/architecture/check-design-routes.py"),
    ("python3", "scripts/quality/architecture/check-constitution.py"),
    ("python3", "-m", "pytest", "tests/integration/scripts/test_service_test_suites.py", "-q"),
)


def _git(*arguments: str, cwd: Path) -> str:
    return subprocess.check_output(["git", *arguments], cwd=cwd, text=True).strip()


def _state_root(repo_root: Path) -> Path:
    raw = Path(_git("rev-parse", "--git-common-dir", cwd=repo_root))
    common = raw if raw.is_absolute() else repo_root / raw
    return common.resolve() / STATE_DIRECTORY


def _acquire_lock(path: Path) -> TextIO | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    os.chmod(path, 0o600)
    return handle


def remaining_work_by_folder(repo_root: Path) -> dict[str, list[str]]:
    """Return canonical roadmap documents with observable unchecked work."""
    grouped: dict[str, list[str]] = {}
    for relative in inventory.canonical_documents(repo_root):
        candidate = PurePosixPath(relative)
        if len(candidate.parts) < 4 or "- [ ]" not in (repo_root / relative).read_text(
            encoding="utf-8"
        ):
            continue
        grouped.setdefault(candidate.parts[2], []).append(relative)
    return {folder: sorted(documents) for folder, documents in sorted(grouped.items())}


def refused_folders(
    state_root: Path, issue_number: int, *, now: float, ttl: int = REFUSAL_TTL_SECONDS
) -> frozenset[str]:
    """Return folders this issue was recently refused, so a run is not respent on them."""
    try:
        raw = json.loads((state_root / REFUSAL_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    if not isinstance(raw, dict):
        return frozenset()
    prefix = f"{issue_number}:"
    return frozenset(
        key[len(prefix) :]
        for key, recorded in raw.items()
        if key.startswith(prefix) and isinstance(recorded, int | float) and now - recorded < ttl
    )


def record_refusal(
    state_root: Path, issue_number: int, folder: str, *, now: float, ttl: int = REFUSAL_TTL_SECONDS
) -> None:
    path = state_root / REFUSAL_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    kept = {
        key: value
        for key, value in raw.items()
        if isinstance(value, int | float) and now - value < ttl
    }
    kept[f"{issue_number}:{folder}"] = now
    path.write_text(json.dumps(kept, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(path, 0o600)


def choose_folder(
    grouped: Mapping[str, Sequence[str]],
    *,
    chooser: Callable[[Sequence[str]], str] | None = None,
) -> tuple[str, list[str]] | None:
    """Choose one folder that can supply a complete implementation batch."""
    eligible = sorted(
        folder for folder, documents in grouped.items() if len(documents) >= BATCH_SIZE
    )
    if not eligible:
        return None
    selected = (chooser or secrets.choice)(eligible)
    return selected, list(grouped[selected])


def _has_unchecked_exit_criterion(issue: project_board.IssueRecord) -> bool:
    return (
        project_board.has_exit_contract(issue.body)
        and re.search(r"^\s*-\s+\[ \]\s+\S", issue.body, re.MULTILINE) is not None
    )


def choose_issue(
    issues: Mapping[int, project_board.IssueRecord],
    items: Mapping[int, project_board.ProjectItem],
) -> project_board.IssueRecord | None:
    """Choose the highest-priority executable issue registered on the project board."""
    status_rank = {"In progress": 0, "Ready": 1}
    priority_rank = {"P0 - now": 0, "P1 - next": 1, "P2 - later": 2, "P3 - someday": 3}
    candidates: list[tuple[int, int, int, project_board.IssueRecord]] = []
    for number, item in items.items():
        issue = issues.get(number)
        if issue is None or issue.state.upper() != "OPEN":
            continue
        if item.status not in ELIGIBLE_PROJECT_STATUSES:
            continue
        if issue.labels.intersection({"blocked", "completed"}):
            continue
        if not _has_unchecked_exit_criterion(issue):
            continue
        candidates.append(
            (
                status_rank[item.status],
                priority_rank.get(item.priority or "", len(priority_rank)),
                number,
                issue,
            )
        )
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: candidate[:3])[3]


def discover_issue(repo_root: Path) -> project_board.IssueRecord | None:
    """Read the current repository project and choose one executable issue."""
    client = project_board.GitHubClient(timeout_seconds=30)
    repository = project_board.repository_name(client, None)
    owner = repository.partition("/")[0]
    project_number = int(
        os.environ.get("FDAI_GITHUB_PROJECT_NUMBER", project_board.DEFAULT_PROJECT_NUMBER)
    )
    issues = project_board.issue_records(client, repository)
    items = project_board.project_items(
        client,
        repository=repository,
        owner=owner,
        project_number=project_number,
    )
    return choose_issue(issues, items)


def _claim_issue(repo_root: Path, issue: project_board.IssueRecord) -> bool:
    """Best-effort project the selected issue into the active work state."""
    result = subprocess.run(  # noqa: S603 - fixed repository lifecycle command
        [sys.executable, "scripts/automation/project-board.py", "start", str(issue.number)],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode == 0


def _within_session_capacity(active_sessions: int, maximum: int) -> bool:
    return active_sessions <= maximum


def _campaign_relation(*, ahead: int, behind: int) -> str:
    if ahead > 0 and behind > 0:
        return "diverged"
    if ahead > 0:
        return "ahead"
    if behind > 0:
        return "behind"
    return "current"


def _main_checkout(repo_root: Path) -> Path | None:
    """Return the checkout that holds main, if one is registered."""
    output = _git("worktree", "list", "--porcelain", cwd=repo_root)
    current: Path | None = None
    for line in output.splitlines():
        if line.startswith("worktree "):
            current = Path(line.removeprefix("worktree "))
        elif line.strip() == "branch refs/heads/main" and current is not None:
            return current
    return None


def _dirty_paths(checkout: Path) -> set[str]:
    """Return every path the checkout has uncommitted, including untracked ones."""
    paths: set[str] = set()
    for line in _git("status", "--porcelain", cwd=checkout).splitlines():
        entry = line[3:].strip()
        # A rename reads `old -> new`; both sides are in flight and both must count.
        for part in entry.split(" -> "):
            candidate = part.strip().strip('"')
            if candidate:
                paths.add(candidate)
    return paths


def _merge_in_progress(checkout: Path) -> bool:
    """Return whether the checkout already holds an unconcluded merge.

    A linked worktree keeps ``MERGE_HEAD`` under the common directory, so the path
    has to come from git rather than be assembled as ``<checkout>/.git/MERGE_HEAD``.
    """
    raw = Path(_git("rev-parse", "--git-path", "MERGE_HEAD", cwd=checkout))
    return (raw if raw.is_absolute() else checkout / raw).exists()


def _newest_validated_commit(repo_root: Path) -> str | None:
    """Return the newest commit ahead of main that already holds a validation receipt."""
    for commit in _git("rev-list", "main..HEAD", cwd=repo_root).splitlines():
        if _validation_receipt_exists(repo_root, commit):
            return commit
    return None


def _land_validated_batch(repo_root: Path) -> str | None:
    """Merge the newest validated commit into main when the merge disturbs no live edit.

    Nothing else moves this work onto main (#137), so it accumulated on a branch that only
    diverged further. Two conditions looked like safety and behaved like a permanent refusal.

    Gating on HEAD never fired, because the campaign commits a batch and asks in the same
    cycle: HEAD is by construction the freshest commit and the least likely to be validated.
    Measured proof: the tip earned a receipt at 15:19, and by the time landing was consulted
    the branch had moved on and reported no receipt again. Landing now takes the newest
    ancestor that does hold one, so progress no longer depends on winning a race against the
    campaign's own production rate.

    Requiring a spotless main checkout never fired either, because the primary checkout is
    where people and other sessions work. What actually matters is narrower and checkable:
    the merge must not touch a file somebody is editing. When the incoming paths and the
    dirty paths are disjoint, git rewrites only files nobody holds.

    Landing is still skipped rather than forced: unvalidated work stays put, and a conflict
    aborts instead of leaving a half-merged tree that the next run would refuse. A skip that
    has work ready says why, because the blocking conditions are all outside this branch and
    a silent skip is indistinguishable from having nothing to hand over.
    """
    if _git("rev-list", "--count", "main..HEAD", cwd=repo_root) == "0":
        return None
    head = _newest_validated_commit(repo_root)
    if head is None:
        return None
    checkout = _main_checkout(repo_root)
    if checkout is None:
        return None
    # Somebody else's unconcluded merge lives in the same checkout. Merging on top of it
    # fails, and aborting afterwards would discard their conflict resolution, so refuse now.
    if _merge_in_progress(checkout):
        return f"cannot land {head[:12]}: the main checkout has an unconcluded merge"
    # `git merge` refuses whenever the index differs from HEAD, whatever the merge touches.
    # Measured: it named four staged files that were byte-identical on both sides.
    staged = _git("diff", "--name-only", "--cached", cwd=checkout).splitlines()
    if staged:
        return f"cannot land {head[:12]}: staged in the main checkout: {' '.join(sorted(staged))}"
    incoming = set(_git("diff", "--name-only", f"main...{head}", cwd=repo_root).splitlines())
    held = sorted(incoming & _dirty_paths(checkout))
    if held:
        return f"cannot land {head[:12]}: edited in the main checkout: {' '.join(held)}"
    before = _git("rev-parse", "main", cwd=repo_root)
    result = subprocess.run(  # noqa: S603 - fixed git merge operation
        ["git", "merge", "--no-ff", "--no-edit", head],
        cwd=checkout,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        # A refusal leaves no MERGE_HEAD, and aborting then fails and hides the real reason.
        if _merge_in_progress(checkout):
            subprocess.run(  # noqa: S603 - fixed git merge abort
                ["git", "merge", "--abort"],
                cwd=checkout,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
        reason = (result.stderr or result.stdout).strip().splitlines()
        return f"cannot land {head[:12]}: {reason[0] if reason else 'merge failed'}"
    # `git merge` skips the post-commit hook, so the merge commit needs registering by hand.
    _register_committed_work(checkout, before)
    return f"landed {head[:12]} on main"


def _sync_campaign_base(repo_root: Path) -> str:
    """Absorb main into the campaign branch or report why work must hold."""
    ahead = int(_git("rev-list", "--count", "main..HEAD", cwd=repo_root))
    behind = int(_git("rev-list", "--count", "HEAD..main", cwd=repo_root))
    relation = _campaign_relation(ahead=ahead, behind=behind)
    if relation in {"current", "ahead"}:
        return relation
    # Nothing lands campaign batches on main (#137), so the branch is routinely ahead when
    # main moves. Fast-forward while that is still possible, otherwise take a real merge;
    # refusing would hold every later run forever.
    merge_arguments = ["git", "merge", "--ff-only", "main"]
    if relation == "diverged":
        merge_arguments = ["git", "merge", "--no-edit", "main"]
    before = _git("rev-parse", "HEAD", cwd=repo_root)
    result = subprocess.run(  # noqa: S603 - fixed git merge operation
        merge_arguments,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode == 0:
        # `git merge` skips the post-commit hook, so a sync merge never reached the queue on
        # its own. That left the branch tip permanently unvalidated: the batch below it had a
        # receipt, the merge that absorbed main did not, and landing requires one on HEAD. The
        # branch would take every commit main produced and never hand any of its own back.
        _register_committed_work(repo_root, before)
        return "current"
    # Never leave a half-merged worktree behind; the next run requires a clean tree.
    subprocess.run(  # noqa: S603 - fixed git merge abort
        ["git", "merge", "--abort"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return "sync-failed"


def campaign_prompt(
    folder: str,
    candidates: Sequence[str],
    *,
    issue: project_board.IssueRecord,
) -> str:
    """Build the bounded implementation and hardening contract for one batch."""
    candidate_lines = "\n".join(f"- {document}" for document in candidates)
    # The prompt and the post-batch checks must name the same gates; listing them twice is how
    # the batch came to believe it had passed a gate nobody ran.
    gate_lines = "\n".join(f"  - `{' '.join(gate)}`" for gate in BATCH_OWNED_GATES)
    header = (
        f"Implement one FDAI roadmap residual-work campaign for registered issue #{issue.number}."
    )
    return f"""{header}

Issue contract:
{issue.body}

Target folder: docs/roadmap/{folder}/
Batch size: exactly {BATCH_SIZE} canonical English documents
Candidate documents with unchecked remaining work:
{candidate_lines}

Execution contract:
- Read the applicable repository instructions, route-selected design documents, each chosen
  English/Korean document pair, implementing code, and adjacent tests before editing.
- Select exactly {BATCH_SIZE} candidates whose remaining work is comparatively quick to implement
    and directly advances an unchecked exit criterion in issue #{issue.number}. If no coherent set
    of {BATCH_SIZE} documents advances that issue, return blocked without changing the repository.
- Write a bounded execution plan, then implement every selected document's chosen remaining item.
- Keep the implementation ledgers truthful. Update both language variants and refresh each Korean
  source SHA. Do not mark unrelated or evidence-dependent work complete.
- Add or update focused tests for every behavior change. Run the narrowest executable checks after
  each edit and commit only focused passing changes with task-owned pathspecs.
- Central validation rejects the whole branch on gates the focused checks never run, and one
  rejected commit stops every later batch. Before each commit run every command below plus
  `python3 scripts/quality/architecture/check-design-doc-impact.py --cached`, and fix what they
  report:
{gate_lines}
  Adding or moving a module under a routed surface requires updating an owning design
  document in the same commit, so record the new module where that route says it belongs. Use
  the display terms the terminology gate requires in operator-facing prose. Write Korean and
  Hangul character ranges as literal UTF-8, never as escaped code points, and never introduce
  a concrete GUID.
- After all {BATCH_SIZE} implementations pass, perform at least {MIN_HARDENING_ROUNDS} explicit
  critique and hardening rounds over the complete batch. Fix every verified finding above Low,
  rerun its focused check, and continue beyond round {MIN_HARDENING_ROUNDS} until the highest
  remaining verified severity is Low or none. Do not fabricate findings to reach the round count.
- Do not modify repository instructions, hooks, automation, quality gates, test configuration,
  generated artifacts, or signed integrity files unless a selected implementation legitimately
  owns that surface. Never run repository-wide validation, deployment, cloud, network, push,
    destructive git, or close issue #{issue.number}.
- Preserve customer-agnostic scope, constitutional safety invariants, public contracts, and
  English GitHub issue records. End with a clean worktree and one or more focused commits.
- Before returning, confirm every selected document and evidence path exists exactly as written.
- The result is rejected if any field breaks these bounds, so keep every entry short: at most
  50 `tests` entries of at most 500 characters each, at most 100 `evidence_paths`, and a
  `summary` under 3000 characters. Report one command and its outcome per `tests` entry;
  truncate long command lines rather than pasting whole invocations or captured output.
- End with exactly one JSON object and no prose after it:
{{"outcome":"completed|blocked","issue":{issue.number},"folder":"{folder}",
 "documents":["exactly {BATCH_SIZE} canonical English paths"],
 "hardening_rounds":{MIN_HARDENING_ROUNDS},
 "remaining_max_severity":"low|none","summary":"bounded factual result",
 "evidence_paths":["relative/path"],"tests":["focused command and result"]}}
"""


def _safe_path(value: object, *, repo_root: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("campaign paths must be non-empty strings")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise RuntimeError("campaign paths must stay inside the repository")
    resolved = (repo_root / candidate).resolve()
    if repo_root.resolve() not in resolved.parents or not resolved.exists():
        raise RuntimeError(f"campaign path does not exist: {candidate}")
    return candidate.as_posix()


def validate_result(
    payload: Mapping[str, Any],
    *,
    repo_root: Path,
    issue_number: int,
    folder: str,
    candidates: Sequence[str],
) -> dict[str, Any]:
    """Validate completion evidence before accepting a campaign batch."""
    outcome = payload.get("outcome")
    if outcome not in {"completed", "blocked"}:
        raise RuntimeError("campaign outcome must be completed or blocked")
    if payload.get("issue") != issue_number:
        raise RuntimeError("campaign result issue does not match the selected issue")
    if payload.get("folder") != folder:
        raise RuntimeError("campaign result folder does not match the selected folder")
    raw_documents = payload.get("documents", [])
    raw_evidence = payload.get("evidence_paths", [])
    raw_tests = payload.get("tests", [])
    if not isinstance(raw_documents, list) or not isinstance(raw_evidence, list):
        raise RuntimeError("campaign documents and evidence_paths must be lists")
    if not isinstance(raw_tests, list) or len(raw_tests) > 50:
        raise RuntimeError("campaign tests must be a bounded list")
    documents = [_safe_path(value, repo_root=repo_root) for value in raw_documents]
    evidence = [_safe_path(value, repo_root=repo_root) for value in raw_evidence]
    if len(evidence) > 100:
        raise RuntimeError("campaign evidence_paths must be a bounded list")
    tests = [value for value in raw_tests if isinstance(value, str) and 0 < len(value) <= 500]
    if len(tests) != len(raw_tests):
        raise RuntimeError("campaign tests contain an invalid entry")
    rounds = payload.get("hardening_rounds")
    severity = str(payload.get("remaining_max_severity", "")).lower()
    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 3000:
        raise RuntimeError("campaign summary is missing or too long")
    if outcome == "completed":
        if len(documents) != BATCH_SIZE or len(set(documents)) != BATCH_SIZE:
            raise RuntimeError(
                f"completed campaign must contain exactly {BATCH_SIZE} unique documents"
            )
        if not set(documents).issubset(candidates):
            raise RuntimeError("completed campaign selected a document outside the candidate set")
        if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < MIN_HARDENING_ROUNDS:
            raise RuntimeError(
                f"completed campaign requires at least {MIN_HARDENING_ROUNDS} hardening rounds"
            )
        if severity not in {"low", "none"}:
            raise RuntimeError("completed campaign has a remaining finding above Low")
        if not evidence or not tests:
            raise RuntimeError("completed campaign requires implementation and test evidence")
    return {
        "outcome": outcome,
        "issue": issue_number,
        "folder": folder,
        "documents": documents,
        "hardening_rounds": rounds,
        "remaining_max_severity": severity,
        "summary": " ".join(summary.split()),
        "evidence_paths": evidence,
        "tests": tests,
    }


def _changed_paths(repo_root: Path, base: str) -> list[str]:
    return sorted(_git("diff", "--name-only", f"{base}..HEAD", cwd=repo_root).splitlines())


def _require_document_updates(result: Mapping[str, Any], changed_paths: Sequence[str]) -> None:
    expected = {
        path
        for document in result["documents"]
        for path in (document, document.removesuffix(".md") + "-ko.md")
    }
    if not expected.issubset(changed_paths):
        raise RuntimeError("campaign did not commit every selected English/Korean document pair")


def _register_committed_work(repo_root: Path, base: str) -> None:
    """Register commits that exist so a failed batch does not strand unvalidatable work."""
    if _git("rev-parse", "HEAD", cwd=repo_root) == base:
        return
    for arguments in (
        ["python3", "scripts/automation/validation_queue.py", "ensure-range", f"{base}..HEAD"],
        ["python3", "scripts/automation/validation_queue.py", "wake"],
    ):
        subprocess.run(  # noqa: S603 - fixed repository validation commands
            arguments,
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )


def _run_check(arguments: list[str], *, repo_root: Path, timeout: int) -> None:
    completed = subprocess.run(  # noqa: S603 - fixed repository validation commands
        arguments,
        cwd=repo_root,
        env=agent.worker_environment(repo_root, repo_root),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"campaign validation failed: {' '.join(arguments[:2])}")


def _validation_receipt_exists(repo_root: Path, revision: str) -> bool:
    common = Path(_git("rev-parse", "--git-common-dir", cwd=repo_root))
    common = common if common.is_absolute() else repo_root / common
    commit = _git("rev-parse", revision, cwd=repo_root)
    return (common.resolve() / "fdai-validation-queue/receipts" / f"{commit}.json").is_file()


def _validation_rejected(repo_root: Path, revision: str) -> bool:
    """Report whether the queue already judged this commit and rejected it."""
    common = Path(_git("rev-parse", "--git-common-dir", cwd=repo_root))
    common = common if common.is_absolute() else repo_root / common
    commit = _git("rev-parse", revision, cwd=repo_root)
    record = common.resolve() / "fdai-validation-queue/runs" / f"{commit}.json"
    if not record.is_file():
        return False
    try:
        return int(json.loads(record.read_text(encoding="utf-8")).get("status", 0)) != 0
    except (OSError, ValueError):
        return False


def run_cycle(
    repo_root: Path,
    *,
    idle_seconds: int,
    timeout: int,
    max_active_sessions: int = 2,
) -> str:
    """Run at most one campaign batch and return a machine-readable status line."""
    state_root = _state_root(repo_root)
    if (state_root / "STOP").exists() or (repo_root / ".improve/STOP").exists():
        return "held: stop file present"
    lock = _acquire_lock(state_root / "campaign.lock")
    if lock is None:
        return "held: another campaign is active"
    with lock:
        leases = watchdog._active_session_leases(repo_root, idle_seconds)
        sessions = watchdog._recent_copilot_activity(repo_root, idle_seconds)
        active = watchdog._active_session_count(leases, sessions)
        if not _within_session_capacity(active, max_active_sessions):
            return f"held: active-sessions={active}, limit={max_active_sessions}"
        if _git("status", "--porcelain", cwd=repo_root):
            return "held: campaign worktree is dirty"
        branch = _git("branch", "--show-current", cwd=repo_root)
        if not branch.startswith("roadmap-implementation/"):
            return "held: campaign branch is not isolated"
        # Hand finished work over before deciding whether to produce more. Landing only ever
        # merges a commit that already holds a receipt, so it is safe while the tip is still
        # being validated, and putting it after the hold below deadlocked the branch: the
        # hold returned early, landing never ran, and the validated commits underneath the
        # tip could never reach main no matter how long the lane waited.
        landed = _land_validated_batch(repo_root)
        if landed is not None:
            print(f"roadmap-implementation campaign {landed}")
        # Settle the receipt before touching the branch. Absorbing main first mints a new
        # merge commit on every held run, and main moves whenever another session commits,
        # so the head would outrun validation forever instead of waiting once for it.
        # `git merge` also skips the post-commit hook, so register the head here rather
        # than waiting on a receipt the queue was never asked to produce.
        if _git("rev-list", "--count", "main..HEAD", cwd=repo_root) != "0" and not (
            _validation_receipt_exists(repo_root, "HEAD")
        ):
            # Waiting only helps while the verdict is still outstanding. Once the queue has
            # rejected this snapshot the answer cannot change, and the fix usually lands on
            # main, which the hold below would never let the branch absorb. That combination
            # held the lane indefinitely on a gate main had already fixed.
            if _validation_rejected(repo_root, "HEAD"):
                relation = _sync_campaign_base(repo_root)
                return f"held: previous campaign head was rejected; absorbed main ({relation})"
            _register_committed_work(repo_root, "main")
            return "held: previous campaign head is awaiting central validation"
        relation = _sync_campaign_base(repo_root)
        if relation == "sync-failed":
            return "held: campaign branch could not absorb main; resolve the conflict by hand"
        try:
            issue = discover_issue(repo_root)
        except project_board.BoardUnavailableError:
            return "held: registered issue discovery is unavailable"
        if issue is None:
            return "idle: no eligible registered issue"
        grouped = remaining_work_by_folder(repo_root)
        refused = refused_folders(state_root, issue.number, now=time.time())
        # Fail open: if every folder was refused, re-offer them all rather than idling forever.
        narrowed = {name: docs for name, docs in grouped.items() if name not in refused}
        selected = choose_folder(narrowed or grouped)
        if selected is None:
            return f"idle: no roadmap folder has {BATCH_SIZE} remaining-work documents"
        folder, candidates = selected
        issue_claimed = _claim_issue(repo_root, issue)
        cli = agent.copilot_path()
        if cli is None:
            raise RuntimeError("Copilot CLI is unavailable")
        base = _git("rev-parse", "HEAD", cwd=repo_root)
        try:
            output = agent.run_copilot(
                cli,
                campaign_prompt(folder, candidates, issue=issue),
                repo_root,
                apply=True,
                timeout=timeout,
                repo_root=repo_root,
            )
            result = validate_result(
                agent.json_object(output),
                repo_root=repo_root,
                issue_number=issue.number,
                folder=folder,
                candidates=candidates,
            )
            if result["outcome"] == "blocked":
                if _git("rev-parse", "HEAD", cwd=repo_root) != base or _git(
                    "status", "--porcelain", cwd=repo_root
                ):
                    raise RuntimeError("blocked campaign must not leave repository changes")
                record_refusal(state_root, issue.number, folder, now=time.time())
                # A blocked run produces no commit, so its summary is the only evidence of why.
                return f"blocked: issue #{issue.number}, docs/roadmap/{folder}: {result['summary']}"
            if _git("status", "--porcelain", cwd=repo_root):
                raise RuntimeError("campaign worker left uncommitted changes")
            if _git("rev-parse", "HEAD", cwd=repo_root) == base:
                raise RuntimeError("completed campaign did not commit changes")
            changed_paths = _changed_paths(repo_root, base)
            _require_document_updates(result, changed_paths)
            forbidden = (
                ".github/instructions/",
                ".githooks/",
                "scripts/automation/roadmap_",
                "scripts/integrity/",
                "scripts/quality/",
            )
            if any(path.startswith(forbidden) for path in changed_paths):
                raise RuntimeError("campaign changed a repository-control surface")
            _run_check(
                ["bash", "scripts/automation/tests-for-diff.sh", "--run", f"{base}..HEAD"],
                repo_root=repo_root,
                timeout=CHANGED_TEST_TIMEOUT_SECONDS,
            )
            _run_check(
                ["bash", "scripts/quality/localization/check-translations.sh"],
                repo_root=repo_root,
                timeout=QUALITY_CHECK_TIMEOUT_SECONDS,
            )
            for gate in BATCH_OWNED_GATES:
                _run_check(list(gate), repo_root=repo_root, timeout=QUALITY_CHECK_TIMEOUT_SECONDS)
            # This one needs the batch's own range, so it cannot join the list above.
            _run_check(
                [
                    "python3",
                    "scripts/quality/architecture/check-design-doc-impact.py",
                    f"{base}..HEAD",
                ],
                repo_root=repo_root,
                timeout=QUALITY_CHECK_TIMEOUT_SECONDS,
            )
            _run_check(
                [
                    "python3",
                    "scripts/automation/validation_queue.py",
                    "ensure-range",
                    f"{base}..HEAD",
                ],
                repo_root=repo_root,
                timeout=60,
            )
            _run_check(
                ["python3", "scripts/automation/validation_queue.py", "wake"],
                repo_root=repo_root,
                timeout=60,
            )
            state_root.mkdir(parents=True, exist_ok=True)
            with (state_root / "ledger.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {"base": base, "head": _git("rev-parse", "HEAD", cwd=repo_root), **result},
                        sort_keys=True,
                    )
                    + "\n"
                )
            return (
                f"completed: issue #{issue.number}, claimed={str(issue_claimed).lower()}, "
                f"docs/roadmap/{folder} "
                f"({len(result['documents'])} documents)"
            )
        except BaseException:
            # Commits already exist; without registration they can never earn a receipt
            # and every later push of this branch stays blocked.
            _register_committed_work(repo_root, base)
            raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--idle-seconds", type=int, default=900)
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_AGENT_TIMEOUT_SECONDS,
        help="Bounded budget for one agent batch; verification stages carry their own budgets.",
    )
    parser.add_argument("--max-active-sessions", type=int, default=2)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    repo_root = Path(_git("rev-parse", "--show-toplevel", cwd=Path.cwd()))
    message = run_cycle(
        repo_root,
        idle_seconds=max(60, arguments.idle_seconds),
        timeout=max(60, arguments.timeout),
        max_active_sessions=max(0, arguments.max_active_sessions),
    )
    print(f"roadmap-implementation campaign {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
