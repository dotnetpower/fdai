import pytest
from fdai_operator_service.control_enablement_projection import admitted_control_enablement
from fdai_service_contracts.control_enablement import resolve_control_enablement


def _result(severity: str, enabled: bool | None = None) -> dict[str, object]:
    setting = resolve_control_enablement(severity, enabled=enabled)
    return {
        "enablement": setting.to_dict(),
        "evaluation": "not_evaluated",
        "satisfaction": "unknown",
        "evidence_complete": False,
        "limitations": [] if setting.enabled else ["control_disabled"],
    }


def test_defaults_and_explicit_disable_are_admitted_without_authority() -> None:
    for severity in ("critical", "high", "medium", "low", "informational"):
        catalog = {
            "severity": severity,
            "enablement": resolve_control_enablement(severity).to_dict(),
        }
        assert admitted_control_enablement(catalog, _result(severity)) == catalog["enablement"]
        overridden = admitted_control_enablement(
            catalog, _result(severity, False), enabled_override=False
        )
        assert overridden is not None
        assert overridden["enabled"] is False
        assert overridden["execution_authority"] is False


def test_result_cannot_silently_override_profile_or_escalate_authority() -> None:
    catalog = {"severity": "medium", "enablement": resolve_control_enablement("medium").to_dict()}
    with pytest.raises(ValueError, match="reviewed control setting"):
        admitted_control_enablement(catalog, _result("medium", False))
    result = _result("medium")
    result["enablement"] = {
        **resolve_control_enablement("medium").to_dict(),
        "execution_authority": True,
    }
    with pytest.raises(ValueError, match="reviewed control setting"):
        admitted_control_enablement(catalog, result)


def test_disabled_result_cannot_claim_satisfaction() -> None:
    result = {**_result("low"), "evaluation": "evaluated", "satisfaction": "satisfied"}
    with pytest.raises(ValueError, match="disabled control"):
        admitted_control_enablement({"severity": "low"}, result)


def test_new_catalog_rejects_legacy_result_missing_enablement() -> None:
    with pytest.raises(ValueError, match="missing or malformed"):
        admitted_control_enablement({"severity": "medium", "enablement": {}}, {})
    assert admitted_control_enablement({}, {}) is None
