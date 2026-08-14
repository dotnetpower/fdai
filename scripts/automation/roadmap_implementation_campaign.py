#!/usr/bin/env python3
"""Run one explicitly enabled randomized roadmap implementation batch."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import secrets
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, TextIO

import roadmap_verification_agent as agent
import roadmap_verification_inventory as inventory
import roadmap_verification_watchdog as watchdog

BATCH_SIZE = 10
MIN_HARDENING_ROUNDS = 10
STATE_DIRECTORY = "fdai-roadmap-implementation"


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


def campaign_prompt(folder: str, candidates: Sequence[str], *, issue: int) -> str:
    """Build the bounded implementation and hardening contract for one batch."""
    candidate_lines = "\n".join(f"- {document}" for document in candidates)
    return f"""Implement one FDAI roadmap residual-work campaign for issue #{issue}.

Target folder: docs/roadmap/{folder}/
Batch size: exactly {BATCH_SIZE} canonical English documents
Candidate documents with unchecked remaining work:
{candidate_lines}

Execution contract:
- Read the applicable repository instructions, route-selected design documents, each chosen
  English/Korean document pair, implementing code, and adjacent tests before editing.
- Select exactly {BATCH_SIZE} candidates whose remaining work is comparatively quick to implement
  without inventing runtime evidence, weakening a contract, or making an architecture decision.
- Write a bounded execution plan, then implement every selected document's chosen remaining item.
- Keep the implementation ledgers truthful. Update both language variants and refresh each Korean
  source SHA. Do not mark unrelated or evidence-dependent work complete.
- Add or update focused tests for every behavior change. Run the narrowest executable checks after
  each edit and commit only focused passing changes with task-owned pathspecs.
- After all {BATCH_SIZE} implementations pass, perform at least {MIN_HARDENING_ROUNDS} explicit
  critique and hardening rounds over the complete batch. Fix every verified finding above Low,
  rerun its focused check, and continue beyond round {MIN_HARDENING_ROUNDS} until the highest
  remaining verified severity is Low or none. Do not fabricate findings to reach the round count.
- Do not modify repository instructions, hooks, automation, quality gates, test configuration,
  generated artifacts, or signed integrity files unless a selected implementation legitimately
  owns that surface. Never run repository-wide validation, deployment, cloud, network, push,
  destructive git, or close issue #{issue}.
- Preserve customer-agnostic scope, constitutional safety invariants, public contracts, and
  English GitHub issue records. End with a clean worktree and one or more focused commits.
- Before returning, confirm every selected document and evidence path exists exactly as written.
- End with exactly one JSON object and no prose after it:
{{"outcome":"completed|blocked","folder":"{folder}",
 "documents":["exactly ten canonical English paths"],"hardening_rounds":10,
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
    folder: str,
    candidates: Sequence[str],
) -> dict[str, Any]:
    """Validate completion evidence before accepting a campaign batch."""
    outcome = payload.get("outcome")
    if outcome not in {"completed", "blocked"}:
        raise RuntimeError("campaign outcome must be completed or blocked")
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
            raise RuntimeError("completed campaign must contain exactly ten unique documents")
        if not set(documents).issubset(candidates):
            raise RuntimeError("completed campaign selected a document outside the candidate set")
        if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < MIN_HARDENING_ROUNDS:
            raise RuntimeError("completed campaign requires at least ten hardening rounds")
        if severity not in {"low", "none"}:
            raise RuntimeError("completed campaign has a remaining finding above Low")
        if not evidence or not tests:
            raise RuntimeError("completed campaign requires implementation and test evidence")
    return {
        "outcome": outcome,
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


def run_cycle(
    repo_root: Path,
    *,
    issue: int,
    idle_seconds: int,
    timeout: int,
    max_active_sessions: int = 1,
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
        sessions = watchdog._recent_copilot_activity(idle_seconds)
        active = watchdog._active_session_count(leases, sessions)
        if active > max_active_sessions:
            return f"held: active-sessions={active}, limit={max_active_sessions}"
        if _git("status", "--porcelain", cwd=repo_root):
            return "held: campaign worktree is dirty"
        branch = _git("branch", "--show-current", cwd=repo_root)
        if not branch.startswith("roadmap-implementation/"):
            return "held: campaign branch is not isolated"
        if _git("rev-list", "--count", "main..HEAD", cwd=repo_root) != "0" and not (
            _validation_receipt_exists(repo_root, "HEAD")
        ):
            return "held: previous campaign head is awaiting central validation"
        selected = choose_folder(remaining_work_by_folder(repo_root))
        if selected is None:
            return "idle: no roadmap folder has ten remaining-work documents"
        folder, candidates = selected
        cli = agent.copilot_path()
        if cli is None:
            raise RuntimeError("Copilot CLI is unavailable")
        base = _git("rev-parse", "HEAD", cwd=repo_root)
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
            folder=folder,
            candidates=candidates,
        )
        if result["outcome"] == "blocked":
            if _git("rev-parse", "HEAD", cwd=repo_root) != base or _git(
                "status", "--porcelain", cwd=repo_root
            ):
                raise RuntimeError("blocked campaign must not leave repository changes")
            return f"blocked: docs/roadmap/{folder}"
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
            timeout=timeout,
        )
        _run_check(
            ["bash", "scripts/quality/localization/check-translations.sh"],
            repo_root=repo_root,
            timeout=timeout,
        )
        _run_check(
            ["python3", "scripts/automation/validation_queue.py", "ensure-range", f"{base}..HEAD"],
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
        return f"completed: docs/roadmap/{folder} ({len(result['documents'])} documents)"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--idle-seconds", type=int, default=900)
    parser.add_argument("--timeout", type=int, default=14_400)
    parser.add_argument("--max-active-sessions", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.issue <= 0:
        raise SystemExit("--issue must be a positive integer")
    repo_root = Path(_git("rev-parse", "--show-toplevel", cwd=Path.cwd()))
    message = run_cycle(
        repo_root,
        issue=arguments.issue,
        idle_seconds=max(60, arguments.idle_seconds),
        timeout=max(60, arguments.timeout),
        max_active_sessions=max(0, arguments.max_active_sessions),
    )
    print(f"roadmap-implementation campaign {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
