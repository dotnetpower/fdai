"""Operations PostgreSQL and unavailable family adapters."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass

from fdai_service_contracts import OperatorRole
from starlette.exceptions import HTTPException

from fdai_operator_service.context_selection import ContextSelectionRegistry
from fdai_operator_service.families.operations.contracts import (
    EventProposal,
    ProjectionNotFoundError,
    ProjectionQuery,
    ProjectionUnavailableError,
    ProposalConflictError,
    ProposalReceipt,
    ReplayBatch,
    ReplayEvent,
    ReplayQuery,
)
from fdai_operator_service.families.operations.instance_explorer import (
    project_inventory_instance,
    project_inventory_instances,
)
from fdai_operator_service.families.operations.instance_states import project_inventory_states
from fdai_operator_service.families.operations.inventory_impact import project_inventory_impact
from fdai_operator_service.family_adapter_values import mapping as _mapping
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreUnavailable,
    PostgresProposalConflict,
)
from fdai_operator_service.postgres_read_investigation_replay import (
    PostgresReadInvestigationReplayStore,
)


@dataclass(frozen=True, slots=True)
class PostgresOperationsAdapters:
    """Serve operations projections, proposals, replay, and signed webhook intake."""

    store: PostgresFamilyStore
    webhook_secret: str | None = None
    read_investigation_replay: PostgresReadInvestigationReplayStore | None = None
    context_selection_registry: ContextSelectionRegistry | None = None

    async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
        """Read one explicitly materialized operations projection."""
        if query.operation in {
            "blast_radius.simulate",
            "ontology.instance.explore",
            "ontology.instance.list",
            "ontology.instance.states",
        }:
            try:
                ontology_projection = await self.store.read_projection(
                    family="operations",
                    operation="ontology.graph",
                )
                if query.operation == "ontology.instance.states":
                    return await project_inventory_states(
                        query=query,
                        reader=self.store,
                        ontology_projection=ontology_projection,
                    )
                if query.operation == "ontology.instance.explore":
                    return await project_inventory_instance(
                        query=query,
                        reader=self.store,
                        ontology_projection=ontology_projection,
                        selection_registry=self.context_selection_registry,
                    )
                if query.operation == "ontology.instance.list":
                    return await project_inventory_instances(
                        query=query,
                        reader=self.store,
                        ontology_projection=ontology_projection,
                        selection_registry=self.context_selection_registry,
                    )
                return await project_inventory_impact(
                    query=query,
                    reader=self.store,
                    ontology_projection=ontology_projection,
                )
            except PostgresFamilyStoreUnavailable as exc:
                raise ProjectionUnavailableError from exc
        operation = query.operation
        if operation in {"ontology.declaration.detail", "ontology.declaration.dependents"}:
            operation = (
                f"ontology.declaration.detail.{_highest_operator_role(query.roles).value.lower()}"
            )
        try:
            payload = await self.store.read_projection(
                family="operations",
                operation=operation,
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise ProjectionUnavailableError from exc
        if query.operation == "ontology.declaration.detail":
            return _ontology_declaration_projection(payload, query, section="details")
        if query.operation == "ontology.declaration.dependents":
            return _ontology_declaration_projection(payload, query, section="dependents")
        if query.operation == "ontology.release.diff":
            return _ontology_release_diff(payload, query)
        if query.operation == "ontology.evidence.health":
            return _ontology_evidence_health(payload, query)
        return payload

    async def propose(self, proposal: EventProposal) -> ProposalReceipt:
        """Persist one event proposal without publishing or executing it."""
        try:
            stored = await self.store.append_proposal(
                family="operations",
                operation=proposal.operation,
                principal_id=proposal.principal_id,
                idempotency_key=proposal.idempotency_key,
                payload=_mapping(asdict(proposal)),
            )
        except PostgresProposalConflict as exc:
            raise ProposalConflictError from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return ProposalReceipt(
            request_id=stored.proposal_id,
            correlation_id=proposal.correlation_id,
            dispatch_status="pending",
            accepted_at=stored.accepted_at,
        )

    async def replay(self, query: ReplayQuery) -> ReplayBatch:
        """Replay authoritative audit events using the durable sequence watermark."""

        if query.stream.startswith("read-investigation:"):
            if self.read_investigation_replay is None:
                raise ProjectionUnavailableError
            return await self.read_investigation_replay.replay(query)
        try:
            stored = await self.store.replay(
                stream=query.stream,
                principal_id=query.principal_id,
                after_sequence=query.after_sequence,
                limit=query.limit,
                **({"cursor_epoch": query.cursor_epoch} if query.cursor_epoch is not None else {}),
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise ProjectionUnavailableError from exc
        events = tuple(ReplayEvent(record.sequence, record.event, record.data) for record in stored)
        watermark = events[-1].sequence if events else query.after_sequence or 0
        return ReplayBatch(events=events, watermark=watermark)

    async def verify(
        self,
        operation: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> bool:
        """Verify an HMAC signature before accepting webhook proposals."""
        del operation
        if self.webhook_secret is None:
            raise HTTPException(status_code=503, detail="webhook signing input is unavailable")
        supplied = headers.get("x-fdai-signature", "")
        if not supplied.startswith("sha256="):
            return False
        expected = hmac.new(self.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, supplied[len("sha256=") :])


class UnavailableOperationsAdapters:
    """Fail all operations dependencies closed while keeping their routes visible."""

    async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
        del query
        raise ProjectionUnavailableError

    async def propose(self, proposal: EventProposal) -> ProposalReceipt:
        del proposal
        raise HTTPException(status_code=503, detail="event proposal outbox is unavailable")

    async def replay(self, query: ReplayQuery) -> ReplayBatch:
        del query
        raise ProjectionUnavailableError

    async def verify(
        self,
        operation: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> bool:
        del operation, headers, body
        raise HTTPException(status_code=503, detail="webhook signing input is unavailable")


_OPERATOR_ROLE_RANK = {
    OperatorRole.READER: 0,
    OperatorRole.CONTRIBUTOR: 1,
    OperatorRole.APPROVER: 2,
    OperatorRole.OWNER: 3,
}


def _highest_operator_role(roles: frozenset[OperatorRole]) -> OperatorRole:
    ordinary_roles = roles & _OPERATOR_ROLE_RANK.keys()
    if not ordinary_roles:
        raise ProjectionUnavailableError("ordinary Operator role is unavailable")
    return max(ordinary_roles, key=_OPERATOR_ROLE_RANK.__getitem__)


def _ontology_declaration_projection(
    payload: Mapping[str, object],
    query: ProjectionQuery,
    *,
    section: str,
) -> Mapping[str, object]:
    if payload.get("purpose") != query.purpose or payload.get("mutation_authority") is not False:
        raise ProjectionUnavailableError("ontology declaration projection boundary is invalid")
    details = payload.get(section)
    if not isinstance(details, Mapping):
        raise ProjectionUnavailableError("ontology declaration projection is malformed")
    kind = query.path.get("kind", "")
    declarations = details.get(kind)
    if not isinstance(declarations, Mapping):
        raise ProjectionNotFoundError(kind)
    declaration = declarations.get(query.path.get("name", ""))
    if not isinstance(declaration, Mapping):
        raise ProjectionNotFoundError(query.path.get("name", ""))
    return declaration


def _ontology_release_diff(
    payload: Mapping[str, object],
    query: ProjectionQuery,
) -> Mapping[str, object]:
    if payload.get("mutation_authority") is not False:
        raise ProjectionUnavailableError("ontology release diff boundary is invalid")
    candidate = query.path.get("candidate_digest", "")
    if re.fullmatch(r"sha256:[a-f0-9]{64}", candidate) is None:
        raise ValueError("candidate ontology release digest MUST be sha256")
    release_digests = payload.get("release_digests")
    diffs = payload.get("diffs")
    if not isinstance(release_digests, list) or not isinstance(diffs, Mapping):
        raise ProjectionUnavailableError("ontology release diff registry is malformed")
    requested_base = query.params.get("base", (None,))[-1]
    if requested_base is None:
        try:
            candidate_index = release_digests.index(candidate)
        except ValueError as exc:
            raise ProjectionNotFoundError(candidate) from exc
        if candidate_index == 0:
            raise ProjectionNotFoundError("previous ontology release")
        base = release_digests[candidate_index - 1]
    else:
        base = requested_base
    if not isinstance(base, str) or re.fullmatch(r"sha256:[a-f0-9]{64}", base) is None:
        raise ValueError("base ontology release digest MUST be sha256")
    diff = diffs.get(f"{candidate}|{base}")
    if not isinstance(diff, Mapping):
        raise ProjectionNotFoundError(f"{candidate}|{base}")
    return {
        **diff,
        "registry_truncated": payload.get("truncated") is True,
        "registry_truncation_reason": payload.get("truncation_reason"),
    }


def _ontology_evidence_health(
    payload: Mapping[str, object],
    query: ProjectionQuery,
) -> Mapping[str, object]:
    if payload.get("mutation_authority") is not False:
        raise ProjectionUnavailableError("ontology evidence health boundary is invalid")
    health = payload.get("evidence_health")
    if not isinstance(health, Mapping):
        raise ProjectionUnavailableError("ontology evidence health registry is malformed")
    name = query.path.get("name", "")
    projection = health.get(name)
    if not isinstance(projection, Mapping):
        raise ProjectionNotFoundError(name)
    return projection


__all__ = ["PostgresOperationsAdapters", "UnavailableOperationsAdapters"]
