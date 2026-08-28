"""Pure startup decisions for the headless control-plane process."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from fdai.delivery.agent_activity import DEFAULT_STAGE_TOPIC
from fdai.runtime.venue import ExecutionVenue, resolve_execution_venue, uses_workload_identity
from fdai.shared.config.models import LlmMode

_AUXILIARY_KAFKA_BOOTSTRAP_ENV = "FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS"
VERTICAL_IDENTITY_ENV = {
    "identity/change": "FDAI_CHANGE_MI_CLIENT_ID",
    "identity/resilience": "FDAI_RESILIENCE_MI_CLIENT_ID",
    "identity/finops": "FDAI_FINOPS_MI_CLIENT_ID",
}


@dataclass(frozen=True, slots=True)
class IdentityRequests:
    """Optional runtime capabilities that require a workload identity."""

    telemetry: bool
    configuration_drift: bool
    diagnostic: bool
    gateway: bool
    case_history: bool
    vertical_execution: bool

    @property
    def any_requested(self) -> bool:
        """Return whether any optional capability requires an identity."""

        return (
            self.telemetry
            or self.configuration_drift
            or self.diagnostic
            or self.gateway
            or self.case_history
            or self.vertical_execution
        )


@dataclass(frozen=True, slots=True)
class BootstrapPlan:
    """Validated, side-effect-free decisions consumed by runtime assembly."""

    start_consumer: bool
    venue: ExecutionVenue | None
    identity_requests: IdentityRequests
    requires_initial_identity: bool
    consumer_requires_workload_identity: bool
    github_change_feed_enabled: bool
    chatops_enabled: bool
    email_enabled: bool
    auxiliary_kafka_bootstrap_servers: str | None
    pantheon_object_topic: str
    stage_topic: str
    isolated_executor_authority_cutover: bool
    diagnostic_kafka_bootstrap_servers: str | None
    diagnostic_topic: str | None
    diagnostic_metric_whitelist: tuple[str, ...]

    @property
    def requires_channel_http_client(self) -> bool:
        """Return whether an enabled delivery channel requires the HTTP client."""

        return self.github_change_feed_enabled or self.chatops_enabled or self.email_enabled


def build_bootstrap_plan(
    *,
    llm_mode: str,
    environment: Mapping[str, str],
) -> BootstrapPlan:
    """Resolve startup decisions without acquiring resources or changing process state."""

    start_consumer = environment.get("FDAI_START_CONSUMER", "").lower() in {"1", "true"}
    venue = resolve_execution_venue(environment) if start_consumer else None
    identity_requests = IdentityRequests(
        telemetry=bool(
            environment.get("FDAI_MONITOR_WORKSPACE_ID", "").strip()
            or environment.get("FDAI_PROMETHEUS_ENDPOINT", "").strip()
        ),
        configuration_drift=environment.get("FDAI_CONFIGURATION_DRIFT_ENABLED", "").strip().lower()
        in {"1", "true"},
        diagnostic=False,
        gateway=bool(environment.get("FDAI_DEV_OPERATIONS_GATEWAY_URL", "").strip()),
        case_history=bool(environment.get("FDAI_CASE_HISTORY_CONTAINER_URL", "").strip()),
        vertical_execution=any(
            environment.get(env_var, "").strip() for env_var in VERTICAL_IDENTITY_ENV.values()
        ),
    )
    auxiliary_bootstrap = environment.get(_AUXILIARY_KAFKA_BOOTSTRAP_ENV, "").strip()
    diagnostic_bootstrap = environment.get("FDAI_DIAGNOSTIC_KAFKA_BOOTSTRAP_SERVERS", "").strip()
    diagnostic_topic = environment.get("FDAI_DIAGNOSTIC_TOPIC", "").strip()
    diagnostic_whitelist = _diagnostic_metric_whitelist(environment)
    diagnostic_values = (
        bool(diagnostic_bootstrap),
        bool(diagnostic_topic),
        bool(diagnostic_whitelist),
    )
    if any(diagnostic_values) and not all(diagnostic_values):
        raise ValueError(
            "diagnostic Kafka bootstrap, topic, and metric whitelist MUST be configured together"
        )
    if diagnostic_bootstrap:
        if not start_consumer:
            raise ValueError("diagnostic Kafka ingestion requires FDAI_START_CONSUMER")
        identity_requests = IdentityRequests(
            telemetry=identity_requests.telemetry,
            configuration_drift=identity_requests.configuration_drift,
            diagnostic=True,
            gateway=identity_requests.gateway,
            case_history=identity_requests.case_history,
            vertical_execution=identity_requests.vertical_execution,
        )

    return BootstrapPlan(
        start_consumer=start_consumer,
        venue=venue,
        identity_requests=identity_requests,
        requires_initial_identity=(llm_mode == LlmMode.AZURE or identity_requests.any_requested),
        consumer_requires_workload_identity=(venue is not None and uses_workload_identity(venue)),
        github_change_feed_enabled=bool(environment.get("FDAI_GITOPS_TOKEN")),
        chatops_enabled=bool(environment.get("FDAI_CHATOPS_WEBHOOK_URL")),
        email_enabled=bool(environment.get("FDAI_EMAIL_ENDPOINT")),
        auxiliary_kafka_bootstrap_servers=auxiliary_bootstrap or None,
        pantheon_object_topic=environment.get(
            "FDAI_PANTHEON_OBJECT_TOPIC", "fdai.pantheon.objects"
        ).strip(),
        stage_topic=environment.get("FDAI_STAGE_TOPIC", "").strip() or DEFAULT_STAGE_TOPIC,
        isolated_executor_authority_cutover=(
            environment.get("FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER", "").strip() == "1"
        ),
        diagnostic_kafka_bootstrap_servers=diagnostic_bootstrap or None,
        diagnostic_topic=diagnostic_topic or None,
        diagnostic_metric_whitelist=diagnostic_whitelist,
    )


def _diagnostic_metric_whitelist(environment: Mapping[str, str]) -> tuple[str, ...]:
    raw = environment.get("FDAI_DIAGNOSTIC_METRIC_WHITELIST_JSON", "").strip()
    if not raw:
        return ()
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("FDAI_DIAGNOSTIC_METRIC_WHITELIST_JSON MUST be a JSON array") from exc
    if (
        not isinstance(values, list)
        or not 1 <= len(values) <= 256
        or any(not isinstance(value, str) or not value.strip() for value in values)
    ):
        raise ValueError("FDAI_DIAGNOSTIC_METRIC_WHITELIST_JSON MUST contain 1-256 strings")
    normalized = tuple(value.strip() for value in values)
    if normalized != tuple(sorted(normalized)) or len(normalized) != len(set(normalized)):
        raise ValueError(
            "FDAI_DIAGNOSTIC_METRIC_WHITELIST_JSON MUST contain unique ordered strings"
        )
    return normalized


__all__ = [
    "VERTICAL_IDENTITY_ENV",
    "BootstrapPlan",
    "IdentityRequests",
    "build_bootstrap_plan",
]
