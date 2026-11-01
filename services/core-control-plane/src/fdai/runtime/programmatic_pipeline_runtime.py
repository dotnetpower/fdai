"""Production composition helper for ProgrammaticPipelineService."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class ProgrammaticPipelineRuntimeBundle:
    """Bundled runtime state for ProgrammaticPipelineService execution."""

    service: ProgrammaticPipelineService
    store: ProgrammaticPipelineStore
    sandbox_profiles: ProgrammaticPipelineSandboxCatalog
    authority: PipelineCapabilityAuthority


def build_programmatic_pipeline_runtime(
    *,
    runner: ProgrammaticPipelineRunner,
    executor: ToolExecutor,
    store: ProgrammaticPipelineStore | None = None,
    sandbox_profiles: Sequence[ProgrammaticPipelineSandboxProfile] | None = None,
    authority: PipelineCapabilityAuthority | None = None,
) -> ProgrammaticPipelineRuntimeBundle:
    """Compose a ProgrammaticPipelineRuntimeBundle over the registered ToolExecutor and store."""
    resolved_store = store or InMemoryProgrammaticPipelineStore()
    catalog = ProgrammaticPipelineSandboxCatalog(
        tuple(sandbox_profiles or DEFAULT_PIPELINE_SANDBOX_PROFILES)
    )
    resolved_authority = authority or PipelineCapabilityAuthority()
    service = ProgrammaticPipelineService(
        runner=runner,
        executor=executor,
        store=resolved_store,
        sandbox_profiles=catalog,
        authority=resolved_authority,
    )
    return ProgrammaticPipelineRuntimeBundle(
        service=service,
        store=resolved_store,
        sandbox_profiles=catalog,
        authority=resolved_authority,
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
    return build_programmatic_pipeline_runtime(
        runner=runner,
        executor=executor,
        store=store,
        sandbox_profiles=sandbox_profiles,
        authority=authority,
    ).service


__all__ = [
    "DEFAULT_PIPELINE_SANDBOX_PROFILES",
    "ProgrammaticPipelineRuntimeBundle",
    "build_programmatic_pipeline_runtime",
    "build_programmatic_pipeline_service",
]
