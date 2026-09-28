"""Assurance Twin posture/review projection tests.

The Operator Service does not compute the twin's verdict, severity, or
freshness - it only shapes rows the twin already wrote. Every test below
asks whether unusable evidence produces an explicit gap rather than a
fabricated clear result.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fdai_operator_service.assurance_twin_posture_projection import (
    GAP_CONFLICT,
    GAP_DIGEST_MISMATCH,
    GAP_MALFORMED,
    GAP_NOT_FRESH,
    GAP_TRUNCATED,
    POSTURE_STATE_KEY_PREFIX,
    assurance_twin_posture_projection,
    assurance_twin_review_detail_projection,
    assurance_twin_review_list_projection,
)

_PROVENANCE_FIELDS = (
    "activity_id",
    "correlation_id",
    "evidence_digest",
    "evidence_source_revision",
    "source_confirmed",
    "conflict",
)
_REVISION = "sha256:0000000000000000000000000000000000000000000000000000000000000001"
_REVIEW_STATE_KEY_PREFIX = "runtime:assurance-twin-review:"

_POSTURE_BODY: dict[str, Any] = {
    "scope": "sub/00000000-0000-0000-0000-000000000001",
    "generated_at": "2026-07-07T00:00:00Z",
    "mode": "shadow",
    "verdict": "blocked",
    "blocks_action": False,
    "resource_count": 1,
    "rule_count": 1,
    "highest_severity": "high",
    "severity_counts": {"low": 0, "medium": 0, "high": 1, "critical": 0},
    "findings": [
        {
            "rule_id": "r-1",
            "resource_type": "compute.vm",
            "resource_ref": "vm-a",
            "severity": "high",
            "reason": "reason",
            "evidence_refs": [],
        }
    ],
    "freshness": "fresh",
    "reason_codes": [],
}

_REVIEW_BODY: dict[str, Any] = {
    "pr_ref": "owner/repo#1",
    "review_key": "Review_Key-1",
    "verdict": "needs_review",
    "mode": "shadow",
    "generated_at": "2026-07-07T00:00:00Z",
    "freshness": "fresh",
    "reason_codes": [],
    "metadata": {},
    "findings": [
        {
            "rule_id": "r-1",
            "resource_type": "compute.vm",
            "resource_ref": "vm-a",
            "severity": "high",
            "reason": "reason",
            "evidence_refs": [],
        }
    ],
}


def _digest(body: dict[str, Any]) -> str:
    material = {key: value for key, value in body.items() if key not in _PROVENANCE_FIELDS}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _row(body: dict[str, Any], **provenance: Any) -> dict[str, Any]:
    """Build one durable row with verifying provenance unless overridden."""

    value = {
        **body,
        "activity_id": "assurance-twin.posture-report:correlation-1:completed",
        "correlation_id": "correlation-1",
        "evidence_digest": _digest(body),
        "evidence_source_revision": _REVISION,
    }
    value.update(provenance)
    if "scope" in body:
        key = f"{POSTURE_STATE_KEY_PREFIX}{body['scope']}"
    else:
        key = f"{_REVIEW_STATE_KEY_PREFIX}{body['review_key']}"
    return {"key": key, "value": value}


def test_posture_projection_is_unavailable_when_no_rows_exist() -> None:
    projection = assurance_twin_posture_projection(())
    assert projection["available"] is False
    assert projection["complete"] is True
    assert projection["reports"] == []
    assert projection["gaps"] == []


def test_posture_projection_renders_a_recorded_report_verbatim() -> None:
    projection = assurance_twin_posture_projection((_row(_POSTURE_BODY),))
    assert projection["available"] is True
    assert projection["complete"] is True
    reports = projection["reports"]
    assert isinstance(reports, list)
    report = reports[0]
    assert report["verdict"] == "blocked"
    assert report["finding_count"] == 1
    assert report["severity_counts"] == {"low": 0, "medium": 0, "high": 1, "critical": 0}
    assert report["freshness"] == "fresh"


def test_posture_projection_exposes_replay_provenance() -> None:
    projection = assurance_twin_posture_projection((_row(_POSTURE_BODY),))
    reports = projection["reports"]
    assert isinstance(reports, list)
    report = reports[0]
    assert report["activity_id"] == "assurance-twin.posture-report:correlation-1:completed"
    assert report["correlation_id"] == "correlation-1"
    assert report["evidence_digest"] == _digest(_POSTURE_BODY)
    assert report["evidence_source_revision"] == _REVISION


def test_posture_projection_reports_a_gap_for_an_invalid_verdict() -> None:
    malformed = {**_POSTURE_BODY, "verdict": "not-a-real-verdict"}
    projection = assurance_twin_posture_projection((_row(malformed),))
    assert projection["available"] is False
    assert projection["complete"] is False
    assert projection["reports"] == []
    gaps = projection["gaps"]
    assert isinstance(gaps, list)
    assert gaps[0]["reason_code"] == GAP_MALFORMED


def test_posture_projection_reports_a_gap_for_incomplete_severity_counts() -> None:
    malformed = {**_POSTURE_BODY, "severity_counts": {"low": 0}}
    projection = assurance_twin_posture_projection((_row(malformed),))
    assert projection["available"] is False
    gaps = projection["gaps"]
    assert isinstance(gaps, list)
    assert gaps[0]["reason_code"] == GAP_MALFORMED


def test_posture_projection_rejects_boolean_counts() -> None:
    for field in ("resource_count", "rule_count"):
        malformed = {**_POSTURE_BODY, field: True}
        projection = assurance_twin_posture_projection((_row(malformed),))

        assert projection["available"] is False, field
        gaps = projection["gaps"]
        assert isinstance(gaps, list)
        assert gaps[0]["reason_code"] == GAP_MALFORMED


def test_posture_projection_rejects_a_whitespace_only_scope() -> None:
    malformed = {**_POSTURE_BODY, "scope": "   "}

    projection = assurance_twin_posture_projection((_row(malformed),))

    assert projection["available"] is False
    gaps = projection["gaps"]
    assert isinstance(gaps, list)
    assert gaps[0]["reason_code"] == GAP_MALFORMED


def test_posture_projection_never_renders_stale_evidence_as_usable() -> None:
    stale = {
        **_POSTURE_BODY,
        "freshness": "stale",
        "reason_codes": ["inventory_freshness_ttl_exceeded"],
    }
    projection = assurance_twin_posture_projection((_row(stale),))
    assert projection["available"] is False
    assert projection["complete"] is False
    assert projection["reports"] == []
    gaps = projection["gaps"]
    assert isinstance(gaps, list)
    assert gaps[0]["reason_code"] == GAP_NOT_FRESH
    assert gaps[0]["freshness"] == "stale"
    assert gaps[0]["reason_codes"] == ["inventory_freshness_ttl_exceeded"]


def test_posture_projection_never_renders_unavailable_or_unknown_evidence() -> None:
    for freshness in ("unavailable", "unknown"):
        body = {**_POSTURE_BODY, "freshness": freshness}
        projection = assurance_twin_posture_projection((_row(body),))
        assert projection["available"] is False, freshness
        gaps = projection["gaps"]
        assert isinstance(gaps, list)
        assert gaps[0]["reason_code"] == GAP_NOT_FRESH


def test_posture_projection_rejects_a_row_whose_digest_does_not_verify() -> None:
    tampered = _row(_POSTURE_BODY)
    tampered["value"]["verdict"] = "clear"
    projection = assurance_twin_posture_projection((tampered,))
    assert projection["available"] is False
    gaps = projection["gaps"]
    assert isinstance(gaps, list)
    assert gaps[0]["reason_code"] == GAP_DIGEST_MISMATCH


def test_posture_projection_keeps_unconfirmed_source_unavailable() -> None:
    projection = assurance_twin_posture_projection((_row(_POSTURE_BODY, source_confirmed=False),))
    assert projection["available"] is False
    gaps = projection["gaps"]
    assert isinstance(gaps, list)
    assert gaps[0]["reason_code"] == GAP_NOT_FRESH


def test_posture_projection_rejects_a_row_without_provenance() -> None:
    projection = assurance_twin_posture_projection(({"value": dict(_POSTURE_BODY)},))
    assert projection["available"] is False
    gaps = projection["gaps"]
    assert isinstance(gaps, list)
    assert gaps[0]["reason_code"] == GAP_MALFORMED


def test_posture_projection_withholds_conflicting_rows_for_one_identity() -> None:
    other = {**_POSTURE_BODY, "verdict": "clear", "highest_severity": None}
    projection = assurance_twin_posture_projection((_row(_POSTURE_BODY), _row(other)))
    assert projection["available"] is False
    assert projection["reports"] == []
    gaps = projection["gaps"]
    assert isinstance(gaps, list)
    assert gaps[0]["reason_code"] == GAP_CONFLICT
    assert gaps[0]["identity"] == _POSTURE_BODY["scope"]


def test_posture_projection_rejects_a_mismatched_durable_key() -> None:
    row = _row(_POSTURE_BODY)
    row["key"] = f"{POSTURE_STATE_KEY_PREFIX}different-scope"

    projection = assurance_twin_posture_projection((row,))

    assert projection["available"] is False
    assert projection["reports"] == []
    gaps = projection["gaps"]
    assert isinstance(gaps, list)
    assert gaps[0]["identity"] is None
    assert gaps[0]["reason_code"] == GAP_MALFORMED


def test_posture_projection_withholds_duplicate_rows_for_one_identity() -> None:
    row = _row(_POSTURE_BODY)

    projection = assurance_twin_posture_projection((row, row))

    assert projection["available"] is False
    assert projection["reports"] == []
    gaps = projection["gaps"]
    assert isinstance(gaps, list)
    assert gaps[0]["identity"] == _POSTURE_BODY["scope"]
    assert gaps[0]["reason_code"] == GAP_CONFLICT


def test_posture_projection_rejects_a_missing_blocks_action_flag() -> None:
    body = {key: value for key, value in _POSTURE_BODY.items() if key != "blocks_action"}
    projection = assurance_twin_posture_projection((_row(body),))
    assert projection["available"] is False
    assert projection["reports"] == []
    gaps = projection["gaps"]
    assert isinstance(gaps, list)
    assert gaps[0]["reason_code"] == GAP_MALFORMED


def test_posture_projection_never_coerces_a_string_blocks_action_flag() -> None:
    # A truthy string MUST NOT silently become a blocking posture, and
    # "false" MUST NOT silently become non-blocking.
    for value in ("true", "false", 1, None):
        projection = assurance_twin_posture_projection(
            (_row({**_POSTURE_BODY, "blocks_action": value}),)
        )
        assert projection["available"] is False
        gaps = projection["gaps"]
        assert isinstance(gaps, list)
        assert gaps[0]["reason_code"] == GAP_MALFORMED


def test_posture_projection_renders_a_blocking_report_exactly() -> None:
    projection = assurance_twin_posture_projection(
        (_row({**_POSTURE_BODY, "blocks_action": True}),)
    )
    reports = projection["reports"]
    assert isinstance(reports, list)
    assert reports[0]["blocks_action"] is True


def test_review_list_projection_withholds_a_tombstoned_row() -> None:
    row = _row(_REVIEW_BODY)
    row["value"]["conflict"] = {
        "reason_code": "assurance_twin_review_key_conflict",
        "stored_evidence_digest": _digest(_REVIEW_BODY),
        "rejected_evidence_digest": _digest({**_REVIEW_BODY, "verdict": "blocked"}),
    }
    projection = assurance_twin_review_list_projection((row,))
    assert projection["available"] is False
    assert projection["reviews"] == []
    gaps = projection["gaps"]
    assert isinstance(gaps, list)
    assert gaps[0]["reason_code"] == GAP_CONFLICT
    assert gaps[0]["identity"] == "Review_Key-1"


def test_review_detail_projection_is_unavailable_for_a_tombstoned_row() -> None:
    row = _row(_REVIEW_BODY)
    row["value"]["conflict"] = {
        "reason_code": "assurance_twin_review_key_conflict",
        "stored_evidence_digest": _digest(_REVIEW_BODY),
        "rejected_evidence_digest": _digest({**_REVIEW_BODY, "verdict": "blocked"}),
    }
    detail = assurance_twin_review_detail_projection(row, requested_review_key="Review_Key-1")
    assert detail is not None
    assert detail["available"] is False
    assert detail["review"] is None
    gap = detail["gap"]
    assert isinstance(gap, dict)
    assert gap["reason_code"] == GAP_CONFLICT


def test_posture_projection_withholds_a_tombstoned_row_too() -> None:
    row = _row(_POSTURE_BODY)
    row["value"]["conflict"] = {"reason_code": "assurance_twin_review_key_conflict"}
    projection = assurance_twin_posture_projection((row,))
    assert projection["available"] is False
    gaps = projection["gaps"]
    assert isinstance(gaps, list)
    assert gaps[0]["reason_code"] == GAP_CONFLICT


def test_posture_projection_sorts_multiple_reports_newest_first() -> None:
    older = {**_POSTURE_BODY, "scope": "sub/a", "generated_at": "2026-01-01T00:00:00Z"}
    newer = {**_POSTURE_BODY, "scope": "sub/b", "generated_at": "2026-06-01T00:00:00Z"}
    projection = assurance_twin_posture_projection((_row(older), _row(newer)))
    reports = projection["reports"]
    assert isinstance(reports, list)
    assert [report["scope"] for report in reports] == ["sub/b", "sub/a"]


def test_review_list_projection_is_unavailable_when_no_rows_exist() -> None:
    projection = assurance_twin_review_list_projection(())
    assert projection["available"] is False
    assert projection["complete"] is True
    assert projection["reviews"] == []


def test_review_list_projection_renders_a_recorded_review_summary() -> None:
    projection = assurance_twin_review_list_projection((_row(_REVIEW_BODY),))
    assert projection["available"] is True
    reviews = projection["reviews"]
    assert isinstance(reviews, list)
    review = reviews[0]
    assert review["review_key"] == "Review_Key-1"
    assert review["finding_count"] == 1
    assert "findings" not in review
    assert review["evidence_digest"] == _digest(_REVIEW_BODY)


def test_review_list_projection_never_coerces_malformed_findings_to_zero() -> None:
    malformed = {**_REVIEW_BODY, "findings": "not-a-list"}
    projection = assurance_twin_review_list_projection((_row(malformed),))
    assert projection["available"] is False
    assert projection["reviews"] == []
    gaps = projection["gaps"]
    assert isinstance(gaps, list)
    assert gaps[0]["reason_code"] == GAP_MALFORMED
    assert gaps[0]["identity"] == "Review_Key-1"


def test_review_detail_projection_is_none_when_row_is_absent() -> None:
    assert assurance_twin_review_detail_projection(None, requested_review_key="k-1") is None


def test_review_detail_projection_includes_finding_evidence() -> None:
    detail = assurance_twin_review_detail_projection(
        _row(_REVIEW_BODY), requested_review_key="Review_Key-1"
    )
    assert detail is not None
    assert detail["available"] is True
    review = detail["review"]
    assert isinstance(review, dict)
    assert review["review_key"] == "Review_Key-1"
    findings = review["findings"]
    assert isinstance(findings, list)
    assert findings[0]["rule_id"] == "r-1"


def test_review_detail_projection_is_explicitly_unavailable_for_malformed_findings() -> None:
    malformed = {**_REVIEW_BODY, "findings": "not-a-list"}
    detail = assurance_twin_review_detail_projection(
        _row(malformed), requested_review_key="Review_Key-1"
    )
    assert detail is not None
    assert detail["available"] is False
    assert detail["review"] is None
    gap = detail["gap"]
    assert isinstance(gap, dict)
    assert gap["reason_code"] == GAP_MALFORMED


def test_review_detail_projection_is_explicitly_unavailable_when_not_fresh() -> None:
    stale = {**_REVIEW_BODY, "freshness": "unavailable", "reason_codes": ["provider_error"]}
    detail = assurance_twin_review_detail_projection(
        _row(stale), requested_review_key="Review_Key-1"
    )
    assert detail is not None
    assert detail["available"] is False
    gap = detail["gap"]
    assert isinstance(gap, dict)
    assert gap["reason_code"] == GAP_NOT_FRESH
    assert gap["reason_codes"] == ["provider_error"]


def test_review_detail_projection_rejects_a_tampered_body() -> None:
    tampered = _row(_REVIEW_BODY)
    tampered["value"]["verdict"] = "clear"
    detail = assurance_twin_review_detail_projection(tampered, requested_review_key="Review_Key-1")
    assert detail is not None
    assert detail["available"] is False
    gap = detail["gap"]
    assert isinstance(gap, dict)
    assert gap["reason_code"] == GAP_DIGEST_MISMATCH


def test_posture_projection_reports_a_gap_when_the_page_does_not_cover_the_prefix() -> None:
    rows = tuple(_row({**_POSTURE_BODY, "scope": f"sub/{index}"}) for index in range(201))
    projection = assurance_twin_posture_projection(rows)
    reports = projection["reports"]
    gaps = projection["gaps"]
    assert isinstance(reports, list)
    assert isinstance(gaps, list)
    assert len(reports) == 200
    assert projection["complete"] is False
    assert gaps[0]["reason_code"] == GAP_TRUNCATED


def test_review_list_projection_reports_a_truncation_gap_too() -> None:
    rows = tuple(_row({**_REVIEW_BODY, "review_key": f"k-{index}"}) for index in range(201))
    projection = assurance_twin_review_list_projection(rows)
    assert projection["complete"] is False
    gaps = projection["gaps"]
    assert isinstance(gaps, list)
    assert gaps[0]["reason_code"] == GAP_TRUNCATED


def test_posture_projection_rejects_whitespace_only_provenance_fields() -> None:
    # A falsy-only check (``not value``) would let a whitespace-only string
    # through; each provenance field MUST be rejected as malformed instead.
    for field in ("activity_id", "correlation_id", "evidence_source_revision"):
        row = _row(_POSTURE_BODY)
        row["value"][field] = "   "
        projection = assurance_twin_posture_projection((row,))
        assert projection["available"] is False, field
        gaps = projection["gaps"]
        assert isinstance(gaps, list)
        assert gaps[0]["reason_code"] == GAP_MALFORMED, field


def test_posture_projection_rejects_an_empty_evidence_digest() -> None:
    row = _row(_POSTURE_BODY)
    row["value"]["evidence_digest"] = ""
    projection = assurance_twin_posture_projection((row,))
    assert projection["available"] is False
    gaps = projection["gaps"]
    assert isinstance(gaps, list)
    assert gaps[0]["reason_code"] == GAP_MALFORMED


def test_posture_projection_rejects_an_oversized_provenance_field() -> None:
    row = _row(_POSTURE_BODY)
    row["value"]["correlation_id"] = "c" * 513
    projection = assurance_twin_posture_projection((row,))
    assert projection["available"] is False
    gaps = projection["gaps"]
    assert isinstance(gaps, list)
    assert gaps[0]["reason_code"] == GAP_MALFORMED


def test_posture_projection_never_trims_a_valid_provenance_field() -> None:
    # A leading/trailing space inside an otherwise valid value is part of
    # its identity - it MUST pass through unmodified, not be silently
    # trimmed before being replayed to a caller.
    row = _row(_POSTURE_BODY)
    row["value"]["correlation_id"] = " correlation-1 "
    row["value"]["evidence_digest"] = _digest(_POSTURE_BODY)
    projection = assurance_twin_posture_projection((row,))
    assert projection["available"] is True
    reports = projection["reports"]
    assert isinstance(reports, list)
    assert reports[0]["correlation_id"] == " correlation-1 "


def test_posture_projection_rejects_malformed_reason_codes_while_otherwise_valid() -> None:
    cases: list[object] = [
        "not-a-list",
        ["ok", ""],
        ["ok", "   "],
        ["dup", "dup"],
        [1, 2],
        ["x" * 513],
        [f"code-{index}" for index in range(201)],
    ]
    for reason_codes in cases:
        projection = assurance_twin_posture_projection(
            (_row({**_POSTURE_BODY, "reason_codes": reason_codes}),)
        )
        assert projection["available"] is False, reason_codes
        gaps = projection["gaps"]
        assert isinstance(gaps, list)
        assert gaps[0]["reason_code"] == GAP_MALFORMED, reason_codes


def test_posture_projection_renders_valid_distinct_reason_codes_verbatim() -> None:
    projection = assurance_twin_posture_projection(
        (_row({**_POSTURE_BODY, "reason_codes": ["a", "b"]}),)
    )
    assert projection["available"] is True
    reports = projection["reports"]
    assert isinstance(reports, list)
    assert reports[0]["reason_codes"] == ["a", "b"]


def test_review_projection_rejects_malformed_evidence_refs_while_otherwise_valid() -> None:
    cases: list[object] = [
        "not-a-list",
        ["ref-a", ""],
        ["ref-a", "ref-a"],
        [None],
    ]
    for evidence_refs in cases:
        malformed_findings = [{**_REVIEW_BODY["findings"][0], "evidence_refs": evidence_refs}]
        projection = assurance_twin_review_list_projection(
            (_row({**_REVIEW_BODY, "findings": malformed_findings}),)
        )
        assert projection["available"] is False, evidence_refs
        gaps = projection["gaps"]
        assert isinstance(gaps, list)
        assert gaps[0]["reason_code"] == GAP_MALFORMED, evidence_refs


def test_review_detail_projection_binds_the_requested_key_to_the_stored_body() -> None:
    slashed_review_key = "Owner/Repo#7:Change/With Slash"
    body = {**_REVIEW_BODY, "review_key": slashed_review_key}
    detail = assurance_twin_review_detail_projection(
        _row(body), requested_review_key=slashed_review_key
    )
    assert detail is not None
    assert detail["available"] is True
    review = detail["review"]
    assert isinstance(review, dict)
    assert review["review_key"] == slashed_review_key


def test_review_detail_projection_rejects_a_case_mismatched_key() -> None:
    detail = assurance_twin_review_detail_projection(
        _row(_REVIEW_BODY), requested_review_key="review_key-1"
    )
    assert detail is not None
    assert detail["available"] is False
    assert detail["review"] is None
    gap = detail["gap"]
    assert isinstance(gap, dict)
    assert gap["reason_code"] == GAP_MALFORMED
    # No fragment of the mismatched row's own identity leaks into the gap.
    assert gap["identity"] is None


def test_review_detail_projection_rejects_a_slash_variant_of_the_stored_key() -> None:
    body = {**_REVIEW_BODY, "review_key": "owner/repo#1"}
    detail = assurance_twin_review_detail_projection(
        _row(body), requested_review_key="owner/repo/1"
    )
    assert detail is not None
    assert detail["available"] is False
    gap = detail["gap"]
    assert isinstance(gap, dict)
    assert gap["reason_code"] == GAP_MALFORMED


def test_two_usable_reviews_for_one_change_handle_are_a_conflict_gap() -> None:
    older = {**_REVIEW_BODY, "review_key": "review-old", "verdict": "clear", "findings": []}
    newer = {
        **_REVIEW_BODY,
        "review_key": "review-new",
        "verdict": "blocked",
        "generated_at": "2026-07-07T01:00:00Z",
    }
    other = {**_REVIEW_BODY, "review_key": "review-other", "pr_ref": "owner/repo#2"}

    projection = assurance_twin_review_list_projection((_row(older), _row(newer), _row(other)))

    reviews = projection["reviews"]
    gaps = projection["gaps"]
    assert isinstance(reviews, list) and isinstance(gaps, list)
    assert [review["review_key"] for review in reviews] == ["review-other"]
    assert projection["available"] is True and projection["complete"] is False
    assert sorted((gap["identity"], gap["reason_code"]) for gap in gaps) == [
        ("review-new", GAP_CONFLICT),
        ("review-old", GAP_CONFLICT),
    ]
