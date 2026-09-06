"""Bounded ACR Distribution v2 publication for a future protected executor.

This is not an installer, approval mechanism, or public mutating CLI. The caller
must bind the authenticated target and distinct executor identity to current
protected authorization, safeguards, and audit before calling either publication function.
Tokens stay in memory. Cross-host/data-endpoint redirects are refused: supporting
them would require a separately attested allowlist, which this adapter does not
accept. An Azure-public login-server name can resolve through approved private DNS.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import math
import re
import socket
import ssl
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from socket import getaddrinfo as _getaddrinfo
from socket import socket as _socket
from typing import Protocol, cast
from urllib.parse import parse_qsl, urlencode, urlsplit

from fdai_deployment_cli.oci_archive import (
    OCI_MANIFEST,
    VerifiedOciImage,
    validate_dependency_oci_archive,
    validate_oci_archive,
)

_HOST = re.compile(r"[a-z0-9]{5,50}\.azurecr\.io")
_COMPONENT = r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*"
_REPOSITORY = re.compile(rf"{_COMPONENT}(?:/{_COMPONENT})*")
_TOKEN = re.compile(r"[A-Za-z0-9._~+/-]+=*")
_RESPONSE_LIMIT = 4 * 1024 * 1024
_DNS_SLOTS = threading.BoundedSemaphore(4)
_Address = tuple[int, tuple[str, int] | tuple[str, int, int, int]]


class AcrPublishError(RuntimeError):
    """Sanitized failure with stable stage/status codes and optional HTTP status."""

    def __init__(self, stage: str, status: str, http_status: int | None = None) -> None:
        self.stage, self.status, self.http_status = stage, status, http_status
        super().__init__(f"ACR publication {stage}: {status}")


@dataclass(frozen=True, slots=True)
class RegistryResponse:
    """Bounded transport response; payload and headers are never represented."""

    status: int
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    body: bytes = field(default=b"", repr=False)

    def header(self, name: str) -> str | None:
        """Read one case-insensitive header, rejecting ambiguous duplicates."""

        values = [value for key, value in self.headers.items() if key.lower() == name.lower()]
        if len(values) > 1:
            raise AcrPublishError("response", "duplicate-header")
        return values[0] if values else None


class RegistryTransport(Protocol):
    """Injected I/O boundary: no redirects/retries, bounded body and monotonic deadline."""

    def request(
        self,
        host: str,
        method: str,
        target: str,
        headers: Mapping[str, str],
        body: Iterable[bytes],
        *,
        content_length: int,
        deadline: float,
    ) -> RegistryResponse:
        """Transmit exactly content_length bytes without persisting credentials."""
        ...


def _lookup_address(
    host: str,
    deadline: float,
    result: Queue[_Address | str],
    slots: threading.BoundedSemaphore,
) -> None:
    """Resolver workers never receive a connection, request body, or credentials."""
    outcome: _Address | str = "transport-failure"
    try:
        if time.monotonic() >= deadline:
            outcome = "timeout"
        else:
            addresses = _getaddrinfo(host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
            if addresses:
                family, _, _, _, target = addresses[0]
                if family in {socket.AF_INET, socket.AF_INET6}:
                    endpoint = cast(tuple[str, int] | tuple[str, int, int, int], target)
                    socket.inet_pton(family, endpoint[0])
                    outcome = family, endpoint
    except TimeoutError:
        outcome = "timeout"
    except OSError:
        outcome = "transport-failure"
    finally:
        result.put_nowait(outcome)
        slots.release()


def _resolve_address(host: str, deadline: float) -> _Address:
    if time.monotonic() >= deadline:
        raise AcrPublishError("transport", "timeout")
    slots = _DNS_SLOTS
    if not slots.acquire(blocking=False):
        raise AcrPublishError("transport", "resolver-busy")
    result: Queue[_Address | str] = Queue(maxsize=1)
    worker = threading.Thread(
        target=_lookup_address,
        args=(host, deadline, result, slots),
        daemon=True,
    )
    try:
        worker.start()
    except RuntimeError:
        slots.release()
        raise AcrPublishError("transport", "resolver-unavailable") from None
    try:
        address = result.get(timeout=max(0, deadline - time.monotonic()))
    except Empty:
        raise AcrPublishError("transport", "timeout") from None
    if time.monotonic() >= deadline:
        raise AcrPublishError("transport", "timeout")
    if isinstance(address, str):
        raise AcrPublishError("transport", address)
    return address


class HttpsRegistryTransport:
    """Real stdlib HTTPS transport with normal certificate/hostname verification.

    DNS waits obey the socket/call budget, with at most four daemon resolver workers.
    An abandoned worker can finish DNS only; it cannot connect or transmit HTTP.
    One numeric address is connected without a second lookup or address retries.
    TLS verifies the approved login-server hostname, not the resolved IP address.
    No proxy, custom insecure TLS context, or redirect handler is used.
    """

    def __init__(self, *, io_timeout: float = 15.0) -> None:
        if not math.isfinite(io_timeout) or not 0 < io_timeout <= 120:
            raise AcrPublishError("transport", "invalid-timeout")
        self.io_timeout = io_timeout

    def request(
        self,
        host: str,
        method: str,
        target: str,
        headers: Mapping[str, str],
        body: Iterable[bytes],
        *,
        content_length: int,
        deadline: float,
    ) -> RegistryResponse:
        """Send one bounded request; error bodies are neither read nor exposed."""

        if not _HOST.fullmatch(host) or not _request_target(target):
            raise AcrPublishError("transport", "invalid-target")
        family, address = _resolve_address(
            host, min(deadline, time.monotonic() + self._remaining(deadline))
        )
        context = ssl.create_default_context()
        connection = http.client.HTTPSConnection(
            host,
            timeout=self._remaining(deadline),
            context=context,
        )
        connection.auto_open = 0
        stream: socket.socket | None = None
        timer: threading.Timer | None = None
        try:
            self._remaining(deadline)
            stream = _socket(family, socket.SOCK_STREAM, socket.IPPROTO_TCP)
            stream.settimeout(self._remaining(deadline))
            stream.connect(address)
            stream.settimeout(self._remaining(deadline))
            connection.sock = context.wrap_socket(stream, server_hostname=host)
            self._socket_budget(connection, deadline)
            timer = threading.Timer(
                max(0, deadline - time.monotonic()),
                _shutdown,
                args=(connection.sock,),
            )
            timer.daemon = True
            timer.start()
            self._remaining(deadline)
            connection.putrequest(method, target, skip_accept_encoding=True)
            connection.putheader("Content-Length", str(content_length))
            for key, value in headers.items():
                if key.lower() not in {"authorization", "content-type", "accept"}:
                    raise AcrPublishError("transport", "invalid-header")
                connection.putheader(key, value)
            self._socket_budget(connection, deadline)
            connection.endheaders()
            sent = 0
            for chunk in body:
                if not isinstance(chunk, bytes) or len(chunk) > 1024 * 1024:
                    raise AcrPublishError("transport", "invalid-body")
                sent += len(chunk)
                if sent > content_length:
                    raise AcrPublishError("transport", "invalid-body")
                self._socket_budget(connection, deadline)
                connection.send(chunk)
            if sent != content_length:
                raise AcrPublishError("transport", "invalid-body")
            self._socket_budget(connection, deadline)
            response = connection.getresponse()
            selected: dict[str, str] = {}
            for key, value in response.getheaders():
                key = key.lower()
                if key in {"location", "docker-content-digest", "content-type", "content-length"}:
                    if key in selected:
                        raise AcrPublishError("transport", "duplicate-header")
                    selected[key] = value
            payload = bytearray()
            if response.status == 200 and method != "HEAD":
                while True:
                    self._socket_budget(connection, deadline)
                    chunk = response.read1(min(65536, _RESPONSE_LIMIT + 1 - len(payload)))
                    if not chunk:
                        break
                    payload.extend(chunk)
                    if len(payload) > _RESPONSE_LIMIT:
                        raise AcrPublishError("transport", "response-limit")
            self._remaining(deadline)
            return RegistryResponse(response.status, selected, bytes(payload))
        except TimeoutError:
            raise AcrPublishError("transport", "timeout") from None
        except (OSError, ValueError, http.client.HTTPException):
            if time.monotonic() >= deadline:
                raise AcrPublishError("transport", "timeout") from None
            raise AcrPublishError("transport", "transport-failure") from None
        finally:
            if timer is not None:
                timer.cancel()
            connection.close()
            if stream is not None:
                stream.close()

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if not math.isfinite(remaining) or remaining <= 0:
            raise AcrPublishError("transport", "timeout")
        return min(self.io_timeout, remaining)

    def _socket_budget(self, connection: http.client.HTTPSConnection, deadline: float) -> None:
        timeout = self._remaining(deadline)
        if connection.sock is not None:
            connection.sock.settimeout(timeout)


def _shutdown(stream: socket.socket | None) -> None:
    """Interrupt slow-drip headers/body at the absolute deadline, without retries."""
    if stream is not None:
        try:
            stream.shutdown(socket.SHUT_RDWR)
        except OSError:
            return


@dataclass(frozen=True, slots=True)
class PublishedImage[Revision: (str, None)]:
    """Independent digest-readback evidence, not installation or operational readiness."""

    manifest_digest: str
    source_commit: Revision
    platform_tag: str
    requests: int


class _Session:
    def __init__(
        self,
        host: str,
        transport: RegistryTransport,
        deadline: float,
        call_timeout: float,
        max_requests: int,
    ) -> None:
        self.host, self.transport, self.deadline = host, transport, deadline
        self.call_timeout, self.max_requests, self.requests = call_timeout, max_requests, 0
        self.authorization = ""

    def request(
        self,
        stage: str,
        method: str,
        target: str,
        expected: set[int],
        *,
        body: Iterable[bytes] = (),
        size: int = 0,
        media_type: str = "application/octet-stream",
    ) -> RegistryResponse:
        if self.requests >= self.max_requests:
            raise AcrPublishError(stage, "request-limit")
        if time.monotonic() >= self.deadline:
            raise AcrPublishError(stage, "timeout")
        headers = {
            "Content-Type": media_type,
            "Accept": "application/json" if stage == "token" else OCI_MANIFEST,
        }
        if self.authorization:
            headers["Authorization"] = self.authorization
        self.requests += 1
        call_deadline = min(self.deadline, time.monotonic() + self.call_timeout)
        try:
            result = self.transport.request(
                self.host,
                method,
                target,
                headers,
                body,
                content_length=size,
                deadline=call_deadline,
            )
        except AcrPublishError as exc:
            raise AcrPublishError(stage, exc.status, exc.http_status) from None
        except TimeoutError:
            raise AcrPublishError(stage, "timeout") from None
        except (OSError, ValueError, http.client.HTTPException):
            raise AcrPublishError(stage, "transport-failure") from None
        if time.monotonic() >= call_deadline:
            raise AcrPublishError(stage, "timeout")
        if result.status not in expected:
            raise AcrPublishError(stage, "http-error", result.status)
        if len(result.body) > _RESPONSE_LIMIT:
            raise AcrPublishError(stage, "response-limit")
        return result


def publish_oci_archive(
    path: Path,
    *,
    registry: str,
    repository: str,
    expected_archive_sha256: str,
    expected_manifest_digest: str,
    expected_source_commit: str,
    expected_platform_tag: str,
    credential_provider: Callable[[], str],
    transport: RegistryTransport | None = None,
    total_timeout: float = 300.0,
    call_timeout: float = 60.0,
    max_requests: int = 256,
) -> PublishedImage[str]:
    """Upload verified bytes by digest and independently GET the resulting manifest.

    Full local validation precedes credential acquisition and all HTTP. The injected
    provider must return a short-lived ACR refresh token for this approved registry
    using its own bounded identity flow. There is no credential fallback or retry.
    Failure may leave uploaded content; the caller owns audit and approved recovery.
    Invalid archives raise OciArchiveError; publication failures raise AcrPublishError.
    """

    session = _publication_session(
        registry, repository, transport, total_timeout, call_timeout, max_requests
    )
    image = validate_oci_archive(
        path,
        expected_archive_sha256=expected_archive_sha256,
        expected_manifest_digest=expected_manifest_digest,
        expected_source_commit=expected_source_commit,
        expected_platform_tag=expected_platform_tag,
    )
    return _publish_image(session, repository, image, credential_provider)


def publish_dependency_oci_archive(
    path: Path,
    *,
    registry: str,
    repository: str,
    expected_archive_sha256: str,
    expected_manifest_digest: str,
    expected_platform_tag: str,
    credential_provider: Callable[[], str],
    transport: RegistryTransport | None = None,
    total_timeout: float = 300.0,
    call_timeout: float = 60.0,
    max_requests: int = 256,
) -> PublishedImage[None]:
    """Publish approved dependency content without inventing an FDAI source revision.

    Protected authorization, target/identity binding, lease, audit and approved recovery
    remain caller prerequisites, exactly as for service publication. Local content
    validation precedes credentials; the same bounded upload and independent manifest
    GET must pass. The receipt carries source_commit=None, not dependency provenance.
    """
    session = _publication_session(
        registry, repository, transport, total_timeout, call_timeout, max_requests
    )
    image = validate_dependency_oci_archive(
        path,
        expected_archive_sha256=expected_archive_sha256,
        expected_manifest_digest=expected_manifest_digest,
        expected_platform_tag=expected_platform_tag,
    )
    return _publish_image(session, repository, image, credential_provider)


def _publication_session(
    registry: str,
    repository: str,
    transport: RegistryTransport | None,
    total_timeout: float,
    call_timeout: float,
    max_requests: int,
) -> _Session:
    deadline = time.monotonic() + total_timeout
    if (
        not math.isfinite(total_timeout)
        or not 0 < total_timeout <= 3600
        or not math.isfinite(call_timeout)
        or not 0 < call_timeout <= 120
        or type(max_requests) is not int
        or not 1 <= max_requests <= 60_003
    ):
        raise AcrPublishError("target", "invalid-budget")
    if (
        not _HOST.fullmatch(registry)
        or len(repository) > 255
        or not _REPOSITORY.fullmatch(repository)
    ):
        raise AcrPublishError("target", "invalid-target")
    return _Session(
        registry, transport or HttpsRegistryTransport(), deadline, call_timeout, max_requests
    )


def _publish_image[Revision: (str, None)](
    session: _Session,
    repository: str,
    image: VerifiedOciImage[Revision],
    credential_provider: Callable[[], str],
) -> PublishedImage[Revision]:
    if time.monotonic() >= session.deadline:
        raise AcrPublishError("credentials", "timeout")
    try:
        refresh_token = credential_provider()
    except (OSError, RuntimeError, ValueError):
        raise AcrPublishError("credentials", "unavailable") from None
    if (
        not isinstance(refresh_token, str)
        or not 0 < len(refresh_token) <= 65536
        or not _TOKEN.fullmatch(refresh_token)
    ):
        raise AcrPublishError("credentials", "invalid")
    form = urlencode(
        {
            "grant_type": "refresh_token",
            "service": session.host,
            "scope": f"repository:{repository}:pull,push",
            "refresh_token": refresh_token,
        }
    ).encode("ascii")
    response = session.request(
        "token",
        "POST",
        "/oauth2/token",
        {200},
        body=(form,),
        size=len(form),
        media_type="application/x-www-form-urlencoded",
    )
    try:
        payload = json.loads(response.body, object_pairs_hook=_unique_token_fields)
        token = payload["access_token"]
        if not isinstance(token, str) or len(token) > 65536 or not _TOKEN.fullmatch(token):
            raise ValueError
    except (ValueError, KeyError, TypeError, RecursionError):
        raise AcrPublishError("token", "invalid-response") from None
    session.authorization = "Bearer " + token
    try:
        return _upload(session, repository, image)
    finally:
        session.authorization = ""


def _unique_token_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError
    return result


def _upload[Revision: (str, None)](
    session: _Session, repository: str, image: VerifiedOciImage[Revision]
) -> PublishedImage[Revision]:
    base = f"/v2/{repository}"
    uploaded: set[str] = set()
    for blob in (image.config, *image.layers):
        if blob.digest in uploaded:
            continue
        observed = session.request("blob-head", "HEAD", f"{base}/blobs/{blob.digest}", {200, 404})
        if observed.status == 404:
            started = session.request("blob-start", "POST", f"{base}/blobs/uploads/", {202})
            location = _upload_location(started.header("Location"), session.host, repository)
            separator = "&" if "?" in location else "?"
            target = location + separator + urlencode({"digest": blob.digest})
            observed = session.request(
                "blob-upload", "PUT", target, {201}, body=image.iter_bytes(blob), size=blob.size
            )
        if observed.header("Docker-Content-Digest") != blob.digest:
            raise AcrPublishError("blob", "digest-mismatch")
        uploaded.add(blob.digest)
    manifest = image.manifest
    target = f"{base}/manifests/{manifest.digest}"
    session.request(
        "manifest-put",
        "PUT",
        target,
        {201},
        body=image.iter_bytes(manifest),
        size=manifest.size,
        media_type=manifest.media_type,
    )
    readback = session.request("manifest-readback", "GET", target, {200})
    if (
        readback.header("Docker-Content-Digest") != manifest.digest
        or "sha256:" + hashlib.sha256(readback.body).hexdigest() != manifest.digest
    ):
        raise AcrPublishError("manifest-readback", "digest-mismatch")
    return PublishedImage(
        manifest.digest, image.source_commit, image.platform_tag, session.requests
    )


def _request_target(value: str) -> bool:
    return (
        value.startswith("/")
        and not value.startswith("//")
        and len(value) <= 8192
        and all(32 < ord(character) < 127 for character in value)
        and "\\" not in value
        and "#" not in value
    )


def _upload_location(value: str | None, host: str, repository: str) -> str:
    try:
        if (
            value is None
            or len(value) > 4096
            or any(ord(character) <= 32 or ord(character) >= 127 for character in value)
            or "\\" in value
            or "#" in value
        ):
            raise ValueError
        parsed = urlsplit(value)
        if (parsed.scheme or parsed.netloc) and (parsed.scheme != "https" or parsed.netloc != host):
            raise ValueError
        prefix = f"/v2/{repository}/blobs/uploads/"
        upload_id = parsed.path.removeprefix(prefix)
        if (
            not parsed.path.startswith(prefix)
            or upload_id in {".", ".."}
            or not re.fullmatch(r"[A-Za-z0-9._~-]+", upload_id)
        ):
            raise ValueError
        query = parse_qsl(
            parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=1
        )
        if any(key != "_state" or not value for key, value in query):
            raise ValueError
        return parsed.path + ("?" + urlencode(query) if query else "")
    except (ValueError, TypeError):
        raise AcrPublishError("blob-start", "invalid-location") from None
