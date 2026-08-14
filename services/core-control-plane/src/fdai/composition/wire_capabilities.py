"""Capability bundle composition helpers for downstream forks."""

from __future__ import annotations

from dataclasses import replace

from fdai.core.capability_catalog import (
    CapabilityBundle,
    CapabilityRuntime,
    build_capability_references,
    default_capability_catalog,
)
from fdai.core.detection.configuration_drift_service import (
    ConfigurationBaselineSource,
    ConfigurationDriftService,
    ConfigurationObservationSource,
)
from fdai.core.tools.types import ToolArtifact
from fdai.core.working_context import ContextSelectionShadowRunner
from fdai.delivery.configuration_drift import build_configuration_drift_bundle
from fdai.shared.contracts.models import OntologyActionType, Workflow
from fdai.shared.providers.knowledge import KnowledgeSource

from ._helpers import Container


def default_capability_runtime() -> CapabilityRuntime:
    """Return the upstream discovery catalog with no executable bindings."""

    return CapabilityRuntime(catalog=default_capability_catalog())


def install_capability_bundle(
    container: Container,
    bundle: CapabilityBundle,
    *,
    reasoning_tools: tuple[ToolArtifact, ...] = (),
    action_types: tuple[OntologyActionType, ...] = (),
    context_selection_policies: tuple[str, ...] = (),
    workflows: tuple[Workflow, ...] = (),
) -> Container:
    """Validate and install one downstream capability bundle.

    The returned container is new and the input remains unchanged. ActionType
    and Workflow bindings are references only; invocation still goes through
    the control loop, risk gate, and existing executor paths.
    """

    runtime = container.capability_runtime.install(
        bundle,
        references=build_capability_references(
            reasoning_tools=reasoning_tools,
            action_types=action_types,
            context_selection_policies=context_selection_policies,
            workflows=workflows,
        ),
    )
    authority = container.context_selection_policy_authority
    shadow_runner = container.context_selection_shadow_runner
    if authority is not None:
        authority = authority.with_capability_runtime(runtime)
        if shadow_runner is not None:
            # A runner pinned to the pre-install authority would keep measuring a stale
            # candidate set; rebuild it on the refreshed authority and the same store.
            # Evaluations already scheduled on the previous runner still complete and
            # append to that shared store, but only the new runner can be drained.
            shadow_runner = ContextSelectionShadowRunner(
                authority=authority,
                store=shadow_runner.store,
                config=shadow_runner.config,
            )
    return replace(
        container,
        capability_runtime=runtime,
        context_selection_policy_authority=authority,
        context_selection_shadow_runner=shadow_runner,
    )


def bind_configuration_drift(
    container: Container,
    *,
    baseline_source: ConfigurationBaselineSource,
    observation_source: ConfigurationObservationSource,
    expected_version: str,
    expected_sha256: str,
    expected_scope: str,
    knowledge_source: KnowledgeSource | None = None,
) -> Container:
    """Return a new container with one server-pinned read-only drift capability."""

    service = ConfigurationDriftService(
        baseline_source=baseline_source,
        observation_source=observation_source,
        expected_version=expected_version,
        expected_sha256=expected_sha256,
        expected_scope=expected_scope,
        knowledge_source=knowledge_source,
    )
    return install_capability_bundle(
        container,
        build_configuration_drift_bundle(service),
    )


__all__ = [
    "bind_configuration_drift",
    "default_capability_runtime",
    "install_capability_bundle",
]
