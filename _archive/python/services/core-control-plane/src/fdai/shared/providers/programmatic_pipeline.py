"""Provider-neutral contracts for isolated programmatic pipeline runners."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class PipelineRunnerStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class GeneratedPipelineClientContract:
    module_name: str
    class_name: str
    allowed_tools: tuple[str, ...]
    source: str
    source_digest: str


@dataclass(frozen=True, slots=True)
class PipelineRunSpec:
    run_id: str
    source: str
    source_digest: str
    input_json: tuple[str, ...]
    capability_token: str
    client: GeneratedPipelineClientContract
    timeout_seconds: float
    max_stdout_bytes: int
    max_stderr_bytes: int
    max_final_json_bytes: int


@dataclass(frozen=True, slots=True)
class PipelineToolCall:
    run_id: str
    capability_token: str
    call_id: str
    tool_id: str
    arguments_json: str


@dataclass(frozen=True, slots=True)
class PipelineToolResponse:
    ok: bool
    output_json: str | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class PipelineRunnerOutput:
    status: PipelineRunnerStatus
    stdout: str
    stderr: str
    final_json: str | None
    duration_ms: int
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    final_json_truncated: bool = False
    detail: str | None = None


class PipelineToolBroker(Protocol):
    async def dispatch(self, call: PipelineToolCall) -> PipelineToolResponse: ...


class ProgrammaticPipelineRunner(Protocol):
    async def run(
        self,
        spec: PipelineRunSpec,
        *,
        broker: PipelineToolBroker,
    ) -> PipelineRunnerOutput: ...

    async def cancel(self, run_id: str) -> bool: ...


__all__ = [
    "GeneratedPipelineClientContract",
    "PipelineRunSpec",
    "PipelineRunnerOutput",
    "PipelineRunnerStatus",
    "PipelineToolBroker",
    "PipelineToolCall",
    "PipelineToolResponse",
    "ProgrammaticPipelineRunner",
]
