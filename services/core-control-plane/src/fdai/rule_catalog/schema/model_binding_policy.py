"""Validated environment-scoped T1/T2 model binding intent.

The policy narrows the reviewed LLM registry for one deployment environment. It
has no provider credentials or activation authority; protected planning remains
responsible for resolving, sealing, approving, and applying the resulting model
artifact.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Any, cast

import yaml
from fdai_service_contracts.model_binding import (
    CapabilityBindingPolicy,
    ModelBindingCapacity,
    ModelBindingPolicy,
    ModelSelectionMode,
    ModelSku,
)
from jsonschema import Draft202012Validator

from fdai.rule_catalog.schema.llm_registry import (
    CapabilitySpec,
    FamilyPreference,
    LlmRegistry,
    Sku,
)

_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_SCHEMA_FILE = "model_binding_policy.schema.json"
_T2_PRIMARY = "t2.reasoner.primary"
_T2_SECONDARY = "t2.reasoner.secondary"


def load_model_binding_policy_from_mapping(raw: Mapping[str, Any]) -> ModelBindingPolicy:
    """Validate one untrusted policy mapping against schema and semantic rules."""
    schema = json.loads(
        resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_FILE).read_text(encoding="utf-8")
    )
    errors = sorted(
        Draft202012Validator(schema).iter_errors(dict(raw)),
        key=lambda item: list(item.path),
    )
    if errors:
        preview = "; ".join(
            f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors[:5]
        )
        raise ValueError(f"model binding policy validation failed: {preview}")
    return ModelBindingPolicy.model_validate(raw)


def load_model_binding_policy_from_yaml(path: Path) -> ModelBindingPolicy:
    """Load one YAML policy while rejecting a non-mapping document root."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("model binding policy MUST be a YAML mapping")
    return load_model_binding_policy_from_mapping(raw)


def capability_policy(
    *, registry: LlmRegistry, policy: ModelBindingPolicy | None, capability: str
) -> tuple[ModelSelectionMode, CapabilitySpec]:
    """Return the effective mode and immutable capability specification."""
    base = registry.models[capability]
    if policy is None or capability not in policy.capabilities:
        return ModelSelectionMode.AUTO, base
    requested = policy.capabilities[capability]
    if requested.selection_mode is not ModelSelectionMode.PINNED:
        return requested.selection_mode, base
    publisher = cast(str, requested.publisher)
    family = cast(str, requested.family)
    sku = Sku(cast(ModelSku, requested.sku).value)
    capacity = cast(ModelBindingCapacity, requested.capacity)
    updates: dict[str, object] = {
        "preferences": (FamilyPreference(publisher=publisher, family=family),),
        "sku": sku,
        "capacity_tpm": None,
        "capacity_ptu": None,
    }
    updates["capacity_ptu" if capacity.unit == "ptu" else "capacity_tpm"] = capacity.value
    return requested.selection_mode, base.model_copy(update=updates)


def validate_policy_against_registry(*, registry: LlmRegistry, policy: ModelBindingPolicy) -> None:
    """Reject unknown capabilities and an explicitly same-publisher T2 pair."""
    unknown = sorted(set(policy.capabilities) - set(registry.models))
    if unknown:
        raise ValueError(f"model binding policy references unknown capabilities: {unknown}")
    primary_mode, primary = capability_policy(
        registry=registry, policy=policy, capability=_T2_PRIMARY
    )
    secondary_mode, secondary = capability_policy(
        registry=registry, policy=policy, capability=_T2_SECONDARY
    )
    if ModelSelectionMode.HIL_ONLY in {primary_mode, secondary_mode}:
        return
    if primary.preferences[0].publisher == secondary.preferences[0].publisher:
        raise ValueError("T2 primary and secondary binding policies require distinct publishers")


__all__ = [
    "CapabilityBindingPolicy",
    "ModelBindingCapacity",
    "ModelBindingPolicy",
    "ModelSelectionMode",
    "capability_policy",
    "load_model_binding_policy_from_mapping",
    "load_model_binding_policy_from_yaml",
    "validate_policy_against_registry",
]
