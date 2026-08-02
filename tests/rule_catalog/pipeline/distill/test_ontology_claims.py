"""Tests for deterministic ontology claim inventory and accounting."""

from __future__ import annotations

import hashlib

import pytest

from fdai.rule_catalog.pipeline.distill.ontology_claims import (
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


def _document(text: str) -> ManualDocument:
    return ManualDocument(
        doc_id="runbook",
        text=text,
        source_ref="doc:runbook",
        content_sha=hashlib.sha256(text.encode()).hexdigest(),
        metadata={"revision": "rev-3"},
    )


def test_inventory_classifies_operational_claims_and_skips_fences() -> None:
    document = _document(
        "# Service\n"
        "Checkout depends on Orders. CPU must remain below 80%.\n"
        "```text\nRestart must not count.\n```\n"
        "During the incident, latency was measured at 900ms.\n"
    )
    claims = inventory_claims(document)
    assert [claim.kind for claim in claims] == [
        ClaimKind.RELATIONSHIP,
        ClaimKind.THRESHOLD,
        ClaimKind.HISTORY,
    ]
    assert claims[0].authority is AuthorityClass.DECLARED_INTENT
    assert claims[1].critical is True
    assert claims[2].authority is AuthorityClass.HISTORICAL_EVIDENCE


def test_execution_permission_claim_is_critical_and_non_authoritative() -> None:
    claims = inventory_claims(_document("Operators may execute rollback without approval."))
    assert len(claims) == 1
    assert claims[0].authority is AuthorityClass.EXECUTION_AUTHORITY
    assert claims[0].critical is True


def test_claim_ids_are_stable_and_distinct_for_repeated_sentences() -> None:
    document = _document("Service A uses Service B. Service A uses Service B.")
    first = inventory_claims(document)
    second = inventory_claims(document)
    assert first == second
    assert len({claim.claim_id for claim in first}) == 2


def test_reconcile_accounts_for_mapped_and_unmapped_claims() -> None:
    document = _document("Checkout depends on Orders. CPU must remain below 80%.")
    claims = inventory_claims(document)
    candidate = DistilledCandidate(
        kind=CandidateKind.RULE,
        candidate_id="candidate-1",
        source_ref=document.source_ref,
        source_section="Service",
        source_lines=(1, 1),
    )
    resolutions = reconcile_claims(claims, [candidate])
    assert all(item.disposition is ClaimDisposition.MAPPED for item in resolutions)
    assert all(item.candidate_ids == ("candidate-1",) for item in resolutions)


def test_reconcile_rejects_duplicate_candidate_identity() -> None:
    document = _document("Checkout depends on Orders.")
    candidate = DistilledCandidate(
        kind=CandidateKind.RULE,
        candidate_id="duplicate",
        source_ref=document.source_ref,
        source_section="Service",
        source_lines=(1, 1),
    )
    with pytest.raises(ValueError, match="candidate ids MUST be unique"):
        reconcile_claims(inventory_claims(document), [candidate, candidate])


def test_mismatched_document_digest_fails_closed() -> None:
    document = ManualDocument(
        doc_id="runbook",
        text="Checkout depends on Orders.",
        source_ref="doc:runbook",
        content_sha="a" * 64,
    )
    with pytest.raises(ValueError, match="MUST match"):
        inventory_claims(document)


def test_provider_observation_and_korean_claims_are_classified() -> None:
    provider = inventory_claims(_document("The resource is currently deployed in the cluster."))
    assert provider[0].authority is AuthorityClass.PROVIDER_OBSERVATION

    korean = inventory_claims(
        _document("서비스는 데이터베이스에 의존하며 지연은 80ms 미만이어야 합니다.")
    )
    assert len(korean) == 1
    assert korean[0].critical is True


def test_percent_threshold_and_tilde_fence_handling() -> None:
    claims = inventory_claims(
        _document("CPU 80%.\n~~~text\n메모리는 90% 미만이어야 합니다.\n~~~\n")
    )
    assert len(claims) == 1
    assert claims[0].kind is ClaimKind.THRESHOLD


def test_exact_candidate_mapping_does_not_cover_sibling_claim() -> None:
    document = _document("Checkout depends on Orders. CPU must remain below 80%.")
    claims = inventory_claims(document)
    candidate = DistilledCandidate(
        kind=CandidateKind.ONTOLOGY_LINK,
        candidate_id="candidate-1",
        source_ref=document.source_ref,
        source_section="Service",
        source_lines=(1, 1),
    )
    resolutions = reconcile_claims(
        claims,
        [candidate],
        exact_candidate_claims={"candidate-1": claims[0].claim_id},
    )
    assert resolutions[0].disposition is ClaimDisposition.MAPPED
    assert resolutions[1].disposition is ClaimDisposition.NEEDS_REVIEW


def test_mismatched_fence_marker_does_not_expose_fenced_claims() -> None:
    claims = inventory_claims(
        _document("~~~text\n```\nCPU must remain below 80%.\n~~~\nCheckout depends on Orders.\n")
    )
    assert len(claims) == 1
    assert claims[0].kind is ClaimKind.RELATIONSHIP


def test_claim_inventory_rejects_oversized_document() -> None:
    with pytest.raises(ValueError, match="byte limit"):
        inventory_claims(_document("x" * 5_000_001))
