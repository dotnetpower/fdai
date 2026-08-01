"""Deterministic pre-incident deployment and configuration activity answers."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

ScopeActivityProvider = Callable[[int, int], Awaitable[Mapping[str, object]]]

_CANONICAL: Final = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_.()-]{1,127}) change history: "
    r"pre-incident activity "
    r"group=(?P<group>[A-Za-z0-9][A-Za-z0-9_.()-]{1,127}) "
    r"before=(?P<before>\S{1,64}) locale=(?P<locale>en|ko)$"
)
_RELEVANT_OPERATION: Final = re.compile(r"deployment|write|update|configuration", re.IGNORECASE)
_LOOKBACK_SECONDS: Final = 24 * 3_600
_IMMEDIATE_WINDOW: Final = timedelta(hours=1)
_MAX_EVENTS: Final = 200
_MAX_RENDERED: Final = 20
_SOURCE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


@dataclass(frozen=True, slots=True)
class PreIncidentActivityRequest:
    resource_name: str
    resource_group: str
    before_at: datetime
    locale: str


def parse_preincident_activity(question: str) -> PreIncidentActivityRequest | None:
    """Parse only the server-generated canonical pre-incident request."""

    match = _CANONICAL.fullmatch(" ".join(question.split()))
    if match is None:
        return None
    try:
        before_at = datetime.fromisoformat(match.group("before").replace("Z", "+00:00"))
    except ValueError:
        return None
    if before_at.tzinfo is None:
        return None
    return PreIncidentActivityRequest(
        resource_name=match.group("name"),
        resource_group=match.group("group"),
        before_at=before_at.astimezone(UTC),
        locale=match.group("locale"),
    )


async def resolve_preincident_activity(
    request: PreIncidentActivityRequest,
    provider: ScopeActivityProvider,
) -> dict[str, object]:
    """Read bounded scope activity and render changes before the verified incident anchor."""

    try:
        payload = dict(await provider(_LOOKBACK_SECONDS, _MAX_EVENTS))
    except Exception as exc:  # noqa: BLE001 - provider boundary fails closed
        return _unavailable(request, type(exc).__name__)
    raw_events = payload.get("events")
    if payload.get("status") != "matched" or not isinstance(raw_events, (list, tuple)):
        return _unavailable(request, str(payload.get("reason") or "activity_provider_unavailable"))

    relevant: list[dict[str, str]] = []
    for raw in raw_events[:_MAX_EVENTS]:
        event = _event_before_anchor(raw, request)
        if event is not None:
            relevant.append(event)
    relevant.sort(key=lambda event: event["occurred_at"], reverse=True)
    immediate_start = request.before_at - _IMMEDIATE_WINDOW
    immediate = [
        event
        for event in relevant
        if datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00")) >= immediate_start
    ]
    source = str(payload.get("source") or "azure-activity-log")
    observed_at = str(payload.get("observed_at") or "")
    if _SOURCE.fullmatch(source) is None or _aware_timestamp(observed_at) is None:
        return _unavailable(request, "activity_provenance_invalid")
    truncated = (
        bool(payload.get("truncated"))
        or len(raw_events) > _MAX_EVENTS
        or len(relevant) > _MAX_RENDERED
    )
    evidence_ref = f"activity:{source}@{observed_at}"
    answer = _render(
        request,
        immediate=immediate,
        nearest=relevant[:_MAX_RENDERED],
        source=source,
        observed_at=observed_at,
        truncated=truncated,
    )
    return {
        "answer": answer,
        "facts": {
            "status": "matched",
            "intent": "pre_incident_changes",
            "resource_name": request.resource_name,
            "resource_group": request.resource_group,
            "before_at": request.before_at.isoformat().replace("+00:00", "Z"),
            "immediate_count": len(immediate),
            "matched_count": len(relevant),
            "truncated": truncated,
            "evidence_refs": (evidence_ref,),
            "evidence_sources": (source,),
        },
    }


def _event_before_anchor(
    raw: object,
    request: PreIncidentActivityRequest,
) -> dict[str, str] | None:
    if not isinstance(raw, Mapping):
        return None
    resource_group = str(raw.get("resource_group") or "")
    operation = _bounded_display(raw.get("operation"), fallback="unknown", max_chars=256)
    event_status = str(raw.get("event_status") or raw.get("status") or "")
    occurred_at = str(raw.get("occurred_at") or "")
    if (
        resource_group.casefold() != request.resource_group.casefold()
        or _RELEVANT_OPERATION.search(operation) is None
        or event_status.casefold() not in {"succeeded", "success"}
    ):
        return None
    occurred = _aware_timestamp(occurred_at)
    if occurred is None:
        return None
    if occurred >= request.before_at or occurred < request.before_at - timedelta(
        seconds=_LOOKBACK_SECONDS
    ):
        return None
    return {
        "occurred_at": occurred.isoformat().replace("+00:00", "Z"),
        "name": _bounded_display(
            raw.get("name") or raw.get("resource_name"),
            fallback="unknown",
            max_chars=128,
        ),
        "type": _bounded_display(
            raw.get("type") or raw.get("resource_type"),
            fallback="arm-resource",
            max_chars=128,
        ),
        "operation": operation,
    }


def _render(
    request: PreIncidentActivityRequest,
    *,
    immediate: Sequence[Mapping[str, str]],
    nearest: Sequence[Mapping[str, str]],
    source: str,
    observed_at: str,
    truncated: bool,
) -> str:
    korean = request.locale == "ko"
    anchor = request.before_at.isoformat().replace("+00:00", "Z")
    if korean:
        lines = [f"장애 기준 시각 {anchor} 직전 1시간의 배포/설정 변경은 {len(immediate)}건입니다."]
        if not immediate:
            lines.append("- 직전 1시간에는 일치하는 배포 또는 설정 write가 관찰되지 않았습니다.")
            if nearest:
                lines.append("가장 가까운 이전 관련 변경:")
        lines.extend(_line(event, korean=True) for event in (immediate[:_MAX_RENDERED] or nearest))
        lines.append(f"근거: {source}, 관찰 시각 {observed_at}.")
        if truncated:
            lines.append("Activity Log 결과가 잘렸으므로 더 이른 관련 변경이 있을 수 있습니다.")
        return "\n".join(lines)
    lines = [
        f"Found {len(immediate)} deployment or configuration change(s) in the hour before "
        f"the incident anchor {anchor}."
    ]
    if not immediate:
        lines.append("- No matching deployment or configuration write was observed in that hour.")
        if nearest:
            lines.append("Nearest earlier relevant changes:")
    lines.extend(_line(event, korean=False) for event in (immediate[:_MAX_RENDERED] or nearest))
    lines.append(f"Evidence: {source}, observed {observed_at}.")
    if truncated:
        lines.append("The Activity Log result is truncated; earlier relevant changes may exist.")
    return "\n".join(lines)


def _line(event: Mapping[str, str], *, korean: bool) -> str:
    label = "변경" if korean else "Change"
    return (
        f"- {label} {event['occurred_at']} {event['name']}: {event['type']}, {event['operation']}"
    )


def _aware_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _bounded_display(value: object, *, fallback: str, max_chars: int) -> str:
    normalized = " ".join(str(value or fallback).split())
    printable = "".join(character for character in normalized if character.isprintable())
    return (printable or fallback)[:max_chars]


def _unavailable(request: PreIncidentActivityRequest, reason: str) -> dict[str, object]:
    answer = (
        "Azure Activity Log 근거를 사용할 수 없어 장애 직전 변경을 확정하지 않았습니다."
        if request.locale == "ko"
        else (
            "Azure Activity Log evidence is unavailable, so pre-incident changes were "
            "not confirmed."
        )
    )
    return {
        "answer": answer,
        "facts": {
            "status": "unavailable",
            "intent": "pre_incident_changes",
            "resource_name": request.resource_name,
            "reason": reason[:128],
            "evidence_refs": (),
            "evidence_sources": (),
        },
    }


__all__ = [
    "PreIncidentActivityRequest",
    "ScopeActivityProvider",
    "parse_preincident_activity",
    "resolve_preincident_activity",
]
