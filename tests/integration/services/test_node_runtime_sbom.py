from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "services/core-control-plane/docker/node-runtime-sbom.py"
_SPEC = importlib.util.spec_from_file_location("node_runtime_sbom_under_test", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_VERSIONS = {
    "node": "24.21.0",
    "acorn": "8.18.0",
    "amaro": "1.1.11",
    "undici": "7.29.1",
    "openssl": "3.5.8",
    "modules": "137",
}


def test_inventory_binds_binary_without_claiming_full_native_coverage() -> None:
    result = _MODULE.build_sbom(_VERSIONS, binary_digest="a" * 64, archive_digest="b" * 64)
    metadata = result["metadata"]
    assert metadata["component"]["hashes"] == [{"alg": "SHA-256", "content": "a" * 64}]
    assert metadata["component"]["purl"] == "pkg:generic/nodejs@24.21.0"
    properties = {entry["name"]: entry["value"] for entry in metadata["properties"]}
    assert properties["fdai:coverage-scope"] == "embedded-npm-only"
    assert properties["fdai:source-archive-sha256"] == "b" * 64
    assert json.loads(properties["fdai:unassessed-version-fields"]) == ["modules", "openssl"]
    assert json.loads(properties["fdai:runtime-reported-versions"]) == _VERSIONS
    assert {entry["purl"] for entry in result["components"]} == {
        "pkg:npm/acorn@8.18.0",
        "pkg:npm/amaro@1.1.11",
        "pkg:npm/undici@7.29.1",
    }
    assert result == _MODULE.build_sbom(
        dict(reversed(list(_VERSIONS.items()))), binary_digest="a" * 64, archive_digest="b" * 64
    )


@pytest.mark.parametrize("field", ["node", "acorn", "amaro", "undici"])
@pytest.mark.parametrize("value", [None, "", "invalid", "../7.3.0"])
def test_invalid_required_versions_fail_explicitly(field: str, value: object) -> None:
    versions: dict[str, object] = dict(_VERSIONS)
    versions[field] = value
    message = "bounded ASCII string map" if value is None else f"valid {field} version"
    with pytest.raises(ValueError, match=message):
        _MODULE.build_sbom(versions, binary_digest="a" * 64, archive_digest="b" * 64)


@pytest.mark.parametrize("digest", ["", "not-a-digest", "A" * 64, "a" * 65])
def test_invalid_provenance_fails_explicitly(digest: str) -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        _MODULE.build_sbom(_VERSIONS, binary_digest=digest, archive_digest="b" * 64)
    with pytest.raises(ValueError, match="SHA-256"):
        _MODULE.build_sbom(_VERSIONS, binary_digest="a" * 64, archive_digest=digest)


@pytest.mark.parametrize("value", ["a" * 129, "\u00e9", 42])
def test_invalid_native_observations_are_not_silently_omitted(value: object) -> None:
    versions: dict[str, object] = dict(_VERSIONS)
    versions["openssl"] = value
    with pytest.raises(ValueError, match="bounded ASCII string map"):
        _MODULE.build_sbom(versions, binary_digest="a" * 64, archive_digest="b" * 64)


def test_cli_hashes_actual_bytes_and_writes_standard_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    versions = tmp_path / "versions.json"
    versions.write_text(json.dumps(_VERSIONS))
    binary = tmp_path / "node"
    binary.write_bytes(b"controlled-binary-bytes")
    output = tmp_path / "inventory.cdx.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(_SCRIPT),
            "--versions",
            str(versions),
            "--binary",
            str(binary),
            "--archive-sha256",
            "b" * 64,
            "--output",
            str(output),
        ],
    )
    _MODULE.main()
    result = json.loads(output.read_text())
    assert (
        result["metadata"]["component"]["hashes"][0]["content"]
        == hashlib.sha256(binary.read_bytes()).hexdigest()
    )
