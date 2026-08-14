"""Resolve separate T1 and T2 semantic-planning request targets."""

from __future__ import annotations

from collections.abc import Callable

from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.rule_catalog.schema.llm_resolver import CapabilityStatus, ResolvedModels
from fdai.rule_catalog.schema.model_endpoint import ModelAuthKind


def t1_model_targets(
    resolved: ResolvedModels,
    *,
    endpoint: str | None,
    endpoint_resolver: Callable[[str], str] | None,
) -> tuple[ModelRequestTarget, ...]:
    """Return resolved narrator or T1 judge targets in preference order."""
    candidates = resolved.narrator_candidates
    if not candidates and resolved.narrator is not None:
        candidates = (resolved.narrator,)
    targets = [
        ModelRequestTarget(
            endpoint=candidate.endpoint,
            deployment=candidate.deployment,
            api_version=candidate.api_version,
            api_style=candidate.api_style,
            auth_audience=candidate.auth_audience,
        )
        for candidate in candidates
    ]
    if not targets:
        judge = _target_for_capability(
            resolved,
            "t1.judge",
            endpoint=endpoint,
            endpoint_resolver=endpoint_resolver,
        )
        if judge is not None:
            targets.append(judge)
    return _unique_targets(targets)


def t2_model_targets(
    resolved: ResolvedModels,
    *,
    endpoint: str | None,
    endpoint_resolver: Callable[[str], str] | None,
) -> tuple[ModelRequestTarget, ...]:
    """Return optional T2 escalation targets without borrowing T1 capacity."""
    targets: list[ModelRequestTarget] = [
        ModelRequestTarget(
            endpoint=candidate.endpoint,
            deployment=candidate.deployment,
            api_version=candidate.api_version,
            api_style=candidate.api_style,
            auth_audience=candidate.auth_audience,
        )
        for candidate in resolved.reasoner_primary_candidates
    ]
    if not targets:
        primary = _target_for_capability(
            resolved,
            "t2.reasoner.primary",
            endpoint=endpoint,
            endpoint_resolver=endpoint_resolver,
        )
        if primary is not None:
            targets.append(primary)
    return _unique_targets(targets)


def _unique_targets(targets: list[ModelRequestTarget]) -> tuple[ModelRequestTarget, ...]:
    unique: dict[tuple[str, str, str | None], ModelRequestTarget] = {}
    for target in targets:
        unique.setdefault((target.endpoint, target.deployment, target.api_version), target)
    return tuple(unique.values())


def _target_for_capability(
    resolved: ResolvedModels,
    capability_id: str,
    *,
    endpoint: str | None,
    endpoint_resolver: Callable[[str], str] | None,
) -> ModelRequestTarget | None:
    binding = next(
        (item for item in resolved.endpoint_bindings if item.capability == capability_id),
        None,
    )
    if binding is not None:
        if (
            binding.auth_kind is not ModelAuthKind.ENTRA
            or binding.auth_audience is None
            or endpoint_resolver is None
        ):
            return None
        return ModelRequestTarget(
            endpoint=endpoint_resolver(binding.endpoint_ref),
            deployment=binding.deployment,
            api_style=binding.api_style,
            api_version=binding.api_version or "2024-06-01",
            auth_audience=binding.auth_audience,
            route_kind=binding.route_kind,
            binding_id=binding.binding_id,
        )
    capability = next(
        (
            item
            for item in resolved.capabilities
            if item.name == capability_id
            and item.status in {CapabilityStatus.RESOLVED, CapabilityStatus.CAPACITY_REDUCED}
        ),
        None,
    )
    if capability is None or endpoint is None:
        return None
    return ModelRequestTarget(
        endpoint=endpoint,
        deployment=capability.name,
        api_version="2024-06-01",
    )


__all__ = ["t1_model_targets", "t2_model_targets"]
