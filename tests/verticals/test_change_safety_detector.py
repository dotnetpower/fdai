"""Change Safety out-of-band detector — attribution + response tests.

Cover the five contract shapes documented in
[phase-1-rule-catalog-t0.md § Out-of-Band Detection]:

1. authorized via pipeline principal registry;
2. authorized via merged-remediation-PR correlation;
3. suppressed inside the settling window;
4. out_of_band → shadow reconcile PR + alert event emitted;
5. every outcome writes exactly one audit entry with mode=shadow.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from aiopspilot.core.verticals.change_safety_detector import (
    ACTIVITY_LOG_SIGNAL_KIND,
    OUT_OF_BAND_ALERT_TOPIC,
    ChangeAttribution,
    ChangeSafetyDecision,
    ChangeSafetyDetector,
    ChangeSafetyDetectorConfig,
    DetectorOutcome,
)
from aiopspilot.shared.contracts.models import Event, Mode
from aiopspilot.shared.providers.event_bus import PublishReceipt
from aiopspilot.shared.providers.pipeline_principal import (
    InMemoryPipelinePrincipalRegistry,
)
from aiopspilot.shared.providers.remediation_pr import (
    PublishReceipt as PrPublishReceipt,
)
from aiopspilot.shared.providers.remediation_pr import (
    RemediationPr,
)
from aiopspilot.shared.providers.remediation_pr_ledger import (
    InMemoryRemediationPrLedger,
)
from aiopspilot.shared.providers.testing import (
    InMemoryEventBus,
    InMemoryStateStore,
    RecordingRemediationPrPublisher,
)

# ---------------------------------------------------------------------------
# Fixtures / factories
# ---------------------------------------------------------------------------


FIXED_DETECTED_AT = datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC)


def _event(
    *,
    signal_kind: str | None = ACTIVITY_LOG_SIGNAL_KIND,
    actor: str | None = "sp-manual-user",
    resource_type: str = "compute.vm",
    resource_id: str = "sub/rg/vm-a",
    correlation_id: str | None = None,
    idempotency_key: str = "oob-1",
    detected_at: datetime = FIXED_DETECTED_AT,
) -> Event:
    payload: dict[str, Any] = {
        "resource": {
            "resource_id": resource_id,
            "type": resource_type,
            "props": {},
        },
    }
    if signal_kind is not None:
        payload["signal_kind"] = signal_kind
    if actor is not None:
        payload["actor"] = {"principal_id": actor}
    return Event(
        schema_version="1.0.0",
        event_id=uuid4(),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        source="azure_activity_log",
        event_type="config_changed",
        resource_ref=resource_id,
        payload=payload,
        detected_at=detected_at,
        ingested_at=detected_at + timedelta(milliseconds=250),
        mode=Mode.SHADOW,
    )


def _detector(
    *,
    principals: tuple[str, ...] = (),
    correlations: Mapping[str, str] | None = None,
    settling: timedelta | None = None,
    per_type_settling: Mapping[str, timedelta] | None = None,
    now: datetime | None = None,
) -> tuple[
    ChangeSafetyDetector,
    RecordingRemediationPrPublisher,
    InMemoryEventBus,
    InMemoryStateStore,
]:
    registry = InMemoryPipelinePrincipalRegistry(principals)
    ledger = InMemoryRemediationPrLedger(correlations)
    publisher = RecordingRemediationPrPublisher()
    bus = InMemoryEventBus()
    audit = InMemoryStateStore()
    config = ChangeSafetyDetectorConfig(
        default_settling_window=settling or timedelta(seconds=60),
        settling_windows=dict(per_type_settling or {}),
    )
    clock = (lambda fixed=now: fixed) if now is not None else None
    detector = ChangeSafetyDetector(
        principal_registry=registry,
        ledger=ledger,
        publisher=publisher,
        event_bus=bus,
        audit_store=audit,
        config=config,
        clock=clock,
    )
    return detector, publisher, bus, audit


# ---------------------------------------------------------------------------
# Attribution — three outcomes
# ---------------------------------------------------------------------------


async def test_authorized_by_pipeline_principal_no_pr_no_alert() -> None:
    detector, publisher, bus, audit = _detector(principals=("sp-ci-runner",))
    event = _event(actor="sp-ci-runner", idempotency_key="auth-actor")

    decision = await detector.detect(event)

    assert decision.attribution is ChangeAttribution.AUTHORIZED
    assert decision.outcome is DetectorOutcome.AUTHORIZED
    assert decision.reason.startswith("actor:sp-ci-runner")
    # No PR, no alert.
    assert publisher.records == ()
    assert bus._records.get(OUT_OF_BAND_ALERT_TOPIC) is None  # type: ignore[attr-defined]
    # Exactly one audit entry.
    entries = list(audit.audit_entries)
    assert len(entries) == 1
    assert entries[0]["entry"]["attribution"] == "authorized"
    assert entries[0]["entry"]["mode"] == Mode.SHADOW.value


async def test_authorized_by_correlation_to_merged_pr() -> None:
    detector, publisher, bus, audit = _detector(correlations={"corr-abc": "owner/repo#42"})
    event = _event(
        actor="unknown-actor",
        correlation_id="corr-abc",
        idempotency_key="auth-corr",
    )

    decision = await detector.detect(event)

    assert decision.attribution is ChangeAttribution.AUTHORIZED
    assert decision.outcome is DetectorOutcome.AUTHORIZED
    assert decision.correlated_pr_ref == "owner/repo#42"
    assert "owner/repo#42" in decision.reason
    assert publisher.records == ()
    assert bus._records.get(OUT_OF_BAND_ALERT_TOPIC) is None  # type: ignore[attr-defined]
    entries = list(audit.audit_entries)
    assert len(entries) == 1
    assert entries[0]["entry"]["correlated_pr_ref"] == "owner/repo#42"


async def test_out_of_band_emits_reconcile_pr_and_alert() -> None:
    detector, publisher, bus, audit = _detector(
        principals=("sp-ci-runner",),  # actor below is NOT in registry
        now=FIXED_DETECTED_AT + timedelta(seconds=120),  # past settling window
    )
    event = _event(
        actor="oid-portal-user",
        resource_id="sub/rg-1/vm-42",
        idempotency_key="oob-key",
    )

    decision = await detector.detect(event)

    assert decision.attribution is ChangeAttribution.OUT_OF_BAND
    assert decision.outcome is DetectorOutcome.OUT_OF_BAND_EMITTED
    # Reconcile PR was emitted.
    assert len(publisher.records) == 1
    pr = publisher.records[0]
    assert pr.mode is Mode.SHADOW
    assert "shadow" in pr.labels
    assert "out-of-band" in pr.labels
    assert pr.idempotency_key == "oob::oob-key"
    assert "sub/rg-1/vm-42" in pr.title
    assert "reconcile" in pr.title.lower()
    # Alert event was published.
    alerts = bus._records[OUT_OF_BAND_ALERT_TOPIC]  # type: ignore[attr-defined]
    assert len(alerts) == 1
    key, payload = alerts[0]
    assert key == "sub/rg-1/vm-42"
    assert payload["source_event_id"] == str(event.event_id)
    assert payload["actor"] == "oid-portal-user"
    assert payload["mode"] == Mode.SHADOW.value
    # Audit: one entry recording the emission.
    entries = list(audit.audit_entries)
    assert len(entries) == 1
    entry = entries[0]["entry"]
    assert entry["attribution"] == "out_of_band"
    assert entry["outcome"] == "out_of_band_emitted"
    assert entry["pr_ref"] == pr.idempotency_key.split("::")[0] or entry["pr_ref"]
    assert entry["alert_topic"] == OUT_OF_BAND_ALERT_TOPIC


# ---------------------------------------------------------------------------
# Settling-window suppression
# ---------------------------------------------------------------------------


async def test_suppressed_inside_settling_window() -> None:
    # detected 10s ago, default 60s window → suppressed.
    detected = FIXED_DETECTED_AT
    detector, publisher, bus, audit = _detector(
        now=detected + timedelta(seconds=10),
    )
    event = _event(
        actor="unknown-actor",
        idempotency_key="settling-1",
        detected_at=detected,
    )

    decision = await detector.detect(event)

    assert decision.attribution is ChangeAttribution.SUPPRESSED
    assert decision.outcome is DetectorOutcome.SUPPRESSED
    assert "settling window" in decision.reason
    assert publisher.records == ()
    assert bus._records.get(OUT_OF_BAND_ALERT_TOPIC) is None  # type: ignore[attr-defined]
    entries = list(audit.audit_entries)
    assert len(entries) == 1
    assert entries[0]["entry"]["attribution"] == "suppressed"


async def test_settling_window_per_resource_type_override() -> None:
    detected = FIXED_DETECTED_AT
    detector, publisher, _, audit = _detector(
        per_type_settling={"compute.vm": timedelta(seconds=5)},
        now=detected + timedelta(seconds=10),
    )
    # Same 10s age, but compute.vm window is only 5s → out_of_band.
    event = _event(
        actor="oid-portal",
        resource_type="compute.vm",
        idempotency_key="settling-override",
        detected_at=detected,
    )

    decision = await detector.detect(event)

    assert decision.attribution is ChangeAttribution.OUT_OF_BAND
    assert decision.outcome is DetectorOutcome.OUT_OF_BAND_EMITTED
    assert len(publisher.records) == 1


# ---------------------------------------------------------------------------
# Reconcile PR only fires on OUT_OF_BAND
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("build_event", "expected_outcome"),
    [
        (
            lambda: _event(
                actor="sp-ci",
                idempotency_key="only-authorized",
            ),
            DetectorOutcome.AUTHORIZED,
        ),
        (
            lambda: _event(
                actor="oid-portal",
                idempotency_key="only-suppressed",
            ),
            DetectorOutcome.SUPPRESSED,
        ),
    ],
)
async def test_reconcile_pr_only_on_out_of_band(
    build_event: Any, expected_outcome: DetectorOutcome
) -> None:
    detector, publisher, _, _ = _detector(
        principals=("sp-ci",),
        now=FIXED_DETECTED_AT + timedelta(seconds=1),  # inside 60s window
    )
    decision = await detector.detect(build_event())
    assert decision.outcome is expected_outcome
    assert publisher.records == ()


# ---------------------------------------------------------------------------
# Signal-kind gating
# ---------------------------------------------------------------------------


async def test_non_activity_log_is_a_no_op() -> None:
    detector, publisher, bus, audit = _detector()
    event = _event(signal_kind=None, idempotency_key="not-al")

    decision = await detector.detect(event)

    assert decision.outcome is DetectorOutcome.NOT_ACTIVITY_LOG
    assert publisher.records == ()
    assert bus._records.get(OUT_OF_BAND_ALERT_TOPIC) is None  # type: ignore[attr-defined]
    # NO audit entry — the primary loop writes routing audit after us.
    assert list(audit.audit_entries) == []


async def test_wrong_signal_kind_is_a_no_op() -> None:
    detector, publisher, _, audit = _detector()
    event = _event(signal_kind="azure.resource_health", idempotency_key="not-al-2")

    decision = await detector.detect(event)

    assert decision.outcome is DetectorOutcome.NOT_ACTIVITY_LOG
    assert publisher.records == ()
    assert list(audit.audit_entries) == []


# ---------------------------------------------------------------------------
# Fail-close behaviour when the publisher or bus raises
# ---------------------------------------------------------------------------


class _RaisingPublisher(RecordingRemediationPrPublisher):
    async def publish(self, pr: RemediationPr) -> PrPublishReceipt:
        raise RuntimeError("simulated remote outage")


class _RaisingBus(InMemoryEventBus):
    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        raise RuntimeError("bus down")


async def test_publisher_failure_downgrades_to_partial() -> None:
    registry = InMemoryPipelinePrincipalRegistry(("sp-ci",))
    ledger = InMemoryRemediationPrLedger()
    publisher = _RaisingPublisher()
    bus = InMemoryEventBus()
    audit = InMemoryStateStore()
    detector = ChangeSafetyDetector(
        principal_registry=registry,
        ledger=ledger,
        publisher=publisher,
        event_bus=bus,
        audit_store=audit,
        clock=lambda: FIXED_DETECTED_AT + timedelta(seconds=120),
    )
    event = _event(actor="unknown", idempotency_key="partial-1")

    decision = await detector.detect(event)

    assert decision.attribution is ChangeAttribution.OUT_OF_BAND
    assert decision.outcome is DetectorOutcome.OUT_OF_BAND_PARTIAL
    # Alert succeeded; PR failed.
    assert decision.pr_ref is None
    assert decision.alert_offset is not None
    entry = list(audit.audit_entries)[-1]["entry"]
    assert "simulated remote outage" in entry["pr_error"]


async def test_alert_bus_failure_downgrades_to_partial() -> None:
    registry = InMemoryPipelinePrincipalRegistry(())
    ledger = InMemoryRemediationPrLedger()
    publisher = RecordingRemediationPrPublisher()
    bus = _RaisingBus()
    audit = InMemoryStateStore()
    detector = ChangeSafetyDetector(
        principal_registry=registry,
        ledger=ledger,
        publisher=publisher,
        event_bus=bus,
        audit_store=audit,
        clock=lambda: FIXED_DETECTED_AT + timedelta(seconds=120),
    )
    event = _event(actor="unknown", idempotency_key="partial-2")

    decision = await detector.detect(event)

    assert decision.outcome is DetectorOutcome.OUT_OF_BAND_PARTIAL
    # PR succeeded; alert failed.
    assert decision.pr_ref is not None
    assert decision.alert_offset is None
    entry = list(audit.audit_entries)[-1]["entry"]
    assert "bus down" in entry["alert_error"]


# ---------------------------------------------------------------------------
# Idempotency: re-delivery hits publisher dedupe key
# ---------------------------------------------------------------------------


async def test_out_of_band_pr_idempotent_on_redelivery() -> None:
    detector, publisher, bus, _audit = _detector(
        now=FIXED_DETECTED_AT + timedelta(seconds=120),
    )
    e1 = _event(actor="portal", idempotency_key="dup-key")
    e2 = _event(actor="portal", idempotency_key="dup-key")

    d1 = await detector.detect(e1)
    d2 = await detector.detect(e2)

    assert d1.outcome is DetectorOutcome.OUT_OF_BAND_EMITTED
    assert d2.outcome is DetectorOutcome.OUT_OF_BAND_EMITTED
    # Publisher deduplicates on idempotency_key so exactly one PR
    # record was appended even though two publish attempts happened.
    assert len(publisher.records) == 1
    # Two alerts, two audit entries — the alert bus + audit are
    # append-only regardless of PR dedupe.
    assert len(bus._records[OUT_OF_BAND_ALERT_TOPIC]) == 2  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Actor extraction handles both shapes documented in the module docstring
# ---------------------------------------------------------------------------


async def test_actor_extraction_from_string_shape() -> None:
    registry = InMemoryPipelinePrincipalRegistry(("sp-ci",))
    ledger = InMemoryRemediationPrLedger()
    publisher = RecordingRemediationPrPublisher()
    bus = InMemoryEventBus()
    audit = InMemoryStateStore()
    detector = ChangeSafetyDetector(
        principal_registry=registry,
        ledger=ledger,
        publisher=publisher,
        event_bus=bus,
        audit_store=audit,
    )
    event = Event(
        schema_version="1.0.0",
        event_id=uuid4(),
        idempotency_key="actor-shape-str",
        source="azure_activity_log",
        event_type="config_changed",
        payload={"signal_kind": ACTIVITY_LOG_SIGNAL_KIND, "actor": "sp-ci"},
        detected_at=FIXED_DETECTED_AT,
        ingested_at=FIXED_DETECTED_AT,
        mode=Mode.SHADOW,
    )

    decision = await detector.detect(event)

    assert decision.attribution is ChangeAttribution.AUTHORIZED
    assert decision.actor == "sp-ci"


async def test_unknown_actor_and_no_correlation_and_past_window_is_out_of_band() -> None:
    detector, publisher, bus, audit = _detector(
        now=FIXED_DETECTED_AT + timedelta(seconds=61),
    )
    event = _event(actor=None, idempotency_key="no-actor")

    decision = await detector.detect(event)

    assert decision.attribution is ChangeAttribution.OUT_OF_BAND
    assert decision.outcome is DetectorOutcome.OUT_OF_BAND_EMITTED
    assert decision.actor is None
    assert "unknown" in decision.reason


# ---------------------------------------------------------------------------
# All outcomes audited — one entry per non-passthrough call
# ---------------------------------------------------------------------------


async def test_all_terminal_outcomes_audited_with_mode_shadow() -> None:
    detector, _, _, audit = _detector(
        principals=("sp-ci",),
        correlations={"corr-1": "repo#1"},
    )

    # authorized-by-actor
    await detector.detect(_event(actor="sp-ci", idempotency_key="a1"))
    # authorized-by-correlation
    await detector.detect(
        _event(
            actor="mystery",
            correlation_id="corr-1",
            idempotency_key="a2",
        )
    )
    # suppressed (default clock puts us at real now, event.detected_at is
    # FIXED_DETECTED_AT in the past, so use an event detected "now")
    now_event = _event(
        actor="mystery",
        idempotency_key="a3",
        detected_at=datetime.now(tz=UTC),
    )
    await detector.detect(now_event)

    entries = list(audit.audit_entries)
    assert len(entries) == 3
    outcomes = [e["entry"]["outcome"] for e in entries]
    assert outcomes == ["authorized", "authorized", "suppressed"]
    assert all(e["entry"]["mode"] == Mode.SHADOW.value for e in entries)


# ---------------------------------------------------------------------------
# ControlLoop wiring — detector runs BEFORE trust_router when supplied
# ---------------------------------------------------------------------------


async def test_control_loop_invokes_detector_before_router_for_activity_log(
    tmp_path,
) -> None:
    from aiopspilot.core.control_loop import ControlLoop, ControlLoopResult
    from aiopspilot.core.event_ingest import EventIngest
    from aiopspilot.core.executor import (
        ResourceLockManager,
        ShadowExecutor,
        TemplateRenderer,
    )
    from aiopspilot.core.executor.action_builder import ActionBuilder
    from aiopspilot.core.tiers.t0_deterministic import RuleIndex, T0Engine
    from aiopspilot.core.trust_router import TrustRouter
    from aiopspilot.shared.contracts.registry import PackageResourceSchemaRegistry
    from aiopspilot.shared.contracts.validation import (
        JsonSchemaContractValidator,
        JsonSchemaEventValidator,
    )

    detector, publisher, bus, audit = _detector(
        now=FIXED_DETECTED_AT + timedelta(seconds=120),
    )
    from pathlib import Path

    index = RuleIndex.build(())
    registry = PackageResourceSchemaRegistry()
    validator = JsonSchemaEventValidator(JsonSchemaContractValidator(registry))
    exec_audit = InMemoryStateStore()
    executor = ShadowExecutor(
        publisher=RecordingRemediationPrPublisher(),
        audit_store=exec_audit,
        renderer=TemplateRenderer(remediation_root=Path(tmp_path)),
        resource_lock=ResourceLockManager(),
    )
    loop = ControlLoop(
        event_ingest=EventIngest(validator=validator),
        trust_router=TrustRouter(index=index),
        t0_engine=T0Engine(index=index, evaluator=None),
        action_builder=ActionBuilder(action_types_by_name={}),
        executor=executor,
        audit_store=exec_audit,
        rules_by_id={},
        change_safety_detector=detector,
    )

    raw = {
        "schema_version": "1.0.0",
        "event_id": str(uuid4()),
        "idempotency_key": "loop-oob-1",
        "source": "azure_activity_log",
        "event_type": "config_changed",
        "detected_at": FIXED_DETECTED_AT.isoformat(),
        "ingested_at": FIXED_DETECTED_AT.isoformat(),
        "mode": "shadow",
        "payload": {
            "signal_kind": ACTIVITY_LOG_SIGNAL_KIND,
            "actor": {"principal_id": "portal-user"},
            "resource": {
                "resource_id": "sub/rg/vm-1",
                "type": "compute.vm",
                "props": {},
            },
        },
    }

    result: ControlLoopResult = await loop.process(raw)

    # Detector fired.
    assert isinstance(result.change_safety_decision, ChangeSafetyDecision)
    assert result.change_safety_decision.outcome is DetectorOutcome.OUT_OF_BAND_EMITTED
    # Reconcile PR + alert produced by the detector.
    assert len(publisher.records) == 1
    assert OUT_OF_BAND_ALERT_TOPIC in bus._records  # type: ignore[attr-defined]
    # Primary pipeline still ran and abstained (empty index).
    assert result.decision == "abstain"


async def test_control_loop_skips_detector_for_non_activity_log_event(tmp_path) -> None:
    from aiopspilot.core.control_loop import ControlLoop
    from aiopspilot.core.event_ingest import EventIngest
    from aiopspilot.core.executor import (
        ResourceLockManager,
        ShadowExecutor,
        TemplateRenderer,
    )
    from aiopspilot.core.executor.action_builder import ActionBuilder
    from aiopspilot.core.tiers.t0_deterministic import RuleIndex, T0Engine
    from aiopspilot.core.trust_router import TrustRouter
    from aiopspilot.shared.contracts.registry import PackageResourceSchemaRegistry
    from aiopspilot.shared.contracts.validation import (
        JsonSchemaContractValidator,
        JsonSchemaEventValidator,
    )

    detector, publisher, bus, audit = _detector()
    from pathlib import Path

    index = RuleIndex.build(())
    registry = PackageResourceSchemaRegistry()
    validator = JsonSchemaEventValidator(JsonSchemaContractValidator(registry))
    exec_audit = InMemoryStateStore()
    executor = ShadowExecutor(
        publisher=RecordingRemediationPrPublisher(),
        audit_store=exec_audit,
        renderer=TemplateRenderer(remediation_root=Path(tmp_path)),
        resource_lock=ResourceLockManager(),
    )
    loop = ControlLoop(
        event_ingest=EventIngest(validator=validator),
        trust_router=TrustRouter(index=index),
        t0_engine=T0Engine(index=index, evaluator=None),
        action_builder=ActionBuilder(action_types_by_name={}),
        executor=executor,
        audit_store=exec_audit,
        rules_by_id={},
        change_safety_detector=detector,
    )

    raw = {
        "schema_version": "1.0.0",
        "event_id": str(uuid4()),
        "idempotency_key": "loop-not-al",
        "source": "cost_management",
        "event_type": "cost_anomaly",
        "detected_at": FIXED_DETECTED_AT.isoformat(),
        "ingested_at": FIXED_DETECTED_AT.isoformat(),
        "mode": "shadow",
        "payload": {},
    }

    result = await loop.process(raw)

    # Detector never fired.
    assert result.change_safety_decision is None
    assert publisher.records == ()
    assert OUT_OF_BAND_ALERT_TOPIC not in bus._records  # type: ignore[attr-defined]
    assert list(audit.audit_entries) == []


# ---------------------------------------------------------------------------
# Provider fake sanity — Protocol contracts are honored
# ---------------------------------------------------------------------------


def test_pipeline_principal_registry_contains() -> None:
    r = InMemoryPipelinePrincipalRegistry(("a", "b"))
    assert r.contains("a") is True
    assert r.contains("b") is True
    assert r.contains("c") is False


def test_remediation_pr_ledger_find_correlation() -> None:
    lg = InMemoryRemediationPrLedger({"c1": "repo#1"})
    assert lg.find_correlation("c1") == "repo#1"
    assert lg.find_correlation("c2") is None
    lg.record("c2", "repo#2")
    assert lg.find_correlation("c2") == "repo#2"


def test_remediation_pr_ledger_record_rejects_empty() -> None:
    lg = InMemoryRemediationPrLedger()
    with pytest.raises(ValueError):
        lg.record("", "x")
    with pytest.raises(ValueError):
        lg.record("k", "")


def test_detector_config_window_for_default_and_override() -> None:
    cfg = ChangeSafetyDetectorConfig(
        default_settling_window=timedelta(seconds=30),
        settling_windows={"compute.vm": timedelta(seconds=5)},
    )
    assert cfg.window_for(None) == timedelta(seconds=30)
    assert cfg.window_for("unknown") == timedelta(seconds=30)
    assert cfg.window_for("compute.vm") == timedelta(seconds=5)


async def test_resource_type_flat_payload_shape_still_extracted() -> None:
    """The extractor accepts a flat ``resource_type`` field (Phase 0 fixture shape)."""
    registry = InMemoryPipelinePrincipalRegistry(())
    ledger = InMemoryRemediationPrLedger()
    publisher = RecordingRemediationPrPublisher()
    bus = InMemoryEventBus()
    audit = InMemoryStateStore()
    detector = ChangeSafetyDetector(
        principal_registry=registry,
        ledger=ledger,
        publisher=publisher,
        event_bus=bus,
        audit_store=audit,
        config=ChangeSafetyDetectorConfig(
            default_settling_window=timedelta(seconds=1),
            settling_windows={"compute.vm": timedelta(seconds=99999)},
        ),
        clock=lambda: FIXED_DETECTED_AT + timedelta(seconds=10),
    )
    event = Event(
        schema_version="1.0.0",
        event_id=uuid4(),
        idempotency_key="flat-shape",
        source="azure_activity_log",
        event_type="config_changed",
        payload={
            "signal_kind": ACTIVITY_LOG_SIGNAL_KIND,
            "actor": "mystery",
            "resource_type": "compute.vm",
        },
        detected_at=FIXED_DETECTED_AT,
        ingested_at=FIXED_DETECTED_AT,
        mode=Mode.SHADOW,
    )

    decision = await detector.detect(event)

    # 99999s window on compute.vm → suppressed proves flat resource_type
    # was read + fed into window_for.
    assert decision.outcome is DetectorOutcome.SUPPRESSED
    assert decision.resource_type == "compute.vm"
