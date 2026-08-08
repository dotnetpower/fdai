"""LlmRegistry model + fail-fast loader.

Mirror of ``rule-catalog/schema/llm-registry.schema.json`` - the JSON
Schema is the source of truth for structural validation; this pydantic
model layers on invariants the schema cannot express (mixed-model
publisher distinctness across ``t2.reasoner.primary`` /
``t2.reasoner.secondary``).

The loader follows the aggregate-issue pattern used elsewhere in the
schema package (see :mod:`.exemption`, :mod:`.resource_type`) so a
reviewer sees the full remediation list in one :class:`LlmRegistryError`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from pathlib import Path
from typing import Annotated, Any

import yaml
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator

_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_SCHEMA_FILE = "llm_registry.schema.json"

# Capabilities the mixed-model invariant applies to. Kept as a tuple so a
# future extra reasoner tier lands here explicitly (no accidental drift).
_MIXED_MODEL_PAIR: tuple[str, str] = (
    "t2.reasoner.primary",
    "t2.reasoner.secondary",
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LlmRegistryIssue:
    key: str
    message: str


class LlmRegistryError(ValueError):
    """Aggregate error surfaced at the registry-load boundary."""

    def __init__(self, issues: list[LlmRegistryIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{i.key}: {i.message}" for i in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"llm-registry validation failed: {preview}{suffix}")


# ---------------------------------------------------------------------------
# Enums & models
# ---------------------------------------------------------------------------


class MixedModelMode(StrEnum):
    AZURE_FOUNDRY = "azure-foundry"
    EXTERNAL = "external"
    HIL_ONLY = "hil-only"


class Sku(StrEnum):
    STANDARD = "Standard"
    GLOBAL_STANDARD = "GlobalStandard"
    PROVISIONED_MANAGED = "ProvisionedManaged"
    GLOBAL_PROVISIONED_MANAGED = "GlobalProvisionedManaged"
    DATA_ZONE_PROVISIONED_MANAGED = "DataZoneProvisionedManaged"

    @property
    def is_provisioned(self) -> bool:
        return self in {
            Sku.PROVISIONED_MANAGED,
            Sku.GLOBAL_PROVISIONED_MANAGED,
            Sku.DATA_ZONE_PROVISIONED_MANAGED,
        }


class Invocation(StrEnum):
    ALWAYS = "always"
    ON_DISAGREEMENT = "on_disagreement"
    ON_NOVEL_CASE = "on_novel_case"


class FamilyPreference(BaseModel):
    """One (publisher, family) entry in a capability's preference list."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    publisher: Annotated[str, Field(min_length=1, max_length=64)]
    family: Annotated[str, Field(min_length=1, max_length=128)]


class CapabilitySpec(BaseModel):
    """One capability entry (``t1.embedding``, ``t2.reasoner.primary`` ...)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    preferences: tuple[FamilyPreference, ...]
    sku: Sku = Sku.STANDARD
    capacity_tpm: Annotated[int, Field(ge=1000)] | None = None
    capacity_ptu: Annotated[int, Field(ge=1)] | None = None
    invocation: Invocation = Invocation.ALWAYS
    tool_calling_required: bool = False
    """Whether this capability must resolve to a function-calling-capable
    family. Set ``True`` for a capability whose function tools require it;
    the resolver degrades that capability to ``hil-only`` when the selected
    family is not in the supplied tool-calling family set. Public web search
    is a separate ``t1.web_search`` capability whose Azure Responses managed
    tool is verified by a live startup readiness probe."""

    @model_validator(mode="after")
    def _require_capacity_for_sku(self) -> CapabilitySpec:
        if self.sku.is_provisioned:
            if self.capacity_ptu is None or self.capacity_tpm is not None:
                raise ValueError(
                    "provisioned model SKU requires capacity_ptu and forbids capacity_tpm"
                )
        elif self.capacity_tpm is None or self.capacity_ptu is not None:
            raise ValueError("standard model SKU requires capacity_tpm and forbids capacity_ptu")
        return self

    @property
    def capacity_unit(self) -> str:
        return "ptu" if self.sku.is_provisioned else "tpm"

    @property
    def requested_capacity(self) -> int:
        value = self.capacity_ptu if self.sku.is_provisioned else self.capacity_tpm
        if value is None:  # pragma: no cover - guarded by model validation
            raise ValueError("model capability capacity is unavailable")
        return value


class LlmRegistry(BaseModel):
    """Root registry model."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )

    schema_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    mixed_model_mode: MixedModelMode = MixedModelMode.AZURE_FOUNDRY
    models: dict[str, CapabilitySpec]

    @model_validator(mode="after")
    def _require_mixed_model_publisher_distinct(self) -> LlmRegistry:
        """Enforce the phase-2 mixed-model invariant declaratively.

        ``hil-only`` mode is a valid opt-out - the primary/secondary
        publisher distinctness is not required (there is no secondary).
        For every other mode, the union of first-preferences of the two
        reasoner capabilities MUST NOT share a publisher.
        """
        if self.mixed_model_mode is MixedModelMode.HIL_ONLY:
            return self
        primary_name, secondary_name = _MIXED_MODEL_PAIR
        primary = self.models.get(primary_name)
        secondary = self.models.get(secondary_name)
        if primary is None or secondary is None:
            # Missing capability is a structural error - the resolver will
            # abort. We do not raise here so the loader can still surface
            # every other issue; the risk-gate / resolver enforces at
            # deploy time.
            return self
        primary_pub = primary.preferences[0].publisher
        secondary_pub = secondary.preferences[0].publisher
        if primary_pub == secondary_pub:
            raise ValueError(
                f"mixed-model invariant violated: {primary_name}[0].publisher"
                f"={primary_pub!r} == {secondary_name}[0].publisher"
                f"={secondary_pub!r}. Distinct publishers are required "
                "unless mixed_model_mode='hil-only'."
            )
        return self


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _load_json_schema() -> dict[str, Any]:
    raw = resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_FILE).read_text(encoding="utf-8")
    return json.loads(raw)  # type: ignore[no-any-return]


def load_llm_registry_from_mapping(raw: Mapping[str, Any]) -> LlmRegistry:
    """Validate ``raw`` and return :class:`LlmRegistry` on success.

    Aggregates JSON Schema + pydantic issues into a single
    :class:`LlmRegistryError`.
    """
    issues: list[LlmRegistryIssue] = []

    schema = _load_json_schema()
    validator = Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(dict(raw)), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in err.absolute_path) or "<root>"
        issues.append(LlmRegistryIssue(key=path, message=err.message))

    if issues:
        raise LlmRegistryError(issues)

    try:
        return LlmRegistry.model_validate(raw)
    except ValueError as exc:
        errors = getattr(exc, "errors", None)
        if callable(errors):
            for e in errors():
                loc = ".".join(str(p) for p in e.get("loc", ()))
                issues.append(LlmRegistryIssue(key=loc or "<root>", message=e["msg"]))
        else:
            issues.append(LlmRegistryIssue(key="<root>", message=str(exc)))
        raise LlmRegistryError(issues) from exc


def load_llm_registry_from_yaml(path: Path) -> LlmRegistry:
    """Convenience wrapper that reads a YAML file and delegates."""
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, Mapping):
        raise LlmRegistryError(
            [LlmRegistryIssue(key="<root>", message="registry file MUST be a YAML mapping")]
        )
    return load_llm_registry_from_mapping(raw)


__all__ = [
    "CapabilitySpec",
    "FamilyPreference",
    "Invocation",
    "LlmRegistry",
    "LlmRegistryError",
    "LlmRegistryIssue",
    "MixedModelMode",
    "Sku",
    "load_llm_registry_from_mapping",
    "load_llm_registry_from_yaml",
]
