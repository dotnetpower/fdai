"""Immutable governance-catalog exemption lookup tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.catalog_exemption import CatalogExemptionRegistry
from fdai.rule_catalog.schema.exemption import load_exemption_from_mapping
from fdai.shared.providers.exemption import (
    InMemoryExemptionRecord,
    InMemoryExemptionRegistry,
    empty_exemption_registry,
)

_SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"
_OTHER_SUBSCRIPTION = "00000000-0000-0000-0000-000000000099"
_AT = datetime(2026, 8, 15, tzinfo=UTC)


def _exemption(
    *,
    scope: dict[str, str],
    state: str = "active",
    expires_at: str = "2026-09-01T00:00:00Z",
    revoked_at: str | None = None,
):  # type: ignore[no-untyped-def]
    raw = {
        "schema_version": "1.0.0",
        "id": "exemption.rule-a.scope-a",
        "rule_id": "rule-a",
        "scope": {"subscription_id": _SUBSCRIPTION, **scope},
        "justification": "A bounded migration exception is approved for this exact scope.",
        "requested_by": "00000000-0000-0000-0000-000000000001",
        "approved_by": "00000000-0000-0000-0000-000000000002",
        "state": state,
        "created_at": "2026-08-01T00:00:00Z",
        "expires_at": expires_at,
    }
    if revoked_at is not None:
        raw["revoked_at"] = revoked_at
        raw["revoked_by"] = "00000000-0000-0000-0000-000000000003"
    return load_exemption_from_mapping(raw)


def _registry(*exemptions):  # type: ignore[no-untyped-def]
    return CatalogExemptionRegistry(
        tuple(exemptions),
        fallback=empty_exemption_registry(),
    )


def test_resource_group_match_requires_same_subscription() -> None:
    registry = _registry(_exemption(scope={"resource_group": "rg-a"}))
    matching = f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/rg-a/providers/X/items/a"
    other = f"/subscriptions/{_OTHER_SUBSCRIPTION}/resourceGroups/rg-a/providers/X/items/a"

    assert registry.find_match(rule_id="rule-a", resource_ref=matching, at=_AT) is not None
    assert registry.find_match(rule_id="rule-a", resource_ref=other, at=_AT) is None


def test_unparseable_target_cannot_match_resource_group_exemption() -> None:
    registry = _registry(_exemption(scope={"resource_group": "rg-a"}))

    assert registry.find_match(rule_id="rule-a", resource_ref="resource-a", at=_AT) is None


def test_noncanonical_azure_path_cannot_prove_resource_group_scope() -> None:
    registry = _registry(_exemption(scope={"resource_group": "rg-a"}))
    prefixed = f"/unexpected/subscriptions/{_SUBSCRIPTION}/resourceGroups/rg-a/providers/X/items/a"
    missing_provider = f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/rg-a/items/a/b/c"

    assert registry.find_match(rule_id="rule-a", resource_ref=prefixed, at=_AT) is None
    assert registry.find_match(rule_id="rule-a", resource_ref=missing_provider, at=_AT) is None


def test_resource_exemption_wins_before_resource_group() -> None:
    target = f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/rg-a/providers/X/items/a"
    broad = _exemption(scope={"resource_group": "rg-a"})
    narrow = _exemption(scope={"resource_ref": target}).model_copy(
        update={"id": "exemption.rule-a.resource-a"}
    )
    registry = _registry(broad, narrow)

    match = registry.find_match(rule_id="rule-a", resource_ref=target, at=_AT)

    assert match is not None
    assert match.exemption_id == "exemption.rule-a.resource-a"


def test_resource_reference_match_is_case_sensitive() -> None:
    registry = _registry(_exemption(scope={"resource_ref": "resource:example/Target-A"}))

    assert (
        registry.find_match(
            rule_id="rule-a",
            resource_ref="resource:example/target-a",
            at=_AT,
        )
        is None
    )


def test_inactive_or_expired_exemption_never_matches() -> None:
    target = f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/rg-a/providers/X/items/a"
    expired_state = _exemption(scope={"resource_group": "rg-a"}, state="expired")
    expired_time = _exemption(
        scope={"resource_group": "rg-a"},
        expires_at="2026-08-10T00:00:00Z",
    ).model_copy(update={"id": "exemption.rule-a.expired-time"})
    registry = _registry(expired_state, expired_time)

    assert registry.find_match(rule_id="rule-a", resource_ref=target, at=_AT) is None


def test_revoked_state_never_matches_regardless_of_audit_timestamp() -> None:
    target = f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/rg-a/providers/X/items/a"
    revoked = _exemption(
        scope={"resource_group": "rg-a"},
        state="revoked",
        revoked_at="2026-12-31T00:00:00Z",
    )

    assert _registry(revoked).find_match(rule_id="rule-a", resource_ref=target, at=_AT) is None


def test_fallback_is_used_only_when_catalog_has_no_match() -> None:
    fallback = InMemoryExemptionRegistry(
        (
            InMemoryExemptionRecord(
                exemption_id="fallback-rule-a",
                rule_id="rule-a",
                resource_group="rg-fallback",
                resource_ref=None,
                expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            ),
        )
    )
    catalog_target = f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/rg-a/providers/X/items/catalog"
    fallback_target = (
        f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/rg-fallback/providers/X/items/fallback"
    )
    registry = CatalogExemptionRegistry(
        (_exemption(scope={"resource_ref": catalog_target}),),
        fallback=fallback,
    )

    catalog_match = registry.find_match(
        rule_id="rule-a",
        resource_ref=catalog_target,
        resource_group="rg-fallback",
        at=_AT,
    )
    fallback_match = registry.find_match(
        rule_id="rule-a",
        resource_ref=fallback_target,
        resource_group="rg-fallback",
        at=_AT,
    )

    assert catalog_match is not None
    assert catalog_match.exemption_id == "exemption.rule-a.scope-a"
    assert fallback_match is not None
    assert fallback_match.exemption_id == "fallback-rule-a"


def test_expiry_boundary_is_exclusive() -> None:
    expiry = datetime(2026, 9, 1, tzinfo=UTC)
    target = f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/rg-a/providers/X/items/a"
    registry = _registry(_exemption(scope={"resource_group": "rg-a"}))

    assert (
        registry.find_match(
            rule_id="rule-a",
            resource_ref=target,
            at=expiry - timedelta(microseconds=1),
        )
        is not None
    )
    assert registry.find_match(rule_id="rule-a", resource_ref=target, at=expiry) is None


@pytest.mark.parametrize(
    "resource_ref",
    [
        "/subscriptions/not-a-uuid/resourceGroups/rg-a/providers/X/items/a",
        f"/subscriptions/{_SUBSCRIPTION}/resourceGroups//providers/X/items/a",
        f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/rg-a",
    ],
)
def test_malformed_arm_resource_id_cannot_match(resource_ref: str) -> None:
    registry = _registry(_exemption(scope={"resource_group": "rg-a"}))

    assert registry.find_match(rule_id="rule-a", resource_ref=resource_ref, at=_AT) is None
