from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from fdai_cost_governance.lifecycle_cli import (
    _canonical_digest,
    _release_identity,
    _runtime_config_digest,
)


def _wheel(
    tmp_path: Path,
    *,
    tamper_resource: bool = False,
    resource_path: str = "semantic-profile.json",
) -> Path:
    profile_body = {
        "ontology_release_digest": f"sha256:{'a' * 64}",
        "package_id": "cost-governance",
        "schema_version": "1.0.0",
    }
    profile = {
        **profile_body,
        "canonical_sha256": _canonical_digest(profile_body),
    }
    profile_bytes = json.dumps(profile, sort_keys=True).encode()
    manifest = {
        "assets": [
            {
                "id": "semantic-profile:cost-governance",
                "kind": "semantic_profile",
                "path": resource_path,
                "references": [],
                "sha256": hashlib.sha256(profile_bytes).hexdigest(),
            }
        ],
        "candidate_state": "inert",
        "package_id": "cost-governance",
        "package_version": "0.1.1",
        "schema_version": "1.0.0",
    }
    wheel = tmp_path / "fdai_cost_governance-0.1.1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "fdai_cost_governance-0.1.1.dist-info/METADATA",
            "Metadata-Version: 2.4\nName: fdai-cost-governance\nVersion: 0.1.1\n",
        )
        archive.writestr(
            "fdai_cost_governance/resources/manifest.json",
            json.dumps(manifest),
        )
        archive.writestr(
            str(Path("fdai_cost_governance/resources") / resource_path),
            b"tampered" if tamper_resource else profile_bytes,
        )
    return wheel


def test_release_identity_is_derived_from_verified_wheel_bytes(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path)

    identity = _release_identity(wheel)

    assert identity.package_version == "0.1.1"
    assert identity.wheel_digest == f"sha256:{hashlib.sha256(wheel.read_bytes()).hexdigest()}"
    assert identity.semantic_profile_digest.startswith("sha256:")
    assert identity.ontology_release_digest == f"sha256:{'a' * 64}"


def test_release_identity_rejects_tampered_wheel_resource(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="resource digest mismatch"):
        _release_identity(_wheel(tmp_path, tamper_resource=True))


def test_release_identity_rejects_resource_path_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="member path escapes"):
        _release_identity(_wheel(tmp_path, resource_path="../semantic-profile.json"))


def test_runtime_config_digest_rejects_duplicate_keys(tmp_path: Path) -> None:
    config = tmp_path / "runtime-config.json"
    config.write_text('{"enabled":true,"enabled":false}', encoding="utf-8")

    with pytest.raises(ValueError, match="repeats key"):
        _runtime_config_digest(config)