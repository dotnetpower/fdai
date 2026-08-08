"""Topic naming and partition-key strategy."""

from __future__ import annotations

from fdai.agents._framework.topics import (
    OWNED_OBJECT_TOPICS,
    partition_key_for,
    topic_for_object_type,
)


def test_topic_for_object_type_kebab_cases() -> None:
    assert topic_for_object_type("Event") == "object.event"
    assert topic_for_object_type("ActionRun") == "object.action-run"
    assert topic_for_object_type("SecurityEvent") == "object.security-event"
    assert topic_for_object_type("HandoffEscalation") == "object.handoff-escalation"


def test_owned_object_topics_include_pantheon_publications() -> None:
    # Every topic derived from an AgentSpec.owns must be registered as an
    # owned object topic so the bus can reject writes to unknown topics.
    from fdai.agents import PANTHEON_SPECS

    for spec in PANTHEON_SPECS:
        for topic in spec.publishes:
            assert topic in OWNED_OBJECT_TOPICS, (
                f"topic {topic!r} (owner={spec.name!r}) missing from OWNED_OBJECT_TOPICS"
            )


def test_partition_key_mutation_prefers_resource_id() -> None:
    key = partition_key_for(
        "object.action-run",
        {"resource_id": "rg-1/vm-1", "correlation_id": "corr-1"},
    )
    assert key == "rg-1/vm-1"


def test_partition_key_mutation_falls_back_to_correlation() -> None:
    # data-quality edge case: mutation topic missing resource_id
    key = partition_key_for(
        "object.action-run",
        {"correlation_id": "corr-only"},
    )
    assert key == "corr-only"


def test_partition_key_correlation_topic_uses_correlation_id() -> None:
    key = partition_key_for(
        "object.verdict",
        {"resource_id": "should-be-ignored", "correlation_id": "corr-42"},
    )
    assert key == "corr-42"


def test_partition_key_unknown_topic_defaults_to_correlation() -> None:
    key = partition_key_for(
        "object.unknown-topic",
        {"correlation_id": "fallback"},
    )
    assert key == "fallback"
