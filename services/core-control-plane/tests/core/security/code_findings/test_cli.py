"""Tests for the operator CLI: gated export, signing, registry, revocation, and import."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fdai.delivery import code_security_cli

from ._support import CATALOG_ROOT, REVISION, result, sarif, write_signing_key


def _policy(tmp_path: Path) -> Path:
    path = tmp_path / "providers.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "version": "1.0.0",
                "providers": [
                    {
                        "id": "example-agent",
                        "display_name": "Example agent",
                        "modes": ["minimized"],
                        "data_residency": "example-region",
                        "training_use": "none",
                        "retention_days": 0,
                        "approved_until": "2099-12-31",
                    }
                ],
            }
        )
    )
    return path


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, object]]:
    code = code_security_cli.main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def _export(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], *extra: str
) -> tuple[int, dict[str, object]]:
    mdash = tmp_path / "mdash.sarif"
    mdash.write_bytes(
        sarif(
            "MDASH", [result("sqli", "src/db.py", 2, cwe=89), result("bad", "../x.py", 1, cwe=89)]
        )
    )
    opengrep = tmp_path / "opengrep.sarif"
    opengrep.write_bytes(sarif("Opengrep", [result("python.sqli", "src/db.py", 2, cwe=89)]))
    return _run(
        capsys,
        "export",
        "--sarif",
        f"{mdash}:external",
        "--sarif",
        f"{opengrep}:deterministic",
        "--revision",
        REVISION,
        "--repo-alias",
        "example-service",
        "--out",
        str(tmp_path / "out"),
        "--registry",
        str(tmp_path / "registry"),
        "--provider-policy",
        str(_policy(tmp_path)),
        "--catalog-root",
        str(CATALOG_ROOT),
        *extra,
    )


def test_signed_export_import_and_revocation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key = write_signing_key(tmp_path / "signing.pem")
    code, exported = _export(
        tmp_path, capsys, "--provider", "example-agent", "--signing-key", str(key)
    )
    assert code == 0, exported
    assert exported["signed"] is True and exported["mode"] == "minimized"
    assert exported["occurrences"] == 2 and exported["issues"] == 1
    assert exported["dropped"] == {"unresolvable_location": 1}
    pack_dir = Path(str(exported["pack_dir"]))
    assert (pack_dir.stat().st_mode & 0o077) == 0
    manifest = json.loads((pack_dir / "pack.manifest.json").read_text())
    assert manifest["target_provider"] == "example-agent"
    assert manifest["signing_key_id"] == exported["signing_key_id"]
    assert (pack_dir / "pack.manifest.dsse.json").exists()
    record = json.loads((tmp_path / "registry" / f"{exported['pack_id']}.json").read_text())
    result_file = tmp_path / "result.json"
    body = {
        "schema_version": 1,
        "pack_id": record["pack_id"],
        "manifest_sha256": record["manifest_sha256"],
        "base_commit": REVISION,
        "final_head": "c" * 40,
        "issues": [{"issue_id": record["issue_ids"][0], "status": "deferred"}],
    }
    result_file.write_text(json.dumps(body))
    code, imported = _run(
        capsys,
        "import-result",
        "--registry",
        str(tmp_path / "registry"),
        "--result",
        str(result_file),
    )
    assert code == 0 and imported["claims"][0]["status"] == "deferred"  # type: ignore[index]
    code, revoked = _run(
        capsys,
        "revoke",
        "--registry",
        str(tmp_path / "registry"),
        "--pack-id",
        record["pack_id"],
        "--reason",
        "lost laptop",
    )
    assert code == 0 and revoked["revoked"] is True
    code, rejected = _run(
        capsys,
        "import-result",
        "--registry",
        str(tmp_path / "registry"),
        "--result",
        str(result_file),
    )
    assert code == 1 and rejected["reason"] == "pack_revoked"
    code, key_out = _run(capsys, "public-key", "--signing-key", str(key))
    assert code == 0 and key_out["key_id"] == exported["signing_key_id"]


def test_export_is_denied_for_unapproved_provider_or_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, denied = _export(tmp_path, capsys, "--provider", "other-agent")
    assert code == 1 and denied["reason"] == "export_denied"
    code, denied = _export(tmp_path, capsys, "--provider", "example-agent", "--mode", "full")
    assert code == 1 and denied["reason"] == "export_denied"
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "registry").exists()


def test_unknown_pack_result_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result_file = tmp_path / "result.json"
    result_file.write_text(json.dumps({"pack_id": "abcdefabcdef"}))
    code, rejected = _run(
        capsys,
        "import-result",
        "--registry",
        str(tmp_path / "registry"),
        "--result",
        str(result_file),
    )
    assert code == 1 and rejected["reason"] == "unknown_pack"


def test_verify_fixes_and_adjudicate_through_the_registry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, exported = _export(
        tmp_path,
        capsys,
        "--provider",
        "example-agent",
        "--full-repository",
        "Opengrep",
        "--full-repository",
        "MDASH",
    )
    assert code == 0, exported
    registry = tmp_path / "registry"
    record = json.loads((registry / f"{exported['pack_id']}.json").read_text())
    issue_id = record["issue_ids"][0]
    head = "d" * 40
    result_file = tmp_path / "result.json"
    result_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pack_id": record["pack_id"],
                "manifest_sha256": record["manifest_sha256"],
                "base_commit": REVISION,
                "final_head": head,
                "issues": [
                    {
                        "issue_id": issue_id,
                        "status": "fixed_claimed",
                        "validation": "tests_passed",
                        "commits": [head],
                    }
                ],
            }
        )
    )
    clean = []
    for producer in ("MDASH", "Opengrep"):
        path = tmp_path / f"{producer}-rescan.sarif"
        path.write_text(
            json.dumps(
                {
                    "version": "2.1.0",
                    "runs": [
                        {
                            "tool": {"driver": {"name": producer, "version": "1.0.0"}},
                            "results": [],
                            "invocations": [{"executionSuccessful": True}],
                        }
                    ],
                }
            )
        )
        clean += ["--rescan-sarif", f"{path}:external", "--full-repository", producer]
    code, verified = _run(
        capsys,
        "verify-fixes",
        "--registry",
        str(registry),
        "--result",
        str(result_file),
        "--rescan-revision",
        head,
        "--catalog-root",
        str(CATALOG_ROOT),
        *clean,
    )
    assert code == 0, verified
    assert verified["verdicts"][0]["verdict"] == "fixed_verified"  # type: ignore[index]
    code, partial = _run(
        capsys,
        "verify-fixes",
        "--registry",
        str(registry),
        "--result",
        str(result_file),
        "--rescan-revision",
        head,
        "--catalog-root",
        str(CATALOG_ROOT),
        *clean[:4],
    )
    assert partial["verdicts"][0]["verdict"] == "inconclusive"  # type: ignore[index]

    fp_file = tmp_path / "fp.json"
    fp_file.write_text(
        result_file.read_text().replace('"fixed_claimed"', '"claimed_false_positive"')
    )
    code, decided = _run(
        capsys,
        "adjudicate",
        "--registry",
        str(registry),
        "--result",
        str(fp_file),
        "--issue",
        issue_id,
        "--decision",
        "rejected",
        "--claimant",
        "dev@example.com",
        "--adjudicator",
        "secops@example.com",
        "--approval-ref",
        "approval/hil-7",
        "--rationale",
        "The id reaches the query without validation.",
    )
    assert code == 0 and decided["issue_disposition"] == "open"
    code, refused = _run(
        capsys,
        "adjudicate",
        "--registry",
        str(registry),
        "--result",
        str(fp_file),
        "--issue",
        issue_id,
        "--decision",
        "accepted",
        "--claimant",
        "dev@example.com",
        "--adjudicator",
        "dev@example.com",
        "--approval-ref",
        "approval/hil-8",
        "--rationale",
        "Self approval attempt here.",
    )
    assert code == 1 and refused["reason"] == "adjudication_rejected"
    reviews = (registry / f"{record['pack_id']}.reviews.jsonl").read_text().splitlines()
    assert [json.loads(line)["kind"] for line in reviews] == [
        "fix_verification",
        "fix_verification",
        "false_positive_adjudication",
    ]


def test_publish_review_without_bus_writes_package_and_plans_notifications(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scan = tmp_path / "scan.sarif"
    scan.write_bytes(sarif("Opengrep", [result("python.sqli", "src/db.py", 2, cwe=89)]))
    out = tmp_path / "review.json"
    code, published = _run(
        capsys,
        "publish-review",
        "--sarif",
        f"{scan}:deterministic",
        "--revision",
        REVISION,
        "--repo-alias",
        "example-service",
        "--out",
        str(out),
        "--catalog-root",
        str(CATALOG_ROOT),
    )
    assert code == 0, published
    assert published["published"] is False
    assert published["decision"] == "coverage_incomplete"
    assert [n["template_key"] for n in published["notifications"]] == [
        "code_security_coverage_alert",
        "code_security_digest",
    ]  # type: ignore[index, union-attr]
    written = json.loads(out.read_text())
    assert written["package"]["grants_authority"] is False
    assert "src/db.py" not in out.read_text()


def test_export_verifies_external_findings_against_the_exact_revision(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import subprocess

    def git(cwd: Path, *argv: str) -> str:
        return subprocess.run(  # noqa: S603 - controlled test command
            ["git", *argv],  # noqa: S607 - git from PATH in tests
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    repo = tmp_path / "origin"
    (repo / "src").mkdir(parents=True)
    git(tmp_path, "init", "-q", "-b", "main", str(repo))
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "uploadpack.allowAnySHA1InWant", "true")
    (repo / "src" / "db.py").write_text(
        "from flask import request\n\ndef find():\n"
        "    cursor.execute(\"SELECT * FROM t WHERE n = '%s'\" % request.args['n'])\n"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "initial")
    revision = git(repo, "rev-parse", "HEAD")
    mdash = tmp_path / "mdash.sarif"
    mdash.write_bytes(sarif("MDASH", [result("sqli", "src/db.py", 4, cwe=89)]))
    code, output = _run(
        capsys,
        "export",
        "--sarif",
        f"{mdash}:external",
        "--revision",
        revision,
        "--repo-alias",
        "example-service",
        "--out",
        str(tmp_path / "out"),
        "--registry",
        str(tmp_path / "registry"),
        "--provider",
        "example-agent",
        "--provider-policy",
        str(_policy(tmp_path)),
        "--catalog-root",
        str(CATALOG_ROOT),
        "--verify-repository",
        str(repo),
        "--work-root",
        str(tmp_path / "work"),
    )
    assert code == 0, output
    assert output["verified"] == 1
    pack_text = "".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "out").rglob("*.json")
        if path.is_file()
    )
    assert '"confidence": "verified"' in pack_text
    code, output = _run(
        capsys,
        "export",
        "--sarif",
        f"{mdash}:external",
        "--revision",
        revision,
        "--repo-alias",
        "example-service",
        "--out",
        str(tmp_path / "out2"),
        "--registry",
        str(tmp_path / "registry"),
        "--provider",
        "example-agent",
        "--provider-policy",
        str(_policy(tmp_path)),
        "--verify-repository",
        str(repo),
    )
    assert code == 1 and "--work-root" in str(output["error"])
