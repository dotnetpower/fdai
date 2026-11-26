"""Private, bounded Microsoft Graph I/O for the Entra bootstrap adapter."""

from __future__ import annotations

import http.client
import json
import queue
import re
import socket
import ssl
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit
from uuid import UUID

HOST = "graph.microsoft.com"
MAX_BYTES = 1_048_576
MAX_REQUESTS = 96
Json = dict[str, Any]


class EntraBootstrapError(RuntimeError):
    """Expose only stable failure codes, never provider text or private identifiers."""

    def __init__(self, code: str, http_status: int | None = None) -> None:
        self.code, self.http_status = code, http_status
        super().__init__(f"Entra bootstrap: {code}")


@dataclass(frozen=True, slots=True)
class GraphToken:
    """In-memory provider result; Graph independently confirms its tenant."""

    tenant_id: str = field(repr=False)
    access_token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class GraphResponse:
    """One bounded HTTP response with an intentionally non-represented payload."""

    status: int
    body: bytes = field(default=b"", repr=False)


class GraphTransport(Protocol):
    """Trusted injection seam: fixed Graph host, no retries, persistence, or redirects."""

    def request(
        self,
        method: str,
        target: str,
        headers: Mapping[str, str],
        body: bytes,
        *,
        deadline: float,
    ) -> GraphResponse:
        """Complete one request before its monotonic deadline."""
        ...


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if not 0 < remaining <= 180:
        raise EntraBootstrapError("deadline")
    return min(10.0, remaining)


def _shutdown(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        return


class HttpsGraphTransport:
    """Verified stdlib HTTPS; bounded DNS, socket work, headers, and response body.

    DNS workers have no credential or HTTP access. A late DNS result cannot send a
    request. Only the first resolved address is attempted, without fallback/retry.
    """

    def request(
        self,
        method: str,
        target: str,
        headers: Mapping[str, str],
        body: bytes,
        *,
        deadline: float,
    ) -> GraphResponse:
        """Send once to the fixed public Graph endpoint, ignoring proxy environment."""
        parsed = urlsplit(target)
        if (
            method not in {"GET", "POST", "PATCH"}
            or parsed.netloc
            or parsed.scheme
            or not target.startswith("/v1.0/")
            or not target.isascii()
            or any(ord(char) <= 32 or ord(char) == 127 for char in target)
            or "\\" in target
            or "#" in target
            or len(target) > 4096
            or len(body) > 131_072
            or set(headers) != {"Authorization", "Content-Type", "Accept"}
            or not re.fullmatch(r"Bearer [A-Za-z0-9._~+/-]+=*", headers["Authorization"])
            or headers["Content-Type"] != "application/json"
            or headers["Accept"] != "application/json"
        ):
            raise EntraBootstrapError("invalid-request")
        resolved: queue.Queue[Any] = queue.Queue(maxsize=1)

        def resolve() -> None:
            try:
                resolved.put(socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM))
            except OSError:
                resolved.put(None)

        connection = http.client.HTTPSConnection(HOST, context=ssl.create_default_context())
        raw: socket.socket | None = None
        timer: threading.Timer | None = None
        try:
            threading.Thread(target=resolve, daemon=True).start()
            addresses = resolved.get(timeout=_remaining(deadline))
            if not addresses:
                raise EntraBootstrapError("transport")
            family, kind, protocol, _, address = addresses[0]
            raw = socket.socket(family, kind, protocol)
            raw.settimeout(_remaining(deadline))
            raw.connect(address)
            raw.settimeout(_remaining(deadline))
            connection.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=HOST)
            timer = threading.Timer(
                _remaining(deadline),
                _shutdown,
                args=(connection.sock,),
            )
            timer.daemon = True
            timer.start()
            connection.sock.settimeout(_remaining(deadline))
            connection.request(method, target, body=body, headers=dict(headers))
            response = connection.getresponse()
            payload = bytearray()
            if response.status in {200, 201}:
                while True:
                    connection.sock.settimeout(_remaining(deadline))
                    chunk = response.read1(min(65_536, MAX_BYTES + 1 - len(payload)))
                    if not chunk:
                        break
                    payload.extend(chunk)
                    if len(payload) > MAX_BYTES:
                        raise EntraBootstrapError("response-limit")
            _remaining(deadline)
            return GraphResponse(response.status, bytes(payload))
        except (TimeoutError, queue.Empty):
            raise EntraBootstrapError("timeout") from None
        except (OSError, ValueError, http.client.HTTPException):
            raise EntraBootstrapError("transport") from None
        finally:
            if timer is not None:
                timer.cancel()
            connection.close()
            if raw is not None:
                raw.close()


def uuid(value: object) -> str:
    """Require a nonzero UUID without echoing rejected values."""
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value
    ):
        raise EntraBootstrapError("invalid-uuid")
    result = UUID(value)
    if not result.int:
        raise EntraBootstrapError("invalid-uuid")
    return str(result)


def objects(value: object) -> list[Json]:
    """Reject unknown or incomplete collections instead of interpreting absence."""
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise EntraBootstrapError("invalid-response")
    return value


def strings(value: object) -> list[str]:
    """Require a complete string collection from Graph."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise EntraBootstrapError("invalid-response")
    return value


def matches(actual: Json, expected: Json) -> bool:
    """Compare projected fields recursively, retaining unrelated array entries."""
    for key, value in expected.items():
        observed = actual.get(key)
        if isinstance(value, dict):
            if not isinstance(observed, dict) or not matches(observed, value):
                return False
        elif isinstance(value, list):
            if not isinstance(observed, list) or any(
                not any(
                    matches(candidate, item)
                    if isinstance(item, dict) and isinstance(candidate, dict)
                    else candidate == item
                    for candidate in observed
                )
                for item in value
            ):
                return False
        elif type(observed) is not type(value) or observed != value:
            return False
    return True


class Graph:
    """One token-pinned attempt with request and total budgets; never retries."""

    def __init__(
        self,
        tenant_id: str,
        provider: Callable[[str], GraphToken],
        transport: GraphTransport,
    ) -> None:
        self.deadline = time.monotonic() + 180
        self.transport, self.requests = transport, 0
        try:
            token = provider(tenant_id)
        except (OSError, RuntimeError, ValueError):
            raise EntraBootstrapError("token-provider") from None
        if not isinstance(token, GraphToken):
            raise EntraBootstrapError("token-provider")
        if uuid(token.tenant_id) != tenant_id:
            raise EntraBootstrapError("tenant-mismatch")
        if not isinstance(token.access_token, str) or not re.fullmatch(
            r"[A-Za-z0-9._~+/-]{1,16384}={0,2}",
            token.access_token,
        ):
            raise EntraBootstrapError("invalid-token")
        self._headers = {
            "Authorization": f"Bearer {token.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        organizations = self.list("organization", {"$select": "id"})
        if len(organizations) != 1 or organizations[0].get("id") != tenant_id:
            raise EntraBootstrapError("tenant-mismatch")

    def call(self, method: str, path: str, body: Json | None = None) -> Json:
        """Make one exact request, dropping all provider errors and error bodies."""
        _remaining(self.deadline)
        if self.requests >= MAX_REQUESTS:
            raise EntraBootstrapError("request-limit")
        encoded = b"" if body is None else json.dumps(body, separators=(",", ":")).encode()
        if len(encoded) > 131_072:
            raise EntraBootstrapError("request-limit")
        self.requests += 1
        try:
            response = self.transport.request(
                method,
                "/v1.0/" + path,
                self._headers,
                encoded,
                deadline=min(self.deadline, time.monotonic() + 10),
            )
        except EntraBootstrapError:
            raise
        except (OSError, ValueError, http.client.HTTPException, TimeoutError):
            raise EntraBootstrapError("transport") from None
        _remaining(self.deadline)
        expected = {"GET": {200}, "POST": {201, 204}, "PATCH": {204}}[method]
        if response.status not in expected:
            raise EntraBootstrapError("http-failure", response.status)
        if len(response.body) > MAX_BYTES:
            raise EntraBootstrapError("response-limit")
        if response.status == 204:
            return {}
        try:
            result = json.loads(response.body)
        except (ValueError, RecursionError):
            raise EntraBootstrapError("invalid-response") from None
        if not isinstance(result, dict):
            raise EntraBootstrapError("invalid-response")
        return result

    def list(self, path: str, query: Mapping[str, str] | None = None) -> list[Json]:
        """Require a complete single bounded page; never follow nextLink URLs."""
        paging = {} if path == "organization" else {"$top": "100"}
        result = self.call("GET", path + "?" + urlencode({**paging, **(query or {})}))
        if "@odata.nextLink" in result:
            raise EntraBootstrapError("incomplete-collection")
        rows = objects(result.get("value"))
        if len(rows) > 100:
            raise EntraBootstrapError("response-limit")
        return rows

    def owned(self, kind: str, marker: str, name: str, nickname: str = "") -> Json | None:
        """Require one exact marker and reject colliding names, including foreign ones."""
        predicate = (
            f"mailNickname eq '{nickname}'" if kind == "groups" else f"tags/any(t:t eq '{marker}')"
        )
        marked = self.list(kind, {"$filter": predicate})
        named = self.list(kind, {"$filter": f"displayName eq '{name}'"})
        records = {uuid(row.get("id")): row for row in [*marked, *named]}
        if len(marked) > 1 or len(named) > 1 or len(records) > 1:
            raise EntraBootstrapError("ambiguous-ownership")
        if not records:
            return None
        object_id = next(iter(records))
        record = self.get(kind, object_id)
        valid = (
            record.get("description") == marker
            if kind == "groups"
            else [tag for tag in strings(record.get("tags")) if tag.startswith("fdai-bootstrap:")]
            == [marker]
        )
        if not valid or record.get("displayName") != name or record.get("id") != object_id:
            raise EntraBootstrapError("foreign-ownership")
        uuid(record.get("id"))
        return record

    def get(self, kind: str, object_id: str) -> Json:
        """Select the complete group security contract, including nondefault fields."""
        query = (
            "?$select=id,displayName,description,mailNickname,mailEnabled,securityEnabled,"
            "groupTypes,isAssignableToRole,onPremisesSyncEnabled"
            if kind == "groups"
            else ""
        )
        return self.call("GET", f"{kind}/{object_id}{query}")

    def ensure(self, kind: str, existing: Json | None, expected: Json) -> Json:
        """Create or patch, then independently GET every requested field."""
        if existing is None:
            created = self.call("POST", kind, expected)
            object_id = uuid(created.get("id"))
        else:
            object_id = uuid(existing.get("id"))
            if not matches(existing, expected):
                self.call("PATCH", f"{kind}/{object_id}", expected)
        observed = self.get(kind, object_id)
        if observed.get("id") != object_id or not matches(observed, expected):
            raise EntraBootstrapError("readback-mismatch")
        if existing and "appId" in existing and observed.get("appId") != existing["appId"]:
            raise EntraBootstrapError("readback-mismatch")
        return observed
