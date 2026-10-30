"""Admit server-owned assessment preferences without raising authority."""

from collections.abc import Mapping

from fdai_service_contracts.control_enablement import resolve_control_enablement


def admitted_control_enablement(
    catalog_control: Mapping[str, object],
    result: Mapping[str, object],
    *,
    enabled_override: bool | None = None,
) -> dict[str, object] | None:
    value = result.get("enablement")
    if value is None and "enablement" not in catalog_control:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("assessment control enablement is missing or malformed")
    severity = catalog_control.get("severity", catalog_control.get("impact", "medium"))
    if not isinstance(severity, str):
        raise ValueError("catalog control severity is malformed")
    expected = resolve_control_enablement(
        severity,
        enabled=enabled_override,
        active=catalog_control.get("lifecycle") != "disabled",
    ).to_dict()
    if (
        type(value.get("enabled")) is not bool
        or type(value.get("default_enabled")) is not bool
        or value.get("execution_authority") is not False
        or dict(value) != expected
    ):
        raise ValueError("assessment enablement does not match the reviewed control setting")
    if expected["enabled"] is False:
        limitations = result.get("limitations")
        if (
            result.get("evaluation") != "not_evaluated"
            or result.get("satisfaction") != "unknown"
            or result.get("evidence_complete") is not False
            or not isinstance(limitations, (list, tuple))
            or "control_disabled" not in limitations
        ):
            raise ValueError("disabled control cannot claim an evaluated outcome")
    return expected
