"""Exemption lifecycle coordinator - scheduled sweep + lifecycle audit evidence.

Combines the pure decision core
(:func:`fdai.rule_catalog.schema.exemption_lifecycle.plan_exemption_lifecycle`)
with an injected :class:`~fdai.shared.providers.exemption_lifecycle.ExemptionLifecycleNotifier`
and the standard append-only :class:`~fdai.shared.providers.state_store.StateStore`
audit boundary (the same seam every other control-loop audit entry uses - no
``object.override`` bus topic, no owning agent; see
agent-pantheon.instructions.md).

Idempotency: an ahead-of-expiry alert is delivered **at most once** per
exemption. ``StateStore.write_state_with_audit_if_absent`` atomically claims a
per-exemption marker key and appends the audit entry in one call, so a
re-entrant or concurrently scheduled sweep never double-notifies (mirrors
:class:`fdai.core.hil_resume.load_control.ApprovalReminderDispatcher`).

This coordinator only *decides and evidences*; it does not itself flip an
exemption's ``state`` to ``expired`` on disk - that terminal catalog-as-code
mutation stays with ``scripts/governance/exemption-expire.py`` (a reviewed PR
changes the tracked artifact, matching the GitOps control flow in
rule-governance.md). The coordinator still emits an audit entry for a due
``EXPIRE`` decision so the lifecycle evidence trail is complete even before the
tracked file is updated.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from fdai.rule_catalog.schema.exemption import Exemption
from fdai.rule_catalog.schema.exemption_lifecycle import (
    ExemptionAssignmentBinding,
    ExemptionExpiryCommand,
    ExemptionExpiryDigest,
    ExemptionExpiryDigestItem,
    ExemptionLifecycleAction,
    ExemptionLifecycleDecision,
    build_exemption_expiry_command,
    exemption_revision,
    plan_exemption_lifecycle,
)
from fdai.shared.contracts.models import Event
from fdai.shared.providers.event_bus import EventBus, PublishReceipt
from fdai.shared.providers.exemption_lifecycle import ExemptionLifecycleNotifier
from fdai.shared.providers.state_store import StateStore

_STATE_KEY_PREFIX = "governance:exemption-lifecycle:"


@dataclass(frozen=True, slots=True)
class ExemptionLifecycleRunResult:
    """Summary of one coordinator sweep - evidence for a scheduled-run audit."""

    evaluated: int
    alerted: int
    expired_due: int
    commands_published: int = 0
    commands_held: int = 0


class ExemptionExpiryCommandPublisher(Protocol):
    """Publish one expiry proposal into the normal typed action pipeline."""

    async def publish(self, command: ExemptionExpiryCommand) -> PublishReceipt: ...


class EventBusExemptionExpiryCommandPublisher:
    """EventBus adapter that attributes a scheduled proposal without impersonating an operator."""

    def __init__(self, *, event_bus: EventBus, topic: str) -> None:
        if not topic.strip():
            raise ValueError("expiry command topic MUST be non-empty")
        self._event_bus = event_bus
        self._topic = topic

    async def publish(self, command: ExemptionExpiryCommand) -> PublishReceipt:
        event_id = str(uuid5(NAMESPACE_URL, f"fdai.exemption-expiry://{command.idempotency_key}"))
        event = Event.model_validate(
            {
                "schema_version": "1.0.0",
                "event_id": event_id,
                "idempotency_key": command.idempotency_key,
                "correlation_id": f"exemption-expiry:{command.exemption_id}",
                "source": "scheduler",
                "event_type": "operator_request",
                "resource_ref": command.scope_ref,
                "payload": {
                    "operator_request": {
                        "initiator_principal": "ExemptionLifecycleCoordinator",
                        "action_type": "governance.reapply-rule-assignment",
                        "params": command.action_params(),
                    },
                    "scheduled_task": {
                        "command_schema_version": command.schema_version,
                        "issued_at": command.issued_at.isoformat(),
                        "grants_authority": False,
                    },
                },
                "detected_at": command.issued_at.isoformat(),
                "ingested_at": command.issued_at.isoformat(),
                "mode": "shadow",
            }
        )
        return await self._event_bus.publish(
            self._topic,
            command.assignment_id,
            event.model_dump(mode="json"),
        )


def _audit_entry(decision: ExemptionLifecycleDecision, *, kind: str) -> dict[str, object]:
    return {
        "actor": "fdai.delivery.exemption_lifecycle",
        "producer_principal": "Saga",
        "action_kind": kind,
        "mode": "shadow",
        "idempotency_key": f"{_STATE_KEY_PREFIX}{decision.exemption_id}",
        "correlation_id": decision.exemption_id,
        "exemption_id": decision.exemption_id,
        "rule_id": decision.rule_id,
        "expires_at": decision.expires_at.isoformat(),
        "recorded_at": decision.at.isoformat(),
    }


class ExemptionLifecycleCoordinator:
    """Scheduled sweep over the immutable exemption catalog.

    ``run_once`` is safe to call repeatedly (e.g. from a periodic tick or the
    standalone CLI): each exemption's ahead-of-expiry alert fires exactly once
    across any number of calls/replicas, and every decision - alert or
    already-due expiry - leaves an append-only audit entry
    (``governance.exemption_alert`` / ``governance.exemption_expiry_due``)
    that also feeds the discovery loop's operational-signal input
    (rule-governance.md "Feedback Loop"; ``operational_learning/discovery_contracts.py``
    ``DiscoverySignalKind.OPERATIONAL``).
    """

    def __init__(
        self,
        *,
        exemptions: Sequence[Exemption],
        notifier: ExemptionLifecycleNotifier,
        audit_store: StateStore,
        alert_lead_days: int,
        assignment_bindings: Mapping[str, ExemptionAssignmentBinding] | None = None,
        command_publisher: ExemptionExpiryCommandPublisher | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._exemptions = tuple(exemptions)
        self._by_id = {exemption.id: exemption for exemption in self._exemptions}
        self._notifier = notifier
        self._audit_store = audit_store
        self._alert_lead = timedelta(days=alert_lead_days)
        self._assignment_bindings = dict(assignment_bindings or {})
        self._command_publisher = command_publisher
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def run_once(self, *, now: datetime | None = None) -> ExemptionLifecycleRunResult:
        moment = now or self._clock()
        decisions = plan_exemption_lifecycle(
            self._exemptions,
            now=moment,
            alert_lead=self._alert_lead,
        )
        alerted = 0
        expired_due = 0
        published = 0
        held = 0
        alert_attempts: list[tuple[str, int, ExemptionLifecycleDecision]] = []
        for decision in decisions:
            if decision.action is ExemptionLifecycleAction.ALERT_AHEAD_OF_EXPIRY:
                attempt = await self._claim_alert_attempt(decision, moment=moment)
                if attempt is not None:
                    key, revision = attempt
                    alert_attempts.append((key, revision, decision))
            else:
                claimed = await self._audit_store.write_state_with_audit_if_absent(
                    f"{_STATE_KEY_PREFIX}expiry-due:{decision.exemption_id}",
                    {
                        "exemption_id": decision.exemption_id,
                        "expiry_due_recorded_at": moment.isoformat(),
                    },
                    _audit_entry(decision, kind="governance.exemption_expiry_due"),
                )
                if claimed:
                    expired_due += 1
                disposition = await self._publish_expiry_command(decision, moment=moment)
                published += disposition == "published"
                held += disposition == "held"
        if alert_attempts:
            digest = ExemptionExpiryDigest(
                schema_version="1.0.0",
                generated_at=moment,
                items=tuple(
                    ExemptionExpiryDigestItem(
                        exemption_id=decision.exemption_id,
                        exemption_revision=exemption_revision(self._by_id[decision.exemption_id]),
                        rule_id=decision.rule_id,
                        requested_by=str(self._by_id[decision.exemption_id].requested_by),
                        expires_at=decision.expires_at,
                    )
                    for _, _, decision in alert_attempts
                ),
            )
            try:
                await self._notifier.notify_expiry_digest(digest=digest)
            except Exception as exc:  # noqa: BLE001 - audit every item and retain retry state
                for key, revision, decision in alert_attempts:
                    await self._complete_alert_attempt(
                        key,
                        decision,
                        revision=revision,
                        status="failed",
                        moment=moment,
                        error_kind=type(exc).__name__,
                    )
                raise
            for key, revision, decision in alert_attempts:
                await self._complete_alert_attempt(
                    key,
                    decision,
                    revision=revision,
                    status="delivered",
                    moment=moment,
                )
            alerted = len(alert_attempts)
        return ExemptionLifecycleRunResult(
            evaluated=len(decisions),
            alerted=alerted,
            expired_due=expired_due,
            commands_published=published,
            commands_held=held,
        )

    async def _publish_expiry_command(
        self,
        decision: ExemptionLifecycleDecision,
        *,
        moment: datetime,
    ) -> str:
        binding = self._assignment_bindings.get(decision.exemption_id)
        if binding is None or self._command_publisher is None:
            reason = (
                "assignment_binding_unavailable"
                if binding is None
                else "command_publisher_unavailable"
            )
            await self._audit_store.write_state_with_audit_if_absent(
                f"{_STATE_KEY_PREFIX}expiry-held:{decision.exemption_id}:{reason}",
                {"exemption_id": decision.exemption_id, "reason": reason},
                {
                    **_audit_entry(decision, kind="governance.exemption_expiry_held"),
                    "reason": reason,
                },
            )
            return "held"

        command = build_exemption_expiry_command(
            self._by_id[decision.exemption_id],
            binding,
            issued_at=moment,
        )
        key = f"{_STATE_KEY_PREFIX}expiry-command:{command.idempotency_key}"
        if await self._audit_store.read_state(key) is not None:
            return "duplicate"
        try:
            receipt = await self._command_publisher.publish(command)
        except Exception as exc:  # noqa: BLE001 - unknown delivery is audited and retried by key
            await self._audit_store.append_audit_entry(
                {
                    **_audit_entry(decision, kind="governance.exemption_expiry_publish_failed"),
                    "command_idempotency_key": command.idempotency_key,
                    "error_kind": type(exc).__name__,
                    "outcome": "held_unknown_delivery",
                }
            )
            raise
        claimed = await self._audit_store.write_state_with_audit_if_absent(
            key,
            {
                "exemption_id": command.exemption_id,
                "command_idempotency_key": command.idempotency_key,
                "topic": receipt.topic,
                "partition": receipt.partition,
                "offset": receipt.offset,
                "outcome": "broker_accepted_not_executed",
            },
            {
                **_audit_entry(decision, kind="governance.exemption_expiry_command_published"),
                "command_idempotency_key": command.idempotency_key,
                "assignment_id": command.assignment_id,
                "active_exemption_revision": command.active_exemption_revision,
                "expired_exemption_revision": command.expired_exemption_revision,
                "outcome": "broker_accepted_not_executed",
            },
        )
        return "published" if claimed else "duplicate"

    async def _claim_alert_attempt(
        self,
        decision: ExemptionLifecycleDecision,
        *,
        moment: datetime,
    ) -> tuple[str, int] | None:
        key = f"{_STATE_KEY_PREFIX}alert:{decision.exemption_id}"
        value = {
            "revision": 1,
            "exemption_id": decision.exemption_id,
            "status": "attempted",
            "attempted_at": moment.isoformat(),
        }
        if await self._audit_store.write_state_with_audit_if_absent(
            key,
            value,
            _audit_entry(decision, kind="governance.exemption_alert_attempted"),
        ):
            return key, 1
        existing = await self._audit_store.read_state(key)
        if existing is None:
            raise RuntimeError("exemption alert claim disappeared")
        if existing.get("status") != "failed":
            return None
        revision = existing.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError("exemption alert retry state has an invalid revision")
        retry = {
            **dict(existing),
            "revision": revision + 1,
            "status": "attempted",
            "attempted_at": moment.isoformat(),
        }
        claimed = await self._audit_store.compare_and_set_state_with_audit(
            key,
            retry,
            expected_revision=revision,
            audit_entry=_audit_entry(decision, kind="governance.exemption_alert_retried"),
        )
        return (key, revision + 1) if claimed else None

    async def _complete_alert_attempt(
        self,
        key: str,
        decision: ExemptionLifecycleDecision,
        *,
        revision: int,
        status: str,
        moment: datetime,
        error_kind: str | None = None,
    ) -> None:
        value = {
            "revision": revision + 1,
            "exemption_id": decision.exemption_id,
            "status": status,
            "completed_at": moment.isoformat(),
            "error_kind": error_kind,
        }
        audit = _audit_entry(
            decision,
            kind=(
                "governance.exemption_alert"
                if status == "delivered"
                else "governance.exemption_alert_failed"
            ),
        )
        audit["error_kind"] = error_kind
        completed = await self._audit_store.compare_and_set_state_with_audit(
            key,
            value,
            expected_revision=revision,
            audit_entry=audit,
        )
        if not completed:
            raise RuntimeError("exemption alert attempt lost its revision")


__all__ = [
    "EventBusExemptionExpiryCommandPublisher",
    "ExemptionExpiryCommandPublisher",
    "ExemptionLifecycleCoordinator",
    "ExemptionLifecycleRunResult",
]
