"""Pure exemption lifecycle decisions (rule-governance.md "Exemptions")."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.rule_catalog.schema.exemption import Exemption, load_exemption_from_mapping
from fdai.rule_catalog.schema.exemption_lifecycle import (
    ExemptionLifecycleAction,
    plan_exemption_lifecycle,
)


def _exemption(
    *,
    exemption_id: str,
    created_at: str,
    expires_at: str,
    state: str = "active",
) -> Exemption:
    raw: dict[str, object] = {
        "schema_version": "1.0.0",
        "id": exemption_id,
        "rule_id": "rule-a",
        "scope": {
            "subscription_id": "00000000-0000-0000-0000-000000000000",
            "resource_group": "rg-a",
        },
        "justification": "Waived while a migration is being completed for this scope.",
        "requested_by": "00000000-0000-0000-0000-000000000001",
        "approved_by": "00000000-0000-0000-0000-000000000002",
        "state": state,
        "created_at": created_at,
        "expires_at": expires_at,
    }
    if state == "revoked":
        raw["revoked_at"] = expires_at
        raw["revoked_by"] = "00000000-0000-0000-0000-000000000003"
    return load_exemption_from_mapping(raw)


_NOW = datetime(2026, 8, 20, tzinfo=UTC)


def test_far_from_expiry_has_no_decision() -> None:
    exemption = _exemption(
        exemption_id="e.far",
        created_at="2026-08-01T00:00:00Z",
        expires_at="2027-08-01T00:00:00Z",
    )
    decisions = plan_exemption_lifecycle((exemption,), now=_NOW, alert_lead=timedelta(days=14))
    assert decisions == ()


def test_within_alert_lead_window_alerts() -> None:
    exemption = _exemption(
        exemption_id="e.soon",
        created_at="2026-08-01T00:00:00Z",
        expires_at="2026-08-25T00:00:00Z",  # 5 days from _NOW
    )
    decisions = plan_exemption_lifecycle((exemption,), now=_NOW, alert_lead=timedelta(days=14))
    assert len(decisions) == 1
    assert decisions[0].action is ExemptionLifecycleAction.ALERT_AHEAD_OF_EXPIRY
    assert decisions[0].exemption_id == "e.soon"


def test_exactly_at_alert_lead_boundary_alerts() -> None:
    exemption = _exemption(
        exemption_id="e.boundary",
        created_at="2026-08-01T00:00:00Z",
        expires_at="2026-09-03T00:00:00Z",  # exactly 14 days from _NOW
    )
    decisions = plan_exemption_lifecycle((exemption,), now=_NOW, alert_lead=timedelta(days=14))
    assert len(decisions) == 1
    assert decisions[0].action is ExemptionLifecycleAction.ALERT_AHEAD_OF_EXPIRY


def test_past_expiry_expires() -> None:
    exemption = _exemption(
        exemption_id="e.past",
        created_at="2026-07-01T00:00:00Z",
        expires_at="2026-08-19T00:00:00Z",  # one day before _NOW
    )
    decisions = plan_exemption_lifecycle((exemption,), now=_NOW, alert_lead=timedelta(days=14))
    assert len(decisions) == 1
    assert decisions[0].action is ExemptionLifecycleAction.EXPIRE


def test_expiring_exactly_now_expires() -> None:
    exemption = _exemption(
        exemption_id="e.now",
        created_at="2026-07-01T00:00:00Z",
        expires_at=_NOW.isoformat(),
    )
    decisions = plan_exemption_lifecycle((exemption,), now=_NOW, alert_lead=timedelta(days=14))
    assert decisions[0].action is ExemptionLifecycleAction.EXPIRE


def test_non_active_states_are_skipped() -> None:
    exemption = _exemption(
        exemption_id="e.revoked",
        created_at="2026-07-01T00:00:00Z",
        expires_at="2026-08-19T00:00:00Z",
        state="revoked",
    )
    decisions = plan_exemption_lifecycle((exemption,), now=_NOW, alert_lead=timedelta(days=14))
    assert decisions == ()


def test_decisions_are_ordered_by_exemption_id() -> None:
    later = _exemption(
        exemption_id="e.z",
        created_at="2026-08-01T00:00:00Z",
        expires_at="2026-08-25T00:00:00Z",
    )
    earlier = _exemption(
        exemption_id="e.a",
        created_at="2026-08-01T00:00:00Z",
        expires_at="2026-08-19T00:00:00Z",
    )
    decisions = plan_exemption_lifecycle((later, earlier), now=_NOW, alert_lead=timedelta(days=14))
    assert [d.exemption_id for d in decisions] == ["e.a", "e.z"]


def test_naive_clock_is_rejected() -> None:
    exemption = _exemption(
        exemption_id="e.a",
        created_at="2026-08-01T00:00:00Z",
        expires_at="2026-08-25T00:00:00Z",
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        plan_exemption_lifecycle(
            (exemption,), now=datetime(2026, 8, 20), alert_lead=timedelta(days=14)
        )


@pytest.mark.parametrize("lead", [timedelta(0), timedelta(days=-1)])
def test_non_positive_alert_lead_is_rejected(lead: timedelta) -> None:
    exemption = _exemption(
        exemption_id="e.a",
        created_at="2026-08-01T00:00:00Z",
        expires_at="2026-08-25T00:00:00Z",
    )
    with pytest.raises(ValueError, match="alert_lead MUST be positive"):
        plan_exemption_lifecycle((exemption,), now=_NOW, alert_lead=lead)
