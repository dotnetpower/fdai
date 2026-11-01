"""Focused tests for bounded temporary public-access lifecycle and two-phase audit closure."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai_deployment_cli.temporary_public_access import (
    TemporaryPublicAccessCoordinator,
    TemporaryPublicAccessError,
    TemporaryPublicAccessRequest,
)

_NOW = datetime(2026, 11, 1, 7, 0, tzinfo=UTC)
_RESOURCE_ID = (
    "/subscriptions/sub-test/resourceGroups/rg-ops/providers/"
    "Microsoft.ContainerService/managedClusters/aks-fdai"
)


class _FakeFirewallDriver:
    def __init__(
        self,
        *,
        fail_revoke: bool = False,
        lingering_rule_on_readback: bool = False,
    ) -> None:
        self.fail_revoke = fail_revoke
        self.lingering_rule_on_readback = lingering_rule_on_readback
        self.active_rules: dict[tuple[str, str], str] = {}
        self.grant_calls: int = 0
        self.revoke_calls: int = 0
        self.readback_calls: int = 0

    def grant_rule(
        self,
        *,
        target_resource_id: str,
        rule_id: str,
        caller_cidr: str,
        expires_at: datetime,
    ) -> None:
        del expires_at
        self.grant_calls += 1
        self.active_rules[(target_resource_id, rule_id)] = caller_cidr

    def revoke_rule(
        self,
        *,
        target_resource_id: str,
        rule_id: str,
    ) -> None:
        self.revoke_calls += 1
        if self.fail_revoke:
            raise RuntimeError("ARM network security rule deletion timed out")
        if not self.lingering_rule_on_readback:
            self.active_rules.pop((target_resource_id, rule_id), None)

    def verify_rule_absent(
        self,
        *,
        target_resource_id: str,
        rule_id: str,
    ) -> bool:
        self.readback_calls += 1
        return (target_resource_id, rule_id) not in self.active_rules


def _request(
    *,
    correlation_id: str = "corr-temp-access-1",
    caller_cidr: str = "203.0.113.42/32",
    ttl_seconds: int = 600,
) -> TemporaryPublicAccessRequest:
    return TemporaryPublicAccessRequest(
        correlation_id=correlation_id,
        target_resource_id=_RESOURCE_ID,
        caller_cidr=caller_cidr,
        ttl_seconds=ttl_seconds,
        requested_at=_NOW,
        caller_principal_id="operator-admin",
    )


def test_successful_bounded_host_cidr_execution_cleanup_readback_and_idempotent_replay() -> None:
    driver = _FakeFirewallDriver()
    coordinator = TemporaryPublicAccessCoordinator(driver)
    req = _request()

    outcome = coordinator.execute_with_temporary_access(
        req,
        lambda: {"provisioned": True},
        closed_at=_NOW + timedelta(seconds=15),
    )

    assert outcome.status == "closed_clean"
    assert outcome.terminal_success is True
    assert outcome.requires_operator_remediation is False
    assert outcome.operation_succeeded is True
    assert outcome.cleanup_succeeded is True
    assert outcome.readback_verified_absent is True
    assert outcome.operation_result == {"provisioned": True}
    assert outcome.phase1_audit.phase == "phase_1"
    assert outcome.phase1_audit.phase_status == "granted"
    assert outcome.phase2_audit.phase == "phase_2"
    assert outcome.phase2_audit.phase_status == "closed_clean"
    assert outcome.receipt_digest.startswith("sha256:")
    assert driver.grant_calls == 1
    assert driver.revoke_calls == 1
    assert driver.readback_calls == 1

    replayed = coordinator.execute_with_temporary_access(
        req,
        lambda: {"provisioned": False},
        closed_at=_NOW + timedelta(seconds=30),
    )
    assert replayed == outcome
    assert driver.grant_calls == 1


@pytest.mark.parametrize(
    "invalid_cidr",
    [
        "0.0.0.0/0",
        "*",
        "::/0",
        "0.0.0.0/32",
        "203.0.113.0/24",
        "203.0.113.42",
        "127.0.0.1/32",
        "169.254.1.1/32",
    ],
)
def test_wildcard_non_host_or_non_global_cidr_is_rejected(invalid_cidr: str) -> None:
    with pytest.raises(TemporaryPublicAccessError):
        _request(caller_cidr=invalid_cidr)


@pytest.mark.parametrize("invalid_ttl", [0, -10, 3601, 86400, True])
def test_out_of_bounds_ttl_is_rejected(invalid_ttl: int) -> None:
    with pytest.raises(TemporaryPublicAccessError, match="ttl_seconds"):
        _request(ttl_seconds=invalid_ttl)


def test_cleanup_exception_forces_incomplete_cleanup_failed_even_when_operation_succeeded() -> None:
    driver = _FakeFirewallDriver(fail_revoke=True)
    coordinator = TemporaryPublicAccessCoordinator(driver)
    req = _request(correlation_id="corr-revoke-fail")

    outcome = coordinator.execute_with_temporary_access(
        req,
        lambda: "inner-provisioning-ok",
        closed_at=_NOW + timedelta(seconds=20),
    )

    assert outcome.operation_succeeded is True
    assert outcome.operation_result == "inner-provisioning-ok"
    assert outcome.cleanup_succeeded is False
    assert outcome.readback_verified_absent is False
    assert outcome.status == "incomplete_cleanup_failed"
    assert outcome.terminal_success is False
    assert outcome.requires_operator_remediation is True
    assert outcome.phase2_audit.phase_status == "cleanup_failed"
    assert outcome.phase2_audit.requires_operator_remediation is True
    assert outcome.cleanup_error is not None
    assert "timed out" in outcome.cleanup_error
    assert len(coordinator.audit_trail) == 3


def test_readback_verification_failure_forces_incomplete_cleanup_failed() -> None:
    driver = _FakeFirewallDriver(lingering_rule_on_readback=True)
    coordinator = TemporaryPublicAccessCoordinator(driver)
    req = _request(correlation_id="corr-readback-fail")

    outcome = coordinator.execute_with_temporary_access(
        req,
        lambda: "inner-provisioning-ok",
        closed_at=_NOW + timedelta(seconds=20),
    )

    assert outcome.operation_succeeded is True
    assert outcome.cleanup_succeeded is True
    assert outcome.readback_verified_absent is False
    assert outcome.status == "incomplete_cleanup_failed"
    assert outcome.terminal_success is False
    assert outcome.requires_operator_remediation is True
    assert outcome.phase2_audit.phase_status == "cleanup_failed"
    assert outcome.cleanup_error == "post-cleanup readback reported temporary rule still present"
