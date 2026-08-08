"""Azure-compatible submission adapter for isolated programmatic pipelines."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from fdai.shared.providers.programmatic_pipeline import (
    PipelineRunnerOutput,
    PipelineRunSpec,
    PipelineToolBroker,
)


class AzurePipelineSubmissionClient(Protocol):
    """Submit to a pre-provisioned isolated job through managed identity wiring."""

    async def submit(
        self,
        spec: PipelineRunSpec,
        *,
        broker: PipelineToolBroker,
    ) -> PipelineRunnerOutput: ...

    async def cancel(self, run_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class AzureIsolatedPipelineRunnerConfig:
    max_submission_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        if not 1_024 <= self.max_submission_bytes <= 10_000_000:
            raise ValueError("Azure pipeline max_submission_bytes MUST be in [1024, 10000000]")


class AzureIsolatedPipelineRunner:
    """Strict adapter only; resource provisioning and credentials stay outside it."""

    def __init__(
        self,
        *,
        client: AzurePipelineSubmissionClient,
        config: AzureIsolatedPipelineRunnerConfig | None = None,
    ) -> None:
        self._client = client
        self._config = config or AzureIsolatedPipelineRunnerConfig()

    async def run(
        self,
        spec: PipelineRunSpec,
        *,
        broker: PipelineToolBroker,
    ) -> PipelineRunnerOutput:
        if hashlib.sha256(spec.source.encode("utf-8")).hexdigest() != spec.source_digest:
            raise ValueError("Azure pipeline source digest mismatch")
        client_digest = hashlib.sha256(spec.client.source.encode("utf-8")).hexdigest()
        if client_digest != spec.client.source_digest:
            raise ValueError("Azure generated client digest mismatch")
        if not spec.capability_token:
            raise ValueError("Azure pipeline capability token MUST be non-empty")
        submission_bytes = sum(
            len(value.encode("utf-8"))
            for value in (
                spec.source,
                spec.client.source,
                *spec.input_json,
            )
        )
        if submission_bytes > self._config.max_submission_bytes:
            raise ValueError("Azure pipeline submission exceeds its byte limit")
        return await self._client.submit(spec, broker=broker)

    async def cancel(self, run_id: str) -> bool:
        return await self._client.cancel(run_id)


__all__ = [
    "AzureIsolatedPipelineRunner",
    "AzureIsolatedPipelineRunnerConfig",
    "AzurePipelineSubmissionClient",
]
