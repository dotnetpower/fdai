"""Immutable semantic-planning configuration and diagnostic request identity."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from typing import Any

from fdai_service_contracts.ontology_query import content_digest
from pydantic import BaseModel

from fdai.core.ontology_platform import QueryManifest
from fdai.core.ontology_platform.models import ObjectPredicateOperator
from fdai.core.prompts import PromptAssembler, PromptReplayManifest, estimate_prompt_tokens
from fdai.core.prompts.types import LayerRef, PromptLayer
from fdai.delivery.catalog_search.generation import SemanticGenerationBuild
from fdai.delivery.catalog_search.ontology_candidate_proposal import (
    OntologyCandidateModelBinding,
    OntologyCandidateProposal,
    candidate_nested_property_catalog,
    candidate_object_id_catalog,
    candidate_predicate_property_catalog,
)

from .completion_body import completion_body_params, uses_completion_token_budget
from .request_target import ModelRequestTarget
from .semantic_planning_manifest import (
    transmitted_prompt_manifest,
    validate_output_reserve,
    validate_prompt_manifest,
)

_MAX_CANDIDATES = 8
MAX_SYSTEM_PROMPT_CHARS = 65_536
_STRUCTURED_OUTPUT_API_VERSION = "2024-10-21"
_STRUCTURED_OUTPUT_MINIMUM_VERSION = (2024, 8, 1)
_STRUCTURED_OUTPUT_INSTRUCTION = (
    "Return exactly one JSON object matching the response_format json_schema."
)


@dataclass(frozen=True, slots=True)
class AzureOpenAISemanticPlanningModelConfig:
    """Bounded request targets and catalog-owned semantic planning prompts."""

    candidates: tuple[ModelRequestTarget, ...]
    frame_system_prompt: str
    plan_system_prompt: str
    operational_frame_system_prompt: str | None = None
    recovery_frame_system_prompt: str | None = None
    frame_prompt_manifest: PromptReplayManifest | None = None
    plan_prompt_manifest: PromptReplayManifest | None = None
    operational_frame_prompt_manifest: PromptReplayManifest | None = None
    recovery_frame_prompt_manifest: PromptReplayManifest | None = None
    timeout_seconds: float = 90.0
    max_tokens: int = 2_048
    reasoning_effort: str | None = None
    frame_prompt_assembler: PromptAssembler | None = None
    plan_prompt_assembler: PromptAssembler | None = None

    def __post_init__(self) -> None:
        if not 1 <= len(self.candidates) <= _MAX_CANDIDATES:
            raise ValueError(f"semantic planning candidates MUST contain 1 to {_MAX_CANDIDATES}")
        for assembler, prompt, manifest in (
            (self.frame_prompt_assembler, self.frame_system_prompt, self.frame_prompt_manifest),
            (self.plan_prompt_assembler, self.plan_system_prompt, self.plan_prompt_manifest),
        ):
            if assembler is not None and (
                assembler.complete.system_text != prompt
                or assembler.complete.replay_manifest() != manifest
            ):
                raise ValueError("semantic planning assembler MUST match its complete prompt")
        identities = tuple(
            (candidate.endpoint, candidate.deployment, candidate.api_version)
            for candidate in self.candidates
        )
        if len(identities) != len(set(identities)):
            raise ValueError("semantic planning candidates MUST be unique")
        for prompt in (self.frame_system_prompt, self.plan_system_prompt):
            if not prompt or len(prompt) > MAX_SYSTEM_PROMPT_CHARS:
                raise ValueError("semantic planning system prompts MUST be non-empty and bounded")
        if self.operational_frame_system_prompt is not None and (
            not self.operational_frame_system_prompt
            or len(self.operational_frame_system_prompt) > MAX_SYSTEM_PROMPT_CHARS
        ):
            raise ValueError("operational frame system prompt MUST be non-empty and bounded")
        if self.recovery_frame_system_prompt is not None and (
            not self.recovery_frame_system_prompt
            or len(self.recovery_frame_system_prompt) > MAX_SYSTEM_PROMPT_CHARS
        ):
            raise ValueError("recovery frame system prompt MUST be non-empty and bounded")
        validate_prompt_manifest(self.frame_system_prompt, self.frame_prompt_manifest)
        validate_prompt_manifest(self.plan_system_prompt, self.plan_prompt_manifest)
        validate_prompt_manifest(
            self.operational_frame_system_prompt,
            self.operational_frame_prompt_manifest,
        )
        validate_prompt_manifest(
            self.recovery_frame_system_prompt,
            self.recovery_frame_prompt_manifest,
        )
        if not 0 < self.timeout_seconds <= 120:
            raise ValueError("semantic planning timeout_seconds MUST be in (0, 120]")
        if not 1 <= self.max_tokens <= 4_096:
            raise ValueError("semantic planning max_tokens MUST be in [1, 4096]")
        if self.reasoning_effort is not None and self.reasoning_effort not in {
            "minimal",
            "low",
            "medium",
            "high",
        }:
            raise ValueError("semantic planning reasoning_effort MUST be reviewed")
        for name, manifest in (
            ("frame", self.frame_prompt_manifest),
            ("plan", self.plan_prompt_manifest),
            ("operational frame", self.operational_frame_prompt_manifest),
            ("recovery frame", self.recovery_frame_prompt_manifest),
        ):
            validate_output_reserve(name, manifest, self.max_tokens)


def candidate_proposal_binding(
    config: AzureOpenAISemanticPlanningModelConfig,
    manifest: QueryManifest | None = None,
    build: SemanticGenerationBuild | None = None,
) -> OntologyCandidateModelBinding:
    if len(config.candidates) != 1 or config.plan_prompt_manifest is None:
        raise ValueError("candidate proposal binding requires one target and a prompt")
    schema = proposal_schema(OntologyCandidateProposal, manifest=manifest, build=build)
    target = candidate_proposal_request_target(config.candidates[0])
    prompt = transmitted_prompt_manifest(
        config.plan_prompt_manifest,
        system_content=candidate_proposal_system_content(config.plan_system_prompt),
        schema=schema,
    )
    if prompt is None:
        raise ValueError("candidate proposal prompt binding is unavailable")
    return OntologyCandidateModelBinding(
        content_digest(asdict(target)),
        content_digest({"deployment": target.deployment}),
        content_digest(
            {
                "completion": completion_body_params(
                    target.model_family or target.deployment,
                    temperature=0.0,
                    max_tokens=config.max_tokens,
                ),
                "response_format": candidate_proposal_response_format(
                    manifest=manifest,
                    build=build,
                ),
                "reasoning_effort": reasoning_effort_for_target(config, target),
                "quote_policy": quote_policy(),
                "timeout_seconds": config.timeout_seconds,
                "max_attempts": 1,
            }
        ),
        prompt,
    )


def proposal_schema(
    proposal_type: type[BaseModel],
    *,
    manifest: QueryManifest | None = None,
    query: str | None = None,
    build: SemanticGenerationBuild | None = None,
) -> str:
    if proposal_type is OntologyCandidateProposal:
        schema = strict_candidate_proposal_schema(manifest=manifest, query=query, build=build)
        return json.dumps(
            schema,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    return json.dumps(
        proposal_type.model_json_schema(),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def candidate_proposal_response_format(
    *,
    manifest: QueryManifest | None = None,
    query: str | None = None,
    build: SemanticGenerationBuild | None = None,
) -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "ontology_candidate_proposal",
            "strict": True,
            "schema": strict_candidate_proposal_schema(
                manifest=manifest,
                query=query,
                build=build,
            ),
        },
    }


def candidate_proposal_system_content(prompt: str) -> str:
    return f"{prompt}\n{_STRUCTURED_OUTPUT_INSTRUCTION}"


def candidate_proposal_prompt_manifest(
    prompt_manifest: PromptReplayManifest,
    *,
    manifest: QueryManifest | None = None,
    query: str | None = None,
    build: SemanticGenerationBuild | None = None,
) -> PromptReplayManifest:
    schema = proposal_schema(OntologyCandidateProposal, manifest=manifest, query=query, build=build)
    layers = tuple(
        layer for layer in prompt_manifest.layer_manifest if layer.id != "semantic-response-schema"
    )
    return replace(
        prompt_manifest,
        layer_manifest=(
            *layers,
            LayerRef(
                id="semantic-response-schema",
                version=1,
                layer=PromptLayer.ADAPTER_SCHEMA,
                token_estimate=estimate_prompt_tokens(schema),
            ),
        ),
    )


def quote_policy() -> dict[str, str]:
    return {"mode": "free_text_with_exact_span_validator"}


def candidate_proposal_schema_digest(
    *,
    manifest: QueryManifest | None = None,
    query: str | None = None,
    build: SemanticGenerationBuild | None = None,
) -> str:
    return content_digest(
        strict_candidate_proposal_schema(manifest=manifest, query=query, build=build)
    )


def candidate_proposal_request_target(target: ModelRequestTarget) -> ModelRequestTarget:
    if _api_version_supports_structured_outputs(target.api_version):
        return target
    return replace(target, api_version=_STRUCTURED_OUTPUT_API_VERSION)


def reasoning_effort_for_target(
    config: AzureOpenAISemanticPlanningModelConfig,
    target: ModelRequestTarget,
) -> str | None:
    family = target.model_family or target.deployment
    if config.reasoning_effort is None or not uses_completion_token_budget(family):
        return None
    return config.reasoning_effort


def _api_version_supports_structured_outputs(api_version: str | None) -> bool:
    if api_version is None:
        return False
    date = api_version.split("-", 3)
    if len(date) < 3:
        return False
    try:
        observed = (int(date[0]), int(date[1]), int(date[2][:2]))
    except ValueError:
        return False
    return observed >= _STRUCTURED_OUTPUT_MINIMUM_VERSION


def strict_candidate_proposal_schema(
    *,
    manifest: QueryManifest | None = None,
    query: str | None = None,
    build: SemanticGenerationBuild | None = None,
) -> dict[str, Any]:
    property_catalog = candidate_predicate_property_catalog(manifest) if manifest else ()
    id_catalog = candidate_object_id_catalog(build) if build else ()
    nested_catalog = (
        candidate_nested_property_catalog(manifest, build) if manifest and build else ()
    )
    nested_by_type: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    for entry in nested_catalog:
        keys = entry.get("keys")
        if not isinstance(keys, tuple) or not all(isinstance(key, str) for key in keys):
            raise ValueError("candidate nested property catalog is malformed")
        nested_by_type.setdefault(str(entry["object_type"]), []).append(
            (str(entry["property"]), keys)
        )
    ids_by_type = {str(item["object_type"]): _catalog_object_ids(item) for item in id_catalog}
    all_object_types = tuple(str(item["object_type"]) for item in property_catalog)
    all_properties = tuple(
        sorted(
            {
                str(property_name)
                for item in property_catalog
                for property_name in _catalog_properties(item)
            }
        )
    )
    object_type_schema: dict[str, Any] = {"type": "string", "minLength": 1, "maxLength": 256}
    if all_object_types:
        object_type_schema = {"type": "string", "enum": list(all_object_types)}

    def property_schema(properties: tuple[str, ...] = all_properties) -> dict[str, Any]:
        if properties:
            return {"type": "string", "enum": list(properties)}
        return {"type": "string", "minLength": 1, "maxLength": 256}

    def predicate_variants(properties: tuple[str, ...] = all_properties) -> list[dict[str, Any]]:
        prop = property_schema(properties)
        return [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["property", "operator", "equals"],
                "properties": {
                    "property": prop,
                    "operator": {
                        "type": "string",
                        "enum": [
                            "equals",
                            "not_equals",
                            "at_least",
                            "at_most",
                            "contains",
                            "equals_ignore_case",
                        ],
                    },
                    "equals": scalar,
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["property", "operator", "values"],
                "properties": {
                    "property": prop,
                    "operator": {"type": "string", "enum": ["in"]},
                    "values": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 1000,
                        "items": scalar,
                    },
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["property", "operator"],
                "properties": {
                    "property": prop,
                    "operator": {"type": "string", "enum": ["exists", "absent"]},
                },
            },
        ]

    scalar: dict[str, Any] = {"type": ["string", "number", "integer", "boolean"]}

    def nested_schema(entries: list[tuple[str, tuple[str, ...]]] | None) -> dict[str, Any]:
        if entries is not None and not entries:
            return {"type": "array", "maxItems": 0, "items": {"type": "string"}}
        operators = [operator.value for operator in ObjectPredicateOperator]
        variants: list[dict[str, Any]] = []
        # One variant per parent keeps each key enum listed once; unused operands are null.
        for parent, keys in entries or [("", ())]:
            variants.append(
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["property", "key", "operator", "equals", "values"],
                    "properties": {
                        "property": (
                            {"type": "string", "enum": [parent]}
                            if parent
                            else {"type": "string", "minLength": 1, "maxLength": 256}
                        ),
                        "key": (
                            {"type": "string", "enum": list(keys)}
                            if keys
                            else {"type": "string", "minLength": 1, "maxLength": 256}
                        ),
                        "operator": {"type": "string", "enum": operators},
                        "equals": {"type": ["string", "number", "integer", "boolean", "null"]},
                        "values": {
                            "type": ["array", "null"],
                            "minItems": 1,
                            "maxItems": 1000,
                            "items": scalar,
                        },
                    },
                }
            )
        return {"type": "array", "maxItems": 16, "items": {"anyOf": variants}}

    quote_item: dict[str, Any] = {"type": "string", "minLength": 1, "maxLength": 16384}
    default_clause_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["object_type", "predicates", "nested_predicates", "object_ids", "quote"],
        "properties": {
            "object_type": object_type_schema,
            "predicates": {
                "type": "array",
                "maxItems": 16,
                "items": {"anyOf": predicate_variants()},
            },
            "nested_predicates": nested_schema(None),
            "object_ids": {
                "type": ["array", "null"],
                "minItems": 1,
                "maxItems": 100,
                "items": {"type": "string", "minLength": 1, "maxLength": 512},
            },
            "quote": quote_item,
        },
    }
    if property_catalog:
        clause_items: dict[str, Any] = {
            "anyOf": [
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "object_type",
                        "predicates",
                        "nested_predicates",
                        "object_ids",
                        "quote",
                    ],
                    "properties": {
                        "object_type": {"type": "string", "enum": [str(item["object_type"])]},
                        "predicates": {
                            "type": "array",
                            "maxItems": 16,
                            "items": {"anyOf": predicate_variants(_catalog_properties(item))},
                        },
                        "nested_predicates": nested_schema(
                            nested_by_type.get(str(item["object_type"]), [])
                            if build is not None
                            else None
                        ),
                        "object_ids": _object_ids_schema(
                            ids_by_type.get(str(item["object_type"]), ())
                        ),
                        "quote": quote_item,
                    },
                }
                for item in property_catalog
            ]
        }
    else:
        clause_items = default_clause_schema
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "reason", "clauses"],
        "properties": {
            "status": {"type": "string", "enum": ["select", "clarify"]},
            "reason": {
                "type": "string",
                "enum": [
                    "conditions_proposed",
                    "unresolved_reference",
                    "unsupported_constraint",
                    "ambiguous_request",
                ],
            },
            "clauses": {
                "type": "array",
                "maxItems": 8,
                "items": clause_items,
            },
        },
    }
    if _enum_value_count(schema) > _MAX_STRUCTURED_ENUM_VALUES:
        raise ValueError("candidate proposal schema exceeds the structured-output enum bound")
    return schema


# Azure OpenAI structured outputs reject schemas above this total; hold before dispatch.
_MAX_STRUCTURED_ENUM_VALUES = 500


def _enum_value_count(node: Any) -> int:
    if isinstance(node, dict):
        own = len(node["enum"]) if isinstance(node.get("enum"), list) else 0
        return own + sum(_enum_value_count(value) for value in node.values())
    if isinstance(node, list):
        return sum(_enum_value_count(value) for value in node)
    return 0


def _catalog_properties(item: dict[str, object]) -> tuple[str, ...]:
    properties = item.get("properties")
    if not isinstance(properties, tuple) or not all(
        isinstance(property_name, str) for property_name in properties
    ):
        raise ValueError("candidate predicate property catalog is malformed")
    return properties


def _catalog_object_ids(item: dict[str, object]) -> tuple[str, ...]:
    object_ids = item.get("object_ids")
    if not isinstance(object_ids, tuple) or not all(
        isinstance(identifier, str) for identifier in object_ids
    ):
        raise ValueError("candidate object id catalog is malformed")
    return object_ids


def _object_ids_schema(object_ids: tuple[str, ...]) -> dict[str, Any]:
    item_schema: dict[str, Any] = {"type": "string", "minLength": 1, "maxLength": 512}
    if object_ids:
        item_schema = {"type": "string", "enum": list(object_ids)}
    return {
        "type": ["array", "null"],
        "minItems": 1,
        "maxItems": 100,
        "items": item_schema,
    }
