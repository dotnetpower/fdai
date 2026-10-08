"""Tests for binding returned remediation results to the exported pack."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.security.code_findings.result_import import (
    ClaimStatus,
    NextStep,
    PackRecord,
    RemediationResultRejectedError,
    import_remediation_result,
)

_NOW = datetime(2026, 10, 8, tzinfo=UTC)
_ISSUE = "FDAI-SEC-0123456789ab"
_OTHER = "FDAI-SEC-ba9876543210"
_RECORD = PackRecord(
    pack_id="abcdef012345",
    manifest_sha256="f" * 64,
    base_commit="a" * 40,
    issue_ids=frozenset({_ISSUE, _OTHER}),
    expires_at=_NOW + timedelta(days=7),
)


def _result(**overrides: object) -> bytes:
    document: dict[str, object] = {
        "schema_version": 1,
        "pack_id": "abcdef012345",
        "manifest_sha256": "f" * 64,
        "base_commit": "a" * 40,
        "final_head": "c" * 40,
        "issues": [
            {
                "issue_id": _ISSUE,
                "status": "fixed_claimed",
                "validation": "tests_passed",
                "commits": ["c" * 40],
            },
            {
                "issue_id": _OTHER,
                "status": "claimed_false_positive",
                "evidence": "guarded\u202e by caller",
            },
        ],
    }
    document.update(overrides)
    return json.dumps(document).encode()


def test_valid_result_becomes_claims_that_need_rescan_or_adjudication() -> None:
    imported = import_remediation_result(_result(), _RECORD, _NOW)
    fixed, false_positive = imported.claims
    assert fixed.status is ClaimStatus.FIXED_CLAIMED
    assert fixed.next_step is NextStep.RESCAN_REQUIRED
    assert false_positive.next_step is NextStep.ADJUDICATION_REQUIRED
    assert "\u202e" not in false_positive.evidence
    assert all(claim.status.value != "fixed_verified" for claim in imported.claims)


@pytest.mark.parametrize(
    ("overrides", "record", "reason"),
    [
        ({"pack_id": "000000000000"}, _RECORD, "unknown_pack"),
        ({"manifest_sha256": "e" * 64}, _RECORD, "manifest_digest_mismatch"),
        ({"base_commit": "b" * 40}, _RECORD, "base_commit_mismatch"),
        ({"final_head": "HEAD"}, _RECORD, "invalid_final_head"),
        ({}, None, "pack_revoked"),
        (
            {"issues": [{"issue_id": "FDAI-SEC-ffffffffffff", "status": "deferred"}]},
            _RECORD,
            "issue_not_in_pack",
        ),
        (
            {"issues": [{"issue_id": _ISSUE, "status": "fixed_verified", "commits": ["c" * 40]}]},
            _RECORD,
            "invalid_status",
        ),
        (
            {"issues": [{"issue_id": _ISSUE, "status": "fixed_claimed", "commits": []}]},
            _RECORD,
            "claim_without_commit",
        ),
        (
            {"issues": [{"issue_id": _ISSUE, "status": "fixed_claimed", "commits": ["main"]}]},
            _RECORD,
            "invalid_commit",
        ),
        (
            {
                "issues": [
                    {"issue_id": _ISSUE, "status": "deferred"},
                    {"issue_id": _ISSUE, "status": "deferred"},
                ]
            },
            _RECORD,
            "duplicate_issue",
        ),
        ({"schema_version": 2}, _RECORD, "unsupported_schema"),
    ],
)
def test_rejections_have_stable_reasons(
    overrides: dict[str, object], record: PackRecord | None, reason: str
) -> None:
    # ``None`` stands for a revoked copy of the default record.
    if record is None:
        record = PackRecord(
            pack_id=_RECORD.pack_id,
            manifest_sha256=_RECORD.manifest_sha256,
            base_commit=_RECORD.base_commit,
            issue_ids=_RECORD.issue_ids,
            expires_at=_RECORD.expires_at,
            revoked=True,
        )
    with pytest.raises(RemediationResultRejectedError) as caught:
        import_remediation_result(_result(**overrides), record, _NOW)
    assert caught.value.reason == reason


def test_expired_oversize_and_malformed_results_are_rejected() -> None:
    with pytest.raises(RemediationResultRejectedError, match="pack_expired"):
        import_remediation_result(_result(), _RECORD, _NOW + timedelta(days=30))
    with pytest.raises(RemediationResultRejectedError, match="result_too_large"):
        import_remediation_result(b" " * 1_000_001, _RECORD, _NOW)
    with pytest.raises(RemediationResultRejectedError, match="malformed_result"):
        import_remediation_result(b"{not json", _RECORD, _NOW)
