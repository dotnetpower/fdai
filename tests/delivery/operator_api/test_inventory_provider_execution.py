from fdai.delivery.operator_api.routes.inventory_provider_execution import (
    project_inventory_provider_execution,
)


def test_projects_subscription_scope_and_bounded_command_result() -> None:
    projected = project_inventory_provider_execution(
        {
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
        }
    )

    assert projected is not None
    assert projected["subscription_id"] == "subscription-example"
    assert projected["commands"][0]["duration_ms"] == 321
    assert projected["commands"][0]["result"]["preview"] == [
        {"name": "resource-example", "type": "example/type"}
    ]


def test_rejects_unbounded_or_unknown_result_fields() -> None:
    receipt = {
        "transport": "azure_cli",
        "backend": "azure_resource_graph",
        "executed": True,
        "redacted": True,
        "page_count": 1,
        "commands": [
            {
                "label": "resources",
                "language": "azure_cli",
                "command": "az graph query",
                "result": {
                    "count": 1,
                    "preview": [{"secret": "not allowed"}],
                    "truncated": False,
                },
            }
        ],
    }

    assert project_inventory_provider_execution(receipt) is None

    receipt["commands"][0]["result"] = {
        "count": True,
        "preview": [],
        "truncated": True,
    }
    assert project_inventory_provider_execution(receipt) is None
