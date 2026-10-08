"""Tests for the JavaScript, native, Java, and C# proof harnesses and their sandbox isolation."""

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
_JAVA = shutil.which("java")
_DOTNET = shutil.which("dotnet")
needs_node = pytest.mark.skipif(
    not sandbox_available() or _NODE is None, reason="bubblewrap or Node.js unavailable"
)
needs_java = pytest.mark.skipif(
    not sandbox_available()
    or _JAVA is None
    or not (Path(_JAVA).resolve().parent / "javac").exists()
    or not _PYTHON.exists(),
    reason="bubblewrap, a JDK, or system python unavailable",
)
needs_dotnet = pytest.mark.skipif(
    not sandbox_available() or _DOTNET is None or not _PYTHON.exists(),
    reason="bubblewrap, the .NET SDK, or system python unavailable",
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
    assert proof_language("src/App.java").name == "java"  # type: ignore[union-attr]
    assert proof_language("src/Tools.cs").name == "csharp"  # type: ignore[union-attr]
    assert proof_language("routes/app.mjs") is None
    assert proof_language("src/App.kt") is None


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


_JAVA_TOOLS = """package demo;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;

public class Tools {
    public static void ping(String host) throws IOException {
        Runtime.getRuntime().exec(new String[] {"sh", "-c", "ping -c 1 " + host});
    }

    public static void pingSafe(String host) throws IOException {
        new ProcessBuilder("ping", "-c", "1", host).start();
    }

    public static byte[] read(String name) throws IOException {
        return Files.readAllBytes(Path.of("/srv/files/" + name));
    }

    public static byte[] readSafe(String name) throws IOException {
        return Files.readAllBytes(Path.of("/srv/files", new File(name).getName()));
    }

    public static void rows(Connection connection, String name) throws SQLException {
        connection.createStatement().executeQuery("SELECT * FROM t WHERE name = '" + name + "'");
    }

    public static void rowsSafe(Connection connection, String name) throws SQLException {
        PreparedStatement statement = connection.prepareStatement("SELECT * FROM t WHERE name = ?");
        statement.setString(1, name);
        statement.executeQuery();
    }

    public static void touch(String value) throws IOException {
        Runtime.getRuntime().exec(new String[] {"sh", "-c", "touch created-by-proof; " + value});
    }

    public static void pingBuilder(String host) throws IOException {
        new ProcessBuilder("sh", "-c", "ping -c 1 " + host).start();
    }

    public static void log(String body) throws IOException {
        Files.writeString(Path.of("/srv/app.log"), body);
    }

    public static void count(String pattern) throws IOException {
        new ProcessBuilder("grep", "-c", pattern + " /srv/app.log").start();
    }

    public static void grepPositional(String name) throws IOException {
        Runtime.getRuntime().exec(new String[] {"sh", "-c", "grep -- \\"$1\\" f", "sh", name});
    }
}
"""

_JAVA_CASES = {
    "ping": (13, 78, True),
    "ping_safe": (17, 78, False),
    "read": (21, 22, True),
    "read_safe": (25, 22, False),
    "rows": (29, 89, True),
    "rows_safe": (33, 89, False),
    "touch": (39, 78, True),
    "ping_builder": (43, 78, True),
    "log_contents": (47, 22, False),
    "count_without_shell": (51, 78, False),
    "positional_parameter": (55, 78, False),
}

_CSHARP_TOOLS = """using System.Data;
using System.Diagnostics;
using System.IO;

namespace Demo
{
    public static class Tools
    {
        public static void Ping(string host)
        {
            Process.Start("/bin/sh", "-c \\"ping -c 1 " + host + "\\"");
        }

        public static void PingSafe(string host)
        {
            var info = new ProcessStartInfo("ping");
            info.ArgumentList.Add(host);
            Process.Start(info);
        }

        public static string Read(string name)
        {
            return File.ReadAllText("/srv/files/" + name);
        }

        public static string ReadSafe(string name)
        {
            return File.ReadAllText(Path.Combine("/srv/files", Path.GetFileName(name)));
        }

        public static void Rows(IDbConnection connection, string name)
        {
            var command = connection.CreateCommand();
            command.CommandText = "SELECT * FROM t WHERE name = '" + name + "'";
        }

        public static void RowsSafe(IDbConnection connection, string name)
        {
            var command = connection.CreateCommand();
            command.CommandText = "SELECT * FROM t WHERE name = @name";
        }

        public static void Touch(string value)
        {
            var info = new ProcessStartInfo { FileName = "/bin/sh" };
            info.Arguments = "-c \\"touch created-by-proof; " + value + "\\"";
            Process.Start(info);
        }

        public static void Count(string pattern)
        {
            Process.Start("grep", "-c " + pattern + " /srv/app.log");
        }

        public static void Log(string text)
        {
            File.WriteAllText("/srv/app.log", text);
        }

        public static void GrepPositional(string name)
        {
            Process.Start("sh", new[] { "-c", "grep -- \\"$1\\" f", "sh", name });
        }

        public static void EchoQuoted(string name)
        {
            var info = new ProcessStartInfo("sh");
            info.ArgumentList.Add("-c");
            info.ArgumentList.Add("echo \\"" + name + "\\"");
            Process.Start(info);
        }
    }
}
"""

_CSHARP_CASES = {
    "ping": (11, 78, True),
    "ping_safe": (17, 78, False),
    "read": (23, 22, True),
    "read_safe": (28, 22, False),
    "rows": (34, 89, True),
    "rows_safe": (40, 89, False),
    "touch": (46, 78, True),
    "count_without_shell": (52, 78, False),
    "log_contents": (57, 22, False),
    "positional_parameter": (62, 78, False),
    "quoted_list_element": (69, 78, False),
}


def _prove_managed(
    tmp_path: Path,
    path: str,
    text: str,
    cases: dict[str, tuple[int, int, bool]],
    runtimes: dict[str, Path],
    timeout_seconds: int = 300,
) -> tuple[Path, list[CodeSecurityIssue], tuple[object, ...]]:
    source = tmp_path / "source"
    (source / path).parent.mkdir(parents=True, exist_ok=True)
    (source / path).write_text(text, encoding="utf-8")
    issues = build_issues(
        _occurrences(path, cases, Lane.DETERMINISTIC), _CATALOG, AnalysisContext(revision=_REVISION)
    )
    lines = text.splitlines()
    assert len(issues) == len(cases), [lines[line - 1] for line, _, _ in cases.values()]
    results = asyncio.run(
        prove_issues(
            source,
            issues,
            _verified(issues),
            sandbox=BubblewrapScannerSandbox(),
            python=_PYTHON,
            runtimes=runtimes,
            timeout_seconds=timeout_seconds,
        )
    )
    return source, issues, results


def test_managed_targets_exclude_classes_without_a_hooked_sink() -> None:
    issues = build_issues(
        _occurrences(
            "src/App.java", {"code": (3, 95, True), "cmd": (5, 78, True)}, Lane.DETERMINISTIC
        ),
        _CATALOG,
        AnalysisContext(revision=_REVISION),
    )
    targets = proof_targets(issues, _verified(issues), ("java",))
    assert [target["weakness_class"] for target in targets] == ["command_injection"]
    assert proof_targets(issues, (), ("java",)) == []


@needs_java
def test_java_sandbox_proves_vulnerable_flows_and_refuses_safe_ones(tmp_path: Path) -> None:
    source, issues, results = _prove_managed(
        tmp_path,
        "src/main/java/demo/Tools.java",
        _JAVA_TOOLS,
        _JAVA_CASES,
        {"java": Path(str(_JAVA)).resolve()},
    )
    by_line = _by_line(issues, results)
    for name, (line, _, vulnerable) in _JAVA_CASES.items():
        outcome = getattr(by_line[line], "outcome", None)
        assert outcome == ("proven" if vulnerable else "not_proven"), (name, by_line[line])
        if not vulnerable:
            assert getattr(by_line[line], "reason", None) == "canary_not_observed", by_line[line]
    assert not list(source.rglob("created-by-proof"))


@needs_dotnet
def test_csharp_sandbox_proves_vulnerable_flows_and_refuses_safe_ones(tmp_path: Path) -> None:
    source, issues, results = _prove_managed(
        tmp_path,
        "src/Tools.cs",
        _CSHARP_TOOLS,
        _CSHARP_CASES,
        {"csharp": Path(str(_DOTNET)).resolve()},
    )
    by_line = _by_line(issues, results)
    for name, (line, _, vulnerable) in _CSHARP_CASES.items():
        outcome = getattr(by_line[line], "outcome", None)
        assert outcome == ("proven" if vulnerable else "not_proven"), (name, by_line[line])
        if not vulnerable:
            assert getattr(by_line[line], "reason", None) == "canary_not_observed", by_line[line]
    assert not list(source.rglob("created-by-proof"))


@needs_dotnet
def test_csharp_file_with_project_dependencies_stays_unproven(tmp_path: Path) -> None:
    text = (
        "using Microsoft.Data.SqlClient;\n"
        "public static class Rows {\n"
        "    public static void Run(SqlConnection c, string n) {\n"
        '        new SqlCommand("SELECT * FROM t WHERE n = \'" + n + "\'", c).ExecuteReader();\n'
        "    }\n"
        "}\n"
    )
    _, _, results = _prove_managed(
        tmp_path, "Rows.cs", text, {"rows": (4, 89, True)}, {"csharp": Path(str(_DOTNET)).resolve()}
    )
    assert [(r.outcome, r.reason) for r in results] == [("not_proven", "compile_failed")]  # type: ignore[attr-defined]


@needs_java
def test_java_harness_timeouts_leave_targets_unproven(tmp_path: Path) -> None:
    methods = "\n".join(
        f"    public static void run{index}(String v) throws Exception "
        "{ Runtime.getRuntime().exec(v); }"
        for index in range(8)
    )
    text = (
        "public class Spin {\n    static { spin(); }\n"
        f"{methods}\n    static void spin() {{ while (true) {{ }} }}\n}}\n"
    )
    _, _, results = _prove_managed(
        tmp_path,
        "Spin.java",
        text,
        {"spin": (3, 78, True)},
        {"java": Path(str(_JAVA)).resolve()},
        timeout_seconds=10,
    )
    assert [(r.outcome, r.reason) for r in results] == [("not_proven", "timed_out")]  # type: ignore[attr-defined]


def test_driven_toolchains_outside_the_sandbox_mounts_are_unavailable(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "App.java").write_text(_JAVA_TOOLS, encoding="utf-8")
    issues = build_issues(
        _occurrences("App.java", {"ping": (13, 78, True)}, Lane.DETERMINISTIC),
        _CATALOG,
        AnalysisContext(revision=_REVISION),
    )
    results = asyncio.run(
        prove_issues(
            source,
            issues,
            _verified(issues),
            sandbox=BubblewrapScannerSandbox(),
            python=_PYTHON,
            runtimes={"java": tmp_path / "jdk" / "bin" / "java"},
        )
    )
    assert [(r.outcome, r.reason) for r in results] == [("not_proven", "runtime_unavailable")]


def test_sandbox_exposes_only_named_etc_configuration_directories(tmp_path: Path) -> None:
    from fdai.rule_catalog.code_security_scanners import ScannerSpec

    spec = ScannerSpec(
        producer="fdai-prove-java",
        argv=("{source}",),
        success_exit_codes=(0,),
        timeout_seconds=10,
        max_output_bytes=1_000,
    )
    sandbox = BubblewrapScannerSandbox()
    argv = sandbox.command(spec, _PYTHON, tmp_path, system_config=(Path("/etc/java-21-openjdk"),))
    assert argv[argv.index("/etc/java-21-openjdk") - 1] == "--ro-bind-try"
    for refused in (Path("/etc"), Path("/home/user/conf"), Path("/etc/a/b")):
        with pytest.raises(ValueError, match="/etc/<name>"):
            sandbox.command(spec, _PYTHON, tmp_path, system_config=(refused,))
