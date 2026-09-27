"""Present machine-owned answer values in operator-readable, localized words.

Answers keep every machine token that a reviewer or test relies on, such as the explicit
no-authority marker, but pair it with ordinary language. Provider status values and ISO
instants are rendered for reading; the technical details retain the exact source values.
"""

from __future__ import annotations

from datetime import UTC, datetime

_STATUS_LABELS: dict[str, tuple[str, str]] = {
    "creating": ("생성 중", "Creating"),
    "deallocated": ("할당 해제됨", "Deallocated"),
    "deallocating": ("할당 해제 중", "Deallocating"),
    "deleting": ("삭제 중", "Deleting"),
    "failed": ("실패", "Failed"),
    "paused": ("일시 중지됨", "Paused"),
    "ready": ("준비됨", "Ready"),
    "running": ("실행 중", "Running"),
    "starting": ("시작 중", "Starting"),
    "stopped": ("중지됨", "Stopped"),
    "stopping": ("중지 중", "Stopping"),
    "succeeded": ("성공", "Succeeded"),
    "updating": ("업데이트 중", "Updating"),
}


def authority_line(*, korean: bool) -> str:
    """State the read-only, no-execution boundary with its machine marker."""

    return (
        "읽기 전용 결과이며 실행 권한이 없습니다 (`execution_authority=false`)."
        if korean
        else "This read-only result grants no execution authority (`execution_authority=false`)."
    )


def completeness_text(complete: bool, *, korean: bool) -> str:
    """Name source completeness in the answer language."""

    if korean:
        return "완전" if complete else "불완전"
    return "complete" if complete else "incomplete"


def readable_timestamp(value: str) -> str:
    """Render a timezone-aware ISO-8601 instant as UTC seconds; other text is unchanged."""

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        return value
    return parsed.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def readable_resource_status(value: str, *, korean: bool) -> str:
    """Name a provider lifecycle status in operator words; an unknown value stays verbatim."""

    label = _STATUS_LABELS.get(value.rsplit("/", 1)[-1].strip().casefold())
    if label is None:
        return value
    return label[0] if korean else label[1]


__all__ = [
    "authority_line",
    "completeness_text",
    "readable_resource_status",
    "readable_timestamp",
]
