#!/usr/bin/env python3
"""Reuse successful local structural checks, never CI or deployment evidence.

Both callers select committed HEAD. All commands run in an owned, locked
worktree with a verified non-editable dependency environment. Receipts are
optional; unavailable storage runs the checks instead of reporting a pass.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation.local_validation_inputs import (  # noqa: E402
    dependency_digest,
    digest,
    execution_environment,
    git,
    installed_digest,
    tracked_snapshot,
)

SCHEMA = 1
MAX_AGE_SECONDS = 86_400
MAX_RECEIPTS = 128
STAGE_SECONDS = 1_800
RUNNER = "scripts/automation/run-pre-push-structural-gates.sh"


def read_record(path: Path) -> dict[str, object] | None:
    """Treat absent, malformed, oversized, or unreadable local state as a miss."""
    try:
        if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size > 65_536:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def cache_hit(path: Path, context: str, *, now: float) -> bool:
    """Accept only an exact, unexpired, successful local structural receipt."""
    record = read_record(path)
    if record is None:
        return False
    completed = record.get("completed_at")
    if not isinstance(completed, (int, float)) or isinstance(completed, bool):
        return False
    return (
        type(record.get("schema_version")) is int
        and record.get("schema_version") == SCHEMA
        and record.get("scope") == "local-structural"
        and record.get("context") == context
        and record.get("success") is True
        and 0 <= now - completed <= MAX_AGE_SECONDS
    )


def write_record(path: Path, value: dict[str, object]) -> bool:
    """Atomically publish optional state; storage failures do not fail validation."""
    pending = path.with_name(f".{path.name}.{uuid.uuid4().hex}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink() or path.is_symlink():
            return False
        descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, sort_keys=True)
            output.write("\n")
        pending.replace(path)
        return True
    except OSError:
        print("local-validation: cache-write=unavailable; validation result retained")
        return False
    finally:
        try:
            pending.unlink(missing_ok=True)
        except OSError:
            print("local-validation: cache-cleanup=unavailable")


def prune_receipts(root: Path) -> None:
    """Bound optional receipt retention without touching other validation state."""
    try:
        entries = sorted(root.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in entries[MAX_RECEIPTS:]:
            path.unlink()
    except OSError:
        print("local-validation: cache-prune=unavailable")


@contextmanager
def locked_state(root: Path) -> Iterator[Path]:
    """Serialize shared scratch/environment mutations; contention uses private state."""
    common = Path(git(root, "rev-parse", "--git-common-dir").decode().strip())
    if not common.is_absolute():
        common = root / common
    state = common.resolve() / "fdai-local-validation"
    lock = None
    private = False
    try:
        if state.is_symlink():
            raise OSError("local validation state cannot be a symlink")
        state.mkdir(mode=0o700, parents=True, exist_ok=True)
        if (state / "run.lock").is_symlink():
            raise OSError("local validation lock cannot be a symlink")
        lock = (state / "run.lock").open("a+")
        deadline = time.monotonic() + 10
        while True:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise OSError("local validation state is busy") from None
                time.sleep(0.1)
    except OSError:
        if lock is not None:
            lock.close()
            lock = None
        state = root / ".fdai" / f"local-validation-{uuid.uuid4().hex}"
        state.mkdir(mode=0o700, parents=True)
        private = True
        print("local-validation: cache=unavailable; using isolated uncached validation")
    try:
        yield state
    finally:
        if private:
            try:
                git(root, "worktree", "remove", "--force", str(state / "worktree"))
                shutil.rmtree(state)
            except (OSError, subprocess.SubprocessError):
                print("local-validation: private-state-cleanup=unavailable")
        if lock is not None:
            lock.close()


def prepare_worktree(root: Path, state: Path, head: str) -> Path:
    """Reset only this mechanism's registered Git-common-dir scratch checkout."""
    worktree = state / "worktree"
    if worktree.is_symlink() or state.is_symlink():
        raise ValueError("local validation scratch paths cannot be symlinks")
    registered = git(root, "worktree", "list", "--porcelain").decode().splitlines()
    if f"worktree {worktree}" not in registered:
        if worktree.exists():
            raise ValueError("unregistered local validation scratch directory")
        git(root, "worktree", "add", "--quiet", "--detach", str(worktree), head)
    else:
        git(worktree, "reset", "--hard", head)
    git(worktree, "clean", "-ffdx")
    return worktree


def prepare_environment(
    root: Path,
    state: Path,
    environment: dict[str, str],
    dependency: str,
    tools: str,
) -> str:
    """Reuse frozen third-party dependencies only while their actual bytes match.

    Workspace packages are deliberately not installed: no editable pointer can
    import another checkout's dirty sources. Gate/test source paths come from
    the isolated committed checkout, not the dependency environment.
    """
    context = digest({"dependency": dependency, "tools": tools})
    receipt = read_record(state / "environment.json")
    current = None
    try:
        current = installed_digest(state / "venv")
    except (OSError, ValueError):
        print("local-validation: environment=missing-or-unreadable")
    if receipt == {"context": context, "installed": current} and current is not None:
        print("local-validation: dependency-sync=cached reason=verified-installed-inputs")
        return current
    venv = state / "venv"
    if venv.is_symlink():
        raise ValueError("local validation environment cannot be a symlink")
    if venv.exists():
        shutil.rmtree(venv)
    started = time.monotonic()
    subprocess.run(
        ["uv", "sync", "--frozen", "--extra", "dev", "--no-install-workspace", "--python", "3.13"],
        cwd=root,
        env=environment,
        check=True,
        timeout=600,
    )
    current = installed_digest(venv)
    write_record(state / "environment.json", {"context": context, "installed": current})
    print(f"local-validation: dependency-sync=passed duration={time.monotonic() - started:.3f}s")
    return current


def cache_context(
    root: Path,
    tree: str,
    tools: str,
    installed: str,
    arguments: list[str],
) -> str:
    """Bind content and execution identity, including Git's local ignore inputs."""
    common = Path(git(root, "rev-parse", "--git-common-dir").decode().strip())
    if not common.is_absolute():
        common = root / common
    exclude = common / "info" / "exclude"
    return digest(
        {
            "schema": SCHEMA,
            "tree": tree,
            "tools": tools,
            "installed": installed,
            "arguments": arguments,
            "git_config": git(root, "config", "--null", "--list").hex(),
            "git_exclude": exclude.read_bytes().hex() if exclude.exists() else "",
        }
    )


def run(root: Path, arguments: list[str], *, structural: bool) -> int:
    """Validate committed bytes; only the fixed structural command can use receipts."""
    started = time.monotonic()
    reusable = structural and not any(
        os.environ.get(name, "").lower() in {"1", "true"} for name in ("CI", "GITHUB_ACTIONS")
    )
    tree, _ = tracked_snapshot(root)
    head = git(root, "rev-parse", "HEAD").decode().strip()
    with locked_state(root) as state:
        worktree = prepare_worktree(root, state, head)
        snapshot_tree, files = tracked_snapshot(worktree)
        if snapshot_tree != tree:
            raise ValueError("selected source tree changed before validation")
        environment, tools = execution_environment(state)
        installed = prepare_environment(
            worktree,
            state,
            environment,
            dependency_digest(files),
            tools,
        )
        if tracked_snapshot(worktree)[0] != tree:
            raise ValueError("selected source tree changed during environment preparation")
        environment["UV_NO_SYNC"] = "1"
        environment["FDAI_STRUCTURAL_CACHE_ACTIVE"] = "1"
        context = cache_context(worktree, tree, tools, installed, arguments)
        receipt = state / "receipts" / f"{context}.json"
        if reusable and cache_hit(receipt, context, now=time.time()):
            print(
                "structural-gates: OK cached=true reason=matching-local-inputs "
                f"input_digest={context} duration={time.monotonic() - started:.3f}s"
            )
            return 0
        print("local-validation: cache=miss reason=missing-invalid-or-changed-inputs")
        completed = subprocess.run(
            arguments,
            cwd=worktree,
            env=environment,
            check=False,
            timeout=STAGE_SECONDS,
        )
        if completed.returncode != 0:
            return completed.returncode
        after_tree, _ = tracked_snapshot(worktree)
        _, after_tools = execution_environment(state)
        after_installed = installed_digest(state / "venv")
        if cache_context(worktree, after_tree, after_tools, after_installed, arguments) != context:
            raise ValueError("validation inputs changed during execution")
        if reusable:
            write_record(
                receipt,
                {
                    "schema_version": SCHEMA,
                    "scope": "local-structural",
                    "context": context,
                    "success": True,
                    "completed_at": time.time(),
                },
            )
            prune_receipts(receipt.parent)
        print(
            f"local-validation: status=0 cached=false input_digest={context} "
            f"duration={time.monotonic() - started:.3f}s"
        )
        return 0


def main() -> int:
    """Run shared structural validation or an uncached hook-owned project command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("structural", "command"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    arguments = options.arguments
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    if options.mode == "structural":
        arguments = ["bash", RUNNER]
    if not arguments:
        parser.error("command requires arguments")
    try:
        return run(Path.cwd().resolve(), arguments, structural=options.mode == "structural")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(
            f"local-validation: BLOCKED - {type(error).__name__}; no success recorded",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
