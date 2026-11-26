"""Classify retained runner-image drift caused by tenant patch-orchestration policy."""

from __future__ import annotations

from collections.abc import Mapping

TENANT_PATCH_POLICY_ATTRIBUTES = frozenset(
    {
        "bypass_platform_safety_checks_on_user_schedule_enabled",
        "patch_assessment_mode",
        "patch_mode",
    }
)
_PATCH_POLICY_VM_ADDRESSES = frozenset(
    {
        "azurerm_linux_virtual_machine.builder",
        "azurerm_linux_virtual_machine.verifier",
    }
)
_SUPPORTED_MODES = frozenset({"ImageDefault", "AutomaticByPlatform"})
_ERROR = "runner image zero-change verification failed"


def tenant_patch_policy_drift(plan: Mapping[str, object]) -> tuple[str, ...]:
    """Return the VMs whose only planned change reverts tenant patch-policy settings.

    The deallocated builder and verifier VMs can receive a tenant's platform-patching settings
    after the image receipt exists. Every other planned change still fails closed.
    """

    changes = plan.get("resource_changes")
    if not isinstance(changes, list):
        raise ValueError(_ERROR)
    tolerated: list[str] = []
    for item in changes:
        if not isinstance(item, Mapping) or not isinstance(item.get("change"), Mapping):
            raise ValueError(_ERROR)
        change = item["change"]
        actions = change.get("actions")
        if actions == ["no-op"]:
            continue
        if item.get("mode") == "data" and actions == ["read"]:
            continue
        address = item.get("address")
        if (
            item.get("mode") != "managed"
            or address not in _PATCH_POLICY_VM_ADDRESSES
            or actions != ["update"]
        ):
            raise ValueError(_ERROR)
        changed = _changed_attributes(change)
        if not changed or not changed <= TENANT_PATCH_POLICY_ATTRIBUTES:
            raise ValueError(_ERROR)
        _require_supported_selection(change["before"])
        tolerated.append(str(address))
    if not tolerated:
        raise ValueError(_ERROR)
    return tuple(sorted(tolerated))


def _changed_attributes(change: Mapping[str, object]) -> frozenset[str]:
    before = change.get("before")
    after = change.get("after")
    unknown = change.get("after_unknown")
    if (
        not isinstance(before, Mapping)
        or not isinstance(after, Mapping)
        or not isinstance(unknown, Mapping)
    ):
        raise ValueError(_ERROR)
    changed = {
        str(key) for key in before.keys() | after.keys() if before.get(key) != after.get(key)
    }
    changed.update(str(key) for key, value in unknown.items() if _contains_unknown(value))
    return frozenset(changed)


def _contains_unknown(value: object) -> bool:
    if value is True:
        return True
    if isinstance(value, Mapping):
        return any(_contains_unknown(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_unknown(item) for item in value)
    return False


def _require_supported_selection(observed: object) -> None:
    if not isinstance(observed, Mapping):
        raise ValueError(_ERROR)
    mode = observed.get("patch_mode")
    assessment = observed.get("patch_assessment_mode")
    bypass = observed.get("bypass_platform_safety_checks_on_user_schedule_enabled")
    if (
        mode not in _SUPPORTED_MODES
        or assessment not in {None, *_SUPPORTED_MODES}
        or not isinstance(bypass, bool)
        or (bypass and mode != "AutomaticByPlatform")
    ):
        raise ValueError(_ERROR)
