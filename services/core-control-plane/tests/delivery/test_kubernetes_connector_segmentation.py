"""Shadow segmentation registration and probes are evidence only."""

from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.kubernetes_connector_segmentation import (
    SEGMENTATION_PREFIX,
    SegmentationProbe,
    SegmentationRegistrationError,
    ShadowSegmentationRegistration,
    assess_segmentation_probes,
    register_shadow_segmentation,
)
from fdai.shared.providers.testing import InMemoryStateStore

NOW = datetime(2026, 10, 4, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64


def registration(**changes: object) -> ShadowSegmentationRegistration:
    value = {
        "target_ref": "cluster-example",
        "namespace": "example",
        "capability_ref": "network-segmentation",
        "registered_at": NOW,
        "expires_at": NOW + timedelta(minutes=10),
        "recovery_digest": DIGEST,
        "management_dependency_digests": [DIGEST, OTHER_DIGEST],
        "execution_authority": False,
    }
    value.update(changes)
    return ShadowSegmentationRegistration.model_validate(value)


def probe(kind: str, observed: str, *, observer: str) -> SegmentationProbe:
    return SegmentationProbe.model_validate(
        {
            "target_ref": "cluster-example",
            "namespace": "example",
            "probe_ref": f"{kind}-{observer}",
            "observer_ref": observer,
            "kind": kind,
            "observed": observed,
            "observed_at": NOW,
            "expires_at": NOW + timedelta(minutes=5),
            "evidence_digest": DIGEST if observed != "unknown" else None,
        }
    )


async def test_register_shadow_segmentation_is_idempotent_and_no_authority() -> None:
    store = InMemoryStateStore()
    assert await register_shadow_segmentation(store, registration(), now=lambda: NOW)
    assert not await register_shadow_segmentation(store, registration(), now=lambda: NOW)
    rows = await store.read_states(SEGMENTATION_PREFIX, limit=10)
    assert rows[0]["registration"]["mode"] == "shadow"
    assert rows[0]["registration"]["execution_authority"] is False
    assert len(list(store.audit_entries)) == 1
    with pytest.raises(SegmentationRegistrationError):
        await register_shadow_segmentation(
            store, registration(recovery_digest=OTHER_DIGEST), now=lambda: NOW
        )


async def test_corrupt_recovery_checkpoint_is_not_accepted() -> None:
    store = InMemoryStateStore()
    await register_shadow_segmentation(store, registration(), now=lambda: NOW)
    key = next(iter(store._state))  # noqa: SLF001 - white-box corruption for recovery proof.
    broken = dict(store._state[key])  # noqa: SLF001
    broken["registration_digest"] = OTHER_DIGEST
    await store.write_state(key, broken)
    with pytest.raises(SegmentationRegistrationError):
        await register_shadow_segmentation(store, registration(), now=lambda: NOW)


def test_independent_positive_and_negative_probes_gate_review_readiness() -> None:
    result = assess_segmentation_probes(
        registration(),
        (
            probe("positive", "connected", observer="observer-a"),
            probe("negative", "blocked", observer="observer-b"),
        ),
        now=NOW,
    )
    assert result.status == "ready_for_review"
    assert result.execution_authority is False
    not_independent = assess_segmentation_probes(
        registration(),
        (
            probe("positive", "connected", observer="observer-a"),
            probe("negative", "blocked", observer="observer-a"),
        ),
        now=NOW,
    )
    assert not_independent.status == "needs_evidence"
    failed_negative = assess_segmentation_probes(
        registration(),
        (
            probe("positive", "connected", observer="observer-a"),
            probe("negative", "connected", observer="observer-b"),
        ),
        now=NOW,
    )
    assert failed_negative.status == "blocked"
