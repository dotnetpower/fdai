"""Tests for bounded code-security issue summaries."""

from __future__ import annotations

import json

import pytest
from fdai.core.security.code_findings.canonical import AnalysisContext, build_issues
from fdai.core.security.code_findings.issue_summary import (
    MAX_ISSUE_SUMMARIES,
    IssueSummaryError,
    summarize_issues,
    validate_issue_summary,
)
from fdai.core.security.code_findings.models import Lane
from fdai.core.security.code_findings.sarif import SarifIngestContext, ingest_sarif

from ._support import REVISION, catalog, result, sarif


def _issues():  # type: ignore[no-untyped-def]
    raw = sarif(
        "Scanner",
        [
            result("sqli", "src/secret_module/db.py", 4, cwe=89, message="leak me"),
            result(
                "CVE-2024-66666",
                "package-lock.json",
                1,
                properties={"packageName": "libk", "security-severity": "8.0"},
            ),
        ],
    )
    occurrences = ingest_sarif(
        raw, SarifIngestContext(lane=Lane.EXTERNAL, revision=REVISION)
    ).occurrences
    return build_issues(occurrences, catalog(), AnalysisContext(revision=REVISION))


def test_summaries_carry_triage_fields_but_no_location_or_scanner_text() -> None:
    summaries, truncated = summarize_issues(_issues())
    assert truncated is False and len(summaries) == 2
    text = json.dumps(summaries)
    assert "secret_module" not in text and "db.py" not in text and "leak me" not in text
    by_class = {item["weakness_class"]: item for item in summaries}
    assert by_class["sql_injection"]["cwe_ids"] == [89]
    dependency = next(item for item in summaries if item["package"] == "libk")
    assert dependency["advisory_ids"] == ["CVE-2024-66666"]
    assert all(validate_issue_summary(item) == item for item in summaries)


def test_summaries_are_bounded_and_report_truncation() -> None:
    issue = _issues()[0]
    summaries, truncated = summarize_issues([issue] * (MAX_ISSUE_SUMMARIES + 1))
    assert len(summaries) == MAX_ISSUE_SUMMARIES and truncated is True


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda s: s.update(path="src/db.py"), "fields"),
        (lambda s: s.update(issue_id="../x"), "issue_id"),
        (lambda s: s.update(priority="P9"), "priority"),
        (lambda s: s.update(severity="extreme"), "severity"),
        (lambda s: s.update(weakness_class="Bad Class"), "weakness_class"),
        (lambda s: s.update(cwe_ids=["CWE-89"]), "cwe_ids"),
        (lambda s: s.update(advisory_ids=["<script>"]), "advisory_ids"),
        (lambda s: s.update(package="../../etc"), "package"),
        (lambda s: s.update(known_exploited="yes"), "known_exploited"),
    ],
)
def test_validator_rejects_out_of_contract_summaries(mutate, message: str) -> None:  # type: ignore[no-untyped-def]
    summary = dict(summarize_issues(_issues())[0][0])
    mutate(summary)
    with pytest.raises(IssueSummaryError, match=message):
        validate_issue_summary(summary)
