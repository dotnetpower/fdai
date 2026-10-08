"""Tests for the JavaScript and native proof harnesses and their sandbox isolation."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest
from fdai.core.security.code_findings.canonical import AnalysisContext, build_issues
from fdai.core.security.code_findings.models import (
    CodeSecurityIssue,
    Lane,
    Occurrence,
    SourceLocation,
)
from fdai.core.security.code_findings.verifier import VerifierOutcome, VerifierResult
from fdai.delivery.code_security_prove import proof_language, proof_targets, prove_issues
from fdai.delivery.code_security_sandbox import BubblewrapScannerSandbox, sandbox_available
from fdai.rule_catalog.code_security import load_code_security_catalog

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CATALOG = load_code_security_catalog(_REPO_ROOT / "rule-catalog" / "code-security")
_REVISION = "b" * 40
_PYTHON = Path("/usr/bin/python3")
_NODE = shutil.which("node")
_GCC = shutil.which("gcc")
needs_node = pytest.mark.skipif(
    not sandbox_available() or _NODE is None, reason="bubblewrap or Node.js unavailable"
)
needs_gcc = pytest.mark.skipif(
    not sandbox_available() or _GCC is None or not _PYTHON.exists(),
    reason="bubblewrap, gcc, or system python unavailable",
)

_ROUTES = """const express = require('express');
const { exec, execFile, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const router = express.Router();
router.get('/ping', (req, res) => {
  exec('ping -c 1 ' + req.query.host, () => res.send('ok'));
});
router.get('/ping-safe', (req, res) => {
  execFile('ping', ['-c', '1', req.query.host], () => res.send('ok'));
});
router.post('/calc', (req, res) => {
  res.send(String(eval(req.body.expr)));
});
router.post('/calc-safe', (req, res) => {
  res.send(String(Number(req.body.expr)));
});
router.get('/file', (req, res) => {
  res.send(fs.readFileSync('/srv/files/' + req.query.name));
});
router.get('/file-safe', (req, res) => {
  res.send(fs.readFileSync(path.join('/srv/files', path.basename(req.query.name))));
});
router.post('/rows', (req, res) => {
  db.query("SELECT * FROM t WHERE name = '" + req.body.name + "'");
});
router.post('/rows-safe', (req, res) => {
  db.query('SELECT * FROM t WHERE name = ?', [req.body.name]);
});
router.post('/touch', (req, res) => {
  execSync('touch ' + __dirname + '/created-by-proof; ' + req.body.cmd);
});
function Handler() {
  this.update = (req, res) => {
    const value = eval(req.body.value);
    const other = eval(req.body.other);
    res.send(value + other);
  };
}
const db = require('mysql').createConnection({});
module.exports = { router, Handler };
"""

_JS_CASES = {
    "ping": (7, 78, True),
    "ping_safe": (10, 78, False),
    "calc": (13, 95, True),
    "calc_safe": (16, 95, False),
    "file": (19, 22, True),
    "file_safe": (22, 22, False),
    "rows": (25, 89, True),
    "rows_safe": (28, 89, False),
    "touch": (31, 78, True),
    "handler_first": (35, 95, True),
    "handler_second": (36, 95, True),
}

_NATIVE = """#include <string.h>
#include <stddef.h>

void copy_name(const char *input, size_t length) {
    char name[16];
    memcpy(name, input, length);
    (void)name;
}

void copy_name_checked(const char *input, size_t length) {
    char name[16];
    if (length > sizeof(name)) length = sizeof(name);
    memcpy(name, input, length);
    (void)name;
}

int parse(int a, int b, int c) {
    char name[4];
    name[a] = 0;
    return b + c;
}

int main(void) { return 0; }
"""

_NATIVE_CASES = {"copy": (6, 787, True), "checked": (13, 787, False), "parse": (19, 787, False)}


def _occurrences(
    path: str, cases: dict[str, tuple[int, int, bool]], lane: Lane
) -> list[Occurrence]:
    return [
        Occurrence(
            occurrence_id=name,
            producer="Opengrep" if lane is Lane.DETERMINISTIC else "fdai-lens",
            producer_version="1",
            lane=lane,
            scan_digest="sha256:x",
            revision=_REVISION,
            rule_id=name,
            location=SourceLocation(path, line),
            cwe_ids=(cwe,),
        )
        for name, (line, cwe, _) in cases.items()
    ]


def _verified(issues: Sequence[CodeSecurityIssue]) -> tuple[VerifierResult, ...]:
    return tuple(
        VerifierResult(issue.issue_id, VerifierOutcome.VERIFIED, "test", "test") for issue in issues
    )


def _by_line(issues: Sequence[CodeSecurityIssue], results: Sequence[object]) -> dict[int, object]:
    return {
        issue.fix_site.start_line or 0: next(
            r for r in results if getattr(r, "issue_id", None) == issue.issue_id
        )
        for issue in issues
    }


def test_languages_follow_the_fix_site_extension() -> None:
    assert proof_language("app/views.py").name == "python"  # type: ignore[union-attr]
    assert proof_language("routes/app.js").name == "javascript"  # type: ignore[union-attr]
    assert proof_language("src/parse.cc").name == "native"  # type: ignore[union-attr]
    assert proof_language("src/App.java") is None
    assert proof_language("routes/app.mjs") is None


def test_targets_need_an_enabled_language_and_native_needs_a_reported_lane() -> None:
    js = build_issues(
        _occurrences("routes/app.js", _JS_CASES, Lane.DETERMINISTIC),
        _CATALOG,
        AnalysisContext(revision=_REVISION),
    )
    assert proof_targets(js, _verified(js)) == []
    assert len(proof_targets(js, _verified(js), ("javascript",))) == len(js)
    assert proof_targets(js, (), ("javascript",)) == []
    reported = build_issues(
        _occurrences("src/buf.c", _NATIVE_CASES, Lane.DETERMINISTIC),
        _CATALOG,
        AnalysisContext(revision=_REVISION),
    )
    assert len(proof_targets(reported, (), ("native",))) == len(reported)
    lens_only = build_issues(
        _occurrences("src/buf.c", _NATIVE_CASES, Lane.LLM_LENS),
        _CATALOG,
        AnalysisContext(revision=_REVISION),
    )
    assert proof_targets(lens_only, _verified(lens_only), ("native",)) == []


@needs_node
def test_javascript_sandbox_proves_vulnerable_flows_and_refuses_safe_ones(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "routes").mkdir(parents=True)
    (source / "routes" / "app.js").write_text(_ROUTES, encoding="utf-8")
    lines = _ROUTES.splitlines()
    issues = build_issues(
        _occurrences("routes/app.js", _JS_CASES, Lane.DETERMINISTIC),
        _CATALOG,
        AnalysisContext(revision=_REVISION),
    )
    assert len(issues) == len(_JS_CASES), [lines[line - 1] for line, _, _ in _JS_CASES.values()]
    results = asyncio.run(
        prove_issues(
            source,
            issues,
            _verified(issues),
            sandbox=BubblewrapScannerSandbox(),
            runtimes={"javascript": Path(str(_NODE)).resolve()},
        )
    )
    by_line = _by_line(issues, results)
    for name, (line, _, vulnerable) in _JS_CASES.items():
        outcome = getattr(by_line[line], "outcome", None)
        assert outcome == ("proven" if vulnerable else "not_proven"), (name, by_line[line])
    assert not (source / "routes" / "created-by-proof").exists()


@needs_node
def test_javascript_harness_timeouts_leave_targets_unproven(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "spin.js").write_text("while (true) {}\nexports.run = (x) => eval(x);\n")
    issues = build_issues(
        _occurrences("spin.js", {"spin": (2, 95, True)}, Lane.DETERMINISTIC),
        _CATALOG,
        AnalysisContext(revision=_REVISION),
    )
    results = asyncio.run(
        prove_issues(
            source,
            issues,
            _verified(issues),
            sandbox=BubblewrapScannerSandbox(),
            runtimes={"javascript": Path(str(_NODE)).resolve()},
            timeout_seconds=10,
        )
    )
    assert [(r.outcome, r.reason) for r in results] == [("not_proven", "timed_out")]


@needs_gcc
def test_native_sandbox_proves_an_overflow_at_the_fix_site_only(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "src").mkdir(parents=True)
    (source / "src" / "buf.c").write_text(_NATIVE, encoding="utf-8")
    issues = build_issues(
        _occurrences("src/buf.c", _NATIVE_CASES, Lane.DETERMINISTIC),
        _CATALOG,
        AnalysisContext(revision=_REVISION),
    )
    results = asyncio.run(
        prove_issues(
            source,
            issues,
            (),
            sandbox=BubblewrapScannerSandbox(),
            python=_PYTHON,
            runtimes={"native": Path(str(_GCC)).resolve()},
        )
    )
    by_line = _by_line(issues, results)
    assert getattr(by_line[6], "outcome", None) == "proven", by_line[6]
    assert str(getattr(by_line[6], "sink", "")).startswith("asan:stack-buffer-overflow")
    assert getattr(by_line[13], "reason", None) == "no_report_at_fix_site"
    assert getattr(by_line[19], "reason", None) == "unsupported_signature"


@needs_gcc
def test_native_harness_needs_an_interpreter(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "buf.c").write_text(_NATIVE, encoding="utf-8")
    issues = build_issues(
        _occurrences("buf.c", {"copy": (6, 787, True)}, Lane.DETERMINISTIC),
        _CATALOG,
        AnalysisContext(revision=_REVISION),
    )
    results = asyncio.run(
        prove_issues(
            source,
            issues,
            (),
            sandbox=BubblewrapScannerSandbox(),
            runtimes={"native": Path(str(_GCC)).resolve()},
        )
    )
    assert [(r.outcome, r.reason) for r in results] == [("not_proven", "no_interpreter")]
