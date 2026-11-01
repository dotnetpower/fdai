"""Production composition helper for ProgrammaticPipelineService."""

from __future__ import annotations

from collections.abc import Sequence

from fdai.core.programmatic_pipeline import (
    InMemoryProgrammaticPipelineStore,
    PipelineCapabilityAuthority,
    ProgrammaticPipelineService,
    ProgrammaticPipelineStore,
)
from fdai.core.sandbox import (
    ProgrammaticPipelineSandboxCatalog,
    ProgrammaticPipelineSandboxProfile,
)
from fdai.core.tools.executor import ToolExecutor
from fdai.shared.providers.programmatic_pipeline import ProgrammaticPipelineRunner

DEFAULT_PIPELINE_SANDBOX_PROFILES: tuple[ProgrammaticPipelineSandboxProfile, ...] = (
    ProgrammaticPipelineSandboxProfile(
        profile_id="pipeline.local-read",
        allowed_read_tools=frozenset(
            {
                "tool.read-inventory",
                "tool.read-metrics",
                "tool.read-logs",
                "tool.read-traces",
            }
        ),
        max_timeout_seconds=30,
        max_input_items=64,
        max_input_bytes=256_000,
        max_tool_calls=32,
        max_call_input_bytes=64_000,
        max_call_output_bytes=256_000,
        max_stdout_bytes=16_000,
        max_stderr_bytes=16_000,
        max_final_json_bytes=256_000,
    ),
)


def build_programmatic_pipeline_service(
    *,
    runner: ProgrammaticPipelineRunner,
    executor: ToolExecutor,
    store: ProgrammaticPipelineStore | None = None,
    sandbox_profiles: Sequence[ProgrammaticPipelineSandboxProfile] | None = None,
    authority: PipelineCapabilityAuthority | None = None,
) -> ProgrammaticPipelineService:
    """Compose ProgrammaticPipelineService over the registered ToolExecutor and store."""
    profiles = tuple(sandbox_profiles or DEFAULT_PIPELINE_SANDBOX_PROFILES)
    return ProgrammaticPipelineService(
        runner=runner,
        executor=executor,
        store=store or InMemoryProgrammaticPipelineStore(),
        sandbox_profiles=ProgrammaticPipelineSandboxCatalog(profiles),
        authority=authority or PipelineCapabilityAuthority(),
    )


__all__ = [
    "DEFAULT_PIPELINE_SANDBOX_PROFILES",
    "build_programmatic_pipeline_service",
]
