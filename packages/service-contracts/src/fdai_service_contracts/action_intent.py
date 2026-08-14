"""Authority-free ontology action intent shared by Operator and Core services."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from fdai_service_contracts.ontology_query import (
    QueryContract,
    content_digest,
    parse_json_object,
)
from fdai_service_contracts.operator import JsonValue

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"


class ActionIntentSource(StrEnum):
    """Reviewed source classes for authority-free ontology action intent."""

    OPERATOR_LANGUAGE = "operator_language"


class OntologyActionIntent(QueryContract):
    """Bind a candidate ActionType and arguments to exact semantic evidence."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    source: ActionIntentSource
    actor_ref: Annotated[str, Field(min_length=1, max_length=256)]
    purpose: Annotated[str, Field(min_length=1, max_length=128)]
    ontology_release_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    action_type_name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")]
    action_type_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    action_declaration_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    arguments_json: Annotated[str, Field(min_length=2, max_length=65_536)]
    target_selector_json: Annotated[str, Field(min_length=2, max_length=65_536)]
    evidence_refs: Annotated[tuple[str, ...], Field(min_length=1, max_length=64)]
    input_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    intent_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    authority: Literal["candidate_only"] = "candidate_only"
    execution_authority: Literal[False] = False

    @property
    def arguments(self) -> dict[str, JsonValue]:
        """Return a fresh canonical Action argument mapping."""

        return parse_json_object(self.arguments_json, field_name="arguments_json")

    @property
    def target_selector(self) -> dict[str, JsonValue]:
        """Return a fresh canonical target selector mapping."""

        return parse_json_object(self.target_selector_json, field_name="target_selector_json")

    @model_validator(mode="after")
    def _identity_is_exact_and_no_authority(self) -> OntologyActionIntent:
        if tuple(dict.fromkeys(self.evidence_refs)) != self.evidence_refs:
            raise ValueError("action intent evidence_refs MUST be unique and ordered")
        material = {
            "schema_version": self.schema_version,
            "source": self.source.value,
            "actor_ref": self.actor_ref,
            "purpose": self.purpose,
            "ontology_release_digest": self.ontology_release_digest,
            "action_type_name": self.action_type_name,
            "action_type_version": self.action_type_version,
            "action_declaration_digest": self.action_declaration_digest,
            "arguments": self.arguments,
            "target_selector": self.target_selector,
            "evidence_refs": self.evidence_refs,
            "input_digest": self.input_digest,
            "authority": self.authority,
            "execution_authority": self.execution_authority,
        }
        if self.intent_digest != content_digest(material):
            raise ValueError("action intent digest does not match its content")
        return self


__all__ = ["ActionIntentSource", "OntologyActionIntent"]
