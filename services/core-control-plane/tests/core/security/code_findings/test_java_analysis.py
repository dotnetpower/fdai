from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fdai.core.security.code_findings.java_analysis import (
    JavaAnalysisLimits,
    JavaCompilerConfig,
    analyze_java_repository,
)
from fdai.rule_catalog.code_security_analysis import load_analysis_rules

REVISION = "a" * 40
DIGEST = f"sha256:{'b' * 64}"
REPO_ROOT = Path(__file__).parents[6]


def _rule():  # type: ignore[no-untyped-def]
    root = REPO_ROOT / "rule-catalog" / "code-security"
    return next(
        rule for rule in load_analysis_rules(root) if rule.rule_id == "fdai.java.sql-injection"
    )


def _analyze(root: Path, *, limits: JavaAnalysisLimits | None = None):  # type: ignore[no-untyped-def]
    return analyze_java_repository(
        root,
        revision=REVISION,
        build_context_digest=DIGEST,
        framework_model_digest=_rule().digest(),
        rule=_rule(),
        limits=limits,
    )


def test_cross_file_request_parameter_reaches_sql_sink(tmp_path: Path) -> None:
    (tmp_path / "Api.java").write_text(
        "class Api { Object search(Request request) { "
        'return Store.run(request.getParameter("q")); } }'
    )
    (tmp_path / "Store.java").write_text(
        "class Store { static Object run(String query) { return database.executeQuery(query); } }"
    )

    result = _analyze(tmp_path)

    assert result is not None
    assert len(result.paths) == 1
    assert result.paths[0].steps[0].span.path == "Api.java"
    assert result.paths[0].steps[-1].span.path == "Store.java"
    assert not result.graph.coverage_limits


def test_parameterized_and_constant_queries_stay_safe(tmp_path: Path) -> None:
    (tmp_path / "Store.java").write_text(
        """class Store {
        Object search(Request request) {
          PreparedStatement stmt = connection.prepareStatement("SELECT * FROM item WHERE id = ?");
          stmt.setString(1, request.getParameter("id"));
          return stmt.executeQuery();
        }
        Object health() { return database.executeQuery("SELECT 1"); }
        }"""
    )

    result = _analyze(tmp_path)

    assert result is not None
    assert result.paths == ()
    assert not result.graph.coverage_limits


def test_symlink_and_graph_budget_fail_closed(tmp_path: Path) -> None:
    outside = tmp_path.parent / "Outside.java"
    outside.write_text("class Outside {}")
    (tmp_path / "Linked.java").symlink_to(outside)
    (tmp_path / "Main.java").write_text("class Main { void run() {} }")

    result = _analyze(tmp_path, limits=JavaAnalysisLimits(max_nodes=1))

    assert result is not None
    assert "java-graph-node-limit" in result.graph.coverage_limits
    assert any(item.startswith("java-unreadable:") for item in result.graph.coverage_limits)


def test_exact_file_limit_is_complete_and_excess_is_incomplete(tmp_path: Path) -> None:
    (tmp_path / "One.java").write_text("class One {}", encoding="utf-8")
    exact = _analyze(tmp_path, limits=JavaAnalysisLimits(max_files=1))
    assert exact is not None
    assert "java-file-limit" not in exact.graph.coverage_limits

    (tmp_path / "Two.java").write_text("class Two {}", encoding="utf-8")
    excess = _analyze(tmp_path, limits=JavaAnalysisLimits(max_files=1))
    assert excess is not None
    assert "java-file-limit" in excess.graph.coverage_limits


def test_javac_symbols_bind_cross_file_calls_and_report_attribution(tmp_path: Path) -> None:
    java = shutil.which("java")
    if java is None:
        pytest.skip("a JDK is required for compiler-backed Java analysis")
    (tmp_path / "Types.java").write_text(
        "class Request { String getParameter(String key) { return key; } }\n"
        "class Database { Object executeQuery(String query) { return query; } }\n",
        encoding="utf-8",
    )
    (tmp_path / "Api.java").write_text(
        "class Api { Object search(Request request) { "
        'return Store.run(request.getParameter("q")); } }',
        encoding="utf-8",
    )
    (tmp_path / "Store.java").write_text(
        "class Store { static Database database = new Database(); "
        "static Object run(String query) { return database.executeQuery(query); } }",
        encoding="utf-8",
    )

    result = analyze_java_repository(
        tmp_path,
        revision=REVISION,
        build_context_digest=DIGEST,
        framework_model_digest=_rule().digest(),
        rule=_rule(),
        compiler=JavaCompilerConfig(
            java=Path(java),
            helper=REPO_ROOT / "tools" / "code-security-java-frontend" / "FdaiJavaSymbols.java",
        ),
    )

    assert result is not None and len(result.paths) == 1
    assert result.graph.frontend_versions["javac"].count(".") == 2
    assert "java.compiler-attribution-errors:1" not in result.graph.coverage_limits
    assert any(node.name == "Store.run" for node in result.graph.nodes)
    assert any(node.name == "Database.executeQuery" for node in result.graph.nodes)
