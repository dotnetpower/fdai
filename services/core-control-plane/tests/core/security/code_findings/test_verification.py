"""Tests for coverage receipts, rescan verification, and false-positive adjudication."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fdai.core.security.code_findings.adjudication import (
    AdjudicationDecision,
    AdjudicationError,
    adjudicate_false_positive,
)
from fdai.core.security.code_findings.canonical import AnalysisContext, build_issues
from fdai.core.security.code_findings.models import Lane
from fdai.core.security.code_findings.receipts import (
    baseline_from_dict,
    baseline_to_dict,
    build_receipt,
    receipt_from_dict,
    receipt_to_dict,
)
from fdai.core.security.code_findings.result_import import (
    ClaimStatus,
    IssueClaim,
    NextStep,
    ValidationState,
)
from fdai.core.security.code_findings.sarif import SarifIngestContext, ingest_sarif
from fdai.core.security.code_findings.verification import FixVerdict, verify_fix_claims

from ._support import REVISION, catalog, result

FIXED = "b" * 40


def _sarif(
    results: list[dict[str, object]],
    *,
    success: bool | None = True,
    artifacts: tuple[str, ...] = ("src/db.py",),
    producer: str = "Opengrep",
) -> bytes:
    run: dict[str, object] = {
        "tool": {
            "driver": {"name": producer, "version": "1.2.0", "rules": [{"id": "python.sqli"}]}
        },
        "results": results,
        "artifacts": [{"location": {"uri": path}} for path in artifacts],
    }
    if success is not None:
        run["invocations"] = [{"executionSuccessful": success}]
    return json.dumps({"version": "2.1.0", "runs": [run]}).encode()


def _scan(raw: bytes, revision: str, **receipt_kwargs: object):  # type: ignore[no-untyped-def]
    ingested = ingest_sarif(raw, SarifIngestContext(lane=Lane.DETERMINISTIC, revision=revision))
    issues = build_issues(ingested.occurrences, catalog(), AnalysisContext(revision=revision))
    receipt = build_receipt(revision, catalog().version_stamp(), [ingested], **receipt_kwargs)  # type: ignore[arg-type]
    return issues, receipt


def _claim(
    issue_id: str, status: ClaimStatus = ClaimStatus.FIXED_CLAIMED, evidence: str = ""
) -> IssueClaim:
    return IssueClaim(
        issue_id,
        status,
        ValidationState.TESTS_PASSED,
        ("b" * 40,),
        NextStep.RESCAN_REQUIRED,
        evidence,
    )


_FINDING = result("python.sqli", "src/db.py", 2, cwe=89)


def _baseline():  # type: ignore[no-untyped-def]
    issues, receipt = _scan(_sarif([_FINDING]), REVISION)
    stored = baseline_from_dict(json.loads(json.dumps(baseline_to_dict(issues))))
    return issues[0], stored, receipt_from_dict(json.loads(json.dumps(receipt_to_dict(receipt))))


def test_equivalent_clean_rescan_verifies_the_fix() -> None:
    issue, stored, baseline = _baseline()
    rescan_issues, rescan = _scan(_sarif([]), FIXED)
    (verdict,) = verify_fix_claims(
        [_claim(issue.issue_id)], stored, baseline, rescan, rescan_issues, FIXED
    )
    assert verdict.verdict is FixVerdict.FIXED_VERIFIED


def test_root_cause_still_reported_after_line_shift_is_still_present() -> None:
    issue, stored, baseline = _baseline()
    moved = result("python.sqli", "src/db.py", 9, cwe=89)
    rescan_issues, rescan = _scan(_sarif([moved]), FIXED)
    (verdict,) = verify_fix_claims(
        [_claim(issue.issue_id)], stored, baseline, rescan, rescan_issues, FIXED
    )
    assert verdict.verdict is FixVerdict.STILL_PRESENT


@pytest.mark.parametrize(
    ("raw", "kwargs", "reason"),
    [
        (_sarif([], success=None), {}, "completion not reported"),
        (_sarif([], success=False), {}, "completion not reported"),
        (_sarif([], artifacts=("src/other.py",)), {}, "not among analyzed paths"),
        (_sarif([], producer="Semgrep"), {}, "no rescan run"),
        (_sarif([]), {"rules_versions": {"Opengrep": "rules-2"}}, "rules version changed"),
    ],
)
def test_non_equivalent_rescan_is_inconclusive(
    raw: bytes, kwargs: dict[str, object], reason: str
) -> None:
    issue, stored, baseline = _baseline()
    rescan_issues, rescan = _scan(raw, FIXED, **kwargs)
    (verdict,) = verify_fix_claims(
        [_claim(issue.issue_id)], stored, baseline, rescan, rescan_issues, FIXED
    )
    assert verdict.verdict is FixVerdict.INCONCLUSIVE
    assert any(reason in item for item in verdict.reasons), verdict.reasons


def test_declared_supersession_and_full_repository_restore_equivalence() -> None:
    issue, stored, baseline = _baseline()
    rescan_issues, rescan = _scan(
        _sarif([], artifacts=()),
        FIXED,
        rules_versions={"Opengrep": "rules-2"},
        supersedes={"Opengrep": frozenset({"tool:1.2.0"})},
        full_repository=frozenset({"Opengrep"}),
    )
    (verdict,) = verify_fix_claims(
        [_claim(issue.issue_id)], stored, baseline, rescan, rescan_issues, FIXED
    )
    assert verdict.verdict is FixVerdict.FIXED_VERIFIED


def test_rescan_of_a_different_commit_is_inconclusive_and_other_claims_not_applicable() -> None:
    issue, stored, baseline = _baseline()
    rescan_issues, rescan = _scan(_sarif([]), "c" * 40)
    verdicts = verify_fix_claims(
        [_claim(issue.issue_id), _claim(issue.issue_id, ClaimStatus.DEFERRED)],
        stored,
        baseline,
        rescan,
        rescan_issues,
        FIXED,
    )
    assert verdicts[0].verdict is FixVerdict.INCONCLUSIVE
    assert "claimed commit" in verdicts[0].reasons[0]
    assert verdicts[1].verdict is FixVerdict.NOT_APPLICABLE


def test_dependency_alias_keeps_issue_present() -> None:
    lock = result(
        "CVE-2024-55555",
        "package-lock.json",
        1,
        properties={"packageName": "libq", "security-severity": "7.5"},
    )
    issues, receipt = _scan(_sarif([lock], artifacts=("package-lock.json",)), REVISION)
    stored = baseline_from_dict(baseline_to_dict(issues))
    alias = result(
        "GHSA-cfgh-jmpq-rvwx",
        "package-lock.json",
        1,
        properties={"packageName": "libq", "tags": ["CVE-2024-55555"]},
    )
    rescan_issues, rescan = _scan(_sarif([alias], artifacts=("package-lock.json",)), FIXED)
    (verdict,) = verify_fix_claims(
        [_claim(issues[0].issue_id)], stored, receipt, rescan, rescan_issues, FIXED
    )
    assert verdict.verdict is FixVerdict.STILL_PRESENT


def test_artifact_traversal_is_not_counted_as_analyzed() -> None:
    _, receipt = _scan(_sarif([], artifacts=("../outside.py", "src/db.py")), REVISION)
    assert receipt.runs[0].analyzed_paths == frozenset({"src/db.py"})


_AT = datetime(2026, 10, 7, tzinfo=UTC)


def test_adjudication_requires_separate_principals_and_approval() -> None:
    claim = _claim(
        "FDAI-SEC-0123456789ab", ClaimStatus.CLAIMED_FALSE_POSITIVE, "input validated upstream"
    )
    kwargs = {
        "pack_id": "abcdefabcdef",
        "approval_ref": "approval/hil-42",
        "decision": AdjudicationDecision.ACCEPTED,
        "rationale": "Caller allowlists the id before this query.",
        "decided_at": _AT,
    }
    record = adjudicate_false_positive(
        claim, claimant="dev@example.com", adjudicator="secops@example.com", **kwargs
    )  # type: ignore[arg-type]
    assert record.issue_disposition == "false_positive"
    with pytest.raises(AdjudicationError, match="own claim"):
        adjudicate_false_positive(
            claim, claimant="dev@example.com", adjudicator="dev@example.com", **kwargs
        )  # type: ignore[arg-type]
    solo = adjudicate_false_positive(
        claim,
        claimant="op@example.com",
        adjudicator="op@example.com",
        single_operator_profile=True,
        **kwargs,
    )  # type: ignore[arg-type]
    assert solo.single_operator_profile is True
    with pytest.raises(AdjudicationError, match="approval"):
        adjudicate_false_positive(
            claim, claimant="a", adjudicator="b", **{**kwargs, "approval_ref": ""}
        )  # type: ignore[arg-type]
    with pytest.raises(AdjudicationError, match="claimed_false_positive"):
        adjudicate_false_positive(
            _claim("FDAI-SEC-0123456789ab"), claimant="a", adjudicator="b", **kwargs
        )  # type: ignore[arg-type]
    with pytest.raises(AdjudicationError, match="rationale"):
        adjudicate_false_positive(
            claim, claimant="a", adjudicator="b", **{**kwargs, "rationale": "short"}
        )  # type: ignore[arg-type]
