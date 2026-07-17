"""Synthetic promotion-gate and model-metering fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fdai.core.measurement.promotion_gate import ShadowVerdictRecord
from fdai.core.metering import InvocationMode, LlmInvocation, TokenUsage


def synthetic_verdicts() -> list[ShadowVerdictRecord]:
    now = datetime.now(tz=UTC)
    verdicts = [
        ShadowVerdictRecord(
            action_type_name="ops.publish-change-summary",
            observed_at=now - timedelta(days=15 + offset % 3),
            was_policy_escape=False,
            operator_reviewed=True,
            operator_agreed=True,
        )
        for offset in range(30)
    ]
    verdicts.append(
        ShadowVerdictRecord(
            action_type_name="remediate.disable-public-access",
            observed_at=now - timedelta(days=1),
            was_policy_escape=True,
            operator_reviewed=True,
            operator_agreed=False,
        )
    )
    return verdicts


def synthetic_llm_invocations() -> tuple[LlmInvocation, ...]:
    now = datetime.now(tz=UTC)
    plan = (
        ("evt-cost-anomaly-01", "t2.reasoner.primary", "gpt-4o", 3200, 480, 0, "0.0128"),
        ("evt-cost-anomaly-01", "t2.reasoner.secondary", "claude-opus-4", 3200, 510, 0, "0.0863"),
        ("evt-drift-02", "t2.reasoner.primary", "gpt-4o", 2800, 300, 1, "0.0100"),
        ("evt-drift-02", "t2.reasoner.secondary", "claude-opus-4", 2800, 260, 1, "0.0615"),
        ("evt-rca-03", "t2.rca", "gpt-4o", 1500, 220, 2, "0.0060"),
    )
    return tuple(
        LlmInvocation(
            occurred_at=now - timedelta(days=days_ago),
            correlation_id=correlation_id,
            capability_id=capability_id,
            model_key=model_key,
            tier="T2",
            mode=InvocationMode.ENFORCE,
            usage=TokenUsage(prompt_tokens=prompt, completion_tokens=completion),
            cost=Decimal(cost),
        )
        for correlation_id, capability_id, model_key, prompt, completion, days_ago, cost in plan
    )


__all__ = ["synthetic_llm_invocations", "synthetic_verdicts"]
