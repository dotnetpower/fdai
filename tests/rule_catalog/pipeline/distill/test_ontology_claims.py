"""Tests for deterministic ontology claim inventory and accounting."""

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


def test_reconcile_rejects_unknown_exact_candidate_and_claim_ids() -> None:
    document = _document("Checkout depends on Orders.")
    claims = inventory_claims(document)
    candidate = DistilledCandidate(
        kind=CandidateKind.ONTOLOGY_LINK,
        candidate_id="candidate-1",
        source_ref=document.source_ref,
        source_section="Service",
        source_lines=(1, 1),
    )

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


def test_mismatched_document_digest_fails_closed() -> None:
    document = ManualDocument(
        doc_id="runbook",
        text="Checkout depends on Orders.",
        source_ref="doc:runbook",
        content_sha="a" * 64,
    )
    with pytest.raises(ValueError, match="MUST match"):
        inventory_claims(document)


def test_document_digest_accepts_omitted_hash_and_rejects_invalid_format() -> None:
    text = "Checkout depends on Orders."
    without_hash = ManualDocument(
        doc_id="runbook",
        text=text,
        source_ref="doc:runbook",
        content_sha="",
    )
    invalid_hash = ManualDocument(
        doc_id="runbook",
        text=text,
        source_ref="doc:runbook",
        content_sha="A" * 64,
    )

    assert document_content_digest(without_hash) == hashlib.sha256(text.encode()).hexdigest()
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        document_content_digest(invalid_hash)


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


@pytest.mark.parametrize(
    ("text", "kind", "signals"),
    [
        (
            "You need to verify the backup first.",
            ClaimKind.NORMATIVE,
            {ClaimKind.NORMATIVE, ClaimKind.PROCEDURE},
        ),
        (
            "Do not restart the primary.",
            ClaimKind.NORMATIVE,
            {ClaimKind.NORMATIVE, ClaimKind.PROCEDURE},
        ),
        ("The controller does not create the group.", ClaimKind.NORMATIVE, {ClaimKind.NORMATIVE}),
        ("The probe depends on the service.", ClaimKind.RELATIONSHIP, {ClaimKind.RELATIONSHIP}),
        ("Keep between 1 and 10 replicas.", ClaimKind.THRESHOLD, {ClaimKind.THRESHOLD}),
        (
            "Before upgrading, back up the database first.",
            ClaimKind.PROCEDURE,
            {ClaimKind.PROCEDURE},
        ),
        ("First, look at the affected container logs.", ClaimKind.PROCEDURE, {ClaimKind.PROCEDURE}),
        ("Check the current revision.", ClaimKind.PROCEDURE, {ClaimKind.PROCEDURE}),
        ("Verify the restore point.", ClaimKind.PROCEDURE, {ClaimKind.PROCEDURE}),
        ("먼저 백업 상태를 확인하세요.", ClaimKind.PROCEDURE, {ClaimKind.PROCEDURE}),
        (
            "서비스를 다시 시작하지 마세요.",
            ClaimKind.NORMATIVE,
            {ClaimKind.NORMATIVE, ClaimKind.PROCEDURE},
        ),
        (
            "복제본 수는 1개에서 10개 사이여야 합니다.",
            ClaimKind.THRESHOLD,
            {ClaimKind.NORMATIVE, ClaimKind.THRESHOLD},
        ),
    ],
)
def test_inventory_preserves_adversarial_claim_signals(
    text: str,
    kind: ClaimKind,
    signals: set[ClaimKind],
) -> None:
    claims = inventory_claims(_document(text))
    assert len(claims) == 1
    assert claims[0].kind is kind
    assert signals.issubset(set(claims[0].signals))


def test_sentence_splitting_preserves_versions_urls_and_multiple_claims() -> None:
    claims = inventory_claims(
        _document(
            "Upgrade from v1.29.3 to v1.30.1. Verify https://example.com/v1.2.3/status first."
        )
    )
    assert len(claims) == 2
    assert all(claim.kind is ClaimKind.PROCEDURE for claim in claims)


def test_markup_only_units_are_not_claims_but_inline_emphasis_is_semantic() -> None:
    claims = inventory_claims(
        _document(
            '<sect1 id="backup-1">\n'
            "{{< caution >}}\n"
            "The database <emphasis>must</emphasis> be backed up first.\n"
            "<!-- overview -->\n"
            "{{< /caution >}}\n"
            "</sect1>\n"
        )
    )
    assert len(claims) == 1
    assert claims[0].kind is ClaimKind.NORMATIVE
    assert ClaimKind.PROCEDURE in claims[0].signals

    inline_document = _document("<!-- overview --> Check the current revision.")
    inline_claims = inventory_claims(inline_document)
    assert claim_text_records(inline_document, inline_claims)[0][1] == "Check the current revision."


def test_claim_text_reconstruction_rejects_changed_source_text() -> None:
    original = _document("Checkout depends on Orders.")
    changed = _document("Checkout depends on Inventory.")

    with pytest.raises(ValueError, match="MUST remain reconstructable"):
        claim_text_records(changed, inventory_claims(original))


def test_singular_dependency_phrase_is_a_relationship() -> None:
    claims = inventory_claims(
        _document("The readiness probe does not depend on the liveness probe.")
    )

    assert len(claims) == 1
    assert ClaimKind.NORMATIVE in claims[0].signals
    assert ClaimKind.RELATIONSHIP in claims[0].signals


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
