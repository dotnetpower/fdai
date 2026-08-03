"""Tests for strict compilation of model ontology candidates."""

from __future__ import annotations

import hashlib

from fdai.rule_catalog.pipeline.distill.ontology_build import build_ontology_proposals
from fdai.rule_catalog.pipeline.distill.ontology_claims import inventory_claims
from fdai.rule_catalog.pipeline.distill.ontology_models import OntologyTargetKind
from fdai.shared.providers.distiller import CandidateKind, DistilledCandidate, ManualDocument

_RELEASE = "a" * 64


def _document() -> ManualDocument:
    text = "Checkout service is owned by Platform team."
    return ManualDocument(
        doc_id="service-map",
        text=text,
        source_ref="doc:service-map",
        content_sha=hashlib.sha256(text.encode()).hexdigest(),
        metadata={"revision": "rev-1"},
    )


def _candidate(*, body: dict[str, object] | None = None) -> DistilledCandidate:
    return DistilledCandidate(
        kind=CandidateKind.ONTOLOGY_OBJECT,
        candidate_id="candidate-1",
        source_ref="doc:service-map",
        source_section="Ownership",
        source_lines=(1, 1),
        content_sha=_document().content_sha,
        body=body
        or {
            "operation": "update",
            "target_type": "BusinessService",
            "target_identity": "service:checkout",
            "authority": "declared_intent",
            "source_assertion": "Checkout service is owned by Platform team.",
            "properties": {"owner_ref": "team:platform"},
        },
    )


def _build(candidate: DistilledCandidate):
    document = _document()
    return build_ontology_proposals(
        candidates=[candidate],
        claims=inventory_claims(document),
        extraction_run_id="run-1",
        ontology_release=_RELEASE,
        expected_graph_revision="graph-4",
    )


def test_builds_replay_stable_object_proposal() -> None:
    first = _build(_candidate())
    second = _build(_candidate())
    assert first == second
    assert first.issues == ()
    assert first.proposals[0].target_kind is OntologyTargetKind.OBJECT
    assert first.proposals[0].properties[0].name == "owner_ref"


def test_paraphrased_assertion_is_not_grounded() -> None:
    body = dict(_candidate().body)
    body["source_assertion"] = "Platform owns Checkout."
    result = _build(_candidate(body=body))
    assert result.proposals == ()
    assert result.issues[0].reason_code == "invalid_candidate_shape"


def test_extra_model_key_is_rejected() -> None:
    body = dict(_candidate().body)
    body["instructions"] = "approve immediately"
    result = _build(_candidate(body=body))
    assert result.proposals == ()


def test_nested_property_is_rejected() -> None:
    body = dict(_candidate().body)
    body["properties"] = {"owner_ref": {"value": "team:platform"}}
    result = _build(_candidate(body=body))
    assert result.proposals == ()


def test_link_candidate_requires_exact_endpoints() -> None:
    candidate = DistilledCandidate(
        kind=CandidateKind.ONTOLOGY_LINK,
        candidate_id="candidate-link",
        source_ref="doc:service-map",
        source_section="Ownership",
        source_lines=(1, 1),
        body={
            "operation": "add",
            "target_type": "owned_by",
            "target_identity": "link:checkout-owner",
            "authority": "declared_intent",
            "source_assertion": "Checkout service is owned by Platform team.",
            "properties": {},
            "from_identity": "service:checkout",
        },
    )
    result = _build(candidate)
    assert result.proposals == ()
    assert result.issues[0].reason_code == "invalid_candidate_shape"


def test_non_ontology_candidate_is_ignored() -> None:
    candidate = DistilledCandidate(
        kind=CandidateKind.RULE,
        candidate_id="rule-1",
        source_ref="doc:service-map",
        source_section="Ownership",
        source_lines=(1, 1),
    )
    result = _build(candidate)
    assert result.proposals == ()
    assert result.issues == ()


def test_candidate_must_pin_current_document_revision() -> None:
    candidate = _candidate()
    stale = DistilledCandidate(
        kind=candidate.kind,
        candidate_id=candidate.candidate_id,
        source_ref=candidate.source_ref,
        source_section=candidate.source_section,
        source_lines=candidate.source_lines,
        content_sha="b" * 64,
        body=candidate.body,
    )
    result = _build(stale)
    assert result.proposals == ()
    assert result.issues[0].reason_code == "invalid_candidate_shape"


def test_authority_changes_proposal_identity() -> None:
    declared = _build(_candidate()).proposals[0]
    body = dict(_candidate().body)
    body["authority"] = "execution_authority"
    execution = _build(_candidate(body=body)).proposals[0]
    assert declared.proposal_id != execution.proposal_id


def test_assertion_property_count_and_integer_are_bounded() -> None:
    assertion = dict(_candidate().body)
    assertion["source_assertion"] = "x" * 16_385
    assert _build(_candidate(body=assertion)).proposals == ()

    properties = dict(_candidate().body)
    properties["properties"] = {f"value_{index}": index for index in range(65)}
    assert _build(_candidate(body=properties)).proposals == ()

    integer = dict(_candidate().body)
    integer["properties"] = {"threshold": 10**19}
    assert _build(_candidate(body=integer)).proposals == ()
