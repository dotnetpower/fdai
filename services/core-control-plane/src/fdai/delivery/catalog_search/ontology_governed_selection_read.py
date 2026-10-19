"""Budgeted hosted inference before, never inside, a deterministic ontology Function."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform import QueryManifest
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.core.ontology_platform.typed_selection_contracts import (
    ReadCapabilityBinding,
    ReadModelStageContract,
    ReadSelectionEvidence,
)
from fdai.delivery.persistence.state_store_typed_selection_read import StateStoreTypedSelectionRead

from .generation import SemanticGenerationBuild
from .ontology_candidate_context import (
    CandidateContextLimits,
    CandidateProposalContext,
    prepare_candidate_proposal_context,
)
from .ontology_candidate_proposal import (
    OntologyCandidateModelBinding,
    OntologyCandidateProposalResult,
)
from .ontology_candidate_selection import (
    OntologyCandidateSelection,
    SelectedOntologyCandidates,
    resolve_candidate_selection,
)
from .ontology_snapshot_store import OntologyStagedProjection
from .ontology_snapshot_validation import (
    OntologySnapshotValidation,
    validate_snapshot_against_current_graph,
)

if TYPE_CHECKING:
    from .ontology_index_lifecycle import IndexScope
    from .ontology_index_workers import OntologyContextIndexWorkers

_EVIDENCE_PREFIX = "typed-selection:"


@dataclass(frozen=True)
class ReadSelectionSource:
    binding: ReadCapabilityBinding
    manifest: QueryManifest
    build: SemanticGenerationBuild
    staged: OntologyStagedProjection
    validation: OntologySnapshotValidation
    gateway: SecuredObjectSetQueryGateway


class PreparedReadProposer(Protocol):
    def candidate_proposal_binding_for_manifest(
        self,
        manifest: QueryManifest,
        build: SemanticGenerationBuild | None = None,
    ) -> OntologyCandidateModelBinding: ...

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
    ) -> OntologyCandidateProposalResult: ...


async def typed_read_source(
    workers: OntologyContextIndexWorkers,
    scope: IndexScope,
    *,
    proposer: PreparedReadProposer,
    source_revision: str,
    data_policy_digest: str,
) -> ReadSelectionSource:
    """Resolve the current secured source without inference or authority changes."""
    target = await workers._current_target(scope)
    build = await workers._snapshots.read(
        target.staged.snapshot_digest,
        manifest=target.manifest,
        source_generation=target.staged.source_generation,
        source_projection_digest=target.staged.source_projection_digest,
    )
    if build is None:
        raise PermissionError("typed selection current snapshot is unavailable")
    validation = await validate_snapshot_against_current_graph(
        snapshots=workers._snapshots,
        staged=target.staged,
        gateway=target.gateway,
        manifest=target.manifest,
        as_of=workers._clock(),
        embedding_space_id=workers._space,
        embedding_model_version=workers._model,
        embedding_dimension=workers._dimension,
        validator_id="typed-selection-read-source",
    )
    binding = ReadCapabilityBinding(
        source_revision=source_revision,
        manifest_digest=target.manifest.manifest_digest,
        principal_scope_digest=scope.principal_scope_digest,
        model_binding_digest=content_digest(
            asdict(proposer.candidate_proposal_binding_for_manifest(target.manifest, build))
        ),
        data_policy_digest=data_policy_digest,
        context_protocol="typed-selection-context-transport.v1",
    )
    return ReadSelectionSource(
        binding, target.manifest, build, target.staged, validation, target.gateway
    )


class GovernedTypedSelectionRead:
    """Explicit admission, immutable handoff and no model calls during consumption."""

    contract = ReadModelStageContract()

    def __init__(
        self,
        *,
        registry: StateStoreTypedSelectionRead,
        source: Callable[[FunctionInvocationContext], Awaitable[ReadSelectionSource]] | None,
        proposer: PreparedReadProposer | None,
    ) -> None:
        self.registry = registry
        self.source = source
        self.proposer = proposer

    async def _source(self, context: FunctionInvocationContext) -> ReadSelectionSource:
        if (
            self.source is None
            or context.principal_ref is None
            or context.principal_scope_digest is None
            or context.caller_agent != "Bragi"
            or context.purposes != ("operations-review",)
        ):
            raise PermissionError("typed selection requires the current authenticated read source")
        source = await self.source(context)
        if (
            source.binding.principal_scope_digest != context.principal_scope_digest
            or source.binding.manifest_digest != source.manifest.manifest_digest
        ):
            raise PermissionError("typed selection current source scope changed")
        await self.registry.active(source.binding)
        return source

    @staticmethod
    def _same_source(first: ReadSelectionSource, second: ReadSelectionSource) -> bool:
        return (
            first.binding == second.binding
            and first.staged == second.staged
            and first.build.metadata.generation_digest == second.build.metadata.generation_digest
        )

    async def prepare(
        self,
        arguments: dict[str, Any],
        context: FunctionInvocationContext,
    ) -> FunctionInvocationContext:
        """Run exactly two bounded proposals and issue no evidence on failure/cancellation."""
        if self.proposer is None or len(context.evidence_refs) >= 64:
            raise PermissionError("typed selection qualified proposer is unavailable")
        query = arguments.get("query")
        limit = arguments.get("limit")
        if (
            not isinstance(query, str)
            or not query.strip()
            or len(query) > 4096
            or type(limit) is not int
            or not 1 <= limit <= 20
            or set(arguments) != {"query", "limit"}
        ):
            raise PermissionError("typed selection read arguments are invalid")
        request_ref = context.authentication_request_ref or "typed-read:" + uuid4().hex
        began = False
        try:
            async with asyncio.timeout(self.contract.total_timeout_seconds):
                source = await self._source(context)
                pointer = await self.registry.active(source.binding)
                model = self.proposer.candidate_proposal_binding_for_manifest(
                    source.manifest, source.build
                )
                if content_digest(asdict(model)) != source.binding.model_binding_digest:
                    raise PermissionError("typed selection actual model binding changed")
                packaged = prepare_candidate_proposal_context(
                    query=query,
                    manifest=source.manifest,
                    build=source.build,
                    staged=source.staged,
                    source_revision=source.binding.source_revision,
                    model_binding=model,
                    data_handling_policy_digest=source.binding.data_policy_digest,
                    source_validation=source.validation,
                )
                await self.registry.begin_request(request_ref)
                began = True
                tasks = []
                async with asyncio.TaskGroup() as group:
                    for _ in range(self.contract.max_model_calls):
                        tasks.append(
                            group.create_task(
                                self._propose(
                                    context=packaged,
                                    query=query,
                                    manifest=source.manifest,
                                    build=source.build,
                                    staged=source.staged,
                                    source_revision=source.binding.source_revision,
                                    data_handling_policy_digest=source.binding.data_policy_digest,
                                    source_validation=source.validation,
                                )
                            )
                        )
                results = [task.result() for task in tasks]
                selections = []
                for result in results:
                    if (
                        result.input_digest != packaged.context_digest
                        or result.proposal.status != "select"
                        or result.selection is None
                        or result.quote_invalid_clauses
                    ):
                        raise PermissionError("typed selection proposal requires clarification")
                    result.proposal.validate_source_quotes(query)
                    selections.append(result.selection)
                current = await self._source(context)
                if not self._same_source(source, current):
                    raise PermissionError("typed selection source drifted during inference")
                resolved = await asyncio.gather(
                    *(self._resolve(selection, query, current) for selection in selections)
                )
                memberships = tuple(
                    tuple(document.rule_id for document in value.documents) for value in resolved
                )
                if memberships[0] != memberships[1]:
                    raise PermissionError("typed selection proposals disagree")
                issued_at = self.registry.clock()
                evidence = ReadSelectionEvidence(
                    binding=current.binding,
                    registry_revision=pointer.revision,
                    qualification_digest=pointer.qualification_digest,
                    principal_ref=context.principal_ref or "",
                    request_ref=request_ref,
                    query_digest=content_digest({"query": query, "limit": limit}),
                    snapshot_digest=current.staged.snapshot_digest,
                    generation_digest=current.build.metadata.generation_digest,
                    source_projection_digest=current.staged.source_projection_digest,
                    selection_json=selections[0].model_dump_json(),
                    agreement_digest=content_digest({"memberships": memberships}),
                    issued_at=issued_at,
                    expires_at=issued_at + timedelta(seconds=30),
                )
                reference = await self.registry.save_selection(evidence)
                return context.model_copy(
                    update={
                        "authentication_request_ref": request_ref,
                        "evidence_refs": (*context.evidence_refs, _EVIDENCE_PREFIX + reference),
                    }
                )
        except BaseException:
            if began:
                await asyncio.shield(self.registry.cancel_request(request_ref))
            raise

    async def _resolve(
        self,
        selection: OntologyCandidateSelection,
        query: str,
        source: ReadSelectionSource,
    ) -> SelectedOntologyCandidates:
        return await resolve_candidate_selection(
            selection=selection,
            query=query,
            staged=source.staged,
            manifest=source.manifest,
            documents=source.build.documents,
            gateway=source.gateway,
            as_of=self.registry.clock(),
            deadline=asyncio.get_running_loop().time() + 5,
            resource_type_query_terms={},
        )

    async def _propose(self, **values: Any) -> OntologyCandidateProposalResult:
        if self.proposer is None:
            raise PermissionError("typed selection qualified proposer is unavailable")
        async with asyncio.timeout(self.contract.per_call_timeout_seconds):
            return await self.proposer.propose_prepared_candidate_selection(**values)

    async def consume(
        self,
        query: str,
        limit: int,
        context: FunctionInvocationContext,
    ) -> dict[str, object]:
        """Deterministic current-state validation only. This method never invokes a model."""
        references = tuple(
            value.removeprefix(_EVIDENCE_PREFIX)
            for value in context.evidence_refs
            if value.startswith(_EVIDENCE_PREFIX)
        )
        if len(references) != 1:
            raise PermissionError("typed selection requires one exact immutable evidence reference")
        evidence = await self.registry.selection(references[0])
        source = await self._source(context)
        if (
            evidence.binding != source.binding
            or evidence.principal_ref != context.principal_ref
            or evidence.request_ref != context.authentication_request_ref
            or evidence.query_digest != content_digest({"query": query, "limit": limit})
            or evidence.snapshot_digest != source.staged.snapshot_digest
            or evidence.generation_digest != source.build.metadata.generation_digest
            or evidence.source_projection_digest != source.staged.source_projection_digest
        ):
            raise PermissionError(
                "typed selection evidence scope, source, model or request drifted"
            )
        selected = await self._resolve(
            OntologyCandidateSelection.model_validate_json(evidence.selection_json), query, source
        )
        current = await self._source(context)
        if not self._same_source(source, current):
            raise PermissionError("typed selection source changed before consumption")
        await self.registry.consume(evidence)
        payload: dict[str, object] = {
            "candidates": [
                {
                    "id": record.id,
                    "object_type": record.object_type,
                    "properties": dict(record.properties),
                    "revision": record.revision,
                }
                for record in selected.objects[:limit]
            ],
            "evidence_refs": [*selected.query_receipt_digests, evidence.digest],
            "candidate_count": len(selected.documents),
            "truncated": len(selected.documents) > limit,
            "principal_scope_digest": source.binding.principal_scope_digest,
            "ontology_release_digest": source.manifest.release_digest,
            "query_digest": evidence.query_digest,
            "authority": "candidate_only",
            "execution_authority": False,
            "exhaustive": False,
        }
        return {**payload, "result_digest": content_digest(payload)}
