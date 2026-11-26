"""Focused tests for ActionType-to-license-capability mapping and clock-rollback detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.capability_catalog.defaults import default_capability_catalog
from fdai.core.licensing import (
    LicenseClaims,
    LicenseEntitlementAuthority,
    encode_license_token,
)
from fdai.core.licensing.trial import TrialRecord, TrialStatus
from fdai.delivery.licensing_capability_map import (
    BASE_MUTATION_CAPABILITY_ID,
    SelectiveActingLicenseVerifier,
    TrustedTimeRollbackDetector,
    required_license_capabilities_for_action_type,
)

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
SIGNATURE = b"s" * 64


class _AcceptAllVerifier:
    def verify(self, document: bytes, signature: bytes) -> bool:
        del document, signature
        return True


def _make_authority(*capability_ids: str) -> LicenseEntitlementAuthority:
    claims = LicenseClaims(
        license_id="lic-selective-01",
        distribution_id="fdai-upstream",
        capability_ids=tuple(sorted(set(capability_ids))),
        not_before=NOW - timedelta(days=1),
        not_after=NOW + timedelta(days=14),
    )
    token = encode_license_token(claims.canonical_document(), SIGNATURE)
    return LicenseEntitlementAuthority(
        catalog=default_capability_catalog(),
        token=token,
        verifier=_AcceptAllVerifier(),
        require_license=True,
    )


@pytest.mark.parametrize(
    ("action_type_id", "expected_capabilities"),
    [
        (
            "tool.run-chaos-experiment",
            frozenset({BASE_MUTATION_CAPABILITY_ID, "chaos.run_experiment"}),
        ),
        (
            "ops.rollback-kubernetes-rollout",
            frozenset({BASE_MUTATION_CAPABILITY_ID, "operations.kubectl"}),
        ),
        (
            "remediate.kubernetes-network-policy",
            frozenset({BASE_MUTATION_CAPABILITY_ID, "operations.kubectl"}),
        ),
        (
            "tool.open-incident-ticket",
            frozenset({BASE_MUTATION_CAPABILITY_ID, "incident.create"}),
        ),
        (
            "tool.file-irp-followup",
            frozenset({BASE_MUTATION_CAPABILITY_ID, "incident.platform-writeback"}),
        ),
        (
            "ops.restart-service",
            frozenset({BASE_MUTATION_CAPABILITY_ID}),
        ),
        (
            "remediate.right-size",
            frozenset({BASE_MUTATION_CAPABILITY_ID}),
        ),
    ],
)
def test_deterministic_action_type_to_license_capability_mapping(
    action_type_id: str,
    expected_capabilities: frozenset[str],
) -> None:
    first = required_license_capabilities_for_action_type(action_type_id)
    second = required_license_capabilities_for_action_type(action_type_id)

    assert first == expected_capabilities
    assert second == expected_capabilities


@pytest.mark.parametrize("bad_id", ["", "invalid", "unknown.action", "ops.UPPERCASE"])
def test_invalid_action_type_identifier_is_rejected(bad_id: str) -> None:
    with pytest.raises(ValueError):
        required_license_capabilities_for_action_type(bad_id)


def test_selective_acting_license_grants_only_mapped_action_types() -> None:
    authority = _make_authority(BASE_MUTATION_CAPABILITY_ID, "operations.kubectl")
    verifier = SelectiveActingLicenseVerifier(authority=authority)

    k8s_decision = verifier.evaluate(
        action_type_id="ops.rollback-kubernetes-rollout",
        now=NOW,
    )
    assert k8s_decision.allowed is True
    assert k8s_decision.missing_capability_ids == frozenset()
    assert k8s_decision.execution_authority is False

    chaos_decision = verifier.evaluate(
        action_type_id="tool.run-chaos-experiment",
        now=NOW,
    )
    assert chaos_decision.allowed is False
    assert chaos_decision.missing_capability_ids == frozenset({"chaos.run_experiment"})
    assert chaos_decision.execution_authority is False


def test_falsifying_wall_clock_rollback_latches_sticky_denial() -> None:
    detector = TrustedTimeRollbackDetector()
    authority = _make_authority(
        BASE_MUTATION_CAPABILITY_ID,
        "chaos.run_experiment",
        "operations.kubectl",
    )
    verifier = SelectiveActingLicenseVerifier(
        authority=authority,
        clock_detector=detector,
    )

    initial = verifier.evaluate(action_type_id="ops.restart-service", now=NOW)
    assert initial.allowed is True
    assert detector.clock_regressed is False

    rolled_back_now = NOW - timedelta(minutes=5)
    after_rollback = verifier.evaluate(
        action_type_id="ops.restart-service",
        now=rolled_back_now,
    )
    assert after_rollback.allowed is False
    assert after_rollback.status == "clock_regression"
    assert detector.clock_regressed is True

    # Advancing the host clock forward again MUST NOT clear sticky clock_regression denial.
    later_now = NOW + timedelta(minutes=10)
    after_recovery_attempt = verifier.evaluate(
        action_type_id="ops.restart-service",
        now=later_now,
    )
    assert after_recovery_attempt.allowed is False
    assert after_recovery_attempt.status == "clock_regression"


def test_trusted_time_skew_marks_trial_record_clock_blocked() -> None:
    detector = TrustedTimeRollbackDetector(max_trusted_skew=timedelta(seconds=30))
    record = TrialRecord(
        installation_binding="a" * 64,
        deployment_binding="b" * 64,
        activated_at=NOW - timedelta(days=5),
        last_observed_at=NOW - timedelta(hours=1),
    )

    updated, decision = detector.observe_trial_record(
        record,
        host_now=NOW,
        trusted_now=NOW + timedelta(minutes=2),
    )
    assert decision.clock_regressed is True
    assert updated.clock_blocked is True
    assert updated.status is TrialStatus.CLOCK_BLOCKED
