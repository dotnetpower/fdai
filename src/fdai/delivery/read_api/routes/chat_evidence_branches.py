"""Bounded concurrent read-evidence branches for progressive operator chat."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

MAX_EVIDENCE_BRANCHES = 4
DEFAULT_EVIDENCE_BRANCH_TIMEOUT_SECONDS = 30.0

_LOG = logging.getLogger(__name__)

BranchProgressObserver = Callable[[Mapping[str, Any]], Awaitable[None]]
BranchResolver = Callable[[BranchProgressObserver], Awaitable[dict[str, Any]]]


class EvidenceBranchKind(StrEnum):
    TOOL = "tool"
    OPERATIONAL = "operational"
    AGENT = "agent"
    PUBLIC_WEB = "public_web"


class EvidenceBranchStatus(StrEnum):
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class EvidenceBranchSpec:
    kind: EvidenceBranchKind
    resolve: BranchResolver
    evidence_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceBranchResult:
    kind: EvidenceBranchKind
    status: EvidenceBranchStatus
    context: Mapping[str, Any]
    duration_ms: int


async def resolve_evidence_branches(
    *,
    request_id: str,
    base_context: Mapping[str, Any],
    specs: Sequence[EvidenceBranchSpec],
    progress_observer: BranchProgressObserver,
    timeout_seconds: float = DEFAULT_EVIDENCE_BRANCH_TIMEOUT_SECONDS,
) -> tuple[EvidenceBranchResult, ...]:
    """Resolve independent snapshots concurrently and return canonical spec order."""

    if not 0 < len(specs) <= MAX_EVIDENCE_BRANCHES:
        raise ValueError(f"evidence branch count MUST be between 1 and {MAX_EVIDENCE_BRANCHES}")
    if timeout_seconds <= 0:
        raise ValueError("evidence branch timeout MUST be positive")
    kinds = [spec.kind for spec in specs]
    if len(kinds) != len(set(kinds)):
        raise ValueError("evidence branch kinds MUST be distinct")

    async with asyncio.TaskGroup() as task_group:
        tasks = [
            task_group.create_task(
                _resolve_branch(
                    request_id=request_id,
                    base_context=base_context,
                    spec=spec,
                    progress_observer=progress_observer,
                    timeout_seconds=timeout_seconds,
                )
            )
            for spec in specs
        ]
    return tuple(task.result() for task in tasks)


async def _resolve_branch(
    *,
    request_id: str,
    base_context: Mapping[str, Any],
    spec: EvidenceBranchSpec,
    progress_observer: BranchProgressObserver,
    timeout_seconds: float,
) -> EvidenceBranchResult:
    branch_id = f"{request_id}:{spec.kind.value}"
    started_at = datetime.now(tz=UTC)
    started = time.monotonic()
    await progress_observer(
        _lifecycle_event(
            branch_id=branch_id,
            kind=spec.kind,
            status="running",
            summary=f"Checking {spec.kind.value} evidence",
            started_at=started_at,
        )
    )

    async def observe_branch_progress(event: Mapping[str, Any]) -> None:
        enriched = dict(event)
        enriched["branch_id"] = branch_id
        enriched["branch_kind"] = spec.kind.value
        await progress_observer(enriched)

    try:
        async with asyncio.timeout(timeout_seconds):
            context = await spec.resolve(observe_branch_progress)
    except TimeoutError:
        return await _terminal_result(
            branch_id=branch_id,
            kind=spec.kind,
            status=EvidenceBranchStatus.TIMED_OUT,
            summary=f"{spec.kind.value} evidence timed out",
            context=base_context,
            started_at=started_at,
            started=started,
            progress_observer=progress_observer,
        )
    except asyncio.CancelledError:
        try:
            await progress_observer(
                _lifecycle_event(
                    branch_id=branch_id,
                    kind=spec.kind,
                    status=EvidenceBranchStatus.CANCELLED.value,
                    summary=f"{spec.kind.value} evidence cancelled",
                    started_at=started_at,
                    started=started,
                )
            )
        except Exception as exc:  # noqa: BLE001 - cancellation remains authoritative
            _LOG.warning(
                "chat evidence cancellation progress failed: %s",
                type(exc).__name__,
                extra={"branch_kind": spec.kind.value},
                exc_info=True,
            )
        raise
    except ValueError as exc:
        _LOG.info(
            "chat_evidence_branch_rejected",
            extra={
                "branch_kind": spec.kind.value,
                "error_type": type(exc).__name__,
            },
        )
        return await _terminal_result(
            branch_id=branch_id,
            kind=spec.kind,
            status=EvidenceBranchStatus.UNAVAILABLE,
            summary=f"{spec.kind.value} evidence unavailable",
            context=base_context,
            started_at=started_at,
            started=started,
            progress_observer=progress_observer,
        )
    except Exception as exc:  # noqa: BLE001 - isolate one read-only evidence branch
        _LOG.warning(
            "chat evidence branch failed: %s",
            type(exc).__name__,
            extra={"branch_kind": spec.kind.value},
            exc_info=True,
        )
        return await _terminal_result(
            branch_id=branch_id,
            kind=spec.kind,
            status=EvidenceBranchStatus.FAILED,
            summary=f"{spec.kind.value} evidence failed",
            context=base_context,
            started_at=started_at,
            started=started,
            progress_observer=progress_observer,
        )

    status = (
        EvidenceBranchStatus.COMPLETED
        if any(key in context for key in spec.evidence_keys)
        else EvidenceBranchStatus.UNAVAILABLE
    )
    return await _terminal_result(
        branch_id=branch_id,
        kind=spec.kind,
        status=status,
        summary=(
            f"{spec.kind.value} evidence ready"
            if status is EvidenceBranchStatus.COMPLETED
            else f"{spec.kind.value} evidence unavailable"
        ),
        context=context,
        started_at=started_at,
        started=started,
        progress_observer=progress_observer,
    )


async def _terminal_result(
    *,
    branch_id: str,
    kind: EvidenceBranchKind,
    status: EvidenceBranchStatus,
    summary: str,
    context: Mapping[str, Any],
    started_at: datetime,
    started: float,
    progress_observer: BranchProgressObserver,
) -> EvidenceBranchResult:
    duration_ms = max(0, int((time.monotonic() - started) * 1000))
    await progress_observer(
        _lifecycle_event(
            branch_id=branch_id,
            kind=kind,
            status=status.value,
            summary=summary,
            started_at=started_at,
            started=started,
        )
    )
    return EvidenceBranchResult(
        kind=kind,
        status=status,
        context=dict(context),
        duration_ms=duration_ms,
    )


def _lifecycle_event(
    *,
    branch_id: str,
    kind: EvidenceBranchKind,
    status: str,
    summary: str,
    started_at: datetime,
    started: float | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event": "branch",
        "branch_id": branch_id,
        "branch_kind": kind.value,
        "parent_branch_id": None,
        "status": status,
        "summary": summary,
        "started_at": started_at.isoformat(),
        "evidence_refs": [],
    }
    if started is not None:
        payload.update(
            {
                "completed_at": datetime.now(tz=UTC).isoformat(),
                "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
            }
        )
    return payload


__all__ = [
    "DEFAULT_EVIDENCE_BRANCH_TIMEOUT_SECONDS",
    "MAX_EVIDENCE_BRANCHES",
    "EvidenceBranchKind",
    "EvidenceBranchResult",
    "EvidenceBranchSpec",
    "EvidenceBranchStatus",
    "resolve_evidence_branches",
]
