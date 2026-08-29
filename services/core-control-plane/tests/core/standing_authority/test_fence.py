"""Shadow-only standing-authorization dispatch-fence contract tests."""

from __future__ import annotations

from fdai.core.standing_authority.fence import (
    LifecycleFenceReason,
    StandingAuthorizationFenceGuard,
)
from fdai.core.standing_authority.lifecycle import LifecycleFence
from fdai.shared.providers.standing_authority import StandingAuthorizationStoreError

FENCE = LifecycleFence(
    family_id="family:one",
    revision_id="sha256:" + "a" * 64,
    fencing_generation=3,
    transition_digest="sha256:" + "b" * 64,
)


async def test_fence_guard_accepts_only_an_exact_primary_match() -> None:
    class _Store:
        async def check_fence(self, fence):
            return fence == FENCE

    current = await StandingAuthorizationFenceGuard(store=_Store()).evaluate(FENCE)
    stale = await StandingAuthorizationFenceGuard(store=_Store()).evaluate(
        LifecycleFence(
            family_id=FENCE.family_id,
            revision_id=FENCE.revision_id,
            fencing_generation=4,
            transition_digest=FENCE.transition_digest,
        )
    )

    assert current.current
    assert current.reason is LifecycleFenceReason.CURRENT
    assert current.execution_authority is False
    assert stale.reason is LifecycleFenceReason.STALE


async def test_fence_guard_fails_closed_when_primary_is_unavailable() -> None:
    class _Store:
        async def check_fence(self, fence):
            del fence
            raise StandingAuthorizationStoreError("primary unavailable")

    result = await StandingAuthorizationFenceGuard(store=_Store()).evaluate(FENCE)

    assert not result.current
    assert result.reason is LifecycleFenceReason.STORE_UNAVAILABLE
