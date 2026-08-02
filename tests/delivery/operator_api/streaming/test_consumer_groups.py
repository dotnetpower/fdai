"""Tests for per-instance Operator API stream consumer groups."""

from __future__ import annotations

import pytest

from fdai.delivery.operator_api.streaming.consumer_groups import instance_consumer_group


def test_uses_explicit_local_instance() -> None:
    assert (
        instance_consumer_group(
            "fdai-agent-activity",
            {
                "FDAI_OPERATOR_API_CONSUMER_INSTANCE": "local-developer-a",
                "HOSTNAME": "deployment-replica",
            },
        )
        == "fdai-agent-activity.local-developer-a"
    )


def test_uses_deployment_hostname_when_local_instance_is_absent() -> None:
    assert (
        instance_consumer_group(
            "fdai-live-stage",
            {"HOSTNAME": "operator-api-replica-abc"},
        )
        == "fdai-live-stage.operator-api-replica-abc"
    )


def test_keeps_base_group_for_non_runtime_test_harness() -> None:
    assert instance_consumer_group("fdai-agent-activity", {}) == "fdai-agent-activity"


@pytest.mark.parametrize("instance", ["bad value", ".leading", "x" * 129])
def test_rejects_invalid_instance(instance: str) -> None:
    with pytest.raises(ValueError, match="consumer instance"):
        instance_consumer_group(
            "fdai-agent-activity",
            {"FDAI_OPERATOR_API_CONSUMER_INSTANCE": instance},
        )
