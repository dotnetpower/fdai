"""Protected channel attachment fetch and ingestion handoff."""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO, Protocol, Self, cast
from urllib.parse import SplitResult, quote, urlsplit

import httpx
from azure.core.credentials_async import AsyncTokenCredential
from fdai_operator_service.families.conversation.channel_edge.models import (
    ChannelAttachment,
)
from fdai_service_contracts import (
    ChannelAttachmentAdmissionReceipt,
    ChannelAttachmentAdmissionRequest,
    ChannelAttachmentCommitReceipt,
    ChannelAttachmentTerminalReceipt,
)


class ChannelAttachmentHandoffError(RuntimeError):
    """Fail one attachment without retaining provider response details."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class WorkloadAccessToken:
    """Bind a secret bearer token to its requested non-secret audience."""

    token: str
    audience: str

    def __post_init__(self) -> None:
        if not self.token or not self.audience:
            raise ValueError("workload token and audience MUST be non-empty")


class SlackBotTokenProvider(Protocol):
    """Resolve the Slack bot secret without exposing it to configuration records."""

    async def get_token(self) -> str: ...


class AudienceTokenProvider(Protocol):
    """Resolve one token scoped to a server-selected audience."""

    async def get_token(self, audience: str) -> WorkloadAccessToken: ...


class AzureAttachmentTokenProvider:
    """Acquire audience-bound attachment tokens from one process-owned credential."""

    def __init__(self, credential: AsyncTokenCredential) -> None:
        self._credential = credential
        self._closed = False

    async def get_token(self, audience: str) -> WorkloadAccessToken:
        if not audience.strip() or len(audience) > 512:
            raise ValueError("attachment token audience is invalid")
        token = await self._credential.get_token(audience)
        if not isinstance(token.token, str) or not token.token:
            raise RuntimeError("attachment credential returned an invalid token")
        return WorkloadAccessToken(token.token, audience)

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            await self._credential.close()


class StaticSlackBotTokenProvider:
    """Retain one startup-injected Slack secret without rendering it in repr."""

    __slots__ = ("_token",)

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("Slack bot token MUST be non-empty")
        self._token = token

    async def get_token(self) -> str:
        return self._token


@dataclass(frozen=True, slots=True)
class AttachmentDownloadLocation:
    """Carry only a server-resolved Teams destination and token audience."""

    url: str
    audience: str


class TeamsAttachmentEndpointResolver(Protocol):
    """Resolve an opaque provider id through server-owned deployment state."""

    async def resolve(
        self,
        *,
        conversation_ref: str,
        attachment_id: str,
    ) -> AttachmentDownloadLocation: ...


class ConfiguredTeamsAttachmentEndpointResolver:
    """Expand an opaque id only into a fixed operator-configured HTTPS template."""

    def __init__(self, *, url_template: str, audience: str) -> None:
        if url_template.count("{attachment_id}") != 1 or "{" in url_template.replace(
            "{attachment_id}", ""
        ):
            raise ValueError("Teams attachment URL template MUST contain one attachment_id")
        probe = url_template.replace("{attachment_id}", "probe")
        _validated_https_url(probe, allowed_hosts=frozenset({_required_host(probe)}))
        if not audience.strip() or len(audience) > 512:
            raise ValueError("Teams attachment audience is invalid")
        self._url_template = url_template
        self._audience = audience

    async def resolve(
        self,
        *,
        conversation_ref: str,
        attachment_id: str,
    ) -> AttachmentDownloadLocation:
        del conversation_ref
        if not attachment_id or len(attachment_id) > 200:
            raise ChannelAttachmentHandoffError(
                "Teams attachment id is invalid", code="invalid_source_ref"
            )
        return AttachmentDownloadLocation(
            url=self._url_template.replace("{attachment_id}", quote(attachment_id, safe="")),
            audience=self._audience,
        )


class SpooledAttachment:
    """Own one unnamed temporary file and expose bounded replay exactly while open."""

    def __init__(
        self,
        handle: BinaryIO,
        *,
        size_bytes: int,
        sha256: str,
        chunk_size: int,
    ) -> None:
        self._handle = handle
        self.size_bytes = size_bytes
        self.sha256 = sha256
        self._chunk_size = chunk_size
        self._closed = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        await self.close()

    async def chunks(self) -> AsyncIterator[bytes]:
        if self._closed:
            raise RuntimeError("attachment spool is closed")
        await asyncio.to_thread(self._handle.seek, 0)
        while chunk := await asyncio.to_thread(self._handle.read, self._chunk_size):
            yield chunk

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await asyncio.to_thread(self._handle.close)


class BoundedAttachmentSpool:
    """Capture decoded provider bytes in an unnamed quota-bound scratch file."""

    def __init__(self, *, scratch_directory: Path, chunk_size: int = 64 * 1024) -> None:
        root = scratch_directory.resolve()
        if chunk_size < 1 or not root.is_dir():
            raise ValueError("attachment scratch directory and chunk size are invalid")
        self._root = root
        self._chunk_size = chunk_size

    async def capture(
        self,
        chunks: AsyncIterator[bytes],
        *,
        expected_size: int,
        max_size: int,
    ) -> SpooledAttachment:
        if expected_size < 1 or expected_size > max_size:
            raise ChannelAttachmentHandoffError(
                "attachment declared size exceeds policy", code="size_limit"
            )
        handle = cast(
            BinaryIO,
            await asyncio.to_thread(
                tempfile.TemporaryFile,
                mode="w+b",
                dir=self._root,
            ),
        )
        digest = hashlib.sha256()
        observed = 0
        try:
            async for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise ChannelAttachmentHandoffError(
                        "attachment stream yielded invalid bytes", code="invalid_stream"
                    )
                observed += len(chunk)
                if observed > expected_size or observed > max_size:
                    raise ChannelAttachmentHandoffError(
                        "attachment stream exceeds its admitted size", code="size_mismatch"
                    )
                digest.update(chunk)
                await asyncio.to_thread(handle.write, chunk)
            if observed != expected_size:
                raise ChannelAttachmentHandoffError(
                    "attachment stream size does not match metadata", code="size_mismatch"
                )
            await asyncio.to_thread(handle.flush)
            return SpooledAttachment(
                handle,
                size_bytes=observed,
                sha256=digest.hexdigest(),
                chunk_size=self._chunk_size,
            )
        except BaseException:
            await asyncio.to_thread(handle.close)
            raise


class ChannelAttachmentFetcher(Protocol):
    """Fetch one admitted opaque attachment into protected scratch."""

    async def fetch(
        self,
        attachment: ChannelAttachment,
        *,
        conversation_ref: str,
        max_content_bytes: int,
    ) -> SpooledAttachment: ...


class SlackPrivateAttachmentFetcher:
    """Resolve Slack metadata from files.info and stream only an allowlisted private URL."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        tokens: SlackBotTokenProvider,
        spool: BoundedAttachmentSpool,
        files_info_url: str,
        metadata_hosts: frozenset[str],
        download_hosts: frozenset[str],
        metadata_limit_bytes: int = 256 * 1024,
    ) -> None:
        _validated_https_url(files_info_url, allowed_hosts=metadata_hosts)
        if urlsplit(files_info_url).query or urlsplit(files_info_url).fragment:
            raise ValueError("Slack files.info URL MUST NOT contain a query or fragment")
        if metadata_limit_bytes < 1:
            raise ValueError("Slack metadata limit MUST be positive")
        self._http = http_client
        self._tokens = tokens
        self._spool = spool
        self._files_info_url = files_info_url
        self._download_hosts = download_hosts
        self._metadata_limit = metadata_limit_bytes

    async def fetch(
        self,
        attachment: ChannelAttachment,
        *,
        conversation_ref: str,
        max_content_bytes: int,
    ) -> SpooledAttachment:
        del conversation_ref
        file_id = _opaque_source_id(attachment.source_ref, "slack-file:")
        token = await self._tokens.get_token()
        if not token:
            raise ChannelAttachmentHandoffError(
                "Slack file credential is unavailable", code="credential_unavailable"
            )
        metadata = await self._slack_metadata(file_id, token)
        file_record = metadata.get("file")
        if metadata.get("ok") is not True or not isinstance(file_record, Mapping):
            raise ChannelAttachmentHandoffError(
                "Slack files.info did not return a file", code="metadata_rejected"
            )
        if (
            file_record.get("id") != file_id
            or file_record.get("name") != attachment.name
            or file_record.get("mimetype") != attachment.media_type_hint
            or file_record.get("size") != attachment.size_bytes
        ):
            raise ChannelAttachmentHandoffError(
                "Slack file metadata changed after ingress", code="metadata_mismatch"
            )
        download_url = file_record.get("url_private_download") or file_record.get("url_private")
        if not isinstance(download_url, str):
            raise ChannelAttachmentHandoffError(
                "Slack private file URL is unavailable", code="metadata_rejected"
            )
        _validated_https_url(download_url, allowed_hosts=self._download_hosts)
        return await _download_to_spool(
            http_client=self._http,
            url=download_url,
            authorization="Bearer " + token,
            spool=self._spool,
            expected_size=attachment.size_bytes,
            max_size=max_content_bytes,
        )

    async def _slack_metadata(self, file_id: str, token: str) -> Mapping[str, Any]:
        async with self._http.stream(
            "GET",
            self._files_info_url,
            params={"file": file_id},
            headers={"Authorization": "Bearer " + token},
            follow_redirects=False,
        ) as response:
            _require_http_ok(response, source="Slack metadata")
            body = await _bounded_response_body(response, self._metadata_limit)
        try:
            value = json.loads(body, object_pairs_hook=_unique_object)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ChannelAttachmentHandoffError(
                "Slack metadata is invalid JSON", code="invalid_metadata"
            ) from exc
        if not isinstance(value, Mapping):
            raise ChannelAttachmentHandoffError(
                "Slack metadata is not an object", code="invalid_metadata"
            )
        return value


class TeamsPrivateAttachmentFetcher:
    """Fetch only a server-resolved Teams location with an audience-scoped token."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        tokens: AudienceTokenProvider,
        resolver: TeamsAttachmentEndpointResolver,
        spool: BoundedAttachmentSpool,
        allowed_hosts: frozenset[str],
        allowed_audiences: frozenset[str],
    ) -> None:
        if not allowed_hosts or not allowed_audiences:
            raise ValueError("Teams attachment host and audience allowlists are required")
        self._http = http_client
        self._tokens = tokens
        self._resolver = resolver
        self._spool = spool
        self._allowed_hosts = allowed_hosts
        self._allowed_audiences = allowed_audiences

    async def fetch(
        self,
        attachment: ChannelAttachment,
        *,
        conversation_ref: str,
        max_content_bytes: int,
    ) -> SpooledAttachment:
        attachment_id = _opaque_source_id(attachment.source_ref, "teams-file:")
        location = await self._resolver.resolve(
            conversation_ref=conversation_ref,
            attachment_id=attachment_id,
        )
        _validated_https_url(location.url, allowed_hosts=self._allowed_hosts)
        if location.audience not in self._allowed_audiences:
            raise ChannelAttachmentHandoffError(
                "Teams attachment audience is not authorized", code="invalid_audience"
            )
        token = await self._tokens.get_token(location.audience)
        if token.audience != location.audience:
            raise ChannelAttachmentHandoffError(
                "Teams identity returned another audience", code="identity_audience_mismatch"
            )
        return await _download_to_spool(
            http_client=self._http,
            url=location.url,
            authorization="Bearer " + token.token,
            spool=self._spool,
            expected_size=attachment.size_bytes,
            max_size=max_content_bytes,
        )


class ChannelAttachmentIntakeClient:
    """Call one fixed ingestion origin with a workload token and strict receipts."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        tokens: AudienceTokenProvider,
        origin: str,
        audience: str,
        allow_loopback_http: bool = False,
    ) -> None:
        parsed = urlsplit(origin)
        local_http = (
            allow_loopback_http
            and parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        )
        if not local_http:
            parsed = _validated_https_url(origin, allowed_hosts=frozenset({_required_host(origin)}))
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("attachment intake origin MUST be an HTTPS origin")
        if not audience.strip() or len(audience) > 512:
            raise ValueError("attachment intake audience is invalid")
        self._http = http_client
        self._tokens = tokens
        self._origin = origin.rstrip("/")
        self._audience = audience

    async def admit(
        self, request: ChannelAttachmentAdmissionRequest
    ) -> ChannelAttachmentAdmissionReceipt:
        response = await self._request(
            "POST",
            "/internal/document-ingestion/channel-attachments/v1/admissions",
            json=request.model_dump(mode="json"),
        )
        receipt = _decode_receipt(response)
        if not isinstance(receipt, ChannelAttachmentAdmissionReceipt):
            raise ChannelAttachmentHandoffError(
                "intake admission returned another receipt kind", code="invalid_receipt"
            )
        _match_receipt_request(request, receipt)
        return receipt

    async def commit(
        self,
        request: ChannelAttachmentAdmissionRequest,
        content: SpooledAttachment,
    ) -> ChannelAttachmentCommitReceipt:
        response = await self._request(
            "PUT",
            f"/internal/document-ingestion/channel-attachments/v1/{request.handoff_id}/content",
            headers={
                "X-FDAI-Request-Digest": request.request_digest,
                "X-FDAI-Content-SHA256": content.sha256,
                "Content-Length": str(content.size_bytes),
                "Content-Type": "application/octet-stream",
            },
            content=content.chunks(),
        )
        receipt = _decode_receipt(response)
        if not isinstance(receipt, ChannelAttachmentCommitReceipt):
            raise ChannelAttachmentHandoffError(
                "intake commit returned another receipt kind", code="invalid_receipt"
            )
        _match_receipt_request(request, receipt)
        return receipt

    async def status(
        self,
        request: ChannelAttachmentAdmissionRequest,
    ) -> (
        ChannelAttachmentAdmissionReceipt
        | ChannelAttachmentCommitReceipt
        | ChannelAttachmentTerminalReceipt
    ):
        response = await self._request(
            "GET",
            f"/internal/document-ingestion/channel-attachments/v1/{request.handoff_id}",
            headers={"X-FDAI-Request-Digest": request.request_digest},
        )
        receipt = _decode_receipt(response)
        _match_receipt_request(request, receipt)
        return receipt

    async def probe_readiness(self) -> bool:
        """Verify the configured workload token at the fixed intake origin."""

        try:
            response = await self._request(
                "GET",
                "/internal/document-ingestion/channel-attachments/v1/auth-probe",
            )
        except ChannelAttachmentHandoffError:
            return False
        return response.status_code == 204

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = await self._tokens.get_token(self._audience)
        if token.audience != self._audience:
            raise ChannelAttachmentHandoffError(
                "ingestion identity returned another audience",
                code="identity_audience_mismatch",
            )
        try:
            request = self._http.build_request(
                method,
                self._origin + path,
                headers={
                    "Authorization": "Bearer " + token.token,
                    **kwargs.pop("headers", {}),
                },
                **kwargs,
            )
            response = await self._http.send(
                request,
                follow_redirects=False,
                stream=True,
            )
        except httpx.HTTPError as exc:
            raise ChannelAttachmentHandoffError(
                "attachment intake transport failed", code="intake_transport"
            ) from exc
        try:
            if response.is_redirect:
                raise ChannelAttachmentHandoffError(
                    "attachment intake redirect was refused", code="intake_redirect"
                )
            if response.status_code < 200 or response.status_code >= 300:
                code = {
                    401: "intake_unauthenticated",
                    403: "intake_denied",
                    404: "intake_not_found",
                    409: "intake_conflict",
                    413: "intake_size_limit",
                }.get(response.status_code, "intake_unavailable")
                raise ChannelAttachmentHandoffError(
                    "attachment intake rejected the request", code=code
                )
            content = await _bounded_intake_response(response, maximum=256 * 1024)
            return httpx.Response(
                status_code=response.status_code,
                headers=response.headers,
                content=content,
                request=request,
            )
        finally:
            await response.aclose()


async def _download_to_spool(
    *,
    http_client: httpx.AsyncClient,
    url: str,
    authorization: str,
    spool: BoundedAttachmentSpool,
    expected_size: int,
    max_size: int,
) -> SpooledAttachment:
    async with http_client.stream(
        "GET",
        url,
        headers={"Authorization": authorization},
        follow_redirects=False,
    ) as response:
        _require_http_ok(response, source="private attachment")
        length = response.headers.get("content-length")
        if length is not None:
            try:
                parsed_length = int(length)
            except ValueError as exc:
                raise ChannelAttachmentHandoffError(
                    "attachment Content-Length is invalid", code="invalid_content_length"
                ) from exc
            if parsed_length < 0 or parsed_length != expected_size or parsed_length > max_size:
                raise ChannelAttachmentHandoffError(
                    "attachment Content-Length does not match metadata",
                    code="size_mismatch",
                )
        return await spool.capture(
            response.aiter_bytes(),
            expected_size=expected_size,
            max_size=max_size,
        )


async def _bounded_response_body(response: httpx.Response, maximum: int) -> bytes:
    chunks: list[bytes] = []
    observed = 0
    async for chunk in response.aiter_bytes():
        observed += len(chunk)
        if observed > maximum:
            raise ChannelAttachmentHandoffError(
                "provider metadata exceeds its bounded size", code="metadata_size_limit"
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _bounded_intake_response(response: httpx.Response, *, maximum: int) -> bytes:
    chunks: list[bytes] = []
    observed = 0
    try:
        async for chunk in response.aiter_bytes():
            observed += len(chunk)
            if observed > maximum:
                raise ChannelAttachmentHandoffError(
                    "attachment intake receipt is oversized", code="invalid_receipt"
                )
            chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise ChannelAttachmentHandoffError(
            "attachment intake transport failed", code="intake_transport"
        ) from exc
    return b"".join(chunks)


def _require_http_ok(response: httpx.Response, *, source: str) -> None:
    if response.is_redirect:
        raise ChannelAttachmentHandoffError(
            f"{source} redirect was refused", code="redirect_refused"
        )
    if response.status_code != 200:
        raise ChannelAttachmentHandoffError(f"{source} request failed", code="provider_unavailable")


def _validated_https_url(url: str, *, allowed_hosts: frozenset[str]) -> SplitResult:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("attachment URL is invalid") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname not in allowed_hosts
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("attachment URL is outside the fixed HTTPS boundary")
    return parsed


def _required_host(url: str) -> str:
    host = urlsplit(url).hostname
    if host is None:
        raise ValueError("attachment URL host is missing")
    return host


def _opaque_source_id(source_ref: str, prefix: str) -> str:
    if not source_ref.startswith(prefix):
        raise ChannelAttachmentHandoffError(
            "attachment source reference is invalid", code="invalid_source_ref"
        )
    value = source_ref[len(prefix) :]
    if not value or len(value) > 200:
        raise ChannelAttachmentHandoffError(
            "attachment source reference is invalid", code="invalid_source_ref"
        )
    return value


def _decode_receipt(
    response: httpx.Response,
) -> (
    ChannelAttachmentAdmissionReceipt
    | ChannelAttachmentCommitReceipt
    | ChannelAttachmentTerminalReceipt
):
    if len(response.content) > 256 * 1024:
        raise ChannelAttachmentHandoffError(
            "attachment intake receipt is oversized", code="invalid_receipt"
        )
    try:
        payload = json.loads(response.content, object_pairs_hook=_unique_object)
        if not isinstance(payload, dict):
            raise ValueError("receipt is not an object")
        receipt_kind = payload.get("receipt_kind")
        if receipt_kind == "admission":
            return ChannelAttachmentAdmissionReceipt.model_validate(payload)
        if receipt_kind == "commit":
            return ChannelAttachmentCommitReceipt.model_validate(payload)
        if receipt_kind == "terminal":
            return ChannelAttachmentTerminalReceipt.model_validate(payload)
        raise ValueError("receipt kind is unsupported")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ChannelAttachmentHandoffError(
            "attachment intake receipt is invalid", code="invalid_receipt"
        ) from exc


def _match_receipt_request(
    request: ChannelAttachmentAdmissionRequest,
    receipt: (
        ChannelAttachmentAdmissionReceipt
        | ChannelAttachmentCommitReceipt
        | ChannelAttachmentTerminalReceipt
    ),
) -> None:
    if receipt.handoff_id != request.handoff_id or receipt.request_digest != request.request_digest:
        raise ChannelAttachmentHandoffError(
            "attachment intake receipt is not bound to its request",
            code="invalid_receipt",
        )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


__all__ = [
    "AttachmentDownloadLocation",
    "AudienceTokenProvider",
    "AzureAttachmentTokenProvider",
    "BoundedAttachmentSpool",
    "ChannelAttachmentHandoffError",
    "ChannelAttachmentIntakeClient",
    "ConfiguredTeamsAttachmentEndpointResolver",
    "SlackBotTokenProvider",
    "SlackPrivateAttachmentFetcher",
    "StaticSlackBotTokenProvider",
    "SpooledAttachment",
    "TeamsAttachmentEndpointResolver",
    "TeamsPrivateAttachmentFetcher",
    "WorkloadAccessToken",
]
