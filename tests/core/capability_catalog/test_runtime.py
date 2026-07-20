"""Runtime capability bundle validation tests."""

from __future__ import annotations

import pytest

from fdai.core.capability_catalog import (
    Capability,
    CapabilityBinding,
    CapabilityBindingKind,
    CapabilityBundle,
    CapabilityCategory,
    CapabilityReferences,
    CapabilityRuntime,
    CapabilityRuntimeError,
    SideEffectClass,
    build_capability_references,
)
from fdai.core.prompts.types import PromptMode
from fdai.core.tools import CapabilityGate, ToolArtifact
from fdai.core.tools.testing import InMemoryToolProvider


def _capability(capability_id: str, *, mutating: bool = False) -> Capability:
    return Capability(
        capability_id=capability_id,
        name=capability_id,
        category=CapabilityCategory.REMEDIATION,
        summary="runtime test capability",
        side_effect_class=(SideEffectClass.EXECUTE if mutating else SideEffectClass.READ),
    )


def test_bundle_resolves_reasoning_tool_action_and_workflow() -> None:
    provider = InMemoryToolProvider()
    runtime = CapabilityRuntime().install(
        CapabilityBundle(
            capabilities=(
                _capability("evidence.audit"),
                _capability("ops.restart", mutating=True),
                _capability("process.review", mutating=True),
            ),
            bindings=(
                CapabilityBinding(
                    capability_id="evidence.audit",
                    kind=CapabilityBindingKind.REASONING_TOOL,
                    target_ref="audit.query",
                    provider_id="audit-provider",
                ),
                CapabilityBinding(
                    capability_id="ops.restart",
                    kind=CapabilityBindingKind.ACTION_TYPE,
                    target_ref="ops.restart-service",
                ),
                CapabilityBinding(
                    capability_id="process.review",
                    kind=CapabilityBindingKind.WORKFLOW,
                    target_ref="architecture-review",
                ),
            ),
            tool_providers={"audit-provider": provider},
        ),
        references=CapabilityReferences(
            reasoning_tools={"audit.query": "audit-provider"},
            action_types=frozenset({"ops.restart-service"}),
            workflows=frozenset({"architecture-review"}),
        ),
    )

    assert runtime.bound_capability_ids() == (
        "evidence.audit",
        "ops.restart",
        "process.review",
    )
    assert runtime.resolve("evidence.audit").provider is provider
    assert runtime.resolve("ops.restart").provider is None


def test_install_is_atomic_when_reference_is_unknown() -> None:
    runtime = CapabilityRuntime()
    bundle = CapabilityBundle(
        capabilities=(_capability("ops.unknown", mutating=True),),
        bindings=(
            CapabilityBinding(
                capability_id="ops.unknown",
                kind=CapabilityBindingKind.ACTION_TYPE,
                target_ref="ops.not-registered",
            ),
        ),
    )

    with pytest.raises(CapabilityRuntimeError, match="not registered"):
        runtime.install(bundle, references=CapabilityReferences())

    assert runtime.bound_capability_ids() == ()
    assert runtime.catalog.get("ops.unknown") is None


def test_catalog_projection_cannot_mutate_runtime() -> None:
    runtime = CapabilityRuntime()
    projection = runtime.catalog
    projection.register(_capability("local.only"))

    assert runtime.catalog.get("local.only") is None


def test_reasoning_tool_requires_registered_provider() -> None:
    bundle = CapabilityBundle(
        capabilities=(_capability("evidence.audit"),),
        bindings=(
            CapabilityBinding(
                capability_id="evidence.audit",
                kind=CapabilityBindingKind.REASONING_TOOL,
                target_ref="audit.query",
                provider_id="missing",
            ),
        ),
    )

    with pytest.raises(CapabilityRuntimeError, match="provider 'missing'"):
        CapabilityRuntime().install(
            bundle,
            references=CapabilityReferences(reasoning_tools={"audit.query": "missing"}),
        )


def test_bundle_rejects_unreferenced_provider() -> None:
    provider = InMemoryToolProvider()

    with pytest.raises(CapabilityRuntimeError, match="unreferenced"):
        CapabilityRuntime().install(
            CapabilityBundle(tool_providers={"unused": provider}),
            references=CapabilityReferences(),
        )


def test_reasoning_tool_provider_must_match_artifact_declaration() -> None:
    provider = InMemoryToolProvider()
    bundle = CapabilityBundle(
        capabilities=(_capability("evidence.audit"),),
        bindings=(
            CapabilityBinding(
                capability_id="evidence.audit",
                kind=CapabilityBindingKind.REASONING_TOOL,
                target_ref="audit.query",
                provider_id="fork-provider",
            ),
        ),
        tool_providers={"fork-provider": provider},
    )

    with pytest.raises(CapabilityRuntimeError, match="declares provider"):
        CapabilityRuntime().install(
            bundle,
            references=CapabilityReferences(reasoning_tools={"audit.query": "catalog-provider"}),
        )


def test_reference_builder_uses_loaded_catalog_objects() -> None:
    artifact = ToolArtifact(
        id="audit.query",
        version=1,
        description="query audit",
        input_schema={"type": "object"},
        capability_gate=CapabilityGate(None, None, 0.0),
        allowlist=None,
        output_wrapper=None,
        default_mode=PromptMode.SHADOW,
        provider="AuditLogQueryProvider",
        provenance_source="test",
    )

    references = build_capability_references(
        reasoning_tools=(artifact,),
        context_selection_policies=("candidate-v1@1.0.0",),
    )

    assert references.reasoning_tools == {"audit.query": "AuditLogQueryProvider"}
    assert references.context_selection_policies == frozenset({"candidate-v1@1.0.0"})


def test_context_selection_policy_binding_is_reference_only() -> None:
    runtime = CapabilityRuntime().install(
        CapabilityBundle(
            capabilities=(_capability("context.selection.candidate"),),
            bindings=(
                CapabilityBinding(
                    capability_id="context.selection.candidate",
                    kind=CapabilityBindingKind.CONTEXT_SELECTION_POLICY,
                    target_ref="candidate-v1@1.0.0",
                ),
            ),
        ),
        references=CapabilityReferences(
            context_selection_policies=frozenset({"candidate-v1@1.0.0"})
        ),
    )

    resolved = runtime.resolve("context.selection.candidate")

    assert resolved.binding.target_ref == "candidate-v1@1.0.0"
    assert resolved.provider is None
