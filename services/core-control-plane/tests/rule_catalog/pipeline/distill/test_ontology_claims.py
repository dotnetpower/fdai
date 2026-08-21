"""Structural ontology claim inventory and accounting tests."""

from __future__ import annotations

import hashlib

import pytest
from fdai.rule_catalog.pipeline.distill.ontology_claims import (
    claim_text_records,
    document_content_digest,
    inventory_claims,
    reconcile_claims,
)
from fdai.rule_catalog.pipeline.distill.ontology_models import (
    AuthorityClass,
    ClaimDisposition,
    ClaimKind,
)
from fdai.shared.providers.distiller import (
    CandidateKind,
    DistilledCandidate,
    ManualDocument,
)


def _document(text: str, *, content_sha: str | None = None) -> ManualDocument:
    return ManualDocument(
        doc_id="runbook",
        text=text,
        source_ref="doc:runbook",
        content_sha=content_sha or hashlib.sha256(text.encode()).hexdigest(),
        metadata={"revision": "rev-3"},
    )


def test_inventory_keeps_all_prose_unclassified_and_skips_fences() -> None:
    document = _document(
        "# Service\n"
        "Checkout depends on Orders. CPU must remain below 80%.\n"
        "```text\nRestart must not count.\n```\n"
        "During the incident, latency was measured at 900ms.\n"
    )

    claims = inventory_claims(document)

    assert len(claims) == 3
    assert {claim.kind for claim in claims} == {ClaimKind.UNCLASSIFIED}
    assert {claim.authority for claim in claims} == {AuthorityClass.UNCLASSIFIED}
    assert all(claim.critical is False for claim in claims)
    assert [text for _claim_id, text in claim_text_records(document, claims)] == [
        "Checkout depends on Orders.",
        "CPU must remain below 80%.",
        "During the incident, latency was measured at 900ms.",
    ]


def test_claim_ids_are_stable_and_distinct_for_repeated_sentences() -> None:
    document = _document("Service A uses Service B. Service A uses Service B.")
    first = inventory_claims(document)
    assert first == inventory_claims(document)
    assert len({claim.claim_id for claim in first}) == 2


def test_reconcile_accounts_for_mapped_and_unmapped_claims() -> None:
    document = _document("Checkout depends on Orders.\nCPU must remain below 80%.")
    claims = inventory_claims(document)
    candidate = DistilledCandidate(
        kind=CandidateKind.RULE,
        candidate_id="candidate-1",
        source_ref=document.source_ref,
        source_section="Service",
        source_lines=(1, 1),
    )

    resolutions = reconcile_claims(claims, [candidate])

    assert resolutions[0].disposition is ClaimDisposition.MAPPED
    assert resolutions[1].disposition is ClaimDisposition.NEEDS_REVIEW


def test_reconcile_rejects_duplicate_or_unknown_identity() -> None:
    document = _document("Checkout depends on Orders.")
    claims = inventory_claims(document)
    candidate = DistilledCandidate(
        kind=CandidateKind.ONTOLOGY_LINK,
        candidate_id="candidate-1",
        source_ref=document.source_ref,
        source_section="Service",
        source_lines=(1, 1),
    )
    with pytest.raises(ValueError, match="candidate ids MUST be unique"):
        reconcile_claims(claims, [candidate, candidate])
    with pytest.raises(ValueError, match="known candidates"):
        reconcile_claims(
            claims,
            [candidate],
            exact_candidate_claims={"missing": claims[0].claim_id},
        )
    with pytest.raises(ValueError, match="known claims"):
        reconcile_claims(
            claims,
            [candidate],
            exact_candidate_claims={"candidate-1": "claim-missing"},
        )


def test_document_digest_and_reconstruction_fail_closed() -> None:
    document = _document("Service A uses Service B.")
    claims = inventory_claims(document)
    changed = _document("Service A no longer uses Service B.")

    assert document_content_digest(document) == hashlib.sha256(document.text.encode()).hexdigest()
    with pytest.raises(ValueError, match="reconstructable"):
        claim_text_records(changed, claims)
    with pytest.raises(ValueError, match="MUST match"):
        document_content_digest(_document(document.text, content_sha="0" * 64))


def test_claim_inventory_rejects_oversized_document() -> None:
    with pytest.raises(ValueError, match="byte limit"):
        inventory_claims(_document("x" * 5_000_001))
