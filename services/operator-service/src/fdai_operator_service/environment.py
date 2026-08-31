"""Validated environment contract for the independent Operator process."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from fdai_service_contracts import (
    BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP,
    BACKGROUND_TASK_PROJECTION_TOPIC,
    OperatorRole,
)

HOST_ENV = "FDAI_OPERATOR_SERVICE_HOST"
PORT_ENV = "FDAI_OPERATOR_SERVICE_PORT"
TENANT_ENV = "FDAI_ENTRA_TENANT_ID"
AUDIENCE_ENV = "FDAI_API_AUDIENCE"
ISSUER_ENV = "FDAI_ENTRA_ISSUER"
JWKS_URI_ENV = "FDAI_ENTRA_JWKS_URI"
CORS_ORIGINS_ENV = "FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS"
DATABASE_URL_ENV = "FDAI_DATABASE_URL"
DATABASE_ROLE_ENV = "FDAI_DATABASE_ROLE"
DATABASE_STATEMENT_TIMEOUT_ENV = "FDAI_OPERATOR_DATABASE_STATEMENT_TIMEOUT_MS"
DATABASE_CONNECT_TIMEOUT_ENV = "FDAI_OPERATOR_DATABASE_CONNECT_TIMEOUT_S"
EXPECTED_DATABASE_ROLE = "fdai_operator"
LOCAL_AZURE_NARRATOR_ENV = "FDAI_OPERATOR_SERVICE_LOCAL_AZURE_NARRATOR"
LOCAL_AZURE_CLI_AUTH_ENV = "FDAI_OPERATOR_API_LOCAL_AZURE_CLI"
LOCAL_ENTRA_AUTH_ENV = "FDAI_OPERATOR_API_LOCAL_ENTRA"
DEV_MODE_ENV = "FDAI_OPERATOR_API_DEV_MODE"
NARRATOR_PROBE_INTERVAL_ENV = "FDAI_NARRATOR_PROBE_INTERVAL_SECONDS"
KAFKA_BOOTSTRAP_SERVERS_ENV = "FDAI_KAFKA_BOOTSTRAP_SERVERS"
HIL_DECISION_TOPIC_ENV = "FDAI_HIL_DECISION_TOPIC"
STAGE_TOPIC_ENV = "FDAI_STAGE_TOPIC"
LIVE_STAGE_CONSUMER_GROUP_ENV = "FDAI_LIVE_STAGE_CONSUMER_GROUP_ID"
SEMANTIC_REQUEST_TOPIC_ENV = "FDAI_SEMANTIC_TURN_REQUEST_TOPIC"
SEMANTIC_PROJECTION_TOPIC_ENV = "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC"
SEMANTIC_PHYSICAL_TOPIC_ENV = "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC"
SEMANTIC_OUTBOX_NAMESPACE_ENV = "FDAI_SEMANTIC_TURN_OUTBOX_NAMESPACE"
SEMANTIC_CONSUMER_GROUP_ENV = "FDAI_SEMANTIC_TURN_CONSUMER_GROUP_ID"
SEMANTIC_KAFKA_CLIENT_ID_ENV = "FDAI_SEMANTIC_TURN_KAFKA_CLIENT_ID"
READ_INVESTIGATION_REQUEST_TOPIC_ENV = "FDAI_READ_INVESTIGATION_REQUEST_TOPIC"
READ_INVESTIGATION_COMPLETION_TOPIC_ENV = "FDAI_READ_INVESTIGATION_COMPLETION_TOPIC"
READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP_ENV = (
    "FDAI_READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP_ID"
)
BACKGROUND_TASK_PROJECTION_TOPIC_ENV = "FDAI_BACKGROUND_TASK_PROJECTION_TOPIC"
BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP_ENV = "FDAI_BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP_ID"
MANAGED_IDENTITY_CLIENT_ID_ENV = "FDAI_COMMAND_MI_CLIENT_ID"
DEFAULT_HOST = "0.0.0.0"  # noqa: S104 - Container ingress terminates external HTTPS.
DEFAULT_PORT = 8000
DEFAULT_DATABASE_STATEMENT_TIMEOUT_MS = 20_000
DEFAULT_DATABASE_CONNECT_TIMEOUT_S = 10
DEFAULT_SEMANTIC_CONSUMER_GROUP = "operator-semantic-turn-v1"
DEFAULT_SEMANTIC_KAFKA_CLIENT_ID = "fdai-operator-service"
DEFAULT_STAGE_TOPIC = "fdai.pipeline.stages"
DEFAULT_HIL_DECISION_TOPIC = "fdai.hil.decisions"
DEFAULT_LIVE_STAGE_CONSUMER_GROUP = "fdai-operator-live-stage-v1"
DEFAULT_READ_INVESTIGATION_COMPLETION_TOPIC = "core.read-investigation.completions"
DEFAULT_READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP = "operator-read-investigation-completion-v1"
DEFAULT_BACKGROUND_TASK_PROJECTION_TOPIC = BACKGROUND_TASK_PROJECTION_TOPIC
DEFAULT_BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP = BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP
DEFAULT_NARRATOR_PROBE_INTERVAL_SECONDS = 300
MIN_NARRATOR_PROBE_INTERVAL_SECONDS = 30
MAX_NARRATOR_PROBE_INTERVAL_SECONDS = 3_600
_SEMANTIC_OUTBOX_NAMESPACE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

GROUP_ENV: Mapping[OperatorRole, str] = MappingProxyType(
    {
        OperatorRole.READER: "FDAI_RBAC_READERS_GROUP_ID",
        OperatorRole.CONTRIBUTOR: "FDAI_RBAC_CONTRIBUTORS_GROUP_ID",
        OperatorRole.APPROVER: "FDAI_RBAC_APPROVERS_GROUP_ID",
        OperatorRole.OWNER: "FDAI_RBAC_OWNERS_GROUP_ID",
        OperatorRole.BREAK_GLASS: "FDAI_RBAC_BREAK_GLASS_GROUP_ID",
    }
)


class OperatorServiceConfigurationError(ValueError):
    """Raised before provider loading when service configuration is invalid."""


@dataclass(frozen=True, slots=True)
class OperatorEnvironment:
    """Hold immutable production HTTP and human-identity configuration."""

    values: Mapping[str, str]
    host: str
    port: int
    tenant_id: str
    audience: str
    issuer: str
    jwks_uri: str
    group_ids: Mapping[OperatorRole, str]
    cors_allow_origins: tuple[str, ...]
    database_url: str | None
    database_role: str | None
    database_statement_timeout_ms: int
    database_connect_timeout_s: int
    local_azure_narrator: bool
    local_azure_cli_auth: bool
    narrator_probe_interval_seconds: int
    kafka_bootstrap_servers: str | None
    hil_decision_topic: str | None
    stage_topic: str
    live_stage_consumer_group_id: str
    semantic_request_topic: str | None
    semantic_projection_topic: str | None
    semantic_physical_topic: str | None
    semantic_outbox_namespace: str | None
    semantic_consumer_group_id: str
    semantic_kafka_client_id: str
    read_investigation_request_topic: str | None
    read_investigation_completion_topic: str | None
    read_investigation_completion_consumer_group_id: str | None
    background_task_projection_topic: str | None
    background_task_projection_consumer_group_id: str | None
    managed_identity_client_id: str | None

    @classmethod
    def parse(cls, environ: Mapping[str, str]) -> OperatorEnvironment:
        """Validate listener, Entra, RBAC, and CORS settings before provider use."""
        values = dict(environ)
        host = values.get(HOST_ENV, DEFAULT_HOST).strip()
        if not host:
            raise OperatorServiceConfigurationError(f"{HOST_ENV} MUST be non-empty")

        raw_port = values.get(PORT_ENV, str(DEFAULT_PORT)).strip()
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise OperatorServiceConfigurationError(f"{PORT_ENV} MUST be an integer") from exc
        if not 1 <= port <= 65535:
            raise OperatorServiceConfigurationError(f"{PORT_ENV} MUST be between 1 and 65535")

        tenant_id = _require(values, TENANT_ENV)
        audience = _require(values, AUDIENCE_ENV)
        issuer = values.get(ISSUER_ENV, "").strip() or (
            f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        )
        jwks_uri = values.get(JWKS_URI_ENV, "").strip() or (
            f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        )
        group_ids = {role: _require(values, key) for role, key in GROUP_ENV.items()}
        if len(set(group_ids.values())) != len(group_ids):
            raise OperatorServiceConfigurationError("Operator RBAC group IDs MUST be unique")

        cors_allow_origins = tuple(
            origin.strip()
            for origin in values.get(CORS_ORIGINS_ENV, "").split(",")
            if origin.strip()
        )
        if "*" in cors_allow_origins:
            raise OperatorServiceConfigurationError(
                f"{CORS_ORIGINS_ENV} MUST NOT contain a wildcard origin"
            )

        database_url = values.get(DATABASE_URL_ENV, "").strip() or None
        database_role = values.get(DATABASE_ROLE_ENV, "").strip() or None
        if database_url is None and database_role is not None:
            raise OperatorServiceConfigurationError(
                f"{DATABASE_ROLE_ENV} MUST be unset when {DATABASE_URL_ENV} is unset"
            )
        if database_url is not None and database_role != EXPECTED_DATABASE_ROLE:
            raise OperatorServiceConfigurationError(
                f"{DATABASE_ROLE_ENV} MUST be {EXPECTED_DATABASE_ROLE}"
            )
        database_statement_timeout_ms = _positive_int(
            values,
            DATABASE_STATEMENT_TIMEOUT_ENV,
            DEFAULT_DATABASE_STATEMENT_TIMEOUT_MS,
        )
        database_connect_timeout_s = _positive_int(
            values,
            DATABASE_CONNECT_TIMEOUT_ENV,
            DEFAULT_DATABASE_CONNECT_TIMEOUT_S,
        )
        local_azure_narrator = _boolean(values, LOCAL_AZURE_NARRATOR_ENV, default=False)
        local_azure_cli_auth = _boolean(values, LOCAL_AZURE_CLI_AUTH_ENV, default=False)
        local_entra_auth = _boolean(values, LOCAL_ENTRA_AUTH_ENV, default=False)
        dev_mode = _boolean(values, DEV_MODE_ENV, default=False)
        if local_azure_cli_auth:
            if values.get("RUNTIME_ENV", "").strip().lower() != "dev":
                raise OperatorServiceConfigurationError(
                    f"{LOCAL_AZURE_CLI_AUTH_ENV} requires RUNTIME_ENV=dev"
                )
            if dev_mode or local_entra_auth:
                raise OperatorServiceConfigurationError(
                    f"{LOCAL_AZURE_CLI_AUTH_ENV} MUST NOT be combined with "
                    f"{DEV_MODE_ENV} or {LOCAL_ENTRA_AUTH_ENV}"
                )
        narrator_probe_interval_seconds = _bounded_int(
            values,
            NARRATOR_PROBE_INTERVAL_ENV,
            DEFAULT_NARRATOR_PROBE_INTERVAL_SECONDS,
            minimum=MIN_NARRATOR_PROBE_INTERVAL_SECONDS,
            maximum=MAX_NARRATOR_PROBE_INTERVAL_SECONDS,
        )
        if local_azure_narrator and values.get("RUNTIME_ENV", "").strip().lower() != "dev":
            raise OperatorServiceConfigurationError(
                f"{LOCAL_AZURE_NARRATOR_ENV} requires RUNTIME_ENV=dev"
            )
        kafka_bootstrap_servers = values.get(KAFKA_BOOTSTRAP_SERVERS_ENV, "").strip() or None
        explicit_hil_decision_topic = values.get(HIL_DECISION_TOPIC_ENV, "").strip()
        if explicit_hil_decision_topic and kafka_bootstrap_servers is None:
            raise OperatorServiceConfigurationError(
                f"{HIL_DECISION_TOPIC_ENV} requires {KAFKA_BOOTSTRAP_SERVERS_ENV}"
            )
        hil_decision_topic = (
            explicit_hil_decision_topic or DEFAULT_HIL_DECISION_TOPIC
            if kafka_bootstrap_servers is not None
            else None
        )
        stage_topic = values.get(STAGE_TOPIC_ENV, "").strip() or DEFAULT_STAGE_TOPIC
        live_stage_consumer_group_id = (
            values.get(LIVE_STAGE_CONSUMER_GROUP_ENV, "").strip()
            or DEFAULT_LIVE_STAGE_CONSUMER_GROUP
        )
        semantic_request_topic = values.get(SEMANTIC_REQUEST_TOPIC_ENV, "").strip() or None
        semantic_projection_topic = values.get(SEMANTIC_PROJECTION_TOPIC_ENV, "").strip() or None
        semantic_physical_topic = values.get(SEMANTIC_PHYSICAL_TOPIC_ENV, "").strip() or None
        semantic_outbox_namespace = values.get(SEMANTIC_OUTBOX_NAMESPACE_ENV, "").strip() or None
        if (
            semantic_outbox_namespace is not None
            and _SEMANTIC_OUTBOX_NAMESPACE_PATTERN.fullmatch(semantic_outbox_namespace) is None
        ):
            raise OperatorServiceConfigurationError(
                f"{SEMANTIC_OUTBOX_NAMESPACE_ENV} MUST be a bounded lowercase identifier"
            )
        if semantic_outbox_namespace is not None and database_url is None:
            raise OperatorServiceConfigurationError(
                f"{SEMANTIC_OUTBOX_NAMESPACE_ENV} requires {DATABASE_URL_ENV}"
            )
        semantic_transport = (
            kafka_bootstrap_servers,
            semantic_request_topic,
            semantic_projection_topic,
        )
        if any(semantic_transport) and not all(semantic_transport):
            raise OperatorServiceConfigurationError(
                f"{KAFKA_BOOTSTRAP_SERVERS_ENV}, {SEMANTIC_REQUEST_TOPIC_ENV}, and "
                f"{SEMANTIC_PROJECTION_TOPIC_ENV} MUST be configured together"
            )
        if semantic_physical_topic is not None and not all(semantic_transport):
            raise OperatorServiceConfigurationError(
                f"{SEMANTIC_PHYSICAL_TOPIC_ENV} and the semantic transport MUST be "
                "configured together"
            )
        if hil_decision_topic is not None and hil_decision_topic in {
            semantic_request_topic,
            semantic_projection_topic,
            semantic_physical_topic,
        }:
            raise OperatorServiceConfigurationError(
                f"{HIL_DECISION_TOPIC_ENV} MUST be distinct from semantic topics"
            )
        if local_azure_narrator and kafka_bootstrap_servers is not None:
            raise OperatorServiceConfigurationError(
                f"{LOCAL_AZURE_NARRATOR_ENV} MUST be disabled when semantic Kafka transport "
                "is configured"
            )
        if values.get("FDAI_CHATOPS_WEBHOOK_SECRET", "").strip() and (
            database_url is None or kafka_bootstrap_servers is None or hil_decision_topic is None
        ):
            raise OperatorServiceConfigurationError(
                "HIL callback requires PostgreSQL and configured Kafka decision transport"
            )
        semantic_consumer_group_id = (
            values.get(SEMANTIC_CONSUMER_GROUP_ENV, "").strip() or DEFAULT_SEMANTIC_CONSUMER_GROUP
        )
        semantic_kafka_client_id = (
            values.get(SEMANTIC_KAFKA_CLIENT_ID_ENV, "").strip() or DEFAULT_SEMANTIC_KAFKA_CLIENT_ID
        )
        read_investigation_request_topic = (
            values.get(READ_INVESTIGATION_REQUEST_TOPIC_ENV, "").strip() or None
        )
        if read_investigation_request_topic is not None and kafka_bootstrap_servers is None:
            raise OperatorServiceConfigurationError(
                f"{READ_INVESTIGATION_REQUEST_TOPIC_ENV} requires {KAFKA_BOOTSTRAP_SERVERS_ENV}"
            )
        if read_investigation_request_topic is not None and read_investigation_request_topic in {
            semantic_request_topic,
            semantic_projection_topic,
            semantic_physical_topic,
            hil_decision_topic,
        }:
            raise OperatorServiceConfigurationError(
                f"{READ_INVESTIGATION_REQUEST_TOPIC_ENV} MUST be distinct from semantic topics"
            )
        explicit_completion_topic = values.get(
            READ_INVESTIGATION_COMPLETION_TOPIC_ENV,
            "",
        ).strip()
        explicit_completion_group = values.get(
            READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP_ENV,
            "",
        ).strip()
        if (
            explicit_completion_topic or explicit_completion_group
        ) and kafka_bootstrap_servers is None:
            raise OperatorServiceConfigurationError(
                f"read investigation completion transport requires {KAFKA_BOOTSTRAP_SERVERS_ENV}"
            )
        read_investigation_completion_topic = (
            explicit_completion_topic or DEFAULT_READ_INVESTIGATION_COMPLETION_TOPIC
            if kafka_bootstrap_servers is not None
            else None
        )
        read_investigation_completion_consumer_group_id = (
            explicit_completion_group or DEFAULT_READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP
            if kafka_bootstrap_servers is not None
            else None
        )
        if read_investigation_completion_topic is not None and (
            read_investigation_completion_topic
            in {
                semantic_request_topic,
                semantic_projection_topic,
                semantic_physical_topic,
                read_investigation_request_topic,
                hil_decision_topic,
            }
        ):
            raise OperatorServiceConfigurationError(
                f"{READ_INVESTIGATION_COMPLETION_TOPIC_ENV} MUST be distinct from other topics"
            )
        explicit_background_task_projection_topic = values.get(
            BACKGROUND_TASK_PROJECTION_TOPIC_ENV,
            "",
        ).strip()
        explicit_background_task_projection_group = values.get(
            BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP_ENV,
            "",
        ).strip()
        if (
            explicit_background_task_projection_topic or explicit_background_task_projection_group
        ) and kafka_bootstrap_servers is None:
            raise OperatorServiceConfigurationError(
                f"background task projection transport requires {KAFKA_BOOTSTRAP_SERVERS_ENV}"
            )
        background_task_projection_topic = (
            explicit_background_task_projection_topic or DEFAULT_BACKGROUND_TASK_PROJECTION_TOPIC
            if kafka_bootstrap_servers is not None
            else None
        )
        background_task_projection_consumer_group_id = (
            explicit_background_task_projection_group
            or DEFAULT_BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP
            if kafka_bootstrap_servers is not None
            else None
        )
        if background_task_projection_topic is not None and (
            background_task_projection_topic
            in {
                semantic_request_topic,
                semantic_projection_topic,
                semantic_physical_topic,
                read_investigation_request_topic,
                read_investigation_completion_topic,
                hil_decision_topic,
            }
        ):
            raise OperatorServiceConfigurationError(
                f"{BACKGROUND_TASK_PROJECTION_TOPIC_ENV} MUST be distinct from other topics"
            )
        managed_identity_client_id = values.get(MANAGED_IDENTITY_CLIENT_ID_ENV, "").strip() or None

        return cls(
            values=MappingProxyType(values),
            host=host,
            port=port,
            tenant_id=tenant_id,
            audience=audience,
            issuer=issuer,
            jwks_uri=jwks_uri,
            group_ids=MappingProxyType(group_ids),
            cors_allow_origins=cors_allow_origins,
            database_url=database_url,
            database_role=database_role,
            database_statement_timeout_ms=database_statement_timeout_ms,
            database_connect_timeout_s=database_connect_timeout_s,
            local_azure_narrator=local_azure_narrator,
            local_azure_cli_auth=local_azure_cli_auth,
            narrator_probe_interval_seconds=narrator_probe_interval_seconds,
            kafka_bootstrap_servers=kafka_bootstrap_servers,
            hil_decision_topic=hil_decision_topic,
            stage_topic=stage_topic,
            live_stage_consumer_group_id=live_stage_consumer_group_id,
            semantic_request_topic=semantic_request_topic,
            semantic_projection_topic=semantic_projection_topic,
            semantic_physical_topic=semantic_physical_topic,
            semantic_outbox_namespace=semantic_outbox_namespace,
            semantic_consumer_group_id=semantic_consumer_group_id,
            semantic_kafka_client_id=semantic_kafka_client_id,
            read_investigation_request_topic=read_investigation_request_topic,
            read_investigation_completion_topic=read_investigation_completion_topic,
            read_investigation_completion_consumer_group_id=(
                read_investigation_completion_consumer_group_id
            ),
            background_task_projection_topic=background_task_projection_topic,
            background_task_projection_consumer_group_id=(
                background_task_projection_consumer_group_id
            ),
            managed_identity_client_id=managed_identity_client_id,
        )


def _require(environ: Mapping[str, str], key: str) -> str:
    value = environ.get(key, "").strip()
    if not value:
        raise OperatorServiceConfigurationError(f"{key} MUST be non-empty")
    return value


def _positive_int(environ: Mapping[str, str], key: str, default: int) -> int:
    raw = environ.get(key, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise OperatorServiceConfigurationError(f"{key} MUST be an integer") from exc
    if value < 1:
        raise OperatorServiceConfigurationError(f"{key} MUST be positive")
    return value


def _bounded_int(
    environ: Mapping[str, str],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    value = _positive_int(environ, key, default)
    if not minimum <= value <= maximum:
        raise OperatorServiceConfigurationError(f"{key} MUST be in [{minimum}, {maximum}]")
    return value


def _boolean(environ: Mapping[str, str], key: str, *, default: bool) -> bool:
    raw = environ.get(key, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise OperatorServiceConfigurationError(f"{key} MUST be a boolean")


__all__ = [
    "AUDIENCE_ENV",
    "BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP_ENV",
    "BACKGROUND_TASK_PROJECTION_TOPIC_ENV",
    "CORS_ORIGINS_ENV",
    "DATABASE_CONNECT_TIMEOUT_ENV",
    "DATABASE_ROLE_ENV",
    "DATABASE_STATEMENT_TIMEOUT_ENV",
    "DATABASE_URL_ENV",
    "DEV_MODE_ENV",
    "DEFAULT_HOST",
    "DEFAULT_NARRATOR_PROBE_INTERVAL_SECONDS",
    "DEFAULT_PORT",
    "EXPECTED_DATABASE_ROLE",
    "GROUP_ENV",
    "HOST_ENV",
    "ISSUER_ENV",
    "KAFKA_BOOTSTRAP_SERVERS_ENV",
    "LIVE_STAGE_CONSUMER_GROUP_ENV",
    "STAGE_TOPIC_ENV",
    "LOCAL_AZURE_NARRATOR_ENV",
    "LOCAL_AZURE_CLI_AUTH_ENV",
    "LOCAL_ENTRA_AUTH_ENV",
    "MAX_NARRATOR_PROBE_INTERVAL_SECONDS",
    "MANAGED_IDENTITY_CLIENT_ID_ENV",
    "MIN_NARRATOR_PROBE_INTERVAL_SECONDS",
    "NARRATOR_PROBE_INTERVAL_ENV",
    "JWKS_URI_ENV",
    "PORT_ENV",
    "READ_INVESTIGATION_REQUEST_TOPIC_ENV",
    "READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP_ENV",
    "READ_INVESTIGATION_COMPLETION_TOPIC_ENV",
    "SEMANTIC_CONSUMER_GROUP_ENV",
    "SEMANTIC_KAFKA_CLIENT_ID_ENV",
    "SEMANTIC_PROJECTION_TOPIC_ENV",
    "SEMANTIC_PHYSICAL_TOPIC_ENV",
    "SEMANTIC_OUTBOX_NAMESPACE_ENV",
    "SEMANTIC_REQUEST_TOPIC_ENV",
    "TENANT_ENV",
    "OperatorEnvironment",
    "OperatorServiceConfigurationError",
]
