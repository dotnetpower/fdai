"""Authorization-first deterministic join of immutable trajectory snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from fdai.core.trajectory.models import (
    DatasetGovernance,
    SourceRecordDigest,
    TrajectoryEnvelope,
    TrajectoryStep,
    TrajectoryStepKind,
    TrajectoryTerminalOutcome,
    catalog_tool_statistics,
)
from fdai.shared.providers.trajectory import (
    ApprovalSnapshotProvider,
    AuditSnapshotProvider,
    ConversationSnapshotProvider,
    ImmutableTrajectorySnapshot,
    OutcomeSnapshotProvider,
    ToolSnapshotProvider,
    TrajectoryAccessAuthorizer,
    TrajectoryBatchFilters,
)

_STEP_RANK = {kind.value: rank for rank, kind in enumerate(TrajectoryStepKind)}


@dataclass(frozen=True, slots=True)
class TrajectoryProjectionRequest:
    principal_id: str
    access_scope: str
    purpose: str
    environment: str
    evidence_profile: str
    model_capability_id: str
    redaction_policy_version: str
    governance: DatasetGovernance
    catalog_tool_ids: tuple[str, ...]
    filters: TrajectoryBatchFilters = TrajectoryBatchFilters()


class TrajectoryProjectionError(ValueError):
    """Raised when immutable sources cannot form a complete trajectory."""


class TrajectoryJoinService:
    """Authorize before touching a source, then join in canonical order."""

    def __init__(
        self,
        *,
        authorizer: TrajectoryAccessAuthorizer,
        audit: AuditSnapshotProvider,
        conversation: ConversationSnapshotProvider,
        tool: ToolSnapshotProvider,
        approval: ApprovalSnapshotProvider,
        outcome: OutcomeSnapshotProvider,
    ) -> None:
        self._authorizer = authorizer
        self._providers = (audit, conversation, tool, approval, outcome)

    async def materialize(
        self,
        request: TrajectoryProjectionRequest,
    ) -> tuple[TrajectoryEnvelope, ...]:
        scope = await self._authorizer.authorize(
            principal_id=request.principal_id,
            access_scope=request.access_scope,
            purpose=request.purpose,
        )
        snapshots: list[ImmutableTrajectorySnapshot] = []
        for provider in self._providers:
            snapshots.extend(await provider.snapshot(scope=scope, filters=request.filters))
        grouped: dict[tuple[str, str], list[ImmutableTrajectorySnapshot]] = {}
        for snapshot in snapshots:
            grouped.setdefault((snapshot.trace_id, snapshot.correlation_id), []).append(snapshot)
        return tuple(
            self._project_group(
                trace_id=key[0],
                correlation_id=key[1],
                snapshots=grouped[key],
                request=request,
                principal_scope_digest=scope.principal_scope_digest,
            )
            for key in sorted(grouped)
        )

    def _project_group(
        self,
        *,
        trace_id: str,
        correlation_id: str,
        snapshots: list[ImmutableTrajectorySnapshot],
        request: TrajectoryProjectionRequest,
        principal_scope_digest: str,
    ) -> TrajectoryEnvelope:
        ordered = sorted(snapshots, key=_snapshot_key)
        if not ordered:
            raise TrajectoryProjectionError("trajectory group MUST contain source records")
        outcome_snapshot = _terminal_snapshot(ordered)
        completion_status = _terminal_outcome(outcome_snapshot)
        steps = tuple(
            TrajectoryStep(
                sequence=sequence,
                occurred_at=snapshot.occurred_at,
                kind=TrajectoryStepKind(snapshot.step_kind),
                source=_source_digest(snapshot),
                payload=snapshot.payload,
            )
            for sequence, snapshot in enumerate(ordered)
        )
        sources = tuple(sorted({_source_digest(item) for item in ordered}, key=_source_key))
        return TrajectoryEnvelope(
            trajectory_id=f"{trace_id}:{correlation_id}",
            trace_id=trace_id,
            correlation_id=correlation_id,
            started_at=ordered[0].occurred_at,
            completed_at=ordered[-1].occurred_at,
            environment=request.environment,
            evidence_profile=request.evidence_profile,
            principal_scope_digest=principal_scope_digest,
            model_capability_id=request.model_capability_id,
            completion_status=completion_status,
            redaction_policy_version=request.redaction_policy_version,
            governance=request.governance,
            source_records=sources,
            steps=steps,
            tool_statistics=catalog_tool_statistics(
                request.catalog_tool_ids,
                _tool_statistics(ordered),
            ),
        )


def _snapshot_key(snapshot: ImmutableTrajectorySnapshot) -> tuple[datetime, int, str, str]:
    rank = _STEP_RANK.get(snapshot.step_kind)
    if rank is None:
        raise TrajectoryProjectionError(f"unsupported trajectory step kind: {snapshot.step_kind}")
    return snapshot.occurred_at, rank, snapshot.source_kind.value, snapshot.record_id


def _source_digest(snapshot: ImmutableTrajectorySnapshot) -> SourceRecordDigest:
    return SourceRecordDigest(
        record_type=snapshot.source_kind.value,
        record_id=snapshot.record_id,
        sha256=snapshot.record_digest,
    )


def _source_key(source: SourceRecordDigest) -> tuple[str, str]:
    return source.record_type, source.record_id


def _terminal_snapshot(
    snapshots: list[ImmutableTrajectorySnapshot],
) -> ImmutableTrajectorySnapshot:
    terminal = [item for item in snapshots if item.step_kind == "terminal_outcome"]
    if len(terminal) != 1 or terminal[0] is not snapshots[-1]:
        raise TrajectoryProjectionError(
            "trajectory MUST contain exactly one final terminal_outcome snapshot"
        )
    return terminal[0]


def _terminal_outcome(snapshot: ImmutableTrajectorySnapshot) -> TrajectoryTerminalOutcome:
    value = snapshot.payload.get("outcome")
    try:
        return TrajectoryTerminalOutcome(str(value))
    except ValueError as exc:
        raise TrajectoryProjectionError("trajectory terminal outcome is invalid") from exc


def _tool_statistics(
    snapshots: list[ImmutableTrajectorySnapshot],
) -> Mapping[str, tuple[int, int, int]]:
    requests: dict[str, int] = {}
    successes: dict[str, int] = {}
    failures: dict[str, int] = {}
    for snapshot in snapshots:
        tool_id = snapshot.payload.get("tool_id")
        if not isinstance(tool_id, str):
            continue
        if snapshot.step_kind == "tool_request":
            requests[tool_id] = requests.get(tool_id, 0) + 1
        elif snapshot.step_kind == "tool_receipt":
            status = snapshot.payload.get("status")
            target = successes if status == "succeeded" else failures
            target[tool_id] = target.get(tool_id, 0) + 1
    return {
        tool_id: (
            requests.get(tool_id, 0),
            successes.get(tool_id, 0),
            failures.get(tool_id, 0),
        )
        for tool_id in requests.keys() | successes.keys() | failures.keys()
    }


__all__ = ["TrajectoryJoinService", "TrajectoryProjectionError", "TrajectoryProjectionRequest"]
