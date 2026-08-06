from __future__ import annotations

import pytest

from fdai.rule_catalog.schema.rule_semantic_feedback import (
    QueryFailureEvidence,
    RetrievalFailureLayer,
    build_feedback_candidate,
)

_A = "sha256:" + "a" * 64
_B = "sha256:" + "b" * 64
_C = "sha256:" + "c" * 64


def _evidence(**overrides: object) -> QueryFailureEvidence:
    values: dict[str, object] = {
        "attempt_id": "attempt:1",
        "query_digest": _A,
        "principal_scope_digest": _B,
        "catalog_digest": _C,
        "reason_code": "target-not-retrieved",
        "layer": RetrievalFailureLayer.RANKING_ERROR,
        "reproduced": True,
        "evidence_refs": ("receipt:retrieval:1",),
        "exact_target_rule_ref": "rule:public-access@1",
    }
    values.update(overrides)
    return QueryFailureEvidence(**values)  # type: ignore[arg-type]


def test_reproduced_retrieval_failure_creates_stable_challenger() -> None:
    left = build_feedback_candidate(_evidence())
    right = build_feedback_candidate(_evidence())

    assert left == right
    assert left.mode == "challenger_only"
    assert left.promotion_authority is False


def test_non_retrieval_failure_cannot_create_surface_candidate() -> None:
    with pytest.raises(ValueError, match="not owned"):
        build_feedback_candidate(_evidence(layer=RetrievalFailureLayer.PROVIDER_EVIDENCE))


def test_unreproduced_failure_cannot_create_surface_candidate() -> None:
    with pytest.raises(ValueError, match="reproduced"):
        build_feedback_candidate(_evidence(reproduced=False))


def test_user_correction_without_exact_target_is_not_an_oracle() -> None:
    with pytest.raises(ValueError, match="exact target"):
        build_feedback_candidate(
            _evidence(
                exact_target_rule_ref=None,
                user_correction_ref="conversation-turn:correction-1",
            )
        )


def test_feedback_contract_never_retains_raw_text() -> None:
    with pytest.raises(ValueError, match="raw operator text"):
        _evidence(raw_text_retained=True)
