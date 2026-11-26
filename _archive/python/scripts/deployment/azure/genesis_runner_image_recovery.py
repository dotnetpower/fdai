"""Inspect residual runner-image plans without authorizing or repeating a claimed apply."""

from __future__ import annotations

from collections.abc import Mapping

from fdai_deployment_cli.contracts import canonical_bytes
from genesis_runner_image_contract import _EXPECTED_RESOURCE_TYPES

_WAIT = "terraform_data.await_builder_poweroff"
_PENDING = frozenset(
    {
        "azapi_resource_action.builder_deallocate",
        "azapi_resource_action.builder_generalize",
        "azapi_resource_action.verifier_deallocate",
        "azurerm_image.runner",
        "azurerm_linux_virtual_machine.verifier",
        "azurerm_virtual_machine_extension.verifier",
    }
)
_READ = "data.azapi_resource.runner_image"


def validate_residual_plan(
    projection: Mapping[str, object], original: Mapping[str, object]
) -> dict[str, object]:
    """Accept only unexecuted image-finalization work after a failed local poweroff wait.

    This is an action-boundary check, not execution authority or proof of current Azure
    state. The planner must separately bind original claim/state, variables and the exact
    corrected Terraform root. Existing Azure resources and commands must remain no-op;
    only the local Terraform wait marker may be replaced. Unknown, duplicate, omitted,
    unverified drift, deferred, incomplete or error-bearing plans are rejected.
    """
    if (
        projection.get("errored") is not False
        or projection.get("complete") is not True
        or projection.get("applyable") is not True
        or projection.get("deferred_changes")
    ):
        raise ValueError("runner image residual plan is incomplete or drifted")
    checks = projection.get("checks", [])
    if not isinstance(checks, list) or any(
        not isinstance(check, dict) or check.get("status") not in {"pass", "unknown"}
        for check in checks
    ):
        raise ValueError("runner image residual plan has failed checks")
    original_changes = _changes(original)
    changes = _changes(projection)
    if set(changes) != set(original_changes) or set(changes) != set(_EXPECTED_RESOURCE_TYPES) | {
        _READ
    }:
        raise ValueError("runner image residual inventory differs from the approved inventory")
    refresh_count = _validate_refresh(
        projection.get("resource_drift", []), changes, original_changes
    )
    pending = []
    preserved = 0
    for address, entry in changes.items():
        change = entry.get("change")
        before = original_changes[address].get("change")
        if not isinstance(change, dict) or not isinstance(before, dict):
            raise ValueError("runner image residual change is invalid")
        expected_type = "azapi_resource" if address == _READ else _EXPECTED_RESOURCE_TYPES[address]
        if entry.get("type") != expected_type or entry.get("mode") != (
            "data" if address == _READ else "managed"
        ):
            raise ValueError("runner image residual resource identity differs")
        actions = change.get("actions")
        if address == _READ:
            if actions not in (["read"], ["no-op"]):
                raise ValueError("runner image residual data source has effects")
        elif address == _WAIT:
            if actions != ["delete", "create"]:
                raise ValueError(
                    "runner image residual plan must replace only its failed local wait"
                )
            pending.append(address)
        elif address in _PENDING:
            if actions != ["create"] or change.get("before") is not None:
                raise ValueError("runner image residual finalization is already present or changed")
            if not _same_known(
                before.get("after"), change.get("after"), before.get("after_unknown", {})
            ):
                raise ValueError(
                    "runner image residual finalization differs from the original intent"
                )
            pending.append(address)
        else:
            if actions != ["no-op"] or change.get("before") != change.get("after"):
                raise ValueError("runner image residual plan would repeat or modify completed work")
            preserved += 1
    return {
        "state": "review",
        "remaining_addresses": sorted(pending),
        "preserved_managed_count": preserved,
        "verified_refresh_count": refresh_count,
        "apply_authorized": False,
        "mutation_performed": False,
        "deployment_ready": False,
    }


def _changes(projection: Mapping[str, object]) -> dict[str, dict[str, object]]:
    entries = projection.get("resource_changes")
    if not isinstance(entries, list):
        raise ValueError("runner image residual plan has no resource inventory")
    result = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("address"), str):
            raise ValueError("runner image residual resource record is invalid")
        address = entry["address"]
        if address in result:
            raise ValueError("runner image residual resource record is duplicated")
        result[address] = entry
    return result


def _same_known(original: object, actual: object, unknown: object) -> bool:
    if unknown is True:
        return True
    if isinstance(original, dict):
        unknown_fields = unknown if isinstance(unknown, dict) else {}
        return isinstance(actual, dict) and all(
            key in actual and _same_known(value, actual[key], unknown_fields.get(key, False))
            for key, value in original.items()
        )
    if isinstance(original, list):
        unknown_items = unknown if isinstance(unknown, list) else []
        return (
            isinstance(actual, list)
            and len(original) == len(actual)
            and all(
                _same_known(
                    value,
                    actual[index],
                    unknown_items[index] if index < len(unknown_items) else False,
                )
                for index, value in enumerate(original)
            )
        )
    return type(original) is type(actual) and original == actual


def _validate_refresh(
    entries: object,
    changes: dict[str, dict[str, object]],
    original: dict[str, dict[str, object]],
) -> int:
    if not isinstance(entries, list):
        raise ValueError("runner image residual refresh observations are invalid")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("address"), str):
            raise ValueError("runner image residual refresh record is invalid")
        address = entry["address"]
        if address in seen or address not in changes or address in _PENDING | {_WAIT, _READ}:
            raise ValueError("runner image residual refresh identity is invalid")
        seen.add(address)
        delta = entry.get("change")
        intended = original[address].get("change")
        planned = changes[address].get("change")
        if (
            not isinstance(delta, dict)
            or not isinstance(intended, dict)
            or not isinstance(planned, dict)
            or delta.get("actions") != ["update"]
            or planned.get("actions") != ["no-op"]
            or entry.get("type") != changes[address].get("type")
            or entry.get("mode") != "managed"
        ):
            raise ValueError("runner image residual refresh would alter completed work")
        before, after = delta.get("before"), delta.get("after")
        if (
            not isinstance(before, dict)
            or not isinstance(after, dict)
            or not isinstance(before.get("id"), str)
            or not before["id"]
            or before.get("id") != after.get("id")
            or after != planned.get("before")
        ):
            raise ValueError("runner image residual refresh changed resource identity")
        unknown = intended.get("after_unknown", {})
        if not isinstance(unknown, dict):
            raise ValueError("runner image original unknown-field evidence is invalid")
        for key in set(before) | set(after):
            if before.get(key) == after.get(key) or unknown.get(key) is True:
                continue
            if _normalized(
                before.get(key), unordered=key == "application_rule_collection"
            ) != _normalized(after.get(key), unordered=key == "application_rule_collection"):
                raise ValueError(
                    "runner image residual refresh changed a known configuration field"
                )
    return len(seen)


def _normalized(value: object, *, unordered: bool) -> object:
    if value is None or value == [] or value == {} or value == "":
        return None
    if isinstance(value, dict):
        return {key: _normalized(item, unordered=unordered) for key, item in value.items()}
    if isinstance(value, list):
        result = [_normalized(item, unordered=unordered) for item in value]
        return sorted(result, key=canonical_bytes) if unordered else result
    return value
