#!/usr/bin/env python3
"""Run one isolated roadmap implementation-verification job."""

from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import roadmap_verification as queue
import roadmap_verification_agent as agent
import roadmap_verification_inventory as inventory

UTC = timezone.utc  # noqa: UP017 - repository automation supports system Python 3.10.


def _run(
    arguments: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - commands are fixed or validated git operations
        arguments,
        cwd=cwd,
        env=dict(env) if env is not None else None,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _worktree_root(repo_root: Path) -> Path:
    configured = os.environ.get("FDAI_ROADMAP_WORKTREE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return repo_root.parent / f"{repo_root.name}-worktrees" / "roadmap-verification"


def _prepare_worktree(repo_root: Path, job_id: str, base_ref: str) -> tuple[Path, str, str]:
    base = _run(["git", "rev-parse", "--verify", f"{base_ref}^{{commit}}"], cwd=repo_root)
    if base.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40,64}", base.stdout.strip()):
        raise RuntimeError("roadmap verification base ref is not a commit")
    run_id = f"{time.strftime('%Y%m%d%H%M%S')}-{job_id}-{os.getpid()}"
    worktree = _worktree_root(repo_root) / run_id
    branch = f"roadmap-verification/{job_id}-{run_id[:14]}-{os.getpid()}"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    added = _run(
        ["git", "worktree", "add", "--quiet", "-b", branch, str(worktree), base.stdout.strip()],
        cwd=repo_root,
    )
    if added.returncode != 0:
        raise RuntimeError("could not create roadmap verification worktree")
    return worktree, branch, base.stdout.strip()


def _changed_paths(worktree: Path, base: str) -> list[str]:
    result = _run(["git", "diff", "--name-only", f"{base}..HEAD"], cwd=worktree)
    if result.returncode != 0:
        raise RuntimeError("could not inspect roadmap verification commit")
    return sorted(path for path in result.stdout.splitlines() if path)


def _reject_verification_surface_changes(changed_paths: list[str]) -> None:
    exact = {
        ".pre-commit-config.yaml",
        "Makefile",
        "pyproject.toml",
        "scripts/automation/resolve_test_impact.py",
        "scripts/automation/tests-for-diff.sh",
        "scripts/automation/validation_queue.py",
        "scripts/verify.sh",
        "tests/conftest.py",
        "uv.lock",
    }
    prefixes = (
        ".github/agents/",
        ".github/instructions/",
        ".githooks/",
        "scripts/automation/roadmap_verification",
        "scripts/integrity/",
        "scripts/quality/",
        "security/integrity/",
    )
    forbidden = [
        path for path in changed_paths if path in exact or any(path.startswith(p) for p in prefixes)
    ]
    if forbidden:
        raise RuntimeError("roadmap worker changed verification or repository-control files")


def _archive_failure(
    paths: queue.QueuePaths,
    worktree: Path,
    job_id: str,
    base: str | None,
) -> str | None:
    status = _run(["git", "status", "--porcelain"], cwd=worktree)
    if status.returncode != 0:
        return None
    committed = (
        _run(["git", "diff", "--binary", f"{base}..HEAD"], cwd=worktree)
        if base is not None
        else None
    )
    if not status.stdout.strip() and (committed is None or not committed.stdout.strip()):
        return None
    archive = paths.state_root / "diagnostics" / f"{job_id}-{int(time.time())}"
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "status.txt").write_text(status.stdout, encoding="utf-8")
    working = _run(["git", "diff", "--binary", "HEAD"], cwd=worktree)
    (archive / "working.patch").write_text(working.stdout, encoding="utf-8")
    if committed is not None:
        (archive / "committed.patch").write_text(committed.stdout, encoding="utf-8")
    untracked = _run(["git", "ls-files", "--others", "--exclude-standard"], cwd=worktree)
    (archive / "untracked.txt").write_text(untracked.stdout, encoding="utf-8")
    return str(archive)


def _frontmatter_field(path: Path, key: str) -> str | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        return None
    frontmatter = text[4:].split("\n---\n", maxsplit=1)[0]
    match = re.search(rf"^{re.escape(key)}\s*:\s*(.+?)\s*$", frontmatter, re.MULTILINE)
    return match.group(1).strip("\"'") if match else None


def _verify_metadata(worktree: Path, job: Mapping[str, Any], outcome: str) -> None:
    today = datetime.now(UTC).date().isoformat()
    for relative in (str(job["document"]), str(job["translation"])):
        path = worktree / relative
        if _frontmatter_field(path, "code_verification_status") != outcome:
            raise RuntimeError(f"roadmap verification status metadata is missing: {relative}")
        if _frontmatter_field(path, "code_verified_at") != today:
            raise RuntimeError(f"roadmap verification date metadata is missing: {relative}")


def _independent_checks(repo_root: Path, worktree: Path, base: str) -> list[str]:
    environment = agent.worker_environment(repo_root, worktree)
    environment["FDAI_PYTEST_MAX_WORKERS"] = "2"
    commands = (
        (["bash", "scripts/automation/tests-for-diff.sh", "--run", f"{base}..HEAD"], 900),
        (["bash", "scripts/quality/localization/check-translations.sh"], 120),
    )
    completed: list[str] = []
    for command, check_timeout in commands:
        result = _run(command, cwd=worktree, env=environment, timeout=check_timeout)
        if result.returncode != 0:
            raise RuntimeError(f"independent roadmap check failed: {' '.join(command[:2])}")
        completed.append(" ".join(command))
    return completed


def _integrate_branch(repo_root: Path, branch: str, base: str) -> str:
    if _run(["git", "status", "--porcelain"], cwd=repo_root).stdout.strip():
        raise RuntimeError("campaign worktree must be clean before integration")
    current_head = _run(["git", "rev-parse", "HEAD"], cwd=repo_root).stdout.strip()
    if current_head != base:
        raise RuntimeError("campaign branch moved while the roadmap job was running")
    current_branch = _run(["git", "branch", "--show-current"], cwd=repo_root).stdout.strip()
    if not current_branch:
        raise RuntimeError("campaign worktree must have a checked-out branch")
    merged = _run(["git", "merge", "--ff-only", branch], cwd=repo_root)
    if merged.returncode != 0:
        raise RuntimeError("campaign branch could not fast-forward to the verified job")
    return current_branch


def _eligible_statuses(*, apply: bool, retry_failed: bool) -> frozenset[str]:
    if retry_failed:
        return frozenset({"failed"})
    if apply:
        return frozenset({"queued", "failed", "reviewed", "gap_found"})
    return frozenset({"queued", "failed"})


def run_one(
    paths: queue.QueuePaths,
    *,
    apply: bool,
    base_ref: str,
    lease_seconds: int,
    timeout: int,
    integrate: bool = False,
    retry_failed: bool = False,
) -> dict[str, Any] | None:
    queue.sync(paths)
    owner = f"{socket.gethostname()}:{os.getpid()}"
    job = queue.claim(
        paths,
        owner=owner,
        lease_seconds=lease_seconds,
        eligible_statuses=_eligible_statuses(apply=apply, retry_failed=retry_failed),
    )
    if job is None:
        return None
    worktree: Path | None = None
    branch: str | None = None
    base: str | None = None
    retain_branch = False
    try:
        cli = agent.copilot_path()
        if cli is None:
            raise RuntimeError("Copilot CLI is unavailable")
        worktree, branch, base = _prepare_worktree(paths.repo_root, job["job_id"], base_ref)
        queue.heartbeat(
            paths,
            job_id=job["job_id"],
            owner=owner,
            checkpoint="auditing",
            lease_seconds=lease_seconds,
            details={"branch": branch, "worktree": str(worktree)},
        )
        output = agent.run_copilot(
            cli,
            agent.prompt(job, apply=apply),
            worktree,
            apply=apply,
            timeout=timeout,
            repo_root=paths.repo_root,
        )
        result = agent.validate_result(agent.json_object(output), worktree=worktree, apply=apply)
        head = _run(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
        dirty = _run(["git", "status", "--porcelain"], cwd=worktree).stdout.strip()
        if dirty:
            raise RuntimeError("roadmap worker left uncommitted changes")
        changed_paths = _changed_paths(worktree, base)
        _reject_verification_surface_changes(changed_paths)
        if not apply and (head != base or changed_paths):
            raise RuntimeError("report-only roadmap worker changed the repository")
        applied_outcomes = {"verified", "designed", "not_applicable"}
        if apply and result["outcome"] in applied_outcomes:
            required_docs = {str(job["document"]), str(job["translation"])}
            if head == base or not required_docs.issubset(changed_paths):
                raise RuntimeError(
                    "applied roadmap result must commit both roadmap document variants"
                )
            _verify_metadata(worktree, job, str(result["outcome"]))
            result["independent_checks"] = _independent_checks(paths.repo_root, worktree, base)
            retain_branch = True
            result.update({"base": base, "branch": branch, "head": head})
            if integrate:
                _run(
                    ["git", "worktree", "remove", "--force", str(worktree)],
                    cwd=paths.repo_root,
                )
                worktree = None
                result["branch"] = _integrate_branch(paths.repo_root, branch, base)
                _run(["git", "branch", "-D", branch], cwd=paths.repo_root)
                branch = None
                retain_branch = False
        elif apply and (head != base or changed_paths):
            raise RuntimeError("blocked apply result must not commit repository changes")
        evidence_root = paths.repo_root if worktree is None else worktree
        result["document_blob"] = inventory.file_blob(evidence_root, str(job["document"]))
        result["evidence_digest"] = inventory.evidence_digest(
            evidence_root,
            list(result["evidence_paths"]),
        )
        completed = queue.finish(
            paths,
            job_id=job["job_id"],
            owner=owner,
            outcome=str(result["outcome"]),
            result=result,
        )
        return completed
    except Exception as exc:
        if worktree is not None:
            _archive_failure(paths, worktree, job["job_id"], base)
        queue.fail(
            paths,
            job_id=job["job_id"],
            owner=owner,
            error_type=type(exc).__name__,
        )
        raise
    finally:
        if worktree is not None:
            _run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=paths.repo_root,
            )
        if branch is not None and not retain_branch:
            _run(["git", "branch", "-D", branch], cwd=paths.repo_root)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--base-ref", default="HEAD")
    parser.add_argument("--lease-seconds", type=int, default=1800)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--integrate", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    paths = queue.queue_paths()
    result = run_one(
        paths,
        apply=arguments.apply,
        base_ref=arguments.base_ref,
        lease_seconds=arguments.lease_seconds,
        timeout=arguments.timeout,
        integrate=arguments.integrate,
        retry_failed=arguments.retry_failed,
    )
    if result is None:
        print("roadmap-verification: no eligible job")
    else:
        print(f"roadmap-verification: {result['document']} -> {result['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
