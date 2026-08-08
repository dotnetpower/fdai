"""StateStore-backed promotion mode durability and fail-closed tests."""

from __future__ import annotations

import pytest
from fdai.core.risk_gate import PromotionMetrics
from fdai.delivery.persistence.state_store_action_promotion import (
    StateStoreActionPromotionRegistry,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.models import Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _action_type():
    from pathlib import Path

    root = Path(__file__).resolve().parents[4] / "rule-catalog" / "action-types"
    return next(
        item
        for item in load_action_type_catalog(root, schema_registry=PackageResourceSchemaRegistry())
        if item.name == "remediate.tag-add"
    )


@pytest.mark.asyncio
async def test_legacy_metrics_only_enforce_clamps_to_shadow_after_restart() -> None:
    store = InMemoryStateStore()
    first = StateStoreActionPromotionRegistry(store=store, allow_legacy_metrics=True)
    action_type = _action_type()
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
    first.demote(action_type.name)
    await first.persist(action_type.name)

    second = StateStoreActionPromotionRegistry(store=store, allow_legacy_metrics=True)
    await second.refresh(action_type.name)
    assert second.mode_of(action_type.name) is Mode.SHADOW
