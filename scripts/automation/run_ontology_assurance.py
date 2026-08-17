"""Run source-bound ontology assurance with fail-closed child supervision."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation.ontology_assurance_supervisor import (
    AssuranceProcessSupervisor,
    AtomicRunStatus,
    ProcessExit,
    ProcessSpec,
    RequiredChildExitedError,
)

SOURCE_REVISION_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
RUN_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
STRICT_QUESTION_IDS: Final = (
    "en-inventory_listing-1",
    "ko-inventory_listing-1",
    "en-relationship_traversal-4",
    "ko-relationship_traversal-4",
    "en-property_filter-5",
    "ko-property_filter-5",
    "en-aggregation-3",
    "ko-aggregation-3",
    "en-temporal_comparison-1",
    "ko-temporal_comparison-1",
    "en-causal_analysis-1",
    "ko-causal_analysis-1",
    "en-evidence_validation-2",
    "ko-evidence_validation-3",
)
STRICT_OPERATION_COUNTS: Final = {
    "aggregation": 2,
    "causal_analysis": 2,
    "evidence_validation": 2,
    "inventory_listing": 2,
    "property_filter": 2,
    "relationship_traversal": 2,
    "temporal_comparison": 2,
}


class AssuranceRunError(RuntimeError):
    """Raised when a governed precondition or release gate fails."""


def _utc_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # noqa: UP017


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
    return f"sha256:{hashlib.sha256(completed.stdout).hexdigest()}"


def _symlink(target: Path, link: Path) -> None:
    if link.is_symlink():
        if link.resolve() != target.resolve():
            raise AssuranceRunError(f"existing assurance link targets another path: {link}")
        return
    if link.exists():
        raise AssuranceRunError(f"assurance link path already exists: {link}")
    link.symlink_to(target, target_is_directory=target.is_dir())


def _find_artifact(output_path: Path) -> Path:
    candidates = sorted(output_path.glob("**/ontology-query-randomized-assurance.json"))
    if not candidates:
        raise AssuranceRunError(f"assurance artifact is missing under {output_path}")
    return candidates[0]


def _read_artifact(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AssuranceRunError(f"assurance artifact is unreadable: {path}") from error
    if not isinstance(payload, dict):
        raise AssuranceRunError("assurance artifact root MUST be an object")
    return payload


def _digest_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _bind_transport_evidence(
    path: Path,
    *,
    phase: str,
    request_topic: str,
    projection_topic: str,
    request_count: int,
    projection_count: int,
) -> None:
    payload = _read_artifact(path)
    payload["transport_evidence"] = {
        "schema_version": "1.0.0",
        "phase": phase,
        "request_topic_digest": _digest_text(request_topic),
        "projection_topic_digest": _digest_text(projection_topic),
        "request_count": request_count,
        "projection_count": projection_count,
    }
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _transport_evidence_accepted(
    payload: Mapping[str, Any],
    *,
    phase: str,
    expected_count: int,
) -> bool:
    evidence = payload.get("transport_evidence")
    if not isinstance(evidence, Mapping):
        return False
    request_digest = evidence.get("request_topic_digest")
    projection_digest = evidence.get("projection_topic_digest")
    return (
        evidence.get("schema_version") == "1.0.0"
        and evidence.get("phase") == phase
        and evidence.get("request_count") == expected_count
        and evidence.get("projection_count") == expected_count
        and isinstance(request_digest, str)
        and DIGEST_PATTERN.fullmatch(request_digest) is not None
        and isinstance(projection_digest, str)
        and DIGEST_PATTERN.fullmatch(projection_digest) is not None
        and request_digest != projection_digest
    )


def strict_artifact_accepted(payload: Mapping[str, Any], source_revision: str) -> bool:
    """Return whether the fresh 14-cell artifact clears the immutable strict gate."""
    summary = payload.get("summary")
    configuration = payload.get("run_configuration")
    return (
        isinstance(summary, Mapping)
        and isinstance(configuration, Mapping)
        and _transport_evidence_accepted(payload, phase="strict_14", expected_count=14)
        and all(
            (
                payload.get("schema_version") == "1.3.0",
                configuration.get("schema_version") == "1.4.0",
                payload.get("source_revision") == source_revision,
                payload.get("passed") is True,
                payload.get("run_mode") == "live",
                payload.get("receipt_source") == "live_assurance",
                summary.get("question_count") == 14,
                summary.get("live_question_count") == 14,
                summary.get("resumed_question_count") == 0,
                summary.get("passed_count") == 14,
                summary.get("answered_count") == 14,
                summary.get("answered_with_complete_evidence_count") == 14,
                summary.get("evidence_generation_consistent") is True,
                summary.get("answered_locale_coverage_complete") is True,
                summary.get("locale_counts") == {"en": 7, "ko": 7},
                summary.get("operation_counts") == STRICT_OPERATION_COUNTS,
                summary.get("transport_retry_count") == 0,
                summary.get("exhausted_transport_retry_count") == 0,
                summary.get("unsupported_operational_claim_count") == 0,
                summary.get("unauthorized_execution_count") == 0,
                summary.get("ambient_request_count") == 0,
                summary.get("bound_request_count") == 0,
                summary.get("plan_capability_mismatch_count") == 0,
            )
        )
    )


def full_artifact_accepted(payload: Mapping[str, Any], source_revision: str) -> bool:
    """Return whether the seeded 100-case artifact clears every release criterion."""
    summary = payload.get("summary")
    configuration = payload.get("run_configuration")
    return (
        isinstance(summary, Mapping)
        and isinstance(configuration, Mapping)
        and _transport_evidence_accepted(payload, phase="seeded_100", expected_count=100)
        and all(
            (
                payload.get("schema_version") == "1.3.0",
                configuration.get("schema_version") == "1.4.0",
                payload.get("source_revision") == source_revision,
                payload.get("passed") is True,
                payload.get("production_ready") is True,
                payload.get("run_mode") == "live",
                payload.get("receipt_source") == "live_assurance",
                summary.get("question_count") == 100,
                summary.get("live_question_count") == 100,
                summary.get("resumed_question_count") == 0,
                summary.get("passed_count") == 100,
                summary.get("locale_coverage_complete") is True,
                summary.get("operation_coverage_complete") is True,
                summary.get("answered_locale_coverage_complete") is True,
                summary.get("required_answer_coverage_complete") is True,
                summary.get("answered_count")
                == summary.get("answered_with_complete_evidence_count"),
                summary.get("unsupported_operational_claim_count") == 0,
                summary.get("unauthorized_execution_count") == 0,
                summary.get("ambient_request_count") == 0,
                summary.get("bound_request_count") == 0,
                summary.get("plan_capability_mismatch_count") == 0,
                summary.get("exhausted_transport_retry_count") == 0,
            )
        )
    )


def transport_delta_accepted(
    *,
    request_before: int,
    request_after: int,
    projection_before: int,
    projection_after: int,
    expected_count: int,
) -> bool:
    """Require one exact request and projection record per measured live turn."""
    return (
        expected_count > 0
        and request_after - request_before == expected_count
        and projection_after - projection_before == expected_count
    )


class OntologyAssuranceRunner:
    """Own one isolated stack and its strict-then-seeded assurance sequence."""

    def __init__(
        self,
        *,
        repo: Path,
        source_revision: str,
        run_id: str,
        status_path: Path,
        model_path: Path,
        storage_state: Path,
        prep_only: bool,
    ) -> None:
        self.repo = repo.resolve()
        self.source_revision = source_revision
        self.short_revision = source_revision[:10]
        self.run_id = run_id
        self.status = AtomicRunStatus(
            status_path,
            run_id=run_id,
            source_revision=source_revision,
        )
        self.model_path = model_path.resolve()
        self.storage_state = storage_state.resolve()
        self.prep_only = prep_only
        self.worktree = (
            self.repo.parent / "fdai-worktrees" / f"issue63-assurance-{self.short_revision}"
        )
        self.run_root = self.repo / ".fdai" / "live-validation" / "runs" / run_id
        self.stack_log = self.run_root / "stack.log"
        self.request_topic = f"assurance.operator.semantic-turn.requests.{run_id.lower()}"
        self.projection_topic = f"assurance.core.semantic-turn.projections.{run_id.lower()}"
        self.strict_output = (
            self.repo
            / ".fdai"
            / "live-validation"
            / (f"ontology-query-14-cell-{run_id}-{source_revision}")
        )
        self.full_output = (
            self.repo
            / ".fdai"
            / "live-validation"
            / (f"ontology-query-100-case-{run_id}-{source_revision}")
        )
        self.strict_checkpoint = self.run_root / "strict.checkpoint.json"
        self.full_checkpoint = self.run_root / "seeded-100.checkpoint.json"
        self.supervisor = AssuranceProcessSupervisor(self.status)

    async def run(self) -> int:
        """Execute one source-bound run and return a process-compatible status."""
        try:
            await asyncio.to_thread(self._prepare)
            await self.supervisor.start_services(self._service_specs())
            self.status.update(state="running", phase="readiness")
            await self._wait_for_readiness()
            if self.prep_only:
                self.status.update(state="complete", phase="prepared", termination=None)
                return 0

            request_before = await asyncio.to_thread(self._topic_high_watermark, self.request_topic)
            projection_before = await asyncio.to_thread(
                self._topic_high_watermark, self.projection_topic
            )
            strict_exit = await self._run_playwright_phase(
                label="strict_14",
                output=self.strict_output,
                checkpoint=self.strict_checkpoint,
                run_budget_ms=1_800_000,
                question_ids=STRICT_QUESTION_IDS,
            )
            if strict_exit.returncode != 0:
                raise AssuranceRunError(f"strict 14-cell phase exited {strict_exit.returncode}")
            strict_artifact = _find_artifact(self.strict_output)
            request_after = await asyncio.to_thread(self._topic_high_watermark, self.request_topic)
            projection_after = await asyncio.to_thread(
                self._topic_high_watermark, self.projection_topic
            )
            request_count = request_after - request_before
            projection_count = projection_after - projection_before
            await asyncio.to_thread(
                _bind_transport_evidence,
                strict_artifact,
                phase="strict_14",
                request_topic=self.request_topic,
                projection_topic=self.projection_topic,
                request_count=request_count,
                projection_count=projection_count,
            )
            if not transport_delta_accepted(
                request_before=request_before,
                request_after=request_after,
                projection_before=projection_before,
                projection_after=projection_after,
                expected_count=14,
            ):
                raise AssuranceRunError("strict semantic topic counts do not match 14 live turns")
            strict_payload = _read_artifact(strict_artifact)
            if not strict_artifact_accepted(strict_payload, self.source_revision):
                raise AssuranceRunError("strict 14-cell artifact failed the immutable gate")

            full_exit = await self._run_playwright_phase(
                label="seeded_100",
                output=self.full_output,
                checkpoint=self.full_checkpoint,
                run_budget_ms=5_400_000,
                question_ids=(),
            )
            if full_exit.returncode != 0:
                raise AssuranceRunError(f"seeded 100-case phase exited {full_exit.returncode}")
            full_artifact = _find_artifact(self.full_output)
            full_request_after = await asyncio.to_thread(
                self._topic_high_watermark, self.request_topic
            )
            full_projection_after = await asyncio.to_thread(
                self._topic_high_watermark, self.projection_topic
            )
            full_request_count = full_request_after - request_after
            full_projection_count = full_projection_after - projection_after
            await asyncio.to_thread(
                _bind_transport_evidence,
                full_artifact,
                phase="seeded_100",
                request_topic=self.request_topic,
                projection_topic=self.projection_topic,
                request_count=full_request_count,
                projection_count=full_projection_count,
            )
            if not transport_delta_accepted(
                request_before=request_after,
                request_after=full_request_after,
                projection_before=projection_after,
                projection_after=full_projection_after,
                expected_count=100,
            ):
                raise AssuranceRunError("seeded semantic topic counts do not match 100 live turns")
            full_payload = _read_artifact(full_artifact)
            if not full_artifact_accepted(full_payload, self.source_revision):
                raise AssuranceRunError("seeded 100-case artifact failed the immutable gate")
            self.status.update(
                state="complete",
                phase="complete",
                termination=None,
                artifacts={
                    "strict": str(strict_artifact),
                    "seeded_100": str(full_artifact),
                },
            )
            return 0
        except RequiredChildExitedError:
            return 1
        except (AssuranceRunError, TimeoutError) as error:
            self.status.update(
                state="failed",
                termination={"reason": type(error).__name__, "detail": str(error)},
            )
            return 1
        finally:
            await self.supervisor.close()

    def _prepare(self) -> None:
        self.status.update(
            state="preparing",
            phase="source_binding",
            outputs={
                "strict": str(self.strict_output),
                "seeded_100": str(self.full_output),
            },
            checkpoints={
                "strict": str(self.strict_checkpoint),
                "seeded_100": str(self.full_checkpoint),
            },
        )
        _run_checked(
            (
                sys.executable,
                str(self.repo / "scripts" / "automation" / "validation_queue.py"),
                "check-commit",
                self.source_revision,
            ),
            cwd=self.repo,
            log_path=self.stack_log,
        )
        required = (
            self.model_path,
            self.storage_state,
            self.repo / ".fdai" / "local-runtime.env",
            self.repo / ".fdai" / "local-operator-service.env",
            self.repo / "console" / "node_modules",
        )
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise AssuranceRunError(f"required assurance inputs are missing: {', '.join(missing)}")
        if stat.S_IMODE(self.storage_state.stat().st_mode) != 0o600:
            raise AssuranceRunError("Browser Entra storage state MUST have mode 600")
        if self.strict_checkpoint.exists() or self.full_checkpoint.exists():
            raise AssuranceRunError("fresh assurance checkpoints already exist for this run id")
        if self.strict_output.exists() or self.full_output.exists():
            raise AssuranceRunError("fresh assurance output already exists for this run id")

        if not (self.worktree / ".git").exists():
            _run_checked(
                (
                    "git",
                    "-C",
                    str(self.repo),
                    "worktree",
                    "add",
                    "--detach",
                    str(self.worktree),
                    self.source_revision,
                ),
                cwd=self.repo,
                log_path=self.stack_log,
            )
        if _git_output(self.worktree, "rev-parse", "HEAD") != self.source_revision:
            raise AssuranceRunError("detached assurance worktree revision mismatch")
        if _git_output(self.worktree, "status", "--short"):
            raise AssuranceRunError("detached assurance worktree is not clean")
        _symlink(self.repo / ".venv", self.worktree / ".venv")
        _symlink(
            self.repo / "console" / "node_modules",
            self.worktree / "console" / "node_modules",
        )
        _symlink(self.repo / "console" / ".env.local", self.worktree / "console" / ".env.local")

        self.status.update(state="preparing", phase="transport_setup")
        _run_checked(
            (
                "docker",
                "exec",
                "fdai-redpanda",
                "rpk",
                "topic",
                "create",
                "--if-not-exists",
                "--partitions",
                "1",
                self.request_topic,
                self.projection_topic,
            ),
            cwd=self.repo,
            log_path=self.stack_log,
        )

    def _service_specs(self) -> tuple[ProcessSpec, ...]:
        core_command = (
            "/usr/bin/bash",
            "-c",
            """
set -euo pipefail
cd "$1"
set -a
source "$2/.fdai/local-runtime.env"
set +a
export LLM_RESOLVED_MODELS_PATH="$3"
export FDAI_CORE_CONSUMER_GROUP_ID="$4-core"
export FDAI_PANTHEON_CONSUMER_GROUP_PREFIX="$4-pantheon"
export FDAI_SEMANTIC_TURN_CONSUMER_GROUP_ID="$4-semantic-core"
export FDAI_SEMANTIC_TURN_REQUEST_TOPIC="$5"
export FDAI_SEMANTIC_TURN_PROJECTION_TOPIC="$6"
python_path="$1/services/core-control-plane/src:$1/packages/service-contracts/src"
exec env -u AZURE_CONFIG_DIR FDAI_RUNTIME_LOCK_FILE="$7" \
    PYTHONPATH="$python_path${PYTHONPATH:+:$PYTHONPATH}" \
  "$2/.venv/bin/python" -m fdai
""",
            "_",
            str(self.worktree),
            str(self.repo),
            str(self.model_path),
            self.run_id,
            self.request_topic,
            self.projection_topic,
            str(self.run_root / "core.lock"),
        )
        operator_command = (
            "/usr/bin/bash",
            "-c",
            """
set -euo pipefail
cd "$1"
set -a
source "$2/.fdai/local-operator-service.env"
set +a
export FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS=http://localhost:5275
export FDAI_LIVE_STAGE_CONSUMER_GROUP_ID="$3-live-stage"
export FDAI_SEMANTIC_TURN_CONSUMER_GROUP_ID="$3-semantic-operator"
export FDAI_SEMANTIC_TURN_REQUEST_TOPIC="$4"
export FDAI_SEMANTIC_TURN_PROJECTION_TOPIC="$5"
export FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC=
export FDAI_SEMANTIC_TURN_OUTBOX_NAMESPACE="${3,,}"
python_path="$1/services/operator-service/src:$1/packages/service-contracts/src"
exec env -u AZURE_CONFIG_DIR \
    PYTHONPATH="$python_path${PYTHONPATH:+:$PYTHONPATH}" \
  "$2/.venv/bin/python" -m uvicorn fdai_operator_service.main:create_app \
  --factory --host 127.0.0.1 --port 8014 --no-access-log
""",
            "_",
            str(self.worktree),
            str(self.repo),
            self.run_id,
            self.request_topic,
            self.projection_topic,
        )
        console_command = (
            "/usr/bin/bash",
            "-c",
            """
set -euo pipefail
cd "$1/console"
export VITE_DEV_MODE=0
export VITE_LOCAL_AZURE_CLI_AUTH=0
export VITE_OPERATOR_API_BASE_URL=http://127.0.0.1:8014
export VITE_INGESTION_API_BASE_URL=http://127.0.0.1:8011
exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5275 --strictPort
""",
            "_",
            str(self.worktree),
        )
        return (
            ProcessSpec(
                label="core",
                command=core_command,
                command_label="python -m fdai",
                cwd=self.worktree,
                log_path=self.run_root / "core.log",
            ),
            ProcessSpec(
                label="operator",
                command=operator_command,
                command_label="python -m uvicorn fdai_operator_service.main:create_app :8014",
                cwd=self.worktree,
                log_path=self.run_root / "operator.log",
            ),
            ProcessSpec(
                label="console",
                command=console_command,
                command_label="vite :5275",
                cwd=self.worktree / "console",
                log_path=self.run_root / "console.log",
            ),
        )

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


def _resolve_source_revision(repo: Path, raw: str | None) -> str:
    revision = raw or _git_output(repo, "rev-parse", "HEAD")
    if not SOURCE_REVISION_PATTERN.fullmatch(revision):
        raise AssuranceRunError("source revision MUST be a full lowercase commit SHA")
    resolved = _git_output(repo, "rev-parse", f"{revision}^{{commit}}")
    if resolved != revision:
        raise AssuranceRunError("source revision does not resolve to the exact commit")
    return revision


async def _run_with_signal_provenance(runner: OntologyAssuranceRunner) -> int:
    """Retain a runner signal and let task cancellation execute owned cleanup."""
    loop = asyncio.get_running_loop()
    received_signal: asyncio.Future[signal.Signals] = loop.create_future()

    def record_signal(signal_value: signal.Signals) -> None:
        if not received_signal.done():
            received_signal.set_result(signal_value)

    installed: list[signal.Signals] = []
    for signal_value in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_value, record_signal, signal_value)
            installed.append(signal_value)
        except NotImplementedError:
            continue
    run_task = asyncio.create_task(runner.run())
    guarded_tasks: set[asyncio.Future[Any]] = {run_task, received_signal}
    try:
        done, _ = await asyncio.wait(
            guarded_tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if received_signal in done:
            signal_value = received_signal.result()
            runner.status.update(
                state="failed",
                termination={
                    "reason": "runner_signal",
                    "signal": signal_value.name,
                },
            )
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await run_task
            return 128 + int(signal_value)
        return run_task.result()
    finally:
        for signal_value in installed:
            loop.remove_signal_handler(signal_value)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--source-revision")
    parser.add_argument("--run-id")
    parser.add_argument("--status-path", type=Path)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--storage-state", type=Path)
    parser.add_argument("--prep-only", action="store_true")
    parser.add_argument("--detach", action="store_true")
    parser.add_argument("--internal-run", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def _main(argv: Sequence[str]) -> int:
    args = _parse_args(argv)
    repo = args.repo.resolve()
    source_revision = _resolve_source_revision(repo, args.source_revision)
    run_id = args.run_id or f"issue63-{source_revision[:10]}-{_utc_tag()}"
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise AssuranceRunError(
            "run id MUST be 1-64 ASCII letters, digits, dot, underscore, or dash"
        )
    status_path = (
        args.status_path
        or (repo / ".fdai" / "live-validation" / f"ontology-assurance-{run_id}.status.json")
    ).resolve()
    model_path = args.model_path or (
        repo / ".fdai" / "live-validation" / "resolved-models-semantic-gpt-4-1-2026-08-14.json"
    )
    storage_state = args.storage_state or (
        repo / ".fdai" / "live-validation" / "browser-entra-storage-state-5275.json"
    )
    if args.detach and not args.internal_run:
        runner_log = status_path.with_suffix(".runner.log")
        runner_log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(runner_log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        command = [
            sys.executable,
            "-m",
            "scripts.automation.run_ontology_assurance",
            "--repo",
            str(repo),
            "--source-revision",
            source_revision,
            "--run-id",
            run_id,
            "--status-path",
            str(status_path),
            "--model-path",
            str(model_path),
            "--storage-state",
            str(storage_state),
            "--internal-run",
        ]
        if args.prep_only:
            command.append("--prep-only")
        with os.fdopen(descriptor, "ab", buffering=0) as log_handle:
            process = subprocess.Popen(  # noqa: S603 - command invokes this repository script
                command,
                cwd=repo,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        print(json.dumps({"pid": process.pid, "run_id": run_id, "status_path": str(status_path)}))
        return 0

    lock_path = status_path.with_suffix(f"{status_path.suffix}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with lock_path.open("w", encoding="utf-8") as lock_handle:
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise AssuranceRunError("another runner owns this assurance status path") from error
        runner = OntologyAssuranceRunner(
            repo=repo,
            source_revision=source_revision,
            run_id=run_id,
            status_path=status_path,
            model_path=model_path,
            storage_state=storage_state,
            prep_only=args.prep_only,
        )
        return asyncio.run(_run_with_signal_provenance(runner))


if __name__ == "__main__":
    try:
        raise SystemExit(_main(sys.argv[1:]))
    except AssuranceRunError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
