"""ExemptionRegistry - human-override lookup contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.shared.providers.exemption import (
    ExemptionRegistry,
    InMemoryExemptionRecord,
    InMemoryExemptionRegistry,
    empty_exemption_registry,
)


def _at(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=UTC)


def _record(**overrides: object) -> InMemoryExemptionRecord:
    base = {
        "exemption_id": "exempt-1",
        "rule_id": "object-storage.public-access.deny",
        "resource_group": None,
        "resource_ref": None,
        "expires_at": _at("2099-01-01T00:00:00"),
        "revoked_at": None,
        "justification": "vetted legacy workload",
    }
    base.update(overrides)
    return InMemoryExemptionRecord(**base)  # type: ignore[arg-type]


def test_empty_registry_never_matches() -> None:
    registry: ExemptionRegistry = empty_exemption_registry()
    assert registry.find_match(rule_id="r", resource_ref="x") is None


def test_registry_ignores_expired_records() -> None:
    registry = InMemoryExemptionRegistry(
        records=(
            _record(
                resource_group="rg-a",
                expires_at=_at("2024-01-01T00:00:00"),  # long past
            ),
        )
    )
    assert (
        registry.find_match(
            rule_id="object-storage.public-access.deny",
            resource_ref="/subscriptions/x/resourceGroups/rg-a/providers/foo/bar/y",
            resource_group="rg-a",
            at=_at("2026-07-05T00:00:00"),
        )
        is None
    )


def test_registry_ignores_revoked_records() -> None:
    registry = InMemoryExemptionRegistry(
        records=(
            _record(
                resource_group="rg-a",
                revoked_at=_at("2026-06-01T00:00:00"),
            ),
        )
    )
    assert (
        registry.find_match(
            rule_id="object-storage.public-access.deny",
            resource_ref="x",
            resource_group="rg-a",
            at=_at("2026-07-05T00:00:00"),
        )
        is None
    )


def test_registry_requires_scope_match_by_resource_group() -> None:
    registry = InMemoryExemptionRegistry(
        records=(_record(resource_group="rg-a"),),
    )
    assert (
        registry.find_match(
            rule_id="object-storage.public-access.deny",
            resource_ref="x",
            resource_group="rg-b",
            at=_at("2026-07-05T00:00:00"),
        )
        is None
    )
    match = registry.find_match(
        rule_id="object-storage.public-access.deny",
        resource_ref="x",
        resource_group="rg-a",
        at=_at("2026-07-05T00:00:00"),
    )
    assert match is not None
    assert match.exemption_id == "exempt-1"
    assert "rg=rg-a" in match.scope_summary


def test_registry_matches_by_narrow_resource_ref() -> None:
    registry = InMemoryExemptionRegistry(
        records=(_record(resource_ref="/subs/x/rg/y/z/target"),),
    )
    match = registry.find_match(
        rule_id="object-storage.public-access.deny",
        resource_ref="/subs/x/rg/y/z/target",
        at=_at("2026-07-05T00:00:00"),
    )
    assert match is not None
    assert "resource=/subs/x/rg/y/z/target" in match.scope_summary


def test_registry_rejects_unscoped_records() -> None:
    """A record with neither ``resource_group`` nor ``resource_ref``
    covers too much (subscription-wide) - the risk-gate MUST NOT honor
    it. That is a rule retirement, not an override."""
    registry = InMemoryExemptionRegistry(
        records=(_record(resource_group=None, resource_ref=None),),
    )
    assert (
        registry.find_match(
            rule_id="object-storage.public-access.deny",
            resource_ref="anything",
            resource_group="rg-a",
            at=_at("2026-07-05T00:00:00"),
        )
        is None
    )


def test_registry_returns_none_for_unknown_rule() -> None:
    registry = InMemoryExemptionRegistry(
        records=(_record(resource_group="rg-a"),),
    )
    assert (
        registry.find_match(
            rule_id="some.other.rule",
            resource_ref="x",
            resource_group="rg-a",
            at=_at("2026-07-05T00:00:00"),
        )
        is None
    )


def test_registry_default_at_uses_current_time() -> None:
    future = datetime.now(tz=UTC) + timedelta(days=365)
    registry = InMemoryExemptionRegistry(
        records=(_record(resource_group="rg-a", expires_at=future),),
    )
    match = registry.find_match(
        rule_id="object-storage.public-access.deny",
        resource_ref="x",
        resource_group="rg-a",
    )
    assert match is not None
