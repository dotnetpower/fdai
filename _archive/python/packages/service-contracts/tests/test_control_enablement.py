import pytest

from fdai_service_contracts.control_enablement import resolve_control_enablement


@pytest.mark.parametrize(
    ("severity", "expected"),
    [
        ("critical", True),
        ("high", True),
        ("medium", True),
        ("low", False),
        ("informational", False),
        ("High", True),
        ("Medium", True),
        ("Low", False),
        ("info", False),
    ],
)
def test_default_enablement_has_exact_medium_threshold(severity: str, expected: bool) -> None:
    setting = resolve_control_enablement(severity)
    assert setting.enabled is expected
    assert setting.default_enabled is expected
    assert setting.source == "severity_default"
    assert setting.to_dict()["mode"] == "shadow"
    assert setting.to_dict()["execution_authority"] is False


@pytest.mark.parametrize("severity", ["critical", "high", "medium", "low", "informational"])
@pytest.mark.parametrize("enabled", [True, False])
def test_explicit_setting_takes_precedence(severity: str, enabled: bool) -> None:
    setting = resolve_control_enablement(severity, enabled=enabled)
    assert setting.enabled is enabled
    assert setting.source == "profile_override"


@pytest.mark.parametrize("severity", ["critical", "high", "medium", "low", "informational"])
def test_historical_control_cannot_be_enabled(severity: str) -> None:
    setting = resolve_control_enablement(severity, enabled=True, active=False)
    assert setting.enabled is False
    assert setting.source == "lifecycle_disabled"


@pytest.mark.parametrize("severity", ["", "urgent", " medium", "sev1"])
def test_unknown_priority_is_not_silently_enabled(severity: str) -> None:
    with pytest.raises(ValueError):
        resolve_control_enablement(severity)


@pytest.mark.parametrize("value", [0, 1, "true", "false"])
def test_non_boolean_override_is_rejected(value: object) -> None:
    with pytest.raises(ValueError, match="boolean"):
        resolve_control_enablement("medium", enabled=value)  # type: ignore[arg-type]
