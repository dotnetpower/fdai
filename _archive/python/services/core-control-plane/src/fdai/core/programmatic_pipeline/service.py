"""Validate, authorize, run, and persist one reviewed programmatic pipeline."""

from __future__ import annotations

from fdai.core.programmatic_pipeline.broker import ProgrammaticPipelineBroker
from fdai.core.programmatic_pipeline.capability import PipelineCapabilityAuthority
from fdai.core.programmatic_pipeline.client import generate_pipeline_client
from fdai.core.programmatic_pipeline.models import (
    ProgrammaticPipelineStats,
    ProgrammaticPipelineStatus,
    ProgrammaticToolPipelineRequest,
    ProgrammaticToolPipelineResult,
)
from fdai.core.programmatic_pipeline.store import ProgrammaticPipelineStore
from fdai.core.python_task.validator import validate_programmatic_pipeline_source
from fdai.core.sandbox.profiles import ProgrammaticPipelineSandboxCatalog
from fdai.core.tools.executor import ToolExecutor
from fdai.shared.providers.programmatic_pipeline import (
    PipelineRunnerOutput,
    PipelineRunnerStatus,
    PipelineRunSpec,
    ProgrammaticPipelineRunner,
)


class ProgrammaticPipelineService:
    def __init__(
        self,
        *,
        runner: ProgrammaticPipelineRunner,
        executor: ToolExecutor,
        store: ProgrammaticPipelineStore,
        sandbox_profiles: ProgrammaticPipelineSandboxCatalog,
        authority: PipelineCapabilityAuthority | None = None,
    ) -> None:
        self._runner = runner
        self._executor = executor
        self._store = store
        self._sandbox_profiles = sandbox_profiles
        self._authority = authority or PipelineCapabilityAuthority()

    async def run(
        self,
        request: ProgrammaticToolPipelineRequest,
    ) -> ProgrammaticToolPipelineResult:
        prior = await self._store.result_for(request.idempotency_key)
        if prior is not None:
            return prior
        self._sandbox_profiles.constrain(request)
        validation = validate_programmatic_pipeline_source(request.reviewed_source)
        if validation.source_digest != request.reviewed_source_digest:
            return await self._rejected(request, "reviewed source digest mismatch")
        if not validation.valid:
            codes = ",".join(sorted({issue.code for issue in validation.issues}))
            return await self._rejected(request, f"source policy rejected: {codes}")

        capability = self._authority.issue(
            run_id=request.run_id,
            allowed_tools=request.allowed_read_tools,
            ttl_seconds=request.limits.timeout_seconds + 5,
            max_calls=request.limits.max_tool_calls,
            max_input_bytes=request.limits.max_call_input_bytes,
        )
        client = generate_pipeline_client(request.allowed_read_tools)
        broker = ProgrammaticPipelineBroker(
            authority=self._authority,
            executor=self._executor,
            store=self._store,
            max_output_bytes=request.limits.max_call_output_bytes,
        )
        try:
            try:
                output = await self._runner.run(
                    PipelineRunSpec(
                        run_id=request.run_id,
                        source=request.reviewed_source,
                        source_digest=request.reviewed_source_digest,
                        input_json=request.input_json,
                        capability_token=capability.token,
                        client=client,
                        timeout_seconds=request.limits.timeout_seconds,
                        max_stdout_bytes=request.limits.max_stdout_bytes,
                        max_stderr_bytes=request.limits.max_stderr_bytes,
                        max_final_json_bytes=request.limits.max_final_json_bytes,
                    ),
                    broker=broker,
                )
            except Exception as exc:  # noqa: BLE001 - provider boundary
                output = PipelineRunnerOutput(
                    status=PipelineRunnerStatus.INCOMPLETE,
                    stdout="",
                    stderr="",
                    final_json=None,
                    duration_ms=0,
                    detail=f"runner adapter failed: {type(exc).__name__}",
                )
        finally:
            self._authority.revoke(request.run_id)

        receipts = await self._store.calls_for(request.run_id)
        status = _STATUS_MAP[output.status]
        complete = status is ProgrammaticPipelineStatus.SUCCEEDED and output.final_json is not None
        result = ProgrammaticToolPipelineResult(
            run_id=request.run_id,
            status=status,
            source_digest=request.reviewed_source_digest,
            stdout=output.stdout,
            stderr=output.stderr,
            final_json=output.final_json if complete else None,
            receipt_refs=tuple(item.receipt_ref for item in receipts),
            stats=ProgrammaticPipelineStats(
                tool_calls=len(receipts),
                succeeded_calls=sum(item.status.value == "succeeded" for item in receipts),
                failed_calls=sum(item.status.value != "succeeded" for item in receipts),
                input_bytes=sum(item.input_bytes for item in receipts),
                output_bytes=sum(item.output_bytes for item in receipts),
                duration_ms=output.duration_ms,
            ),
            complete=complete,
            detail=output.detail,
            truncated=(
                output.stdout_truncated or output.stderr_truncated or output.final_json_truncated
            ),
        )
        await self._store.complete(idempotency_key=request.idempotency_key, result=result)
        return result

    async def cancel(self, run_id: str) -> bool:
        return await self._runner.cancel(run_id)

    async def _rejected(
        self,
        request: ProgrammaticToolPipelineRequest,
        detail: str,
    ) -> ProgrammaticToolPipelineResult:
        result = ProgrammaticToolPipelineResult(
            run_id=request.run_id,
            status=ProgrammaticPipelineStatus.REJECTED,
            source_digest=request.reviewed_source_digest,
            stdout="",
            stderr="",
            final_json=None,
            receipt_refs=(),
            stats=ProgrammaticPipelineStats(0, 0, 0, 0, 0, 0),
            complete=False,
            detail=detail,
        )
        await self._store.complete(idempotency_key=request.idempotency_key, result=result)
        return result


_STATUS_MAP = {
    PipelineRunnerStatus.SUCCEEDED: ProgrammaticPipelineStatus.SUCCEEDED,
    PipelineRunnerStatus.FAILED: ProgrammaticPipelineStatus.FAILED,
    PipelineRunnerStatus.TIMED_OUT: ProgrammaticPipelineStatus.TIMED_OUT,
    PipelineRunnerStatus.CANCELLED: ProgrammaticPipelineStatus.CANCELLED,
    PipelineRunnerStatus.INCOMPLETE: ProgrammaticPipelineStatus.INCOMPLETE,
}


__all__ = ["ProgrammaticPipelineService"]
