"""Append-only Process recording and replay projection for adaptive investigations."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from fdai.core.rca.discrimination import HypothesisDiscriminationFrame
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessRuntimeStore,
    ProcessSnapshot,
    ProcessStatus,
)

from .adaptive_codec import adaptive_result_from_mapping, adaptive_result_to_mapping
from .adaptive_contract import (
    AdaptiveInvestigationBudget,
    AdaptiveInvestigationDisposition,
    AdaptiveInvestigationIteration,
    AdaptiveInvestigationResult,
)

ADAPTIVE_INVESTIGATION_WORKFLOW_REF = "adaptive-investigation"
ADAPTIVE_INVESTIGATION_WORKFLOW_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class AdaptiveInvestigationProcessStart:
    """Process start result that distinguishes new work from persisted replay."""

    snapshot: ProcessSnapshot
    replayed: bool


class AdaptiveInvestigationProcessRecorder:
    """Record one Forseti-accountable adaptive session with Process revision CAS."""

    def __init__(
        self,
        *,
        store: ProcessRuntimeStore,
        session_id: str,
        incident_id: str,
        target_resource_id: str,
        correlation_id: str,
        initial_frame: HypothesisDiscriminationFrame,
        active_strategy_digest: str,
        challenger_strategy_digest: str | None,
        budget: AdaptiveInvestigationBudget,
        planning_handoff_config_digest: str,
        clock: Callable[[], datetime] | None = None,
        startup_lease_seconds: int = 30,
    ) -> None:
        if not 1 <= startup_lease_seconds <= 300:
            raise ValueError("startup_lease_seconds MUST be in [1, 300]")
        self._store = store
        self._session_id = session_id
        self._incident_id = incident_id
        self._target_resource_id = target_resource_id
        self._correlation_id = correlation_id
        self._initial_frame = initial_frame
        self._initial_frame_digest = initial_frame.frame_digest
        self._initial_active_set_receipt_digest = initial_frame.active_set_receipt_digest
        self._initial_cost_model_digest = initial_frame.cost_model_digest
        self._active_strategy_digest = active_strategy_digest
        self._challenger_strategy_digest = challenger_strategy_digest
        self._budget = budget
        self._planning_handoff_config_digest = planning_handoff_config_digest
        self._clock = clock or (lambda: datetime.now(UTC))
        self._startup_lease = timedelta(seconds=startup_lease_seconds)

    async def start(self) -> AdaptiveInvestigationProcessStart:
        """Create and start the Process, or verify an idempotent replay."""

        now = self._clock()
        snapshot, created = await self._store.create(
            snapshot=ProcessSnapshot(
                process_id=self._session_id,
                workflow_ref=ADAPTIVE_INVESTIGATION_WORKFLOW_REF,
                workflow_version=ADAPTIVE_INVESTIGATION_WORKFLOW_VERSION,
                status=ProcessStatus.PENDING,
                current_step="context_frozen",
                target_resource_id=self._target_resource_id,
                started_at=now,
                updated_at=now,
                correlation_id=self._correlation_id,
            ),
            event=ProcessEvent(
                event_id=_event_id(self._session_id, "created"),
                process_id=self._session_id,
                kind=ProcessEventKind.PROCESS_CREATED,
                idempotency_key=f"{self._session_id}:created",
                recorded_at=now,
                correlation_id=self._correlation_id,
                payload=self._creation_payload(),
            ),
        )
        if not created:
            await self._verify_existing_identity(snapshot)
            if snapshot.status is ProcessStatus.PENDING:
                events = await self._store.events(self._session_id)
                creation = next(
                    (event for event in events if event.kind is ProcessEventKind.PROCESS_CREATED),
                    None,
                )
                if (
                    creation is not None
                    and self._clock() - creation.recorded_at >= self._startup_lease
                ):
                    claim_id = uuid4().hex
                    started = await self._store.transition(
                        process_id=self._session_id,
                        expected_revision=snapshot.revision,
                        status=ProcessStatus.RUNNING,
                        current_step="hypotheses_ranked",
                        event=ProcessEvent(
                            event_id=_event_id(
                                self._session_id,
                                f"startup-reclaim:{claim_id}",
                            ),
                            process_id=self._session_id,
                            kind=ProcessEventKind.PROCESS_STARTED,
                            idempotency_key=(f"{self._session_id}:startup-reclaim:{claim_id}"),
                            recorded_at=self._clock(),
                            correlation_id=self._correlation_id,
                            payload={
                                "owner_agent": "Forseti",
                                "startup_reclaimed": True,
                                "execution_authority": False,
                            },
                        ),
                    )
                    return AdaptiveInvestigationProcessStart(
                        snapshot=started,
                        replayed=False,
                    )
            return AdaptiveInvestigationProcessStart(
                snapshot=snapshot,
                replayed=True,
            )
        if snapshot.status is ProcessStatus.PENDING:
            started = await self._store.transition(
                process_id=self._session_id,
                expected_revision=snapshot.revision,
                status=ProcessStatus.RUNNING,
                current_step="hypotheses_ranked",
                event=ProcessEvent(
                    event_id=_event_id(self._session_id, "started"),
                    process_id=self._session_id,
                    kind=ProcessEventKind.PROCESS_STARTED,
                    idempotency_key=f"{self._session_id}:started",
                    recorded_at=self._clock(),
                    correlation_id=self._correlation_id,
                    payload={
                        "owner_agent": "Forseti",
                        "execution_authority": False,
                    },
                ),
            )
            return AdaptiveInvestigationProcessStart(
                snapshot=started,
                replayed=False,
            )
        if snapshot.status is not ProcessStatus.RUNNING and not snapshot.status.terminal:
            raise ValueError("adaptive investigation Process is not resumable")
        return AdaptiveInvestigationProcessStart(snapshot=snapshot, replayed=True)

    async def _verify_existing_identity(self, snapshot: ProcessSnapshot) -> None:
        if (
            snapshot.workflow_ref != ADAPTIVE_INVESTIGATION_WORKFLOW_REF
            or snapshot.workflow_version != ADAPTIVE_INVESTIGATION_WORKFLOW_VERSION
            or snapshot.target_resource_id != self._target_resource_id
            or snapshot.correlation_id != self._correlation_id
        ):
            raise ValueError("adaptive investigation Process identity conflicts with replay")
        events = await self._store.events(self._session_id)
        creation = tuple(
            event for event in events if event.kind is ProcessEventKind.PROCESS_CREATED
        )
        if (
            len(creation) != 1
            or creation[0].event_id != _event_id(self._session_id, "created")
            or creation[0].idempotency_key != f"{self._session_id}:created"
            or creation[0].correlation_id != self._correlation_id
            or dict(creation[0].payload) != dict(self._creation_payload())
        ):
            raise ValueError(
                "adaptive investigation Process creation payload conflicts with replay"
            )

    async def record(
        self,
        item: AdaptiveInvestigationIteration | AdaptiveInvestigationResult,
    ) -> None:
        """Append an iteration or close the Process with one terminal receipt."""

        if isinstance(item, AdaptiveInvestigationIteration):
            await self._record_iteration(item)
            return
        if isinstance(item, AdaptiveInvestigationResult):
            await self._record_terminal(item)
            return
        raise TypeError("adaptive investigation recorder received an unsupported item")

    async def replay_terminal_result(self) -> AdaptiveInvestigationResult:
        """Restore the exact persisted terminal result without provider I/O."""

        events = await self._store.events(self._session_id)
        terminals = tuple(
            event for event in events if event.payload.get("record_type") == "adaptive_terminal"
        )
        if len(terminals) != 1:
            raise ValueError("adaptive investigation replay requires one terminal result")
        raw = terminals[0].payload.get("result")
        if not isinstance(raw, Mapping):
            raise ValueError("adaptive investigation terminal result is unavailable")
        result = adaptive_result_from_mapping(raw)
        if result.session_id != self._session_id or result.incident_id != self._incident_id:
            raise ValueError("adaptive investigation persisted result identity conflicts")
        await self._validate_result_against_pinned(result)
        terminal = terminals[0]
        expected_event_id = _event_id(
            self._session_id,
            f"terminal:{result.result_digest}",
        )
        payload = terminal.payload
        if (
            terminal.event_id != expected_event_id
            or terminal.idempotency_key != f"{self._session_id}:terminal:{result.result_digest}"
            or terminal.correlation_id != self._correlation_id
            or payload.get("result_digest") != result.result_digest
            or payload.get("disposition") != result.disposition.value
            or payload.get("terminal_frame_digest") != result.terminal_frame_digest
            or payload.get("terminal_active_set_receipt_digest")
            != result.terminal_active_set_receipt_digest
            or payload.get("used_queries") != result.used_queries
            or payload.get("used_cost_units") != result.used_cost_units
            or payload.get("iteration_digests")
            != [item.iteration_digest for item in result.iterations]
        ):
            raise ValueError("adaptive investigation terminal envelope conflicts")
        return result

    async def record_failure(self, reason: str) -> None:
        """Close a running Process after an unexpected runtime failure."""

        if not reason or len(reason) > 128:
            raise ValueError("adaptive investigation failure reason MUST be bounded")
        snapshot = await self._required_running_snapshot()
        await self._store.transition(
            process_id=self._session_id,
            expected_revision=snapshot.revision,
            status=ProcessStatus.FAILED,
            current_step="",
            event=ProcessEvent(
                event_id=_event_id(self._session_id, f"failed:{reason}"),
                process_id=self._session_id,
                kind=ProcessEventKind.PROCESS_FAILED,
                idempotency_key=f"{self._session_id}:failed:{reason}",
                recorded_at=self._clock(),
                correlation_id=self._correlation_id,
                payload={
                    "record_type": "adaptive_failed",
                    "reason": reason,
                    "execution_authority": False,
                },
            ),
        )

    async def record_cancellation(self, reason: str) -> None:
        """Close a running Process when its supervising runtime task is cancelled."""

        if not reason or len(reason) > 128:
            raise ValueError("adaptive investigation cancellation reason MUST be bounded")
        snapshot = await self._required_running_snapshot()
        await self._store.transition(
            process_id=self._session_id,
            expected_revision=snapshot.revision,
            status=ProcessStatus.CANCELLED,
            current_step="",
            event=ProcessEvent(
                event_id=_event_id(self._session_id, f"cancelled:{reason}"),
                process_id=self._session_id,
                kind=ProcessEventKind.PROCESS_CANCELLED,
                idempotency_key=f"{self._session_id}:cancelled:{reason}",
                recorded_at=self._clock(),
                correlation_id=self._correlation_id,
                payload={
                    "record_type": "adaptive_cancelled",
                    "reason": reason,
                    "execution_authority": False,
                },
            ),
        )

    async def planning_handoff_was_published(self, handoff_id: str) -> bool:
        """Return whether the stable planning handoff completed publication."""

        return any(
            event.payload.get("record_type") == "adaptive_planning_handoff"
            and event.payload.get("handoff_id") == handoff_id
            for event in await self._store.events(self._session_id)
        )

    async def record_planning_handoff_published(self, handoff_id: str) -> None:
        """Append an idempotent terminal child event after handoff publication."""

        if not handoff_id or len(handoff_id) > 256:
            raise ValueError("adaptive planning handoff id MUST be bounded")
        await self._store.append_event(
            ProcessEvent(
                event_id=_event_id(
                    self._session_id,
                    f"planning-handoff:{handoff_id}",
                ),
                process_id=self._session_id,
                kind=ProcessEventKind.EVIDENCE_ATTACHED,
                idempotency_key=(f"{self._session_id}:planning-handoff:{handoff_id}"),
                recorded_at=self._clock(),
                correlation_id=self._correlation_id,
                step_id="planning-handoff",
                payload={
                    "record_type": "adaptive_planning_handoff",
                    "handoff_id": handoff_id,
                    "published": True,
                    "execution_authority": False,
                },
            )
        )

    async def _record_iteration(self, iteration: AdaptiveInvestigationIteration) -> None:
        snapshot = await self._required_running_snapshot()
        expected_round = 1 + sum(
            event.kind is ProcessEventKind.EVIDENCE_ATTACHED
            and event.payload.get("record_type") == "adaptive_iteration"
            for event in await self._store.events(self._session_id)
        )
        if iteration.round_index != expected_round:
            raise ValueError("adaptive investigation iteration is out of order")
        payload: dict[str, object] = {
            "record_type": "adaptive_iteration",
            "round_index": iteration.round_index,
            "iteration_digest": iteration.iteration_digest,
            "frame_digest": iteration.frame.frame_digest,
            "evidence_cutoff": _timestamp(iteration.frame.evidence_cutoff),
            "graph_revision": iteration.frame.graph_revision,
            "cost_model_digest": iteration.frame.cost_model_digest,
            "active_hypothesis_ids": list(iteration.frame.active_hypothesis_ids),
            "active_set_receipt_digest": iteration.frame.active_set_receipt_digest,
            "selection_digest": iteration.selection.selection_digest,
            "selected_candidate_id": iteration.selection.selected_candidate_id,
            "separated_pair_count": iteration.selection.separated_pair_count,
            "total_pair_count": iteration.selection.total_pair_count,
            "hold_reason": (
                iteration.selection.hold_reason.value
                if iteration.selection.hold_reason is not None
                else None
            ),
            "shadow_comparison_digest": iteration.shadow_comparison_digest,
            "owner_agent": "Forseti",
            "execution_authority": False,
        }
        if iteration.execution is not None:
            payload["execution"] = {
                "frame_digest": iteration.execution.frame_digest,
                "selection_digest": iteration.execution.selection_digest,
                "candidate_digest": iteration.execution.candidate_digest,
                "binding_digest": iteration.execution.binding_digest,
                "verification_receipt_digest": (iteration.execution.verification_receipt_digest),
                "plan_digest": iteration.execution.plan_digest,
                "result_digest": iteration.execution.result_digest,
                "execution_digest": iteration.execution.execution_digest,
                "query_status": iteration.execution.query_status,
                "evidence_refs": list(iteration.execution.evidence_refs),
                "reserved_cost_units": iteration.execution.reserved_cost_units,
                "actual_cost_units": iteration.execution.actual_cost_units,
            }
        if iteration.revision is not None:
            payload["revision"] = {
                "revision_digest": iteration.revision.revision_digest,
                "prior_active_set_receipt_digest": (
                    iteration.revision.prior_active_set_receipt_digest
                ),
                "prior_frame_digest": iteration.revision.prior_frame_digest,
                "observation_result_digest": (iteration.revision.observation_result_digest),
                "scorer_version": iteration.revision.scorer_version,
                "graph_revision": iteration.revision.graph_revision,
                "evidence_cutoff": _timestamp(iteration.revision.evidence_cutoff),
                "active_hypothesis_ids": list(iteration.revision.active_hypothesis_ids),
                "active_set_receipt_digest": (iteration.revision.active_set_receipt_digest),
                "disposition": iteration.revision.disposition.value,
                "complete": iteration.revision.complete,
                "truncated": iteration.revision.truncated,
                "evidence_refs": list(iteration.revision.evidence_refs),
            }
        await self._store.transition(
            process_id=self._session_id,
            expected_revision=snapshot.revision,
            status=ProcessStatus.RUNNING,
            current_step=f"round-{iteration.round_index}",
            event=ProcessEvent(
                event_id=_event_id(
                    self._session_id,
                    f"iteration:{iteration.round_index}:{iteration.iteration_digest}",
                ),
                process_id=self._session_id,
                kind=ProcessEventKind.EVIDENCE_ATTACHED,
                idempotency_key=(
                    f"{self._session_id}:iteration:{iteration.round_index}:"
                    f"{iteration.iteration_digest}"
                ),
                recorded_at=self._clock(),
                correlation_id=self._correlation_id,
                step_id=f"round-{iteration.round_index}",
                attempt=iteration.round_index,
                payload=payload,
            ),
        )

    async def _record_terminal(self, result: AdaptiveInvestigationResult) -> None:
        snapshot = await self._required_running_snapshot()
        if result.session_id != self._session_id or result.incident_id != self._incident_id:
            raise ValueError("adaptive investigation result does not match the Process")
        await self._validate_result_against_pinned(result)
        status, kind = _terminal_process_state(result.disposition)
        await self._store.transition(
            process_id=self._session_id,
            expected_revision=snapshot.revision,
            status=status,
            current_step="",
            event=ProcessEvent(
                event_id=_event_id(
                    self._session_id,
                    f"terminal:{result.result_digest}",
                ),
                process_id=self._session_id,
                kind=kind,
                idempotency_key=f"{self._session_id}:terminal:{result.result_digest}",
                recorded_at=self._clock(),
                correlation_id=self._correlation_id,
                payload={
                    "record_type": "adaptive_terminal",
                    "result_digest": result.result_digest,
                    "disposition": result.disposition.value,
                    "terminal_frame_digest": result.terminal_frame_digest,
                    "terminal_active_set_receipt_digest": (
                        result.terminal_active_set_receipt_digest
                    ),
                    "used_queries": result.used_queries,
                    "used_cost_units": result.used_cost_units,
                    "iteration_digests": [item.iteration_digest for item in result.iterations],
                    "result": adaptive_result_to_mapping(result),
                    "execution_authority": False,
                },
            ),
        )

    async def _validate_result_against_pinned(
        self,
        result: AdaptiveInvestigationResult,
    ) -> None:
        if (
            result.active_strategy_digest != self._active_strategy_digest
            or result.challenger_strategy_digest != self._challenger_strategy_digest
            or result.budget != self._budget
            or result.workflow_version != ADAPTIVE_INVESTIGATION_WORKFLOW_VERSION
        ):
            raise ValueError("adaptive investigation result conflicts with pinned session inputs")
        if result.iterations:
            first = result.iterations[0].frame
            if (
                first.frame_digest != self._initial_frame_digest
                or first.active_set_receipt_digest != self._initial_active_set_receipt_digest
                or first.cost_model_digest != self._initial_cost_model_digest
            ):
                raise ValueError("adaptive investigation result initial frame conflicts")
        elif (
            result.terminal_frame_digest != self._initial_frame_digest
            or result.terminal_active_set_receipt_digest != self._initial_active_set_receipt_digest
        ):
            raise ValueError("adaptive investigation empty result initial frame conflicts")
        recorded_iterations = tuple(
            str(event.payload.get("iteration_digest") or "")
            for event in await self._store.events(self._session_id)
            if event.payload.get("record_type") == "adaptive_iteration"
        )
        result_iterations = tuple(item.iteration_digest for item in result.iterations)
        if recorded_iterations != result_iterations:
            raise ValueError("adaptive investigation result iteration journal conflicts")

    async def _required_running_snapshot(self) -> ProcessSnapshot:
        snapshot = await self._store.get(self._session_id)
        if snapshot is None:
            raise RuntimeError("adaptive investigation Process has not started")
        if snapshot.status is not ProcessStatus.RUNNING:
            raise ValueError("adaptive investigation Process is not running")
        return snapshot

    def _creation_payload(self) -> Mapping[str, object]:
        return {
            "record_type": "adaptive_created",
            "incident_id": self._incident_id,
            "initial_frame_digest": self._initial_frame_digest,
            "initial_active_set_receipt_digest": (self._initial_active_set_receipt_digest),
            "initial_cost_model_digest": self._initial_cost_model_digest,
            "initial_graph_revision": self._initial_frame.graph_revision,
            "initial_evidence_cutoff": _timestamp(self._initial_frame.evidence_cutoff),
            "initial_active_hypothesis_ids": list(self._initial_frame.active_hypothesis_ids),
            "active_strategy_digest": self._active_strategy_digest,
            "challenger_strategy_digest": self._challenger_strategy_digest,
            "planning_handoff_config_digest": (self._planning_handoff_config_digest),
            "budget": {
                "max_rounds": self._budget.max_rounds,
                "max_queries": self._budget.max_queries,
                "max_cost_units": self._budget.max_cost_units,
                "deadline_at": _timestamp(self._budget.deadline_at),
                "policy_digest": self._budget.policy_digest,
            },
            "owner_agent": "Forseti",
            "execution_authority": False,
        }


def project_adaptive_investigation_room(
    events: Sequence[ProcessEvent | Mapping[str, Any]],
) -> dict[str, object] | None:
    """Fold bounded Process events into a read-only Investigation Room projection."""

    normalized = tuple(_event_view(item) for item in events)
    created = tuple(
        item for item in normalized if item["payload"].get("record_type") == "adaptive_created"
    )
    if not created:
        return None
    if len(created) != 1:
        raise ValueError("adaptive investigation journal requires one creation event")
    rounds = tuple(
        item for item in normalized if item["payload"].get("record_type") == "adaptive_iteration"
    )
    terminal = tuple(
        item for item in normalized if item["payload"].get("record_type") == "adaptive_terminal"
    )
    if len(terminal) > 1:
        raise ValueError("adaptive investigation journal has multiple terminal events")
    closures = tuple(
        item
        for item in normalized
        if item["payload"].get("record_type") in {"adaptive_failed", "adaptive_cancelled"}
    )
    if len(closures) > 1 or (closures and terminal):
        raise ValueError("adaptive investigation journal has conflicting closures")
    expected_rounds = tuple(range(1, len(rounds) + 1))
    actual_rounds = tuple(int(item["payload"]["round_index"]) for item in rounds)
    if actual_rounds != expected_rounds:
        raise ValueError("adaptive investigation rounds are not contiguous")
    for previous, current in zip(rounds, rounds[1:], strict=False):
        revision = _mapping(previous["payload"].get("revision"), "revision")
        if revision.get("active_set_receipt_digest") != current["payload"].get(
            "active_set_receipt_digest"
        ):
            raise ValueError("adaptive investigation active-set lineage is broken")
    terminal_payload = terminal[0]["payload"] if terminal else None
    if terminal_payload is not None:
        expected = [item["payload"]["iteration_digest"] for item in rounds]
        if terminal_payload.get("iteration_digests") != expected:
            raise ValueError("adaptive investigation terminal iteration lineage is broken")
    creation_payload = created[0]["payload"]
    if (
        terminal_payload is not None
        and not rounds
        and (
            terminal_payload.get("terminal_frame_digest")
            != creation_payload.get("initial_frame_digest")
            or terminal_payload.get("terminal_active_set_receipt_digest")
            != creation_payload.get("initial_active_set_receipt_digest")
        )
    ):
        raise ValueError("adaptive investigation empty terminal lineage is broken")
    return {
        "read_only": True,
        "mutation_controls": False,
        "incident_id": creation_payload["incident_id"],
        "active_strategy_digest": creation_payload["active_strategy_digest"],
        "challenger_strategy_digest": creation_payload.get("challenger_strategy_digest"),
        "budget": creation_payload["budget"],
        "rounds": [item["payload"] for item in rounds],
        "round_count": len(rounds),
        "terminal": terminal_payload,
        "closure": closures[0]["payload"] if closures else None,
    }


def _event_view(event: ProcessEvent | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(event, ProcessEvent):
        return {"payload": dict(event.payload)}
    return {"payload": _mapping(event.get("payload"), "event payload")}


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"adaptive investigation {label} MUST be an object")
    return dict(value)


def _terminal_process_state(
    disposition: AdaptiveInvestigationDisposition,
) -> tuple[ProcessStatus, ProcessEventKind]:
    if disposition is AdaptiveInvestigationDisposition.CANCELLED:
        return ProcessStatus.CANCELLED, ProcessEventKind.PROCESS_CANCELLED
    if disposition is AdaptiveInvestigationDisposition.TIMED_OUT:
        return ProcessStatus.TIMED_OUT, ProcessEventKind.PROCESS_TIMED_OUT
    return ProcessStatus.SUCCEEDED, ProcessEventKind.PROCESS_COMPLETED


def _event_id(process_id: str, suffix: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"{process_id}:{suffix}"))


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "ADAPTIVE_INVESTIGATION_WORKFLOW_REF",
    "ADAPTIVE_INVESTIGATION_WORKFLOW_VERSION",
    "AdaptiveInvestigationProcessStart",
    "AdaptiveInvestigationProcessRecorder",
    "project_adaptive_investigation_room",
]
