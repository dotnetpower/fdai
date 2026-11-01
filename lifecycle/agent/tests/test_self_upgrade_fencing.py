"""Focused tests for component-specific dual-slot controller role fencing and crash recovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai_lifecycle_agent.self_upgrade_fencing import (
    ComponentSelfUpgradeController,
    RoleFencingError,
    SchemaDowngradeError,
    TrialContinuityViolationError,
)

_TRIAL_ANCHOR = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
_NOW = datetime(2026, 11, 1, 5, 0, tzinfo=UTC)
_LEASE = _NOW + timedelta(minutes=15)
_DIGEST_V1 = "sha256:" + "1" * 64
_DIGEST_V2 = "sha256:" + "2" * 64
_DIGEST_V3 = "sha256:" + "3" * 64


def _bootstrap_controller() -> ComponentSelfUpgradeController:
    controller = ComponentSelfUpgradeController()
    controller.register_component(
        component="core_control_plane",
        active_slot="blue",
        fencing_epoch=1,
        binary_digest=_DIGEST_V1,
        schema_version=3,
        trial_anchor_at=_TRIAL_ANCHOR,
        monotonic_clock_floor_ns=1_000_000,
        lease_expires_at=_LEASE,
        now=_NOW,
    )
    return controller


def test_active_standby_fencing_epoch_enforcement_and_standby_execution_denial() -> None:
    controller = _bootstrap_controller()

    active_fence = controller.assert_execution_allowed(
        "core_control_plane", "blue", epoch=1, now=_NOW + timedelta(minutes=1)
    )
    assert active_fence.role == "active"
    assert active_fence.fencing_epoch == 1
    fence_dict = active_fence.to_dict()
    assert fence_dict["component"] == "core_control_plane"
    assert fence_dict["slot"] == "blue"
    assert fence_dict["role"] == "active"
    assert fence_dict["fencing_epoch"] == 1
    assert fence_dict["binary_digest"] == _DIGEST_V1
    assert controller.verify_transition_chain() is True

    with pytest.raises(RoleFencingError, match="non-active role 'fenced'"):
        controller.assert_execution_allowed(
            "core_control_plane", "green", epoch=1, now=_NOW + timedelta(minutes=1)
        )

    controller.stage_candidate_slot(
        component="core_control_plane",
        candidate_slot="green",
        binary_digest=_DIGEST_V2,
        candidate_schema_version=4,
        trial_anchor_at=_TRIAL_ANCHOR,
        monotonic_clock_floor_ns=1_500_000,
        lease_expires_at=_LEASE,
        now=_NOW + timedelta(minutes=2),
    )

    with pytest.raises(RoleFencingError, match="non-active role 'standby'"):
        controller.assert_execution_allowed(
            "core_control_plane", "green", epoch=1, now=_NOW + timedelta(minutes=3)
        )

    with pytest.raises(RoleFencingError, match="expired lease"):
        controller.assert_execution_allowed(
            "core_control_plane", "blue", epoch=1, now=_LEASE + timedelta(seconds=1)
        )

    with pytest.raises(RoleFencingError, match="independent health/readiness verification"):
        controller.promote_standby_slot(
            component="core_control_plane",
            standby_slot="green",
            health_verified=False,
            lease_expires_at=_NOW + timedelta(minutes=30),
            now=_NOW + timedelta(minutes=4),
        )

    promoted = controller.promote_standby_slot(
        component="core_control_plane",
        standby_slot="green",
        health_verified=True,
        lease_expires_at=_NOW + timedelta(minutes=30),
        now=_NOW + timedelta(minutes=4),
    )
    assert promoted.slot == "green"
    assert promoted.role == "active"
    assert promoted.fencing_epoch == 2

    with pytest.raises(RoleFencingError, match="non-active role 'fenced'"):
        controller.assert_execution_allowed(
            "core_control_plane", "blue", epoch=1, now=_NOW + timedelta(minutes=5)
        )
    with pytest.raises(RoleFencingError, match="stale fencing epoch"):
        controller.assert_execution_allowed(
            "core_control_plane", "green", epoch=1, now=_NOW + timedelta(minutes=5)
        )

    verified_green = controller.assert_execution_allowed(
        "core_control_plane", "green", epoch=2, now=_NOW + timedelta(minutes=5)
    )
    assert verified_green.slot == "green"


def test_schema_downgrade_rejection_and_trial_clock_anchor_preservation() -> None:
    controller = _bootstrap_controller()

    with pytest.raises(SchemaDowngradeError, match="downgrades active schema_version"):
        controller.stage_candidate_slot(
            component="core_control_plane",
            candidate_slot="green",
            binary_digest=_DIGEST_V2,
            candidate_schema_version=2,
            trial_anchor_at=_TRIAL_ANCHOR,
            monotonic_clock_floor_ns=1_000_000,
            lease_expires_at=_LEASE,
            now=_NOW + timedelta(minutes=1),
        )

    with pytest.raises(TrialContinuityViolationError, match="trial_anchor_at"):
        controller.stage_candidate_slot(
            component="core_control_plane",
            candidate_slot="green",
            binary_digest=_DIGEST_V2,
            candidate_schema_version=4,
            trial_anchor_at=_TRIAL_ANCHOR + timedelta(days=1),
            monotonic_clock_floor_ns=1_000_000,
            lease_expires_at=_LEASE,
            now=_NOW + timedelta(minutes=1),
        )

    with pytest.raises(TrialContinuityViolationError, match="monotonic_clock_floor_ns"):
        controller.stage_candidate_slot(
            component="core_control_plane",
            candidate_slot="green",
            binary_digest=_DIGEST_V2,
            candidate_schema_version=4,
            trial_anchor_at=_TRIAL_ANCHOR,
            monotonic_clock_floor_ns=999_999,
            lease_expires_at=_LEASE,
            now=_NOW + timedelta(minutes=1),
        )

    controller.stage_candidate_slot(
        component="core_control_plane",
        candidate_slot="green",
        binary_digest=_DIGEST_V2,
        candidate_schema_version=3,
        trial_anchor_at=_TRIAL_ANCHOR,
        monotonic_clock_floor_ns=2_000_000,
        lease_expires_at=_LEASE,
        now=_NOW + timedelta(minutes=2),
    )
    controller.promote_standby_slot(
        component="core_control_plane",
        standby_slot="green",
        health_verified=True,
        lease_expires_at=_NOW + timedelta(minutes=30),
        now=_NOW + timedelta(minutes=3),
    )

    rolled_back = controller.rollback_to_slot(
        component="core_control_plane",
        target_slot="blue",
        lease_expires_at=_NOW + timedelta(minutes=45),
        now=_NOW + timedelta(minutes=5),
        monotonic_clock_floor_ns=2_500_000,
    )
    assert rolled_back.slot == "blue"
    assert rolled_back.role == "active"
    assert rolled_back.fencing_epoch == 3
    assert rolled_back.trial_anchor_at == _TRIAL_ANCHOR
    assert rolled_back.monotonic_clock_floor_ns == 2_500_000
    assert rolled_back.schema_version == 3

    controller.stage_candidate_slot(
        component="core_control_plane",
        candidate_slot="green",
        binary_digest=_DIGEST_V3,
        candidate_schema_version=5,
        trial_anchor_at=_TRIAL_ANCHOR,
        monotonic_clock_floor_ns=3_000_000,
        lease_expires_at=_NOW + timedelta(minutes=50),
        now=_NOW + timedelta(minutes=6),
    )
    controller.promote_standby_slot(
        component="core_control_plane",
        standby_slot="green",
        health_verified=True,
        lease_expires_at=_NOW + timedelta(minutes=60),
        now=_NOW + timedelta(minutes=7),
    )
    with pytest.raises(SchemaDowngradeError, match="rollback to blue rejected"):
        controller.rollback_to_slot(
            component="core_control_plane",
            target_slot="blue",
            lease_expires_at=_NOW + timedelta(minutes=90),
            now=_NOW + timedelta(minutes=8),
        )


def test_durable_crash_recovery_mid_cutover_restores_single_active_invariant() -> None:
    controller = _bootstrap_controller()
    controller.stage_candidate_slot(
        component="core_control_plane",
        candidate_slot="green",
        binary_digest=_DIGEST_V2,
        candidate_schema_version=4,
        trial_anchor_at=_TRIAL_ANCHOR,
        monotonic_clock_floor_ns=4_000_000,
        lease_expires_at=_LEASE,
        now=_NOW + timedelta(minutes=1),
    )

    with pytest.raises(RoleFencingError, match="simulated crash after fencing prior active slot"):
        controller.promote_standby_slot(
            component="core_control_plane",
            standby_slot="green",
            health_verified=True,
            lease_expires_at=_NOW + timedelta(minutes=30),
            now=_NOW + timedelta(minutes=2),
            interrupt_after_fence=True,
        )

    slots_mid_crash = controller.component_slots("core_control_plane")
    assert slots_mid_crash["blue"].role == "fenced"
    assert slots_mid_crash["green"].role == "standby"

    recovered = controller.recover_after_restart(
        component="core_control_plane",
        lease_expires_at=_NOW + timedelta(minutes=40),
        now=_NOW + timedelta(minutes=3),
    )
    assert recovered.slot == "green"
    assert recovered.role == "active"
    assert recovered.fencing_epoch == 3
    assert recovered.schema_version == 4
    assert recovered.trial_anchor_at == _TRIAL_ANCHOR
    assert recovered.monotonic_clock_floor_ns == 4_000_000

    slots_after = controller.component_slots("core_control_plane")
    active_slots = [s.slot for s in slots_after.values() if s.role == "active"]
    assert active_slots == ["green"]
    assert slots_after["blue"].role == "fenced"
    assert controller.transition_log[-1].transition_kind == "recover"
    assert controller.transition_log[-1].record_digest.startswith("sha256:")


def test_rolled_back_digest_fencing_and_future_trial_anchor_rejection() -> None:
    controller = ComponentSelfUpgradeController()
    with pytest.raises(TrialContinuityViolationError, match="trial_anchor_at"):
        controller.register_component(
            component="core_control_plane",
            active_slot="blue",
            fencing_epoch=1,
            binary_digest=_DIGEST_V1,
            schema_version=3,
            trial_anchor_at=_NOW + timedelta(seconds=1),
            monotonic_clock_floor_ns=1_000_000,
            lease_expires_at=_LEASE,
            now=_NOW,
        )

    controller = _bootstrap_controller()
    with pytest.raises(TrialContinuityViolationError, match="trial_anchor_at"):
        controller.stage_candidate_slot(
            component="core_control_plane",
            candidate_slot="green",
            binary_digest=_DIGEST_V2,
            candidate_schema_version=3,
            trial_anchor_at=_NOW + timedelta(minutes=5),
            monotonic_clock_floor_ns=1_000_000,
            lease_expires_at=_LEASE,
            now=_NOW + timedelta(minutes=1),
        )

    controller.stage_candidate_slot(
        component="core_control_plane",
        candidate_slot="green",
        binary_digest=_DIGEST_V2,
        candidate_schema_version=3,
        trial_anchor_at=_TRIAL_ANCHOR,
        monotonic_clock_floor_ns=1_500_000,
        lease_expires_at=_LEASE,
        now=_NOW + timedelta(minutes=1),
    )
    controller.promote_standby_slot(
        component="core_control_plane",
        standby_slot="green",
        health_verified=True,
        lease_expires_at=_NOW + timedelta(minutes=30),
        now=_NOW + timedelta(minutes=2),
    )
    controller.rollback_to_slot(
        component="core_control_plane",
        target_slot="blue",
        lease_expires_at=_NOW + timedelta(minutes=40),
        now=_NOW + timedelta(minutes=3),
    )

    controller.stage_candidate_slot(
        component="core_control_plane",
        candidate_slot="green",
        binary_digest=_DIGEST_V2,
        candidate_schema_version=3,
        trial_anchor_at=_TRIAL_ANCHOR,
        monotonic_clock_floor_ns=2_000_000,
        lease_expires_at=_NOW + timedelta(minutes=50),
        now=_NOW + timedelta(minutes=4),
    )
    with pytest.raises(RoleFencingError, match="previously rolled-back binary_digest"):
        controller.promote_standby_slot(
            component="core_control_plane",
            standby_slot="green",
            health_verified=True,
            lease_expires_at=_NOW + timedelta(minutes=60),
            now=_NOW + timedelta(minutes=5),
        )

    re_promoted = controller.promote_standby_slot(
        component="core_control_plane",
        standby_slot="green",
        health_verified=True,
        lease_expires_at=_NOW + timedelta(minutes=60),
        now=_NOW + timedelta(minutes=5),
        allow_previously_rolled_back_digest=True,
    )
    assert re_promoted.role == "active"
    assert re_promoted.binary_digest == _DIGEST_V2
    assert controller.verify_transition_chain() is True

    controller.stage_candidate_slot(
        component="core_control_plane",
        candidate_slot="blue",
        binary_digest=_DIGEST_V2,
        candidate_schema_version=3,
        trial_anchor_at=_TRIAL_ANCHOR,
        monotonic_clock_floor_ns=2_500_000,
        lease_expires_at=_NOW + timedelta(minutes=70),
        now=_NOW + timedelta(minutes=6),
    )
    with pytest.raises(RoleFencingError, match="identical binary_digest"):
        controller.promote_standby_slot(
            component="core_control_plane",
            standby_slot="blue",
            health_verified=True,
            lease_expires_at=_NOW + timedelta(minutes=80),
            now=_NOW + timedelta(minutes=7),
        )
    same_digest_promoted = controller.promote_standby_slot(
        component="core_control_plane",
        standby_slot="blue",
        health_verified=True,
        lease_expires_at=_NOW + timedelta(minutes=80),
        now=_NOW + timedelta(minutes=7),
        allow_previously_rolled_back_digest=True,
        allow_same_binary_digest=True,
    )
    assert same_digest_promoted.slot == "blue"
    assert same_digest_promoted.role == "active"
    assert controller.verify_transition_chain() is True

    object.__setattr__(controller._transition_log[-1], "record_digest", "sha256:" + "0" * 64)
    assert controller.verify_transition_chain() is False
