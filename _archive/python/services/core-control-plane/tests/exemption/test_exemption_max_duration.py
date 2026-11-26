"""Configured maximum exemption duration (rule-governance.md "Exemptions")."""

from __future__ import annotations

from datetime import timedelta

from fdai.rule_catalog.schema.exemption import (
    exemption_duration_issue,
    exemption_duration_issues,
    load_exemption_from_mapping,
)


def _valid_raw(
    *, created_at: str = "2026-07-05T00:00:00Z", expires_at: str = "2026-08-05T00:00:00Z"
) -> dict[str, object]:
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
        "created_at": created_at,
        "expires_at": expires_at,
    }


def test_duration_within_bound_has_no_issue() -> None:
    exemption = load_exemption_from_mapping(_valid_raw())
    issue = exemption_duration_issue(exemption, max_duration=timedelta(days=180))
    assert issue is None


def test_duration_exactly_at_bound_has_no_issue() -> None:
    # 2026-07-05 -> 2026-08-05 is exactly 31 days.
    exemption = load_exemption_from_mapping(_valid_raw())
    issue = exemption_duration_issue(exemption, max_duration=timedelta(days=31))
    assert issue is None


def test_duration_exceeding_bound_is_reported() -> None:
    exemption = load_exemption_from_mapping(_valid_raw())
    issue = exemption_duration_issue(exemption, max_duration=timedelta(days=10))
    assert issue is not None
    assert issue.key == f"{exemption.id}:expires_at"
    assert "exceeds the configured maximum" in issue.message


def test_exemption_duration_issues_aggregates_across_exemptions() -> None:
    within_bound = load_exemption_from_mapping(_valid_raw())
    over_bound = load_exemption_from_mapping(
        _valid_raw(created_at="2026-07-05T00:00:00Z", expires_at="2027-07-05T00:00:00Z")
    )
    issues = exemption_duration_issues((within_bound, over_bound), max_duration=timedelta(days=180))
    assert len(issues) == 1
    assert issues[0].key == f"{over_bound.id}:expires_at"
