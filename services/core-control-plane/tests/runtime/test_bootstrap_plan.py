from __future__ import annotations

import pytest
from fdai.delivery.agent_activity import DEFAULT_STAGE_TOPIC
from fdai.runtime.bootstrap_plan import VERTICAL_IDENTITY_ENV, build_bootstrap_plan
from fdai.runtime.venue import ExecutionVenue, ExecutionVenueError
from fdai.shared.config.models import LlmMode


def test_bootstrap_plan_preserves_disabled_consumer_defaults() -> None:
    plan = build_bootstrap_plan(
        llm_mode=LlmMode.LOCAL_FAKE,
        environment={"FDAI_EXECUTION_VENUE": "invalid-while-unused"},
    )

    assert plan.start_consumer is False
    assert plan.venue is None
    assert plan.requires_initial_identity is False
    assert plan.consumer_requires_workload_identity is False
    assert plan.requires_channel_http_client is False
    assert plan.auxiliary_kafka_bootstrap_servers is None
    assert plan.pantheon_object_topic == "fdai.pantheon.objects"
    assert plan.stage_topic == DEFAULT_STAGE_TOPIC
    assert plan.isolated_executor_authority_cutover is False


@pytest.mark.parametrize("enabled", ["1", "true", "TRUE"])
def test_bootstrap_plan_enables_consumer_with_existing_truthy_values(enabled: str) -> None:
    plan = build_bootstrap_plan(
        llm_mode=LlmMode.LOCAL_FAKE,
        environment={
            "FDAI_START_CONSUMER": enabled,
            "FDAI_EXECUTION_VENUE": "local",
        },
    )

    assert plan.start_consumer is True
    assert plan.venue is ExecutionVenue.LOCAL
    assert plan.consumer_requires_workload_identity is False


def test_bootstrap_plan_rejects_invalid_venue_only_for_enabled_consumer() -> None:
    with pytest.raises(ExecutionVenueError):
        build_bootstrap_plan(
            llm_mode=LlmMode.LOCAL_FAKE,
            environment={
                "FDAI_START_CONSUMER": "1",
                "FDAI_EXECUTION_VENUE": "invalid",
            },
        )


@pytest.mark.parametrize(
    ("environment", "request_name"),
    [
        ({"FDAI_MONITOR_WORKSPACE_ID": "workspace"}, "telemetry"),
        ({"FDAI_PROMETHEUS_ENDPOINT": "https://example.com"}, "telemetry"),
        ({"FDAI_CONFIGURATION_DRIFT_ENABLED": "1"}, "configuration_drift"),
        ({"FDAI_DEV_OPERATIONS_GATEWAY_URL": "https://example.com"}, "gateway"),
        ({"FDAI_CASE_HISTORY_CONTAINER_URL": "https://example.com"}, "case_history"),
        (
            {next(iter(VERTICAL_IDENTITY_ENV.values())): "client-id"},
            "vertical_execution",
        ),
        (
            {"FDAI_STEWARDSHIP_AUDIT_INTERVAL_SECONDS": "3600"},
            "stewardship_health",
        ),
    ],
)
def test_bootstrap_plan_identifies_optional_identity_requirements(
    environment: dict[str, str],
    request_name: str,
) -> None:
    plan = build_bootstrap_plan(
        llm_mode=LlmMode.LOCAL_FAKE,
        environment=environment,
    )

    assert plan.identity_requests.any_requested is True
    assert getattr(plan.identity_requests, request_name) is True
    assert plan.requires_initial_identity is True


def test_bootstrap_plan_requires_initial_identity_for_azure_llm() -> None:
    plan = build_bootstrap_plan(llm_mode=LlmMode.AZURE, environment={})

    assert plan.requires_initial_identity is True


def test_bootstrap_plan_binds_complete_diagnostic_stream() -> None:
    plan = build_bootstrap_plan(
        llm_mode=LlmMode.LOCAL_FAKE,
        environment={
            "FDAI_START_CONSUMER": "1",
            "FDAI_EXECUTION_VENUE": "deployed",
            "FDAI_DIAGNOSTIC_KAFKA_BOOTSTRAP_SERVERS": "diagnostics.example.com:9093",
            "FDAI_DIAGNOSTIC_TOPIC": "azure.diagnostics",
            "FDAI_DIAGNOSTIC_METRIC_WHITELIST_JSON": '["http_429_rate","node_cpu_percent"]',
        },
    )

    assert plan.requires_initial_identity is True
    assert plan.diagnostic_topic == "azure.diagnostics"
    assert plan.diagnostic_metric_whitelist == ("http_429_rate", "node_cpu_percent")


@pytest.mark.parametrize(
    "environment",
    (
        {"FDAI_DIAGNOSTIC_TOPIC": "azure.diagnostics"},
        {
            "FDAI_START_CONSUMER": "1",
            "FDAI_EXECUTION_VENUE": "deployed",
            "FDAI_DIAGNOSTIC_KAFKA_BOOTSTRAP_SERVERS": "diagnostics.example.com:9093",
            "FDAI_DIAGNOSTIC_TOPIC": "azure.diagnostics",
            "FDAI_DIAGNOSTIC_METRIC_WHITELIST_JSON": '["z","a"]',
        },
    ),
)
def test_bootstrap_plan_rejects_partial_or_unordered_diagnostic_stream(
    environment: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match="diagnostic|DIAGNOSTIC"):
        build_bootstrap_plan(llm_mode=LlmMode.LOCAL_FAKE, environment=environment)


def test_bootstrap_plan_rejects_diagnostic_stream_without_consumer() -> None:
    with pytest.raises(ValueError, match="START_CONSUMER"):
        build_bootstrap_plan(
            llm_mode=LlmMode.LOCAL_FAKE,
            environment={
                "FDAI_DIAGNOSTIC_KAFKA_BOOTSTRAP_SERVERS": "diagnostics.example.com:9093",
                "FDAI_DIAGNOSTIC_TOPIC": "azure.diagnostics",
                "FDAI_DIAGNOSTIC_METRIC_WHITELIST_JSON": '["node_cpu_percent"]',
            },
        )


@pytest.mark.parametrize(
    "environment_key",
    ["FDAI_GITOPS_TOKEN", "FDAI_CHATOPS_WEBHOOK_URL", "FDAI_EMAIL_ENDPOINT"],
)
def test_bootstrap_plan_identifies_each_http_channel(environment_key: str) -> None:
    plan = build_bootstrap_plan(
        llm_mode=LlmMode.LOCAL_FAKE,
        environment={environment_key: "configured"},
    )

    assert plan.requires_channel_http_client is True


def test_bootstrap_plan_enables_github_for_complete_app_credentials() -> None:
    plan = build_bootstrap_plan(
        llm_mode=LlmMode.LOCAL_FAKE,
        environment={
            "FDAI_GITHUB_APP_CLIENT_ID": "Iv1.example",
            "FDAI_GITHUB_APP_INSTALLATION_ID": "123",
            "FDAI_GITHUB_APP_PRIVATE_KEY": "configured",
        },
    )

    assert plan.github_change_feed_enabled is True
    assert plan.requires_channel_http_client is True


def test_bootstrap_plan_resolves_consumer_bindings_once() -> None:
    plan = build_bootstrap_plan(
        llm_mode=LlmMode.LOCAL_FAKE,
        environment={
            "FDAI_START_CONSUMER": "true",
            "FDAI_EXECUTION_VENUE": "deployed",
            "FDAI_GITOPS_TOKEN": "configured",
            "FDAI_CHATOPS_WEBHOOK_URL": "configured",
            "FDAI_EMAIL_ENDPOINT": "configured",
            "FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS": " auxiliary:9093 ",
            "FDAI_PANTHEON_OBJECT_TOPIC": " custom.objects ",
            "FDAI_STAGE_TOPIC": " custom.stage.topic ",
            "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER": "1",
        },
    )

    assert plan.venue is ExecutionVenue.DEPLOYED
    assert plan.consumer_requires_workload_identity is True
    assert plan.requires_channel_http_client is True
    assert plan.auxiliary_kafka_bootstrap_servers == "auxiliary:9093"
    assert plan.pantheon_object_topic == "custom.objects"
    assert plan.stage_topic == "custom.stage.topic"
    assert plan.isolated_executor_authority_cutover is True
