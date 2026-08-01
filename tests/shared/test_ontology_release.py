"""Exact ontology release identity tests."""

from __future__ import annotations

import pytest

from fdai.shared.contracts.models import (
    OntologyActionType,
    OntologyDeclarationKind,
    Operation,
    PromotionGate,
    RollbackKind,
)
from fdai.shared.ontology.release import build_ontology_release


def _action(name: str, version: str = "1.0.0") -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name=name,
        version=version,
        operation=Operation.UPDATE,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        promotion_gate=PromotionGate(
            min_shadow_days=1,
            min_samples=1,
            min_accuracy=1.0,
            max_policy_escapes=0,
        ),
    )


def test_release_digest_is_order_independent_and_version_sensitive() -> None:
    first = _action("ops.alpha")
    second = _action("ops.beta")

    release = build_ontology_release(action_types=(first, second))
    reordered = build_ontology_release(action_types=(second, first))
    revised = build_ontology_release(action_types=(first, _action("ops.beta", "2.0.0")))

    assert release.digest == reordered.digest
    assert release.digest != revised.digest


def test_release_returns_exact_type_reference() -> None:
    release = build_ontology_release(action_types=(_action("ops.alpha"),))

    reference = release.type_ref(OntologyDeclarationKind.ACTION, "ops.alpha")

    assert reference.version == "1.0.0"
    assert reference.catalog_digest == release.digest


def test_release_rejects_duplicate_declaration_identity() -> None:
    with pytest.raises(ValueError, match="identities MUST be unique"):
        build_ontology_release(action_types=(_action("ops.alpha"), _action("ops.alpha")))
