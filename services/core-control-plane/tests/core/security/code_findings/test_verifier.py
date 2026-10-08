"""Tests for the deterministic weakness verifiers (synthetic sources, never executed)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from fdai.core.security.code_findings.canonical import AnalysisContext, build_issues
from fdai.core.security.code_findings.models import CodeSecurityIssue, Lane
from fdai.core.security.code_findings.sarif import SarifIngestContext, ingest_sarif
from fdai.core.security.code_findings.verifier import (
    VerifierOutcome,
    VerifierResult,
    taint_rule_verifications,
    verified_confidence,
    verify_issues,
)
from fdai.rule_catalog.code_security import CodeSecurityCatalogError, Confidence
from fdai.rule_catalog.code_security_verifiers import VerifierCatalog, load_verifier_catalog

from ._support import CATALOG_ROOT, REVISION, catalog, result, sarif

SQLI, CMDI, CODE, DESER, PATH = 89, 78, 95, 502, 22


def _shipped() -> VerifierCatalog:
    return load_verifier_catalog(CATALOG_ROOT, frozenset(catalog().weakness_classes.classes))


def _verifiers() -> VerifierCatalog:
    """The shipped catalog with every verifier promoted, to test analysis apart from the gate."""
    import yaml

    shipped = _shipped()
    taint = [
        rule["id"]
        for rule_file in sorted((CATALOG_ROOT / "rules" / "verify").glob("*.yaml"))
        for rule in yaml.safe_load(rule_file.read_text())["rules"]
    ]
    keys = (*(f"python:{name}" for name in shipped.python.classes), *taint)
    promotion = shipped.promotion.model_copy(update={"promoted": keys})
    return shipped.model_copy(update={"promotion": promotion})


def _issues(findings: list[tuple[str, int, int]]) -> tuple[CodeSecurityIssue, ...]:
    occurrences = ingest_sarif(
        sarif("Opengrep", [result(f"rule-{cwe}", p, line, cwe=cwe) for p, line, cwe in findings]),
        SarifIngestContext(lane=Lane.DETERMINISTIC, revision=REVISION),
    ).occurrences
    return build_issues(occurrences, catalog(), AnalysisContext(revision=REVISION))


def _line(source: str, marker: str) -> int:
    return next(i for i, text in enumerate(source.splitlines(), 1) if marker in text)


def _verify(tmp_path: Path, source: str, cwe: int, marker: str = "# sink") -> VerifierResult:
    body = textwrap.dedent(source)
    (tmp_path / "app.py").write_text(body, encoding="utf-8")
    issues = _issues([("app.py", _line(body, marker), cwe)])
    (verdict,) = verify_issues(tmp_path, issues, _verifiers(), revision=REVISION)
    return verdict


VULNERABLE = {
    "flask_route_sqli": (
        """
        from flask import Flask
        app = Flask(__name__)

        @app.route("/orders/<name>")
        def order(name):
            query = "SELECT * FROM orders WHERE name = '%s'" % name
            cursor.execute(query)  # sink
        """,
        SQLI,
    ),
    "request_args_shell": (
        """
        import subprocess
        from flask import request

        def ping():
            host = request.args.get("host")
            subprocess.run(f"ping -c 1 {host}", shell=True)  # sink
        """,
        CMDI,
    ),
    "aliased_os_system": (
        """
        from os import system as run_shell
        from flask import request

        def handler():
            run_shell("tar xf " + request.form["archive"])  # sink
        """,
        CMDI,
    ),
    "fastapi_eval": (
        """
        from fastapi import APIRouter
        router = APIRouter()

        @router.get("/calc")
        async def calc(expression: str):
            return eval(expression)  # sink
        """,
        CODE,
    ),
    "pickle_body": (
        """
        import pickle
        from flask import request

        def restore():
            data = request.get_data()
            return pickle.loads(data)  # sink
        """,
        DESER,
    ),
    "yaml_unsafe_loader": (
        """
        import yaml
        from flask import request

        def load():
            return yaml.load(request.data, Loader=yaml.Loader)  # sink
        """,
        DESER,
    ),
    "path_open_in_with": (
        """
        from flask import request

        def download():
            name = request.args["file"]
            with open("/srv/files/" + name) as handle:  # sink
                return handle.read()
        """,
        PATH,
    ),
    "taint_in_one_branch": (
        """
        from flask import request

        def view(flag):
            command = "uptime"
            if flag:
                command = request.args["cmd"]
            import os
            os.system(command)  # sink
        """,
        CMDI,
    ),
    "loop_carried": (
        """
        from flask import request

        def view():
            parts = []
            for item in request.args.getlist("col"):
                parts.append(item)
            sql = "SELECT " + ",".join(parts)
            db.execute(sql)  # sink
        """,
        SQLI,
    ),
}


@pytest.mark.parametrize("case", sorted(VULNERABLE))
def test_attacker_controlled_flow_is_verified(tmp_path: Path, case: str) -> None:
    source, cwe = VULNERABLE[case]
    verdict = _verify(tmp_path, source, cwe)
    assert verdict.outcome is VerifierOutcome.VERIFIED, verdict
    assert verdict.reason == "attacker_controlled_flow"
    assert verdict.sink and verdict.source


SAFE = {
    "parameterized_query": (
        """
        from flask import Flask
        app = Flask(__name__)

        @app.route("/orders/<name>")
        def order(name):
            cursor.execute("SELECT * FROM orders WHERE name = %s", (name,))  # sink
        """,
        SQLI,
        "argument_not_attacker_controlled",
    ),
    "shlex_quote": (
        """
        import shlex, subprocess
        from flask import request

        def ping():
            host = shlex.quote(request.args["host"])
            subprocess.run("ping -c 1 " + host, shell=True)  # sink
        """,
        CMDI,
        "argument_not_attacker_controlled",
    ),
    "no_shell": (
        """
        import subprocess
        from flask import request

        def ping():
            subprocess.run(["ping", "-c", "1", request.args["host"]])  # sink
        """,
        CMDI,
        "no_sink_at_fix_site",
    ),
    "allowlist_guard": (
        """
        import os
        from flask import request, abort
        ALLOWED = {"uptime", "df"}

        def run():
            command = request.args["cmd"]
            if command not in ALLOWED:
                abort(400)
            os.system(command)  # sink
        """,
        CMDI,
        "argument_not_attacker_controlled",
    ),
    "validated_request_expression": (
        """
        import os
        from flask import request
        ALLOWED = {"uptime"}

        def run():
            if request.args["cmd"] in ALLOWED:
                os.system(request.args["cmd"])  # sink
        """,
        CMDI,
        "argument_not_attacker_controlled",
    ),
    "typed_route_converter": (
        """
        from flask import Flask
        app = Flask(__name__)

        @app.route("/orders/<int:order_id>")
        def order(order_id):
            cursor.execute(f"SELECT * FROM orders WHERE id = {order_id}")  # sink
        """,
        SQLI,
        "argument_not_attacker_controlled",
    ),
    "typed_fastapi_parameter": (
        """
        from fastapi import APIRouter
        router = APIRouter()

        @router.get("/orders/{order_id}")
        def order(order_id: int):
            cursor.execute(f"SELECT * FROM orders WHERE id = {order_id}")  # sink
        """,
        SQLI,
        "argument_not_attacker_controlled",
    ),
    "safe_yaml_loader": (
        """
        import yaml
        from flask import request

        def load():
            return yaml.load(request.data, Loader=yaml.SafeLoader)  # sink
        """,
        DESER,
        "no_sink_at_fix_site",
    ),
    "reassigned_before_sink": (
        """
        import os
        from flask import request

        def run():
            command = request.args["cmd"]
            command = "uptime"
            os.system(command)  # sink
        """,
        CMDI,
        "argument_not_attacker_controlled",
    ),
    "unreachable_after_return": (
        """
        import os
        from flask import request

        def run():
            command = request.args["cmd"]
            return None
            os.system(command)  # sink
        """,
        CMDI,
        "unreachable",
    ),
    "constant_false_branch": (
        """
        import os
        from flask import request

        def run():
            if False:
                os.system(request.args["cmd"])  # sink
        """,
        CMDI,
        "unreachable",
    ),
    "local_cli_input_is_not_a_network_source": (
        """
        import os, sys

        def main():
            os.system("echo " + sys.argv[1])  # sink
        """,
        CMDI,
        "argument_not_attacker_controlled",
    ),
    "basename_for_path": (
        """
        import os
        from flask import request

        def download():
            name = os.path.basename(request.args["file"])
            return open("/srv/files/" + name).read()  # sink
        """,
        PATH,
        "argument_not_attacker_controlled",
    ),
}


@pytest.mark.parametrize("case", sorted(SAFE))
def test_safe_or_unproven_flow_is_not_verified(tmp_path: Path, case: str) -> None:
    source, cwe, reason = SAFE[case]
    verdict = _verify(tmp_path, source, cwe)
    assert verdict.outcome is VerifierOutcome.NOT_VERIFIED, verdict
    assert verdict.reason == reason


def test_unsupported_inputs_leave_confidence_unchanged(tmp_path: Path) -> None:
    (tmp_path / "app.js").write_text("eval(location.hash)\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def (:\n", encoding="utf-8")
    (tmp_path / "xss.py").write_text("x = 1\n", encoding="utf-8")
    issues = _issues(
        [("app.js", 1, CODE), ("broken.py", 1, CODE), ("missing.py", 3, CODE), ("xss.py", 1, 79)]
    )
    verdicts = {
        v.issue_id: v for v in verify_issues(tmp_path, issues, _verifiers(), revision=REVISION)
    }
    reasons = sorted(v.reason for v in verdicts.values())
    assert reasons == [
        "file_unavailable",
        "parse_error",
        "unsupported_class",
        "unsupported_language",
    ]
    assert all(v.outcome is VerifierOutcome.UNSUPPORTED for v in verdicts.values())
    assert verified_confidence(verdicts.values()) == {}


def test_revision_mismatch_and_symlink_escape_are_unsupported(tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("import os\nos.system(request.args['x'])\n", encoding="utf-8")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "link.py").symlink_to(outside)
    issues = _issues([("link.py", 2, CMDI)])
    (escaped,) = verify_issues(root, issues, _verifiers(), revision=REVISION)
    assert escaped.reason == "file_unavailable"
    (mismatch,) = verify_issues(root, issues, _verifiers(), revision="b" * 40)
    assert mismatch.reason == "revision_mismatch"


def test_verified_confidence_raises_the_issue_without_touching_severity(tmp_path: Path) -> None:
    source, cwe = VULNERABLE["request_args_shell"]
    body = textwrap.dedent(source)
    (tmp_path / "app.py").write_text(body, encoding="utf-8")
    occurrences = ingest_sarif(
        sarif("Opengrep", [result("r", "app.py", _line(body, "# sink"), cwe=cwe)]),
        SarifIngestContext(lane=Lane.DETERMINISTIC, revision=REVISION),
    ).occurrences
    (before,) = build_issues(occurrences, catalog(), AnalysisContext(revision=REVISION))
    verdicts = verify_issues(tmp_path, (before,), _verifiers(), revision=REVISION)
    (after,) = build_issues(
        occurrences,
        catalog(),
        AnalysisContext(revision=REVISION, verifications=verified_confidence(verdicts)),
    )
    assert before.confidence is Confidence.REPORTED
    assert after.confidence is Confidence.VERIFIED
    assert after.issue_id == before.issue_id
    assert after.severity == before.severity


def test_catalog_rejects_unknown_class_and_ambiguous_sink(tmp_path: Path) -> None:
    text = (CATALOG_ROOT / "verifiers.yaml").read_text(encoding="utf-8")
    (tmp_path / "verifiers.yaml").write_text(
        text.replace("    sql_injection:", "    not_a_class:"), encoding="utf-8"
    )
    with pytest.raises(CodeSecurityCatalogError, match="unknown classes"):
        load_verifier_catalog(tmp_path, frozenset(catalog().weakness_classes.classes))
    (tmp_path / "verifiers.yaml").write_text(
        text.replace("{call: os.system, arg: 0}", "{call: os.system, method: system, arg: 0}"),
        encoding="utf-8",
    )
    with pytest.raises(CodeSecurityCatalogError, match="exactly one"):
        load_verifier_catalog(tmp_path, frozenset(catalog().weakness_classes.classes))


def _taint_issue(producer: str, lane: Lane, rule_id: str) -> tuple[CodeSecurityIssue, list[object]]:
    occurrences = list(
        ingest_sarif(
            sarif(producer, [result(rule_id, "src/Orders.java", 25, cwe=SQLI)]),
            SarifIngestContext(lane=lane, revision=REVISION),
        ).occurrences
    )
    (issue,) = build_issues(occurrences, catalog(), AnalysisContext(revision=REVISION))
    return issue, occurrences


def test_taint_verifier_rule_hit_verifies_the_issue() -> None:
    issue, occurrences = _taint_issue(
        "Semgrep OSS", Lane.DETERMINISTIC, "rules.verify.fdai.verify.java.sql-injection"
    )
    (verdict,) = taint_rule_verifications((issue,), occurrences, _verifiers())  # type: ignore[arg-type]
    assert verdict.outcome is VerifierOutcome.VERIFIED
    assert verdict.sink == "java:sql-injection"
    assert verified_confidence((verdict,)) == {issue.issue_id: Confidence.VERIFIED}


@pytest.mark.parametrize(
    ("producer", "lane", "rule_id"),
    [
        ("MDASH", Lane.EXTERNAL, "fdai.verify.java.sql-injection"),
        ("Opengrep", Lane.EXTERNAL, "fdai.verify.java.sql-injection"),
        ("custom-scanner", Lane.DETERMINISTIC, "fdai.verify.java.sql-injection"),
        ("Opengrep", Lane.DETERMINISTIC, "rules.fdai.java.sql-concatenated-statement"),
        ("Opengrep", Lane.DETERMINISTIC, "evil.fdai.verify.java.sql-injection.extra"),
    ],
)
def test_taint_verification_cannot_be_claimed_by_other_lanes_or_rules(
    producer: str, lane: Lane, rule_id: str
) -> None:
    issue, occurrences = _taint_issue(producer, lane, rule_id)
    assert taint_rule_verifications((issue,), occurrences, _verifiers()) == ()  # type: ignore[arg-type]


def test_verifier_rule_pack_is_classified_and_fixture_covered() -> None:
    import re

    import yaml

    verify_dir = CATALOG_ROOT / "rules" / "verify"
    ids: list[str] = []
    for rule_file in sorted(verify_dir.glob("*.yaml")):
        fixtures = [p for p in verify_dir.glob(f"{rule_file.stem}.*") if p.suffix != ".yaml"]
        annotations = {a for f in fixtures for a in re.findall(r"ruleid: (\S+)", f.read_text())}
        oks = {a for f in fixtures for a in re.findall(r"ok: (\S+)", f.read_text())}
        for rule in yaml.safe_load(rule_file.read_text())["rules"]:
            ids.append(rule["id"])
            assert re.fullmatch(r"fdai\.verify\.[a-z]+\.[a-z-]+", rule["id"]), rule["id"]
            assert rule["mode"] == "taint" and rule["metadata"]["fdai_verifier"] is True
            (cwe,) = rule["metadata"]["cwe"]
            assert catalog().weakness_classes.class_for_cwe(int(cwe.removeprefix("CWE-")))
            assert rule["id"] in annotations, f"{rule['id']} has no positive fixture"
            assert rule["id"] in oks, f"{rule['id']} has no negative fixture"
    assert len(ids) == len(set(ids)) == 10


def test_unpromoted_taint_rule_hit_stays_in_shadow() -> None:
    occurrences = list(
        ingest_sarif(
            sarif(
                "Opengrep",
                [result("rules.verify.fdai.verify.js.path-traversal", "a.js", 4, cwe=PATH)],
            ),
            SarifIngestContext(lane=Lane.DETERMINISTIC, revision=REVISION),
        ).occurrences
    )
    (issue,) = build_issues(occurrences, catalog(), AnalysisContext(revision=REVISION))
    (verdict,) = taint_rule_verifications((issue,), occurrences, _shipped())  # type: ignore[arg-type]
    assert verdict.outcome is VerifierOutcome.NOT_VERIFIED
    assert verdict.reason == "verifier_in_shadow"
    assert verified_confidence((verdict,)) == {}


def test_unpromoted_python_class_stays_in_shadow(tmp_path: Path) -> None:
    shipped = _shipped()
    assert not shipped.promoted("python:command_injection")
    source, cwe = VULNERABLE["request_args_shell"]
    body = textwrap.dedent(source)
    (tmp_path / "app.py").write_text(body, encoding="utf-8")
    issues = _issues([("app.py", _line(body, "# sink"), cwe)])
    (promoted,) = verify_issues(tmp_path, issues, _verifiers(), revision=REVISION)
    assert promoted.outcome is VerifierOutcome.VERIFIED
    (verdict,) = verify_issues(tmp_path, issues, shipped, revision=REVISION)
    assert verdict.outcome is VerifierOutcome.NOT_VERIFIED
    assert verdict.reason == "verifier_in_shadow"


def test_promotion_list_is_backed_by_the_real_code_corpus() -> None:
    import yaml
    from fdai.core.security.code_findings.verifier_evaluation import load_verifier_corpus

    corpus = load_verifier_corpus(
        yaml.safe_load((CATALOG_ROOT / "evaluation" / "verifier-corpus.yaml").read_text())
    )
    promoted = set(_shipped().promotion.promoted)
    assert promoted <= corpus.covered_keys()
    assert f"{corpus.header['corpus_id']}@{corpus.header['version']}" in (
        _shipped().promotion.evidence
    )
    held_out = {item.key for item in corpus.locations if item.split == "holdout"}
    held_out |= {key for spec in corpus.expected_results for key in spec.keys}
    assert promoted <= held_out
    assert "fdai.verify.js.path-traversal" not in promoted
