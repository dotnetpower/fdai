import json

from fdai.delivery.operator_api.application.conversation.evidence.enrichment import (
    _inventory_provider_progress_events,
)


def test_provider_progress_exposes_subscription_command_and_bounded_result() -> None:
    events = _inventory_provider_progress_events(
        {
            "tool": "query_inventory",
            "result": {
                "snapshot_at": "2026-08-03T11:11:27Z",
                "provider_execution": {
                    "transport": "azure_cli",
                    "backend": "azure_resource_graph",
                    "executed": True,
                    "redacted": True,
                    "subscription_id": "subscription-example",
                    "page_count": 1,
                    "commands": [
                        {
                            "label": "resources",
                            "language": "azure_cli",
                            "command": "az graph query --subscriptions subscription-example",
                            "duration_ms": 321,
                            "result": {
                                "count": 1,
                                "preview": [{"name": "resource-example", "type": "example/type"}],
                                "truncated": False,
                            },
                        }
                    ],
                },
            },
        }
    )

    assert len(events) == 1
    event = events[0]
    assert "subscription-example" in str(event["detail"])
    execution = event["execution"]
    assert isinstance(execution, dict)
    assert "subscription-example" in execution["command"]
    assert execution["duration_ms"] == 321
    assert json.loads(execution["output"]) == {
        "count": 1,
        "preview": [{"name": "resource-example", "type": "example/type"}],
        "truncated": False,
    }
