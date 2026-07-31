from __future__ import annotations

import hashlib

from fdai.core.conversation_assurance import (
    AppliedChatPolicy,
    ChatPolicyTarget,
    PolicyStage,
    policy_is_assigned,
)


def _policy(stage: PolicyStage) -> AppliedChatPolicy:
    text = "Improve answer calibration without changing evidence or authority."
    return AppliedChatPolicy(
        candidate_id="candidate-1",
        principal_scope="principal-1",
        target=ChatPolicyTarget.NARRATOR_PROMPT,
        policy_digest=hashlib.sha256(text.encode()).hexdigest(),
        policy_text=text,
        stage=stage,
    )


def test_shadow_and_rollback_never_assign_live_traffic() -> None:
    assert not policy_is_assigned(_policy(PolicyStage.SHADOW), assignment_key="turn-1")
    assert not policy_is_assigned(_policy(PolicyStage.ROLLED_BACK), assignment_key="turn-1")


def test_active_always_assigns_live_traffic() -> None:
    assert policy_is_assigned(_policy(PolicyStage.ACTIVE), assignment_key="turn-1")


def test_canary_assignment_is_stable_and_bounded() -> None:
    policy = _policy(PolicyStage.CANARY_25)
    first = [policy_is_assigned(policy, assignment_key=f"turn-{index}") for index in range(400)]
    second = [policy_is_assigned(policy, assignment_key=f"turn-{index}") for index in range(400)]

    assert first == second
    assert 70 <= sum(first) <= 130
