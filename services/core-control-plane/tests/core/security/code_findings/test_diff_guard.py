"""Tests for the remediation diff guard shared by the pack helper and server import."""

from __future__ import annotations

import pytest
from fdai.core.security.code_findings.diff_guard import (
    evaluate_diff,
    glob_to_regex,
    parse_unified_diff,
)

from ._support import catalog

_ALLOWED = ("src/db.py", "tests/**", "**/test_*.py")


def _policy() -> dict[str, object]:
    return catalog().remediation_policy.guard_document()


def _diff(
    path: str,
    added: list[str],
    removed: list[str] | None = None,
    *,
    new: bool = False,
    deleted: bool = False,
) -> str:
    removed = removed or []
    old = "/dev/null" if new else f"a/{path}"
    newp = "/dev/null" if deleted else f"b/{path}"
    header = [f"diff --git a/{path} b/{path}"]
    if new:
        header.append("new file mode 100644")
    if deleted:
        header.append("deleted file mode 100644")
    header += [f"--- {old}", f"+++ {newp}", f"@@ -1,{len(removed)} +1,{len(added)} @@"]
    return (
        "\n".join(header + [f"-{line}" for line in removed] + [f"+{line}" for line in added]) + "\n"
    )


def _rules(report: dict[str, object]) -> set[str]:
    return {str(v["rule_id"]) for v in report["violations"]}  # type: ignore[index, union-attr]


def test_parameterized_fix_inside_allowed_paths_passes() -> None:
    diff = _diff(
        "src/db.py",
        ['cursor.execute("SELECT * FROM t WHERE id = %s", (user_id,))'],
        ['cursor.execute(f"SELECT * FROM t WHERE id = {user_id}")'],
    )
    diff += _diff(
        "tests/test_db.py",
        ["def test_rejects_injection():", "    assert find('1 OR 1=1') is None"],
        new=True,
    )
    report = evaluate_diff(diff, _ALLOWED, _policy())
    assert report["ok"] is True, report
    assert report["files_checked"] == 2


@pytest.mark.parametrize(
    ("line", "rule_id"),
    [
        ("query = build(user)  # nosec", "suppression-nosec"),
        ("run(cmd)  # nosemgrep", "suppression-semgrep"),
        ("x = eval(s)  # noqa: S307", "suppression-noqa-security"),
        ('@SuppressWarnings("all")', "suppression-java"),
        ("doThing(); // lgtm[js/sql-injection]", "suppression-codeql"),
        ("requests.get(url, verify=False)", "tls-verification-disabled"),
        ("tls.Config{InsecureSkipVerify: true}", "tls-verification-disabled"),
        ("except Exception: pass", "exception-swallowed"),
        ("@pytest.mark.skip(reason='flaky')", "test-skipped"),
    ],
)
def test_forbidden_added_lines_are_rejected(line: str, rule_id: str) -> None:
    report = evaluate_diff(_diff("src/db.py", [line]), _ALLOWED, _policy())
    assert report["ok"] is False
    assert rule_id in _rules(report)


def test_edits_outside_allowed_paths_and_forbidden_paths_are_rejected() -> None:
    diff = _diff("src/other.py", ["x = 1"]) + _diff(".trivyignore", ["CVE-2024-11111"], new=True)
    rules = _rules(evaluate_diff(diff, _ALLOWED, _policy()))
    assert {"outside-allowed-paths", "scanner-ignore-file"} <= rules


def test_deleting_tests_or_assertions_is_rejected() -> None:
    deleted = _diff("tests/test_db.py", [], ["def test_x():", "    assert ok()"], deleted=True)
    weakened = _diff("tests/test_api.py", ["    pass"], ["    assert response.status == 403"])
    rules = _rules(evaluate_diff(deleted + weakened, _ALLOWED, _policy()))
    assert {"test-file-deleted", "test-assertion-removed"} <= rules


def test_binary_and_oversize_diffs_are_rejected() -> None:
    binary = "diff --git a/src/db.py b/src/db.py\nBinary files a/src/db.py and b/src/db.py differ\n"
    assert "binary-change" in _rules(evaluate_diff(binary, _ALLOWED, _policy()))
    policy = _policy()
    policy["limits"] = {**policy["limits"], "max_diff_bytes": 10}  # type: ignore[dict-item]
    assert "diff-too-large" in _rules(
        evaluate_diff(_diff("src/db.py", ["x = 1"]), _ALLOWED, policy)
    )


def test_removed_lines_that_look_like_headers_stay_inside_the_hunk() -> None:
    diff = _diff("src/db.py", ["new"], ["-- old sql comment", "++ also old"])
    (parsed,) = parse_unified_diff(diff)
    assert parsed.removed == ["-- old sql comment", "++ also old"]
    assert parsed.added == [(1, "new")]


@pytest.mark.parametrize(
    ("glob", "path", "expected"),
    [
        ("tests/**", "tests/unit/test_a.py", True),
        ("**/test_*.py", "pkg/tests/test_a.py", True),
        ("**/test_*.py", "test_a.py", True),
        ("src/*", "src/a/b.py", False),
        ("*", "package.json", True),
        ("*", "app/package.json", False),
    ],
)
def test_glob_semantics(glob: str, path: str, expected: bool) -> None:
    assert bool(glob_to_regex(glob).match(path)) is expected


def test_renaming_a_test_away_or_pulling_a_file_into_scope_is_rejected() -> None:
    moved_test = (
        "diff --git a/tests/test_db.py b/tests/test_db.py.bak\n"
        "similarity index 100%\nrename from tests/test_db.py\nrename to tests/test_db.py.bak\n"
    )
    pulled_in = (
        "diff --git a/infra/main.tf b/src/db.py\n"
        "similarity index 100%\nrename from infra/main.tf\nrename to src/db.py\n"
    )
    report = evaluate_diff(moved_test + pulled_in, _ALLOWED, _policy())
    rules = {(v["rule_id"], v["path"]) for v in report["violations"]}  # type: ignore[union-attr, index]
    assert ("test-file-deleted", "tests/test_db.py") in rules
    assert ("outside-allowed-paths", "infra/main.tf") in rules


def test_quoted_paths_are_decoded_and_checked() -> None:
    diff = (
        'diff --git "a/.github/workflows/s\\303\\251curity.yml" '
        '"b/.github/workflows/s\\303\\251curity.yml"\n'
        "new file mode 100644\n--- /dev/null\n"
        '+++ "b/.github/workflows/s\\303\\251curity.yml"\n@@ -0,0 +1 @@\n+run: scan  # nosec\n'
    )
    report = evaluate_diff(diff, _ALLOWED, _policy())
    rules = {(v["rule_id"], v["path"]) for v in report["violations"]}  # type: ignore[union-attr, index]
    assert ("outside-allowed-paths", ".github/workflows/s\u00e9curity.yml") in rules
    assert any(rule == "suppression-nosec" for rule, _ in rules)


def test_undecodable_path_fails_closed() -> None:
    diff = 'diff --git "a/x\\377" "b/x\\377"\n--- "a/x\\377"\n+++ "b/x\\377"\n@@ -1 +1 @@\n-a\n+b\n'
    assert "unsafe-path" in _rules(evaluate_diff(diff, ("**",), _policy()))


def test_repeated_double_star_globs_do_not_backtrack() -> None:
    import time

    pattern = "**/" * 40 + "z"
    started = time.perf_counter()
    assert glob_to_regex(pattern).match("a/" * 30 + "y") is None
    assert time.perf_counter() - started < 0.5
