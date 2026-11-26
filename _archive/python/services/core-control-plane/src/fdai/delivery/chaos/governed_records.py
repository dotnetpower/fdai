"""Admission, identity, ceiling, and audit records for governed chaos runs.

These pure helpers keep the governed adapter's record shapes in one place:
request admission, the durable run identity, the catalog-to-harness scenario
adaptation, the ActionType time box and tier ceiling, and the Saga audit
entries. Receipt and outcome mapping lives in ``governed_outcome``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from fdai.core.chaos.contract import ExperimentResult, FaultScenario
from fdai.core.chaos.run_state import ChaosRunSnapshot, ChaosRunState
from fdai.core.chaos.scenario_catalog import CatalogEntry
from fdai.shared.contracts.models import (
    ActionStopCondition,
    Autonomy,
    Mode,
    OntologyActionType,
    StopConditionKind,
    Tier,
)
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.tool import (
    ToolCallRequest,
    ToolPreconditionError,
    ToolPromotionError,
)

CHAOS_ACTION_TYPE = "tool.run-chaos-experiment"
_ENFORCE_AUTONOMY = frozenset({Autonomy.ENFORCE_HIL, Autonomy.ENFORCE_AUTO})
PRE_INJECTION_STATES = frozenset(
    {
        ChaosRunState.PLANNED,
        ChaosRunState.IMPACT_CHECKED,
        ChaosRunState.DRY_RUN_VERIFIED,
        ChaosRunState.APPROVED,
    }
)


def admit_chaos_request(
    request: ToolCallRequest,
    entries: Mapping[str, CatalogEntry],
) -> tuple[CatalogEntry, FaultScenario, tuple[str, ...]]:
    """Validate one governed enforce request before any lock, state, or injection.

    Raises:
        ToolPromotionError: the request is not a labeled enforce request.
        ToolPreconditionError: the ActionType, idempotency key, scenario, or
            targets are invalid, or the targets exceed the blast-radius cap.
    """

    if request.mode is not Mode.ENFORCE or "enforce" not in request.labels:
        raise ToolPromotionError("governed chaos execution accepts only labeled enforce requests")
    if request.action_type_name != CHAOS_ACTION_TYPE:
        raise ToolPreconditionError(f"governed chaos execution serves only {CHAOS_ACTION_TYPE}")
    if not request.idempotency_key.strip():
        raise ToolPreconditionError("governed chaos execution requires an idempotency key")
    scenario_id = request.arguments.get("scenario_id")
    raw_targets = request.arguments.get("targets")
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise ToolPreconditionError("scenario_id MUST be a non-empty string")
    if not isinstance(raw_targets, (list, tuple)) or not raw_targets:
        raise ToolPreconditionError("targets MUST be a non-empty array")
    if any(not isinstance(item, str) or not item.strip() for item in raw_targets):
        raise ToolPreconditionError("targets MUST contain non-empty strings")
    targets = tuple(dict.fromkeys(item.strip() for item in raw_targets))
    entry = entries.get(scenario_id.strip())
    if entry is None:
        raise ToolPreconditionError(f"unknown chaos scenario {scenario_id!r}")
    try:
        scenario = catalog_fault_scenario(entry)
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolPreconditionError(f"chaos scenario {entry.id!r} is malformed") from exc
    if len(targets) > scenario.blast_radius_cap:
        raise ToolPreconditionError("targets exceed the scenario blast-radius cap")
    return entry, scenario, targets


def governed_chaos_run_id(idempotency_key: str, scenario_id: str, targets: Sequence[str]) -> str:
    """Return the durable run id bound to one request identity and target set."""

    payload = json.dumps(
        {
            "idempotency_key": idempotency_key,
            "scenario_id": scenario_id,
            "targets": sorted(targets),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"chaos-run-{hashlib.sha256(payload.encode()).hexdigest()[:32]}"


def catalog_fault_scenario(entry: CatalogEntry) -> FaultScenario:
    """Adapt one schema-validated catalog entry to the harness scenario contract."""

    spec = entry.spec
    params = spec.get("params")
    return FaultScenario(
        scenario_id=entry.id,
        fault_type=str(spec.get("fault_family", "unknown")),
        description=str(spec.get("description", entry.id)),
        target_selector=f"catalog:{entry.id}",
        expected_signal=entry.expected_signal,
        blast_radius_cap=int(spec.get("blast_radius_cap", 1)),
        duration_seconds=float(spec.get("duration_seconds", 360.0)),
        params=(
            {str(key): str(value) for key, value in params.items()}
            if isinstance(params, Mapping)
            else {}
        ),
        rollback_note=str(spec.get("rollback_note", "")),
    )


def catalog_enforce_request(
    entry: CatalogEntry,
    *,
    targets: tuple[str, ...],
    approval_ref: str,
    fingerprint: str,
    stop_conditions: tuple[ActionStopCondition, ...],
    tier: Tier,
) -> ToolCallRequest:
    """Build the typed enforce request for one catalog scenario.

    The idempotency key binds the scenario version, catalog fingerprint,
    targets, and approval claim, so repeating the same operator request
    replays or resumes one durable run. ``approval_ref`` stays a claim that
    the injected verifier must confirm, and ``tier`` selects the ActionType
    ceiling the adapter enforces.
    """

    identity = json.dumps(
        {
            "approval_ref": approval_ref,
            "catalog_fingerprint": fingerprint,
            "scenario_id": entry.id,
            "scenario_version": entry.spec.get("version"),
            "targets": sorted(targets),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    idempotency_key = f"catalog-scenario:{hashlib.sha256(identity.encode()).hexdigest()}"
    return ToolCallRequest(
        action_id=uuid5(NAMESPACE_URL, f"urn:fdai:{idempotency_key}"),
        idempotency_key=idempotency_key,
        action_type_name=CHAOS_ACTION_TYPE,
        rule_ids=(entry.id,),
        tool_ref=entry.id,
        arguments={"scenario_id": entry.id, "targets": list(targets)},
        labels=("enforce",),
        mode=Mode.ENFORCE,
        stop_conditions=stop_conditions,
        metadata={
            "approval_ref": approval_ref,
            "requested_by": "run-catalog-scenario",
            "tier": tier.value,
        },
    )


def autonomy_ceiling_enforce(action_type: OntologyActionType, request: ToolCallRequest) -> bool:
    """Return whether the ActionType ceiling for the request's tier permits enforcement.

    A missing or unknown tier, a missing ceiling, or ``shadow_only`` never permits
    it, so a current approval cannot lift an ActionType's tier ceiling.
    """

    try:
        tier = Tier(request.metadata.get("tier", ""))
    except ValueError:
        return False
    ceilings = action_type.ceiling_by_tier
    ceiling = getattr(ceilings, tier.value, None) if ceilings is not None else None
    return ceiling is not None and ceiling.max_autonomy in _ENFORCE_AUTONOMY


def time_box_seconds(request: ToolCallRequest) -> float | None:
    """Return the tightest ActionType time box carried by the request, if any."""

    values = [
        item.seconds
        for item in request.stop_conditions
        if item.kind is StopConditionKind.TIME_BOX_EXCEEDED_SECONDS and item.seconds
    ]
    return float(min(values)) if values else None


def escalation_audit_entry(
    snapshot: ChaosRunSnapshot,
    *,
    reason: str,
    recorded_at: datetime,
) -> dict[str, object]:
    """Build the Saga audit entry for an escalation that has no run transition."""

    event_id = f"{snapshot.run_id}:escalation:{reason}:{snapshot.revision}"
    return {
        "event_id": event_id,
        "idempotency_key": event_id,
        "actor": "Saga",
        "producer_principal": "Saga",
        "action_kind": "chaos.run.escalation",
        "mode": Mode.ENFORCE.value,
        "run_id": snapshot.run_id,
        "state": snapshot.state.value,
        "reason": reason,
        "recorded_at": recorded_at.astimezone(UTC).isoformat(),
    }


class AuditedExperimentRecorder:
    """Append each harness result to the Saga audit chain without target values."""

    def __init__(self, state_store: StateStore, *, run_id: str) -> None:
        self._state_store = state_store
        self._run_id = run_id

    async def record(self, result: ExperimentResult) -> None:
        event_id = f"{self._run_id}:experiment:{result.experiment_id}"
        await self._state_store.append_audit_entry(
            {
                "event_id": event_id,
                "idempotency_key": event_id,
                "actor": "Saga",
                "producer_principal": "Saga",
                "action_kind": "chaos.experiment.result",
                "mode": result.mode.value,
                "run_id": self._run_id,
                "scenario_id": result.scenario_id,
                "experiment_id": result.experiment_id,
                "outcome": result.outcome.value,
                "target_count": len(result.targets),
                "injected": result.injected,
                "stopped": result.stopped,
                "reverted": result.reverted,
                "detected": result.detected,
                "stop_reason": result.stop_reason,
                "error_kind": result.error.split(":", 1)[0] if result.error else None,
                "recorded_at": result.ended_at.astimezone(UTC).isoformat(),
            }
        )


__all__ = [
    "CHAOS_ACTION_TYPE",
    "PRE_INJECTION_STATES",
    "AuditedExperimentRecorder",
    "admit_chaos_request",
    "catalog_enforce_request",
    "catalog_fault_scenario",
    "escalation_audit_entry",
    "autonomy_ceiling_enforce",
    "governed_chaos_run_id",
    "time_box_seconds",
]
