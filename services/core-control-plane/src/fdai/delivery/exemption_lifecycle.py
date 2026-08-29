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

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai.rule_catalog.schema.exemption import Exemption
from fdai.rule_catalog.schema.exemption_lifecycle import (
    ExemptionLifecycleAction,
    ExemptionLifecycleDecision,
    plan_exemption_lifecycle,
)
from fdai.shared.providers.exemption_lifecycle import ExemptionLifecycleNotifier
from fdai.shared.providers.state_store import StateStore

_STATE_KEY_PREFIX = "governance:exemption-lifecycle:"


@dataclass(frozen=True, slots=True)
class ExemptionLifecycleRunResult:
    """Summary of one coordinator sweep - evidence for a scheduled-run audit."""

    evaluated: int
    alerted: int
    expired_due: int


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
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._exemptions = tuple(exemptions)
        self._by_id = {exemption.id: exemption for exemption in self._exemptions}
        self._notifier = notifier
        self._audit_store = audit_store
        self._alert_lead = timedelta(days=alert_lead_days)
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
        for decision in decisions:
            if decision.action is ExemptionLifecycleAction.ALERT_AHEAD_OF_EXPIRY:
                attempt = await self._claim_alert_attempt(decision, moment=moment)
                if attempt is not None:
                    key, revision = attempt
                    try:
                        await self._notifier.notify_ahead_of_expiry(
                            exemption=self._by_id[decision.exemption_id],
                            decision=decision,
                        )
                    except Exception as exc:  # noqa: BLE001 - audit and retain retry state
                        await self._complete_alert_attempt(
                            key,
                            decision,
                            revision=revision,
                            status="failed",
                            moment=moment,
                            error_kind=type(exc).__name__,
                        )
                        raise
                    await self._complete_alert_attempt(
                        key,
                        decision,
                        revision=revision,
                        status="delivered",
                        moment=moment,
                    )
                    alerted += 1
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
        return ExemptionLifecycleRunResult(
            evaluated=len(decisions),
            alerted=alerted,
            expired_due=expired_due,
        )

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


__all__ = ["ExemptionLifecycleCoordinator", "ExemptionLifecycleRunResult"]
