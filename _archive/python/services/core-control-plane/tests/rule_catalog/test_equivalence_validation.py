from __future__ import annotations

from copy import deepcopy

import pytest
from fdai.rule_catalog.schema.equivalence_validation import (
    EquivalenceValidationCatalogError,
    EquivalenceValidationReceipt,
    equivalence_validation_content_hash,
    load_equivalence_validation_from_mapping,
    validate_equivalence_receipt_transition,
)

_DIGEST_A = f"sha256:{'a' * 64}"
_DIGEST_B = f"sha256:{'b' * 64}"
_DIGEST_C = f"sha256:{'c' * 64}"
_RULE_DIGESTS = {
    "kubernetes-node-pool.multi-zone@1.0.0": _DIGEST_A,
    "kubernetes-node-pool.zone-resilience@1.1.0": _DIGEST_B,
}


def _receipt_mapping() -> dict[str, object]:
    raw: dict[str, object] = {
        "schema_version": "1.0.0",
        "id": "equivalence.node-pool-zone-resilience",
        "version": "1.0.0",
        "compared_rules": [
            {
                "rule_ref": "kubernetes-node-pool.multi-zone@1.0.0",
                "content_digest": _DIGEST_A,
            },
            {
                "rule_ref": "kubernetes-node-pool.zone-resilience@1.1.0",
                "content_digest": _DIGEST_B,
            },
        ],
        "normalized_predicate_digests": [_DIGEST_A, _DIGEST_B],
        "required_evidence_refs": ["property.kubernetes-node-pool.availability_zones"],
        "parameter_domains": [{"name": "minimum-zone-count", "domain_digest": _DIGEST_C}],
        "counterexamples": {
            "reference": "counterexamples.node-pool-zone-resilience@1.0.0",
            "content_digest": _DIGEST_C,
            "case_count": 24,
        },
        "validator": {
            "name": "heimdall-equivalence-validator",
            "version": "1.0.0",
            "content_digest": _DIGEST_C,
        },
        "evaluator": {
            "name": "opa",
            "version": "0.68.0",
            "content_digest": _DIGEST_C,
        },
        "result": "validated",
        "claims": {
            "same_objective": True,
            "same_applicability": False,
            "same_behavior": False,
            "same_implementation": False,
        },
        "failures": [],
        "reviewer": "Heimdall",
        "state": "candidate",
        "content_digest": _DIGEST_C,
        "provenance": {
            "source_url": "https://github.com/dotnetpower/fdai",
            "resolved_ref": "equivalence-validation:node-pool-zone-resilience@1.0.0",
            "content_hash": _DIGEST_C,
            "license": "MIT",
            "retrieved_at": "2026-08-13T00:00:00Z",
        },
    }
    draft = EquivalenceValidationReceipt.model_validate(raw)
    digest = equivalence_validation_content_hash(draft)
    raw["content_digest"] = digest
    provenance = raw["provenance"]
    assert isinstance(provenance, dict)
    provenance["content_hash"] = digest
    return raw


def _load(raw: dict[str, object]) -> EquivalenceValidationReceipt:
    return load_equivalence_validation_from_mapping(raw, rule_digests=_RULE_DIGESTS)


def _with_state(raw: dict[str, object], state: str) -> dict[str, object]:
    raw["state"] = state
    draft = EquivalenceValidationReceipt.model_validate(raw)
    digest = equivalence_validation_content_hash(draft)
    raw["content_digest"] = digest
    provenance = raw["provenance"]
    assert isinstance(provenance, dict)
    provenance["content_hash"] = digest
    return raw


def test_valid_receipt_keeps_equivalence_claims_independent() -> None:
    receipt = _load(_receipt_mapping())

    assert receipt.claims.same_objective is True
    assert receipt.claims.same_applicability is False
    assert receipt.content_digest == equivalence_validation_content_hash(receipt)


@pytest.mark.parametrize("field", ["effect", "approval", "promotion_authority"])
def test_receipt_rejects_authority_fields(field: str) -> None:
    raw = _receipt_mapping()
    raw[field] = "forbidden"

    with pytest.raises(EquivalenceValidationCatalogError, match="Extra inputs"):
        _load(raw)


def test_receipt_rejects_rule_and_receipt_digest_drift_together() -> None:
    raw = deepcopy(_receipt_mapping())
    compared_rules = raw["compared_rules"]
    assert isinstance(compared_rules, list)
    first_rule = compared_rules[0]
    assert isinstance(first_rule, dict)
    first_rule["content_digest"] = _DIGEST_C
    raw["reviewer"] = "Changed reviewer"

    with pytest.raises(EquivalenceValidationCatalogError) as raised:
        _load(raw)

    messages = " ".join(issue.message for issue in raised.value.issues)
    assert "Rule digest mismatch" in messages
    assert "content_digest mismatch" in messages
    assert "provenance.content_hash mismatch" in messages


def test_same_implementation_requires_same_behavior() -> None:
    raw = _receipt_mapping()
    claims = raw["claims"]
    assert isinstance(claims, dict)
    claims["same_implementation"] = True

    with pytest.raises(EquivalenceValidationCatalogError, match="same_behavior"):
        _load(raw)


def test_receipt_cannot_bypass_independent_review_or_be_promoted() -> None:
    candidate = _load(_receipt_mapping())
    retired = _load(_with_state(_receipt_mapping(), "retired"))

    validate_equivalence_receipt_transition(candidate, retired)
    with pytest.raises(ValueError):
        EquivalenceValidationReceipt.model_validate({**_receipt_mapping(), "state": "promoted"})
