"""Durable Heimdall-owned independent observations for executed actions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from fdai.core.ontology_platform.reconciliation_binding import (
    ObservationContextVerifier,
    ResolvedReconciliationArtifacts,
)
from fdai.core.ontology_platform.reconciliation_producer import ExecutedActionObservation
from fdai.shared.contracts.models import Action
from fdai.shared.providers.state_store import StateStore


class ExecutedActionObservationConflictError(RuntimeError):
    """The same executed Action was assigned different independent evidence."""


@dataclass(frozen=True, slots=True)
class RecordedExecutedActionObservation:
    """Replay-verified execution metadata and Heimdall observation."""

    action_id: str
    plan_digest: str
    execution_outcome: str
    execution_mode: str
    execution_completed_at: datetime | None
    execution_receipt_ref: str | None
    correlation_id: str
    observation: ExecutedActionObservation


class StateStoreExecutedActionObservationStore:
    """Record and replay exact signed observations without execution authority."""

    _KEY_PREFIX = "ontology:executed-action-observation:"
    _MAX_RECORD_BYTES = 4 * 1024 * 1024

    def __init__(
        self,
        *,
        store: StateStore,
        verifier: ObservationContextVerifier,
    ) -> None:
        self._store = store
        self._verifier = verifier

    async def record(
        self,
        *,
        producer_principal: str,
        action: Action,
        artifacts: ResolvedReconciliationArtifacts,
        execution_outcome: str,
        execution_receipt_ref: str | None,
        correlation_id: str,
        observation: ExecutedActionObservation,
        execution_mode: str = "unknown",
        execution_completed_at: datetime | None = None,
    ) -> None:
        """Persist one verifier-accepted observation from Heimdall only."""
        if producer_principal != "Heimdall":
            raise ValueError("executed Action observation producer MUST be Heimdall")
        evidence = observation.evidence
        if (
            evidence.correlation_id != correlation_id
            or evidence.plan_digest != artifacts.plan.digest
            or evidence.ontology_release_ref != artifacts.active_release.ref()
            or evidence.action_type_ref != artifacts.plan.action_type_ref
        ):
            raise ValueError("executed Action observation does not match exact artifacts")
        authenticated = await self._verifier.verify(
            evidence=evidence,
            claimed_context=observation.observation_context,
        )
        if authenticated != observation.observation_context:
            raise ValueError("executed Action observation authentication changed its context")
        record = _record(
            action=action,
            artifacts=artifacts,
            execution_outcome=execution_outcome,
            execution_receipt_ref=execution_receipt_ref,
            correlation_id=correlation_id,
            observation=observation,
            execution_mode=execution_mode,
            execution_completed_at=execution_completed_at,
        )
        if len(json.dumps(record, separators=(",", ":"), sort_keys=True).encode()) > (
            self._MAX_RECORD_BYTES
        ):
            raise ValueError("executed Action observation exceeds the canonical byte limit")
        key = self._key(action, artifacts)
        created = await self._store.write_state_with_audit_if_absent(
            key,
            record,
            {
                "actor": "Heimdall",
                "producer_principal": "Heimdall",
                "action_kind": "effect_observation.recorded",
                "mode": "shadow",
                "action_id": str(action.action_id),
                "correlation_id": correlation_id,
                "idempotency_key": key,
                "observation_id": observation.evidence.observation_id,
                "observation_digest": observation.evidence.content_digest(),
            },
        )
        if created:
            return
        existing = await self._store.read_state(key)
        if existing != record:
            raise ExecutedActionObservationConflictError(
                "executed Action observation identity was reused with different content"
            )

    async def observe(
        self,
        *,
        action: Action,
        artifacts: ResolvedReconciliationArtifacts,
        execution_outcome: str,
        execution_receipt_ref: str | None,
        correlation_id: str,
    ) -> ExecutedActionObservation | None:
        """Return only an exact, reverified observation for this execution."""
        raw = await self._store.read_state(self._key(action, artifacts))
        if raw is None:
            return None
        if len(json.dumps(raw, separators=(",", ":"), sort_keys=True).encode()) > (
            self._MAX_RECORD_BYTES
        ):
            raise ValueError("stored executed Action observation exceeds the canonical byte limit")
        observation = _parse(
            raw,
            action=action,
            artifacts=artifacts,
            execution_outcome=execution_outcome,
            execution_receipt_ref=execution_receipt_ref,
            correlation_id=correlation_id,
        )
        authenticated = await self._verifier.verify(
            evidence=observation.evidence,
            claimed_context=observation.observation_context,
        )
        if authenticated != observation.observation_context:
            raise ValueError("executed Action observation authentication changed on replay")
        return observation

    async def resolve_record(
        self,
        *,
        action_id: str,
        plan_digest: str,
    ) -> RecordedExecutedActionObservation | None:
        """Resolve and reverify one exact durable observation for lineage replay."""

        try:
            canonical_action_id = str(UUID(action_id))
        except ValueError as exc:
            raise ValueError("executed Action observation id MUST be a canonical UUID") from exc
        if canonical_action_id != action_id:
            raise ValueError("executed Action observation id MUST be a canonical UUID")
        if (
            len(plan_digest) != 71
            or not plan_digest.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in plan_digest[7:])
        ):
            raise ValueError("executed Action observation plan digest MUST be canonical")
        raw = await self._store.read_state(f"{self._KEY_PREFIX}{canonical_action_id}:{plan_digest}")
        if raw is None:
            return None
        record = _decode_record(raw)
        if record.action_id != canonical_action_id or record.plan_digest != plan_digest:
            raise ValueError("stored executed Action observation identity changed on replay")
        authenticated = await self._verifier.verify(
            evidence=record.observation.evidence,
            claimed_context=record.observation.observation_context,
        )
        if authenticated != record.observation.observation_context:
            raise ValueError("executed Action observation authentication changed on replay")
        return record

    @classmethod
    def _key(cls, action: Action, artifacts: ResolvedReconciliationArtifacts) -> str:
        return f"{cls._KEY_PREFIX}{action.action_id}:{artifacts.plan.digest}"


def _record(
    *,
    action: Action,
    artifacts: ResolvedReconciliationArtifacts,
    execution_outcome: str,
    execution_receipt_ref: str | None,
    correlation_id: str,
    observation: ExecutedActionObservation,
    execution_mode: str = "unknown",
    execution_completed_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "producer_principal": "Heimdall",
        "action_id": str(action.action_id),
        "action_digest": _action_digest(action),
        "plan_digest": artifacts.plan.digest,
        "execution_outcome": execution_outcome,
        "execution_receipt_ref": execution_receipt_ref,
        "correlation_id": correlation_id,
        "execution_mode": execution_mode,
        "execution_completed_at": (
            execution_completed_at.isoformat() if execution_completed_at is not None else None
        ),
        "observation": {
            "evidence": observation.evidence.model_dump(mode="json"),
            "observation_context": observation.observation_context.model_dump(mode="json"),
            "deadline": observation.deadline.isoformat(),
            "evaluated_at": observation.evaluated_at.isoformat(),
        },
    }


def _decode_record(raw: Mapping[str, Any]) -> RecordedExecutedActionObservation:
    try:
        if raw.get("schema_version") != "1.0.0" or raw.get("producer_principal") != "Heimdall":
            raise ValueError("record envelope changed")
        action_id = str(UUID(str(raw["action_id"])))
        if action_id != raw["action_id"]:
            raise ValueError("Action id is not canonical")
        plan_digest = str(raw["plan_digest"])
        observation_raw = raw["observation"]
        if not isinstance(observation_raw, Mapping):
            raise ValueError("observation is malformed")
        from fdai.core.ontology_platform.reconciliation_contracts import (
            AuthenticatedObservationContext,
            EffectObservationEnvelope,
        )

        observation = ExecutedActionObservation(
            evidence=EffectObservationEnvelope.model_validate(observation_raw["evidence"]),
            observation_context=AuthenticatedObservationContext.model_validate(
                observation_raw["observation_context"]
            ),
            deadline=datetime.fromisoformat(str(observation_raw["deadline"])),
            evaluated_at=datetime.fromisoformat(str(observation_raw["evaluated_at"])),
        )
        execution_mode = str(raw.get("execution_mode") or "unknown")
        if execution_mode not in {"shadow", "enforce", "unknown"}:
            raise ValueError("execution mode is invalid")
        completed_raw = raw.get("execution_completed_at")
        completed_at = (
            datetime.fromisoformat(str(completed_raw)) if completed_raw is not None else None
        )
        if completed_at is not None and (
            completed_at.tzinfo is None or completed_at.utcoffset() is None
        ):
            raise ValueError("execution completion is not timezone-aware")
        return RecordedExecutedActionObservation(
            action_id=action_id,
            plan_digest=plan_digest,
            execution_outcome=str(raw["execution_outcome"]),
            execution_mode=execution_mode,
            execution_completed_at=completed_at,
            execution_receipt_ref=(
                str(raw["execution_receipt_ref"])
                if raw.get("execution_receipt_ref") is not None
                else None
            ),
            correlation_id=str(raw["correlation_id"]),
            observation=observation,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("stored executed Action observation failed validation") from exc


def _parse(
    raw: Mapping[str, Any],
    *,
    action: Action,
    artifacts: ResolvedReconciliationArtifacts,
    execution_outcome: str,
    execution_receipt_ref: str | None,
    correlation_id: str,
) -> ExecutedActionObservation:
    expected = {
        "schema_version": "1.0.0",
        "producer_principal": "Heimdall",
        "action_id": str(action.action_id),
        "action_digest": _action_digest(action),
        "plan_digest": artifacts.plan.digest,
        "execution_outcome": execution_outcome,
        "execution_receipt_ref": execution_receipt_ref,
        "correlation_id": correlation_id,
    }
    if any(raw.get(key) != value for key, value in expected.items()):
        raise ValueError("executed Action observation does not match exact execution")
    observation_raw = raw.get("observation")
    if not isinstance(observation_raw, Mapping):
        raise ValueError("executed Action observation state is malformed")
    try:
        from datetime import datetime

        from fdai.core.ontology_platform.reconciliation_contracts import (
            AuthenticatedObservationContext,
            EffectObservationEnvelope,
        )

        return ExecutedActionObservation(
            evidence=EffectObservationEnvelope.model_validate(observation_raw["evidence"]),
            observation_context=AuthenticatedObservationContext.model_validate(
                observation_raw["observation_context"]
            ),
            deadline=datetime.fromisoformat(str(observation_raw["deadline"])),
            evaluated_at=datetime.fromisoformat(str(observation_raw["evaluated_at"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("executed Action observation state failed validation") from exc


def _action_digest(action: Action) -> str:
    from fdai.core.ontology_platform.reconciliation_contracts import (
        reconciliation_content_digest,
    )

    return reconciliation_content_digest(action.model_dump(mode="json"))


__all__ = [
    "ExecutedActionObservationConflictError",
    "RecordedExecutedActionObservation",
    "StateStoreExecutedActionObservationStore",
]
