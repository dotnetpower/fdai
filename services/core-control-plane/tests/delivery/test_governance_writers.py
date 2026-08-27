"""PR-native governance writers stay inert until an approved, distinct-approver merge."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.gitops_pr.governance_writers import (
    GovernanceWriterError,
    RetirementMode,
    render_exemption_grant,
    render_rule_retirement,
)

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
REQUESTER = "00000000-0000-0000-0000-000000000001"
APPROVER = "00000000-0000-0000-0000-000000000002"
SUBSCRIPTION = "00000000-0000-0000-0000-000000000003"
JUSTIFICATION = "The upstream control is superseded by a narrower authored rule."


def _retirement(**overrides: object) -> object:
    values: dict[str, object] = {
        "rule_id": "azure-builtin.storage.secure-transfer",
        "mode": RetirementMode.SHADOW_ONLY,
        "justification": JUSTIFICATION,
        "requested_by": REQUESTER,
        "approved_by": APPROVER,
        "decided_at": NOW,
    }
    values.update(overrides)
    return render_rule_retirement(**values)  # type: ignore[arg-type]


def _exemption(**overrides: object) -> object:
    values: dict[str, object] = {
        "exemption_id": "exemption-4711",
        "rule_id": "azure-builtin.storage.secure-transfer",
        "subscription_id": SUBSCRIPTION,
        "justification": JUSTIFICATION,
        "requested_by": REQUESTER,
        "approved_by": APPROVER,
        "created_at": NOW,
        "expires_at": NOW + timedelta(days=7),
        "resource_group": "rg-workload",
    }
    values.update(overrides)
    return render_exemption_grant(**values)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Shadow-only rendering
# ---------------------------------------------------------------------------


def test_rendering_carries_no_authority() -> None:
    for document in (_retirement(), _exemption()):
        assert document.execution_path == "pr_native"  # type: ignore[attr-defined]
        assert document.applied is False  # type: ignore[attr-defined]


def test_retirement_renders_the_reviewed_record() -> None:
    document = _retirement()

    assert document.path == (  # type: ignore[attr-defined]
        "rule-catalog/retirements/azure-builtin.storage.secure-transfer.yaml"
    )
    assert document.document["mode"] == "shadow_only"  # type: ignore[attr-defined]
    assert document.document["decided_at"] == "2026-08-15T12:00:00Z"  # type: ignore[attr-defined]


def test_exemption_renders_the_time_boxed_record() -> None:
    document = _exemption()

    assert document.path == "rule-catalog/exemptions/exemption-4711.json"  # type: ignore[attr-defined]
    payload = document.document  # type: ignore[attr-defined]
    assert payload["state"] == "active"
    assert payload["scope"] == {
        "subscription_id": SUBSCRIPTION,
        "resource_group": "rg-workload",
    }
    assert payload["expires_at"] == "2026-08-22T12:00:00Z"


# ---------------------------------------------------------------------------
# No self-approval
# ---------------------------------------------------------------------------


def test_self_approval_is_rejected() -> None:
    with pytest.raises(GovernanceWriterError, match="differ from requested_by"):
        _retirement(approved_by=REQUESTER)
    with pytest.raises(GovernanceWriterError, match="differ from requested_by"):
        _exemption(approved_by=REQUESTER)


def test_principals_must_be_entra_oids() -> None:
    with pytest.raises(GovernanceWriterError, match="requested_by"):
        _retirement(requested_by="operator@example.com")
    with pytest.raises(GovernanceWriterError, match="approved_by"):
        _exemption(approved_by="owner")


# ---------------------------------------------------------------------------
# Bounded inputs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rule_id", ["Bad-Id", "a", "", "x" * 200])
def test_rule_ids_are_bounded(rule_id: str) -> None:
    with pytest.raises(GovernanceWriterError, match="rule_id"):
        _retirement(rule_id=rule_id)


@pytest.mark.parametrize("justification", ["too short", "x" * 501])
def test_justification_is_bounded(justification: str) -> None:
    with pytest.raises(GovernanceWriterError, match="justification"):
        _retirement(justification=justification)


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(GovernanceWriterError, match="decided_at"):
        _retirement(decided_at=NOW.replace(tzinfo=None))
    with pytest.raises(GovernanceWriterError, match="expires_at"):
        _exemption(expires_at=(NOW + timedelta(days=1)).replace(tzinfo=None))


# ---------------------------------------------------------------------------
# Exemption scope
# ---------------------------------------------------------------------------


def test_a_subscription_wide_exemption_is_rejected() -> None:
    with pytest.raises(GovernanceWriterError, match="rule retirement, not an exemption"):
        _exemption(resource_group=None, resource_ref=None)


def test_a_resource_scope_is_accepted() -> None:
    document = _exemption(resource_group=None, resource_ref="/resource/one")

    assert document.document["scope"]["resource_ref"] == "/resource/one"  # type: ignore[attr-defined]


def test_an_exemption_must_expire_after_it_is_created() -> None:
    with pytest.raises(GovernanceWriterError, match="after created_at"):
        _exemption(expires_at=NOW)


def test_the_subscription_must_be_a_uuid() -> None:
    with pytest.raises(GovernanceWriterError, match="subscription_id"):
        _exemption(subscription_id="not-a-uuid")
