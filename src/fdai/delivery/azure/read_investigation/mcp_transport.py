"""Optional Azure MCP transport with immediate typed-provider fallback."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime

from fdai.delivery.azure.read_investigation.transport import AzureReadTransport, AzureRow
from fdai.delivery.mcp import ManagedMcpClient, McpCallResult
from fdai.shared.providers.read_investigation import ReadToolLimits, ResourceSelector

_STATE_TOOL = "compute"
_ACTIVITY_TOOL = "monitor"
_HEALTH_TOOL = "resourcehealth"
AZURE_MCP_READ_TOOLS = frozenset({_STATE_TOOL, _ACTIVITY_TOOL, _HEALTH_TOOL})


class AzureMcpReadTransport:
    """Use Azure MCP only for mapped reads and preserve the REST authority path."""

    transport_id = "mcp+rest"

    def __init__(
        self,
        *,
        client: ManagedMcpClient,
        fallback: AzureReadTransport,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._fallback = fallback
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def resolve_resources(
        self,
        selector: ResourceSelector,
        *,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        return await self._fallback.resolve_resources(selector, limits=limits)

    async def get_resource_state(
        self,
        provider_ref: str,
        *,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        group, name = _vm_parts(provider_ref)
        return await self._call_or_fallback(
            tool_name=_STATE_TOOL,
            arguments={
                "intent": "Get the current state of one resolved Azure virtual machine.",
                "command": "compute_vm_get",
                "parameters": {
                    "resource-group": group,
                    "vm-name": name,
                    "instance-view": True,
                },
            },
            limits=limits,
            decode=lambda result: _state_rows(result, observed_at=self._clock()),
            fallback=lambda: self._fallback.get_resource_state(provider_ref, limits=limits),
        )

    async def query_resource_activity(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        hours = max(1, min(720, (lookback_seconds + 3_599) // 3_600))
        return await self._call_or_fallback(
            tool_name=_ACTIVITY_TOOL,
            arguments={
                "intent": "List bounded activity for one resolved Azure resource.",
                "command": "monitor_activitylog_list",
                "parameters": {"resource-id": provider_ref, "hours": hours},
            },
            limits=limits,
            decode=lambda result: _activity_rows(result, provider_ref=provider_ref),
            fallback=lambda: self._fallback.query_resource_activity(
                provider_ref,
                lookback_seconds=lookback_seconds,
                limits=limits,
            ),
        )

    async def query_resource_health(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        return await self._call_or_fallback(
            tool_name=_HEALTH_TOOL,
            arguments={
                "intent": "Get availability status for one resolved Azure resource.",
                "command": "resourcehealth_availability-status_get",
                "parameters": {"resource-id": provider_ref},
            },
            limits=limits,
            decode=lambda result: _health_rows(result, observed_at=self._clock()),
            fallback=lambda: self._fallback.query_resource_health(
                provider_ref,
                lookback_seconds=lookback_seconds,
                limits=limits,
            ),
        )

    async def query_guest_shutdown_events(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        return await self._fallback.query_guest_shutdown_events(
            provider_ref,
            lookback_seconds=lookback_seconds,
            limits=limits,
        )

    async def query_network_security(
        self,
        provider_ref: str,
        *,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        return await self._fallback.query_network_security(provider_ref, limits=limits)

    async def query_network_peerings(
        self,
        provider_ref: str,
        *,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        return await self._fallback.query_network_peerings(provider_ref, limits=limits)

    async def _call_or_fallback(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, object],
        limits: ReadToolLimits,
        decode: Callable[[McpCallResult], Sequence[AzureRow]],
        fallback: Callable[[], Awaitable[Sequence[AzureRow]]],
    ) -> Sequence[AzureRow]:
        if not self._client.is_routable:
            return await fallback()
        try:
            result = await self._client.call_tool(
                tool_name,
                arguments,
                timeout_seconds=min(limits.timeout_seconds, 15.0),
            )
            _enforce_result_cap(result, limits.max_output_bytes)
            if result.is_error:
                raise ValueError("Azure MCP tool reported an error")
            return decode(result)
        except Exception:  # noqa: BLE001 - optional MCP failure preserves typed authority
            if self._client.is_routable:
                self._client.reject_result()
            return await fallback()


def _vm_parts(provider_ref: str) -> tuple[str, str]:
    parts = provider_ref.strip("/").split("/")
    lowered = [part.casefold() for part in parts]
    try:
        group_index = lowered.index("resourcegroups") + 1
        provider_index = lowered.index("providers")
    except ValueError as exc:
        raise ValueError("resolved VM reference is not an Azure resource ID") from exc
    if (
        group_index >= provider_index
        or provider_index + 4 != len(parts)
        or parts[provider_index + 1].casefold() != "microsoft.compute"
        or parts[provider_index + 2].casefold() != "virtualmachines"
        or not parts[group_index]
        or not parts[provider_index + 3]
    ):
        raise ValueError("resolved resource is not an Azure virtual machine")
    return parts[group_index], parts[provider_index + 3]


def _enforce_result_cap(result: McpCallResult, maximum: int) -> None:
    material = {
        "structured_content": result.structured_content,
        "content": [getattr(item, "text", "") for item in result.content],
    }
    try:
        size = len(json.dumps(material, default=str).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Azure MCP result was not serializable") from exc
    if size > maximum:
        raise ValueError("Azure MCP result exceeded the read-tool output cap")


def _payload(result: McpCallResult) -> object:
    if result.structured_content is not None:
        return result.structured_content
    text = "".join(
        value for item in result.content if isinstance(value := getattr(item, "text", None), str)
    ).strip()
    if not text:
        raise ValueError("Azure MCP result contained no structured data")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Azure MCP result text was not JSON") from exc


def _results(result: McpCallResult) -> object:
    payload = _payload(result)
    if isinstance(payload, Mapping) and "results" in payload:
        return payload["results"]
    return payload


def _state_rows(result: McpCallResult, *, observed_at: datetime) -> Sequence[AzureRow]:
    payload = _results(result)
    state = _find_state(payload)
    if state is None:
        raise ValueError("Azure MCP VM result omitted power state")
    return ({"observed_at": observed_at.isoformat(), "status": "ok", "state": state},)


def _find_state(value: object) -> str | None:
    pending = [value]
    visited = 0
    while pending:
        current = pending.pop()
        visited += 1
        if visited > 2_048:
            raise ValueError("Azure MCP VM result exceeded the traversal cap")
        if isinstance(current, Mapping):
            for key in ("powerState", "power_state", "powerstate", "state"):
                candidate = current.get(key)
                if isinstance(candidate, str) and candidate:
                    return candidate.rsplit("/", 1)[-1]
            statuses = current.get("statuses")
            if isinstance(statuses, Sequence) and not isinstance(statuses, (str, bytes)):
                for status in statuses:
                    if isinstance(status, Mapping):
                        code = status.get("code")
                        if isinstance(code, str) and code.casefold().startswith("powerstate/"):
                            return code.rsplit("/", 1)[-1]
            pending.extend(current.values())
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
            pending.extend(current)
    return None


def _activity_rows(result: McpCallResult, *, provider_ref: str) -> Sequence[AzureRow]:
    payload = _results(result)
    items = _records(payload)
    rows: list[AzureRow] = []
    for item in items:
        resource_ref = _text(item, "resourceId", "resource_id", "resourceUri", "resource_uri")
        if resource_ref is not None and resource_ref.casefold() != provider_ref.casefold():
            raise ValueError("Azure MCP activity result widened the resolved resource")
        occurred_at = _timestamp_text(
            item,
            "eventTimestamp",
            "event_timestamp",
            "occurred_at",
        )
        operation = _localized(item.get("operationName") or item.get("operation"))
        status = _localized(item.get("status")) or "unknown"
        if occurred_at is None or operation is None:
            continue
        rows.append(
            {
                "occurred_at": occurred_at,
                "status": status,
                "operation": operation,
                "caller": _text(item, "caller"),
                "correlation": _text(item, "correlationId", "correlation_id"),
            }
        )
    return rows


def _health_rows(result: McpCallResult, *, observed_at: datetime) -> Sequence[AzureRow]:
    payload = _results(result)
    items = _records(payload, allow_singleton=True)
    rows: list[AzureRow] = []
    for item in items or (() if not isinstance(payload, Mapping) else (payload,)):
        properties = item.get("properties")
        source = properties if isinstance(properties, Mapping) else item
        status = _text(source, "availabilityState", "availability_state", "status")
        if status is None:
            continue
        rows.append(
            {
                "occurred_at": _timestamp_text(source, "occurredTime", "occurred_at")
                or observed_at.isoformat(),
                "status": status,
                "health_kind": _text(source, "reasonType", "reason_type") or "unknown",
            }
        )
    if not rows:
        raise ValueError("Azure MCP Resource Health result omitted availability state")
    return rows


def _records(
    value: object,
    *,
    allow_singleton: bool = False,
) -> tuple[Mapping[str, object], ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if any(not isinstance(item, Mapping) for item in value):
            raise ValueError("Azure MCP result contained a malformed record")
        return tuple(item for item in value if isinstance(item, Mapping))
    if isinstance(value, Mapping):
        for key in ("value", "items", "events", "data"):
            if key not in value:
                continue
            nested = value.get(key)
            if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
                if any(not isinstance(item, Mapping) for item in nested):
                    raise ValueError("Azure MCP result contained a malformed record")
                return tuple(item for item in nested if isinstance(item, Mapping))
            raise ValueError("Azure MCP result record container was not an array")
        if allow_singleton:
            return ()
    raise ValueError("Azure MCP result omitted its record container")


def _text(value: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _timestamp_text(value: Mapping[str, object], *keys: str) -> str | None:
    candidate = _text(value, *keys)
    if candidate is None:
        return None
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Azure MCP result contained an invalid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Azure MCP result timestamp MUST include a timezone")
    return parsed.isoformat()


def _localized(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, Mapping):
        return _text(value, "value", "localizedValue", "localized_value")
    return None


__all__ = ["AZURE_MCP_READ_TOOLS", "AzureMcpReadTransport"]
