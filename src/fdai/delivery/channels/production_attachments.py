"""Production composition for protected Slack and Teams attachments."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite

import httpx

from fdai.core.document_ingestion import DocumentIngestionService, DocumentIngestionWorker
from fdai.delivery.channels.attachment_fetchers import (
    SlackAttachmentFetcherConfig,
    SlackPrivateFileFetcher,
    TeamsAttachmentEndpointResolver,
    TeamsAttachmentFetcherConfig,
    TeamsServerAttachmentFetcher,
)
from fdai.delivery.channels.document_evidence import (
    ChannelAttachmentFetcher,
    ChannelDocumentEvidenceConfig,
    ProtectedChannelAttachmentIngestor,
)
from fdai.shared.providers.secret_provider import SecretProvider
from fdai.shared.providers.workload_identity import WorkloadIdentity


class ProductionAttachmentConfigError(ValueError):
    """Raised when protected channel attachments are partially configured."""


@dataclass(frozen=True, slots=True)
class ProductionAttachmentConfig:
    collection_id: str
    access_descriptor_ref: str
    reader_groups: tuple[str, ...]
    retention_policy_version: str
    slack_bot_token_ref: str = "slack-bot-token"  # noqa: S105 - reference name
    slack_allowed_hosts: tuple[str, ...] = ("files.slack.com",)
    teams_allowed_hosts: tuple[str, ...] = ()
    teams_allowed_audiences: tuple[str, ...] = ()
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if (
            not self.collection_id
            or not self.access_descriptor_ref
            or not self.retention_policy_version
            or not isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ProductionAttachmentConfigError(
                "channel attachment collection, access, retention, and timeout are required"
            )

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str],
    ) -> ProductionAttachmentConfig | None:
        enabled = environ.get("FDAI_CHANNEL_ATTACHMENTS_ENABLED", "").strip().casefold()
        if enabled not in {"1", "true", "yes", "on"}:
            return None
        return cls(
            collection_id=_required(environ, "FDAI_CHANNEL_ATTACHMENT_COLLECTION"),
            access_descriptor_ref=_required(
                environ,
                "FDAI_CHANNEL_ATTACHMENT_ACCESS_REF",
            ),
            reader_groups=_csv(environ.get("FDAI_CHANNEL_ATTACHMENT_READER_GROUPS", "")),
            retention_policy_version=_required(
                environ,
                "FDAI_CHANNEL_ATTACHMENT_RETENTION_POLICY",
            ),
            slack_bot_token_ref=(
                environ.get("FDAI_SLACK_BOT_TOKEN_REF", "").strip() or "slack-bot-token"
            ),
            slack_allowed_hosts=_csv(environ.get("FDAI_SLACK_FILE_HOSTS", "files.slack.com")),
            teams_allowed_hosts=_csv(environ.get("FDAI_TEAMS_ATTACHMENT_HOSTS", "")),
            teams_allowed_audiences=_csv(environ.get("FDAI_TEAMS_ATTACHMENT_AUDIENCES", "")),
            timeout_seconds=_positive_float(
                environ.get("FDAI_CHANNEL_ATTACHMENT_TIMEOUT_SECONDS", ""),
                30.0,
            ),
        )


def build_production_attachment_ingestor(
    *,
    config: ProductionAttachmentConfig,
    service: DocumentIngestionService,
    worker: DocumentIngestionWorker,
    secrets: SecretProvider,
    http_client: httpx.AsyncClient,
    slack_enabled: bool,
    teams_enabled: bool,
    teams_identity: WorkloadIdentity | None = None,
    teams_resolver: TeamsAttachmentEndpointResolver | None = None,
) -> ProtectedChannelAttachmentIngestor:
    fetchers: dict[str, ChannelAttachmentFetcher] = {}
    if slack_enabled:
        fetchers["slack"] = SlackPrivateFileFetcher(
            config=SlackAttachmentFetcherConfig(
                bot_token_ref=config.slack_bot_token_ref,
                allowed_download_hosts=config.slack_allowed_hosts,
                timeout_seconds=config.timeout_seconds,
            ),
            secrets=secrets,
            http_client=http_client,
        )
    if teams_enabled:
        if (
            teams_identity is None
            or teams_resolver is None
            or not config.teams_allowed_hosts
            or not config.teams_allowed_audiences
        ):
            raise ProductionAttachmentConfigError(
                "Teams attachments require identity, resolver, hosts, and audiences"
            )
        fetchers["teams"] = TeamsServerAttachmentFetcher(
            config=TeamsAttachmentFetcherConfig(
                allowed_download_hosts=config.teams_allowed_hosts,
                allowed_audiences=config.teams_allowed_audiences,
                timeout_seconds=config.timeout_seconds,
            ),
            resolver=teams_resolver,
            identity=teams_identity,
            http_client=http_client,
        )
    if not fetchers:
        raise ProductionAttachmentConfigError(
            "channel attachments require at least one enabled channel"
        )
    return ProtectedChannelAttachmentIngestor(
        service=service,
        worker=worker,
        fetchers=fetchers,
        config=ChannelDocumentEvidenceConfig(
            collection_id=config.collection_id,
            access_descriptor_ref=config.access_descriptor_ref,
            reader_groups=config.reader_groups,
            retention_policy_version=config.retention_policy_version,
        ),
    )


def _required(environ: Mapping[str, str], key: str) -> str:
    value = environ.get(key, "").strip()
    if not value:
        raise ProductionAttachmentConfigError(f"{key} MUST be configured")
    return value


def _csv(raw: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))


def _positive_float(raw: str, default: float) -> float:
    try:
        value = float(raw) if raw.strip() else default
    except ValueError as exc:
        raise ProductionAttachmentConfigError(
            "channel attachment timeout MUST be a number"
        ) from exc
    if not isfinite(value) or value <= 0:
        raise ProductionAttachmentConfigError("channel attachment timeout MUST be positive")
    return value


__all__ = [
    "ProductionAttachmentConfig",
    "ProductionAttachmentConfigError",
    "build_production_attachment_ingestor",
]
