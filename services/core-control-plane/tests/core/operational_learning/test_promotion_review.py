from __future__ import annotations

import pytest
from fdai.core.operational_learning.promotion_review import (
    ReviewedReplayAuthority,
    ReviewedReplayPromotionEvidence,
)

REVISION = "a" * 40
DIGEST = "b" * 64


def _evidence(reviewer: str) -> ReviewedReplayPromotionEvidence:
    return ReviewedReplayPromotionEvidence(
        action_type="ops.restart-app",
        action_type_version="1.0.0",
        action_type_digest=DIGEST,
        fdai_revision=REVISION,
        scenario_set_version="v2026.08",
        candidate_digest=DIGEST,
        package_digest=DIGEST,
        replay_first_digest=DIGEST,
        replay_second_digest=DIGEST,
        promotion_evidence_digest=DIGEST,
        review_ref="governance-review:v2026.08",
        reviewer_principal=reviewer,
        approved=True,
    )


@pytest.mark.parametrize(
    "reviewer",
    ["Norns", "norns", "NORNS", " Mimir ", "mimir"],
)
def test_learning_agent_cannot_review_its_own_promotion(reviewer: str) -> None:
    with pytest.raises(ValueError, match="independent reviewer"):
        _evidence(reviewer)


@pytest.mark.parametrize("reviewer", ["", "   "])
def test_blank_reviewer_is_rejected(reviewer: str) -> None:
    with pytest.raises(ValueError, match="independent reviewer"):
        _evidence(reviewer)


def test_independent_reviewer_authorizes_the_exact_tuple() -> None:
    authority = ReviewedReplayAuthority((_evidence("independent-governance-reviewer"),))

    assert authority.accepts(
        action_type="ops.restart-app",
        action_type_version="1.0.0",
        action_type_digest=DIGEST,
        fdai_revision=REVISION,
        scenario_set_version="v2026.08",
        evidence_digest=DIGEST,
    )
    assert not authority.accepts(
        action_type="ops.restart-app",
        action_type_version="1.0.1",
        action_type_digest=DIGEST,
        fdai_revision=REVISION,
        scenario_set_version="v2026.08",
        evidence_digest=DIGEST,
    )
