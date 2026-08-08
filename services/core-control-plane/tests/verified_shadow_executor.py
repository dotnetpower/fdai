"""Test executor that returns an independently verified shadow terminal result."""

from __future__ import annotations

from dataclasses import replace

from fdai.core.executor import ExecutionResult, ExecutorOutcome, ShadowExecutor
from fdai.shared.contracts.models import Action, Rule

_VERIFIED_OUTCOMES = frozenset(
    {
        ExecutorOutcome.PUBLISHED,
        ExecutorOutcome.ALREADY_EXISTED,
    }
)


class VerifiedShadowExecutor(ShadowExecutor):
    """Attach deterministic verified-effect evidence for non-verifier integration tests."""

    async def execute(self, *, action: Action, rule: Rule) -> ExecutionResult:
        result = await super().execute(action=action, rule=rule)
        if result.outcome not in _VERIFIED_OUTCOMES:
            return result
        return replace(
            result,
            audit_context={
                **result.audit_context,
                "effect_verified": True,
                "effect_verification_status": "verified",
                "effect_verification_reason": "test_fixture_observation",
            },
        )


__all__ = ["VerifiedShadowExecutor"]
