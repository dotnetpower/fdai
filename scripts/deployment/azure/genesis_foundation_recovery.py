"""Validate an application-name-only residual Foundation plan without granting authority."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import cast

from fdai_deployment_cli.contracts import canonical_bytes

_APPLICATION = "azapi_resource.app_resource_group"
_POLICY_TAGS = {"FirstPartyUsage": "/Unprivileged"}
_INPUT_CHANGES = {"application_workload", "operations_public_ip_tags"}


def validate_recovery_plan(
    projection: Mapping[str, object],
    original: Mapping[str, object],
    state: Mapping[str, object],
    *,
    application_workload: str,
) -> dict[str, object]:
    """Allow only a new application name and original pending creates on retained state.

    Configuration and provider bytes must be bound separately by the planner. Existing state
    addresses and IDs cannot change; tainted/deposed instances, imports, deferred actions and
    known-setting drift are rejected. This inspection never authorizes or executes a plan.
    """
    if re.fullmatch(r"[a-z][a-z0-9]{1,11}", application_workload) is None:
        raise ValueError("Foundation recovery application workload is invalid")
    if (
        projection.get("complete") is not True
        or projection.get("errored") is not False
        or projection.get("applyable") is not True
        or projection.get("deferred_changes")
    ):
        raise ValueError("Foundation recovery plan is incomplete")
    checks = projection.get("checks", [])
    if not isinstance(checks, list) or any(
        not isinstance(check, dict) or check.get("status") not in {"pass", "unknown"}
        for check in checks
    ):
        raise ValueError("Foundation recovery plan checks failed")
    variables = projection.get("variables")
    old_variables = original.get("variables")
    if (
        not isinstance(variables, dict)
        or not isinstance(old_variables, dict)
        or variables.get("application_workload") != {"value": application_workload}
        or canonical_bytes(
            {key: value for key, value in variables.items() if key not in _INPUT_CHANGES}
        )
        != canonical_bytes(
            {key: value for key, value in old_variables.items() if key not in _INPUT_CHANGES}
        )
    ):
        raise ValueError("Foundation recovery changed inputs beyond the application name")
    old_changes = _changes(original)
    changes = _changes(projection)
    existing = _state_instances(state)
    if variables.get("operations_public_ip_tags", {"value": {}}) != {
        "value": select_public_ip_tags(state)
    }:
        raise ValueError("Foundation recovery IP tags differ from the retained policy value")
    if set(changes) != set(old_changes) or not existing.keys() <= changes.keys():
        raise ValueError("Foundation recovery inventory changed")
    if _APPLICATION not in changes or _APPLICATION in existing:
        raise ValueError("Foundation recovery cannot rename or adopt a managed application group")
    pending = []
    for address, entry in changes.items():
        prior = old_changes[address]
        change, old_change = entry.get("change"), prior.get("change")
        if (
            not isinstance(change, dict)
            or not isinstance(old_change, dict)
            or entry.get("type") != prior.get("type")
            or entry.get("mode") != prior.get("mode")
            or change.get("importing") is not None
            or entry.get("previous_address") is not None
        ):
            raise ValueError("Foundation recovery resource identity changed")
        actions = change.get("actions")
        if entry.get("mode") == "data":
            if actions not in (["read"], ["no-op"]):
                raise ValueError("Foundation recovery data source has effects")
            continue
        if entry.get("mode") != "managed" or old_change.get("actions") != ["create"]:
            raise ValueError("Foundation recovery original plan is not create-only")
        intended = old_change.get("after")
        actual = change.get("after")
        if not isinstance(intended, dict) or not isinstance(actual, dict):
            raise ValueError("Foundation recovery resource values are incomplete")
        if address in existing:
            if (
                actions != ["no-op"]
                or change.get("before") != actual
                or actual.get("id") != existing[address]["id"]
            ):
                raise ValueError("Foundation recovery would alter completed work")
            intended = existing[address]
        else:
            if actions != ["create"] or change.get("before") is not None:
                raise ValueError("Foundation recovery pending resource is not a fresh create")
            pending.append(address)
        if address == _APPLICATION:
            name = actual.get("name")
            if not isinstance(name, str) or not name or name == intended.get("name"):
                raise ValueError("Foundation recovery requires a distinct application group")
            intended = {**intended, "name": name}
        if not _same_known(intended, actual, old_change.get("after_unknown", {})):
            raise ValueError("Foundation recovery changed a known resource setting")
    return {
        "state": "review",
        "preserved_managed_count": len(existing),
        "remaining_addresses": sorted(pending),
        "apply_authorized": False,
        "mutation_performed": False,
        "deployment_ready": False,
    }


def _changes(projection: Mapping[str, object]) -> dict[str, dict[str, object]]:
    entries = projection.get("resource_changes")
    if not isinstance(entries, list):
        raise ValueError("Foundation recovery resource inventory is unavailable")
    result = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("address"), str):
            raise ValueError("Foundation recovery resource entry is invalid")
        address = entry["address"]
        if address in result:
            raise ValueError("Foundation recovery resource entry is duplicated")
        result[address] = entry
    return result


def _state_instances(state: Mapping[str, object]) -> dict[str, dict[str, object]]:
    if (
        state.get("version") != 4
        or type(state.get("serial")) is not int
        or not isinstance(state.get("lineage"), str)
        or not state["lineage"]
        or not isinstance(state.get("resources"), list)
    ):
        raise ValueError("Foundation recovery state is invalid")
    resources = cast(list[object], state["resources"])
    result = {}
    for resource in resources:
        if not isinstance(resource, dict):
            raise ValueError("Foundation recovery state resource is invalid")
        if resource.get("mode") != "managed":
            continue
        parts = [resource.get("module", ""), resource.get("type"), resource.get("name")]
        if any(not isinstance(part, str) for part in parts) or not parts[1] or not parts[2]:
            raise ValueError("Foundation recovery state address is invalid")
        prefix = ".".join(str(part) for part in parts if part)
        instances = resource.get("instances")
        if not isinstance(instances, list) or not instances:
            raise ValueError("Foundation recovery state instances are unavailable")
        for instance in instances:
            if (
                not isinstance(instance, dict)
                or instance.get("deposed")
                or instance.get("status") not in (None, "ready")
            ):
                raise ValueError("Foundation recovery state includes an incomplete instance")
            index = instance.get("index_key")
            if index is not None and type(index) not in {int, str}:
                raise ValueError("Foundation recovery state index is invalid")
            address = prefix + (f"[{json.dumps(index)}]" if index is not None else "")
            attributes = instance.get("attributes")
            identifier = attributes.get("id") if isinstance(attributes, dict) else None
            if not isinstance(identifier, str) or not identifier or address in result:
                raise ValueError("Foundation recovery state identity is invalid")
            attributes = cast(dict[str, object], attributes)
            decoded = dict(attributes)
            if str(resource["type"]).startswith("azapi_"):
                for field in ("body", "output"):
                    value = decoded.get(field)
                    if isinstance(value, dict) and set(value) == {"type", "value"}:
                        decoded[field] = value["value"]
            result[address] = decoded
    if not result:
        raise ValueError("Foundation recovery requires existing managed state")
    return result


def select_public_ip_tags(state: Mapping[str, object]) -> dict[str, str]:
    """Accept only equal empty or exact policy-owned tags on retained Bastion/NAT IPs."""
    instances = _state_instances(state)
    addresses = {
        "module.bootstrap.azurerm_public_ip.bastion[0]",
        "module.bootstrap.azurerm_public_ip.nat[0]",
    }
    present = addresses & instances.keys()
    if not present:
        return {}
    if present != addresses:
        raise ValueError("Foundation recovery public IP policy evidence is incomplete")
    values = [instances[address].get("ip_tags") for address in sorted(addresses)]
    tags = [{} if value is None else value for value in values]
    if tags[0] != tags[1] or tags[0] not in ({}, _POLICY_TAGS):
        raise ValueError("Foundation recovery public IP policy tags are unsupported")
    return dict(cast(dict[str, str], tags[0]))


def _same_known(expected: object, actual: object, unknown: object) -> bool:
    if unknown is True:
        return True
    if (expected is None or expected == "" or expected == [] or expected == {}) and (
        actual is None or actual == "" or actual == [] or actual == {}
    ):
        return True
    if isinstance(expected, dict):
        fields = unknown if isinstance(unknown, dict) else {}
        return isinstance(actual, dict) and all(
            key in actual and _same_known(value, actual[key], fields.get(key, False))
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        items = unknown if isinstance(unknown, list) else []
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(
                _same_known(value, actual[index], items[index] if index < len(items) else False)
                for index, value in enumerate(expected)
            )
        )
    return type(expected) is type(actual) and expected == actual
