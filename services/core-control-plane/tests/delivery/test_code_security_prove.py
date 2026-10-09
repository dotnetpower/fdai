"""Tests for the opt-in proof lane: targets, output parsing, predicates, and sandbox runs."""

from __future__ import annotations

import asyncio
import json
import shlex
from pathlib import Path

import pytest
from fdai.core.security.code_findings.canonical import AnalysisContext, build_issues
from fdai.core.security.code_findings.models import Lane, Occurrence, SourceLocation
from fdai.core.security.code_findings.verifier import VerifierOutcome, VerifierResult
from fdai.delivery.code_security_prove import (
    parse_proof_output,
    proof_targets,
    prove_issues,
    proven_confidence,
)
from fdai.delivery.code_security_sandbox import BubblewrapScannerSandbox, sandbox_available
from fdai.rule_catalog.code_security import Confidence, load_code_security_catalog

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _load_harness():  # type: ignore[no-untyped-def]
    import importlib.util

    path = _REPO_ROOT / "rule-catalog" / "code-security" / "prove" / "fdai_prove.py"
    spec = importlib.util.spec_from_file_location("fdai_prove_harness_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


harness = _load_harness()
_CATALOG = load_code_security_catalog(_REPO_ROOT / "rule-catalog" / "code-security")
_REVISION = "a" * 40
_PYTHON = Path("/usr/bin/python3")
needs_sandbox = pytest.mark.skipif(
    not sandbox_available() or not _PYTHON.exists(),
    reason="unprivileged bubblewrap or system python unavailable",
)

_APP = """import os
import pickle
import shlex
import sqlite3
import subprocess
from flask import Flask, request

app = Flask(__name__)


@app.route("/ping")
def ping():
    host = request.args.get("host")
    return subprocess.run("ping -c 1 " + host, shell=True)


@app.route("/ping-safe")
def ping_safe():
    host = request.args.get("host")
    return subprocess.run("ping -c 1 " + shlex.quote(host), shell=True)


@app.route("/calc")
def calc():
    return eval(request.form["expression"])


@app.route("/calc-safe")
def calc_safe():
    return eval(repr(request.form["expression"]))


@app.route("/restore", methods=["POST"])
def restore():
    return pickle.loads(request.get_data())


@app.route("/orders")
def orders():
    connection = sqlite3.connect(":memory:")
    name = request.args["name"]
    return connection.execute("SELECT * FROM orders WHERE name = '" + name + "'")


@app.route("/orders-safe")
def orders_safe():
    connection = sqlite3.connect(":memory:")
    return connection.execute("SELECT * FROM orders WHERE name = ?", (request.args["name"],))


@app.route("/files")
def files():
    return open("/srv/files/" + request.args["name"]).read()


@app.route("/files-safe")
def files_safe():
    return open("/srv/files/" + os.path.basename(request.args["name"])).read()
"""

_CASES = {
    "ping": (14, 78, True),
    "ping_safe": (20, 78, False),
    "calc": (25, 95, True),
    "calc_safe": (30, 95, False),
    "restore": (35, 502, True),
    "orders": (42, 89, True),
    "orders_safe": (48, 89, False),
    "files": (53, 22, True),
    "files_safe": (58, 22, False),
}


def _issues(tmp_path: Path):  # type: ignore[no-untyped-def]
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text(_APP, encoding="utf-8")
    lines = _APP.splitlines()
    occurrences = []
    for name, (line, cwe, _) in _CASES.items():
        assert lines[line - 1].strip().startswith(("return", "host")), (name, lines[line - 1])
        occurrences.append(
            Occurrence(
                occurrence_id=name,
                producer="Opengrep",
                producer_version="1",
                lane=Lane.DETERMINISTIC,
                scan_digest="sha256:x",
                revision=_REVISION,
                rule_id=name,
                location=SourceLocation("app.py", line),
                cwe_ids=(cwe,),
            )
        )
    issues = build_issues(occurrences, _CATALOG, AnalysisContext(revision=_REVISION))
    verified = tuple(
        VerifierResult(issue.issue_id, VerifierOutcome.VERIFIED, "test", "test") for issue in issues
    )
    return source, issues, verified


def test_payload_predicates_require_an_exploitable_shape() -> None:
    harness._ACTIVE[0] = "command_injection"
    assert harness.tainted("ping -c 1 x;FDAICANARYXY")
    assert not harness.tainted("ping -c 1 " + shlex.quote("x;FDAICANARYXY"))
    harness._ACTIVE[0] = "code_injection"
    assert harness.tainted("FDAICANARYXY")
    assert not harness.tainted(repr("FDAICANARYXY"))
    harness._ACTIVE[0] = "sql_injection"
    assert harness.tainted("WHERE name = 'x'FDAICANARYXY'")
    assert not harness.tainted("WHERE name = 'x''FDAICANARYXY'")
    harness._ACTIVE[0] = "path_traversal"
    assert harness.tainted("/srv/files/../../FDAICANARYXY")
    assert not harness.tainted("/srv/files/FDAICANARYXY")


def test_targets_are_verified_python_issues_in_provable_classes(tmp_path: Path) -> None:
    _, issues, verified = _issues(tmp_path)
    targets = proof_targets(issues, verified[:3])
    assert {t["issue_id"] for t in targets} == {r.issue_id for r in verified[:3]}
    shadow = [
        VerifierResult(r.issue_id, VerifierOutcome.NOT_VERIFIED, "verifier_in_shadow", "v")
        for r in verified
    ]
    assert proof_targets(issues, shadow) == []


def test_output_parsing_ignores_noise_and_unknown_targets() -> None:
    targets = [{"issue_id": "FDAI-SEC-000000000001"}, {"issue_id": "FDAI-SEC-000000000002"}]
    stdout = (
        b"noise\n"
        b'{"issue_id": "FDAI-SEC-000000000001", "outcome": "proven", "reason": "r",'
        b' "sink": "eval"}\n'
        b'{"issue_id": "FDAI-SEC-000000000001", "outcome": "not_proven", "reason": "dup"}\n'
        b'{"issue_id": "FDAI-SEC-999999999999", "outcome": "proven", "reason": "spoof"}\n'
    )
    results = {r.issue_id: r for r in parse_proof_output(stdout, targets)}
    assert results["FDAI-SEC-000000000001"].outcome == "proven"
    assert results["FDAI-SEC-000000000002"].reason == "no_result"
    assert "FDAI-SEC-999999999999" not in results
    assert proven_confidence(list(results.values())) == {"FDAI-SEC-000000000001": Confidence.PROVEN}


@pytest.mark.parametrize("field", ["issue_id", "outcome"])
@pytest.mark.parametrize("value", [[], {}, None, False, 0, ["controlled-id"]])
def test_non_string_proof_identity_or_outcome_cannot_crash_or_raise_confidence(
    field: str, value: object
) -> None:
    targets = [{"issue_id": "controlled-id"}]
    malformed: dict[str, object] = {"issue_id": "controlled-id", "outcome": "proven"}
    malformed[field] = value
    invalid_line = json.dumps(malformed).encode() + b"\n"
    results = parse_proof_output(invalid_line, targets)
    assert [(result.outcome, result.reason) for result in results] == [("not_proven", "no_result")]
    assert proven_confidence(results) == {}
    valid_line = b'{"issue_id":"controlled-id","outcome":"proven","reason":"controlled"}\n'
    recovered = parse_proof_output(invalid_line + valid_line, targets)
    assert [(result.outcome, result.reason) for result in recovered] == [("proven", "controlled")]


@needs_sandbox
def test_sandbox_proves_vulnerable_flows_and_refuses_safe_ones(tmp_path: Path) -> None:
    source, issues, verified = _issues(tmp_path)
    results = asyncio.run(
        prove_issues(
            source,
            issues,
            verified,
            sandbox=BubblewrapScannerSandbox(),
            python=_PYTHON.resolve(),
        )
    )
    by_line = {
        issue.fix_site.start_line: next(r for r in results if r.issue_id == issue.issue_id)
        for issue in issues
    }
    for name, (line, _, vulnerable) in _CASES.items():
        outcome = by_line[line].outcome
        assert outcome == ("proven" if vulnerable else "not_proven"), (name, by_line[line])
