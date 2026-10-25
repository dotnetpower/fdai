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
  Every outcome except ``rejected`` carries it. An applying agent reports ``apply-started`` right
  before the change and ``applied`` or ``rolled-back`` with the next attempt.
* ``POST /v1/installations/{installation_id}/state`` takes a reported-state snapshot and returns
  ``202``, ``409 stale_state`` when its ``observed_at`` isn't newer, ``422 state_invalid``, or
  ``404``. ``503 concurrent_write`` is retried as for reports.

* ``POST /v1/installations/{installation_id}/enrollment-request`` takes the signed enrollment
  ``{"signed_payload", "proof"}`` and returns ``202`` for a pending request, ``409
  installation_exists`` when any record exists, ``403`` for a refused identity or proof, and
  ``422``. It never approves; only ``503 concurrent_write`` is resent.

The client only moves bytes. It never trusts a Plan; admission decides that.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Literal, Protocol, Self
from urllib.parse import quote, urlsplit

import httpx
from fdai_deployment_cli.lifecycle_native import SignedNativeScope

from fdai_lifecycle_agent.strict_json import load_json

type ReportOutcome = Literal[
    "dry-run-admitted", "rejected", "apply-started", "applied", "rolled-back"
]
type ArtifactKind = Literal["release", "configuration"]

MAX_PLAN_RESPONSE_BYTES = 256 * 1024
MAX_ARTIFACT_RESPONSE_BYTES = 2 * 1024 * 1024
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


@dataclass(frozen=True, slots=True)
class FetchedArtifact:
    """Raw signed artifact bytes returned by the current Plan's Hub boundary."""

    payload: bytes
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
        if self.outcome != "rejected" and self.exact_plan_digest is None:
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

    def submit_state(self, installation_id: str, snapshot: Mapping[str, object]) -> None:
        """Deliver one state snapshot; raise ``HubProtocolError`` unless the Hub accepted it."""
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
        authorization: Callable[[], str] | None = None,
    ) -> None:
        self._base_url = validate_hub_url(base_url)
        if authorization is not None and urlsplit(self._base_url).scheme != "https":
            raise ValueError("Authenticated Hub transport requires HTTPS.")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Hub timeout MUST be positive and finite.")
        self._authorization = authorization
        self._timeout_seconds = timeout_seconds
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
            headers = self._headers()
            deadline = time.monotonic() + self._timeout_seconds
            with self._client.stream("GET", path, headers=headers) as response:
                if response.status_code == 204:
                    return None
                if response.status_code == 404:
                    raise HubProtocolError("Hub does not know this installation (404)")
                if response.status_code != 200:
                    raise HubProtocolError(f"Hub plan request returned {response.status_code}")
                body = _bounded_body(response, deadline=deadline)
        except httpx.HTTPError as error:
            raise HubProtocolError(f"Hub plan request failed: {type(error).__name__}") from error
        return _parse_plan_body(body)

    def submit_report(self, installation_id: str, plan_id: str, report: PlanReport) -> None:
        path = (
            f"/v1/installations/{_segment(installation_id, 'installation_id')}"
            f"/plans/{_segment(plan_id, 'plan_id')}/reports"
        )
        self._post(path, report.to_json(), label="report")

    def submit_state(self, installation_id: str, snapshot: Mapping[str, object]) -> None:
        path = f"/v1/installations/{_segment(installation_id, 'installation_id')}/state"
        self._post(path, snapshot, label="state")

    def submit_native_proof(self, installation_id: str, proof: SignedNativeScope) -> None:
        if proof.claim.installation_id != installation_id:
            raise ValueError("Native proof installation binding does not match.")
        path = f"/v1/installations/{_segment(installation_id, 'installation_id')}/native-proofs"
        self._post(path, proof.model_dump(mode="json"), label="native proof")

    def submit_enrollment_request(
        self, installation_id: str, signed_payload: bytes, proof: bytes
    ) -> None:
        """Propose a pending enrollment; the Hub never decides it here, and 409 means it exists."""

        path = (
            f"/v1/installations/{_segment(installation_id, 'installation_id')}/enrollment-request"
        )
        body = {
            "signed_payload": base64.b64encode(signed_payload).decode("ascii"),
            "proof": base64.b64encode(proof).decode("ascii"),
        }
        self._post(path, body, label="enrollment")

    def fetch_artifact(
        self,
        installation_id: str,
        kind: ArtifactKind,
        digest: str,
    ) -> FetchedArtifact | None:
        if (
            kind not in ("release", "configuration")
            or re.fullmatch(r"[0-9a-f]{64}", digest, re.ASCII) is None
        ):
            raise ValueError("Hub artifact kind or digest is invalid.")
        path = (
            f"/v1/installations/{_segment(installation_id, 'installation_id')}"
            f"/artifacts/{kind}/{digest}"
        )
        try:
            headers = self._headers()
            deadline = time.monotonic() + self._timeout_seconds
            with self._client.stream("GET", path, headers=headers) as response:
                if response.status_code == 404:
                    return None
                if response.status_code != 200:
                    raise HubProtocolError(f"Hub artifact request returned {response.status_code}")
                body = _bounded_body(
                    response,
                    deadline=deadline,
                    maximum=MAX_ARTIFACT_RESPONSE_BYTES,
                )
        except httpx.HTTPError as error:
            raise HubProtocolError(
                f"Hub artifact request failed: {type(error).__name__}"
            ) from error
        try:
            document = load_json(body, label="Hub artifact response")
        except ValueError as error:
            raise HubProtocolError("Hub artifact response is not JSON") from error
        if (
            not isinstance(document, dict)
            or set(document) != {"kind", "digest", "payload", "signature"}
            or document["kind"] != kind
            or document["digest"] != digest
        ):
            raise HubProtocolError("Hub artifact response identity differs")
        return FetchedArtifact(
            payload=_base64(document["payload"], "payload"),
            signature=_base64(document["signature"], "signature"),
        )

    def _post(self, path: str, body: Mapping[str, object], *, label: str) -> None:
        """POST ``body``; resend it after ``503 concurrent_write``, otherwise raise unless 202."""

        for retry in range(MAX_CONCURRENT_WRITE_RETRIES + 1):
            try:
                headers = self._headers()
                deadline = time.monotonic() + self._timeout_seconds
                with self._client.stream("POST", path, json=body, headers=headers) as stream:
                    response_headers = stream.headers.copy()
                    # iter_bytes() already decodes the content encoding.
                    response_headers.pop("content-encoding", None)
                    response_headers.pop("content-length", None)
                    response = httpx.Response(
                        stream.status_code,
                        headers=response_headers,
                        content=_bounded_body(stream, deadline=deadline),
                    )
            except httpx.HTTPError as error:
                raise HubProtocolError(
                    f"Hub {label} request failed: {type(error).__name__}"
                ) from error
            if response.status_code == 202:
                return
            concurrent_write = (
                response.status_code == 503 and _error_code(response) == "concurrent_write"
            )
            if not concurrent_write or retry == MAX_CONCURRENT_WRITE_RETRIES:
                break
            self._sleep(_retry_after(response))
        code = _error_code(response)
        raise HubProtocolError(
            f"Hub {label} request returned {response.status_code} {code}".rstrip(), code=code
        )

    def _headers(self) -> dict[str, str]:
        if self._authorization is None:
            return {}
        token = self._authorization()
        if not token or any(character.isspace() for character in token):
            raise HubProtocolError("Hub credential returned an invalid access token.")
        return {"Authorization": f"Bearer {token}"}


def _retry_after(response: httpx.Response) -> float:
    try:
        seconds = float(response.headers.get("Retry-After", "1"))
    except ValueError:
        seconds = 1.0
    if not math.isfinite(seconds):
        raise HubProtocolError("Hub Retry-After MUST be finite.")
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
    if (
        parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.path not in ("", "/")
    ):
        raise ValueError(
            "Hub URL MUST be an origin without credentials, a path, query, or fragment"
        )
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


def _bounded_body(
    response: httpx.Response,
    *,
    deadline: float,
    maximum: int = MAX_PLAN_RESPONSE_BYTES,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        if time.monotonic() >= deadline:
            raise HubProtocolError("Hub response exceeded the request deadline.")
        total += len(chunk)
        if total > maximum:
            raise HubProtocolError("Hub response exceeds the size limit")
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
