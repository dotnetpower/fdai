"""Bounded diagnostic candidate proposals over the planning adapter's HTTP boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from functools import partial
from typing import Any

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
    candidate_proposal_payload,
    filter_candidate_proposal_quotes,
)
from fdai.delivery.catalog_search.ontology_candidate_selection import OntologyCandidateSelection
from fdai.delivery.catalog_search.ontology_snapshot_store import OntologyStagedProjection
from fdai.delivery.catalog_search.ontology_snapshot_validation import OntologySnapshotValidation

from .semantic_planning_config import (
    AzureOpenAISemanticPlanningModelConfig,
    candidate_proposal_binding,
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

        return await self._propose_payload(
            query=query,
            manifest=manifest,
            build=build,
            staged=staged,
            payload_factory=payload_factory,
            operation="candidate_selection_prepared",
        )

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
