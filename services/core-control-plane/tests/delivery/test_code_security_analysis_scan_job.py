"""Scan-job integration tests for the FDAI-owned analysis engine."""

from __future__ import annotations

from pathlib import Path

from fdai.delivery.code_security_acquire import AcquiredSource, GitSourceAcquirer
from fdai.delivery.code_security_sandbox import BubblewrapScannerSandbox
from fdai.delivery.code_security_scan_job import ScanJobConfig, run_scan_job, sarif_specs
from fdai.rule_catalog.code_security import load_code_security_catalog
from fdai.rule_catalog.code_security_analysis import load_analysis_rules
from fdai.rule_catalog.code_security_scanners import load_scanner_catalog

REPO_ROOT = Path(__file__).resolve().parents[4]
CATALOG_ROOT = REPO_ROOT / "rule-catalog" / "code-security"
REVISION = "a" * 40


class _Acquirer(GitSourceAcquirer):
    def __init__(self, source: Path) -> None:
        self.source = source

    def acquire_path(self, folder: Path, *, include_uncommitted: bool) -> AcquiredSource:
        assert folder == self.source and include_uncommitted is False
        return AcquiredSource(self.source, REVISION, "b" * 40)


async def test_scan_job_routes_owned_analysis_through_canonical_review(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text(
        """
from flask import request

def query(value):
    return cursor.execute('SELECT ' + value)

@app.get('/search')
def search():
    return query(request.args.get('q'))
""",
        encoding="utf-8",
    )
    result = await run_scan_job(
        ScanJobConfig(
            repository="",
            revision="",
            repository_alias="example-service",
            work_root=tmp_path / "work",
            executables={},
            rules_dir=CATALOG_ROOT / "rules",
            required_scanners=frozenset(),
            local_path=source,
        ),
        catalog=load_code_security_catalog(CATALOG_ROOT),
        scanners=load_scanner_catalog(CATALOG_ROOT),
        acquirer=_Acquirer(source),
        sandbox=BubblewrapScannerSandbox(),
        analysis_rules=load_analysis_rules(CATALOG_ROOT),
    )

    assert len(result.analysis_results) == 1
    assert len(result.issues) == 1
    assert result.issues[0].weakness_class == "sql_injection"
    assert result.package["coverage_complete"] is True
    assert result.coverage_limits == ()
    assert len(result.sarif_files) == 1
    assert sarif_specs(result) == [f"{result.sarif_files[0]}:deterministic"]
    (run,) = result.receipt.runs
    assert run.producer == "FDAI analysis engine"
    assert run.completed is True and run.full_repository is True
