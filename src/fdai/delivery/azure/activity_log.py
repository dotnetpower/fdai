"""Azure Activity Log delta factory - turns forwarded Activity Log entries
into the :type:`~fdai.delivery.azure.inventory.ActivityLogFetchFn` seam the
:class:`~fdai.delivery.azure.inventory.AzureResourceGraphInventory` consumes
in :meth:`~fdai.delivery.azure.inventory.AzureResourceGraphInventory.delta`.

Design boundaries (identical discipline to
:mod:`fdai.delivery.azure.arg_query`)
-------------------------------------------------------------------

- ``core/`` never imports this module. It sits under ``delivery/azure/`` and
  is bound at the composition root through the
  :type:`~fdai.delivery.azure.inventory.ActivityLogFetchFn` seam.
- Identity flows through the injected
  :class:`~fdai.shared.providers.workload_identity.WorkloadIdentity`
  Protocol - no ``DefaultAzureCredential``, no ``azure-identity`` import.
- HTTP transport is an injected :class:`httpx.AsyncClient`. Tests pass a
  client backed by :class:`httpx.MockTransport`.
- The CSP-neutral ``resource_id`` is folded from the ARM id with the SAME
  :func:`~fdai.delivery.azure.arg_query._to_neutral_id` rule the full-scan
  uses, so a delta upsert lands on the exact ontology key the
  ``full_snapshot`` produced. The ARM ``resourceType`` is reverse-mapped
  to a CSP-neutral ``resource_type`` through the vocabulary; an event whose
  ARM type is not in the vocabulary is dropped rather than emitted with an
  unknown type.

Cursor model
------------

Azure Activity Log returns events newest-first and pages via a ``nextLink``.
:meth:`AzureResourceGraphInventory.delta` drives a bounded page loop, so
this fetch does exactly one page per call and encodes the running
newest-timestamp into the in-flight cursor:

- A **resume** cursor is a bare RFC 3339 timestamp (the lower bound of the
  next pull). An empty resume cursor starts at ``now - initial_lookback``.
- An **in-flight** cursor is ``"<running_max_iso>\x1f<next_link>"`` - the
  running newest timestamp carried across pages plus the ``nextLink`` to
  follow. When the last page has no ``nextLink``, the fetch returns the
  running newest timestamp as the next resume cursor.

Since Activity Log's ``eventTimestamp ge`` filter is inclusive, the
boundary event may re-appear on the next pull; idempotent upsert keys make
that a no-op.

Safety / cost invariants
------------------------

- **Fail-closed on partial**: a non-2xx response or malformed page raises
  :class:`ActivityLogError`; :meth:`delta` propagates it without the
  ``final=True`` fence, so the caller keeps the previous cursor.
- **Bounded record size**: the untrusted ``props`` map is truncated with
  the shared :func:`~fdai.delivery.azure.arg_query._truncate_props` helper.
- The overall page count per :meth:`delta` call is bounded by the
  inventory adapter's ``max_delta_pages`` cap.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from urllib.parse import urlparse

import httpx

from fdai.delivery.azure.arg_query import (
    _build_arm_to_neutral_map,
    _to_neutral_id,
    _truncate_props,
)
from fdai.delivery.azure.inventory import ActivityLogFetchFn, ActivityLogPage
from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ARG_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_ACTIVITY_LOG_API_VERSION: Final[str] = "2015-04-01"
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
_DEFAULT_MAX_PROPS_BYTES: Final[int] = 16 * 1024
_DEFAULT_INITIAL_LOOKBACK_SECONDS: Final[int] = 3600
_CURSOR_SEP: Final[str] = "\x1f"  # ASCII unit separator - never in a URL or RFC 3339 ts


class ActivityLogError(RuntimeError):
    """Raised when an Activity Log page fetch fails or returns unusable output.

    The message is safe to log - it never carries raw response bodies or
    tenant-identifying values, only the HTTP status and a short reason.
    """


@dataclass(frozen=True, slots=True)
class AzureActivityLogFactoryConfig:
    """Configuration for the Activity Log delta factory."""

    subscription_scope: str
    """The single subscription id the Activity Log query runs over. The
    delta path is single-scope by design; a multi-subscription fork binds
    one factory (and one delta stream) per subscription."""

    arg_endpoint: str = _DEFAULT_ARG_ENDPOINT
    api_version: str = _DEFAULT_ACTIVITY_LOG_API_VERSION
    audience: str = _DEFAULT_AUDIENCE
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_props_bytes: int = _DEFAULT_MAX_PROPS_BYTES
    initial_lookback_seconds: int = _DEFAULT_INITIAL_LOOKBACK_SECONDS
    only_succeeded: bool = True
    """When True (default), only ``status.value == 'Succeeded'`` events map
    to an upsert; ``Started`` / ``Failed`` entries are skipped so a failed
    or in-progress operation never mutates the ontology graph."""

    def __post_init__(self) -> None:
        if not self.subscription_scope:
            raise ValueError("AzureActivityLogFactoryConfig.subscription_scope MUST be non-empty")
        parsed_endpoint = urlparse(self.arg_endpoint)
        if parsed_endpoint.scheme != "https" or not parsed_endpoint.netloc:
            raise ValueError(
                "AzureActivityLogFactoryConfig.arg_endpoint MUST use https:// "
                "- the bearer token is sent on every request "
                f"(got {self.arg_endpoint!r})"
            )
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if self.max_props_bytes < 1024:
            raise ValueError("max_props_bytes MUST be >= 1024")
        if self.initial_lookback_seconds < 0:
            raise ValueError("initial_lookback_seconds MUST be >= 0")


class AzureActivityLogFactory:
    """Build an :type:`ActivityLogFetchFn` bound to a WorkloadIdentity + HTTP client."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        resource_types: ResourceTypeRegistry,
        http_client: httpx.AsyncClient,
        config: AzureActivityLogFactoryConfig,
    ) -> None:
        self._identity: Final[WorkloadIdentity] = identity
        self._http: Final[httpx.AsyncClient] = http_client
        self._config: Final[AzureActivityLogFactoryConfig] = config
        self._endpoint_host: Final[str] = urlparse(config.arg_endpoint).netloc.lower()
        # ARM type -> CSP-neutral resource_type reverse map, computed once.
        self._arm_to_neutral: Final[Mapping[str, str]] = _build_arm_to_neutral_map(resource_types)

    def build_fetch_fn(self) -> ActivityLogFetchFn:
        async def _fetch(cursor: str) -> ActivityLogPage:
            carried_max, next_link = _decode_cursor(cursor)
            if next_link is not None:
                request_url = next_link
            else:
                request_url = self._initial_url(resume_cursor=cursor)

            payload = await self._get(request_url)
            resources, page_max = self._map_events(payload)
            running_max = _max_dt(carried_max, page_max)

            link = payload.get("nextLink")
            if isinstance(link, str) and link:
                return ActivityLogPage(
                    resources=resources,
                    cursor=_encode_cursor(running_max, link),
                    has_more=True,
                )
            # Last page: hand back the running newest timestamp as the next
            # resume cursor (or echo the input cursor when no event was seen).
            resume = running_max.isoformat() if running_max is not None else (cursor or "")
            return ActivityLogPage(resources=resources, cursor=resume, has_more=False)

        return _fetch

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _initial_url(self, *, resume_cursor: str) -> str:
        start = resume_cursor.strip()
        if not start:
            since = datetime.now(tz=UTC) - timedelta(seconds=self._config.initial_lookback_seconds)
            start = _activity_log_timestamp(since)
        else:
            # Parse-and-canonicalize the persisted resume cursor rather than
            # trusting it verbatim: only a valid RFC 3339 timestamp is folded
            # into the OData ``$filter``, so a corrupt or hostile cursor
            # cannot smuggle filter syntax into the query.
            parsed = _parse_ts(start)
            if parsed is None:
                raise ActivityLogError("resume cursor is not a valid RFC 3339 timestamp")
            start = _activity_log_timestamp(parsed)
        flt = f"eventTimestamp ge '{start}'"
        return (
            f"{self._config.arg_endpoint.rstrip('/')}"
            f"/subscriptions/{self._config.subscription_scope}"
            "/providers/Microsoft.Insights/eventtypes/management/values"
            f"?api-version={self._config.api_version}"
            f"&$filter={flt}"
        )

    async def _get(self, url: str) -> Mapping[str, Any]:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc.lower() != self._endpoint_host:
            raise ActivityLogError("Activity Log nextLink changed scheme or host")
        token = await self._identity.get_token(self._config.audience)
        headers = {
            "Authorization": f"Bearer {token.token}",
            "Accept": "application/json",
        }
        try:
            response = await self._http.get(
                url, headers=headers, timeout=self._config.timeout_seconds
            )
        except httpx.HTTPError as exc:
            raise ActivityLogError(f"Activity Log request failed: {type(exc).__name__}") from exc

        if response.status_code >= 400:
            snippet = response.text[:200].replace("\n", " ")
            raise ActivityLogError(
                f"Activity Log returned HTTP {response.status_code}: {snippet!r}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ActivityLogError("Activity Log returned non-JSON") from exc
        if not isinstance(payload, Mapping):
            raise ActivityLogError("Activity Log payload is not an object")
        return payload

    def _map_events(
        self, payload: Mapping[str, Any]
    ) -> tuple[tuple[ResourceRecord, ...], datetime | None]:
        events = payload.get("value")
        if not isinstance(events, list):
            raise ActivityLogError("Activity Log payload missing 'value' array")

        # Dedupe within the page by neutral resource id, keeping the newest
        # event so a resource written twice in one page upserts once.
        by_id: dict[str, tuple[datetime, ResourceRecord]] = {}
        page_max: datetime | None = None
        for event in events:
            if not isinstance(event, Mapping):
                continue
            mapped = self._map_one(event)
            if mapped is None:
                continue
            at, record = mapped
            page_max = _max_dt(page_max, at)
            prior = by_id.get(record.resource_id)
            if prior is None or at >= prior[0]:
                by_id[record.resource_id] = (at, record)

        resources = tuple(rec for _, rec in by_id.values())
        return resources, page_max

    def _map_one(self, event: Mapping[str, Any]) -> tuple[datetime, ResourceRecord] | None:
        if self._config.only_succeeded and _nested_value(event, "status") != "Succeeded":
            return None

        arm_id = event.get("resourceId")
        if not isinstance(arm_id, str) or not arm_id:
            return None

        arm_type = _nested_value(event, "resourceType") or _arm_type_from_id(arm_id)
        if not arm_type:
            return None
        neutral_type = self._arm_to_neutral.get(arm_type.lower())
        if neutral_type is None:
            # Not a vocabulary type the full-scan tracks - drop it rather
            # than emit an unknown type into the ontology.
            return None

        at = _parse_ts(event.get("eventTimestamp"))
        if at is None:
            return None

        props = _truncate_props(
            {
                "operation": _nested_value(event, "operationName"),
                "status": _nested_value(event, "status"),
                "caller": event.get("caller"),
                "eventTimestamp": event.get("eventTimestamp"),
            },
            max_bytes=self._config.max_props_bytes,
        )
        record = ResourceRecord(
            resource_id=_to_neutral_id(arm_id),
            type=neutral_type,
            props=props,
            provider_ref=arm_id,
            last_seen=at.isoformat(),
        )
        return at, record


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _activity_log_timestamp(value: datetime) -> str:
    """Serialize an Activity Log filter timestamp in Azure's accepted UTC form."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _decode_cursor(cursor: str) -> tuple[datetime | None, str | None]:
    """Split an in-flight cursor into (running_max, next_link).

    A resume cursor (no separator) returns ``(None, None)`` - the caller
    treats it as a lower-bound timestamp and builds the initial query.
    """
    if _CURSOR_SEP not in cursor:
        return None, None
    max_part, _, url = cursor.partition(_CURSOR_SEP)
    return _parse_ts(max_part), (url or None)


def _encode_cursor(running_max: datetime | None, next_link: str) -> str:
    max_iso = running_max.isoformat() if running_max is not None else ""
    return f"{max_iso}{_CURSOR_SEP}{next_link}"


def _max_dt(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


def _parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    text = raw.strip().replace("Z", "+00:00") if raw.endswith("Z") else raw.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _nested_value(event: Mapping[str, Any], key: str) -> str | None:
    """Activity Log wraps enum-ish fields as ``{"value": ..., "localizedValue": ...}``."""
    raw = event.get(key)
    if isinstance(raw, Mapping):
        value = raw.get("value")
        return str(value) if value is not None else None
    if isinstance(raw, str) and raw:
        return raw
    return None


def _arm_type_from_id(arm_id: str) -> str | None:
    """Best-effort provider/type extraction from an ARM id when the event
    omits ``resourceType`` (rare). Returns e.g.
    ``Microsoft.Compute/virtualMachines`` from
    ``/subscriptions/.../providers/Microsoft.Compute/virtualMachines/vm-a``.
    """
    marker = "/providers/"
    idx = arm_id.lower().rfind(marker.lower())
    if idx == -1:
        return None
    tail = arm_id[idx + len(marker) :].split("/")
    if len(tail) < 2:
        return None
    return f"{tail[0]}/{tail[1]}"


__all__ = [
    "ActivityLogError",
    "AzureActivityLogFactory",
    "AzureActivityLogFactoryConfig",
]
