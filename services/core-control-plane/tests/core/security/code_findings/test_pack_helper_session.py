"""End-to-end remediation session: rendered pack helper against a temporary git repository."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fdai.core.security.code_findings.canonical import AnalysisContext, build_issues
from fdai.core.security.code_findings.models import Lane
from fdai.core.security.code_findings.pack import (
    PackRequest,
    RemediationPack,
    render_remediation_pack,
)
from fdai.core.security.code_findings.result_import import (
    ClaimStatus,
    PackRecord,
    import_remediation_result,
)
from fdai.core.security.code_findings.sarif import SarifIngestContext, ingest_sarif

from ._support import catalog, result, sarif

_VULNERABLE = (
    'def find(cur, uid):\n    return cur.execute(f"SELECT * FROM users WHERE id = {uid}")\n'
)
_FIXED = (
    'def find(cur, uid):\n    return cur.execute("SELECT * FROM users WHERE id = %s", (uid,))\n'
)


def _env(tmp_path: Path) -> dict[str, str]:
    hooks = tmp_path / "no-hooks"
    hooks.mkdir(exist_ok=True)
    return {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Example Dev",
        "GIT_AUTHOR_EMAIL": "dev@example.com",
        "GIT_COMMITTER_NAME": "Example Dev",
        "GIT_COMMITTER_EMAIL": "dev@example.com",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.hooksPath",
        "GIT_CONFIG_VALUE_0": str(hooks),
    }


def _git(repo: Path, env: dict[str, str], *args: str) -> str:
    return subprocess.run(  # noqa: S603 - controlled test command
        ["git", "-C", str(repo), *args],  # noqa: S607 - git from PATH in tests
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


def _setup(tmp_path: Path) -> tuple[Path, Path, RemediationPack, dict[str, str]]:
    env = _env(tmp_path)
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    _git(tmp_path, env, "init", "-q", "-b", "main", str(repo))
    (repo / "src" / "db.py").write_text(_VULNERABLE)
    _git(repo, env, "add", "-A")
    _git(repo, env, "commit", "-q", "-m", "initial")
    base = _git(repo, env, "rev-parse", "HEAD")
    raw = sarif("Opengrep", [result("python.sqli", "src/db.py", 2, cwe=89)])
    occurrences = ingest_sarif(
        raw, SarifIngestContext(lane=Lane.DETERMINISTIC, revision=base)
    ).occurrences
    issues = build_issues(occurrences, catalog(), AnalysisContext(revision=base))
    pack = render_remediation_pack(
        issues,
        catalog(),
        PackRequest(
            repository_alias="example-service", base_commit=base, created_at=datetime.now(UTC)
        ),
    )
    pack_dir = tmp_path / "packs" / pack.directory_name
    for relative, data in pack.files.items():
        target = pack_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return repo, pack_dir, pack, env


def _helper(pack_dir: Path, repo: Path, env: dict[str, str], *args: str) -> dict[str, Any]:
    proc = subprocess.run(  # noqa: S603 - runs the rendered pack helper under test
        [
            sys.executable,
            str(pack_dir / "tools" / "fdai_remediate.py"),
            "--pack",
            str(pack_dir),
            "--repo",
            str(repo),
            *args,
        ],
        capture_output=True,
        text=True,
        env={**env, "PYTHONPATH": ""},
        check=False,
    )
    output = json.loads(proc.stdout)
    assert (proc.returncode == 0) == bool(output.get("ok")), proc.stderr
    return output


def test_full_session_guards_commits_and_returns_importable_claims(tmp_path: Path) -> None:
    repo, pack_dir, pack, env = _setup(tmp_path)
    verified = _helper(pack_dir, repo, env, "verify")
    assert verified["ok"], verified
    summary = _helper(pack_dir, repo, env, "summary")
    assert summary["issues"] == 1 and "| Priority |" in summary["table_markdown"]
    assert _helper(pack_dir, repo, env, "plan")["ok"] is False
    _helper(pack_dir, repo, env, "record", "scope", "--json", json.dumps({"targets": "all"}))
    assert len(_helper(pack_dir, repo, env, "plan")["groups"]) == 1
    started = _helper(pack_dir, repo, env, "start")
    assert started["branch"] == f"fdai/sec/{pack.pack_id}"
    step = _helper(pack_dir, repo, env, "next-group")
    group_id = step["group"]["group_id"]
    issue_id = step["in_scope_issue_ids"][0]
    assert step["effective_depth"] == "D2"
    _helper(pack_dir, repo, env, "record", "group-start", group_id)

    (repo / "src" / "db.py").write_text(_FIXED.replace("(uid,))", "(uid,))  # nosec"))
    refused = _helper(pack_dir, repo, env, "commit", group_id)
    assert refused["committed"] is False
    assert {v["rule_id"] for v in refused["violations"]} == {"suppression-nosec"}

    (repo / "src" / "db.py").write_text(_FIXED)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_db.py").write_text("def test_param():\n    assert True\n")
    committed = _helper(pack_dir, repo, env, "commit", group_id)
    assert committed["committed"] is True
    message = _git(repo, env, "log", "-1", "--format=%B")
    assert f"FDAI-Pack: {pack.pack_id}" in message and issue_id in message
    _helper(
        pack_dir,
        repo,
        env,
        "record",
        "issue",
        issue_id,
        "--status",
        "fixed_claimed",
        "--validation",
        "tests_passed",
        "--tests",
        "pytest -q tests: 1 passed",
        "--regression-test",
        "tests/test_db.py",
    )
    _helper(pack_dir, repo, env, "record", "group-end", group_id, "--status", "done")
    assert _helper(pack_dir, repo, env, "next-group")["done"] is True
    assert _helper(pack_dir, repo, env, "verify")["ok"] is True

    finished = _helper(pack_dir, repo, env, "finish")
    assert finished["status_counts"] == {"fixed_claimed": 1}
    record = PackRecord(
        pack_id=pack.pack_id,
        manifest_sha256=pack.manifest_sha256,
        base_commit=_git(repo, env, "rev-parse", "main"),
        issue_ids=frozenset(pack.issue_ids),
        expires_at=pack.expires_at,
    )
    imported = import_remediation_result(
        (pack_dir / "result" / "remediation-result.json").read_bytes(), record, datetime.now(UTC)
    )
    (claim,) = imported.claims
    assert claim.status is ClaimStatus.FIXED_CLAIMED
    assert claim.commits == (committed["commit"],)
    assert imported.final_head == committed["commit"]


def test_tampered_pack_and_dirty_tree_fail_verification(tmp_path: Path) -> None:
    repo, pack_dir, _, env = _setup(tmp_path)
    index = pack_dir / "findings" / "index.json"
    index.write_text(index.read_text().replace('"P', '"X', 1))
    (repo / "scratch.txt").write_text("local edit")
    checks = {c["id"]: c for c in _helper(pack_dir, repo, env, "verify")["checks"]}
    assert checks["file-digests"]["ok"] is False
    assert checks["clean-tree"]["ok"] is False


def test_pack_inside_repository_must_be_ignored(tmp_path: Path) -> None:
    repo, pack_dir, _, env = _setup(tmp_path)
    inside = repo / pack_dir.name
    pack_dir.rename(inside)
    checks = {c["id"]: c for c in _helper(inside, repo, env, "verify")["checks"]}
    assert checks["pack-ignored"]["ok"] is False
    (repo / ".git" / "info" / "exclude").write_text(f"{inside.name}/\n")
    assert _helper(inside, repo, env, "verify")["ok"] is True


def test_rollback_restores_group_start_and_removes_new_files(tmp_path: Path) -> None:
    repo, pack_dir, _, env = _setup(tmp_path)
    _helper(pack_dir, repo, env, "record", "scope", "--recommended")
    _helper(pack_dir, repo, env, "record", "scope", "--json", json.dumps({"targets": "all"}))
    _helper(pack_dir, repo, env, "start")
    group_id = _helper(pack_dir, repo, env, "next-group")["group"]["group_id"]
    _helper(pack_dir, repo, env, "record", "group-start", group_id)
    (repo / "src" / "db.py").write_text("broken\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_new.py").write_text("x = 1\n")
    assert _helper(pack_dir, repo, env, "rollback-group", group_id)["ok"] is False
    rolled = _helper(pack_dir, repo, env, "rollback-group", group_id, "--yes")
    assert rolled["removed_untracked"] == ["tests/test_new.py"]
    assert (repo / "src" / "db.py").read_text() == _VULNERABLE
    assert _git(repo, env, "status", "--porcelain") == ""


def test_expired_pack_fails_verification(tmp_path: Path) -> None:
    repo, pack_dir, _, env = _setup(tmp_path)
    manifest_path = pack_dir / "pack.manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["expires_at"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    manifest_path.write_text(json.dumps(manifest))
    checks = {c["id"]: c for c in _helper(pack_dir, repo, env, "verify")["checks"]}
    assert checks["not-expired"]["ok"] is False


@pytest.mark.parametrize("bad", ['{"targets": "everything"}', '{"surprise": 1}'])
def test_scope_values_are_validated(tmp_path: Path, bad: str) -> None:
    repo, pack_dir, _, env = _setup(tmp_path)
    assert _helper(pack_dir, repo, env, "record", "scope", "--json", bad)["ok"] is False


def _start_group(pack_dir: Path, repo: Path, env: dict[str, str]) -> str:
    _helper(pack_dir, repo, env, "record", "scope", "--json", json.dumps({"targets": "all"}))
    _helper(pack_dir, repo, env, "start")
    group_id = str(_helper(pack_dir, repo, env, "next-group")["group"]["group_id"])
    _helper(pack_dir, repo, env, "record", "group-start", group_id)
    return group_id


def test_option_shaped_start_head_in_ledger_is_rejected(tmp_path: Path) -> None:
    repo, pack_dir, _, env = _setup(tmp_path)
    group_id = _start_group(pack_dir, repo, env)
    ledger_path = pack_dir / "ledger" / "remediation-ledger.json"
    ledger = json.loads(ledger_path.read_text())
    ledger["groups"][group_id]["start_head"] = "--output=/dev/null"
    ledger_path.write_text(json.dumps(ledger))
    (repo / "src" / "db.py").write_text(_FIXED + "# nosec\n")
    outcome = _helper(pack_dir, repo, env, "commit", group_id)
    assert outcome["ok"] is False and "commit id" in outcome["error"]
    assert _git(repo, env, "log", "--format=%s", "-1") == "initial"


def test_untracked_files_with_quoted_names_are_guarded(tmp_path: Path) -> None:
    repo, pack_dir, _, env = _setup(tmp_path)
    group_id = _start_group(pack_dir, repo, env)
    (repo / "src" / "s\u00e9curit\u00e9.py").write_text("x = run(cmd)  # nosec\n")
    (repo / "src" / 'we"ird.py').write_text("y = 1\n")
    report = _helper(pack_dir, repo, env, "guard", group_id)
    paths = {v["path"] for v in report["violations"]}
    assert report["ok"] is False
    assert {"src/s\u00e9curit\u00e9.py", 'src/we"ird.py'} <= paths
    assert any(v["rule_id"] == "suppression-nosec" for v in report["violations"])


def test_subdirectory_repo_argument_uses_repository_root(tmp_path: Path) -> None:
    repo, pack_dir, _, env = _setup(tmp_path)
    group_id = _start_group(pack_dir, repo / "src", env)
    (repo / "src" / "evil.py").write_text("z = 1  # nosec\n")
    report = _helper(pack_dir, repo / "src", env, "guard", group_id)
    assert {"src/evil.py"} <= {v["path"] for v in report["violations"]}
    (repo / "tests").mkdir()
    (repo / "tests" / "test_new.py").write_text("x = 1\n")
    rolled = _helper(pack_dir, repo / "src", env, "rollback-group", group_id, "--yes")
    assert rolled["removed_untracked"] == ["tests/test_new.py"]
    assert (repo / "src" / "evil.py").exists()


def test_pack_inside_repository_without_ignore_cannot_start(tmp_path: Path) -> None:
    repo, pack_dir, _, env = _setup(tmp_path)
    inside = repo / pack_dir.name
    pack_dir.rename(inside)
    _helper(inside, repo, env, "record", "scope", "--recommended")
    outcome = _helper(inside, repo, env, "start")
    assert outcome["ok"] is False and "exclude" in outcome["error"]


def test_editing_group_scope_after_verify_blocks_the_guard(tmp_path: Path) -> None:
    repo, pack_dir, _, env = _setup(tmp_path)
    group_id = _start_group(pack_dir, repo, env)
    group_file = pack_dir / "findings" / "groups" / f"{group_id}.json"
    document = json.loads(group_file.read_text())
    document["allowed_paths"].append("**")
    group_file.write_text(json.dumps(document))
    outcome = _helper(pack_dir, repo, env, "guard", group_id)
    assert outcome["ok"] is False and "changed since export" in outcome["error"]
