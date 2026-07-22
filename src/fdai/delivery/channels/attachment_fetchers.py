"""Server-authenticated Slack and Teams attachment fetchers.

Inbound channel payloads contribute only opaque attachment ids and bounded
metadata. Download locations are resolved with server-owned credentials and
validated against configured HTTPS hosts before any bytes are read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import isfinite
from typing import Protocol
from urllib.parse import urlparse

import httpx

from fdai.delivery.channels.document_evidence import ChannelAttachmentFetchError
from fdai.shared.providers.conversation_channel import ChannelAttachment
from fdai.shared.providers.secret_provider import SecretProvider
from fdai.shared.providers.workload_identity import WorkloadIdentity


@dataclass(frozen=True, slots=True)
class AttachmentDownloadLocation:
    url: str
    audience: str


class TeamsAttachmentEndpointResolver(Protocol):
    """Resolve an opaque Teams attachment id through server-owned state."""

    async def resolve(self, attachment: ChannelAttachment) -> AttachmentDownloadLocation: ...


@dataclass(frozen=True, slots=True)
class SlackAttachmentFetcherConfig:
    bot_token_ref: str = "slack-bot-token"  # noqa: S105 - secret reference name
    api_base: str = "https://slack.com/api"
    allowed_download_hosts: tuple[str, ...] = ("files.slack.com",)
    timeout_seconds: float = 30.0
    max_metadata_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        _validate_fetch_config(
            api_base=self.api_base,
            allowed_hosts=self.allowed_download_hosts,
            timeout_seconds=self.timeout_seconds,
        )
        if not self.bot_token_ref:
            raise ValueError("Slack attachment bot-token reference MUST be non-empty")
        if self.max_metadata_bytes < 1:
            raise ValueError("Slack attachment metadata byte limit MUST be positive")


class SlackPrivateFileFetcher:
    """Resolve Slack file ids via ``files.info`` and download with a bot token."""

    def __init__(
        self,
        *,
        config: SlackAttachmentFetcherConfig,
        secrets: SecretProvider,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._secrets = secrets
        self._http = http_client

    async def fetch(self, attachment: ChannelAttachment, *, max_bytes: int) -> bytes:
        try:
            token = await self._secrets.get(self._config.bot_token_ref)
            if not token:
                raise ChannelAttachmentFetchError("Slack attachment credential is unavailable")
            payload = await _bounded_json_get(
                client=self._http,
                url=f"{self._config.api_base.rstrip('/')}/files.info",
                params={"file": attachment.source_ref},
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._config.timeout_seconds,
                max_bytes=self._config.max_metadata_bytes,
            )
        except ChannelAttachmentFetchError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise ChannelAttachmentFetchError("Slack attachment metadata is unavailable") from exc
        file_record = payload.get("file") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise ChannelAttachmentFetchError("Slack files.info rejected the attachment")
        if not isinstance(file_record, dict):
            raise ChannelAttachmentFetchError("Slack files.info returned no file record")
        download_url = file_record.get("url_private_download") or file_record.get("url_private")
        if not isinstance(download_url, str):
            raise ChannelAttachmentFetchError("Slack file record has no private download URL")
        _validate_download_url(download_url, self._config.allowed_download_hosts)
        return await _bounded_download(
            client=self._http,
            url=download_url,
            headers={"Authorization": f"Bearer {token}"},
            max_bytes=max_bytes,
            timeout_seconds=self._config.timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class TeamsAttachmentFetcherConfig:
    allowed_download_hosts: tuple[str, ...]
    allowed_audiences: tuple[str, ...]
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if (
            not self.allowed_download_hosts
            or not self.allowed_audiences
            or not isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError(
                "Teams attachment fetcher requires hosts, audiences, and a finite timeout"
            )


class TeamsServerAttachmentFetcher:
    """Fetch Teams bytes from a server-resolved URL with workload identity."""

    def __init__(
        self,
        *,
        config: TeamsAttachmentFetcherConfig,
        resolver: TeamsAttachmentEndpointResolver,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._resolver = resolver
        self._identity = identity
        self._http = http_client

    async def fetch(self, attachment: ChannelAttachment, *, max_bytes: int) -> bytes:
        try:
            location = await self._resolver.resolve(attachment)
            if location.audience not in self._config.allowed_audiences:
                raise ChannelAttachmentFetchError("Teams attachment audience is outside policy")
            _validate_download_url(location.url, self._config.allowed_download_hosts)
            token = await self._identity.get_token(location.audience)
            return await _bounded_download(
                client=self._http,
                url=location.url,
                headers={"Authorization": f"Bearer {token.token}"},
                max_bytes=max_bytes,
                timeout_seconds=self._config.timeout_seconds,
            )
        except ChannelAttachmentFetchError:
            raise
        except (httpx.HTTPError, RuntimeError) as exc:
            raise ChannelAttachmentFetchError("Teams attachment provider is unavailable") from exc


def _validate_fetch_config(
    *, api_base: str, allowed_hosts: tuple[str, ...], timeout_seconds: float
) -> None:
    parsed = urlparse(api_base)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("attachment API base MUST be an HTTPS URL without credentials or query")
    if not allowed_hosts or any(not _is_host_name(host) for host in allowed_hosts):
        raise ValueError("attachment download hosts MUST be non-empty host names")
    if not isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("attachment fetch timeout MUST be positive")


def _validate_download_url(url: str, allowed_hosts: tuple[str, ...]) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    try:
        port = parsed.port
    except ValueError as exc:
        raise ChannelAttachmentFetchError(
            "attachment download URL is outside the allowlist"
        ) from exc
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not any(host == allowed.casefold() for allowed in allowed_hosts)
    ):
        raise ChannelAttachmentFetchError("attachment download URL is outside the allowlist")


def _is_host_name(value: str) -> bool:
    parsed = urlparse(f"//{value}")
    try:
        port = parsed.port
    except ValueError:
        return False
    return bool(parsed.hostname and parsed.hostname == value and port is None)


async def _bounded_download(
    *,
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    max_bytes: int,
    timeout_seconds: float,
) -> bytes:
    if max_bytes < 1:
        raise ValueError("max_bytes MUST be positive")
    chunks: list[bytes] = []
    total = 0
    try:
        async with client.stream(
            "GET",
            url,
            headers=headers,
            timeout=timeout_seconds,
            follow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise ChannelAttachmentFetchError(
                    f"attachment download returned HTTP {response.status_code}"
                )
            content_length = response.headers.get("content-length")
            if content_length is not None:
                try:
                    declared = int(content_length)
                except ValueError as exc:
                    raise ChannelAttachmentFetchError(
                        "attachment Content-Length is invalid"
                    ) from exc
                if declared < 0:
                    raise ChannelAttachmentFetchError("attachment Content-Length is invalid")
                if declared > max_bytes:
                    raise ChannelAttachmentFetchError("attachment exceeds the download byte limit")
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise ChannelAttachmentFetchError("attachment exceeds the download byte limit")
                chunks.append(chunk)
    except ChannelAttachmentFetchError:
        raise
    except httpx.HTTPError as exc:
        raise ChannelAttachmentFetchError("attachment download failed") from exc
    return b"".join(chunks)


async def _bounded_json_get(
    *,
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, str],
    headers: dict[str, str],
    timeout: float,
    max_bytes: int,
) -> object:
    chunks: list[bytes] = []
    total = 0
    try:
        async with client.stream(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise ChannelAttachmentFetchError(
                    f"Slack files.info returned HTTP {response.status_code}"
                )
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise ChannelAttachmentFetchError(
                        "Slack attachment metadata exceeds the byte limit"
                    )
                chunks.append(chunk)
    except ChannelAttachmentFetchError:
        raise
    except httpx.HTTPError as exc:
        raise ChannelAttachmentFetchError("Slack attachment metadata is unavailable") from exc
    try:
        return json.loads(b"".join(chunks))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ChannelAttachmentFetchError("Slack attachment metadata is invalid") from exc


__all__ = [
    "AttachmentDownloadLocation",
    "ChannelAttachmentFetchError",
    "SlackAttachmentFetcherConfig",
    "SlackPrivateFileFetcher",
    "TeamsAttachmentEndpointResolver",
    "TeamsAttachmentFetcherConfig",
    "TeamsServerAttachmentFetcher",
]
