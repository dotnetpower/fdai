"""Transport-neutral public protocols for evaluation hosts and drivers."""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator
from typing import Protocol, runtime_checkable

from fdai_evaluation_sdk.contracts import (
    ArtifactRef,
    ArtifactSpec,
    EvaluationRequest,
    EvaluationResult,
    EvaluationTask,
    ExternalValidationReceipt,
)

EVALUATION_API_VERSION = "1.0"


@runtime_checkable
class EvaluationSession(Protocol):
    """Authority-attenuated session returned by a public evaluation host."""

    @property
    def session_id(self) -> str: ...

    async def execute(self, task: EvaluationTask) -> EvaluationResult: ...

    async def publish_artifact(
        self,
        *,
        task_id: str,
        spec: ArtifactSpec,
        chunks: AsyncIterable[bytes],
    ) -> ArtifactRef: ...

    def read_artifact(self, artifact: ArtifactRef) -> AsyncIterator[bytes]: ...

    async def record_external_validation(self, receipt: ExternalValidationReceipt) -> None: ...

    async def close(self) -> None: ...


@runtime_checkable
class EvaluationHost(Protocol):
    """Public FDAI entry point that exposes no runtime implementation objects."""

    @property
    def api_version(self) -> str: ...

    async def open(self, request: EvaluationRequest) -> EvaluationSession: ...

    async def record_external_validation(self, receipt: ExternalValidationReceipt) -> None: ...


@runtime_checkable
class EvaluationAdapter(Protocol):
    """External harness lifecycle translated to neutral evaluation tasks."""

    adapter_id: str

    async def start(self) -> EvaluationRequest: ...

    async def next_task(self) -> EvaluationTask | None: ...

    async def submit(self, result: EvaluationResult) -> None: ...

    async def close(self) -> None: ...


__all__ = [
    "EVALUATION_API_VERSION",
    "EvaluationAdapter",
    "EvaluationHost",
    "EvaluationSession",
]
