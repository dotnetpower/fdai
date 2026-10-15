"""Tests for optional, authority-free repair candidate validation."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import yaml
from fdai.core.security.code_findings.analysis_sarif import PRODUCER, render_analysis_sarif
from fdai.core.security.code_findings.canonical import AnalysisContext, build_issues
from fdai.core.security.code_findings.models import Lane
from fdai.core.security.code_findings.pack import PackMode, PackRequest, render_remediation_pack
from fdai.core.security.code_findings.python_analysis import analyze_python_repository
from fdai.core.security.code_findings.repair_candidate import (
    RepairCandidate,
    build_repair_candidate_request,
    validate_repair_candidate,
)
from fdai.core.security.code_findings.result_import import (
    ClaimStatus,
    IssueClaim,
    NextStep,
    ValidationState,
)
from fdai.core.security.code_findings.sarif import SarifIngestContext, ingest_sarif
from fdai.core.security.code_findings.verification import FixVerdict, FixVerification
from fdai.rule_catalog.code_security_analysis import load_analysis_rules

from ._support import CATALOG_ROOT, REVISION, catalog

DIGEST = "sha256:" + "b" * 64
FIXED_REVISION = "c" * 40


def _issue(tmp_path: Path):  # type: ignore[no-untyped-def]
    rule = next(
        item
        for item in load_analysis_rules(CATALOG_ROOT)
        if item.rule_id == "fdai.python.sql-injection"
    )
    (tmp_path / "app.py").write_text(
        "from flask import request\n"
        "@app.get('/search')\n"
        "def search():\n"
        "    return cursor.execute('SELECT ' + request.args.get('q'))\n",
        encoding="utf-8",
    )
    analysis = analyze_python_repository(
        tmp_path,
        revision=REVISION,
        build_context_digest=DIGEST,
        framework_model_digest=rule.digest(),
        rule=rule,
    )
    ingested = ingest_sarif(
        render_analysis_sarif(analysis, rule),
        SarifIngestContext(
            lane=Lane.DETERMINISTIC,
            revision=REVISION,
            producer=PRODUCER,
            trusted_analysis_evidence=True,
        ),
    )
    return build_issues(
        ingested.occurrences,
        catalog(),
        AnalysisContext(revision=REVISION),
    )[0]


def _policy() -> dict[str, object]:
    return yaml.safe_load((CATALOG_ROOT / "remediation-policy.yaml").read_text(encoding="utf-8"))


def _candidate(request):  # type: ignore[no-untyped-def]
    return RepairCandidate(
        schema_version="1.0.0",
        request_id=request.request_id,
        issue_id=request.issue_id,
        baseline_revision=request.baseline_revision,
        candidate_revision=FIXED_REVISION,
        path_id=request.path_id,
        path_digest=request.path_digest,
        unified_diff=(
            "diff --git a/app.py b/app.py\n"
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -4,1 +4,1 @@\n"
            "-    return cursor.execute('SELECT ' + request.args.get('q'))\n"
            "+    return cursor.execute('SELECT WHERE id = ?', (request.args.get('q'),))\n"
        ),
    )


def _verification(issue_id: str) -> FixVerification:
    return FixVerification(issue_id, ClaimStatus.FIXED_CLAIMED, FixVerdict.FIXED_VERIFIED)


def _claim(issue_id: str, validation: ValidationState = ValidationState.TESTS_PASSED) -> IssueClaim:
    return IssueClaim(
        issue_id,
        ClaimStatus.FIXED_CLAIMED,
        validation,
        (FIXED_REVISION,),
        NextStep.RESCAN_REQUIRED,
        "isolated tests",
    )


def test_candidate_requires_all_independent_gates(tmp_path: Path) -> None:
    issue = _issue(tmp_path)
    request = build_repair_candidate_request(issue)
    assert request is not None and request.execution_authority is False
    assert b"SELECT" not in request.canonical_bytes()

    result = validate_repair_candidate(
        request,
        _candidate(request),
        policy=_policy(),
        validation_claim=_claim(issue.issue_id),
        verification=_verification(issue.issue_id),
        rescan_revision=FIXED_REVISION,
        displayed_issue=issue,
    )

    assert result.accepted is True
    assert result.reasons == ()
    assert result.diff_receipt["ok"] is True
    assert result.execution_authority is False


def test_candidate_validation_fails_closed_for_each_missing_gate(tmp_path: Path) -> None:
    issue = _issue(tmp_path)
    request = build_repair_candidate_request(issue)
    assert request is not None and issue.analysis_evidence is not None
    candidate = _candidate(request)
    cases = (
        (
            replace(candidate, execution_authority=True),
            _claim(issue.issue_id),
            _verification(issue.issue_id),
            FIXED_REVISION,
            issue,
            "candidate_requests_execution_authority",
        ),
        (
            candidate,
            _claim(issue.issue_id, ValidationState.TESTS_FAILED),
            _verification(issue.issue_id),
            FIXED_REVISION,
            issue,
            "candidate_tests_not_passed",
        ),
        (
            candidate,
            _claim(issue.issue_id),
            FixVerification(issue.issue_id, ClaimStatus.FIXED_CLAIMED, FixVerdict.STILL_PRESENT),
            FIXED_REVISION,
            issue,
            "candidate_fix_not_verified",
        ),
        (
            candidate,
            _claim(issue.issue_id),
            _verification(issue.issue_id),
            "d" * 40,
            issue,
            "candidate_revision_not_rescanned",
        ),
        (
            candidate,
            _claim(issue.issue_id),
            _verification(issue.issue_id),
            FIXED_REVISION,
            replace(
                issue,
                analysis_evidence=replace(issue.analysis_evidence, path_id="path:different"),
            ),
            "displayed_path_replay_mismatch",
        ),
        (
            replace(candidate, unified_diff=candidate.unified_diff.replace("app.py", "other.py")),
            _claim(issue.issue_id),
            _verification(issue.issue_id),
            FIXED_REVISION,
            issue,
            "candidate_diff_rejected",
        ),
    )
    for changed, claim, verification, rescan_revision, displayed, expected in cases:
        result = validate_repair_candidate(
            request,
            changed,
            policy=_policy(),
            validation_claim=claim,
            verification=verification,
            rescan_revision=rescan_revision,
            displayed_issue=displayed,
        )
        assert result.accepted is False
        assert expected in result.reasons


def test_request_abstains_without_displayed_path_evidence(tmp_path: Path) -> None:
    issue = _issue(tmp_path)

    assert build_repair_candidate_request(replace(issue, analysis_evidence=None)) is None
    assert build_repair_candidate_request(replace(issue, code_flow=())) is None


def test_full_pack_exposes_inert_request_but_minimized_pack_withholds_it(tmp_path: Path) -> None:
    issue = _issue(tmp_path)
    base = PackRequest(
        repository_alias="example-service",
        base_commit=REVISION,
        created_at=datetime(2026, 10, 15, tzinfo=UTC),
    )

    full = render_remediation_pack((issue,), catalog(), base)
    minimized = render_remediation_pack((issue,), catalog(), replace(base, mode=PackMode.MINIMIZED))
    index = yaml.safe_load(full.files["findings/index.json"])
    request_path = f"findings/repair-requests/{issue.issue_id}.json"

    assert request_path in full.files
    assert index["repair_candidate_requests"] == [
        {"issue_id": issue.issue_id, "path": request_path, "execution_authority": False}
    ]
    assert b'"execution_authority": false' in full.files[request_path]
    assert request_path not in minimized.files
    assert b"repair-requests" not in b"".join(minimized.files.values())
