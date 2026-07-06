"""Enforcer tests — role/capability gating + framework-neutral dependency shape."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aiopspilot.core.rbac.enforcer import (
    AuthorizationError,
    BreakGlassExpiredError,
    RoleEnforcer,
    RoleRequiredError,
    require_capability,
    require_roles,
)
from aiopspilot.core.rbac.resolver import BreakGlassActivation, Principal
from aiopspilot.core.rbac.roles import Capability, Role


def _principal(*roles: Role, oid: str = "u1") -> Principal:
    return Principal(oid=oid, roles=frozenset(roles))


class TestAuthorize:
    def test_pass_when_principal_carries_required_role(self) -> None:
        enforcer = RoleEnforcer()
        enforcer.authorize(_principal(Role.APPROVER), [Role.APPROVER])

    def test_pass_when_principal_carries_any_of_required_roles(self) -> None:
        enforcer = RoleEnforcer()
        enforcer.authorize(_principal(Role.OWNER), [Role.APPROVER, Role.OWNER])

    def test_deny_when_principal_lacks_required_role(self) -> None:
        enforcer = RoleEnforcer()
        with pytest.raises(RoleRequiredError):
            enforcer.authorize(_principal(Role.READER), [Role.APPROVER])

    def test_deny_when_principal_has_no_roles(self) -> None:
        enforcer = RoleEnforcer()
        with pytest.raises(RoleRequiredError):
            enforcer.authorize(_principal(), [Role.READER])

    def test_empty_required_roles_is_programmer_error(self) -> None:
        enforcer = RoleEnforcer()
        with pytest.raises(ValueError, match="at least one required role"):
            enforcer.authorize(_principal(Role.OWNER), [])

    def test_denial_message_lists_effective_and_required_roles(self) -> None:
        enforcer = RoleEnforcer()
        with pytest.raises(RoleRequiredError) as excinfo:
            enforcer.authorize(_principal(Role.READER), [Role.OWNER])
        msg = str(excinfo.value)
        assert "Owner" in msg
        assert "Reader" in msg

    def test_authorization_error_is_base_class_for_role_required(self) -> None:
        assert issubclass(RoleRequiredError, AuthorizationError)


class TestRequireCapability:
    def test_pass_when_role_covers_capability(self) -> None:
        enforcer = RoleEnforcer()
        enforcer.require_capability(_principal(Role.OWNER), Capability.APPLY_INFRA_IAC)

    def test_deny_when_no_role_covers_capability(self) -> None:
        enforcer = RoleEnforcer()
        with pytest.raises(RoleRequiredError):
            enforcer.require_capability(_principal(Role.CONTRIBUTOR), Capability.APPLY_INFRA_IAC)

    def test_no_roles_means_no_capability(self) -> None:
        enforcer = RoleEnforcer()
        with pytest.raises(RoleRequiredError):
            enforcer.require_capability(_principal(), Capability.VIEW_CONSOLE)


class TestBreakGlassExpiry:
    def _fixed_clock(self, now: datetime) -> RoleEnforcer:
        return RoleEnforcer(clock=lambda: now)

    def _elevated(self, *, activated: datetime, expires: datetime) -> Principal:
        return Principal(
            oid="bg",
            roles=frozenset({Role.OWNER, Role.BREAK_GLASS}),
            break_glass=BreakGlassActivation(
                incident_id="INC-1",
                activated_at=activated,
                expires_at=expires,
                actor_oid="bg",
            ),
        )

    def test_break_glass_within_timebox_passes(self) -> None:
        activated = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
        now = activated + timedelta(minutes=10)
        enforcer = self._fixed_clock(now)
        p = self._elevated(activated=activated, expires=activated + timedelta(hours=1))
        enforcer.authorize(p, [Role.BREAK_GLASS])

    def test_break_glass_after_expiry_is_denied(self) -> None:
        activated = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
        expires = activated + timedelta(minutes=15)
        now = expires + timedelta(minutes=1)
        enforcer = self._fixed_clock(now)
        p = self._elevated(activated=activated, expires=expires)
        with pytest.raises(BreakGlassExpiredError):
            enforcer.authorize(p, [Role.BREAK_GLASS])

    def test_break_glass_without_activation_stamp_is_denied(self) -> None:
        # A principal carrying the BreakGlass role but no activation is
        # a fail-close scenario — the resolver never produces this shape
        # legitimately, so an attacker who forges one gets rejected.
        enforcer = RoleEnforcer()
        p = Principal(oid="bg", roles=frozenset({Role.BREAK_GLASS}), break_glass=None)
        with pytest.raises(BreakGlassExpiredError):
            enforcer.authorize(p, [Role.BREAK_GLASS])

    def test_expired_break_glass_leaves_other_roles_denied_too(self) -> None:
        # Once the effective-roles computation fails-closed on break-glass,
        # ANY authorize() call on the principal raises. This is the
        # documented behavior: expired break-glass forces re-auth, not a
        # silent role-set trim.
        activated = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
        expires = activated + timedelta(minutes=5)
        now = expires + timedelta(minutes=1)
        enforcer = self._fixed_clock(now)
        p = self._elevated(activated=activated, expires=expires)
        with pytest.raises(BreakGlassExpiredError):
            enforcer.authorize(p, [Role.OWNER])


class TestRequireRolesFactory:
    def test_returns_principal_when_authorized(self) -> None:
        dep = require_roles(Role.APPROVER, Role.OWNER)
        p = _principal(Role.APPROVER)
        assert dep(p) is p  # returns the exact object for DI injection

    def test_raises_when_unauthorized(self) -> None:
        dep = require_roles(Role.OWNER)
        with pytest.raises(RoleRequiredError):
            dep(_principal(Role.READER))

    def test_shared_enforcer_used_across_calls(self) -> None:
        activated = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
        expires = activated + timedelta(seconds=1)
        now = activated + timedelta(minutes=5)  # past expiry
        enforcer = RoleEnforcer(clock=lambda: now)
        dep = require_roles(Role.BREAK_GLASS, enforcer=enforcer)
        p = Principal(
            oid="bg",
            roles=frozenset({Role.BREAK_GLASS}),
            break_glass=BreakGlassActivation(
                incident_id="INC-1",
                activated_at=activated,
                expires_at=expires,
                actor_oid="bg",
            ),
        )
        with pytest.raises(BreakGlassExpiredError):
            dep(p)

    def test_zero_roles_rejected(self) -> None:
        with pytest.raises(ValueError):
            require_roles()


class TestRequireCapabilityFactory:
    def test_returns_principal_when_capable(self) -> None:
        dep = require_capability(Capability.VIEW_CONSOLE)
        p = _principal(Role.READER)
        assert dep(p) is p

    def test_raises_when_not_capable(self) -> None:
        dep = require_capability(Capability.APPLY_INFRA_IAC)
        with pytest.raises(RoleRequiredError):
            dep(_principal(Role.APPROVER))

    def test_break_glass_can_trigger_kill_switch(self) -> None:
        # Break-glass MUST retain the kill-switch capability so §7 works.
        activated = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
        expires = activated + timedelta(hours=1)
        now = activated + timedelta(minutes=5)
        enforcer = RoleEnforcer(clock=lambda: now)
        dep = require_capability(Capability.TRIGGER_KILL_SWITCH, enforcer=enforcer)
        p = Principal(
            oid="bg",
            roles=frozenset({Role.BREAK_GLASS}),
            break_glass=BreakGlassActivation(
                incident_id="INC-1",
                activated_at=activated,
                expires_at=expires,
                actor_oid="bg",
            ),
        )
        assert dep(p) is p
