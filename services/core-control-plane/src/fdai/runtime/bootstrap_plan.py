"""Pure startup decisions for the headless control-plane process."""

from __future__ import annotations

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
    gateway: bool
    case_history: bool
    vertical_execution: bool

    @property
    def any_requested(self) -> bool:
        """Return whether any optional capability requires an identity."""

        return self.telemetry or self.gateway or self.case_history or self.vertical_execution


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
        gateway=bool(environment.get("FDAI_DEV_OPERATIONS_GATEWAY_URL", "").strip()),
        case_history=bool(environment.get("FDAI_CASE_HISTORY_CONTAINER_URL", "").strip()),
        vertical_execution=any(
            environment.get(env_var, "").strip() for env_var in VERTICAL_IDENTITY_ENV.values()
        ),
    )
    auxiliary_bootstrap = environment.get(_AUXILIARY_KAFKA_BOOTSTRAP_ENV, "").strip()

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
    )


__all__ = [
    "VERTICAL_IDENTITY_ENV",
    "BootstrapPlan",
    "IdentityRequests",
    "build_bootstrap_plan",
]
