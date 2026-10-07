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
