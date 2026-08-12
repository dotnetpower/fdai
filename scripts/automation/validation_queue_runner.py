"""Execute one isolated centralized validation batch."""

from __future__ import annotations

import fcntl
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from scripts.automation.validation_queue_context import (
    load_stage_cache,
    local_input_digest,
    stage_cache_context,
    sync_fingerprint,
    sync_is_current,
    validation_environment,
    write_stage_cache,
)
from scripts.automation.validation_queue_evidence import structural_gate_digest
from scripts.automation.validation_queue_resume import (
    changed_test_cache_dir,
    changed_test_resume_context,
    failed_nodeids,
    load_changed_test_resume,
    write_changed_test_failure,
)
from scripts.automation.validation_queue_support import (
    UTC,
    QueuePaths,
    atomic_write,
    git,
    initialize,
    pending_commits,
    resolve_commit,
    validation_base,
)


class StageResult(TypedDict):
    """One timed or cached validation stage result."""

    name: str
    status: int
    duration_seconds: float
    cached: bool
    resumed_from: str | None
    resumed_failures: int
    input_digest: str | None


def _link_local_path(source: Path, destination: Path) -> None:
    if source.exists() and not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(source, target_is_directory=source.is_dir())


def _local_worktree_path(paths: QueuePaths, relative: Path) -> Path:
    output = git("worktree", "list", "--porcelain", cwd=paths.repo_root).stdout
    roots = [
        Path(line.removeprefix("worktree "))
        for line in output.splitlines()
        if line.startswith("worktree ")
    ]
    candidates = dict.fromkeys((paths.repo_root, *roots))
    return next(
        (root / relative for root in candidates if (root / relative).exists()),
        paths.repo_root / relative,
    )


def _run_stage(
    name: str,
    arguments: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> StageResult:
    started = time.monotonic()
    status = subprocess.run(arguments, cwd=cwd, env=env, check=False).returncode
    duration = round(time.monotonic() - started, 3)
    print(f"validation-queue: stage={name} status={status} duration={duration:.3f}s")
    return {
        "name": name,
        "status": status,
        "duration_seconds": duration,
        "cached": False,
        "resumed_from": None,
        "resumed_failures": 0,
        "input_digest": None,
    }


def _cached_stage(name: str) -> StageResult:
    print(f"validation-queue: stage={name} status=0 cached=true")
    return {
        "name": name,
        "status": 0,
        "duration_seconds": 0.0,
        "cached": True,
        "resumed_from": None,
        "resumed_failures": 0,
        "input_digest": None,
    }


def _registered_worktrees(paths: QueuePaths) -> set[Path]:
    output = git("worktree", "list", "--porcelain", cwd=paths.repo_root).stdout
    return {
        Path(line.removeprefix("worktree ")).resolve()
        for line in output.splitlines()
        if line.startswith("worktree ")
    }


def _prepare_validation_worktree(paths: QueuePaths, head: str) -> Path:
    registered = _registered_worktrees(paths)
    validation_root = paths.worktree.resolve()
    if validation_root not in registered:
        if paths.worktree.exists():
            shutil.rmtree(paths.worktree)
        git("worktree", "prune", cwd=paths.repo_root, check=False)
        git(
            "worktree",
            "add",
            "--quiet",
            "--detach",
            str(paths.worktree),
            head,
            cwd=paths.repo_root,
        )
    else:
        git("reset", "--hard", head, cwd=paths.worktree)
    git("clean", "-ffdx", cwd=paths.worktree)
    return paths.worktree


def _record_receipts(
    paths: QueuePaths,
    commits: list[str],
    *,
    base: str,
    head: str,
    mode: str,
    run_record: dict[str, object],
) -> None:
    validated_at = datetime.now(UTC).isoformat()
    for commit in commits:
        payload = {
            "commit": commit,
            "validated_at": validated_at,
            "validated_base": base,
            "validated_head": head,
            "mode": mode,
            "duration_seconds": run_record["duration_seconds"],
            "stages": run_record["stages"],
        }
        atomic_write(
            paths.receipts / f"{commit}.json",
            json.dumps(payload, sort_keys=True) + "\n",
        )
        (paths.pending / f"{commit}.json").unlink(missing_ok=True)


def _run_locked(paths: QueuePaths, mode: str) -> int:
    head = resolve_commit(paths, "HEAD")
    pending = pending_commits(paths)
    history = git("rev-list", "--reverse", "--topo-order", head, cwd=paths.repo_root).stdout
    history_commits = history.splitlines()
    selected = [commit for commit in history_commits if commit in pending]
    if not selected:
        print("validation-queue: no pending commits reachable from HEAD")
        return 0

    base = validation_base(paths, selected[0])
    revision_range = f"{base}..{head}"
    started_at = datetime.now(UTC).isoformat()
    run_started = time.monotonic()
    stages: list[StageResult] = []
    status = 1
    try:
        validation_root = _prepare_validation_worktree(paths, head)
        for package_root in ("console", "cli"):
            _link_local_path(
                _local_worktree_path(paths, Path(package_root) / "node_modules"),
                validation_root / package_root / "node_modules",
            )
        for filename in ("resolved-models.json", "resolved-models-local.json"):
            _link_local_path(
                _local_worktree_path(paths, Path(filename)),
                validation_root / filename,
            )
        environment = validation_environment(paths)
        dependency_fingerprint = sync_fingerprint(validation_root, environment)
        if sync_is_current(paths, dependency_fingerprint):
            sync_result = _cached_stage("dependency-sync")
        else:
            sync_result = _run_stage(
                "dependency-sync",
                [
                    "uv",
                    "sync",
                    "--frozen",
                    "--extra",
                    "dev",
                    "--extra",
                    "azure-mcp",
                    "--python",
                    environment["UV_PYTHON"],
                ],
                cwd=validation_root,
                env=environment,
            )
            if sync_result["status"] == 0:
                atomic_write(
                    paths.sync_state,
                    json.dumps({"fingerprint": dependency_fingerprint}, sort_keys=True) + "\n",
                )
        stages.append(sync_result)
        if sync_result["status"] != 0:
            status = int(sync_result["status"])
            return status
        environment["UV_NO_SYNC"] = "1"
        environment["FDAI_VERIFY_CACHE_DIR"] = str(paths.stage_cache / "verify")
        environment["FDAI_VERIFY_CONTEXT_DIGEST"] = local_input_digest(validation_root)
        cache_path = paths.stage_cache / f"{head}.json"
        cache_context = stage_cache_context(
            base=base,
            head=head,
            mode=mode,
            environment=environment,
            local_digest=environment["FDAI_VERIFY_CONTEXT_DIGEST"],
        )
        changed_test_context = changed_test_resume_context(cache_context, dependency_fingerprint)
        changed_test_cache = changed_test_cache_dir(paths, head)
        environment["FDAI_CHANGED_TEST_CACHE_DIR"] = str(changed_test_cache)
        environment["FDAI_CHANGED_TEST_SHARD_DIR"] = str(paths.stage_cache / "pytest-shards" / head)
        passed_stages = load_stage_cache(cache_path, cache_context)
        print(
            f"validation-queue: validating {len(selected)} commit(s) at {head[:12]} "
            f"with mode={mode}"
        )
        if mode == "fast":
            if "changed-tests" in passed_stages:
                changed_result = _cached_stage("changed-tests")
            else:
                resume = load_changed_test_resume(
                    paths,
                    history=history_commits,
                    head=head,
                    context=changed_test_context,
                    validation_root=validation_root,
                )
                changed_arguments = [
                    "bash",
                    "scripts/automation/tests-for-diff.sh",
                    "--run",
                ]
                changed_range = revision_range
                if resume is not None:
                    for nodeid in resume["nodeids"]:
                        changed_arguments.extend(("--include-test", nodeid))
                    changed_range = f"{resume['failed_head']}..{head}"
                    print(
                        "validation-queue: resuming changed tests from "
                        f"{resume['failed_head'][:12]} with "
                        f"{len(resume['nodeids'])} prior failure(s)"
                    )
                changed_arguments.append(changed_range)
                changed_result = _run_stage(
                    "changed-tests",
                    changed_arguments,
                    cwd=validation_root,
                    env=environment,
                )
                if resume is not None:
                    changed_result["resumed_from"] = resume["failed_head"]
                    changed_result["resumed_failures"] = len(resume["nodeids"])
                if changed_result["status"] == 0:
                    passed_stages.add("changed-tests")
                    write_stage_cache(cache_path, cache_context, passed_stages)
                elif changed_result["status"] == 1:
                    failed_tests = failed_nodeids(changed_test_cache, validation_root)
                    if failed_tests:
                        write_changed_test_failure(
                            paths,
                            head=head,
                            context=changed_test_context,
                            nodeids=failed_tests,
                        )
            stages.append(changed_result)
            if changed_result["status"] != 0:
                status = int(changed_result["status"])
                return status
            verify_arguments = [
                "bash",
                "scripts/verify.sh",
                "--fast",
                "--diff",
                revision_range,
            ]
        else:
            verify_arguments = ["bash", "scripts/verify.sh", "--all"]
        verify_result = _run_stage(
            "fast-gates" if mode == "fast" else "all-gates",
            verify_arguments,
            cwd=validation_root,
            env=environment,
        )
        stages.append(verify_result)
        if verify_result["status"] != 0:
            status = int(verify_result["status"])
            return status
        structural_result = _run_stage(
            "structural-gates",
            ["bash", "scripts/automation/run-pre-push-structural-gates.sh"],
            cwd=validation_root,
            env=environment,
        )
        structural_result["input_digest"] = structural_gate_digest(validation_root)
        stages.append(structural_result)
        if structural_result["status"] != 0:
            status = int(structural_result["status"])
            return status
        status = 0
        run_record = _run_record(
            base=base,
            head=head,
            mode=mode,
            started_at=started_at,
            run_started=run_started,
            status=status,
            stages=stages,
        )
        _record_receipts(
            paths,
            selected,
            base=base,
            head=head,
            mode=mode,
            run_record=run_record,
        )
        print(f"validation-queue: validated {len(selected)} commit(s)")
        return 0
    finally:
        run_record = _run_record(
            base=base,
            head=head,
            mode=mode,
            started_at=started_at,
            run_started=run_started,
            status=status,
            stages=stages,
        )
        atomic_write(
            paths.runs / f"{head}.json",
            json.dumps(run_record, sort_keys=True) + "\n",
        )


def _run_record(
    *,
    base: str,
    head: str,
    mode: str,
    started_at: str,
    run_started: float,
    status: int,
    stages: list[StageResult],
) -> dict[str, object]:
    return {
        "base": base,
        "head": head,
        "mode": mode,
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
        "duration_seconds": round(time.monotonic() - run_started, 3),
        "status": status,
        "stages": stages,
    }


def run_validation(paths: QueuePaths, mode: str, *, wait_for_lock: bool = False) -> int:
    """Run one reachable batch under the shared validator lock."""
    initialize(paths)
    with paths.lock.open("a+", encoding="utf-8") as lock_file:
        try:
            operation = fcntl.LOCK_EX
            if not wait_for_lock:
                operation |= fcntl.LOCK_NB
            fcntl.flock(lock_file.fileno(), operation)
        except BlockingIOError:
            print("validation-queue: another integration validator is active", file=sys.stderr)
            return 3
        return _run_locked(paths, mode)
