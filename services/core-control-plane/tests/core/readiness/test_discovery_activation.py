from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.readiness import (
    DISCOVERY_ACTIVATION_STATE_KEY,
    CollectorRunEvidence,
    DiscoveryActivationCoordinator,
    DiscoveryActivationDecision,
    DiscoveryActivationInputs,
    DiscoveryActivationReason,
    DiscoveryEvidenceStatus,
    ShadowDecisionEvidence,
    TimedDiscoveryEvidence,
    reduce_discovery_activation,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


class _DurableCasStateStore(InMemoryStateStore):
    async def compare_and_set_state_with_audit(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        if await self.read_state(key) is None:
            return False
        return await super().compare_and_set_state_with_audit(
            key,
            value,
            expected_revision=expected_revision,
            audit_entry=audit_entry,
        )


def _timed(
    *,
    status: DiscoveryEvidenceStatus = DiscoveryEvidenceStatus.PASSED,
    stale: bool = False,
) -> TimedDiscoveryEvidence:
    return TimedDiscoveryEvidence(
        status=status,
        observed_at=_NOW - timedelta(hours=2 if stale else 1),
        expires_at=_NOW - timedelta(seconds=1) if stale else _NOW + timedelta(hours=1),
    )


def _shadow(
    *,
    count: int = 1_000,
    status: DiscoveryEvidenceStatus = DiscoveryEvidenceStatus.PASSED,
    stale: bool = False,
) -> ShadowDecisionEvidence:
    evidence = _timed(status=status, stale=stale)
    return ShadowDecisionEvidence(
        **evidence.model_dump(),
        decision_count=count,
    )


def _collector(
    *,
    status: DiscoveryEvidenceStatus = DiscoveryEvidenceStatus.PASSED,
    stale: bool = False,
) -> CollectorRunEvidence:
    evidence = _timed(status=status, stale=stale)
    return CollectorRunEvidence(
        **evidence.model_dump(),
        source_id="example-source",
        resolved_revision="abc123",
        content_sha256="0" * 64,
        license="Apache-2.0",
        redistribution="embeddable",
        verified_rules=3,
        schema_validated=True,
        provenance_validated=True,
    )


def _inputs(**overrides: object) -> DiscoveryActivationInputs:
    values: dict[str, object] = {
        "policy_enabled": True,
        "shadow_decision_threshold": 1_000,
        "shadow": _shadow(),
        "collector": _collector(),
        "cross_check": _timed(),
        "verifier": _timed(),
        "post_deploy_smoke": _timed(),
    }
    values.update(overrides)
    return DiscoveryActivationInputs.model_validate(values)


def test_all_current_prerequisites_enable_discovery() -> None:
    report = reduce_discovery_activation(_inputs(), generated_at=_NOW)

    assert report.decision is DiscoveryActivationDecision.ENABLED
    assert report.reason_codes == ()
    assert report.shadow_decision_count == 1_000
    assert report.to_json() == report.to_json()


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("shadow", DiscoveryActivationReason.SHADOW_EVIDENCE_MISSING),
        ("collector", DiscoveryActivationReason.COLLECTOR_EVIDENCE_MISSING),
        ("cross_check", DiscoveryActivationReason.CROSS_CHECK_EVIDENCE_MISSING),
        ("verifier", DiscoveryActivationReason.VERIFIER_EVIDENCE_MISSING),
        ("post_deploy_smoke", DiscoveryActivationReason.SMOKE_EVIDENCE_MISSING),
    ],
)
def test_each_missing_prerequisite_fails_closed(
    field: str,
    reason: DiscoveryActivationReason,
) -> None:
    report = reduce_discovery_activation(_inputs(**{field: None}), generated_at=_NOW)

    assert report.decision is DiscoveryActivationDecision.DISABLED
    assert reason in report.reason_codes


@pytest.mark.parametrize(
    ("field", "evidence", "reason"),
    [
        ("shadow", _shadow(stale=True), DiscoveryActivationReason.SHADOW_EVIDENCE_STALE),
        (
            "collector",
            _collector(stale=True),
            DiscoveryActivationReason.COLLECTOR_EVIDENCE_STALE,
        ),
        (
            "cross_check",
            _timed(stale=True),
            DiscoveryActivationReason.CROSS_CHECK_EVIDENCE_STALE,
        ),
        ("verifier", _timed(stale=True), DiscoveryActivationReason.VERIFIER_EVIDENCE_STALE),
        (
            "post_deploy_smoke",
            _timed(stale=True),
            DiscoveryActivationReason.SMOKE_EVIDENCE_STALE,
        ),
    ],
)
def test_each_stale_prerequisite_fails_closed(
    field: str,
    evidence: object,
    reason: DiscoveryActivationReason,
) -> None:
    report = reduce_discovery_activation(_inputs(**{field: evidence}), generated_at=_NOW)

    assert report.decision is DiscoveryActivationDecision.DISABLED
    assert reason in report.reason_codes


@pytest.mark.parametrize(
    ("field", "evidence", "reason"),
    [
        (
            "shadow",
            _shadow(status=DiscoveryEvidenceStatus.FAILED),
            DiscoveryActivationReason.SHADOW_EVIDENCE_FAILED,
        ),
        (
            "collector",
            _collector(status=DiscoveryEvidenceStatus.FAILED),
            DiscoveryActivationReason.COLLECTOR_EVIDENCE_FAILED,
        ),
        (
            "cross_check",
            _timed(status=DiscoveryEvidenceStatus.FAILED),
            DiscoveryActivationReason.CROSS_CHECK_EVIDENCE_FAILED,
        ),
        (
            "verifier",
            _timed(status=DiscoveryEvidenceStatus.FAILED),
            DiscoveryActivationReason.VERIFIER_EVIDENCE_FAILED,
        ),
        (
            "post_deploy_smoke",
            _timed(status=DiscoveryEvidenceStatus.FAILED),
            DiscoveryActivationReason.SMOKE_EVIDENCE_FAILED,
        ),
    ],
)
def test_each_failed_prerequisite_fails_closed(
    field: str,
    evidence: object,
    reason: DiscoveryActivationReason,
) -> None:
    report = reduce_discovery_activation(_inputs(**{field: evidence}), generated_at=_NOW)

    assert report.decision is DiscoveryActivationDecision.DISABLED
    assert reason in report.reason_codes


def test_shadow_threshold_is_current_policy_value() -> None:
    report = reduce_discovery_activation(
        _inputs(shadow=_shadow(count=999)),
        generated_at=_NOW,
    )

    assert report.reason_codes == (DiscoveryActivationReason.SHADOW_THRESHOLD_NOT_MET,)


def test_policy_disable_short_circuits_without_mutating_evidence() -> None:
    inputs = _inputs(policy_enabled=False)

    report = reduce_discovery_activation(inputs, generated_at=_NOW)

    assert report.decision is DiscoveryActivationDecision.DISABLED
    assert report.reason_codes == (DiscoveryActivationReason.POLICY_DISABLED,)
    assert inputs.collector is not None
    assert inputs.collector.resolved_revision == "abc123"


async def test_coordinator_is_restart_idempotent_and_audits_policy_disable() -> None:
    store = _DurableCasStateStore()
    first = DiscoveryActivationCoordinator(state_store=store)
    second = DiscoveryActivationCoordinator(state_store=store)

    enabled = await first.evaluate(_inputs(), generated_at=_NOW)
    enabled_state = await store.read_state(DISCOVERY_ACTIVATION_STATE_KEY)
    replayed = await second.evaluate(_inputs(), generated_at=_NOW + timedelta(seconds=1))
    replayed_state = await store.read_state(DISCOVERY_ACTIVATION_STATE_KEY)
    disabled = await second.evaluate(
        _inputs(policy_enabled=False),
        generated_at=_NOW + timedelta(seconds=2),
    )

    assert enabled.decision is DiscoveryActivationDecision.ENABLED
    assert replayed.decision is DiscoveryActivationDecision.ENABLED
    assert replayed_state == enabled_state
    assert disabled.decision is DiscoveryActivationDecision.DISABLED
    assert len(tuple(store.audit_entries)) == 2
    state = await store.read_state(DISCOVERY_ACTIVATION_STATE_KEY)
    assert state is not None
    assert state["decision"] == "disabled"
    assert state["revision"] == 2


async def test_threshold_change_is_an_audited_activation_transition() -> None:
    store = InMemoryStateStore()
    coordinator = DiscoveryActivationCoordinator(state_store=store)

    first = await coordinator.evaluate(_inputs(), generated_at=_NOW)
    changed = await coordinator.evaluate(
        _inputs(shadow_decision_threshold=999),
        generated_at=_NOW + timedelta(seconds=1),
    )

    assert first.decision is DiscoveryActivationDecision.ENABLED
    assert changed.decision is DiscoveryActivationDecision.ENABLED
    assert len(tuple(store.audit_entries)) == 2
    state = await store.read_state(DISCOVERY_ACTIVATION_STATE_KEY)
    assert state is not None
    assert state["shadow_decision_threshold"] == 999
    assert state["revision"] == 2
