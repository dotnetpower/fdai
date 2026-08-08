"""Out-of-Band Change Safety detector.

Implements the shadow-mode attribution + response pipeline documented in
[phase-1-rule-catalog-t0.md § Out-of-Band Detection]:

1. **Signal source** - Azure Activity Log records already flowing
   through the Kafka event-ingest topic (``aw.change.events``). The
   detector is invoked BEFORE :class:`~fdai.core.trust_router.TrustRouter`
   by :class:`~fdai.core.control_loop.ControlLoop` for events whose
   ``signal_kind == "azure.activity_log"``; every other event stream
   passes through unchanged.
2. **Attribution** - each event is classified into exactly one of
   :class:`ChangeAttribution` values:

   - :attr:`~ChangeAttribution.AUTHORIZED` - the actor identity is a
     known pipeline principal, OR the event carries a ``correlation_id``
     that links to a merged remediation PR.
   - :attr:`~ChangeAttribution.SUPPRESSED` - the event falls inside the
     per-resource-type settling window (default 60s) used to eat
     propagation lag and reconcile noise. The suppression reason is
     recorded so the audit trail keeps the false-positive rate
     measurable per the phase-1 exit criterion.
   - :attr:`~ChangeAttribution.OUT_OF_BAND` - the change appears to
     originate outside a merged remediation PR / known pipeline. This
     is the only attribution that produces a shadow reconcile PR and
     an alert on the ``aw.change.out-of-band`` topic.

3. **Response** - for :attr:`~ChangeAttribution.OUT_OF_BAND` the
   detector emits (in this exact order):

   a. an audit entry (append-only, shadow mode);
   b. an alert :class:`~fdai.shared.providers.event_bus.EventBus`
      record on ``aw.change.out-of-band`` (never a Kafka publish keyed
      globally - always per-resource for ordering);
   c. a **shadow reconcile PR** through the injected
      :class:`~fdai.shared.providers.remediation_pr.RemediationPrPublisher`.

   The PR is a draft, carries the ``shadow`` label, and MUST NOT
   auto-revert; the phase-1 doc is explicit that revert / reconcile
   execution is gated off until phase 2.

Design boundaries
-----------------

- This module lives in ``core/verticals`` and MUST stay CSP-neutral:
  it depends only on the CSP-neutral Protocols under
  ``fdai.shared.providers``. No ``azure.*`` import, no
  ``fdai.delivery.*`` import (enforced by
  :file:`scripts/quality/architecture/check-core-imports.sh`).
- Attribution is a **classification only** - the detector never mutates
  state, never revert, never blocks the primary pipeline. On any
  publisher / bus error the detector still records the audit entry
  and returns a failure-tagged outcome so a monitor can page on it.
- Every terminal path writes exactly one audit entry - the top-level
  invariant from :doc:`.github/instructions/architecture.instructions`
  applies here too.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final
from uuid import UUID, uuid5

from fdai.shared.contracts.models import Event, Mode
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.pipeline_principal import (
    PipelinePrincipalRegistry,
)
from fdai.shared.providers.remediation_pr import (
    RemediationPr,
    RemediationPrPublisher,
)
from fdai.shared.providers.remediation_pr_ledger import (
    RemediationPrLedger,
)
from fdai.shared.providers.state_store import StateStore

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

ACTIVITY_LOG_SIGNAL_KIND: Final[str] = "azure.activity_log"
"""Value ``ControlLoop`` inspects on ``event.payload['signal_kind']`` to
decide whether to invoke the detector. Kept here so the sender + the
receiver share one canonical string."""

OUT_OF_BAND_ALERT_TOPIC: Final[str] = "aw.change.out-of-band"
"""Kafka topic (CSP-neutral naming) the detector uses for its alert
events. Complements the day-zero ``aw.change.events`` topic in
:file:`infra/main.tf` - a fork MAY override via config, but the string
lives here so tests do not drift from wire."""

DEFAULT_SETTLING_WINDOW_SECONDS: Final[int] = 60
"""Debounce window applied when a resource-type-specific window is
absent; matches the phase-1 doc ("default 60s") and the value
tests import from this module."""

_ATTRIBUTION_NAMESPACE: Final[UUID] = UUID("6b1b6f2c-5a3e-4a91-8f1a-8b8a7e2f9d10")
"""Deterministic UUID5 namespace for the alert event id - keeps a
re-delivered signal producing the same alert event id so the audit
trail can be reconciled across retries."""


# ---------------------------------------------------------------------------
# Enums + dataclasses
# ---------------------------------------------------------------------------


class ChangeAttribution(StrEnum):
    """Attribution outcome for one Activity Log event."""

    AUTHORIZED = "authorized"
    SUPPRESSED = "suppressed"
    OUT_OF_BAND = "out_of_band"


class DetectorOutcome(StrEnum):
    """Terminal outcome for one :meth:`ChangeSafetyDetector.detect` call."""

    AUTHORIZED = "authorized"
    """Change is attributed to a known pipeline principal or a merged
    remediation PR - no reconcile PR, no alert. Audit only."""

    SUPPRESSED = "suppressed"
    """Change fell inside the resource-type settling window - audit
    the suppression with the reason so the false-positive rate is
    measurable."""

    OUT_OF_BAND_EMITTED = "out_of_band_emitted"
    """Change classified as out-of-band and BOTH the shadow reconcile
    PR + alert event were published successfully."""

    OUT_OF_BAND_PARTIAL = "out_of_band_partial"
    """Change classified as out-of-band but one of the two emissions
    (reconcile PR OR alert event) raised; the audit entry records
    which one failed so an operator can retry."""

    NOT_ACTIVITY_LOG = "not_activity_log"
    """Event's ``signal_kind`` did not match - the detector is a no-op
    for this event. No audit is written (the primary pipeline audits
    the routing decision)."""


@dataclass(frozen=True, slots=True)
class ChangeSafetyDetectorConfig:
    """Tunable detector policy - never contains customer values.

    ``settling_windows`` is a per-resource-type override map. A missing
    entry falls back to :attr:`default_settling_window`. The upstream
    default is 60s (phase-1 doc); a fork MAY tune per resource type via
    a config file loaded at the composition root.
    """

    default_settling_window: timedelta = field(
        default_factory=lambda: timedelta(seconds=DEFAULT_SETTLING_WINDOW_SECONDS)
    )
    settling_windows: Mapping[str, timedelta] = field(default_factory=dict)
    alert_topic: str = OUT_OF_BAND_ALERT_TOPIC

    def window_for(self, resource_type: str | None) -> timedelta:
        if resource_type is not None:
            override = self.settling_windows.get(resource_type)
            if override is not None:
                return override
        return self.default_settling_window


@dataclass(frozen=True, slots=True)
class ChangeSafetyDecision:
    """Frozen record produced by :meth:`ChangeSafetyDetector.detect`.

    Downstream code MUST treat this as the audit-authoritative view;
    the :class:`StateStore` entry is derived from it.
    """

    event_id: str
    attribution: ChangeAttribution
    outcome: DetectorOutcome
    actor: str | None
    reason: str
    resource_type: str | None = None
    resource_id: str | None = None
    alert_topic: str | None = None
    alert_offset: int | None = None
    pr_ref: str | None = None
    pr_url: str | None = None
    correlated_pr_ref: str | None = None
    """The merged PR ref returned by
    :meth:`RemediationPrLedger.find_correlation` when attribution is
    AUTHORIZED via correlation."""


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class ChangeSafetyDetector:
    """Out-of-band Change Safety detector - shadow-mode only.

    The detector composes three CSP-neutral Protocols:

    - :class:`PipelinePrincipalRegistry` - actor-id → is-known-pipeline?
    - :class:`RemediationPrLedger` - correlation_id → merged PR ref
    - :class:`RemediationPrPublisher` + :class:`EventBus` +
      :class:`StateStore` - the shadow-response fan-out.

    The upstream default settling window is 60s; a fork provides its own
    :class:`ChangeSafetyDetectorConfig` at the composition root.
    """

    def __init__(
        self,
        *,
        principal_registry: PipelinePrincipalRegistry,
        ledger: RemediationPrLedger,
        publisher: RemediationPrPublisher,
        event_bus: EventBus,
        audit_store: StateStore,
        config: ChangeSafetyDetectorConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._principals = principal_registry
        self._ledger = ledger
        self._publisher = publisher
        self._event_bus = event_bus
        self._audit_store = audit_store
        self._config = config or ChangeSafetyDetectorConfig()
        # Injectable clock keeps the settling-window logic deterministic
        # in tests without freezegun. Callers pass ``lambda: fixed_ts``.
        self._clock = clock or _utcnow

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_activity_log(self, event: Event) -> bool:
        """Return ``True`` iff the detector should classify ``event``.

        Trigger rule: ``payload.signal_kind == "azure.activity_log"``.
        This mirrors the wire-level contract the Kafka producer stamps
        on every Activity Log record; other event streams (Resource
        Health, cost anomalies, ...) skip the detector. Kept public so
        :class:`ControlLoop` uses the same predicate the detector
        would use internally.
        """
        signal_kind = event.payload.get("signal_kind")
        return signal_kind == ACTIVITY_LOG_SIGNAL_KIND

    async def detect(self, event: Event) -> ChangeSafetyDecision:
        """Classify ``event``, side-effect on out-of-band, audit every path.

        Non-activity-log events short-circuit with
        :attr:`DetectorOutcome.NOT_ACTIVITY_LOG` and NO audit - the
        control loop writes the routing audit for the primary path
        after the detector returns.
        """
        if not self.is_activity_log(event):
            return ChangeSafetyDecision(
                event_id=str(event.event_id),
                attribution=ChangeAttribution.AUTHORIZED,  # placeholder - outcome trumps
                outcome=DetectorOutcome.NOT_ACTIVITY_LOG,
                actor=None,
                reason="event.payload.signal_kind != azure.activity_log",
            )

        actor = _extract_actor(event.payload)
        resource_type = _extract_resource_type(event.payload)
        resource_id = _extract_resource_id(event)

        # ---- Attribution ----------------------------------------------------
        attribution, reason, correlated_pr = self._attribute(
            event=event, actor=actor, resource_type=resource_type
        )

        if attribution is ChangeAttribution.AUTHORIZED:
            decision = ChangeSafetyDecision(
                event_id=str(event.event_id),
                attribution=attribution,
                outcome=DetectorOutcome.AUTHORIZED,
                actor=actor,
                reason=reason,
                resource_type=resource_type,
                resource_id=resource_id,
                correlated_pr_ref=correlated_pr,
            )
            await self._write_audit(event=event, decision=decision)
            return decision

        if attribution is ChangeAttribution.SUPPRESSED:
            decision = ChangeSafetyDecision(
                event_id=str(event.event_id),
                attribution=attribution,
                outcome=DetectorOutcome.SUPPRESSED,
                actor=actor,
                reason=reason,
                resource_type=resource_type,
                resource_id=resource_id,
            )
            await self._write_audit(event=event, decision=decision)
            return decision

        # ---- OUT_OF_BAND - shadow response ---------------------------------
        alert_topic = self._config.alert_topic
        alert_offset: int | None = None
        alert_error: str | None = None
        pr_ref: str | None = None
        pr_url: str | None = None
        pr_error: str | None = None

        # 1. Alert event on aw.change.out-of-band.
        try:
            receipt = await self._event_bus.publish(
                alert_topic,
                resource_id or str(event.event_id),
                _alert_payload(event=event, actor=actor, reason=reason, resource_id=resource_id),
            )
            alert_offset = receipt.offset
        except Exception as exc:  # noqa: BLE001 - fail-close: audit and continue
            alert_error = _short_exc(exc)

        # 2. Shadow reconcile PR.
        try:
            pr = _build_reconcile_pr(
                event=event,
                actor=actor,
                resource_id=resource_id,
                resource_type=resource_type,
                reason=reason,
            )
            pr_receipt = await self._publisher.publish(pr)
            pr_ref = pr_receipt.pr_ref
            pr_url = pr_receipt.url
        except Exception as exc:  # noqa: BLE001 - same fail-close policy
            pr_error = _short_exc(exc)

        outcome = (
            DetectorOutcome.OUT_OF_BAND_EMITTED
            if alert_error is None and pr_error is None
            else DetectorOutcome.OUT_OF_BAND_PARTIAL
        )

        decision = ChangeSafetyDecision(
            event_id=str(event.event_id),
            attribution=ChangeAttribution.OUT_OF_BAND,
            outcome=outcome,
            actor=actor,
            reason=reason,
            resource_type=resource_type,
            resource_id=resource_id,
            alert_topic=alert_topic,
            alert_offset=alert_offset,
            pr_ref=pr_ref,
            pr_url=pr_url,
        )
        await self._write_audit(
            event=event,
            decision=decision,
            extra={
                "alert_error": alert_error,
                "pr_error": pr_error,
            },
        )
        return decision

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _attribute(
        self,
        *,
        event: Event,
        actor: str | None,
        resource_type: str | None,
    ) -> tuple[ChangeAttribution, str, str | None]:
        """Return ``(attribution, reason, correlated_pr_ref)``."""
        if actor is not None and self._principals.contains(actor):
            return (
                ChangeAttribution.AUTHORIZED,
                f"actor:{actor} is a registered pipeline principal",
                None,
            )
        if event.correlation_id:
            pr_ref = self._ledger.find_correlation(event.correlation_id)
            if pr_ref:
                return (
                    ChangeAttribution.AUTHORIZED,
                    f"correlation_id:{event.correlation_id} → merged PR {pr_ref}",
                    pr_ref,
                )

        # Settling window - suppress if the event is still within the
        # per-resource-type debounce horizon relative to now.
        window = self._config.window_for(resource_type)
        now = self._clock()
        # ``Event.detected_at`` is not tz-validated by the model, so a
        # producer that emits a naive ISO timestamp would make this
        # subtraction raise TypeError (offset-naive minus offset-aware) and
        # abort the control-loop pass. Treat a naive stamp as UTC (the
        # repo-wide convention) so detection stays robust.
        detected_at = event.detected_at
        if detected_at.tzinfo is None:
            detected_at = detected_at.replace(tzinfo=UTC)
        age = now - detected_at
        if age < window:
            seconds = int(window.total_seconds())
            return (
                ChangeAttribution.SUPPRESSED,
                (
                    f"event age {age.total_seconds():.3f}s within settling window "
                    f"{seconds}s for resource_type={resource_type!r}"
                ),
                None,
            )
        return (
            ChangeAttribution.OUT_OF_BAND,
            (
                f"actor:{actor or '<unknown>'} not a pipeline principal and no "
                "merged remediation PR correlated"
            ),
            None,
        )

    async def _write_audit(
        self,
        *,
        event: Event,
        decision: ChangeSafetyDecision,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "event_id": decision.event_id,
            "idempotency_key": event.idempotency_key,
            "actor": decision.actor,
            "action_kind": "change_safety.detector",
            "mode": Mode.SHADOW.value,
            "attribution": decision.attribution.value,
            "outcome": decision.outcome.value,
            "reason": decision.reason,
            "resource_type": decision.resource_type,
            "resource_id": decision.resource_id,
            "alert_topic": decision.alert_topic,
            "alert_offset": decision.alert_offset,
            "pr_ref": decision.pr_ref,
            "pr_url": decision.pr_url,
            "correlated_pr_ref": decision.correlated_pr_ref,
            "recorded_at": _utcnow().isoformat(),
        }
        if extra:
            for key, value in extra.items():
                if value is not None:
                    entry[key] = value
        await self._audit_store.append_audit_entry(entry)


# ---------------------------------------------------------------------------
# Helpers (module-private)
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    """Return the current UTC time; separate so it is monkeypatch-free."""
    return datetime.now(tz=UTC)


def _extract_actor(payload: Mapping[str, Any]) -> str | None:
    """Pull the pipeline actor id out of the payload.

    Accepts two shapes matching the ``azure.activity_log`` envelope in
    :file:`tools/publish_smoke_event.py` and the Kafka producer:

    1. ``payload['actor']['principal_id']`` - the canonical shape.
    2. ``payload['actor']`` as a plain string (legacy / test fixtures).
    """
    actor = payload.get("actor")
    if isinstance(actor, str) and actor:
        return actor
    if isinstance(actor, Mapping):
        pid = actor.get("principal_id")
        if isinstance(pid, str) and pid:
            return pid
    return None


def _extract_resource_type(payload: Mapping[str, Any]) -> str | None:
    """Pull ``resource_type`` - mirrors :mod:`fdai.core.trust_router`."""
    resource = payload.get("resource")
    if isinstance(resource, Mapping):
        rtype = resource.get("type") or resource.get("resource_type")
        if isinstance(rtype, str) and rtype:
            return rtype
    flat = payload.get("resource_type")
    if isinstance(flat, str) and flat:
        return flat
    return None


def _extract_resource_id(event: Event) -> str | None:
    resource = event.payload.get("resource")
    if isinstance(resource, Mapping):
        rid = resource.get("resource_id")
        if isinstance(rid, str) and rid:
            return rid
    return event.resource_ref or None


def _short_exc(exc: BaseException) -> str:
    """Keep audit strings bounded so a bad payload cannot bloat the log."""
    text = f"{type(exc).__name__}: {exc}"
    return text if len(text) <= 512 else text[:509] + "..."


def _alert_payload(
    *,
    event: Event,
    actor: str | None,
    reason: str,
    resource_id: str | None,
) -> Mapping[str, Any]:
    """Build the wire payload for the ``aw.change.out-of-band`` topic."""
    payload = {
        "schema_version": "1.0.0",
        "alert_event_id": str(uuid5(_ATTRIBUTION_NAMESPACE, str(event.event_id))),
        "source_event_id": str(event.event_id),
        "idempotency_key": event.idempotency_key,
        "actor": actor,
        "resource_id": resource_id,
        "correlation_id": event.correlation_id,
        "detected_at": event.detected_at.isoformat(),
        "reason": reason,
        "mode": Mode.SHADOW.value,
    }
    # Wrap so a caller cannot mutate the payload after the fact.
    return MappingProxyType(payload)


def _build_reconcile_pr(
    *,
    event: Event,
    actor: str | None,
    resource_id: str | None,
    resource_type: str | None,
    reason: str,
) -> RemediationPr:
    """Compose a shadow reconcile PR for an out-of-band change.

    The action_id is a UUID5 of the source event_id so a re-delivery
    hits the publisher's idempotency check without duplicating the PR.
    """
    action_id = uuid5(_ATTRIBUTION_NAMESPACE, f"reconcile:{event.event_id}")
    slug = (resource_id or f"event-{event.event_id}").replace("/", "_").replace(":", "_")
    patch_path = f"infra/envs/dev/{slug}.reconcile.tf"
    title = f"[shadow] Out-of-band change on {resource_id or 'unknown resource'} - reconcile to IaC"
    body = "\n".join(
        [
            "**Change Safety - out-of-band change detected**",
            "",
            f"- **Source event**: `{event.event_id}`",
            f"- **Idempotency key**: `{event.idempotency_key}`",
            f"- **Resource**: `{resource_id or '<unknown>'}`"
            + (f" (`{resource_type}`)" if resource_type else ""),
            f"- **Actor**: `{actor or '<unknown>'}`",
            f"- **Detected at**: {event.detected_at.isoformat()}",
            f"- **Attribution reason**: {reason}",
            "",
            "Shadow-mode reconcile PR - NOT mergeable, NEVER auto-reverts.",
            "Reconcile execution is gated off until phase 2 promotion.",
            "See `docs/roadmap/phases/phase-1-rule-catalog-t0.md § Out-of-Band Detection`.",
        ]
    )
    return RemediationPr(
        action_id=action_id,
        idempotency_key=f"oob::{event.idempotency_key}",
        rule_ids=("change_safety.out_of_band",),
        title=title,
        body=body,
        patch="# reconcile placeholder - populated by the reconcile renderer in phase 2\n",
        patch_path=patch_path,
        labels=("shadow", "change-safety", "out-of-band"),
        mode=Mode.SHADOW,
        metadata={
            "source_event_id": str(event.event_id),
            "detector": "change_safety",
            "attribution": ChangeAttribution.OUT_OF_BAND.value,
        },
    )


__all__ = [
    "ACTIVITY_LOG_SIGNAL_KIND",
    "ChangeAttribution",
    "ChangeSafetyDecision",
    "ChangeSafetyDetector",
    "ChangeSafetyDetectorConfig",
    "DEFAULT_SETTLING_WINDOW_SECONDS",
    "DetectorOutcome",
    "OUT_OF_BAND_ALERT_TOPIC",
]
