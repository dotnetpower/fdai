"""Reconstruct retained execution and effect journals without producing source evidence."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.alert_noise_plan import AlertEffectObservation
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.detection.alert_noise.execution import AlertExecutionHeld
from fdai.core.detection.alert_noise.outcomes import (
    ALERT_RECOVERY_EFFECT_PURPOSE,
    AlertEffectContext,
    AlertExecutedActionRecord,
    alert_effect_deadline,
    alert_effect_key,
    alert_executed_action_key,
    alert_response_outcome,
    classify_alert_effect,
)
from fdai.core.executor.safeguards import full_action_digest
from fdai.delivery.alert_noise_evidence import AdmittedAlertRecord, exact_alert_model
from fdai.shared.providers.state_store import StateStore

AlertEffectPublish = Callable[[str, str, dict[str, Any]], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class AdmittedAlertEffect:
    """One detached independent observation and the actual dispatch context behind it."""

    context: AlertEffectContext
    observation: AlertEffectObservation
    record: AdmittedAlertRecord
    effect_ref: str


async def read_alert_execution(
    store: StateStore,
    action_digest: str,
) -> AlertExecutedActionRecord | None:
    """Read the exact retained executor record; a lookup key never substitutes for its Action."""
    raw = await store.read_state(alert_executed_action_key(action_digest))
    if raw is None:
        return None
    result = exact_alert_model(AlertExecutedActionRecord, dict(raw))
    if result.source_event.action_digest != action_digest:
        raise AlertExecutionHeld("alert_effect_retained_action_mismatch")
    return result


def alert_effect_journal(result: AdmittedAlertEffect, *, now: datetime) -> dict[str, Any]:
    """Reconstruct the observation journal from an independently admitted reader result."""
    context, admitted = result.context, result.record
    response = alert_response_outcome(
        context, result.observation, receipt_digest=admitted.receipt_digest, now=now
    )
    return {
        "schema_version": "1.0.0",
        "actor_agent": "Heimdall",
        "execution_ref": alert_executed_action_key(full_action_digest(context.execution.action)),
        "effect_ref": result.effect_ref,
        "receipt_digest": admitted.receipt_digest,
        "effect_outcome": classify_alert_effect(context, result.observation, now=now),
        "response_outcome": response.model_dump(mode="json") if response else None,
        "execution_authority": False,
        "promotion_authority": False,
        "process_completed": False,
    }


def alert_missing_effect_journal(
    context: AlertEffectContext,
    *,
    source_revision: str,
    recorded_at: datetime,
) -> dict[str, Any]:
    """Describe a missed deadline, not an observation, receipt, failure count or recovery proof."""
    deadline = alert_effect_deadline(context)
    if recorded_at.tzinfo is None or recorded_at < deadline:
        raise AlertExecutionHeld("alert_effect_deadline_not_elapsed")
    return {
        "schema_version": "1.0.0",
        "actor_agent": "Heimdall",
        "execution_ref": alert_executed_action_key(full_action_digest(context.execution.action)),
        "effect_ref": alert_effect_key(
            plan_digest=digest_record(context.execution.plan),
            dispatch_ref=context.execution.dispatch_ref,
        ),
        "receipt_digest": None,
        "response_outcome": None,
        "evidence_status": "unknown",
        "effect_outcome": (
            "recovery_incomplete"
            if context.purpose == ALERT_RECOVERY_EFFECT_PURPOSE
            else "recovery_required"
        ),
        "reason": "alert_effect_independent_proof_unavailable_at_deadline",
        "observation_deadline": deadline.isoformat(),
        "source_revision": source_revision,
        "safeguard_bundle_digest": context.safeguard_bundle_digest,
        "publication_receipt_digest": content_digest(
            context.execution.model_dump(mode="json")["publication_receipt"]
        ),
        "recorded_at": recorded_at.isoformat(),
        "execution_authority": False,
        "promotion_authority": False,
        "process_completed": False,
    }
