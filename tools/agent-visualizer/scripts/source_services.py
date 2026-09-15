"""Describe first-party API adapters without copying credentials, URLs, or runtime bindings."""

from __future__ import annotations

from source_index import SourceIndex

ARG_MODULES = frozenset(
    {
        "fdai.delivery.azure.arg_query",
        "fdai.delivery.azure.arg_transport",
        "fdai.delivery.azure.arg_resource_changes",
        "fdai.delivery.azure.inventory",
        "fdai.delivery.inventory_change_acceleration",
    }
)
OPENAI_MODULES = frozenset(
    {
        "fdai.delivery.azure.llm.adaptive_answer",
        "fdai.delivery.azure.llm.cross_check",
        "fdai.delivery.azure.llm.critic",
        "fdai.delivery.azure.llm.judge",
        "fdai.delivery.azure.llm.proposer",
        "fdai.delivery.azure.llm.embeddings",
        "fdai.delivery.azure.llm.semantic_planning",
        "fdai.delivery.azure.llm.semantic_judgment",
        "fdai_operator_service.adapters.local_narrator",
    }
)
CHANNEL_MODULES = frozenset(
    {
        "fdai_operator_service.streaming.live_stream",
        "fdai_operator_service.adapters.narrator_events",
        "fdai.delivery.notifications.teams",
        "fdai.delivery.notifications.slack",
    }
)


def service_group(module: str) -> str | None:
    """Group direct adapter definitions for presentation, not agent ownership."""
    for identifier, modules in (
        ("azure-resource-graph", ARG_MODULES),
        ("azure-openai", OPENAI_MODULES),
        ("channels", CHANNEL_MODULES),
    ):
        if module in modules:
            return identifier
    return None


def service_metadata(index: SourceIndex) -> list[dict]:
    """Pin every visible API marker to an existing source definition."""
    services = [
        {
            "id": "azure-resource-graph",
            "name": "Azure Resource Graph",
            "ports": [
                {
                    "id": "resource-graph",
                    "label": "AZURE RESOURCE GRAPH",
                    "function_id": (
                        "fdai.delivery.azure.arg_query.AzureArgQueryFactory._fetch_all_pages"
                    ),
                    "mode": "request",
                }
            ],
        },
        {
            "id": "azure-openai",
            "name": "Azure OpenAI",
            "ports": [
                {
                    "id": "openai",
                    "label": "AZURE OPENAI",
                    "function_id": (
                        "fdai_operator_service.adapters.local_narrator."
                        "LocalAzureNarratorAdapters._stream_answer"
                    ),
                    "mode": "stream",
                }
            ],
        },
        {
            "id": "channels",
            "name": "Channels",
            "ports": [
                {
                    "id": "console",
                    "label": "CONSOLE / SSE",
                    "function_id": "fdai_operator_service.streaming.live_stream._live_chunks",
                    "mode": "stream",
                },
                {
                    "id": "teams",
                    "label": "TEAMS",
                    "function_id": "fdai.delivery.notifications.teams.TeamsWebhookChannel.send",
                    "mode": "message",
                },
                {
                    "id": "slack",
                    "label": "SLACK",
                    "function_id": "fdai.delivery.notifications.slack.SlackWebhookChannel.send",
                    "mode": "message",
                },
            ],
        },
    ]
    for service in services:
        for port in service["ports"]:
            if port["function_id"] not in index.functions:
                raise ValueError(f"Service entry definition is missing: {port['function_id']}")
    return services
