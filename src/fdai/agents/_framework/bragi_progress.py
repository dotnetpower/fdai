"""Bounded typed-pipeline progress projection for Bragi."""

from __future__ import annotations

from typing import Any


def record_progress(
    progress: dict[str, list[dict[str, Any]]],
    topic: str,
    payload: dict[str, Any],
    *,
    max_keys: int,
    max_steps: int,
) -> None:
    if topic not in ("object.verdict", "object.action-run"):
        return
    correlation_id = str(payload.get("correlation_id", ""))
    if not correlation_id:
        return
    entry = {
        "topic": topic,
        "state": payload.get("state") or payload.get("risk_verdict"),
        "action_type": payload.get("action_type"),
        "outcome": payload.get("outcome"),
    }
    steps = progress.setdefault(correlation_id, [])
    if steps and steps[-1] == entry:
        return
    steps.append(entry)
    if len(steps) > max_steps:
        del steps[:-max_steps]
    evict_oldest(progress, max_keys, keep=correlation_id)


def append_submitted(
    progress: dict[str, list[dict[str, Any]]],
    correlation_id: str,
    action_type: str,
    *,
    max_keys: int,
) -> None:
    progress.setdefault(correlation_id, []).append(
        {"topic": "object.conversation", "state": "submitted", "action_type": action_type}
    )
    evict_oldest(progress, max_keys, keep=correlation_id)


def evict_oldest(mapping: dict[str, Any], cap: int, *, keep: str | None = None) -> None:
    while len(mapping) > cap:
        for key in mapping:
            if key != keep:
                del mapping[key]
                break
        else:
            break


__all__ = ["append_submitted", "evict_oldest", "record_progress"]
