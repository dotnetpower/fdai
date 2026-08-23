"""Durable Heimdall-owned independent observations for executed actions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from fdai.core.ontology_platform.reconciliation_binding import (
    ObservationContextVerifier,
    ResolvedReconciliationArtifacts,
)
from fdai.core.ontology_platform.reconciliation_producer import ExecutedActionObservation
from fdai.shared.contracts.models import Action
from fdai.shared.providers.state_store import StateStore


class ExecutedActionObservationConflictError(RuntimeError):
    """The same executed Action was assigned different independent evidence."""


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
        "observation": {
            "evidence": observation.evidence.model_dump(mode="json"),
            "observation_context": observation.observation_context.model_dump(mode="json"),
            "deadline": observation.deadline.isoformat(),
            "evaluated_at": observation.evaluated_at.isoformat(),
        },
    }


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
    "StateStoreExecutedActionObservationStore",
]
