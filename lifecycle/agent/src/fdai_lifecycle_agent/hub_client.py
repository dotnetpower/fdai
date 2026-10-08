"""Hub client seam and the loopback-HTTP implementation of the Lifecycle I0 contract.

Contract (Lifecycle I0, unauthenticated loopback Hub):

* ``GET /v1/installations/{installation_id}/plan`` returns ``200`` with
  ``{"plan": {"signed_payload": "<base64>", "signature": "<base64>"}}`` or ``204`` when no
  Plan is pending.
* ``POST /v1/installations/{installation_id}/plans/{plan_id}/reports`` returns ``202`` for a new
  or identical report, ``409`` for a conflicting attempt or other Plan bytes, ``422`` for an
  invalid body, ``404`` for an unknown Plan or installation, and ``503 concurrent_write`` with
  ``Retry-After`` when a concurrent write committed first. Only ``503 concurrent_write`` is retried
  here; any other failure leaves the persisted report for the next poll.
* ``exact_plan_digest`` is ``sha256:`` and the hex SHA-256 of the decoded ``signed_payload``.

The client only moves bytes. It never trusts a Plan; admission decides that.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Literal, Protocol, Self
from urllib.parse import quote, urlsplit

import httpx

from fdai_lifecycle_agent.strict_json import load_json

type ReportOutcome = Literal["dry-run-admitted", "rejected"]

MAX_PLAN_RESPONSE_BYTES = 256 * 1024
MAX_SUMMARY_CHARACTERS = 2000
MAX_CONCURRENT_WRITE_RETRIES = 3
_MAX_RETRY_AFTER_SECONDS = 5.0
_REASON_CODE = re.compile(r"[a-z][a-z0-9_]{0,95}\Z", re.ASCII)
_PATH_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z", re.ASCII)


class HubProtocolError(RuntimeError):
    """The Hub call failed or answered outside the contract; nothing was admitted.

    ``code`` is the Hub's error code, such as ``report_conflict``, when it sent a safe one.
    """

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SignedPlan:
    """Raw Plan bytes and Hub signature exactly as received; untrusted until admitted."""

    signed_payload: bytes
    signature: bytes


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanReport:
    """One sanitized Plan result. ``summary`` carries counts only, never identifiers.

    An admitted report names the exact Plan bytes it checked. A rejection carries only its reason.
    """

    attempt: int
    outcome: ReportOutcome
    reason_code: str
    exact_plan_digest: str | None
    summary: str
    reported_at: datetime

    def __post_init__(self) -> None:
        # Fail before sending what the Hub would answer with 422; other fields are agent-built.
        if _REASON_CODE.fullmatch(self.reason_code) is None:
            raise ValueError("reason_code MUST match ^[a-z][a-z0-9_]{0,95}$")
        if len(self.summary) > MAX_SUMMARY_CHARACTERS:
            raise ValueError("summary MUST be at most 2000 characters")
        if self.outcome == "dry-run-admitted" and self.exact_plan_digest is None:
            raise ValueError("an admitted report MUST name exact_plan_digest")
        if self.reported_at.utcoffset() is None:
            raise ValueError("reported_at MUST include timezone information")

    def to_json(self) -> dict[str, object]:
        """Return the wire body with ``reported_at`` as RFC 3339 UTC."""

        return {
            "attempt": self.attempt,
            "outcome": self.outcome,
            "reason_code": self.reason_code,
            "exact_plan_digest": self.exact_plan_digest,
            "summary": self.summary,
            "reported_at": self.reported_at.astimezone(UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
        }


class HubClient(Protocol):
    """Outbound-only Hub seam. Implementations MUST NOT hold Azure or Kubernetes rights."""

    def fetch_plan(self, installation_id: str) -> SignedPlan | None:
        """Return the pending signed Plan, or ``None`` when the Hub has none."""
        ...

    def submit_report(self, installation_id: str, plan_id: str, report: PlanReport) -> None:
        """Deliver one report; raise ``HubProtocolError`` unless the Hub accepted it."""
        ...


class HttpHubClient:
    """httpx implementation. Plain HTTP is accepted only for a loopback Hub."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_url = validate_hub_url(base_url)
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch_plan(self, installation_id: str) -> SignedPlan | None:
        path = f"/v1/installations/{_segment(installation_id, 'installation_id')}/plan"
        try:
            with self._client.stream("GET", path) as response:
                if response.status_code == 204:
                    return None
                if response.status_code == 404:
                    raise HubProtocolError("Hub does not know this installation (404)")
                if response.status_code != 200:
                    raise HubProtocolError(f"Hub plan request returned {response.status_code}")
                body = _bounded_body(response)
        except httpx.HTTPError as error:
            raise HubProtocolError(f"Hub plan request failed: {type(error).__name__}") from error
        return _parse_plan_body(body)

    def submit_report(self, installation_id: str, plan_id: str, report: PlanReport) -> None:
        path = (
            f"/v1/installations/{_segment(installation_id, 'installation_id')}"
            f"/plans/{_segment(plan_id, 'plan_id')}/reports"
        )
        for retry in range(MAX_CONCURRENT_WRITE_RETRIES + 1):
            try:
                response = self._client.post(path, json=report.to_json())
            except httpx.HTTPError as error:
                raise HubProtocolError(
                    f"Hub report request failed: {type(error).__name__}"
                ) from error
            if response.status_code == 202:
                return
            concurrent_write = (
                response.status_code == 503 and _error_code(response) == "concurrent_write"
            )
            if not concurrent_write or retry == MAX_CONCURRENT_WRITE_RETRIES:
                break
            # The Hub asks for the identical report again after a concurrent write.
            self._sleep(_retry_after(response))
        code = _error_code(response)
        raise HubProtocolError(
            f"Hub report request returned {response.status_code} {code}".rstrip(), code=code
        )


def _retry_after(response: httpx.Response) -> float:
    try:
        seconds = float(response.headers.get("Retry-After", "1"))
    except ValueError:
        seconds = 1.0
    return min(max(seconds, 0.0), _MAX_RETRY_AFTER_SECONDS)


def _error_code(response: httpx.Response) -> str:
    """Return the Hub's error code when it is a safe reason code, otherwise an empty string."""

    try:
        document = response.json()
    except ValueError:
        return ""
    code = document.get("error") if isinstance(document, dict) else None
    if isinstance(code, str) and _REASON_CODE.fullmatch(code):
        return code
    return ""


def validate_hub_url(base_url: str) -> str:
    """Return a normalized Hub base URL or raise ``ValueError``.

    HTTPS is accepted for any host. Plain HTTP is accepted only for a loopback host, because the
    Lifecycle I0 Hub has no authentication and Plan reports must not cross a network in clear.
    """

    parts = urlsplit(base_url)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Hub URL MUST NOT carry credentials, a query, or a fragment")
    if not parts.hostname:
        raise ValueError("Hub URL MUST name a host")
    if parts.scheme == "https":
        return base_url.rstrip("/")
    if parts.scheme == "http" and _is_loopback(parts.hostname):
        return base_url.rstrip("/")
    raise ValueError("Hub URL MUST use https, or http on a loopback host")


def _is_loopback(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def validate_path_segment(value: str, label: str) -> str:
    """Return ``value`` when it is safe as one URL path segment, otherwise raise ``ValueError``."""

    if _PATH_SEGMENT.fullmatch(value) is None:
        raise ValueError(f"{label} is not a safe path segment")
    return value


def _segment(value: str, label: str) -> str:
    try:
        return quote(validate_path_segment(value, label), safe="")
    except ValueError as error:
        raise HubProtocolError(str(error)) from error


def _bounded_body(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > MAX_PLAN_RESPONSE_BYTES:
            raise HubProtocolError("Hub plan response exceeds the size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_plan_body(body: bytes) -> SignedPlan:
    try:
        document = load_json(body, label="Hub plan response")
    except ValueError as error:
        raise HubProtocolError("Hub plan response is not JSON") from error
    if not isinstance(document, dict) or set(document) != {"plan"}:
        raise HubProtocolError("Hub plan response MUST contain only a plan object")
    plan = document["plan"]
    if not isinstance(plan, dict) or set(plan) != {"signed_payload", "signature"}:
        raise HubProtocolError("Hub plan MUST contain only signed_payload and signature")
    return SignedPlan(
        signed_payload=_base64(plan["signed_payload"], "signed_payload"),
        signature=_base64(plan["signature"], "signature"),
    )


def _base64(value: object, label: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise HubProtocolError(f"Hub plan {label} MUST be a non-empty base64 string")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise HubProtocolError(f"Hub plan {label} is not valid base64") from error
