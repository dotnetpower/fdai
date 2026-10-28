import pytest
from fdai_operator_service.families.iam.errors import IamUnavailableError
from fdai_operator_service.postgres_iam_configuration_projection import (
    validate_runtime_setting_value,
)

SETTING = {"key": "detection.resource_availability", "value_type": "object"}


def test_structured_availability_policy_uses_the_canonical_validator() -> None:
    value = {"enabled": False, "resource_types": [], "resources": {}, "max_age_seconds": 300}
    result = validate_runtime_setting_value(SETTING, value)
    assert isinstance(result, dict)
    assert result["enabled"] is False
    assert result["resources"] == {}


@pytest.mark.parametrize("value", ["{}", [], True, {"unexpected": True}])
def test_invalid_policy_is_rejected_before_an_override_is_stored(value: object) -> None:
    with pytest.raises(ValueError):
        validate_runtime_setting_value(SETTING, value)


def test_unregistered_object_setting_cannot_expand_the_configuration_surface() -> None:
    with pytest.raises(IamUnavailableError, match="unregistered"):
        validate_runtime_setting_value({"key": "unregistered", "value_type": "object"}, {})
