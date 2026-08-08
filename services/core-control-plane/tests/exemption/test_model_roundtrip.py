"""Loader + model invariants for :class:`Exemption`."""

from __future__ import annotations

from typing import Any

import pytest
from fdai.rule_catalog.schema.exemption import (
    Exemption,
    ExemptionError,
    ExemptionState,
    load_exemption_from_mapping,
)


def _valid_raw() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "id": "example.tag.owner-required.example-rg",
        "rule_id": "example.tag.owner-required",
        "scope": {
            "subscription_id": "00000000-0000-0000-0000-000000000000",
            "resource_group": "rg-fdai",
        },
        "justification": "Waived while an owner tag lookup service is being provisioned.",
        "requested_by": "00000000-0000-0000-0000-000000000001",
        "approved_by": "00000000-0000-0000-0000-000000000002",
        "state": "active",
        "created_at": "2026-07-05T00:00:00Z",
        "expires_at": "2026-08-05T00:00:00Z",
    }


def test_valid_exemption_roundtrips() -> None:
    exemption = load_exemption_from_mapping(_valid_raw())
    assert isinstance(exemption, Exemption)
    assert exemption.state is ExemptionState.ACTIVE
    assert exemption.scope.resource_group == "rg-fdai"


def test_missing_justification_is_rejected() -> None:
    raw = _valid_raw()
    del raw["justification"]
    with pytest.raises(ExemptionError):
        load_exemption_from_mapping(raw)


def test_short_justification_is_rejected() -> None:
    raw = _valid_raw()
    raw["justification"] = "ok"
    with pytest.raises(ExemptionError) as exc:
        load_exemption_from_mapping(raw)
    assert any("justification" in i.key for i in exc.value.issues)


def test_self_approval_is_rejected() -> None:
    raw = _valid_raw()
    raw["approved_by"] = raw["requested_by"]
    with pytest.raises(ExemptionError):
        load_exemption_from_mapping(raw)


def test_subscription_wide_scope_is_rejected() -> None:
    # Only subscription_id, no resource_group / resource_ref -> a
    # subscription-wide override, which is rejected (Human Override:
    # scope MUST be resource-group-equivalent or narrower).
    raw = _valid_raw()
    raw["scope"] = {"subscription_id": "00000000-0000-0000-0000-000000000000"}
    with pytest.raises(ExemptionError) as exc:
        load_exemption_from_mapping(raw)
    assert any("scope" in i.key or "resource_group" in i.message for i in exc.value.issues)


def test_resource_ref_only_scope_is_accepted() -> None:
    # resource_ref alone (no resource_group) is the narrowest bound - valid.
    raw = _valid_raw()
    raw["scope"] = {
        "subscription_id": "00000000-0000-0000-0000-000000000000",
        "resource_ref": "resource:example/rg/x",
    }
    exemption = load_exemption_from_mapping(raw)
    assert exemption.scope.resource_ref == "resource:example/rg/x"


def test_expiry_not_after_created_is_rejected() -> None:
    raw = _valid_raw()
    raw["expires_at"] = raw["created_at"]  # same instant → invalid
    with pytest.raises(ExemptionError):
        load_exemption_from_mapping(raw)


def test_unknown_field_is_rejected() -> None:
    raw = _valid_raw()
    raw["injected"] = "should_not_be_here"
    with pytest.raises(ExemptionError):
        load_exemption_from_mapping(raw)


def test_invalid_state_is_rejected() -> None:
    raw = _valid_raw()
    raw["state"] = "pending"  # not in enum
    with pytest.raises(ExemptionError):
        load_exemption_from_mapping(raw)
