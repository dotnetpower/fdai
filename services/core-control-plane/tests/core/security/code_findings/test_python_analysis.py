"""Vertical-slice tests for owned Python interprocedural analysis."""

from __future__ import annotations

from pathlib import Path

import pytest
from fdai.core.security.code_findings.analysis_contracts import (
    CodeSecurityRuleSpec,
    PathStepRole,
    RuleAnalysisKind,
    RuleSelector,
)
from fdai.core.security.code_findings.python_analysis import (
    PythonAnalysisLimits,
    analyze_python_repository,
)
from fdai.rule_catalog.code_security_analysis import load_analysis_rules

from ._support import CATALOG_ROOT

REVISION = "a" * 40
DIGEST = "sha256:" + "b" * 64


def rule() -> CodeSecurityRuleSpec:
    return CodeSecurityRuleSpec(
        schema_version="1.0.0",
        rule_id="fdai.python.sql-injection",
        version="1.0.0",
        analysis_kind=RuleAnalysisKind.GRAPH_FLOW,
        languages=("python",),
        cwe_ids=(89,),
        selectors=(
            RuleSelector(role="source", symbol="flask.request.args"),
            RuleSelector(role="source", symbol="request.args"),
            RuleSelector(role="sink", symbol="cursor.execute", argument_index=0),
            RuleSelector(role="propagator", symbol="strip"),
            RuleSelector(
                role="sanitizer",
                symbol="sqlalchemy.bindparam",
                security_context="sql-parameter-binding",
            ),
        ),
        vulnerable_cases=("python-sqli-cross-file",),
        safe_cases=("python-sqli-parameterized",),
    )


def write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def analyze(root: Path, *, limits: PythonAnalysisLimits | None = None):  # type: ignore[no-untyped-def]
    return analyze_python_repository(
        root,
        revision=REVISION,
        build_context_digest=DIGEST,
        framework_model_digest=DIGEST,
        rule=rule(),
        limits=limits,
    )


def test_cross_file_route_input_reaches_sql_sink_with_complete_path(tmp_path: Path) -> None:
    write(
        tmp_path,
        "api.py",
        """
from flask import request
from queries import build_query
import database as storage

@app.get('/orders')
def orders():
    order_id = request.args.get('id')
    query = build_query(order_id)
    return storage.run(query)
""",
    )
    write(
        tmp_path,
        "queries.py",
        """
def normalize(value):
    return value.strip()

def build_query(value):
    return 'SELECT * FROM orders WHERE id = ' + normalize(value)
""",
    )
    write(
        tmp_path,
        "database.py",
        """
def run(query):
    return cursor.execute(query)
""",
    )

    first = analyze(tmp_path)
    second = analyze(tmp_path)

    assert first.graph.digest() == second.graph.digest()
    assert len(first.paths) == 1
    path = first.paths[0]
    assert path.digest() == second.paths[0].digest()
    assert path.steps[0].role is PathStepRole.SOURCE
    assert path.steps[-1].role is PathStepRole.SINK
    assert {step.span.path for step in path.steps} == {"api.py", "queries.py", "database.py"}
    assert sum(step.role is PathStepRole.CALL for step in path.steps) >= 3
    assert not first.graph.coverage_limits


def test_parameterized_query_and_constant_caller_stay_safe(tmp_path: Path) -> None:
    write(
        tmp_path,
        "api.py",
        """
from flask import request
from database import safe_run

@app.get('/orders')
def orders():
    return safe_run(request.args.get('id'))
""",
    )
    write(
        tmp_path,
        "database.py",
        """
def safe_run(order_id):
    return cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))

def maintenance():
    return safe_run('fixed')
""",
    )

    result = analyze(tmp_path)

    assert result.paths == ()
    assert not result.graph.coverage_limits


def test_contexts_do_not_taint_a_separate_constant_caller(tmp_path: Path) -> None:
    write(
        tmp_path,
        "app.py",
        """
from flask import request

def query(value):
    return cursor.execute('SELECT ' + value)

def fixed():
    return query('1')

@app.get('/search')
def search():
    return query(request.args.get('q'))
""",
    )

    result = analyze(tmp_path)

    assert len(result.paths) == 1
    assert result.paths[0].steps[0].span.start_line == 12


def test_recursion_and_unresolved_dispatch_are_explicit_coverage_limits(tmp_path: Path) -> None:
    write(
        tmp_path,
        "app.py",
        """
from flask import request

def recurse(value):
    return recurse(value)

@app.get('/search')
def search():
    value = recurse(request.args.get('q'))
    return handler.execute(value)
""",
    )

    result = analyze(tmp_path, limits=PythonAnalysisLimits(max_call_depth=2))

    assert result.paths == ()
    assert any("recursion" in item for item in result.graph.coverage_limits)


def test_parse_and_file_limits_never_become_clean_coverage(tmp_path: Path) -> None:
    write(tmp_path, "bad.py", "def broken(:\n")
    write(tmp_path, "good.py", "def ok():\n    return 1\n")

    result = analyze(tmp_path, limits=PythonAnalysisLimits(max_files=1))

    assert result.paths == ()
    assert result.graph.coverage_limits


def test_symlink_root_is_rejected_and_graph_budget_is_explicit(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    write(source, "app.py", "def one(value):\n    return value\n")
    linked = tmp_path / "linked"
    linked.symlink_to(source, target_is_directory=True)

    with pytest.raises(ValueError, match="analysis root"):
        analyze(linked)

    result = analyze(source, limits=PythonAnalysisLimits(max_graph_nodes=1))
    assert any("graph-node-limit" in item for item in result.graph.coverage_limits)


@pytest.mark.parametrize(
    ("rule_id", "imports", "sink", "safe_sink"),
    [
        (
            "fdai.python.command-injection",
            "import os\nimport shlex",
            "os.system(value)",
            "os.system(shlex.quote(value))",
        ),
        (
            "fdai.python.path-traversal",
            "import os",
            "open(value)",
            "open(os.path.basename(value))",
        ),
        (
            "fdai.python.xss",
            "import html\nfrom flask import render_template_string",
            "render_template_string(value)",
            "render_template_string(html.escape(value))",
        ),
    ],
)
def test_additional_weakness_rules_distinguish_vulnerable_and_safe_flows(
    tmp_path: Path,
    rule_id: str,
    imports: str,
    sink: str,
    safe_sink: str,
) -> None:
    selected = next(item for item in load_analysis_rules(CATALOG_ROOT) if item.rule_id == rule_id)
    vulnerable = tmp_path / "vulnerable"
    vulnerable.mkdir()
    write(
        vulnerable,
        "app.py",
        f"""
from flask import request
{imports}

@app.get('/input')
def route():
    value = request.args.get('value')
    return {sink}
""",
    )
    safe = tmp_path / "safe"
    safe.mkdir()
    write(
        safe,
        "app.py",
        f"""
from flask import request
{imports}

@app.get('/input')
def route():
    value = request.args.get('value')
    return {safe_sink}
""",
    )

    vulnerable_result = analyze_python_repository(
        vulnerable,
        revision=REVISION,
        build_context_digest=DIGEST,
        framework_model_digest=selected.digest(),
        rule=selected,
    )
    safe_result = analyze_python_repository(
        safe,
        revision=REVISION,
        build_context_digest=DIGEST,
        framework_model_digest=selected.digest(),
        rule=selected,
    )

    assert len(vulnerable_result.paths) == 1
    assert safe_result.paths == ()
