"""File-backed baseline sources and a read-only configuration drift capability."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from fdai.core.capability_catalog import (
    Capability,
    CapabilityBinding,
    CapabilityBindingKind,
    CapabilityBundle,
    CapabilityCategory,
    SideEffectClass,
)
from fdai.core.detection.configuration_drift import (
    ConfigurationObservation,
    FrozenConfigurationBaseline,
)
from fdai.core.detection.configuration_drift_codec import (
    baseline_from_dict,
    observation_from_dict,
    report_to_dict,
)
from fdai.core.detection.configuration_drift_service import ConfigurationDriftService
from fdai.core.prompts.types import PromptMode
from fdai.core.tools import CapabilityGate, ToolArtifact

_MAX_BASELINE_BYTES: Final[int] = 16 * 1024 * 1024
_PROVIDER_ID: Final[str] = "ConfigurationDriftProvider"
_TOOL_ID: Final[str] = "configuration.drift.check"


@dataclass(frozen=True, slots=True)
class JsonFileConfigurationBaselineSource:
    """Load one bounded strict baseline JSON document."""

    path: Path

    async def load(self) -> FrozenConfigurationBaseline:
        return baseline_from_dict(_read_json(self.path))


@dataclass(frozen=True, slots=True)
class JsonFileConfigurationObservationSource:
    """Development and evidence-replay source for a bounded observation."""

    path: Path
    allowed_scope: str

    async def observe(self, *, scope: str) -> ConfigurationObservation:
        if scope != self.allowed_scope:
            raise PermissionError("requested scope is outside the configured observation source")
        observation = observation_from_dict(_read_json(self.path))
        if observation.scope != self.allowed_scope:
            raise PermissionError("observation content is outside the configured scope")
        return observation


@dataclass(frozen=True, slots=True)
class ConfigurationDriftToolProvider:
    """Expose a server-pinned A0 drift check without caller-selected targets."""

    service: ConfigurationDriftService

    async def call(
        self,
        *,
        artifact: ToolArtifact,
        arguments: Mapping[str, Any],
    ) -> object:
        if artifact.id != _TOOL_ID:
            raise ValueError(f"unsupported tool id {artifact.id!r}")
        if arguments:
            raise ValueError("configuration drift check accepts no caller arguments")
        try:
            report = await self.service.run()
        except Exception as exc:  # noqa: BLE001 - external evidence fails closed
            return {
                "schema_version": "1.0.0",
                "verdict": "blocked",
                "error_code": f"configuration_evidence_unavailable:{type(exc).__name__}",
                "findings": [],
                "mutation_count": 0,
                "approval_request_count": 0,
                "mitigation_execution_count": 0,
                "unsupported_claim_count": 0,
            }
        return report_to_dict(report)


def build_configuration_drift_bundle(
    service: ConfigurationDriftService,
) -> CapabilityBundle:
    """Build the reviewed read-only capability, tool metadata, and provider."""

    tool = ToolArtifact(
        id=_TOOL_ID,
        version=1,
        description="Compare a frozen configuration baseline with current scoped evidence.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        capability_gate=CapabilityGate(
            requires_tier="T0",
            requires_novelty_score=None,
            cost_budget_usd_per_call=0.0,
        ),
        allowlist=None,
        output_wrapper='<configuration_drift trusted="false">{output}</configuration_drift>',
        default_mode=PromptMode.SHADOW,
        provider=_PROVIDER_ID,
        provenance_source="fdai.configuration-drift.v1",
    )
    return CapabilityBundle(
        capabilities=(
            Capability(
                capability_id="configuration.drift.read",
                name="Check frozen configuration baseline",
                category=CapabilityCategory.DETECTION,
                summary="Read current scoped evidence and produce a deterministic drift report.",
                side_effect_class=SideEffectClass.READ,
                required_role="reader",
                tags=("configuration-drift", "read-only", "deterministic"),
            ),
        ),
        bindings=(
            CapabilityBinding(
                capability_id="configuration.drift.read",
                kind=CapabilityBindingKind.REASONING_TOOL,
                target_ref=_TOOL_ID,
                provider_id=_PROVIDER_ID,
            ),
        ),
        reasoning_tools=(tool,),
        tool_providers={_PROVIDER_ID: ConfigurationDriftToolProvider(service)},
    )


def _read_json(path: Path) -> Mapping[str, Any]:
    size = path.stat().st_size
    if size <= 0 or size > _MAX_BASELINE_BYTES:
        raise ValueError("configuration evidence file size is outside the allowed range")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("configuration evidence MUST be a JSON object")
    return raw


__all__ = [
    "ConfigurationDriftToolProvider",
    "JsonFileConfigurationBaselineSource",
    "JsonFileConfigurationObservationSource",
    "build_configuration_drift_bundle",
]
