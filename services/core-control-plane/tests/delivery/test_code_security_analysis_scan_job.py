"""Scan-job integration tests for the FDAI-owned analysis engine."""

from __future__ import annotations

from pathlib import Path

from fdai.core.security.code_findings.analysis_contracts import (
    CodeGraphArtifact,
    CodeGraphNode,
    GraphNodeKind,
    PathEvidence,
    PathEvidenceStep,
    PathStepRole,
    SourceSpan,
)
from fdai.core.security.code_findings.typescript_analysis import (
    TypeScriptAnalysisResult,
    TypeScriptFrontendConfig,
)
from fdai.delivery.code_security_acquire import AcquiredSource, GitSourceAcquirer
from fdai.delivery.code_security_sandbox import BubblewrapScannerSandbox
from fdai.delivery.code_security_scan_job import ScanJobConfig, run_scan_job, sarif_specs
from fdai.rule_catalog.code_security import load_code_security_catalog
from fdai.rule_catalog.code_security_analysis import load_analysis_rules
from fdai.rule_catalog.code_security_scanners import load_scanner_catalog

REPO_ROOT = Path(__file__).resolve().parents[4]
CATALOG_ROOT = REPO_ROOT / "rule-catalog" / "code-security"
REVISION = "a" * 40
DIGEST = "sha256:" + "b" * 64


class _Acquirer(GitSourceAcquirer):
    def __init__(
        self,
        source: Path,
        *,
        revision: str = REVISION,
        tree_id: str = "b" * 40,
    ) -> None:
        self.source = source
        self.revision = revision
        self.tree_id = tree_id

    def acquire_path(self, folder: Path, *, include_uncommitted: bool) -> AcquiredSource:
        assert folder == self.source and include_uncommitted is False
        return AcquiredSource(self.source, self.revision, self.tree_id)


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
    analysis_rules = tuple(
        rule
        for rule in load_analysis_rules(CATALOG_ROOT)
        if rule.rule_id == "fdai.python.sql-injection"
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
        analysis_rules=analysis_rules,
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


async def test_scan_job_reuses_and_invalidates_python_snapshots(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    app = source / "app.py"
    app.write_text(
        "from flask import request\n"
        "@app.get('/search')\n"
        "def search():\n"
        "    return cursor.execute('SELECT ' + request.args.get('q'))\n",
        encoding="utf-8",
    )
    analysis_rules = tuple(
        rule
        for rule in load_analysis_rules(CATALOG_ROOT)
        if rule.rule_id == "fdai.python.sql-injection"
    )
    work_root = tmp_path / "work"

    async def scan(revision: str, tree_id: str):  # type: ignore[no-untyped-def]
        return await run_scan_job(
            ScanJobConfig(
                repository="",
                revision="",
                repository_alias="example-service",
                work_root=work_root,
                executables={},
                rules_dir=CATALOG_ROOT / "rules",
                required_scanners=frozenset(),
                local_path=source,
            ),
            catalog=load_code_security_catalog(CATALOG_ROOT),
            scanners=load_scanner_catalog(CATALOG_ROOT),
            acquirer=_Acquirer(source, revision=revision, tree_id=tree_id),
            sandbox=BubblewrapScannerSandbox(),
            analysis_rules=analysis_rules,
        )

    first = await scan(REVISION, "b" * 40)
    app.write_text(
        "from flask import request\n"
        "@app.get('/search')\n"
        "def search():\n"
        "    return cursor.execute('SELECT WHERE id = ?', (request.args.get('q'),))\n",
        encoding="utf-8",
    )
    changed = await scan("c" * 40, "d" * 40)
    repeated = await scan("c" * 40, "d" * 40)

    assert first.analysis_incremental_plans[0].reason == "no_previous_snapshot"
    assert changed.analysis_incremental_plans[0].reason == "dependency_invalidation"
    assert changed.analysis_incremental_plans[0].changed_files == ("app.py",)
    assert changed.analysis_incremental_plans[0].partial_recompute is False
    assert repeated.analysis_incremental_plans[0].reason == "inputs_unchanged"
    assert repeated.analysis_incremental_plans[0].reused_result is True
    assert len(first.issues) == 1
    assert changed.issues == repeated.issues == ()
    assert not first.analysis_cache_notes
    assert not changed.analysis_cache_notes
    assert not repeated.analysis_cache_notes


async def test_scan_job_dispatches_typescript_result_to_canonical_review(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.ts").write_text("export const value = 1;", encoding="utf-8")
    rules = load_analysis_rules(CATALOG_ROOT)
    rule = next(item for item in rules if item.rule_id == "fdai.typescript.sql-injection")
    source_node = CodeGraphNode(
        node_id="source:typescript",
        kind=GraphNodeKind.SOURCE,
        name="request parameter",
        span=SourceSpan(path="app.ts", start_line=1, end_line=1),
    )
    sink_node = CodeGraphNode(
        node_id="sink:typescript",
        kind=GraphNodeKind.SINK,
        name="pool.query",
        span=SourceSpan(path="app.ts", start_line=1, end_line=1),
    )
    graph = CodeGraphArtifact(
        schema_version="1.1.0",
        revision=REVISION,
        build_context_digest=DIGEST,
        framework_model_digest=rule.digest(),
        frontend_versions={"typescript-compiler": "5.9.3"},
        nodes=(source_node, sink_node),
    )
    path = PathEvidence(
        schema_version="1.1.0",
        path_id="path:typescript-scan-job",
        revision=REVISION,
        graph_digest=graph.digest(),
        rule_id=rule.rule_id,
        rule_version=rule.version,
        steps=(
            PathEvidenceStep(
                node_id=source_node.node_id,
                role=PathStepRole.SOURCE,
                span=source_node.span,  # type: ignore[arg-type]
            ),
            PathEvidenceStep(
                node_id=sink_node.node_id,
                role=PathStepRole.SINK,
                span=sink_node.span,  # type: ignore[arg-type]
            ),
        ),
    )

    def analyze(*args, **kwargs):  # type: ignore[no-untyped-def]
        selected = kwargs["rule"]
        return TypeScriptAnalysisResult(
            graph,
            (path,) if selected.rule_id == "fdai.typescript.sql-injection" else (),
        )

    monkeypatch.setattr(
        "fdai.delivery.code_security_scan_job.analyze_typescript_repository",
        analyze,
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
        analysis_rules=rules,
        typescript_frontend=TypeScriptFrontendConfig(
            node=tmp_path / "node",
            script=tmp_path / "frontend.cjs",
        ),
    )

    assert len(result.analysis_results) == 4
    assert result.issues[0].weakness_class == "sql_injection"
    assert result.package["coverage_complete"] is True


async def test_scan_job_dispatches_java_result_to_canonical_review(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "Api.java").write_text(
        "class Api { Object search(Request request) { "
        'return Store.run(request.getParameter("q")); } }',
        encoding="utf-8",
    )
    (source / "Store.java").write_text(
        "class Store { static Object run(String query) { return database.executeQuery(query); } }",
        encoding="utf-8",
    )
    rules = tuple(
        rule
        for rule in load_analysis_rules(CATALOG_ROOT)
        if rule.rule_id == "fdai.java.sql-injection"
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
        analysis_rules=rules,
    )

    assert len(result.analysis_results) == 1
    assert len(result.issues) == 1
    assert result.issues[0].weakness_class == "sql_injection"
    assert result.package["coverage_complete"] is True
