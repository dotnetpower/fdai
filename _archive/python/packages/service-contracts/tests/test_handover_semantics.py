"""Semantic references cannot advertise unsupported success or transport authority."""

import pytest
from fdai_service_contracts.handover_semantics import HandoverSemanticReceipt


def receipt(**changes):
    return HandoverSemanticReceipt.model_validate(
        {
            "source_id": "a" * 64,
            "source_revision": 1,
            "source_digest": "b" * 64,
            "compiler_digest": "c" * 64,
            "package_ref": "human_assignment:semantic-package:" + "d" * 64,
            "package_digest": "e" * 64,
            "disposition": "review_required",
            "reason": "candidates_compiled",
            "rule_count": 1,
            **changes,
        }
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("execution_authority", True),
        ("projection_authority", 0),
        ("promotion_authority", "false"),
        ("review_required", 1),
        ("rule_count", True),
        ("source_revision", True),
        ("rule_count", 0),
        ("ontology_count", 20),
        ("reason", "source_withdrawn"),
    ],
)
def test_semantic_receipt_rejects_authority_coercion_and_inconsistent_success(field, value):
    with pytest.raises(ValueError):
        receipt(**{field: value})


@pytest.mark.parametrize("disposition", ["held", "withdrawn"])
def test_negative_receipt_cannot_claim_compiled_candidates(disposition):
    with pytest.raises(ValueError):
        receipt(disposition=disposition, rule_count=0)


def test_typed_negative_outcome_stays_content_free():
    held = receipt(disposition="held", reason="no_supported_candidates", rule_count=0)
    assert held.model_dump(mode="json")["execution_authority"] is False
    assert held.review_required is True
