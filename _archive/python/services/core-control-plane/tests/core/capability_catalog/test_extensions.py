"""Trust and atomicity tests for capability extension lifecycle."""

from __future__ import annotations

import hashlib

import pytest
from fdai.core.capability_catalog import (
    Capability,
    CapabilityBinding,
    CapabilityBindingKind,
    CapabilityBundle,
    CapabilityCategory,
    CapabilityReferences,
    ExtensionLifecycleError,
    ExtensionManager,
    ExtensionManifest,
    ExtensionPackage,
    ExtensionState,
    SideEffectClass,
)
from fdai.core.prompts.types import PromptMode
from fdai.core.tools import CapabilityGate, ToolArtifact
from fdai.core.tools.testing import InMemoryToolProvider
from fdai.shared.telemetry import InMemoryRoutingTransitionSink

_ARCHIVE = b"synthetic signed capability archive"


class _Verifier:
    def __init__(self, trusted: bool = True) -> None:
        self.trusted = trusted

    def verify(self, manifest: ExtensionManifest, archive: bytes) -> bool:
        return self.trusted


def _package(*, minimum: str = "1.0.0", digest: str | None = None) -> ExtensionPackage:
    capability = Capability(
        capability_id="example.inspect",
        name="Inspect example state",
        category=CapabilityCategory.INVESTIGATION,
        summary="Inspect a synthetic state projection.",
        side_effect_class=SideEffectClass.READ,
        required_role="reader",
    )
    return ExtensionPackage(
        manifest=ExtensionManifest(
            extension_id="example.inspect",
            version="1.0.0",
            source="source:example.inspect",
            archive_sha256=digest or hashlib.sha256(_ARCHIVE).hexdigest(),
            min_host_version=minimum,
            capability_ids=(capability.capability_id,),
        ),
        bundle=CapabilityBundle(
            capabilities=(capability,),
            bindings=(
                CapabilityBinding(
                    capability_id=capability.capability_id,
                    kind=CapabilityBindingKind.ACTION_TYPE,
                    target_ref="ops.inspect-example",
                ),
            ),
        ),
    )


def _manager() -> ExtensionManager:
    return ExtensionManager(
        host_version="1.2.0",
        references=CapabilityReferences(action_types=frozenset({"ops.inspect-example"})),
    )


def test_install_is_verified_and_disabled_by_default() -> None:
    installed = _manager().install(_package(), archive=_ARCHIVE, verifier=_Verifier())

    assert installed.list() == (("example.inspect", ExtensionState.DISABLED, "1.0.0"),)
    assert installed.runtime().bound_capability_ids() == ()


def test_enable_atomically_activates_existing_pipeline_binding() -> None:
    installed = _manager().install(_package(), archive=_ARCHIVE, verifier=_Verifier())

    enabled = installed.enable("example.inspect")

    assert installed.runtime().bound_capability_ids() == ()
    assert enabled.runtime().bound_capability_ids() == ("example.inspect",)


def test_enable_atomically_activates_package_reasoning_tool() -> None:
    artifact = ToolArtifact(
        id="example.inspect-tool",
        version=1,
        description="Inspect example state.",
        input_schema={"type": "object"},
        capability_gate=CapabilityGate(None, None, 0.0),
        allowlist=None,
        output_wrapper=None,
        default_mode=PromptMode.SHADOW,
        provider="ExampleInspectProvider",
        provenance_source="package:test",
    )
    capability = Capability(
        capability_id="example.inspect-tool",
        name="Inspect example state with a tool",
        category=CapabilityCategory.INVESTIGATION,
        summary="Inspect a synthetic state projection with a package tool.",
        side_effect_class=SideEffectClass.READ,
    )
    package = ExtensionPackage(
        manifest=ExtensionManifest(
            extension_id="example.inspect-tool",
            version="1.0.0",
            source="source:example.inspect-tool",
            archive_sha256=hashlib.sha256(_ARCHIVE).hexdigest(),
            min_host_version="1.0.0",
            capability_ids=(capability.capability_id,),
        ),
        bundle=CapabilityBundle(
            capabilities=(capability,),
            bindings=(
                CapabilityBinding(
                    capability_id=capability.capability_id,
                    kind=CapabilityBindingKind.REASONING_TOOL,
                    target_ref=artifact.id,
                    provider_id="ExampleInspectProvider",
                ),
            ),
            reasoning_tools=(artifact,),
            tool_providers={"ExampleInspectProvider": InMemoryToolProvider()},
        ),
    )
    installed = _manager().install(package, archive=_ARCHIVE, verifier=_Verifier())

    assert installed.runtime().reasoning_tools == ()
    enabled = installed.enable(package.manifest.extension_id)
    assert enabled.runtime().reasoning_tools == (artifact,)
    assert enabled.runtime().bound_capability_ids() == (capability.capability_id,)


def test_extension_lifecycle_emits_stable_transitions() -> None:
    transitions = InMemoryRoutingTransitionSink()
    manager = ExtensionManager(
        host_version="1.2.0",
        references=CapabilityReferences(action_types=frozenset({"ops.inspect-example"})),
        transition_sink=transitions,
    )

    installed = manager.install(_package(), archive=_ARCHIVE, verifier=_Verifier())
    installed.enable("example.inspect")

    assert [(item.domain, item.outcome) for item in transitions.transitions] == [
        ("extension", "accepted"),
        ("extension", "enabled"),
    ]


@pytest.mark.parametrize(
    ("package", "verifier", "message"),
    [
        (_package(digest="0" * 64), _Verifier(), "digest"),
        (_package(), _Verifier(False), "trust"),
        (_package(minimum="2.0.0"), _Verifier(), "newer"),
    ],
)
def test_install_fails_closed_before_registration(
    package: ExtensionPackage,
    verifier: _Verifier,
    message: str,
) -> None:
    manager = _manager()

    with pytest.raises(ExtensionLifecycleError, match=message):
        manager.install(package, archive=_ARCHIVE, verifier=verifier)

    assert manager.list() == ()


def test_uninstall_requires_disable_and_rebuilds_runtime() -> None:
    manager = _manager().install(_package(), archive=_ARCHIVE, verifier=_Verifier())
    enabled = manager.enable("example.inspect")

    with pytest.raises(ExtensionLifecycleError, match="disable"):
        enabled.uninstall("example.inspect")

    removed = enabled.disable("example.inspect").uninstall("example.inspect")
    assert removed.list() == ()
    assert removed.runtime().bound_capability_ids() == ()
