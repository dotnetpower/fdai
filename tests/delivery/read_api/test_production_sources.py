from __future__ import annotations

import pytest

from fdai.delivery.read_api.production.data_sources import build_production_data_sources
from fdai.delivery.read_api.production.scope import build_production_scope_source


def test_production_scope_uses_runtime_subscription_and_resource_group() -> None:
    source = build_production_scope_source(
        {
            "AZURE_SUBSCRIPTION_ID": "subscription-a",
            "AZURE_RESOURCE_GROUP": "resource-group-a",
        }
    )
    assert source is not None

    view = source.view.to_dict()
    assert view["monitoring"]["entries"][0]["address"] == "scope://azure/subscription-a"
    assert view["action"]["entries"][0]["address"] == (
        "scope://azure/subscription-a/resource-group-a"
    )
    assert view["executor_boundary"]["resource_groups"] == ["resource-group-a"]


def test_production_scope_rejects_partial_configuration() -> None:
    with pytest.raises(ValueError, match="MUST be configured together"):
        build_production_scope_source({"AZURE_SUBSCRIPTION_ID": "subscription-a"})


def test_production_manifest_distinguishes_configured_and_unavailable_sources() -> None:
    sources = {
        item.key: item
        for item in build_production_data_sources(
            scope_configured=False,
            onboarding_configured=False,
            model_settings_configured=True,
            streams_configured=False,
        )
    }
    assert sources["operational-state"].authoritative is True
    assert sources["overview-measurement"].durable is True
    assert "/conversation-delivery" in sources["durable-governance"].routes
    assert sources["scope"].availability == "unavailable"
    assert sources["models"].availability == "unknown"
    assert sources["streams"].configured is False
    assert sources["stewardship-config"].availability == "available"
    assert sources["provisioning-stream"].availability == "unavailable"
    assert sources["python-tasks"].availability == "unknown"
    assert sources["runtime-skills"].availability == "unknown"
