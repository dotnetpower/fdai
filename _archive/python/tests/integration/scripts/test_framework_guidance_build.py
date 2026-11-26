"""Offline regeneration is exact and accounts for all authoritative identities."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from fdai_service_contracts.catalog_canonical import canonical_digest

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "packages/service-contracts/src/fdai_service_contracts/data"


@pytest.fixture(scope="module")
def builder():
    import sys

    directory = ROOT / "scripts/catalog"
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location(
            "framework_guidance_build_test",
            directory / "framework_guidance_build.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.remove(str(directory))


def test_deterministic_regeneration_matches_every_packaged_byte(builder):
    first = builder.build(ROOT)
    assert first == builder.build(ROOT)
    assert set(first) == {path.name for path in DATA.glob("framework-guidance*.json")}
    assert len(first) == 11
    for name, body in first.items():
        assert body == (DATA / name).read_bytes(), name
    assert (
        sum(
            len(json.loads(body)["entries"])
            for name, body in first.items()
            if name != "framework-guidance.json"
        )
        == 160
    )


def test_manifest_pins_official_sources_and_all_generation_inputs(builder):
    manifest = json.loads(builder.build(ROOT)["framework-guidance.json"])
    assert {source["framework_id"] for source in manifest["official_sources"]} == {
        "azure-waf",
        "azure-mcsb",
        "azure-caf",
    }
    for source in manifest["official_sources"]:
        assert len(source["resolved_ref"]) == 40
        assert source["source_url"].startswith("https://learn.microsoft.com/")
        assert source["license"] == "CC-BY-4.0"
    mcsb = next(
        source for source in manifest["official_sources"] if source["framework_id"] == "azure-mcsb"
    )
    assert mcsb["resolved_ref"] == "2e2db1189667b3108c91fe104661f6869fffd965"
    assert mcsb["content_hash"] == (
        "sha256:759bc9cddf82d5406a835e1fdcbbae2bc30d38d7c2205cafc599053f4dffeb8e"
    )
    for path, digest in manifest["source_files"].items():
        assert digest == "sha256:" + hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    assert (
        len(
            [
                path
                for path in manifest["source_files"]
                if path.startswith("rule-catalog/best-practices/")
            ]
        )
        == 59
    )
    authoring = {
        name: "sha256:" + hashlib.sha256((ROOT / "scripts/catalog" / name).read_bytes()).hexdigest()
        for name in builder.AUTHORING
    }
    assert manifest["authoring_digest"] == "sha256:" + canonical_digest(authoring)


def test_missing_or_duplicate_authoring_identity_fails(builder, monkeypatch):
    first = builder.WAF_ROWS.strip().splitlines()[0]
    monkeypatch.setattr(builder, "WAF_ROWS", builder.WAF_ROWS.replace(first, ""))
    with pytest.raises(ValueError, match="accounting mismatch"):
        builder.build(ROOT)
    with pytest.raises(ValueError, match="Duplicate authored control"):
        builder._parse(first + "\n" + first)


def test_bad_row_and_english_only_overlay_fail(builder, monkeypatch):
    with pytest.raises(ValueError, match="16 columns"):
        builder._parse("RE:01|Incomplete")
    monkeypatch.setattr(
        builder,
        "WAF_ROWS",
        builder.WAF_ROWS.replace(
            "재무 책임을 공유하는 문화 조성",
            "Financial responsibility",
        ),
    )
    with pytest.raises(ValueError, match="readable English and Korean"):
        builder.build(ROOT)


def test_check_command_and_stale_output_detection(builder, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["framework_guidance_build.py", "--check"])
    assert builder.main() == 0
    assert "59 WAF, 86 MCSB v1, 15 CAF; reproducible" in capsys.readouterr().out
    original = Path.read_bytes

    def changed(path):
        body = original(path)
        return body + b" " if path.name == "framework-guidance-00.json" else body

    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(SystemExit, match="requires regeneration"):
        builder.main()
