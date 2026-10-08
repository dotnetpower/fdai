"""Meaning proposals remain distinct from verified candidate membership."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol

from fdai_service_contracts.ontology_query import content_digest
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fdai.core.conversation.semantic_judgment import SemanticJudgmentObservation
from fdai.core.ontology_platform import QueryManifest
from fdai.core.prompts.types import PromptReplayManifest

from .generation import SemanticGenerationBuild, validate_ontology_semantic_generation
from .ontology_candidate_selection import (
    SELECTION_STRATEGY,
    OntologyCandidateClause,
    OntologyCandidateSelection,
)
from .ontology_snapshot_store import OntologyStagedProjection


class OntologyCandidateProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    status: Literal["select", "clarify"]
    reason: Literal[
        "conditions_proposed", "unresolved_reference", "unsupported_constraint", "ambiguous_request"
    ]
    clauses: tuple[OntologyCandidateClause, ...] = Field(max_length=8)
    clause_quotes: tuple[Annotated[str, Field(min_length=1, max_length=16384)], ...] = Field(
        max_length=8
    )

    @model_validator(mode="after")
    def _consistent_outcome(self) -> OntologyCandidateProposal:
        if self.status == "select":
            if (
                self.reason != "conditions_proposed"
                or not self.clauses
                or len(self.clauses) != len(self.clause_quotes)
            ):
                raise ValueError("candidate selection requires conditions and their source quotes")
        elif self.reason == "conditions_proposed" or self.clauses or self.clause_quotes:
            raise ValueError("candidate clarification cannot carry executable conditions")
        return self

    def validate_source_quotes(self, query: str) -> None:
        if any(query.count(quote) != 1 for quote in self.clause_quotes):
            raise ValueError("candidate proposal quote must identify one exact source span")


@dataclass(frozen=True, slots=True)
class OntologyCandidateProposalResult:
    proposal: OntologyCandidateProposal
    selection: OntologyCandidateSelection | None
    input_digest: str
    observation: SemanticJudgmentObservation
    quote_invalid_clauses: int = 0


@dataclass(frozen=True, slots=True)
class OntologyCandidateModelBinding:
    target_digest: str
    deployment_digest: str
    request_parameters_digest: str
    prompt_manifest: PromptReplayManifest


class OntologyCandidateProposer(Protocol):
    def candidate_proposal_binding(self) -> OntologyCandidateModelBinding: ...

    async def propose_candidate_selection(
        self,
        *,
        query: str,
        manifest: QueryManifest,
        build: SemanticGenerationBuild,
        staged: OntologyStagedProjection,
    ) -> OntologyCandidateProposalResult: ...


def _selection_context_document(document_id: str) -> bool:
    """Instances and their ObjectType declarations are the whole typed-selection domain.

    Function, link, interface, and unavailable declarations cannot be selected or predicated
    on, so they never enter the proposal context. An object-only manifest keeps every document.
    """
    return document_id.startswith(("object:", "declaration:object:"))


def candidate_proposal_payload(
    *,
    query: str,
    manifest: QueryManifest,
    build: SemanticGenerationBuild,
    staged: OntologyStagedProjection,
) -> dict[str, object]:
    if not query.strip() or len(query.encode("utf-8")) > 16384:
        raise ValueError("candidate proposal query must be nonempty and bounded")
    validate_ontology_semantic_generation(
        build=build, manifest=manifest, validator_id="candidate-proposal-context"
    )
    payload: dict[str, object] = {
        "query": query,
        "strategy": SELECTION_STRATEGY,
        "manifest_digest": manifest.manifest_digest,
        "snapshot_digest": staged.snapshot_digest,
        "generation_digest": build.metadata.generation_digest,
        "allowed_predicate_properties": candidate_predicate_property_catalog(manifest),
        "allowed_nested_predicate_keys": candidate_nested_property_catalog(manifest, build),
        "documents": [
            {"document_id": document.rule_id, "content": json.loads(document.text)}
            for document in build.documents
            if _selection_context_document(document.rule_id)
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > 131072:
        raise ValueError("complete candidate proposal context exceeds its byte bound")
    payload["input_digest"] = content_digest(payload)
    return payload


def filter_candidate_proposal_quotes(
    query: str,
    proposal: OntologyCandidateProposal,
) -> tuple[OntologyCandidateProposal, int]:
    """Drop only clauses whose attribution quote is not one exact source span."""
    if proposal.status != "select":
        proposal.validate_source_quotes(query)
        return proposal, 0
    clauses = []
    quotes = []
    invalid = 0
    for clause, quote in zip(proposal.clauses, proposal.clause_quotes, strict=True):
        if query.count(quote) == 1:
            clauses.append(clause)
            quotes.append(quote)
        else:
            invalid += 1
    if not clauses:
        return (
            OntologyCandidateProposal(
                status="clarify",
                reason="unsupported_constraint",
                clauses=(),
                clause_quotes=(),
            ),
            invalid,
        )
    filtered = OntologyCandidateProposal(
        status="select",
        reason="conditions_proposed",
        clauses=tuple(clauses),
        clause_quotes=tuple(quotes),
    )
    filtered.validate_source_quotes(query)
    return filtered, invalid


def candidate_predicate_property_catalog(manifest: QueryManifest) -> tuple[dict[str, object], ...]:
    """Return the exact top-level properties the current principal manifest may predicate on."""
    rows: list[dict[str, object]] = []
    for descriptor in manifest.descriptors:
        if descriptor.get("kind") != "object":
            continue
        properties = descriptor.get("properties")
        if not isinstance(properties, dict):
            continue
        rows.append(
            {
                "object_type": str(descriptor["name"]),
                "properties": tuple(sorted(str(name) for name in properties)),
            }
        )
    return tuple(sorted(rows, key=lambda item: str(item["object_type"])))


def candidate_nested_property_catalog(
    manifest: QueryManifest, build: SemanticGenerationBuild
) -> tuple[dict[str, object], ...]:
    """Return keys observed inside allowed object-valued properties of prepared instances."""
    allowed = {
        str(item["object_type"]): set(item["properties"])  # type: ignore[call-overload]
        for item in candidate_predicate_property_catalog(manifest)
    }
    keys: dict[tuple[str, str], set[str]] = {}
    for document in build.documents:
        if not document.rule_id.startswith("object:"):
            continue
        try:
            payload = json.loads(document.text)
            object_type = payload["object_type"]
            properties = payload["properties"]
        except (KeyError, TypeError, ValueError):
            raise ValueError(
                "candidate nested property catalog requires canonical object documents"
            ) from None
        if not isinstance(object_type, str) or not isinstance(properties, dict):
            raise ValueError("candidate nested property catalog requires object properties")
        for name, value in properties.items():
            if name in allowed.get(object_type, ()) and isinstance(value, dict):
                keys.setdefault((object_type, name), set()).update(
                    str(key) for key in value if isinstance(key, str)
                )
    return tuple(
        {"object_type": object_type, "property": name, "keys": tuple(sorted(found))}
        for (object_type, name), found in sorted(keys.items())
        if found
    )


def candidate_object_id_catalog(build: SemanticGenerationBuild) -> tuple[dict[str, object], ...]:
    """Return exact instance identifiers by ObjectType from the prepared canonical build."""
    by_type: dict[str, set[str]] = {}
    for document in build.documents:
        if not document.rule_id.startswith("object:"):
            continue
        try:
            payload = json.loads(document.text)
            object_type = payload["object_type"]
            identifier = payload["id"]
        except (KeyError, TypeError, ValueError):
            raise ValueError(
                "candidate object id catalog requires canonical object documents"
            ) from None
        if not isinstance(object_type, str) or not isinstance(identifier, str):
            raise ValueError("candidate object id catalog requires string identities")
        by_type.setdefault(object_type, set()).add(identifier)
    return tuple(
        {"object_type": object_type, "object_ids": tuple(sorted(identifiers))}
        for object_type, identifiers in sorted(by_type.items())
    )
