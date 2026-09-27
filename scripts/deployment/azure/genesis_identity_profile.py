#!/usr/bin/env python3
"""Read exact reviewed tenant controls without exposing provider identifiers."""

from __future__ import annotations

import concurrent.futures
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fdai_deployment_cli.entra_profiles import EntraControlProfile, EntraTargetProfile
from fdai_deployment_cli.identity_profile import (
    IdentityProfileEvidence,
    IdentityProfileObservation,
)
from genesis_entra import _az_json, _graph, _single_group
from genesis_identity_executor import (
    executor_execution_context,
    identity_operation_context,
)
from genesis_identity_executor import (
    executor_identity as _executor_identity,
)

_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_GROUP_NAMES = {
    "readers": "aw-readers",
    "contributors": "aw-contributors",
    "approvers": "aw-approvers",
    "owners": "aw-owners",
    "break_glass": "aw-break-glass",
}


def observe_identity_profile(
    target: EntraTargetProfile,
    controls: EntraControlProfile,
) -> tuple[IdentityProfileObservation, str | None]:
    """Collect bounded reads and compare only exact profile-declared controls."""

    with identity_operation_context():
        return _observe_identity_profile_serialized(target, controls)


def _observe_identity_profile_serialized(
    target: EntraTargetProfile,
    controls: EntraControlProfile,
) -> tuple[IdentityProfileObservation, str | None]:
    human = _optional(_human_identity)
    human_approver = _optional(lambda: _human_approver_authorized(controls))
    executor_evidence = _optional(lambda: _executor_profile_evidence(target, controls))
    premium = executor_evidence.premium if executor_evidence is not None else None
    groups = executor_evidence.groups if executor_evidence is not None else None
    conditional_access = (
        executor_evidence.conditional_access if executor_evidence is not None else None
    )
    access_review = executor_evidence.access_review if executor_evidence is not None else None
    authentication = executor_evidence.authentication if executor_evidence is not None else None
    azure_policy = executor_evidence.azure_policy if executor_evidence is not None else None
    executor_identity = (
        executor_evidence.executor_identity if executor_evidence is not None else None
    )
    executor_present = (
        None
        if executor_identity is None
        else executor_identity[0].casefold() == target.executor_object_id.casefold()
    )
    separated = (
        None
        if human is None or executor_identity is None
        else human.casefold() != executor_identity[0].casefold()
    )
    observation = IdentityProfileObservation.from_evidence(
        IdentityProfileEvidence(
            premium_license_eligible=premium,
            role_groups_present=None if groups is None else groups[0],
            role_group_profile_match=None if groups is None else groups[1],
            conditional_access_policy_present=conditional_access,
            access_review_present=access_review,
            authentication_method_policy_present=(
                None if authentication is None else authentication[0]
            ),
            phishing_resistant_method_enabled=(
                None if authentication is None else authentication[1]
            ),
            azure_policy_assignment_present=azure_policy,
            human_identity_present=None if human is None else True,
            human_approver_authorized=human_approver,
            executor_identity_present=executor_present,
            executor_is_managed_identity=(
                None if executor_identity is None else executor_identity[1]
            ),
            executor_profile_match=(None if executor_identity is None else executor_identity[2]),
            human_executor_separated=separated,
        )
    )
    return observation, human


@dataclass(frozen=True, slots=True)
class _ExecutorProfileEvidence:
    premium: bool | None
    groups: tuple[bool, bool] | None
    conditional_access: bool | None
    access_review: bool | None
    authentication: tuple[bool, bool] | None
    azure_policy: bool | None
    executor_identity: tuple[str, bool, bool] | None


def _executor_profile_evidence(
    target: EntraTargetProfile,
    controls: EntraControlProfile,
) -> _ExecutorProfileEvidence:
    """Read every executor-owned fact under one restored Azure CLI context."""

    with executor_execution_context(target):
        return _read_executor_profile_concurrently(target, controls)


def _read_executor_profile_concurrently(
    target: EntraTargetProfile,
    controls: EntraControlProfile,
) -> _ExecutorProfileEvidence:
    """Group only executor-context reads after human evidence is complete."""

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        premium_future = executor.submit(
            _optional, lambda: _premium_license_eligible(controls.premium_service_plan)
        )
        groups_future = executor.submit(_optional, lambda: _role_groups(controls))
        conditional_access_future = executor.submit(
            _optional, lambda: _conditional_access_matches(controls)
        )
        access_review_future = executor.submit(_optional, lambda: _access_reviews_match(controls))
        authentication_future = executor.submit(
            _optional, lambda: _authentication_methods_match(controls)
        )
        azure_policy_future = executor.submit(_optional, lambda: _azure_policy_matches(controls))
        executor_future = executor.submit(_optional, lambda: _executor_identity(target))
        return _ExecutorProfileEvidence(
            premium=premium_future.result(),
            groups=groups_future.result(),
            conditional_access=conditional_access_future.result(),
            access_review=access_review_future.result(),
            authentication=authentication_future.result(),
            azure_policy=azure_policy_future.result(),
            executor_identity=executor_future.result(),
        )


def _optional[T](reader: Callable[[], T]) -> T | None:
    try:
        return reader()
    except (OSError, RuntimeError, TypeError, ValueError, subprocess.SubprocessError, TimeoutError):
        return None


def _premium_license_eligible(required_plan: str) -> bool:
    rows = _graph_collection("subscribedSkus?$select=capabilityStatus,servicePlans")
    return any(
        row.get("capabilityStatus") == "Enabled"
        and isinstance(row.get("servicePlans"), list)
        and any(
            isinstance(plan, dict)
            and plan.get("servicePlanName") == required_plan
            and plan.get("provisioningStatus") == "Success"
            for plan in row["servicePlans"]
        )
        for row in rows
    )


def _role_groups(controls: EntraControlProfile) -> tuple[bool, bool]:
    expected = controls.role_groups
    observed: dict[str, str] = {}
    for slot, name in _GROUP_NAMES.items():
        group = _single_group(name)
        if group is None:
            return False, False
        if _GUID.fullmatch(str(group.get("id", ""))) is None:
            raise ValueError("Entra role group identity is invalid")
        observed[slot] = str(group["id"])
    return True, observed == expected


def _conditional_access_matches(controls: EntraControlProfile) -> bool:
    rows = _graph_collection("identity/conditionalAccess/policies")
    groups = controls.role_groups
    for expected in controls.conditional_access_policies:
        matches = [row for row in rows if row.get("id") == expected["policy_id"]]
        if len(matches) != 1 or _project_ca(matches[0]) != _expected_ca(expected, groups):
            return False
    return True


def _project_ca(value: dict[str, Any]) -> dict[str, object]:
    conditions = value.get("conditions")
    users = conditions.get("users") if isinstance(conditions, dict) else None
    applications = conditions.get("applications") if isinstance(conditions, dict) else None
    platforms = conditions.get("platforms") if isinstance(conditions, dict) else None
    locations = conditions.get("locations") if isinstance(conditions, dict) else None
    devices = conditions.get("devices") if isinstance(conditions, dict) else None
    device_filter = devices.get("deviceFilter") if isinstance(devices, dict) else None
    grants = value.get("grantControls")
    strength = grants.get("authenticationStrength") if isinstance(grants, dict) else None
    if (
        not isinstance(conditions, dict)
        or not isinstance(users, dict)
        or not isinstance(applications, dict)
        or not isinstance(grants, dict)
    ):
        raise ValueError("Conditional Access policy readback is incomplete")
    if (
        not set(conditions).issubset(
            {
                "users",
                "clientAppTypes",
                "applications",
                "platforms",
                "locations",
                "signInRiskLevels",
                "userRiskLevels",
                "devices",
            }
        )
        or set(users)
        != {
            "includeGroups",
            "excludeGroups",
            "includeUsers",
            "excludeUsers",
            "includeRoles",
            "excludeRoles",
        }
        or set(applications) != {"includeApplications", "excludeApplications"}
        or (
            platforms is not None
            and (
                not isinstance(platforms, dict)
                or set(platforms) != {"includePlatforms", "excludePlatforms"}
            )
        )
        or (
            locations is not None
            and (
                not isinstance(locations, dict)
                or set(locations) != {"includeLocations", "excludeLocations"}
            )
        )
        or (
            devices is not None
            and (
                not isinstance(devices, dict)
                or set(devices) != {"deviceFilter"}
                or not isinstance(device_filter, dict)
                or set(device_filter) != {"mode", "rule"}
            )
        )
        or set(grants)
        != {
            "operator",
            "builtInControls",
            *(("authenticationStrength",) if strength is not None else ()),
        }
    ):
        raise ValueError("Conditional Access policy contains unreviewed conditions")
    return {
        "state": value.get("state"),
        "include_groups": _provider_strings(users.get("includeGroups")),
        "exclude_groups": _provider_strings(users.get("excludeGroups")),
        "include_users": _provider_strings(users.get("includeUsers")),
        "exclude_users": _provider_strings(users.get("excludeUsers")),
        "include_roles": _provider_strings(users.get("includeRoles")),
        "exclude_roles": _provider_strings(users.get("excludeRoles")),
        "client_app_types": _provider_strings(conditions.get("clientAppTypes")),
        "include_applications": _provider_strings(applications.get("includeApplications")),
        "exclude_applications": _provider_strings(applications.get("excludeApplications")),
        "include_platforms": _provider_strings(
            platforms.get("includePlatforms") if isinstance(platforms, dict) else []
        ),
        "exclude_platforms": _provider_strings(
            platforms.get("excludePlatforms") if isinstance(platforms, dict) else []
        ),
        "include_locations": _provider_strings(
            locations.get("includeLocations") if isinstance(locations, dict) else []
        ),
        "exclude_locations": _provider_strings(
            locations.get("excludeLocations") if isinstance(locations, dict) else []
        ),
        "sign_in_risk_levels": _provider_strings(conditions.get("signInRiskLevels", [])),
        "user_risk_levels": _provider_strings(conditions.get("userRiskLevels", [])),
        "device_filter_mode": (
            device_filter.get("mode") if isinstance(device_filter, dict) else None
        ),
        "device_filter_rule": (
            device_filter.get("rule") if isinstance(device_filter, dict) else None
        ),
        "grant_operator": grants.get("operator"),
        "grant_controls": _provider_strings(grants.get("builtInControls")),
        "authentication_strength_id": (strength.get("id") if isinstance(strength, dict) else None),
    }


def _expected_ca(value: dict[str, Any], groups: dict[str, str]) -> dict[str, object]:
    return {
        "state": "enabled",
        "include_groups": sorted(groups[str(slot)] for slot in value["include_group_slots"]),
        "exclude_groups": sorted(groups[str(slot)] for slot in value["exclude_group_slots"]),
        "include_users": value["include_users"],
        "exclude_users": value["exclude_users"],
        "include_roles": value["include_roles"],
        "exclude_roles": value["exclude_roles"],
        "client_app_types": value["client_app_types"],
        "include_applications": value["include_applications"],
        "exclude_applications": value["exclude_applications"],
        "include_platforms": value["include_platforms"],
        "exclude_platforms": value["exclude_platforms"],
        "include_locations": value["include_locations"],
        "exclude_locations": value["exclude_locations"],
        "sign_in_risk_levels": value["sign_in_risk_levels"],
        "user_risk_levels": value["user_risk_levels"],
        "device_filter_mode": value["device_filter_mode"],
        "device_filter_rule": value["device_filter_rule"],
        "grant_operator": value["grant_operator"],
        "grant_controls": value["grant_controls"],
        "authentication_strength_id": value["authentication_strength_id"],
    }


def _access_reviews_match(controls: EntraControlProfile) -> bool:
    rows = _graph_collection("identityGovernance/accessReviews/definitions")
    groups = controls.role_groups
    for expected in controls.access_reviews:
        matches = [row for row in rows if row.get("id") == expected["definition_id"]]
        if len(matches) != 1:
            return False
        projected = _project_review(matches[0])
        if projected.pop("status") not in expected["allowed_statuses"] or projected != {
            "scope_query": f"/groups/{groups[str(expected['group_slot'])]}/transitiveMembers",
            "scope_query_type": expected["scope_query_type"],
            "recurrence_pattern_type": expected["recurrence_pattern_type"],
            "recurrence_interval": expected["recurrence_interval"],
            "recurrence_range_type": expected["recurrence_range_type"],
            "duration_days": expected["duration_days"],
        }:
            return False
    return True


def _project_review(value: dict[str, Any]) -> dict[str, object]:
    scope = value.get("scope")
    settings = value.get("settings")
    recurrence = settings.get("recurrence") if isinstance(settings, dict) else None
    pattern = recurrence.get("pattern") if isinstance(recurrence, dict) else None
    range_value = recurrence.get("range") if isinstance(recurrence, dict) else None
    if (
        not isinstance(scope, dict)
        or not isinstance(settings, dict)
        or not isinstance(pattern, dict)
        or not isinstance(range_value, dict)
    ):
        raise ValueError("Access Review readback is incomplete")
    return {
        "status": value.get("status"),
        "scope_query": scope.get("query"),
        "scope_query_type": scope.get("queryType"),
        "recurrence_pattern_type": pattern.get("type"),
        "recurrence_interval": pattern.get("interval"),
        "recurrence_range_type": range_value.get("type"),
        "duration_days": settings.get("instanceDurationInDays"),
    }


def _authentication_methods_match(controls: EntraControlProfile) -> tuple[bool, bool]:
    value = _graph(
        "GET",
        "policies/authenticationMethodsPolicy?$select=authenticationMethodConfigurations",
    )
    configurations = value.get("authenticationMethodConfigurations")
    if not isinstance(configurations, list) or any(
        not isinstance(item, dict) for item in configurations
    ):
        raise ValueError("authentication method policy readback is invalid")
    observed = set()
    for item in configurations:
        targets = item.get("includeTargets")
        if not isinstance(targets, list) or any(not isinstance(target, dict) for target in targets):
            raise ValueError("authentication method targets are incomplete")
        observed.add(
            (
                str(item.get("id")),
                str(item.get("state")),
                tuple(
                    sorted(
                        str(target.get("id"))
                        for target in targets
                        if target.get("targetType") == "group"
                    )
                ),
            )
        )
    expected = {
        (
            str(item["method_id"]),
            str(item["state"]),
            tuple(sorted(controls.role_groups[str(slot)] for slot in item["include_group_slots"])),
        )
        for item in controls.authentication_methods
    }
    return True, expected.issubset(observed)


def _azure_policy_matches(controls: EntraControlProfile) -> bool:
    value = _az_json(("policy", "assignment", "list", "--disable-scope-strict-match"))
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("Azure Policy assignment readback is invalid")
    observed = {
        (
            str(item.get("id")),
            str(_policy_field(item, "policyDefinitionId")),
            str(_policy_field(item, "enforcementMode")),
            str(_policy_field(item, "scope")),
        )
        for item in value
    }
    expected = {
        (
            str(item["assignment_id"]),
            str(item["definition_id"]),
            str(item["enforcement_mode"]),
            str(item["scope"]),
        )
        for item in controls.azure_policy_assignments
    }
    return expected.issubset(observed)


def _policy_field(value: dict[str, Any], field: str) -> object:
    properties = value.get("properties")
    if isinstance(properties, dict) and field in properties:
        return properties[field]
    return value.get(field)


def _human_identity() -> str:
    value = _az_json(("ad", "signed-in-user", "show"))
    object_id = value.get("id") if isinstance(value, dict) else None
    if not isinstance(object_id, str) or _GUID.fullmatch(object_id) is None:
        raise ValueError("human identity readback is invalid")
    return object_id


def _human_approver_authorized(controls: EntraControlProfile) -> bool:
    rows = _graph_collection("me/transitiveMemberOf/microsoft.graph.group?$select=id&$top=100")
    approver_group = controls.role_groups["approvers"].casefold()
    return any(
        isinstance(row.get("id"), str) and str(row["id"]).casefold() == approver_group
        for row in rows
    )


def _graph_collection(path: str) -> list[dict[str, Any]]:
    value = _graph("GET", path)
    rows = value.get("value")
    if "@odata.nextLink" in value or not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("identity profile collection is incomplete")
    if any(not isinstance(item, dict) for item in rows):
        raise ValueError("identity profile collection is invalid")
    return rows


def _provider_strings(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("identity control string collection is invalid")
    return sorted(value)
