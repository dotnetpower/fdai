import json
from pathlib import Path

import pytest
from fdai.delivery.control_enablement_profile import load_control_enablement_profiles
from fdai_service_contracts.control_enablement_profile import ControlEnablementProfile


def _material() -> dict[str, object]:
    material = {
        "schema_version": "1.0.0",
        "framework_id": "azure-waf",
        "source_revision": "sha256:" + "1" * 64,
        "scope_digest": "sha256:" + "2" * 64,
        "reviewed_by": "framework-reviewer",
        "reviewed_at": "2026-10-30T00:00:00Z",
        "overrides": [{"control_id": "RE:01", "enabled": False}],
    }
    return {**material, "profile_digest": ControlEnablementProfile.digest_material(material)}


def test_missing_optional_profile_preserves_severity_defaults() -> None:
    assert load_control_enablement_profiles(None) is None


def test_loader_preserves_explicit_false_and_reviewed_digest(tmp_path: Path) -> None:
    path = tmp_path / "controls.json"
    path.write_text(json.dumps({"schema_version": "1.0.0", "profiles": [_material()]}))
    bundle = load_control_enablement_profiles(path)
    assert bundle is not None
    profile = bundle.for_framework("azure-waf")
    assert profile is not None
    assert profile.override_for("RE:01") is False
    assert bundle.for_framework("azure-caf") is None


def test_unreadable_profile_is_an_explicit_failure(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unavailable"):
        load_control_enablement_profiles(tmp_path / "missing.json")


@pytest.mark.parametrize("contents", ["not-json", "{}"])
def test_malformed_profile_is_an_explicit_failure(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "controls.json"
    path.write_text(contents)
    with pytest.raises(ValueError, match="invalid"):
        load_control_enablement_profiles(path)


def test_oversized_profile_is_rejected_before_decode(tmp_path: Path) -> None:
    path = tmp_path / "controls.json"
    path.write_bytes(b" " * 65_537)
    with pytest.raises(ValueError, match="byte limit"):
        load_control_enablement_profiles(path)
