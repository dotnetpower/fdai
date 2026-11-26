"""Run source-bound ontology assurance with fail-closed child supervision."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation.ontology_assurance_evidence import (
    AssuranceRunError,
    _bind_transport_evidence,
    _find_artifact,
    _read_artifact,
    full_artifact_accepted,
    strict_artifact_accepted,
    transport_delta_accepted,
)
from scripts.automation.ontology_assurance_execution import (
    OntologyAssuranceExecutionMixin,
    _git_output,
)
from scripts.automation.ontology_assurance_execution import (
    _workspace_patch_digest as _workspace_patch_digest,
)
from scripts.automation.ontology_assurance_preparation import (
    OntologyAssurancePreparationMixin,
)
from scripts.automation.ontology_assurance_supervisor import (
    AssuranceProcessSupervisor,
    AtomicRunStatus,
    RequiredChildExitedError,
)

SOURCE_REVISION_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
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
    "en-declaration_detail-1",
    "ko-declaration_detail-1",
    "en-release_evidence_health-1",
    "ko-release_evidence_health-1",
    "en-inventory_impact-1",
    "ko-inventory_impact-1",
    "en-rule_state_distinction-1",
    "ko-rule_state_distinction-1",
)


def _scratch_base() -> Path:
    """Resolve the transient run scratch base outside the repository."""
    configured = os.environ.get("FDAI_ASSURANCE_SCRATCH_ROOT")
    if configured:
        return Path(configured).expanduser()
    return Path(tempfile.gettempdir()) / "fdai-assurance"


def _utc_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # noqa: UP017


class OntologyAssuranceRunner(
    OntologyAssurancePreparationMixin,
    OntologyAssuranceExecutionMixin,
):
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
        self.scratch_root = _scratch_base() / run_id
        self.run_root = self.scratch_root / "stack"
        self.evidence_root = self.repo / ".fdai" / "live-validation"
        self.stack_log = self.run_root / "stack.log"
        self.request_topic = f"assurance.operator.semantic-turn.requests.{run_id.lower()}"
        self.projection_topic = f"assurance.core.semantic-turn.projections.{run_id.lower()}"
        self.strict_output = self.scratch_root / (
            f"ontology-query-22-cell-{run_id}-{source_revision}"
        )
        self.full_output = self.scratch_root / (
            f"ontology-query-100-case-{run_id}-{source_revision}"
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
                label="strict_v2",
                output=self.strict_output,
                checkpoint=self.strict_checkpoint,
                run_budget_ms=1_800_000,
                question_ids=STRICT_QUESTION_IDS,
            )
            if strict_exit.returncode != 0:
                raise AssuranceRunError(f"strict v2 22-cell phase exited {strict_exit.returncode}")
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
                phase="strict_v2",
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
                expected_count=22,
            ):
                raise AssuranceRunError("strict semantic topic counts do not match 22 live turns")
            strict_payload = _read_artifact(strict_artifact)
            if not strict_artifact_accepted(strict_payload, self.source_revision):
                raise AssuranceRunError("strict v2 22-cell artifact failed the immutable gate")
            strict_evidence = self._preserve_artifact(strict_artifact, self.strict_output)

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
            full_evidence = self._preserve_artifact(full_artifact, self.full_output)
            self.status.update(
                state="complete",
                phase="complete",
                termination=None,
                artifacts={
                    "strict": str(strict_evidence),
                    "seeded_100": str(full_evidence),
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
