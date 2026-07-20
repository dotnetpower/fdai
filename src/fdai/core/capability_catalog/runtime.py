"""Validated runtime bindings for downstream capability bundles.

The discovery catalog remains inert metadata. This module adds the startup
linkage from that metadata to an existing reasoning tool, ActionType, or
Workflow without creating a second execution path. Mutating targets still
re-enter the normal risk-gate and executor pipeline.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from fdai.core.capability_catalog.catalog import Capability, CapabilityCatalog
from fdai.core.tools.executor import ToolProvider
from fdai.core.tools.types import ToolArtifact
from fdai.shared.contracts.models import OntologyActionType, Workflow


class CapabilityBindingKind(StrEnum):
    """Typed pipeline surface a capability resolves to."""

    REASONING_TOOL = "reasoning_tool"
    ACTION_TYPE = "action_type"
    CONTEXT_SELECTION_POLICY = "context_selection_policy"
    WORKFLOW = "workflow"


@dataclass(frozen=True, slots=True)
class CapabilityBinding:
    """One capability-to-pipeline reference supplied by a fork."""

    capability_id: str
    kind: CapabilityBindingKind
    target_ref: str
    provider_id: str | None = None

    def __post_init__(self) -> None:
        if not self.capability_id or not self.target_ref:
            raise ValueError("capability_id and target_ref MUST be non-empty")
        if self.kind is CapabilityBindingKind.REASONING_TOOL and not self.provider_id:
            raise ValueError("reasoning_tool bindings MUST declare provider_id")
        if self.kind is not CapabilityBindingKind.REASONING_TOOL and self.provider_id is not None:
            raise ValueError("only reasoning_tool bindings MAY declare provider_id")


@dataclass(frozen=True, slots=True)
class CapabilityReferences:
    """Catalog ids available at the composition boundary."""

    reasoning_tools: Mapping[str, str | None] = field(default_factory=dict)
    action_types: frozenset[str] = frozenset()
    context_selection_policies: frozenset[str] = frozenset()
    workflows: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reasoning_tools",
            MappingProxyType(dict(self.reasoning_tools)),
        )
        object.__setattr__(self, "action_types", frozenset(self.action_types))
        object.__setattr__(
            self,
            "context_selection_policies",
            frozenset(self.context_selection_policies),
        )
        object.__setattr__(self, "workflows", frozenset(self.workflows))


@dataclass(frozen=True, slots=True)
class CapabilityBundle:
    """Additive downstream capability registration unit."""

    capabilities: tuple[Capability, ...] = ()
    bindings: tuple[CapabilityBinding, ...] = ()
    tool_providers: Mapping[str, ToolProvider] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ResolvedCapability:
    """Validated metadata, target, and optional reasoning-tool provider."""

    capability: Capability
    binding: CapabilityBinding
    provider: ToolProvider | None


class CapabilityRuntimeError(ValueError):
    """A capability bundle failed startup validation."""


class CapabilityRuntime:
    """Immutable, atomically extended runtime capability registry."""

    __slots__ = ("_bindings", "_catalog", "_tool_providers")

    def __init__(
        self,
        *,
        catalog: CapabilityCatalog | None = None,
        bindings: Mapping[str, CapabilityBinding] | None = None,
        tool_providers: Mapping[str, ToolProvider] | None = None,
    ) -> None:
        self._catalog = catalog or CapabilityCatalog()
        self._bindings = MappingProxyType(dict(bindings or {}))
        self._tool_providers = MappingProxyType(dict(tool_providers or {}))

    @property
    def catalog(self) -> CapabilityCatalog:
        return CapabilityCatalog(self._catalog.list(enabled_only=False))

    @property
    def tool_providers(self) -> Mapping[str, ToolProvider]:
        return self._tool_providers

    def install(
        self,
        bundle: CapabilityBundle,
        *,
        references: CapabilityReferences,
    ) -> CapabilityRuntime:
        """Validate and return a new runtime; never mutate the current one."""

        catalog = CapabilityCatalog(self._catalog.list(enabled_only=False))
        try:
            for capability in bundle.capabilities:
                catalog.register(capability)
        except ValueError as exc:
            raise CapabilityRuntimeError(f"capability registration failed: {exc}") from exc

        providers = dict(self._tool_providers)
        for provider_id, provider in bundle.tool_providers.items():
            if not provider_id:
                raise CapabilityRuntimeError("tool provider ids MUST be non-empty")
            if provider_id in providers:
                raise CapabilityRuntimeError(f"duplicate tool provider {provider_id!r}")
            providers[provider_id] = provider

        bindings = dict(self._bindings)
        for binding in bundle.bindings:
            if binding.capability_id in bindings:
                raise CapabilityRuntimeError(
                    f"duplicate capability binding {binding.capability_id!r}"
                )
            if catalog.get(binding.capability_id) is None:
                raise CapabilityRuntimeError(
                    f"binding references unknown capability {binding.capability_id!r}"
                )
            _validate_binding(binding, references=references, providers=providers)
            bindings[binding.capability_id] = binding

        used_provider_ids = {
            binding.provider_id for binding in bindings.values() if binding.provider_id is not None
        }
        unreferenced = set(bundle.tool_providers) - used_provider_ids
        if unreferenced:
            names = ", ".join(sorted(unreferenced))
            raise CapabilityRuntimeError(f"unreferenced tool providers: {names}")

        return CapabilityRuntime(
            catalog=catalog,
            bindings=bindings,
            tool_providers=providers,
        )

    def resolve(self, capability_id: str) -> ResolvedCapability:
        try:
            binding = self._bindings[capability_id]
        except KeyError as exc:
            raise LookupError(f"capability {capability_id!r} is not runtime-bound") from exc
        capability = self._catalog.get(capability_id)
        if capability is None:  # pragma: no cover - constructor/install invariant
            raise LookupError(f"capability {capability_id!r} has no metadata")
        provider = (
            self._tool_providers[binding.provider_id] if binding.provider_id is not None else None
        )
        return ResolvedCapability(
            capability=capability,
            binding=binding,
            provider=provider,
        )

    def bound_capability_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._bindings))


def _validate_binding(
    binding: CapabilityBinding,
    *,
    references: CapabilityReferences,
    providers: Mapping[str, ToolProvider],
) -> None:
    available_by_kind = {
        CapabilityBindingKind.REASONING_TOOL: references.reasoning_tools,
        CapabilityBindingKind.ACTION_TYPE: references.action_types,
        CapabilityBindingKind.CONTEXT_SELECTION_POLICY: references.context_selection_policies,
        CapabilityBindingKind.WORKFLOW: references.workflows,
    }
    if binding.target_ref not in available_by_kind[binding.kind]:
        raise CapabilityRuntimeError(
            f"{binding.kind.value} target {binding.target_ref!r} is not registered"
        )
    if binding.provider_id is not None and binding.provider_id not in providers:
        raise CapabilityRuntimeError(f"tool provider {binding.provider_id!r} is not registered")
    if binding.kind is CapabilityBindingKind.REASONING_TOOL:
        declared_provider = references.reasoning_tools[binding.target_ref]
        if declared_provider != binding.provider_id:
            raise CapabilityRuntimeError(
                f"reasoning tool {binding.target_ref!r} declares provider "
                f"{declared_provider!r}, not {binding.provider_id!r}"
            )


def build_capability_references(
    *,
    reasoning_tools: Iterable[ToolArtifact] = (),
    action_types: Iterable[OntologyActionType] = (),
    context_selection_policies: Iterable[str] = (),
    workflows: Iterable[Workflow] = (),
) -> CapabilityReferences:
    """Build cross-reference inputs directly from loaded runtime catalogs."""

    return CapabilityReferences(
        reasoning_tools={artifact.id: artifact.provider for artifact in reasoning_tools},
        action_types=frozenset(action_type.name for action_type in action_types),
        context_selection_policies=frozenset(context_selection_policies),
        workflows=frozenset(workflow.name for workflow in workflows),
    )


__all__ = [
    "CapabilityBinding",
    "CapabilityBindingKind",
    "CapabilityBundle",
    "CapabilityReferences",
    "CapabilityRuntime",
    "CapabilityRuntimeError",
    "ResolvedCapability",
    "build_capability_references",
]
