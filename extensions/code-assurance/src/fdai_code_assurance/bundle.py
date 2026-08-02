"""Self-contained FDAI capability bundle for optional code assurance."""

from __future__ import annotations

import hashlib

from fdai.composition import Container, install_capability_bundle
from fdai.core.capability_catalog import (
    Capability,
    CapabilityBinding,
    CapabilityBindingKind,
    CapabilityBundle,
    CapabilityCategory,
    CapabilityParity,
    ExtensionManifest,
    ExtensionPackage,
    SideEffectClass,
)
from fdai.core.prompts.types import PromptMode
from fdai.core.tools import CapabilityGate, ToolArtifact

from .__about__ import __version__
from .assets import load_code_assurance_assets
from .provider import (
    CODE_REVIEW_TOOL_ID,
    SECURITY_REVIEW_TOOL_ID,
    CodeAssuranceProvider,
    PullRequestSource,
)

PROVIDER_ID = "CodeAssuranceProvider"
PACKAGE_VERSION = __version__
_INPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["repository", "pull_number"],
    "properties": {
        "repository": {
            "type": "string",
            "pattern": r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$",
        },
        "pull_number": {"type": "integer", "minimum": 1},
    },
}
_OUTPUT_WRAPPER = '<code_assurance_result trusted="false">{}</code_assurance_result>'


def build_code_assurance_bundle(source: PullRequestSource) -> CapabilityBundle:
    """Build optional read-only review capabilities and their provider."""

    load_code_assurance_assets()
    provider = CodeAssuranceProvider(source)
    tool_specs = (
        (
            "assurance.code-review",
            "Review source changes",
            "Find deterministic correctness risks in a bounded pull-request patch.",
            CODE_REVIEW_TOOL_ID,
        ),
        (
            "assurance.security-review",
            "Review source security",
            "Find deterministic security risks in a bounded pull-request patch.",
            SECURITY_REVIEW_TOOL_ID,
        ),
    )
    capabilities = tuple(
        Capability(
            capability_id=capability_id,
            name=name,
            category=CapabilityCategory.INVESTIGATION,
            summary=summary,
            side_effect_class=SideEffectClass.READ,
            required_role="reader",
            tags=("optional", "code-assurance", "github", "read-only"),
            parity=CapabilityParity.EXTERNAL_BINDING,
        )
        for capability_id, name, summary, _tool_id in tool_specs
    )
    artifacts = tuple(
        ToolArtifact(
            id=tool_id,
            version=1,
            description=summary,
            input_schema=_INPUT_SCHEMA,
            capability_gate=CapabilityGate(
                requires_tier="T2",
                requires_novelty_score=None,
                cost_budget_usd_per_call=0.0,
            ),
            allowlist=None,
            output_wrapper=_OUTPUT_WRAPPER,
            default_mode=PromptMode.SHADOW,
            provider=PROVIDER_ID,
            provenance_source="package:fdai-code-assurance",
        )
        for _capability_id, _name, summary, tool_id in tool_specs
    )
    bindings = tuple(
        CapabilityBinding(
            capability_id=capability_id,
            kind=CapabilityBindingKind.REASONING_TOOL,
            target_ref=tool_id,
            provider_id=PROVIDER_ID,
        )
        for capability_id, _name, _summary, tool_id in tool_specs
    )
    return CapabilityBundle(
        capabilities=capabilities,
        bindings=bindings,
        reasoning_tools=artifacts,
        tool_providers={PROVIDER_ID: provider},
    )


def install_code_assurance_capabilities(
    container: Container,
    *,
    source: PullRequestSource,
) -> Container:
    """Install the optional package without changing base FDAI behavior."""

    return install_capability_bundle(container, build_code_assurance_bundle(source))


def build_code_assurance_extension(
    source: PullRequestSource,
    *,
    archive: bytes,
) -> ExtensionPackage:
    """Bind reviewed wheel bytes to a disabled-first extension package."""

    bundle = build_code_assurance_bundle(source)
    return ExtensionPackage(
        manifest=ExtensionManifest(
            extension_id="code-assurance.review-pack",
            version=PACKAGE_VERSION,
            source="package:fdai-code-assurance",
            archive_sha256=hashlib.sha256(archive).hexdigest(),
            min_host_version="0.1.0",
            max_host_version="0.1.999",
            capability_ids=tuple(capability.capability_id for capability in bundle.capabilities),
        ),
        bundle=bundle,
    )


__all__ = [
    "PACKAGE_VERSION",
    "PROVIDER_ID",
    "build_code_assurance_bundle",
    "build_code_assurance_extension",
    "install_code_assurance_capabilities",
]
