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
        "documents": [
            {"document_id": document.rule_id, "content": json.loads(document.text)}
            for document in build.documents
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > 131072:
        raise ValueError("complete candidate proposal context exceeds its byte bound")
    payload["input_digest"] = content_digest(payload)
    return payload
