"""StateStore-backed promotion mode durability and fail-closed tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.risk_gate import PromotionMetrics
from fdai.delivery.persistence.state_store_action_promotion import (
    PromotionGateStatus,
    PromotionKind,
    PromotionRefusedError,
    StateStoreActionPromotionRegistry,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.models import Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 1, tzinfo=UTC)
_APPROVAL = "a" * 64


def _action_type():
    from pathlib import Path

    root = Path(__file__).resolve().parents[4] / "rule-catalog" / "action-types"
    return next(
        item
        for item in load_action_type_catalog(root, schema_registry=PackageResourceSchemaRegistry())
        if item.name == "remediate.tag-add"
    )


def _passing_metrics(action_type: str) -> PromotionMetrics:
    return PromotionMetrics(
        action_type=action_type,
        shadow_days=999,
        samples=10_000,
        accuracy=1.0,
        policy_escapes=0,
    )


def _failing_metrics(action_type: str) -> PromotionMetrics:
    return PromotionMetrics(
        action_type=action_type,
        shadow_days=0,
        samples=0,
        accuracy=0.0,
        policy_escapes=1,
    )


class _OverrideVerifier:
    def __init__(self, *, accepted: bool = True) -> None:
        self.accepted = accepted
        self.calls: list[dict[str, object]] = []

    async def verify_override(self, **kwargs: object) -> bool:
        self.calls.append(dict(kwargs))
        return self.accepted and kwargs["approval_receipt_digest"] == _APPROVAL


def _override_state(action_type) -> dict[str, object]:  # type: ignore[no-untyped-def]
    assert action_type.provenance is not None
    return {
        "schema_version": "1.0.0",
        "action_type": action_type.name,
        "mode": "enforce",
        "promotion_kind": "operator_override",
        "promoted_at": _NOW.isoformat(),
        "demoted_at": None,
        "promotion_evidence_digest": "e" * 64,
        "action_type_version": action_type.version,
        "action_type_digest": action_type.provenance.content_hash.removeprefix("sha256:"),
        "gate_status": "failed",
        "gate_evidence_digest": "e" * 64,
        "approval_receipt_digest": _APPROVAL,
        "operator_principal": "operator@example.com",
        "override_reason": "Operator accepted bounded risk.",
        "override_recorded_at": _NOW.isoformat(),
        "metrics": None,
    }


@pytest.mark.asyncio
async def test_legacy_metrics_only_enforce_clamps_to_shadow_after_restart() -> None:
    store = InMemoryStateStore()
    first = StateStoreActionPromotionRegistry(store=store, allow_legacy_metrics=True)
    action_type = _action_type()
    await first.refresh_for_update(action_type.name)
    first.consider_promotion(
        action_type=action_type,
        metrics=PromotionMetrics(
            action_type=action_type.name,
            shadow_days=999,
            samples=10_000,
            accuracy=1.0,
            policy_escapes=0,
        ),
    )
    await first.persist(action_type.name)

    second = StateStoreActionPromotionRegistry(store=store, allow_legacy_metrics=True)
    await second.refresh(action_type.name)

    assert second.mode_of(action_type.name) is Mode.SHADOW


async def test_fully_attributed_enforce_requires_authoritative_resolution() -> None:
    class _Verifier:
        async def verify(self, **kwargs: object) -> bool:
            return kwargs["evidence_digest"] == "e" * 64

    store = InMemoryStateStore()
    action_type = _action_type()
    assert action_type.provenance is not None
    await store.write_state(
        f"action_promotion:{action_type.name}",
        {
            "schema_version": "1.0.0",
            "action_type": action_type.name,
            "mode": "enforce",
            "promoted_at": "2026-08-01T00:00:00+00:00",
            "demoted_at": None,
            "promotion_evidence_digest": "e" * 64,
            "fdai_revision": "a" * 40,
            "scenario_set_version": "v2026.08",
            "action_type_version": action_type.version,
            "action_type_digest": action_type.provenance.content_hash.removeprefix("sha256:"),
            "metrics": None,
        },
    )
    registry = StateStoreActionPromotionRegistry(
        store=store,
        persisted_authority_verifier=_Verifier(),
    )

    await registry.refresh(action_type.name)

    assert registry.mode_of(action_type.name) is Mode.ENFORCE
    assert registry.read_model(action_type.name)["promotion_kind"] == PromotionKind.GATE_EVIDENCE


@pytest.mark.asyncio
async def test_operator_override_is_recorded_and_marked() -> None:
    store = InMemoryStateStore()
    verifier = _OverrideVerifier()
    registry = StateStoreActionPromotionRegistry(
        store=store,
        override_authority_verifier=verifier,
    )
    action_type = _action_type()

    await registry.refresh_for_update(action_type.name)
    record = await registry.consider_operator_override(
        action_type=action_type,
        gate_status=PromotionGateStatus.INSUFFICIENT_EVIDENCE,
        gate_evidence_digest="e" * 64,
        approval_receipt_digest=_APPROVAL,
        operator_principal="operator@example.com",
        reason="Development-scope owner accepted bounded promotion risk.",
        recorded_at=_NOW,
    )
    await registry.persist(action_type.name)

    assert record.mode is Mode.ENFORCE
    assert record.production_ready is False
    assert registry.read_model(action_type.name) == {
        "action_type": action_type.name,
        "mode": "enforce",
        "promotion_kind": "operator_override",
        "promoted_at": _NOW.isoformat(),
        "demoted_at": None,
        "promotion_evidence_digest": "e" * 64,
        "capability_recall": None,
        "gate_status": "insufficient_evidence",
        "gate_evidence_digest": "e" * 64,
        "approval_receipt_digest": _APPROVAL,
        "operator_principal": "operator@example.com",
        "override_reason": "Development-scope owner accepted bounded promotion risk.",
        "override_recorded_at": _NOW.isoformat(),
    }
    persisted = await store.read_state(f"action_promotion:{action_type.name}")
    assert persisted is not None
    assert persisted["promotion_kind"] == "operator_override"
    assert persisted["gate_status"] == "insufficient_evidence"
    assert persisted["approval_receipt_digest"] == _APPROVAL
    assert persisted["operator_principal"] == "operator@example.com"
    assert verifier.calls == [
        {
            "action_type": action_type.name,
            "action_type_version": action_type.version,
            "action_type_digest": record.action_type_digest,
            "gate_evidence_digest": "e" * 64,
            "approval_receipt_digest": _APPROVAL,
            "operator_principal": "operator@example.com",
        }
    ]
    audit_entry = tuple(store.audit_entries)[-1]["entry"]
    assert audit_entry["mode"] == "enforce"
    assert audit_entry["promotion_kind"] == "operator_override"

    restarted = StateStoreActionPromotionRegistry(
        store=store,
        override_authority_verifier=_OverrideVerifier(),
    )
    await restarted.refresh(action_type.name)

    assert restarted.mode_of(action_type.name) is Mode.ENFORCE
    assert restarted.read_model(action_type.name)["promotion_kind"] == "operator_override"


async def test_operator_override_without_verifier_is_refused_and_keeps_shadow() -> None:
    registry = StateStoreActionPromotionRegistry(store=InMemoryStateStore())
    action_type = _action_type()

    with pytest.raises(PromotionRefusedError, match="override_authority_unverified"):
        await registry.consider_operator_override(
            action_type=action_type,
            gate_status=PromotionGateStatus.FAILED,
            gate_evidence_digest="e" * 64,
            approval_receipt_digest=_APPROVAL,
            operator_principal="operator@example.com",
            reason="Operator accepted bounded risk.",
            recorded_at=_NOW,
        )

    assert registry.mode_of(action_type.name) is Mode.SHADOW
    assert registry.record(action_type.name) is None


async def test_operator_override_rejected_by_verifier_is_refused() -> None:
    registry = StateStoreActionPromotionRegistry(
        store=InMemoryStateStore(),
        override_authority_verifier=_OverrideVerifier(accepted=False),
    )
    action_type = _action_type()

    with pytest.raises(PromotionRefusedError, match="override_authority_unverified"):
        await registry.consider_operator_override(
            action_type=action_type,
            gate_status=PromotionGateStatus.FAILED,
            gate_evidence_digest="e" * 64,
            approval_receipt_digest=_APPROVAL,
            operator_principal="operator@example.com",
            reason="Operator accepted bounded risk.",
            recorded_at=_NOW,
        )

    assert registry.mode_of(action_type.name) is Mode.SHADOW


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("gate_evidence_digest", "not-a-digest", "gate evidence digest"),
        ("approval_receipt_digest", "not-a-digest", "approval receipt digest"),
        ("operator_principal", "", "principal"),
        ("reason", " ", "reason"),
        ("recorded_at", datetime(2026, 8, 1), "timezone-aware"),
    ],
)
async def test_operator_override_missing_required_fields_are_refused(
    field: str,
    value: object,
    message: str,
) -> None:
    registry = StateStoreActionPromotionRegistry(
        store=InMemoryStateStore(),
        override_authority_verifier=_OverrideVerifier(),
    )
    action_type = _action_type()
    kwargs = {
        "action_type": action_type,
        "gate_status": PromotionGateStatus.FAILED,
        "gate_evidence_digest": "e" * 64,
        "approval_receipt_digest": _APPROVAL,
        "operator_principal": "operator@example.com",
        "reason": "Operator accepted bounded risk.",
        "recorded_at": _NOW,
    }
    kwargs[field] = value

    with pytest.raises(ValueError, match=message):
        await registry.consider_operator_override(**kwargs)


async def test_malformed_persisted_operator_override_clamps_to_shadow() -> None:
    store = InMemoryStateStore()
    action_type = _action_type()
    assert action_type.provenance is not None
    await store.write_state(
        f"action_promotion:{action_type.name}",
        {
            "schema_version": "1.0.0",
            "action_type": action_type.name,
            "mode": "enforce",
            "promotion_kind": "operator_override",
            "promoted_at": _NOW.isoformat(),
            "demoted_at": None,
            "promotion_evidence_digest": "e" * 64,
            "action_type_version": action_type.version,
            "action_type_digest": action_type.provenance.content_hash.removeprefix("sha256:"),
            "metrics": None,
        },
    )
    registry = StateStoreActionPromotionRegistry(
        store=store,
        override_authority_verifier=_OverrideVerifier(),
    )

    await registry.refresh(action_type.name)

    assert registry.mode_of(action_type.name) is Mode.SHADOW


@pytest.mark.parametrize("verifier", [None, _OverrideVerifier(accepted=False)])
async def test_forged_persisted_operator_override_clamps_to_shadow_after_restart(
    verifier: _OverrideVerifier | None,
) -> None:
    store = InMemoryStateStore()
    action_type = _action_type()
    await store.write_state(f"action_promotion:{action_type.name}", _override_state(action_type))
    registry = StateStoreActionPromotionRegistry(
        store=store,
        override_authority_verifier=verifier,
    )

    await registry.refresh(action_type.name)

    assert registry.mode_of(action_type.name) is Mode.SHADOW
    assert registry.record(action_type.name) is None


async def test_verified_persisted_operator_override_survives_restart() -> None:
    store = InMemoryStateStore()
    action_type = _action_type()
    await store.write_state(f"action_promotion:{action_type.name}", _override_state(action_type))
    registry = StateStoreActionPromotionRegistry(
        store=store,
        override_authority_verifier=_OverrideVerifier(),
    )

    await registry.refresh(action_type.name)

    assert registry.mode_of(action_type.name) is Mode.ENFORCE
    assert registry.read_model(action_type.name)["approval_receipt_digest"] == _APPROVAL


async def test_regression_demotion_overrides_operator_override() -> None:
    store = InMemoryStateStore()
    registry = StateStoreActionPromotionRegistry(
        store=store,
        override_authority_verifier=_OverrideVerifier(),
    )
    action_type = _action_type()
    await registry.refresh_for_update(action_type.name)
    await registry.consider_operator_override(
        action_type=action_type,
        gate_status=PromotionGateStatus.FAILED,
        gate_evidence_digest="e" * 64,
        approval_receipt_digest=_APPROVAL,
        operator_principal="operator@example.com",
        reason="Operator accepted bounded risk.",
        recorded_at=_NOW,
    )
    await registry.persist(action_type.name)

    registry.demote(action_type.name, metrics=_failing_metrics(action_type.name))
    await registry.persist(action_type.name)

    assert registry.mode_of(action_type.name) is Mode.SHADOW
    assert registry.read_model(action_type.name)["promotion_kind"] == "gate_evidence"
    persisted = await store.read_state(f"action_promotion:{action_type.name}")
    assert persisted is not None
    assert persisted["mode"] == "shadow"
    assert persisted["promotion_kind"] == "gate_evidence"


async def test_capability_recall_overrides_operator_override() -> None:
    store = InMemoryStateStore()
    registry = StateStoreActionPromotionRegistry(
        store=store,
        override_authority_verifier=_OverrideVerifier(),
    )
    action_type = _action_type()
    await registry.refresh_for_update(action_type.name)
    await registry.consider_operator_override(
        action_type=action_type,
        gate_status=PromotionGateStatus.FAILED,
        gate_evidence_digest="e" * 64,
        approval_receipt_digest=_APPROVAL,
        operator_principal="operator@example.com",
        reason="Operator accepted bounded risk.",
        recorded_at=_NOW,
    )
    await registry.persist(action_type.name)

    await registry.recall_capability(
        action_type.name,
        reason="vendor capability recall",
        recalled_at=_NOW,
    )

    projection = registry.read_model(action_type.name)
    assert registry.mode_of(action_type.name) is Mode.SHADOW
    assert projection["mode"] == "shadow"
    assert projection["promotion_kind"] == "operator_override"
    assert projection["capability_recall"] == {
        "action_type": action_type.name,
        "active": True,
        "reason": "vendor capability recall",
        "recalled_at": _NOW.isoformat(),
        "lifted_at": None,
    }

    restarted = StateStoreActionPromotionRegistry(
        store=store,
        override_authority_verifier=_OverrideVerifier(),
    )
    await restarted.refresh(action_type.name)

    assert restarted.mode_of(action_type.name) is Mode.SHADOW
    assert restarted.read_model(action_type.name)["mode"] == "shadow"


async def test_recalled_capability_refuses_override_and_gate_promotion() -> None:
    store = InMemoryStateStore()
    registry = StateStoreActionPromotionRegistry(
        store=store,
        allow_legacy_metrics=True,
        override_authority_verifier=_OverrideVerifier(),
    )
    action_type = _action_type()
    await registry.recall_capability(
        action_type.name,
        reason="vendor capability recall",
        recalled_at=_NOW,
    )

    with pytest.raises(PromotionRefusedError, match="capability_recall_active"):
        await registry.consider_operator_override(
            action_type=action_type,
            gate_status=PromotionGateStatus.PASSED,
            gate_evidence_digest="e" * 64,
            approval_receipt_digest=_APPROVAL,
            operator_principal="operator@example.com",
            reason="Operator accepted bounded risk.",
            recorded_at=_NOW,
        )
    with pytest.raises(PromotionRefusedError, match="capability_recall_active"):
        registry.consider_promotion(
            action_type=action_type,
            metrics=_passing_metrics(action_type.name),
        )

    await registry.lift_capability_recall(action_type.name, lifted_at=_NOW)

    record = await registry.consider_operator_override(
        action_type=action_type,
        gate_status=PromotionGateStatus.PASSED,
        gate_evidence_digest="e" * 64,
        approval_receipt_digest=_APPROVAL,
        operator_principal="operator@example.com",
        reason="Operator accepted bounded risk after recall lifted.",
        recorded_at=_NOW,
    )
    assert record.mode is Mode.ENFORCE


async def test_gate_evidence_default_is_preserved_for_existing_callers() -> None:
    store = InMemoryStateStore()
    registry = StateStoreActionPromotionRegistry(store=store, allow_legacy_metrics=True)
    action_type = _action_type()
    await registry.refresh_for_update(action_type.name)

    registry.consider_promotion(
        action_type=action_type,
        metrics=_passing_metrics(action_type.name),
    )
    await registry.persist(action_type.name)

    assert registry.read_model(action_type.name)["promotion_kind"] == "gate_evidence"
    persisted = await store.read_state(f"action_promotion:{action_type.name}")
    assert persisted is not None
    assert persisted["promotion_kind"] == "gate_evidence"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("promotion_evidence_digest", "not-a-digest"),
        ("action_type_digest", "not-a-digest"),
        ("fdai_revision", "short"),
        ("promoted_at", "2026-08-01T00:00:00"),
    ],
)
async def test_malformed_enforce_attribution_clamps_to_shadow(
    field: str,
    value: str,
) -> None:
    class _AcceptingVerifier:
        async def verify(self, **kwargs: object) -> bool:
            return True

    store = InMemoryStateStore()
    action_type = _action_type()
    assert action_type.provenance is not None
    state = {
        "schema_version": "1.0.0",
        "action_type": action_type.name,
        "mode": "enforce",
        "promoted_at": "2026-08-01T00:00:00+00:00",
        "demoted_at": None,
        "promotion_evidence_digest": "e" * 64,
        "fdai_revision": "a" * 40,
        "scenario_set_version": "v2026.08",
        "action_type_version": action_type.version,
        "action_type_digest": action_type.provenance.content_hash.removeprefix("sha256:"),
        "metrics": None,
    }
    state[field] = value
    await store.write_state(f"action_promotion:{action_type.name}", state)
    registry = StateStoreActionPromotionRegistry(
        store=store,
        persisted_authority_verifier=_AcceptingVerifier(),
    )

    await registry.refresh(action_type.name)

    assert registry.mode_of(action_type.name) is Mode.SHADOW


async def test_mismatched_persisted_metrics_clamp_to_shadow() -> None:
    class _AcceptingVerifier:
        async def verify(self, **kwargs: object) -> bool:
            return True

    store = InMemoryStateStore()
    action_type = _action_type()
    assert action_type.provenance is not None
    await store.write_state(
        f"action_promotion:{action_type.name}",
        {
            "schema_version": "1.0.0",
            "action_type": action_type.name,
            "mode": "enforce",
            "promoted_at": "2026-08-01T00:00:00+00:00",
            "demoted_at": None,
            "promotion_evidence_digest": "e" * 64,
            "fdai_revision": "a" * 40,
            "scenario_set_version": "v2026.08",
            "action_type_version": action_type.version,
            "action_type_digest": action_type.provenance.content_hash.removeprefix("sha256:"),
            "metrics": {
                "action_type": "ops.other",
                "shadow_days": 30,
                "samples": 100,
                "accuracy": 1.0,
                "policy_escapes": 0,
            },
        },
    )
    registry = StateStoreActionPromotionRegistry(
        store=store,
        persisted_authority_verifier=_AcceptingVerifier(),
    )

    await registry.refresh(action_type.name)

    assert registry.mode_of(action_type.name) is Mode.SHADOW


@pytest.mark.asyncio
async def test_corrupt_state_clamps_cached_enforce_to_shadow() -> None:
    store = InMemoryStateStore()
    registry = StateStoreActionPromotionRegistry(store=store, allow_legacy_metrics=True)
    action_type = _action_type()
    registry.consider_promotion(
        action_type=action_type,
        metrics=PromotionMetrics(
            action_type=action_type.name,
            shadow_days=999,
            samples=10_000,
            accuracy=1.0,
            policy_escapes=0,
        ),
    )
    assert registry.mode_of(action_type.name) is Mode.ENFORCE
    await store.write_state(f"action_promotion:{action_type.name}", {"schema_version": "broken"})

    await registry.refresh(action_type.name)

    assert registry.mode_of(action_type.name) is Mode.SHADOW


@pytest.mark.asyncio
async def test_demotion_is_visible_after_restart() -> None:
    store = InMemoryStateStore()
    first = StateStoreActionPromotionRegistry(store=store, allow_legacy_metrics=True)
    action_type = _action_type()
    await first.refresh_for_update(action_type.name)
    first.demote(action_type.name)
    await first.persist(action_type.name)

    second = StateStoreActionPromotionRegistry(store=store, allow_legacy_metrics=True)
    await second.refresh(action_type.name)
    assert second.mode_of(action_type.name) is Mode.SHADOW
