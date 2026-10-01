from __future__ import annotations

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime_payload_validation import default_payload_validator


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon(), payload_validator=default_payload_validator)


async def test_validator_accepts_representative_saga_issue_payload() -> None:
    bus = _bus()

    await bus.publish(
        "Saga",
        "object.issue",
        {
            "correlation_id": "issue-corr",
            "idempotency_key": "issue-key",
            "fingerprint": "fp-1",
            "issue_number": 7,
            "created": True,
        },
    )

    assert bus.schema_violations == 0
    assert len(bus.messages_on("object.issue")) == 1


async def test_validator_accepts_representative_saga_audit_payload() -> None:
    bus = _bus()

    await bus.publish(
        "Saga",
        "object.audit-entry",
        {
            "correlation_id": "audit-corr",
            "idempotency_key": "audit-key",
            "audited_topic": "object.action-run",
            "action_kind": "action_run.terminal",
        },
    )

    assert bus.schema_violations == 0
    assert len(bus.messages_on("object.audit-entry")) == 1


async def test_validator_accepts_representative_mimir_rule_payload() -> None:
    bus = _bus()

    await bus.publish(
        "Mimir",
        "object.rule",
        {
            "kind": "rule_promotion",
            "correlation_id": "rule-corr",
            "idempotency_key": "rule-key",
            "rule_id": "rule.test",
            "state": "shadow",
            "source": "manual",
            "updated_at": "2026-10-01T00:00:00+00:00",
            "grants_execution_authority": False,
        },
    )

    assert bus.schema_violations == 0
    assert len(bus.messages_on("object.rule")) == 1


async def test_validator_accepts_mimir_handover_knowledge_rule_payload() -> None:
    bus = _bus()

    await bus.publish(
        "Mimir",
        "object.rule",
        {
            "kind": "handover_knowledge",
            "correlation_id": "handover-corr",
            "idempotency_key": "handover-key",
            "resource_id": "handover-source:one",
            "knowledge": {"disposition": "admitted"},
            "execution_authority": False,
            "may_promote": False,
        },
    )

    assert bus.schema_violations == 0
    assert len(bus.messages_on("object.rule")) == 1


async def test_validator_accepts_mimir_catalog_review_rule_payload() -> None:
    bus = _bus()

    await bus.publish(
        "Mimir",
        "object.rule",
        {
            "kind": "catalog_review_outcome",
            "correlation_id": "catalog-corr",
            "idempotency_key": "catalog-key",
            "candidate_digest": "a" * 64,
            "package_digest": "b" * 64,
            "outcome": "published",
            "mode": "shadow",
        },
    )

    assert bus.schema_violations == 0
    assert len(bus.messages_on("object.rule")) == 1


async def test_validator_accepts_representative_mimir_policy_payload() -> None:
    bus = _bus()

    await bus.publish(
        "Mimir",
        "object.policy",
        {
            "kind": "policy_promotion",
            "correlation_id": "policy-corr",
            "idempotency_key": "policy-key",
            "rule_id": "policy.test",
            "policy_id": "policy.test",
            "state": "shadow",
            "source": "manual",
            "updated_at": "2026-10-01T00:00:00+00:00",
            "grants_execution_authority": False,
        },
    )

    assert bus.schema_violations == 0
    assert len(bus.messages_on("object.policy")) == 1


@pytest.mark.parametrize(
    ("topic", "principal", "payload", "match"),
    [
        (
            "object.issue",
            "Saga",
            {"correlation_id": "c", "idempotency_key": "i", "fingerprint": "fp"},
            "issue_number",
        ),
        (
            "object.audit-entry",
            "Saga",
            {"correlation_id": "c", "idempotency_key": "i"},
            "audited_topic, action_kind, or kind",
        ),
        (
            "object.rule",
            "Mimir",
            {
                "kind": "unknown",
                "correlation_id": "c",
                "idempotency_key": "i",
                "rule_id": "r",
                "state": "shadow",
            },
            "kind",
        ),
        (
            "object.policy",
            "Mimir",
            {
                "kind": "unknown",
                "correlation_id": "c",
                "idempotency_key": "i",
                "policy_id": "p",
            },
            "kind",
        ),
    ],
)
async def test_validator_rejects_malformed_authority_topics(
    topic: str,
    principal: str,
    payload: dict[str, object],
    match: str,
) -> None:
    bus = _bus()

    with pytest.raises(ValueError, match=match):
        await bus.publish(principal, topic, payload)

    assert bus.schema_violations == 1
    assert bus.messages_on(topic) == []
