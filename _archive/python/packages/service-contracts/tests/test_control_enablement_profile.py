from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from fdai_service_contracts.control_enablement_profile import (
    ControlEnablementProfile,
    ControlEnablementProfiles,
)

NOW = datetime(2026, 10, 30, tzinfo=UTC)
SCOPE = "sha256:" + "1" * 64


def _material() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "framework_id": "azure-waf",
        "source_revision": "sha256:" + "2" * 64,
        "scope_digest": SCOPE,
        "reviewed_by": "framework-reviewer",
        "reviewed_at": "2026-10-30T00:00:00Z",
        "overrides": [{"control_id": "RE:01", "enabled": False}],
    }


def _profile(material: dict[str, object] | None = None) -> ControlEnablementProfile:
    value = material or _material()
    return ControlEnablementProfile.model_validate(
        {**value, "profile_digest": ControlEnablementProfile.digest_material(value)}
    )


def test_reviewed_profile_is_exact_and_preserves_false() -> None:
    profile = _profile()
    profile.validate_binding(
        framework_id="azure-waf",
        source_revision="sha256:" + "2" * 64,
        scope_digest=SCOPE,
        evaluated_at=NOW,
        control_ids={"RE:01"},
    )
    assert profile.override_for("RE:01") is False
    assert profile.override_for("RE:02") is None
    assert ControlEnablementProfile.model_validate_json(profile.model_dump_json()) == profile


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("framework_id", "azure-caf"),
        ("source_revision", "sha256:" + "3" * 64),
        ("scope_digest", "sha256:" + "4" * 64),
    ],
)
def test_profile_rejects_binding_drift(field: str, value: str) -> None:
    binding = {
        "framework_id": "azure-waf",
        "source_revision": "sha256:" + "2" * 64,
        "scope_digest": SCOPE,
        "evaluated_at": NOW,
        "control_ids": {"RE:01"},
        field: value,
    }
    with pytest.raises(ValueError, match="binding mismatch"):
        _profile().validate_binding(**binding)  # type: ignore[arg-type]


def test_profile_rejects_tampering() -> None:
    material = _profile().model_dump(mode="json")
    material["overrides"] = [{"control_id": "RE:01", "enabled": True}]
    with pytest.raises(ValidationError, match="digest mismatch"):
        ControlEnablementProfile.model_validate(material)


@pytest.mark.parametrize("enabled", [0, 1, "false", None])
def test_override_requires_a_real_boolean(enabled: object) -> None:
    material = _material()
    material["overrides"] = [{"control_id": "RE:01", "enabled": enabled}]
    with pytest.raises(ValidationError):
        _profile(material)


def test_profile_rejects_duplicate_controls() -> None:
    material = _material()
    material["overrides"] = [
        {"control_id": "RE:01", "enabled": True},
        {"control_id": "RE:01", "enabled": False},
    ]
    with pytest.raises(ValidationError, match="unique and ordered"):
        _profile(material)


def test_profile_rejects_future_review_and_unknown_control() -> None:
    for evaluated_at, control_ids, expected in [
        (NOW - timedelta(seconds=1), {"RE:01"}, "cutoff"),
        (NOW, {"RE:02"}, "unknown control"),
    ]:
        with pytest.raises(ValueError, match=expected):
            _profile().validate_binding(
                framework_id="azure-waf",
                source_revision="sha256:" + "2" * 64,
                scope_digest=SCOPE,
                evaluated_at=evaluated_at,
                control_ids=control_ids,
            )


def test_bundle_rejects_duplicate_frameworks() -> None:
    material = _profile().model_dump(mode="json")
    with pytest.raises(ValidationError, match="duplicate frameworks"):
        ControlEnablementProfiles.model_validate(
            {"schema_version": "1.0.0", "profiles": [material, material]}
        )
