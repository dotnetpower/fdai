"""Azure Policy deny parsing for live deployment preflight."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .transport import AzureReader, PreflightError


def azure_policy_findings(
    reader: AzureReader,
    *,
    subscription_id: str,
    resource_group: str,
    neutral_types: tuple[str, ...],
    arm_type_map: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Return grounded findings for planned ARM types denied at the target scope."""
    arm_types: set[str] = set()
    for neutral_type in neutral_types:
        arm_type = neutral_type if "/" in neutral_type else arm_type_map.get(neutral_type)
        if not arm_type:
            raise PreflightError("ARM resource type mapping is incomplete")
        arm_types.add(arm_type)
    if not arm_types:
        return []
    scope = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
    assignments = reader.get_values(
        f"{scope}/providers/Microsoft.Authorization/policyAssignments",
        api_version="2022-06-01",
        params={"$filter": "atScope()"},
    )
    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for assignment in assignments:
        properties = assignment.get("properties")
        if not isinstance(properties, Mapping):
            continue
        definition_id = properties.get("policyDefinitionId")
        if not isinstance(definition_id, str) or not definition_id.startswith("/"):
            continue
        definition = reader.get_json(definition_id, api_version="2021-06-01")
        parsed = _parse_policy_definition(
            definition, assignment_parameters=properties.get("parameters")
        )
        if parsed is None:
            continue
        mode, listed_types, policy_ref = parsed
        denied = (
            {value for value in arm_types if _casefold_contains(listed_types, value)}
            if mode == "not_allowed"
            else {value for value in arm_types if not _casefold_contains(listed_types, value)}
        )
        for resource_type in sorted(denied):
            key = (policy_ref, resource_type.casefold())
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                {
                    "id": f"policy-deny:{policy_ref}:{resource_type}",
                    "category": "policy_guardrail",
                    "severity": "blocking",
                    "title": "Azure Policy denies a planned resource type",
                }
            )
    return findings


def _parse_policy_definition(
    definition: Mapping[str, Any], *, assignment_parameters: Any
) -> tuple[str, frozenset[str], str] | None:
    properties = definition.get("properties")
    if not isinstance(properties, Mapping):
        return None
    rule = properties.get("policyRule")
    if not isinstance(rule, Mapping):
        return None
    parameters = _merged_parameters(properties.get("parameters"), assignment_parameters)
    then = rule.get("then")
    if not isinstance(then, Mapping):
        return None
    effect = _resolve(then.get("effect"), parameters)
    if not isinstance(effect, str) or effect.casefold() != "deny":
        return None
    condition = _unwrap(rule.get("if"))
    if not isinstance(condition, Mapping):
        return None
    parsed = _parse_type_condition(condition, parameters)
    if parsed is None:
        return None
    name = definition.get("name")
    policy_ref = name if isinstance(name, str) and name else "unknown-policy"
    return parsed[0], parsed[1], policy_ref


def _parse_type_condition(
    condition: Mapping[str, Any], parameters: Mapping[str, Any]
) -> tuple[str, frozenset[str]] | None:
    negated = _unwrap(condition.get("not"))
    if isinstance(negated, Mapping):
        values = _type_values(negated, parameters)
        return None if values is None else ("allowed", values)
    values = _type_values(condition, parameters)
    if values is not None:
        return "not_allowed", values
    children = condition.get("allOf")
    if not isinstance(children, list) or not 1 <= len(children) <= 8:
        return None
    parsed: tuple[str, frozenset[str]] | None = None
    for child in children:
        unwrapped = _unwrap(child)
        if not isinstance(unwrapped, Mapping):
            return None
        values = _type_values(unwrapped, parameters)
        mode = "not_allowed"
        if values is None:
            nested = _unwrap(unwrapped.get("not"))
            values = _type_values(nested, parameters) if isinstance(nested, Mapping) else None
            mode = "allowed"
        if values is not None:
            if parsed is not None:
                return None
            parsed = (mode, values)
        elif unwrapped != {"value": "[field('type')]", "exists": True}:
            return None
    return parsed


def _type_values(
    condition: Mapping[str, Any], parameters: Mapping[str, Any]
) -> frozenset[str] | None:
    field = condition.get("field")
    if not isinstance(field, str) or field.casefold() != "type":
        return None
    raw = condition.get("in") if "in" in condition else condition.get("equals")
    resolved = _resolve(raw, parameters)
    if isinstance(resolved, str):
        return frozenset({resolved})
    if isinstance(resolved, list):
        return frozenset(value for value in resolved if isinstance(value, str))
    return None


def _merged_parameters(definition: Any, assignment: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(definition, Mapping):
        for name, spec in definition.items():
            if isinstance(spec, Mapping) and "defaultValue" in spec:
                result[str(name)] = spec["defaultValue"]
    if isinstance(assignment, Mapping):
        for name, spec in assignment.items():
            if isinstance(spec, Mapping) and "value" in spec:
                result[str(name)] = spec["value"]
    return result


def _resolve(value: Any, parameters: Mapping[str, Any]) -> Any:
    if isinstance(value, str):
        match = re.fullmatch(r"\[parameters\('([^']+)'\)\]", value.strip())
        if match:
            return parameters.get(match.group(1))
    return value


def _unwrap(value: Any) -> Any:
    for _ in range(8):
        if not isinstance(value, Mapping):
            break
        children = value.get("allOf") or value.get("anyOf")
        if not isinstance(children, list) or len(children) != 1:
            break
        value = children[0]
    return value


def _casefold_contains(values: frozenset[str], candidate: str) -> bool:
    return candidate.casefold() in {value.casefold() for value in values}
