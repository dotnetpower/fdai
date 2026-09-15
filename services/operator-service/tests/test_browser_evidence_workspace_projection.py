from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai_operator_service.browser_evidence_workspace_projection import (
    browser_evidence_workspace_projection,
)

_NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)
_ARTIFACT = f"sha256:{'a' * 64}"


def test_workspace_projection_exposes_reconciled_payload_free_metadata() -> None:
    payload = browser_evidence_workspace_projection(
        [_row()],
        limit=25,
        next_cursor=None,
    )

    assert payload["schema_version"] == "2.0.0"
    assert payload["consistency"] == "drift_aware"
    assert payload["loaded_count"] == 1
    assert payload["snapshot_total_count"] == 2
    assert payload["snapshot_admitted_count"] == 1
    assert payload["snapshot_withheld_count"] == 1
    assert payload["withheld_reasons"] == {
        "invalid_metadata": 1,
        "trust_invalid": 0,
        "isolation_unverified": 0,
    }
    items = payload["items"]
    assert isinstance(items, list)
    item = items[0]
    assert isinstance(item, dict)
    assert item["artifact_id"] == _ARTIFACT
    assert item["digest_presence"] == {
        "screenshot": True,
        "text": True,
        "accessibility_snapshot": False,
    }
    assert item["audit"] == {
        "state": "exact",
        "sequence": "42",
        "correlation_id": "correlation-1",
    }
    serialized = repr(payload)
    for forbidden in (
        "canonical_source_url",
        "screenshot_hash",
        "visible_text",
        "aria_snapshot",
        "prompt_injection_findings",
    ):
        assert forbidden not in serialized
    assert "isolation" not in item


def test_workspace_projection_distinguishes_empty_page_from_empty_snapshot() -> None:
    payload = browser_evidence_workspace_projection(
        [_summary_row()],
        limit=25,
        next_cursor=None,
    )

    assert payload["items"] == []
    assert payload["loaded_count"] == 0
    assert payload["matching_admitted_count"] == 0
    assert payload["snapshot_admitted_count"] == 1


def test_workspace_projection_requires_cursor_only_for_an_additional_row() -> None:
    first = _row(
        artifact_id=f"sha256:{'a' * 64}",
        matching_admitted_count=2,
        retained_count=2,
        legal_hold_count=0,
        snapshot_total_count=2,
        snapshot_admitted_count=2,
        snapshot_withheld_count=0,
        withheld_invalid_metadata_count=0,
        legal_hold=False,
        legal_hold_ref=None,
        legal_hold_at=None,
        retention_state="retained",
    )
    second = {
        **first,
        "artifact_id": f"sha256:{'b' * 64}",
        "captured_at": _NOW - timedelta(minutes=1),
    }

    payload = browser_evidence_workspace_projection(
        [first, second],
        limit=1,
        next_cursor="cursor",
    )

    assert payload["loaded_count"] == 1
    assert payload["has_more"] is True
    assert payload["next_cursor"] == "cursor"
    with pytest.raises(ValueError, match="cursor presence"):
        browser_evidence_workspace_projection(
            [first, second],
            limit=1,
            next_cursor=None,
        )


def test_workspace_projection_rejects_summary_and_retention_inconsistency() -> None:
    malformed = _row(snapshot_total_count=3)
    with pytest.raises(ValueError, match="snapshot counts"):
        browser_evidence_workspace_projection(
            [malformed],
            limit=25,
            next_cursor=None,
        )

    malformed_retention = _row(retention_state="retained")
    with pytest.raises(ValueError, match="retention state"):
        browser_evidence_workspace_projection(
            [malformed_retention],
            limit=25,
            next_cursor=None,
        )


def test_workspace_projection_rejects_nonexact_audit_identity_and_duplicates() -> None:
    nonexact = _row(audit_link_state="ambiguous")
    with pytest.raises(ValueError, match="non-exact audit"):
        browser_evidence_workspace_projection(
            [nonexact],
            limit=25,
            next_cursor=None,
        )

    duplicate_summary = _row(
        matching_admitted_count=2,
        legal_hold_count=2,
        snapshot_total_count=2,
        snapshot_admitted_count=2,
        snapshot_withheld_count=0,
        withheld_invalid_metadata_count=0,
    )
    with pytest.raises(ValueError, match="duplicate artifacts"):
        browser_evidence_workspace_projection(
            [duplicate_summary, duplicate_summary],
            limit=25,
            next_cursor=None,
        )


def test_workspace_projection_rejects_future_source_and_unsafe_audit_sequence() -> None:
    with pytest.raises(ValueError, match="in the future"):
        browser_evidence_workspace_projection(
            [_row(source_observed_at=_NOW + timedelta(seconds=1))],
            limit=25,
            next_cursor=None,
        )
    with pytest.raises(ValueError, match="exceeds Console range"):
        browser_evidence_workspace_projection(
            [_row(audit_sequence="9007199254740992")],
            limit=25,
            next_cursor=None,
        )


def _summary_row(**overrides: object) -> dict[str, object]:
    return {
        "observed_at": _NOW,
        "source_observed_at": _NOW - timedelta(minutes=1),
        "snapshot_total_count": 2,
        "snapshot_admitted_count": 1,
        "snapshot_withheld_count": 1,
        "withheld_invalid_metadata_count": 1,
        "withheld_trust_invalid_count": 0,
        "withheld_isolation_unverified_count": 0,
        "matching_admitted_count": 0,
        "security_finding_count": 0,
        "legal_hold_count": 0,
        "expiring_count": 0,
        "expired_pending_purge_count": 0,
        "retained_count": 0,
        "artifact_id": None,
        **overrides,
    }


def _row(**overrides: object) -> dict[str, object]:
    return {
        **_summary_row(
            matching_admitted_count=1,
            security_finding_count=1,
            legal_hold_count=1,
        ),
        "artifact_id": _ARTIFACT,
        "policy_id": "dashboard",
        "policy_version": 4,
        "source_host": "dashboard.example",
        "final_host": "status.example",
        "captured_at": _NOW - timedelta(days=1),
        "expires_at": _NOW + timedelta(days=30),
        "selector_count": 18,
        "has_screenshot_digest": True,
        "has_text_digest": True,
        "has_snapshot_digest": False,
        "redaction_count": 7,
        "browser_version": "chromium-test",
        "chain_of_custody_audit_ref": "00000000-0000-0000-0000-000000000000",
        "prompt_injection_finding_count": 1,
        "legal_hold": True,
        "legal_hold_ref": "case:example",
        "legal_hold_at": _NOW - timedelta(hours=1),
        "retention_state": "held",
        "attention_rank": 0,
        "audit_link_state": "exact",
        "audit_sequence": "42",
        "audit_correlation_id": "correlation-1",
        **overrides,
    }
