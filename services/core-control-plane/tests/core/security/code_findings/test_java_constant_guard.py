"""Constant veto regressions use only FDAI-authored Java snippets, never executed."""

from __future__ import annotations

from pathlib import Path

import pytest
from fdai.core.security.code_findings import java_constant_guard
from fdai.core.security.code_findings.canonical import AnalysisContext, build_issues
from fdai.core.security.code_findings.java_constant_guard import java_sql_constant_veto
from fdai.core.security.code_findings.models import Lane
from fdai.core.security.code_findings.sarif import SarifIngestContext, ingest_sarif
from fdai.core.security.code_findings.verifier import VerifierOutcome, taint_rule_verifications
from fdai.core.security.code_findings.verifier_evaluation import LabeledLocation, LocationOutcome
from fdai.delivery import code_security_verifier_eval as evaluation
from fdai.rule_catalog.code_security_verifiers import load_verifier_catalog

from ._support import CATALOG_ROOT, REVISION, catalog, result, sarif


def _source(body: str, helpers: str = "") -> str:
    return f"""class Example {{
void run(String input, boolean unknown) {{
{body}
db.executeQuery(sql); // sink
}}
{helpers}
}}
"""


def _veto(tmp_path: Path, source: str) -> str | None:
    path = tmp_path / "Example.java"
    path.write_text(source, encoding="utf-8")
    line = next(i for i, text in enumerate(source.splitlines(), 1) if "// sink" in text)
    return java_sql_constant_veto(tmp_path, path.name, line)


@pytest.mark.parametrize(
    ("body", "helpers"),
    [
        ('String sql = "SELECT 1";', ""),
        ('String a = "fixed"; String b = a; String sql = "SELECT " + b;', ""),
        ('int n = 4; String sql; if ((2 * 6) - n > 5) sql = "fixed"; else sql = input;', ""),
        ('String sql; if (2147483647 + 1 < 0) sql = "fixed"; else sql = input;', ""),
        ('String sql; if (2147483647L + 1 > 0) sql = "fixed"; else sql = input;', ""),
        ('String sql; if (-7 % 3 == -1) sql = "fixed"; else sql = input;', ""),
        ('String sql; if ((1 << 32) == 1) sql = "fixed"; else sql = input;', ""),
        ('String sql; if ((-1 >>> 1) == 2147483647) sql = "fixed"; else sql = input;', ""),
        ("String sql = fixed(input);", 'private static String fixed(String x) {return "fixed";}'),
        (
            "String sql = Example.fixed(input);",
            'private static String fixed(String x) {return "fixed";}',
        ),
        (
            "String sql = fixed(input);",
            """private static String fixed(String x) {
int n = 3; String result;
if (n * 4 > 8) result = "fixed"; else result = x;
return result;
}""",
        ),
        (
            "String sql = fixed(input);",
            """private static String fixed(String x) {
String selector = "LR"; char chosen = selector.charAt(1); String result;
switch (chosen) {
case 'L': result = x; break;
case 'R': result = "fixed"; break;
default: result = x;
}
return result;
}""",
        ),
        (
            "String sql = fixed(input);",
            """private static String fixed(String x) {
int n = 2; String result;
switch (n) {case 1: case 2: result = "fixed"; break; default: result = x;}
return result;
}""",
        ),
        (
            "String sql = fixed(input);",
            """private static String fixed(String x) {
if (2 > 1) return "fixed";
return x;
}""",
        ),
        (
            "String sql = new Cleaner().fixed(input);",
            """private class Cleaner {
public String fixed(String x) {
String result; int n = 2;
if (n == 2) result = "fixed"; else result = x;
return result;
}
}""",
        ),
    ],
)
def test_provably_constant_sql_has_source_bound_veto(
    tmp_path: Path, body: str, helpers: str
) -> None:
    proof = _veto(tmp_path, _source(body, helpers))
    assert proof is not None
    assert "source_sha256=" in proof and "fdai.java.constant-guard@1" in proof


@pytest.mark.parametrize(
    ("body", "helpers"),
    [
        ("String sql = input;", ""),
        ('String sql = "SELECT " + input;', ""),
        ('String sql = "SELECT " + unknownFunction(input);', ""),
        ('String sql = "fixed"; sql = input;', ""),
        ('String sql; if (unknown) sql = "fixed"; else sql = input;', ""),
        ('String sql = "fixed"; for (int i = 0; i < 2; i++) sql = input;', ""),
        ('int n = 1; n++; String sql; if (n == 1) sql = "fixed"; else sql = input;', ""),
        ("String sql = fixed(input);", 'public static String fixed(String x) {return "fixed";}'),
        (
            "String sql = fixed(input);",
            """private static String fixed(String x) {return "fixed";}
private static String fixed(Object x) {return "fixed";}""",
        ),
        (
            "String sql = fixed(input);",
            """String state;
private static String fixed(String x) {state = x; return "fixed";}""",
        ),
        (
            "String sql = fixed(input);",
            """private static String fixed(String x) {
unknownFunction(x);
return "fixed";
}""",
        ),
        (
            "String sql = fixed(input);",
            """private static String fixed(String x) {
String result; int n = 1;
switch (n) {case 1: result = "fixed"; case 2: result = x; break; default: result = x;}
return result;
}""",
        ),
        (
            "String sql = fixed(input);",
            """private static String fixed(String x) {
String result; int n = 1;
switch (n) {case 1: if (x != null) break; result = "fixed"; break; default: result = x;}
return result;
}""",
        ),
        (
            "Cleaner c = new Cleaner(); String sql = c.fixed(input);",
            """private class Cleaner {
public String fixed(String x) {return "fixed";}
}""",
        ),
        (
            "String sql = new Cleaner().fixed(input);",
            """private class Cleaner {
Cleaner() {unknownFunction();}
public String fixed(String x) {return "fixed";}
}""",
        ),
        (
            "String sql = new Cleaner().fixed(input);",
            """private class Cleaner extends External {
public String fixed(String x) {return "fixed";}
}""",
        ),
        (
            "String sql = new Cleaner() {public String fixed(String x) {return x;}}.fixed(input);",
            'private class Cleaner {public String fixed(String x) {return "fixed";}}',
        ),
        (
            "String sql = Example.fixed(input);",
            """External Example;
private static String fixed(String x) {return "fixed";}
""",
        ),
        (
            "External Example = external; String sql = Example.fixed(input);",
            'private static String fixed(String x) {return "fixed";}',
        ),
        ('String sql = "fixed"; label: {break label;} sql = input;', ""),
        ('String sql = "fixed"; try {sql = input;} catch (Exception e) {}', ""),
        ("String sql = input;", 'private static String unrelated(String x) {return "fixed";}'),
        (
            "String sql = fixed(input);",
            """private static String fixed(String x) {
return fixed(x);
}""",
        ),
        (
            "String sql = fixed(input);",
            """private static String fixed(String x) {
String selector = "AB"; String result;
switch (selector.charAt(99)) {case 'A': result = "fixed"; break; default: result = x;}
return result;
}""",
        ),
        (
            "String sql = fixed(input);",
            """private static String fixed(String x) {
String selector = "😀R"; String result;
switch (selector.charAt(1)) {case 'R': result = "fixed"; break; default: result = x;}
return result;
}""",
        ),
    ],
)
def test_unknown_or_mutating_flows_keep_engine_evidence(
    tmp_path: Path, body: str, helpers: str
) -> None:
    assert _veto(tmp_path, _source(body, helpers)) is None


def test_ambiguous_same_line_sinks_do_not_hide_unknown_flow(tmp_path: Path) -> None:
    source = """class Example {void run(String input) {
String sql = "fixed";
db.executeQuery(sql); db.executeQuery(input); // sink
}}"""
    assert _veto(tmp_path, source) is None


def test_unicode_prelexing_escape_cannot_hide_an_assignment(tmp_path: Path) -> None:
    source = _source('String sql = "fixed"; // ' + "\\u000a" + " sql = input;")
    assert _veto(tmp_path, source) is None


def test_loop_backedge_write_after_sink_keeps_engine_evidence(tmp_path: Path) -> None:
    source = """class Example {void run(String input, boolean unknown) {
String sql = "fixed";
while (unknown) {
db.executeQuery(sql); // sink
sql = input;
}
}}"""
    assert _veto(tmp_path, source) is None


def test_malformed_oversized_and_escaping_sources_never_veto(tmp_path: Path) -> None:
    source = _source('String sql = "fixed";')
    path = tmp_path / "Example.java"
    path.write_text(source)
    assert java_sql_constant_veto(tmp_path, path.name, 4, max_file_bytes=10) is None
    path.write_text("class {")
    assert java_sql_constant_veto(tmp_path, path.name, 1) is None
    assert java_sql_constant_veto(tmp_path, "missing.java", 1) is None
    root = tmp_path / "root"
    root.mkdir()
    (root / "escape.java").symlink_to(path)
    assert java_sql_constant_veto(root, "escape.java", 1) is None


def test_parser_deadline_failure_leaves_engine_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def deadline(source: bytes) -> None:
        raise ValueError("Parsing failed")

    monkeypatch.setattr(java_constant_guard, "_Slice", deadline)
    assert _veto(tmp_path, _source('String sql = "fixed";')) is None


@pytest.mark.parametrize("constant", [True, False])
def test_runtime_and_evaluation_share_veto_without_dropping_base_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, constant: bool
) -> None:
    source = _source('String sql = "fixed";' if constant else "String sql = input;")
    path = tmp_path / "Example.java"
    path.write_text(source)
    line = next(i for i, text in enumerate(source.splitlines(), 1) if "// sink" in text)
    rule = "fdai.verify.java.sql-injection"
    occurrences = ingest_sarif(
        sarif("Opengrep", [result(rule, path.name, line, cwe=89)]),
        SarifIngestContext(lane=Lane.DETERMINISTIC, revision=REVISION),
    ).occurrences
    issues = build_issues(occurrences, catalog(), AnalysisContext(revision=REVISION))
    shipped = load_verifier_catalog(CATALOG_ROOT, frozenset(catalog().weakness_classes.classes))
    promoted = shipped.model_copy(
        update={"promotion": shipped.promotion.model_copy(update={"promoted": (rule,)})}
    )
    (verdict,) = taint_rule_verifications(issues, occurrences, promoted, repository=tmp_path)
    assert len(issues) == 1
    assert verdict.outcome is (
        VerifierOutcome.NOT_VERIFIED if constant else VerifierOutcome.VERIFIED
    )
    assert verdict.reason == (
        "argument_provably_constant" if constant else "attacker_controlled_flow"
    )
    monkeypatch.setattr(
        evaluation,
        "_engine_scan",
        lambda *args: {
            "results": [{"check_id": rule, "path": path.name, "start": {"line": line}}],
            "errors": [],
        },
    )
    label = LabeledLocation("fixture", path.name, line, "sql_injection", "taint", not constant)
    vetoes: list[dict[str, object]] = []
    outcomes, _ = evaluation._taint_outcomes(
        "unused", CATALOG_ROOT / "rules" / "verify", tmp_path, [label], vetoes=vetoes
    )
    assert outcomes[label] is (
        LocationOutcome.NOT_VERIFIED if constant else LocationOutcome.VERIFIED
    )
    assert bool(vetoes) is constant
    if constant:
        assert vetoes[0]["reason"] == verdict.reason
        assert str(vetoes[0]["proof"]) in str(verdict.source)


def test_promoted_java_sql_requires_exact_source_binding(tmp_path: Path) -> None:
    rule = "fdai.verify.java.sql-injection"
    occurrences = ingest_sarif(
        sarif("Opengrep", [result(rule, "Example.java", 1, cwe=89)]),
        SarifIngestContext(lane=Lane.DETERMINISTIC, revision=REVISION),
    ).occurrences
    issues = build_issues(occurrences, catalog(), AnalysisContext(revision=REVISION))
    shipped = load_verifier_catalog(CATALOG_ROOT, frozenset(catalog().weakness_classes.classes))
    promoted = shipped.model_copy(
        update={"promotion": shipped.promotion.model_copy(update={"promoted": (rule,)})}
    )
    (verdict,) = taint_rule_verifications(issues, occurrences, promoted)
    assert verdict.outcome is VerifierOutcome.NOT_VERIFIED
    assert verdict.reason == "java_constant_guard_source_unavailable"


def test_promoted_java_sql_requires_a_fix_site_line(tmp_path: Path) -> None:
    rule = "fdai.verify.java.sql-injection"
    finding = result(rule, "Example.java", 1, cwe=89)
    finding["locations"][0]["physicalLocation"].pop("region")
    occurrences = ingest_sarif(
        sarif("Opengrep", [finding]),
        SarifIngestContext(lane=Lane.DETERMINISTIC, revision=REVISION),
    ).occurrences
    issues = build_issues(occurrences, catalog(), AnalysisContext(revision=REVISION))
    shipped = load_verifier_catalog(CATALOG_ROOT, frozenset(catalog().weakness_classes.classes))
    promoted = shipped.model_copy(
        update={"promotion": shipped.promotion.model_copy(update={"promoted": (rule,)})}
    )
    (verdict,) = taint_rule_verifications(issues, occurrences, promoted, repository=tmp_path)
    assert verdict.outcome is VerifierOutcome.NOT_VERIFIED
    assert verdict.reason == "java_constant_guard_fix_site_unavailable"
