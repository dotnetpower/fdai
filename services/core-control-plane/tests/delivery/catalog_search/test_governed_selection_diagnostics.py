"""Producer diagnoses are bounded, label-independent and preserve the evidence fence."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from fdai.core.ontology_platform.models import ObjectPredicate, ObjectPredicateOperator
from fdai.core.ontology_platform.query_gateway import UnsupportedObjectSetAsOfError
from fdai.delivery.catalog_search.ontology_candidate_proposal import OntologyCandidateProposal
from fdai.delivery.catalog_search.ontology_candidate_selection import (
    OntologyCandidateClause,
    OntologyCandidateSelection,
)
from fdai.delivery.catalog_search.ontology_governed_selection_read import GovernedTypedSelectionRead
from fdai.delivery.catalog_search.ontology_selection_errors import (
    GovernedReadError,
    SelectionFailure,
)
from fdai.delivery.persistence.state_store_typed_selection_read import StateStoreTypedSelectionRead
from tests.delivery.catalog_search.test_governed_typed_selection_read import _fixture, _promote

_QUERY = "Select the current resources."


@pytest.mark.parametrize(
    "kind,reason",
    [
        ("binding", SelectionFailure.PROPOSAL_BINDING_CHANGED),
        ("quote_count", SelectionFailure.CITATION_INVALID),
        ("quote_span", SelectionFailure.CITATION_INVALID),
        ("contract", SelectionFailure.PROPOSAL_CONTRACT_INVALID),
        ("unresolved_reference", SelectionFailure.UNRESOLVED_REFERENCE),
        ("unsupported_constraint", SelectionFailure.UNSUPPORTED_CONSTRAINT),
        ("ambiguous_request", SelectionFailure.AMBIGUOUS_REQUEST),
        ("provider", SelectionFailure.PROPOSAL_UNAVAILABLE),
        ("timeout", SelectionFailure.PROPOSAL_TIMEOUT),
    ],
)
async def test_exact_producer_reason_and_no_consumable_evidence(monkeypatch, kind, reason):
    f = await _fixture()
    await _promote(f)
    original = f.proposer.propose_prepared_candidate_selection

    async def propose(**values):
        if kind == "provider":
            raise ValueError("private provider payload")
        if kind == "timeout":
            raise TimeoutError("private provider payload")
        result = await original(**values)
        if kind == "binding":
            return replace(result, input_digest="sha256:" + "f" * 64)
        if kind == "quote_count":
            return replace(result, quote_invalid_clauses=1)
        if kind == "quote_span":
            return replace(
                result, proposal=result.proposal.model_copy(update={"clause_quotes": ("absent",)})
            )
        if kind == "contract":
            return replace(result, selection=None)
        return replace(
            result,
            proposal=OntologyCandidateProposal(
                status="clarify", reason=kind, clauses=(), clause_quotes=()
            ),
            selection=None,
        )

    monkeypatch.setattr(f.proposer, "propose_prepared_candidate_selection", propose)
    save = AsyncMock(wraps=f.registry.save_selection)
    monkeypatch.setattr(f.registry, "save_selection", save)
    context = f.context.model_copy(update={"authentication_request_ref": "diagnostic-request"})
    with pytest.raises(GovernedReadError) as caught:
        await f.reader.prepare({"query": _QUERY, "limit": 20}, context)
    assert caught.value.reason is reason
    assert "private" not in str(caught.value)
    request = await f.store.read_state(f.registry._request_key("diagnostic-request"))
    assert request == {"revision": 2, "active": False}
    save.assert_not_awaited()


@pytest.mark.parametrize(
    "error,reason",
    [
        (UnsupportedObjectSetAsOfError("private cutoff"), SelectionFailure.TIME_DRIFT),
        (PermissionError("private ACL"), SelectionFailure.MEMBERSHIP_DENIED),
        (ValueError("private contract"), SelectionFailure.PREDICATE_INVALID),
        (TimeoutError("private deadline"), SelectionFailure.MEMBERSHIP_TIMEOUT),
    ],
)
async def test_membership_and_time_failures_are_not_model_errors(monkeypatch, error, reason):
    f = await _fixture()
    await _promote(f)
    monkeypatch.setattr(f.current[0].gateway, "materialize", AsyncMock(side_effect=error))
    with pytest.raises(GovernedReadError) as caught:
        await f.reader.prepare({"query": _QUERY, "limit": 20}, f.context)
    assert caught.value.reason is reason
    assert "private" not in str(caught.value)


async def test_grouped_failure_cancels_sibling_and_retains_one_bounded_reason(monkeypatch):
    f = await _fixture()
    await _promote(f)
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    calls = 0

    async def propose(**values):
        nonlocal calls
        calls += 1
        if calls == 1:
            await entered.wait()
            raise ValueError("private proposal")
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(f.proposer, "propose_prepared_candidate_selection", propose)
    with pytest.raises(GovernedReadError) as caught:
        await f.reader.prepare({"query": _QUERY, "limit": 20}, f.context)
    assert caught.value.reason is SelectionFailure.PROPOSAL_UNAVAILABLE
    assert cancelled.is_set()


async def test_source_drift_is_distinct_from_agreement(monkeypatch):
    f = await _fixture()
    await _promote(f)
    original = f.reader.source
    calls = 0

    async def source(context):
        nonlocal calls
        calls += 1
        value = await original(context)
        if calls == 2:
            return replace(
                value,
                staged=replace(value.staged, snapshot_digest="sha256:" + "f" * 64),
            )
        return value

    monkeypatch.setattr(f.reader, "source", source)
    with pytest.raises(GovernedReadError) as caught:
        await f.reader.prepare({"query": _QUERY, "limit": 20}, f.context)
    assert caught.value.reason is SelectionFailure.SOURCE_DRIFT


async def test_reconstructed_registry_keeps_withdrawal_and_pending_evidence_fenced():
    f = await _fixture()
    pointer = await _promote(f)
    context = await f.reader.prepare({"query": _QUERY, "limit": 20}, f.context)
    await f.registry.demote(
        scope_digest=f.binding.principal_scope_digest,
        expected_revision=pointer.revision,
        reason="revoked",
        actor="Vidar",
    )
    restarted = StateStoreTypedSelectionRead(
        f.store,
        admission=f.admission,
        approvals=f.registry.approvals,
        clock=f.registry.clock,
    )
    reader = GovernedTypedSelectionRead(
        registry=restarted, source=f.reader.source, proposer=f.proposer
    )
    with pytest.raises(GovernedReadError) as caught:
        await reader.consume(_QUERY, 20, context)
    assert caught.value.reason is SelectionFailure.REGISTRY_UNAVAILABLE
    with pytest.raises(PermissionError):
        await restarted.qualification(f.qualification.digest)
    calls = f.proposer.calls
    with pytest.raises(GovernedReadError):
        await reader.prepare({"query": _QUERY, "limit": 20}, f.context)
    assert f.proposer.calls == calls


async def test_agreed_zero_candidate_membership_holds_without_saving_evidence(monkeypatch):
    f = await _fixture()
    await _promote(f)
    original = f.proposer.propose_prepared_candidate_selection

    async def propose(**values):
        result = await original(**values)
        clause = OntologyCandidateClause(
            object_type="Resource",
            predicates=(
                ObjectPredicate(
                    property="id",
                    operator=ObjectPredicateOperator.EQUALS,
                    equals="absent-resource",
                ),
            ),
        )
        proposal = OntologyCandidateProposal(
            status="select",
            reason="conditions_proposed",
            clauses=(clause,),
            clause_quotes=(values["query"],),
        )
        return replace(
            result,
            proposal=proposal,
            selection=OntologyCandidateSelection.bind(
                query=values["query"],
                manifest=values["manifest"],
                staged=values["staged"],
                clauses=(clause,),
            ),
        )

    monkeypatch.setattr(f.proposer, "propose_prepared_candidate_selection", propose)
    save = AsyncMock(wraps=f.registry.save_selection)
    monkeypatch.setattr(f.registry, "save_selection", save)
    with pytest.raises(GovernedReadError) as caught:
        await f.reader.prepare({"query": _QUERY, "limit": 20}, f.context)
    assert caught.value.reason is SelectionFailure.NO_CANDIDATE_MATCH
    assert caught.value.clarification is True
    save.assert_not_awaited()
