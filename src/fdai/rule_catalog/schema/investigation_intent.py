"""Schema-validated intent catalog for agent-owned investigations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum
from importlib import resources
from types import MappingProxyType
from typing import Annotated, Any, cast

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator

_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_SCHEMA_FILE = "investigation_intent.schema.json"


class InvestigationWorkClass(StrEnum):
    READ = "read"
    PROBLEM_RESPONSE = "problem_response"
    ACTION = "action"


class InvestigationOwner(StrEnum):
    ODIN = "Odin"
    THOR = "Thor"
    FORSETI = "Forseti"
    HUGINN = "Huginn"
    HEIMDALL = "Heimdall"
    VIDAR = "Vidar"
    VAR = "Var"
    BRAGI = "Bragi"
    SAGA = "Saga"
    MIMIR = "Mimir"
    MUNINN = "Muninn"
    NORNS = "Norns"
    NJORD = "Njord"
    FREYR = "Freyr"
    LOKI = "Loki"


class SelectorKind(StrEnum):
    RESOURCE = "resource"
    INCIDENT = "incident"
    SCOPE = "scope"
    NONE = "none"


class AnswerContract(StrEnum):
    LIST = "list"
    STATE = "state"
    HEALTH = "health"
    DIAGNOSIS = "diagnosis"
    CHANGE = "change"
    TOPOLOGY = "topology"
    KNOWLEDGE = "knowledge"
    FAILURE = "failure"


class IntentTerms(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    terms: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...]


class InvestigationEvidenceRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    authorities: tuple[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]*$")], ...]
    required_facets: tuple[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]*$")], ...]
    max_age_seconds: Annotated[int, Field(ge=0, le=2_592_000)]
    allow_stale: bool
    on_missing: str


class InvestigationIntentDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    work_class: InvestigationWorkClass
    owner_agent: InvestigationOwner
    plan_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]*$")]
    selector_kind: SelectorKind
    answer_contract: AnswerContract
    required_any: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...]
    required_all: tuple[IntentTerms, ...]
    excluded_any: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...]
    response_modes: Mapping[str, IntentTerms] = Field(default_factory=dict)
    response_mode_order: tuple[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")], ...] = ()
    evidence: InvestigationEvidenceRequirements

    @model_validator(mode="after")
    def _validate_definition(self) -> InvestigationIntentDefinition:
        if not self.required_any and not self.required_all:
            raise ValueError("an investigation intent requires a deterministic matcher")
        if set(self.response_mode_order) != set(self.response_modes):
            raise ValueError("response_mode_order must contain every response mode exactly once")
        if (
            self.work_class is InvestigationWorkClass.READ
            and self.owner_agent is InvestigationOwner.THOR
        ):
            raise ValueError("Thor cannot own read-investigation semantics")
        if (
            self.work_class is InvestigationWorkClass.ACTION
            and self.owner_agent is InvestigationOwner.BRAGI
        ):
            raise ValueError("Bragi cannot own action semantics")
        object.__setattr__(self, "response_modes", MappingProxyType(dict(self.response_modes)))
        return self


class InvestigationIntentRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    suffixes: tuple[str, ...]
    intents: Mapping[str, InvestigationIntentDefinition]

    def model_post_init(self, __context: Any) -> None:
        object.__setattr__(self, "intents", MappingProxyType(dict(self.intents)))


class InvestigationIntentRegistryError(ValueError):
    """Raised when the investigation intent catalog is invalid."""


def _schema() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(
            resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_FILE).read_text(encoding="utf-8")
        ),
    )


def load_investigation_intents_from_mapping(
    raw: Mapping[str, Any],
) -> InvestigationIntentRegistry:
    """Validate and freeze one investigation intent catalog."""

    errors = sorted(
        Draft202012Validator(_schema()).iter_errors(dict(raw)),
        key=lambda error: list(error.path),
    )
    if errors:
        preview = "; ".join(
            f"{'.'.join(str(item) for item in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors[:5]
        )
        raise InvestigationIntentRegistryError(preview)
    try:
        return InvestigationIntentRegistry.model_validate(raw)
    except ValueError as exc:
        raise InvestigationIntentRegistryError(str(exc)) from exc


__all__ = [
    "AnswerContract",
    "InvestigationEvidenceRequirements",
    "InvestigationIntentDefinition",
    "InvestigationIntentRegistry",
    "InvestigationIntentRegistryError",
    "InvestigationOwner",
    "InvestigationWorkClass",
    "IntentTerms",
    "SelectorKind",
    "load_investigation_intents_from_mapping",
]
