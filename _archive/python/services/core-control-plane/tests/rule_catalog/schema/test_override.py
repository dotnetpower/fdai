"""Override domain model - modes, scope bound, distinct approver, optional expiry."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.rule_catalog.schema.override import Override, OverrideMode, resolve_override
from fdai.rule_catalog.schema.scope import ResourceContext, ScopeRef
from fdai.shared.contracts.models import Severity

_JUSTIFICATION = "Non-critical analytics workloads accept a shorter retention window."


def _ctx(**overrides: str) -> ResourceContext:
    base: dict[str, str] = {
        "organization": "org",
        "account": "account-000",
        "resource_group": "rg-analytics",
        "resource_id": "res-1",
        "resource_type": "postgresql-server",
    }
    base.update(overrides)
    return ResourceContext(**base, tags={})


def test_valid_disabled_override_at_resource_group_scope() -> None:
    override = Override(
        id="override.disabled.rg-analytics",
        target_rule="postgresql-server.point-in-time-restore",
        scope=ScopeRef.parse("scope://org/account-000/rg-analytics"),
        mode=OverrideMode.DISABLED,
        justification=_JUSTIFICATION,
        requested_by="requester",
        approver="approver",
    )
    assert override.covers(_ctx(account="account-000", organization="org"), at=datetime.now(tz=UTC))


def test_organization_scope_is_rejected() -> None:
    with pytest.raises(ValueError, match="resource-group-equivalent or narrower"):
        Override(
            id="override.org-wide",
            target_rule="rule.x",
            scope=ScopeRef.parse("scope://org"),
            mode=OverrideMode.DISABLED,
            justification=_JUSTIFICATION,
            requested_by="requester",
            approver="approver",
        )


def test_account_scope_is_rejected() -> None:
    with pytest.raises(ValueError, match="resource-group-equivalent or narrower"):
        Override(
            id="override.account-wide",
            target_rule="rule.x",
            scope=ScopeRef.parse("scope://org/account-000"),
            mode=OverrideMode.DISABLED,
            justification=_JUSTIFICATION,
            requested_by="requester",
            approver="approver",
        )


def test_resource_scope_is_accepted() -> None:
    override = Override(
        id="override.resource",
        target_rule="rule.x",
        scope=ScopeRef.parse("scope://org/account-000/rg-analytics/res-1"),
        mode=OverrideMode.DISABLED,
        justification=_JUSTIFICATION,
        requested_by="requester",
        approver="approver",
    )
    assert override.scope.level.name == "RESOURCE"


def test_self_override_is_rejected() -> None:
    with pytest.raises(ValueError, match="no self-override"):
        Override(
            id="override.self",
            target_rule="rule.x",
            scope=ScopeRef.parse("scope://org/account-000/rg-a"),
            mode=OverrideMode.DISABLED,
            justification=_JUSTIFICATION,
            requested_by="same-oid",
            approver="same-oid",
        )


def test_severity_downgrade_requires_target_severity() -> None:
    with pytest.raises(ValueError, match="severity_downgrade_to"):
        Override(
            id="override.downgrade",
            target_rule="rule.x",
            scope=ScopeRef.parse("scope://org/account-000/rg-a"),
            mode=OverrideMode.SEVERITY_DOWNGRADE,
            justification=_JUSTIFICATION,
            requested_by="requester",
            approver="approver",
        )


def test_severity_downgrade_to_set_without_matching_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="only valid with mode=severity-downgrade"):
        Override(
            id="override.bad",
            target_rule="rule.x",
            scope=ScopeRef.parse("scope://org/account-000/rg-a"),
            mode=OverrideMode.DISABLED,
            justification=_JUSTIFICATION,
            requested_by="requester",
            approver="approver",
            severity_downgrade_to=Severity.MEDIUM,
        )


def test_valid_severity_downgrade_override() -> None:
    override = Override(
        id="override.downgrade",
        target_rule="rule.x",
        scope=ScopeRef.parse("scope://org/account-000/rg-a"),
        mode=OverrideMode.SEVERITY_DOWNGRADE,
        justification=_JUSTIFICATION,
        requested_by="requester",
        approver="approver",
        severity_downgrade_to=Severity.MEDIUM,
    )
    assert override.severity_downgrade_to is Severity.MEDIUM


def test_parameter_relaxation_requires_overrides() -> None:
    with pytest.raises(ValueError, match="parameter_overrides"):
        Override(
            id="override.relax",
            target_rule="rule.x",
            scope=ScopeRef.parse("scope://org/account-000/rg-a"),
            mode=OverrideMode.PARAMETER_RELAXATION,
            justification=_JUSTIFICATION,
            requested_by="requester",
            approver="approver",
        )


def test_parameter_overrides_set_without_matching_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="only valid with mode=parameter-relaxation"):
        Override(
            id="override.bad",
            target_rule="rule.x",
            scope=ScopeRef.parse("scope://org/account-000/rg-a"),
            mode=OverrideMode.DISABLED,
            justification=_JUSTIFICATION,
            requested_by="requester",
            approver="approver",
            parameter_overrides={"min_retention_days": "3"},
        )


def test_valid_parameter_relaxation_override() -> None:
    override = Override(
        id="override.relax",
        target_rule="postgresql-server.point-in-time-restore",
        scope=ScopeRef.parse("scope://org/account-000/rg-analytics"),
        mode=OverrideMode.PARAMETER_RELAXATION,
        justification=_JUSTIFICATION,
        requested_by="requester",
        approver="approver",
        parameter_overrides={"min_retention_days": "3"},
    )
    assert override.parameter_overrides == {"min_retention_days": "3"}


def test_short_justification_is_rejected() -> None:
    with pytest.raises(ValueError, match="justification"):
        Override(
            id="override.short",
            target_rule="rule.x",
            scope=ScopeRef.parse("scope://org/account-000/rg-a"),
            mode=OverrideMode.DISABLED,
            justification="too short",
            requested_by="requester",
            approver="approver",
        )


def test_naive_expiry_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Override(
            id="override.naive",
            target_rule="rule.x",
            scope=ScopeRef.parse("scope://org/account-000/rg-a"),
            mode=OverrideMode.DISABLED,
            justification=_JUSTIFICATION,
            requested_by="requester",
            approver="approver",
            expires_at=datetime(2026, 1, 1),
        )


def test_expired_override_no_longer_covers() -> None:
    override = Override(
        id="override.expiring",
        target_rule="rule.x",
        scope=ScopeRef.parse("scope://org/account-000/rg-a"),
        mode=OverrideMode.DISABLED,
        justification=_JUSTIFICATION,
        requested_by="requester",
        approver="approver",
        expires_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    ctx = _ctx(account="account-000", organization="org", resource_group="rg-a")
    assert not override.covers(ctx, at=datetime(2026, 2, 1, tzinfo=UTC))
    assert override.covers(ctx, at=datetime(2025, 12, 1, tzinfo=UTC))


def test_covers_naive_clock_is_rejected() -> None:
    override = Override(
        id="override.x",
        target_rule="rule.x",
        scope=ScopeRef.parse("scope://org/account-000/rg-a"),
        mode=OverrideMode.DISABLED,
        justification=_JUSTIFICATION,
        requested_by="requester",
        approver="approver",
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        override.covers(_ctx(), at=datetime(2026, 1, 1))


# ---------------------------------------------------------------------------
# resolve_override
# ---------------------------------------------------------------------------


def test_resolve_override_returns_none_when_nothing_covers() -> None:
    override = Override(
        id="override.other-rule",
        target_rule="rule.other",
        scope=ScopeRef.parse("scope://org/account-000/rg-analytics"),
        mode=OverrideMode.DISABLED,
        justification=_JUSTIFICATION,
        requested_by="requester",
        approver="approver",
    )
    ctx = _ctx(account="account-000", organization="org", resource_group="rg-analytics")
    resolved = resolve_override(
        overrides=(override,), ctx=ctx, rule_id="rule.x", at=datetime.now(tz=UTC)
    )
    assert resolved is None


def test_resolve_override_returns_the_covering_override() -> None:
    override = Override(
        id="override.rg",
        target_rule="rule.x",
        scope=ScopeRef.parse("scope://org/account-000/rg-analytics"),
        mode=OverrideMode.DISABLED,
        justification=_JUSTIFICATION,
        requested_by="requester",
        approver="approver",
    )
    ctx = _ctx(account="account-000", organization="org", resource_group="rg-analytics")
    resolved = resolve_override(
        overrides=(override,), ctx=ctx, rule_id="rule.x", at=datetime.now(tz=UTC)
    )
    assert resolved is override


def test_resolve_override_narrowest_scope_wins() -> None:
    broad = Override(
        id="override.rg",
        target_rule="rule.x",
        scope=ScopeRef.parse("scope://org/account-000/rg-analytics"),
        mode=OverrideMode.DISABLED,
        justification=_JUSTIFICATION,
        requested_by="requester",
        approver="approver",
    )
    narrow = Override(
        id="override.resource",
        target_rule="rule.x",
        scope=ScopeRef.parse("scope://org/account-000/rg-analytics/res-1"),
        mode=OverrideMode.SEVERITY_DOWNGRADE,
        justification=_JUSTIFICATION,
        requested_by="requester",
        approver="approver",
        severity_downgrade_to=Severity.LOW,
    )
    ctx = _ctx(account="account-000", organization="org", resource_group="rg-analytics")
    resolved = resolve_override(
        overrides=(broad, narrow), ctx=ctx, rule_id="rule.x", at=datetime.now(tz=UTC)
    )
    assert resolved is narrow


def test_resolve_override_expired_is_skipped() -> None:
    expired = Override(
        id="override.expired",
        target_rule="rule.x",
        scope=ScopeRef.parse("scope://org/account-000/rg-analytics"),
        mode=OverrideMode.DISABLED,
        justification=_JUSTIFICATION,
        requested_by="requester",
        approver="approver",
        expires_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    ctx = _ctx(account="account-000", organization="org", resource_group="rg-analytics")
    resolved = resolve_override(
        overrides=(expired,), ctx=ctx, rule_id="rule.x", at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    assert resolved is None
