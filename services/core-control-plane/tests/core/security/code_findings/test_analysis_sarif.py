"""Tests for routing owned analysis through canonical SARIF ingestion."""

from __future__ import annotations

from pathlib import Path

from fdai.core.security.code_findings.analysis_sarif import PRODUCER, render_analysis_sarif
from fdai.core.security.code_findings.canonical import AnalysisContext, build_issues
from fdai.core.security.code_findings.models import Lane
from fdai.core.security.code_findings.python_analysis import analyze_python_repository
from fdai.core.security.code_findings.receipts import (
    baseline_from_dict,
    baseline_to_dict,
    build_receipt,
)
from fdai.core.security.code_findings.result_import import (
    ClaimStatus,
    IssueClaim,
    NextStep,
    ValidationState,
)
from fdai.core.security.code_findings.sarif import SarifIngestContext, ingest_sarif
from fdai.core.security.code_findings.verification import FixVerdict, verify_fix_claims
from fdai.rule_catalog.code_security_analysis import load_analysis_rules

from ._support import CATALOG_ROOT, REVISION, catalog

DIGEST = "sha256:" + "b" * 64


def test_owned_path_round_trips_through_canonical_findings(tmp_path: Path) -> None:
    rule = next(
        item
        for item in load_analysis_rules(CATALOG_ROOT)
        if item.rule_id == "fdai.python.sql-injection"
    )
    (tmp_path / "app.py").write_text(
        """
from flask import request

def query(value):
    return cursor.execute('SELECT ' + value)

@app.get('/search')
def search():
    return query(request.args.get('q'))
"""
    )
    analysis = analyze_python_repository(
        tmp_path,
        revision=REVISION,
        build_context_digest=DIGEST,
        framework_model_digest=DIGEST,
        rule=rule,
    )

    raw = render_analysis_sarif(analysis, rule)
    ingested = ingest_sarif(
        raw,
        SarifIngestContext(lane=Lane.DETERMINISTIC, revision=REVISION, producer=PRODUCER),
    )
    (issue,) = build_issues(
        ingested.occurrences,
        catalog(),
        AnalysisContext(revision=REVISION),
    )

    assert issue.weakness_class == "sql_injection"
    assert issue.producers == (PRODUCER,)
    assert issue.fix_site.path == "app.py"
    assert [step.path for step in issue.code_flow] == ["app.py", "app.py", "app.py"]
    (run,) = ingested.runs
    assert run.execution_successful is True
    assert run.analyzed_paths == ("app.py",)


def test_incomplete_graph_reports_unsuccessful_sarif_invocation(tmp_path: Path) -> None:
    rule = next(
        item
        for item in load_analysis_rules(CATALOG_ROOT)
        if item.rule_id == "fdai.python.sql-injection"
    )
    (tmp_path / "bad.py").write_text("def broken(:\n")
    analysis = analyze_python_repository(
        tmp_path,
        revision=REVISION,
        build_context_digest=DIGEST,
        framework_model_digest=DIGEST,
        rule=rule,
    )

    ingested = ingest_sarif(
        render_analysis_sarif(analysis, rule),
        SarifIngestContext(lane=Lane.DETERMINISTIC, revision=REVISION, producer=PRODUCER),
    )

    assert ingested.occurrences == ()
    assert ingested.runs[0].execution_successful is False


def test_owned_finding_requires_passing_tests_and_equivalent_clean_rescan(
    tmp_path: Path,
) -> None:
    fixed_revision = "c" * 40
    rule = next(
        item
        for item in load_analysis_rules(CATALOG_ROOT)
        if item.rule_id == "fdai.python.sql-injection"
    )
    source = tmp_path / "app.py"
    source.write_text(
        "from flask import request\n"
        "@app.get('/search')\n"
        "def search():\n"
        "    return cursor.execute('SELECT ' + request.args.get('q'))\n",
        encoding="utf-8",
    )

    def scan(revision: str):  # type: ignore[no-untyped-def]
        analysis = analyze_python_repository(
            tmp_path,
            revision=revision,
            build_context_digest=DIGEST,
            framework_model_digest=rule.digest(),
            rule=rule,
        )
        ingested = ingest_sarif(
            render_analysis_sarif(analysis, rule),
            SarifIngestContext(lane=Lane.DETERMINISTIC, revision=revision, producer=PRODUCER),
        )
        issues = build_issues(
            ingested.occurrences,
            catalog(),
            AnalysisContext(revision=revision),
        )
        receipt = build_receipt(revision, catalog().version_stamp(), [ingested])
        return issues, receipt

    baseline_issues, baseline_receipt = scan(REVISION)
    (baseline_issue,) = baseline_issues
    source.write_text(
        "from flask import request\n"
        "@app.get('/search')\n"
        "def search():\n"
        "    return cursor.execute('SELECT WHERE id = ?', (request.args.get('q'),))\n",
        encoding="utf-8",
    )
    rescan_issues, rescan_receipt = scan(fixed_revision)
    claim = IssueClaim(
        baseline_issue.issue_id,
        ClaimStatus.FIXED_CLAIMED,
        ValidationState.TESTS_PASSED,
        (fixed_revision,),
        NextStep.RESCAN_REQUIRED,
        "isolated tests passed",
    )

    (verification,) = verify_fix_claims(
        [claim],
        baseline_from_dict(baseline_to_dict(baseline_issues)),
        baseline_receipt,
        rescan_receipt,
        rescan_issues,
        fixed_revision,
    )

    assert rescan_issues == ()
    assert verification.verdict is FixVerdict.FIXED_VERIFIED
