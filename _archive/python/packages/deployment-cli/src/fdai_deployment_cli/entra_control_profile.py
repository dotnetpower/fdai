"""Strict reviewed-control profile validation for bounded Entra convergence."""

from __future__ import annotations

import re
from typing import Any

_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_SLOTS = frozenset({"readers", "contributors", "approvers", "owners", "break_glass"})
_METHODS = frozenset({"fido2", "windowsHelloForBusiness", "x509Certificate"})


def validate_control_profile(value: dict[str, Any]) -> None:
    if (
        set(value)
        != {
            "schema_version",
            "premium_service_plan",
            "role_groups",
            "conditional_access_policies",
            "access_reviews",
            "authentication_methods",
            "azure_policy_assignments",
        }
        or value.get("schema_version") != "fdai.entra-control-profile.v1"
    ):
        raise ValueError("Entra control profile fields are invalid")
    if value.get("premium_service_plan") not in {"AAD_PREMIUM", "AAD_PREMIUM_P2"}:
        raise ValueError("Entra premium service plan is invalid")
    groups = value.get("role_groups")
    if (
        not isinstance(groups, dict)
        or set(groups) != _SLOTS
        or any(
            not isinstance(item, str) or _GUID.fullmatch(item) is None for item in groups.values()
        )
        or len(set(groups.values())) != len(_SLOTS)
    ):
        raise ValueError("Entra role group profile is invalid")
    _validate_ca(value.get("conditional_access_policies"))
    _validate_reviews(value.get("access_reviews"))
    _validate_methods(value.get("authentication_methods"))
    _validate_azure_policy(value.get("azure_policy_assignments"))


def _validate_ca(value: object) -> None:
    rows = _nonempty_dict_list(value, "Conditional Access profile")
    for row in rows:
        if set(row) != {
            "policy_id",
            "include_group_slots",
            "exclude_group_slots",
            "include_users",
            "exclude_users",
            "include_roles",
            "exclude_roles",
            "client_app_types",
            "include_applications",
            "exclude_applications",
            "include_platforms",
            "exclude_platforms",
            "include_locations",
            "exclude_locations",
            "sign_in_risk_levels",
            "user_risk_levels",
            "device_filter_mode",
            "device_filter_rule",
            "grant_operator",
            "grant_controls",
            "authentication_strength_id",
        }:
            raise ValueError("Conditional Access profile fields are invalid")
        include_slots = _sorted_strings(row["include_group_slots"])
        exclude_slots = _sorted_strings(row["exclude_group_slots"])
        controls = _sorted_strings(row["grant_controls"])
        strength = row["authentication_strength_id"]
        if (
            _GUID.fullmatch(_text(row, "policy_id")) is None
            or not include_slots
            or not set(include_slots).issubset(_SLOTS)
            or not set(exclude_slots).issubset(_SLOTS)
            or set(include_slots) & set(exclude_slots)
            or row["grant_operator"] not in {"AND", "OR"}
            or not controls
            or not set(controls).issubset({"mfa", "compliantDevice", "authenticationStrength"})
            or (
                ("authenticationStrength" in controls)
                != (isinstance(strength, str) and _GUID.fullmatch(strength) is not None)
            )
        ):
            raise ValueError("Conditional Access profile values are invalid")
        for key in (
            "include_users",
            "exclude_users",
            "include_roles",
            "exclude_roles",
            "client_app_types",
            "include_applications",
            "exclude_applications",
            "include_platforms",
            "exclude_platforms",
            "include_locations",
            "exclude_locations",
            "sign_in_risk_levels",
            "user_risk_levels",
        ):
            _sorted_strings(row[key])
        if (
            row["device_filter_mode"] not in {None, "include", "exclude"}
            or (row["device_filter_mode"] is None and row["device_filter_rule"] is not None)
            or (
                row["device_filter_mode"] is not None
                and not _bounded_ascii(row["device_filter_rule"])
            )
        ):
            raise ValueError("Conditional Access device filter is invalid")


def _validate_reviews(value: object) -> None:
    rows = _nonempty_dict_list(value, "Access Review profile")
    for row in rows:
        if set(row) != {
            "definition_id",
            "group_slot",
            "scope_query_type",
            "recurrence_pattern_type",
            "recurrence_interval",
            "recurrence_range_type",
            "duration_days",
            "allowed_statuses",
        }:
            raise ValueError("Access Review profile fields are invalid")
        if (
            _GUID.fullmatch(_text(row, "definition_id")) is None
            or row["group_slot"] not in _SLOTS
            or row["scope_query_type"] != "MicrosoftGraph"
            or row["recurrence_pattern_type"] not in {"absoluteMonthly", "weekly"}
            or type(row["recurrence_interval"]) is not int
            or not 1 <= row["recurrence_interval"] <= 12
            or row["recurrence_range_type"] not in {"noEnd", "numbered"}
            or type(row["duration_days"]) is not int
            or not 1 <= row["duration_days"] <= 30
            or not _sorted_strings(row["allowed_statuses"])
            or not set(row["allowed_statuses"]).issubset({"NotStarted", "InProgress"})
        ):
            raise ValueError("Access Review profile values are invalid")


def _validate_methods(value: object) -> None:
    rows = _nonempty_dict_list(value, "authentication method profile")
    ids = []
    for row in rows:
        if set(row) != {"method_id", "state", "include_group_slots"}:
            raise ValueError("authentication method profile fields are invalid")
        method_id = _text(row, "method_id")
        slots = _sorted_strings(row["include_group_slots"])
        if (
            method_id not in _METHODS
            or row["state"] != "enabled"
            or not slots
            or not set(slots).issubset(_SLOTS)
        ):
            raise ValueError("authentication method profile values are invalid")
        ids.append(method_id)
    if len(ids) != len(set(ids)):
        raise ValueError("authentication method profile repeats a method")


def _validate_azure_policy(value: object) -> None:
    rows = _nonempty_dict_list(value, "Azure Policy profile")
    for row in rows:
        if set(row) != {"assignment_id", "definition_id", "enforcement_mode", "scope"}:
            raise ValueError("Azure Policy profile fields are invalid")
        if (
            not _bounded_ascii(row["assignment_id"])
            or not _bounded_ascii(row["definition_id"])
            or row["enforcement_mode"] != "Default"
            or not _bounded_ascii(row["scope"])
        ):
            raise ValueError("Azure Policy profile values are invalid")


def _nonempty_dict_list(value: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("Entra control profile collection is invalid")
    if not value:
        raise ValueError(f"{label} MUST contain at least one reviewed control")
    return value


def _sorted_strings(value: object) -> list[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not _bounded_ascii(item) for item in value)
        or value != sorted(set(value))
    ):
        raise ValueError("Entra control profile string collection is invalid")
    return value


def _text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError(f"Entra profile {key} is invalid")
    return item


def _bounded_ascii(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 2048
        and value.isascii()
        and value.isprintable()
    )
