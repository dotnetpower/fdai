"""Child process specifications and readiness for ontology assurance."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path

from scripts.automation.ontology_assurance_evidence import (
    AssuranceRunError,
)
from scripts.automation.ontology_assurance_supervisor import (
    AssuranceProcessSupervisor,
    AtomicRunStatus,
    ProcessExit,
    ProcessSpec,
)


def _run_checked(
    command: Sequence[str],
    *,
    cwd: Path,
    log_path: Path,
    timeout_seconds: float = 120.0,
    capture_output: bool = False,
) -> str:
    log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        with os.fdopen(descriptor, "ab", buffering=0) as log_handle:
            if capture_output:
                completed = subprocess.run(  # noqa: S603 - repository-owned constants
                    tuple(command),
                    cwd=cwd,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    check=False,
                    timeout=timeout_seconds,
                )
            else:
                completed = subprocess.run(  # noqa: S603 - repository-owned constants
                    tuple(command),
                    cwd=cwd,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    check=False,
                    timeout=timeout_seconds,
                )
    except subprocess.TimeoutExpired as error:
        raise AssuranceRunError(f"command exceeded {timeout_seconds:g}s: {command[0]}") from error
    if completed.returncode != 0:
        raise AssuranceRunError(f"command failed with exit {completed.returncode}: {command[0]}")
    return completed.stdout.decode("utf-8", errors="replace") if capture_output else ""


def _git_output(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(  # noqa: S603 - git arguments are fixed or validated revisions
        ("git", "-C", str(repo), *arguments),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise AssuranceRunError(completed.stderr.strip() or "git command failed")
    return completed.stdout.strip()


def _workspace_patch_digest(worktree: Path, source_revision: str) -> str:
    completed = subprocess.run(  # noqa: S603 - git arguments are fixed and revision is validated
        ("git", "-C", str(worktree), "diff", "--binary", source_revision, "--", "."),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise AssuranceRunError("failed to compute the isolated workspace patch digest")
    digest = hashlib.sha256(completed.stdout)
    untracked = subprocess.run(  # noqa: S603 - git arguments are fixed
        (
            "git",
            "-C",
            str(worktree),
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        ),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if untracked.returncode != 0:
        raise AssuranceRunError("failed to enumerate untracked workspace files")
    for raw_path in sorted(path for path in untracked.stdout.split(b"\0") if path):
        path = worktree / raw_path.decode("utf-8")
        if path.is_symlink():
            content = path.readlink().as_posix().encode("utf-8")
            kind = b"symlink"
        elif path.is_file():
            content = path.read_bytes()
            kind = b"file"
        else:
            raise AssuranceRunError("untracked workspace entry is not a file")
        digest.update(b"\0untracked\0")
        digest.update(kind)
        digest.update(len(raw_path).to_bytes(8, "big"))
        digest.update(raw_path)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"sha256:{digest.hexdigest()}"


def _http_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310 - loopback only
            status_code = response.getcode()
            return isinstance(status_code, int) and 200 <= status_code < 500
    except OSError:
        return False


def _log_matches(path: Path, pattern: str) -> bool:
    try:
        return re.search(pattern, path.read_text(encoding="utf-8", errors="replace")) is not None
    except OSError:
        return False


def _log_contains_all(path: Path, values: tuple[str, ...]) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return all(value in text for value in values)


class OntologyAssuranceExecutionMixin:
    root: Path
    repo: Path
    worktree: Path
    run_root: Path
    run_id: str
    run_dir: Path
    logs_dir: Path
    env_dir: Path
    model_path: Path
    storage_state: Path
    stack_log: Path
    source_revision: str
    patch_digest: str
    operator_url: str
    console_url: str
    status: AtomicRunStatus
    supervisor: AssuranceProcessSupervisor
    request_topic: str
    projection_topic: str

    async def _wait_for_readiness(self) -> None:
        await self._wait_for_log_condition(
            label="operator readiness",
            log_path=self.run_root / "operator.log",
            predicate=lambda: _http_ready("http://127.0.0.1:8014/healthz"),
        )
        await self._wait_for_log_condition(
            label="console readiness",
            log_path=self.run_root / "console.log",
            predicate=lambda: _http_ready("http://127.0.0.1:5275/"),
        )
        await self._wait_for_log_condition(
            label="core catalog projection",
            log_path=self.run_root / "core.log",
            predicate=lambda: _log_matches(
                self.run_root / "core.log", r'"catalog_ontology_objects"\s*:\s*[1-9][0-9]*'
            ),
        )
        await self._wait_for_log_condition(
            label="core semantic consumer",
            log_path=self.run_root / "core.log",
            predicate=lambda: _log_contains_all(
                self.run_root / "core.log",
                ("event_bus_consumer_started", self.request_topic),
            ),
        )

    async def _wait_for_log_condition(
        self,
        *,
        label: str,
        log_path: Path,
        predicate: Callable[[], bool],
    ) -> None:
        async def watch() -> None:
            watcher = await asyncio.create_subprocess_exec(
                "inotifywait",
                "--monitor",
                "--quiet",
                "--event",
                "modify",
                "--event",
                "close_write",
                "--format",
                "%e",
                str(log_path),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                if watcher.stdout is None:
                    raise AssuranceRunError(f"{label} watcher has no output stream")
                if await asyncio.to_thread(predicate):
                    return
                while await watcher.stdout.readline():
                    if await asyncio.to_thread(predicate):
                        return
                raise AssuranceRunError(f"{label} watcher ended before readiness")
            finally:
                if watcher.returncode is None:
                    watcher.terminate()
                    await watcher.wait()

        try:
            await self.supervisor.guard_operation(watch(), timeout_seconds=120.0)
        except TimeoutError as error:
            raise AssuranceRunError(f"{label} exceeded its 120s deadline") from error
        self.status.update(state="running", phase="readiness", progress=f"{label} ready")

    async def _run_playwright_phase(
        self,
        *,
        label: str,
        output: Path,
        checkpoint: Path,
        run_budget_ms: int,
        question_ids: tuple[str, ...],
    ) -> ProcessExit:
        npx = shutil.which("npx")
        if npx is None:
            raise AssuranceRunError("npx is unavailable")
        environment = os.environ.copy()
        environment.update(
            FDAI_E2E_BASE_URL="http://localhost:5275",
            FDAI_E2E_OPERATOR_API_URL="http://127.0.0.1:8014",
            FDAI_E2E_STORAGE_STATE=str(self.storage_state),
            FDAI_E2E_SOURCE_REVISION=self.source_revision,
            FDAI_E2E_WORKSPACE_PATCH_SHA256=_workspace_patch_digest(
                self.worktree, self.source_revision
            ),
            FDAI_E2E_ASSURANCE_MIN_REQUEST_INTERVAL_MS="15000",
            FDAI_E2E_ASSURANCE_PER_QUESTION_DEADLINE_MS="180000",
            FDAI_E2E_ASSURANCE_NO_PROGRESS_DEADLINE_MS="300000",
            FDAI_E2E_ASSURANCE_RUN_BUDGET_MS=str(run_budget_ms),
            FDAI_E2E_ASSURANCE_RUN_ID=f"{self.run_id}-{label}",
            FDAI_E2E_ASSURANCE_CHECKPOINT=str(checkpoint),
        )
        if question_ids:
            environment["FDAI_E2E_ASSURANCE_QUESTION_IDS"] = ",".join(question_ids)
        command = (
            npx,
            "--prefix",
            str(self.worktree / "console"),
            "playwright",
            "test",
            "--config",
            str(self.worktree / "console" / "playwright.live.config.ts"),
            "--output",
            str(output),
            str(
                self.worktree
                / "console"
                / "tests"
                / "live-e2e"
                / "ontology-query-assurance.spec.ts"
            ),
        )
        self.status.update(state="running", phase=label, progress=f"starting {label}")
        return await self.supervisor.run_phase(
            ProcessSpec(
                label=label,
                command=command,
                command_label=f"playwright ontology-query-assurance {label}",
                cwd=self.worktree / "console",
                log_path=self.run_root / f"{label}.log",
                environment=environment,
            )
        )

    def _topic_high_watermark(self, topic: str) -> int:
        output = _run_checked(
            ("docker", "exec", "fdai-redpanda", "rpk", "topic", "describe", "-p", topic),
            cwd=self.repo,
            log_path=self.stack_log,
            capture_output=True,
        )
        values: list[int] = []
        for line in output.splitlines():
            columns = line.split()
            if len(columns) >= 6 and columns[0].isdigit() and columns[5].isdigit():
                values.append(int(columns[5]))
        if not values:
            raise AssuranceRunError(f"semantic topic high-watermark is unavailable: {topic}")
        return sum(values)
