"""Resolve verified adaptive model targets without binding runtime services."""

from __future__ import annotations

import logging
from collections.abc import Callable

from fdai.delivery.azure.llm.adaptive_answer import (
    AdaptiveModelTarget,
    AzureOpenAIAdaptiveModelConfig,
)
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.rule_catalog.schema.llm_resolver import CapabilityStatus, ResolvedModels

from .semantic_query_model_targets import model_target_for_capability

_LOGGER = logging.getLogger(__name__)


def resolved_model_config(
    resolved: ResolvedModels,
    *,
    endpoint: str | None,
    endpoint_resolver: Callable[[str], str] | None,
    held_capabilities: frozenset[str],
    timeout_seconds: float,
    max_tokens: int,
    primary_capability: str = "t1.judge",
    reviewer_capability: str | None = None,
    escalation_capability: str = "t2.reasoner.primary",
) -> AzureOpenAIAdaptiveModelConfig | None:
    """Resolve independent author, reviewer, and optional refinement targets."""
    narrators = t1_narrator_targets(resolved, held_capabilities)
    primary = (
        narrators[0]
        if primary_capability == "t1.judge" and narrators
        else resolve_target(
            resolved,
            primary_capability,
            endpoint=endpoint,
            endpoint_resolver=endpoint_resolver,
            held_capabilities=held_capabilities,
        )
    )
    reviewer = (
        resolve_target(
            resolved,
            reviewer_capability,
            endpoint=endpoint,
            endpoint_resolver=endpoint_resolver,
            held_capabilities=held_capabilities,
        )
        if reviewer_capability is not None
        else next(
            (item for item in narrators if primary is not None and item.independent_of(primary)),
            None,
        )
    )
    if primary is None or reviewer is None:
        return None
    try:
        escalation = resolve_target(
            resolved,
            escalation_capability,
            endpoint=endpoint,
            endpoint_resolver=endpoint_resolver,
            held_capabilities=held_capabilities,
        )
    except (LookupError, ValueError):
        _LOGGER.warning("adaptive_refinement_unavailable", extra={"reason": "invalid_binding"})
        escalation = None
    if escalation is not None and not reviewer.independent_of(escalation):
        _LOGGER.warning("adaptive_refinement_unavailable", extra={"reason": "not_independent"})
        escalation = None
    return AzureOpenAIAdaptiveModelConfig(
        primary=primary,
        reviewer=reviewer,
        escalation=escalation,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
    )


def t1_narrator_targets(
    resolved: ResolvedModels,
    held_capabilities: frozenset[str],
) -> tuple[AdaptiveModelTarget, ...]:
    """Return eligible narrator candidates without weakening capability holds."""
    if held_capabilities & {"t1.judge", "t1.narrator"}:
        return ()
    metadata = {item.name: item for item in resolved.capabilities}
    judge = metadata.get("t1.judge")
    if judge is not None and judge.status not in {
        CapabilityStatus.RESOLVED,
        CapabilityStatus.CAPACITY_REDUCED,
    }:
        return ()
    candidates = resolved.narrator_candidates or (
        (resolved.narrator,) if resolved.narrator is not None else ()
    )
    result: list[AdaptiveModelTarget] = []
    for candidate in candidates:
        declared = metadata.get(candidate.deployment)
        if (
            candidate.deployment in held_capabilities
            or declared is None
            or declared.status not in {CapabilityStatus.RESOLVED, CapabilityStatus.CAPACITY_REDUCED}
            or not declared.publisher
            or not declared.family
        ):
            continue
        result.append(
            AdaptiveModelTarget(
                target=ModelRequestTarget(
                    endpoint=candidate.endpoint,
                    deployment=candidate.deployment,
                    api_version=candidate.api_version,
                    api_style=candidate.api_style,
                    auth_audience=candidate.auth_audience,
                ),
                publisher=declared.publisher,
                family=declared.family,
                structured_output=False,
            )
        )
    return tuple(result)


def resolve_target(
    resolved: ResolvedModels,
    capability: str,
    *,
    endpoint: str | None,
    endpoint_resolver: Callable[[str], str] | None,
    held_capabilities: frozenset[str],
) -> AdaptiveModelTarget | None:
    """Resolve one eligible capability to a verified provider request target."""
    resolved_capability = next(
        (item for item in resolved.capabilities if item.name == capability), None
    )
    if resolved_capability is not None and resolved_capability.status not in {
        CapabilityStatus.RESOLVED,
        CapabilityStatus.CAPACITY_REDUCED,
    }:
        return None
    target = model_target_for_capability(
        resolved,
        capability,
        endpoint=endpoint,
        endpoint_resolver=endpoint_resolver,
        held_capabilities=held_capabilities,
    )
    if target is None:
        return None
    binding = next(
        (binding for binding in resolved.endpoint_bindings if binding.capability == capability),
        None,
    )
    publisher: str | None
    family: str | None
    if binding is not None:
        publisher, family = binding.publisher, binding.family
    else:
        if resolved_capability is None:
            return None
        publisher, family = resolved_capability.publisher, resolved_capability.family
    if not publisher or not family:
        return None
    return AdaptiveModelTarget(
        target=target,
        publisher=publisher,
        family=family,
        structured_output=binding.features.structured_output if binding is not None else True,
    )


__all__ = ["resolve_target", "resolved_model_config", "t1_narrator_targets"]
