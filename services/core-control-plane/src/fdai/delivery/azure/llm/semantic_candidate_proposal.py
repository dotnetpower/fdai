"""Bounded diagnostic candidate proposals over the planning adapter's HTTP boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from functools import partial
from typing import Any, Literal

from fdai.core.conversation.semantic_planning_models import SemanticPlanningModelResponse
from fdai.core.ontology_platform import QueryManifest
from fdai.delivery.catalog_search.generation import SemanticGenerationBuild
from fdai.delivery.catalog_search.ontology_candidate_context import (
    CandidateContextError,
    CandidateContextLimits,
    CandidateProposalContext,
    restore_candidate_proposal_context,
)
from fdai.delivery.catalog_search.ontology_candidate_proposal import (
    OntologyCandidateProposal,
    OntologyCandidateProposalResult,
    candidate_nested_property_catalog,
    candidate_proposal_payload,
    filter_candidate_proposal_quotes,
)
from fdai.delivery.catalog_search.ontology_candidate_selection import (
    OntologyCandidateClause,
    OntologyCandidateSelection,
)
from fdai.delivery.catalog_search.ontology_snapshot_store import OntologyStagedProjection
from fdai.delivery.catalog_search.ontology_snapshot_validation import OntologySnapshotValidation

from .semantic_planning_config import (
    AzureOpenAISemanticPlanningModelConfig,
    candidate_proposal_binding,
    partition_candidate_build_pages,
)

_MAX_TIMEOUT_SECONDS = 20
_Completion = Callable[..., Awaitable[Mapping[str, Any] | None]]


class CandidateProposalDiagnostics:
    """Mechanical per-invocation helper; no runtime binding or activation authority."""

    def __init__(
        self,
        *,
        config: AzureOpenAISemanticPlanningModelConfig,
        owner_loop: asyncio.AbstractEventLoop,
        complete: _Completion,
    ) -> None:
        self._config = config
        self._owner_loop = owner_loop
        self._complete = complete

    async def propose_candidate_selection(
        self,
        *,
        query: str,
        manifest: QueryManifest,
        build: SemanticGenerationBuild,
        staged: OntologyStagedProjection,
    ) -> OntologyCandidateProposalResult:
        return await self._propose_payload(
            query=query,
            manifest=manifest,
            staged=staged,
            build=build,
            payload_factory=partial(
                candidate_proposal_payload,
                query=query,
                manifest=manifest,
                build=build,
                staged=staged,
            ),
        )

    async def propose_prepared_candidate_selection(
        self,
        *,
        context: CandidateProposalContext,
        query: str,
        manifest: QueryManifest,
        build: SemanticGenerationBuild,
        staged: OntologyStagedProjection,
        source_revision: str,
        data_handling_policy_digest: str,
        source_validation: OntologySnapshotValidation,
        limits: CandidateContextLimits | None = None,
    ) -> OntologyCandidateProposalResult:
        prompt = self._config.plan_prompt_manifest
        if (
            prompt is None
            or prompt.request_token_budget is None
            or prompt.system_token_budget is None
            or prompt.reserved_output_tokens is None
        ):
            raise CandidateContextError("invalid_source")

        def payload_factory() -> dict[str, object]:
            payload = restore_candidate_proposal_context(
                context,
                query=query,
                manifest=manifest,
                build=build,
                staged=staged,
                source_revision=source_revision,
                model_binding=candidate_proposal_binding(
                    self._config, manifest=manifest, build=build
                ),
                data_handling_policy_digest=data_handling_policy_digest,
                source_validation=source_validation,
                limits=limits,
            )
            payload["input_digest"] = context.context_digest
            return payload

        pages = partition_candidate_build_pages(manifest=manifest, build=build)
        if len(pages) == 1:
            return await self._propose_payload(
                query=query,
                manifest=manifest,
                build=build,
                staged=staged,
                payload_factory=payload_factory,
                operation="candidate_selection_prepared",
            )
        return await self._propose_paged_payload(
            pages=tuple(page for page in pages if page is not None),
            query=query,
            manifest=manifest,
            staged=staged,
            payload_factory=payload_factory,
        )

    async def _propose_paged_payload(
        self,
        *,
        pages: tuple[SemanticGenerationBuild, ...],
        query: str,
        manifest: QueryManifest,
        staged: OntologyStagedProjection,
        payload_factory: Callable[[], dict[str, object]],
    ) -> OntologyCandidateProposalResult:
        if asyncio.get_running_loop() is not self._owner_loop:
            raise ValueError("candidate proposal must run on the model owner loop")
        if (
            len(self._config.candidates) != 1
            or self._config.timeout_seconds > _MAX_TIMEOUT_SECONDS
            or self._config.plan_prompt_manifest is None
            or self._config.plan_prompt_manifest.profile_id
            != "diagnostic.ontology-candidate-selection"
        ):
            raise ValueError("candidate proposal requires one bounded target and diagnostic prompt")
        deadline = asyncio.get_running_loop().time() + self._config.timeout_seconds
        async with asyncio.timeout(self._config.timeout_seconds):
            full_payload = payload_factory()
            raw_documents = full_payload.get("documents")
            if not isinstance(raw_documents, list):
                raise CandidateContextError("invalid_source")
            documents_by_id = {
                str(item["document_id"]): item
                for item in raw_documents
                if isinstance(item, Mapping) and isinstance(item.get("document_id"), str)
            }
            page_requests: list[tuple[SemanticGenerationBuild, dict[str, object]]] = []
            accounted_instance_ids: list[str] = []
            for page_ordinal, page_build in enumerate(pages):
                page_documents = [
                    documents_by_id[doc.rule_id]
                    for doc in page_build.documents
                    if doc.rule_id in documents_by_id
                ]
                accounted_instance_ids.extend(
                    doc.rule_id for doc in page_build.documents if doc.rule_id.startswith("object:")
                )
                page_payload: dict[str, object] = {
                    **full_payload,
                    "allowed_nested_predicate_keys": candidate_nested_property_catalog(
                        manifest, page_build
                    ),
                    "documents": page_documents,
                    "page_ordinal": page_ordinal,
                    "page_count": len(pages),
                }
                page_requests.append((page_build, page_payload))
            expected_instance_ids = [
                str(item["document_id"])
                for item in raw_documents
                if isinstance(item, Mapping)
                and str(item.get("document_id", "")).startswith("object:")
            ]
            if accounted_instance_ids != expected_instance_ids:
                raise CandidateContextError("context_corrupt")
            proposals: list[OntologyCandidateProposal] = []
            total_invalid = 0
            last_observation = None
            for page_build, page_payload in page_requests:
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError("candidate proposal deadline exceeded before dispatch")
                response = await self._complete(
                    payload=page_payload,
                    prompt=self._config.plan_system_prompt,
                    proposal_type=OntologyCandidateProposal,
                    operation="candidate_selection_prepared",
                    manifest=self._config.plan_prompt_manifest,
                    query_manifest=manifest,
                    build=page_build,
                    max_attempts=1,
                )
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError("candidate proposal deadline exceeded after return")
                if not isinstance(response, SemanticPlanningModelResponse):
                    raise ValueError("candidate proposal model unavailable")
                proposal, invalid = filter_candidate_proposal_quotes(
                    query, OntologyCandidateProposal.model_validate(response.proposal)
                )
                proposals.append(proposal)
                total_invalid += invalid
                last_observation = response.observation
            if last_observation is None:
                raise ValueError("candidate proposal model unavailable")
            merged = _merge_paged_proposals(proposals)
            result = OntologyCandidateProposalResult(
                proposal=merged,
                selection=(
                    OntologyCandidateSelection.bind(
                        query=query, manifest=manifest, staged=staged, clauses=merged.clauses
                    )
                    if merged.status == "select"
                    else None
                ),
                input_digest=str(full_payload["input_digest"]),
                observation=last_observation,
                quote_invalid_clauses=total_invalid,
            )
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("candidate proposal deadline exceeded before publication")
            return result

    async def _propose_payload(
        self,
        *,
        query: str,
        manifest: QueryManifest,
        build: SemanticGenerationBuild,
        staged: OntologyStagedProjection,
        payload_factory: Callable[[], dict[str, object]],
        operation: str = "candidate_selection",
    ) -> OntologyCandidateProposalResult:
        if asyncio.get_running_loop() is not self._owner_loop:
            raise ValueError("candidate proposal must run on the model owner loop")
        if (
            len(self._config.candidates) != 1
            or self._config.timeout_seconds > _MAX_TIMEOUT_SECONDS
            or self._config.plan_prompt_manifest is None
            or self._config.plan_prompt_manifest.profile_id
            != "diagnostic.ontology-candidate-selection"
        ):
            raise ValueError("candidate proposal requires one bounded target and diagnostic prompt")
        deadline = asyncio.get_running_loop().time() + self._config.timeout_seconds
        async with asyncio.timeout(self._config.timeout_seconds):
            payload = payload_factory()
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("candidate proposal deadline exceeded before dispatch")
            response = await self._complete(
                payload=payload,
                prompt=self._config.plan_system_prompt,
                proposal_type=OntologyCandidateProposal,
                operation=operation,
                manifest=self._config.plan_prompt_manifest,
                query_manifest=manifest,
                build=build,
                max_attempts=1,
            )
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("candidate proposal deadline exceeded after return")
            if not isinstance(response, SemanticPlanningModelResponse):
                raise ValueError("candidate proposal model unavailable")
            proposal, invalid = filter_candidate_proposal_quotes(
                query, OntologyCandidateProposal.model_validate(response.proposal)
            )
            result = OntologyCandidateProposalResult(
                proposal=proposal,
                selection=(
                    OntologyCandidateSelection.bind(
                        query=query, manifest=manifest, staged=staged, clauses=proposal.clauses
                    )
                    if proposal.status == "select"
                    else None
                ),
                input_digest=str(payload["input_digest"]),
                observation=response.observation,
                quote_invalid_clauses=invalid,
            )
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("candidate proposal deadline exceeded before publication")
            return result


def _merge_paged_proposals(
    proposals: Sequence[OntologyCandidateProposal],
) -> OntologyCandidateProposal:
    if any(
        item.status == "clarify" and item.reason == "unresolved_reference" for item in proposals
    ):
        return OntologyCandidateProposal(
            status="clarify",
            reason="unresolved_reference",
            clauses=(),
            clause_quotes=(),
        )
    selected = [item for item in proposals if item.status == "select"]
    if not selected:
        reason: Literal["ambiguous_request", "unsupported_constraint"] = (
            "ambiguous_request"
            if any(item.reason == "ambiguous_request" for item in proposals)
            else "unsupported_constraint"
        )
        return OntologyCandidateProposal(
            status="clarify",
            reason=reason,
            clauses=(),
            clause_quotes=(),
        )
    grouped_clauses: dict[tuple[Any, ...], OntologyCandidateClause] = {}
    grouped_quotes: dict[tuple[Any, ...], str] = {}
    for proposal in selected:
        for clause, quote in zip(proposal.clauses, proposal.clause_quotes, strict=True):
            key = (
                clause.object_type,
                clause.predicates,
                clause.nested_predicates,
                clause.object_ids is None,
            )
            existing = grouped_clauses.get(key)
            if existing is None:
                grouped_clauses[key] = clause
                grouped_quotes[key] = quote
            elif existing.object_ids is not None and clause.object_ids is not None:
                merged_ids = tuple(dict.fromkeys((*existing.object_ids, *clause.object_ids)))
                grouped_clauses[key] = existing.model_copy(update={"object_ids": merged_ids})
    return OntologyCandidateProposal(
        status="select",
        reason="conditions_proposed",
        clauses=tuple(grouped_clauses.values())[:8],
        clause_quotes=tuple(grouped_quotes.values())[:8],
    )
