"""Pinned registries: strict loading, content-classified revisions, grants, and separation."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from fdai.core.operational_evidence.grant_registry_loader import load_grant_registry
from fdai.core.operational_evidence.registry_json import (
    RegistryUnavailableError,
    RevisionClass,
    content_pin,
)
from fdai.core.operational_evidence.revision_history import (
    LineageBinding,
    RegistryHistory,
    RegistryRevision,
)
from fdai.core.operational_evidence.separation import (
    ProofStoreGrantReadback,
    VerifierSeparationError,
    assert_verifier_separation,
)
from fdai.core.operational_evidence.trust_registry import (
    classify_trust_revision,
    purpose_defects,
)
from fdai.core.operational_evidence.trust_registry_loader import (
    load_trust_registry,
)
from fdai_service_contracts.operational_evidence import (
    OPERATIONAL_EVIDENCE_PURPOSES,
    OperationalEvidenceRejectionClass,
)
from tests.core.operational_evidence.support import (
    NOW,
    REQUESTER,
    REQUESTER_GROUP,
    SCOPE,
    TARGET,
    anchors,
    encode,
    grant_document,
    receipt,
    trust_bytes,
)

_R = OperationalEvidenceRejectionClass


def _trust(document: dict[str, Any] | None = None) -> tuple[bytes, Any]:
    data = trust_bytes() if document is None else encode(document)
    return data, load_trust_registry(data, expected_pin=content_pin(data))


def _grants(document: dict[str, Any] | None = None) -> Any:
    data = encode(document or grant_document())
    return load_grant_registry(data, expected_pin=content_pin(data))


def _trust_document() -> dict[str, Any]:
    return json.loads(trust_bytes())


def test_upstream_registry_covers_every_purpose_with_logical_identifiers_only() -> None:
    _data, registry = _trust()
    assert set(registry.purposes) | set(registry.defects) == set(OPERATIONAL_EVIDENCE_PURPOSES)
    assert registry.defects == {}
    text = trust_bytes().decode()
    for forbidden in ("https://", "subscriptions/", ".azure.com", "password", "secret"):
        assert forbidden not in text
    ceilings = {
        entry["purpose_id"]: entry["freshness_policy"]["ceiling_seconds"]
        for entry in _trust_document()["purposes"]
    }
    assert ceilings["operator-test-context-command"] == 600
    assert ceilings["test-context-transition"] == 120
    assert ceilings["operational-test-context"] == 300
    assert ceilings["operational-test-observation"] == 300
    assert ceilings["case-history-read"] == 60
    assert ceilings["current-case-reuse"] == 300
    assert {ceilings[key] for key in ceilings if key.startswith("forecast-")} == {3600}


def test_pin_mismatch_makes_every_purpose_unavailable() -> None:
    with pytest.raises(RegistryUnavailableError, match="reviewed pin"):
        load_trust_registry(trust_bytes(), expected_pin="sha256:" + "0" * 64)


@pytest.mark.parametrize(
    ("mutation", "defect"),
    [
        ("unknown_field", "invalid_entry"),
        ("duplicate_purpose", "duplicate_purpose"),
    ],
)
def test_defective_purpose_entry_is_unavailable_while_others_stay_bound(
    mutation: str, defect: str
) -> None:
    document = _trust_document()
    entry = next(item for item in document["purposes"] if item["purpose_id"] == "case-history-read")
    if mutation == "unknown_field":
        entry["extra"] = True
    else:
        document["purposes"].append(dict(entry))
    _data, registry = _trust(document)
    assert registry.defects["case-history-read"] == (defect,)
    assert "operator-test-context-command" in registry.purposes


def test_duplicate_json_key_inside_one_purpose_is_unavailable() -> None:
    text = (
        trust_bytes()
        .decode()
        .replace(
            '"purpose_id": "case-history-read",',
            '"purpose_id": "case-history-read",\n      "revoked": false,',
            1,
        )
    )
    data = text.encode()
    registry = load_trust_registry(data, expected_pin=content_pin(data))
    assert registry.defects["case-history-read"] == ("duplicate_key",)


def test_missing_anchor_or_shared_principal_blocks_one_purpose() -> None:
    _data, registry = _trust()
    bound = anchors()
    purpose = "operator-test-context-command"
    verifier = "operational-evidence-verifier"
    assert purpose_defects(registry, bound, purpose_id=purpose, verifier_id=verifier, at=NOW) == ()
    missing = anchors(overrides={})
    missing = type(bound)(
        venue=bound.venue,
        bindings={k: v for k, v in bound.bindings.items() if k != "anchor:operator-service"},
    )
    assert purpose_defects(registry, missing, purpose_id=purpose, verifier_id=verifier, at=NOW) == (
        "anchor_missing",
    )
    shared = anchors(overrides={"anchor:operator-service": "fdai_operational_evidence_verifier"})
    assert purpose_defects(registry, shared, purpose_id=purpose, verifier_id=verifier, at=NOW) == (
        "self_verified",
    )
    deployed = anchors(venue="deployed")
    assert "local_loopback_anchor_in_deployed_venue" in purpose_defects(
        registry, deployed, purpose_id=purpose, verifier_id=verifier, at=NOW
    )


def _narrow_validity(document: dict[str, Any]) -> None:
    document["purposes"][0]["verifiers"][0]["valid_until"] = "2027-01-01T00:00:00+00:00"


def _remove_producer(document: dict[str, Any]) -> None:
    document["purposes"][0]["producers"][0]["producer_version"] = "2.0.0"


def _remove_purpose(document: dict[str, Any]) -> None:
    document["purposes"] = document["purposes"][1:]


def _revoke_verifier(document: dict[str, Any]) -> None:
    document["purposes"][0]["verifiers"][0]["revoked"] = True


def _shorten_ceiling(document: dict[str, Any]) -> None:
    document["purposes"][0]["freshness_policy"]["ceiling_seconds"] = 30


def _rotate(document: dict[str, Any]) -> None:
    current = dict(document["purposes"][0]["verifiers"][0])
    document["purposes"][0]["verifiers"].append({**current, "verifier_version": "1.1.0"})


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (_narrow_validity, RevisionClass.REVOCATION),
        (_remove_producer, RevisionClass.REVOCATION),
        (_remove_purpose, RevisionClass.REVOCATION),
        (_revoke_verifier, RevisionClass.REVOCATION),
        (_shorten_ceiling, RevisionClass.REVOCATION),
        (_rotate, RevisionClass.ROUTINE_ROTATION),
    ],
)
def test_trust_revisions_are_classified_by_content_not_label(mutate: Any, expected: Any) -> None:
    _before_data, before = _trust()
    document = _trust_document()
    document["revision"] = 2
    mutate(document)
    _after_data, after = _trust(document)
    assert classify_trust_revision(before, after) is expected


def _history(*grant_documents: dict[str, Any]) -> RegistryHistory:
    _data, trust = _trust()
    return RegistryHistory(
        tuple(RegistryRevision(trust=trust, grants=_grants(doc)) for doc in grant_documents)
    )


def test_unlabeled_removal_retires_earlier_pins_while_rotation_keeps_them() -> None:
    base = grant_document()
    removed = grant_document()
    removed["revision"] = 2
    removed["principal_grants"] = removed["principal_grants"][1:]
    history = _history(base, removed)
    assert history.step_classes() == (RevisionClass.REVOCATION,)
    assert history.admitting_pins() == {history.current.pins.digest}

    added = grant_document()
    added["revision"] = 2
    added["principal_grants"].append(
        {**added["principal_grants"][0], "grant_id": "g-extra", "reviewer": "grant-reviewer-two"}
    )
    rotated = _history(base, added)
    assert rotated.step_classes() == (RevisionClass.ROUTINE_ROTATION,)
    assert len(rotated.admitting_pins()) == 2


def test_lineage_ends_only_when_its_matched_grant_is_revoked() -> None:
    base = grant_document()
    unrelated = grant_document()
    unrelated["revision"] = 2
    unrelated["principal_grants"][1]["revoked"] = True
    matched = grant_document()
    matched["revision"] = 2
    matched["principal_grants"][0]["revoked"] = True
    binding = LineageBinding(
        purpose_id="test-context-transition",
        verifier_id="operational-evidence-verifier",
        verifier_version="1.0.0",
        trust_anchor_id="anchor:operational-evidence-verifier",
        matched_grants=("g-propose",),
    )
    still = _history(base, unrelated)
    pins = still._revisions[0].pins.digest  # noqa: SLF001 - oldest revision identity
    assert still.admitting_pins() == {still.current.pins.digest}
    assert still.lineage_intact(pins, binding, at=NOW)
    ended = _history(base, matched)
    assert not ended.lineage_intact(ended._revisions[0].pins.digest, binding, at=NOW)  # noqa: SLF001


def test_equal_digests_never_establish_authority() -> None:
    document = grant_document()
    for grant in document["principal_grants"]:
        grant["selector"]["value"] = "00000000-0000-0000-0000-000000000077"
    registry = _grants(document)
    decision = registry.authorize(
        receipt(REQUESTER, SCOPE, ("Contributor",), issued_at=NOW),
        access_scope_digest=SCOPE,
        operation="test-context.propose",
        purpose_id="operator-test-context-command",
        at=NOW,
        target_ref=TARGET,
    )
    assert not decision.allowed
    assert decision.rejection_class is _R.CROSS_SCOPE
    assert decision.reasons == ("grant_missing",)


def test_matching_revoked_or_expired_grant_denies_even_beside_an_allowing_grant() -> None:
    document = grant_document()
    allowing = dict(document["principal_grants"][0])
    revoked = {**allowing, "grant_id": "g-revoked", "revoked": True}
    document["principal_grants"].append(revoked)
    decision = _grants(document).authorize(
        receipt(REQUESTER, REQUESTER_GROUP, ("Contributor",), issued_at=NOW),
        access_scope_digest=SCOPE,
        operation="test-context.propose",
        purpose_id="operator-test-context-command",
        at=NOW,
    )
    assert decision.rejection_class is _R.REVOKED
    expired = grant_document()
    expired["principal_grants"][0]["valid_until"] = (NOW - timedelta(days=1)).isoformat()
    stale = _grants(expired).authorize(
        receipt(REQUESTER, REQUESTER_GROUP, ("Contributor",), issued_at=NOW),
        access_scope_digest=SCOPE,
        operation="test-context.propose",
        purpose_id="operator-test-context-command",
        at=NOW,
    )
    assert stale.rejection_class is _R.STALE


def test_overlapping_grants_never_widen_scope_or_operation() -> None:
    document = grant_document()
    second_scope = {**document["case_scopes"][0], "case_scope_id": "cs-other"}
    second_scope["access_scope_digest"] = "b" * 64
    document["case_scopes"].append(second_scope)
    document["principal_grants"][1]["selector"]["value"] = REQUESTER_GROUP
    document["principal_grants"][1]["case_scopes"] = ["cs-other"]
    registry = _grants(document)
    decision = registry.authorize(
        receipt(REQUESTER, REQUESTER_GROUP, ("Approver",), issued_at=NOW),
        access_scope_digest=SCOPE,
        operation="test-context.review",
        purpose_id="test-context-transition",
        at=NOW,
    )
    assert decision.rejection_class is _R.CROSS_SCOPE
    outside = registry.authorize(
        receipt(REQUESTER, REQUESTER_GROUP, ("Contributor",), issued_at=NOW),
        access_scope_digest=SCOPE,
        operation="test-context.propose",
        purpose_id="operator-test-context-command",
        at=NOW,
        target_ref="/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-prod/x",
    )
    assert outside.reasons == ("target_outside_case_scope",)


def test_reuse_grant_requires_one_current_case_to_target_mapping() -> None:
    document = grant_document()
    document["reuse_grants"] = [
        {
            "grant_id": "r-test",
            "case_scopes": ["cs-test"],
            "target_scope_digest": "c" * 64,
            **{key: document["case_scopes"][0][key] for key in ("valid_from", "valid_until")},
            "revoked": False,
        }
    ]
    registry = _grants(document)
    assert registry.authorize_reuse(
        case_scope_digest=SCOPE, target_scope_digest="c" * 64, at=NOW
    ).allowed
    assert (
        registry.authorize_reuse(
            case_scope_digest=SCOPE, target_scope_digest="d" * 64, at=NOW
        ).rejection_class
        is _R.CROSS_SCOPE
    )


def test_malformed_grant_registry_is_unavailable_as_a_whole() -> None:
    document = grant_document()
    document["principal_grants"][0]["selector"]["kind"] = "display_name"
    with pytest.raises(RegistryUnavailableError):
        _grants(document)


def test_verifier_refuses_to_start_on_any_identity_equality() -> None:
    _data, registry = _trust()
    assert_verifier_separation(
        registry,
        anchors(),
        verifier_principal="fdai_operational_evidence_verifier",
        executor_class_principals=("local-isolated-executor",),
    )
    for principal in (
        "fdai_core",
        "fdai_operator",
        "local-operator-reviewers",
        "local-deploy-runner",
    ):
        with pytest.raises(VerifierSeparationError):
            assert_verifier_separation(
                registry,
                anchors(),
                verifier_principal=principal,
                executor_class_principals=(),
            )
    with pytest.raises(VerifierSeparationError):
        assert_verifier_separation(
            registry,
            anchors(),
            verifier_principal="fdai_operational_evidence_verifier",
            executor_class_principals=("fdai_operational_evidence_verifier",),
        )


def test_writer_readback_reports_self_verified_for_any_foreign_writer() -> None:
    clean = ProofStoreGrantReadback(
        writer_role="fdai_operational_evidence_verifier",
        reader_roles=("fdai_core",),
        insert_holders=("fdai_operational_evidence_verifier",),
        mutation_holders=(),
        writer_role_members=(),
        immutability_guards=("a",),
        expected_guards=("a",),
    )
    assert clean.self_verified_reasons() == ()
    foreign = ProofStoreGrantReadback(
        writer_role="fdai_operational_evidence_verifier",
        reader_roles=("fdai_core",),
        insert_holders=("fdai_core", "fdai_operational_evidence_verifier"),
        mutation_holders=("fdai_core",),
        writer_role_members=("fdai_core",),
        immutability_guards=(),
        expected_guards=("a",),
    )
    assert foreign.self_verified_reasons() == (
        "consumer_holds_writer_role",
        "foreign_insert_grant",
        "foreign_writer_membership",
        "immutability_guard_missing",
        "update_or_delete_grant",
    )


def test_future_dated_match_neither_grants_nor_denies_a_current_grant() -> None:
    document = grant_document()
    future = {
        **document["principal_grants"][0],
        "grant_id": "g-future",
        "valid_from": (NOW + timedelta(days=1)).isoformat(),
        "valid_until": (NOW + timedelta(days=30)).isoformat(),
    }
    document["principal_grants"].append(future)
    principal = receipt(REQUESTER, REQUESTER_GROUP, ("Contributor",), issued_at=NOW)
    arguments: dict[str, Any] = {
        "access_scope_digest": SCOPE,
        "operation": "test-context.propose",
        "purpose_id": "operator-test-context-command",
        "at": NOW,
    }
    decision = _grants(document).authorize(principal, **arguments)
    assert decision.allowed and decision.matched_grants == ("g-propose",)
    document["principal_grants"] = [future, *document["principal_grants"][1:-1]]
    only_future = _grants(document).authorize(principal, **arguments)
    assert only_future.rejection_class is _R.CROSS_SCOPE
    assert only_future.reasons == ("grant_missing",)
