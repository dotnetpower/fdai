"""Tests for routing owned analysis through canonical SARIF ingestion."""

from __future__ import annotations

from pathlib import Path

from fdai.core.security.code_findings.analysis_sarif import PRODUCER, render_analysis_sarif
from fdai.core.security.code_findings.canonical import AnalysisContext, build_issues
from fdai.core.security.code_findings.models import Lane
from fdai.core.security.code_findings.python_analysis import analyze_python_repository
from fdai.core.security.code_findings.sarif import SarifIngestContext, ingest_sarif
from fdai.rule_catalog.code_security_analysis import load_analysis_rules

from ._support import CATALOG_ROOT, REVISION, catalog

DIGEST = "sha256:" + "b" * 64


def test_owned_path_round_trips_through_canonical_findings(tmp_path: Path) -> None:
    (rule,) = load_analysis_rules(CATALOG_ROOT)
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
    (rule,) = load_analysis_rules(CATALOG_ROOT)
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
