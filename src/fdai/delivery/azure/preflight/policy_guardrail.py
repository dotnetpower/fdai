"""Live Azure Policy guardrail probe (POLICY_GUARDRAIL, shadow-first).

Realizes the :class:`~fdai.shared.providers.feasibility_probe.FeasibilityProbe`
Protocol against **real Azure Policy assignments** on the target scope, in
place of the config-driven upstream default
(:class:`~fdai.shared.providers.local.feasibility.DenylistResourceTypeProbe`).

It reads the policy assignments at the scope, resolves each assignment's
definition, and parses the two canonical resource-type guardrails the roadmap
calls out (``Not allowed resource types`` / ``Allowed resource types``) for a
``deny`` effect. A denied resource type the deployment intends to create yields
a grounded blocking finding citing the policy id, mapped to a terraform toggle
when a resolution is registered for that type.

Shadow-first: the probe only *reports*. Whether a finding gates a deploy is the
report's ``blocks_deploy`` flag (enforce mode + promoted category), never the
probe. Read-only and fail-closed - any ARM error propagates as
:class:`AzurePreflightError` so the pass never reports a false ``clear``.

Resource-type namespace: ``PreflightTarget.resource_types`` stays CSP-neutral.
``AzurePolicyProbeConfig.resource_type_map`` translates those values to ARM types
(``Microsoft.Compute/disks``) inside this adapter. Direct ARM types remain accepted
for compatibility; an unmapped neutral type fails closed before an ARM request.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from fdai.delivery.azure.preflight._client import AzureArmClient, AzurePreflightError
from fdai.shared.providers.feasibility_probe import (
    FindingSeverity,
    PreflightTarget,
    ProbeCategory,
    ProbeEvidence,
    ProbeFinding,
    ProbeResolution,
    ResolutionKind,
)
from fdai.shared.providers.local.feasibility import ToggleResolution

_DEFAULT_ASSIGNMENTS_API = "2022-06-01"
_DEFAULT_DEFINITIONS_API = "2021-06-01"
_TYPE_FIELDS = frozenset({"type"})


@dataclass(frozen=True, slots=True)
class AzurePolicyProbeConfig:
    """Scope + API versions + toggle-resolution map for the policy probe."""

    subscription_id: str
    resource_group: str | None = None
    assignments_api_version: str = _DEFAULT_ASSIGNMENTS_API
    definitions_api_version: str = _DEFAULT_DEFINITIONS_API
    resource_type_map: Mapping[str, str] = field(default_factory=dict)
    resolutions: Mapping[str, ToggleResolution] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.subscription_id.strip():
            raise ValueError("subscription_id MUST NOT be empty")

    @property
    def scope(self) -> str:
        scope = f"/subscriptions/{self.subscription_id}"
        if self.resource_group:
            scope = f"{scope}/resourceGroups/{self.resource_group}"
        return scope


class AzurePolicyGuardrailProbe:
    """Read real Azure Policy deny guardrails and report denied resource types."""

    def __init__(self, *, client: AzureArmClient, config: AzurePolicyProbeConfig) -> None:
        self._client = client
        self._config = config

    @property
    def category(self) -> ProbeCategory:
        return ProbeCategory.POLICY_GUARDRAIL

    async def evaluate(self, target: PreflightTarget) -> Sequence[ProbeFinding]:
        if not target.resource_types:
            return ()
        arm_resource_types = _arm_resource_types(
            target.resource_types,
            self._config.resource_type_map,
        )
        assignments = await self._client.get_values(
            f"{self._config.scope}/providers/Microsoft.Authorization/policyAssignments",
            api_version=self._config.assignments_api_version,
            params={"$filter": "atScope()"},
        )
        findings: list[ProbeFinding] = []
        seen: set[tuple[str, str]] = set()
        for assignment in assignments:
            findings.extend(await self._evaluate_assignment(assignment, arm_resource_types, seen))
        # Deterministic order: blocking findings by (resource type, policy id).
        return tuple(sorted(findings, key=lambda f: f.id))

    async def _evaluate_assignment(
        self,
        assignment: Mapping[str, Any],
        arm_resource_types: tuple[str, ...],
        seen: set[tuple[str, str]],
    ) -> list[ProbeFinding]:
        props = assignment.get("properties")
        if not isinstance(props, Mapping):
            return []
        definition_id = props.get("policyDefinitionId")
        if not isinstance(definition_id, str) or not definition_id:
            return []
        definition = await self._client.get_json(
            definition_id, api_version=self._config.definitions_api_version
        )
        parsed = _parse_definition(definition, assignment_params=props.get("parameters"))
        if parsed is None:
            return []
        mode, denied_types, policy_ref = parsed
        denied_hit = _denied_hit(mode, denied_types, arm_resource_types)
        findings: list[ProbeFinding] = []
        for rtype in sorted(denied_hit):
            key = (rtype, policy_ref)
            if key in seen:
                continue
            seen.add(key)
            findings.append(self._finding(rtype, policy_ref))
        return findings

    def _finding(self, rtype: str, policy_ref: str) -> ProbeFinding:
        toggle = self._config.resolutions.get(rtype)
        if toggle is None:
            resolution = ProbeResolution(
                kind=ResolutionKind.MANUAL,
                guidance=(
                    f"resource type {rtype!r} is denied by policy {policy_ref!r} in this "
                    "scope; provision it out-of-line or request a scoped exemption"
                ),
            )
        else:
            resolution = ProbeResolution(
                kind=ResolutionKind.TERRAFORM_TOGGLE,
                autofix=toggle.autofix,
                module=toggle.module,
                set_vars=dict(toggle.set_vars),
            )
        return ProbeFinding(
            id=f"policy-deny:{policy_ref}:{rtype}",
            category=ProbeCategory.POLICY_GUARDRAIL,
            severity=FindingSeverity.BLOCKING,
            title=f"{rtype} denied by policy {policy_ref}",
            evidence=ProbeEvidence(
                source=f"policy:{policy_ref}",
                detail=f"Azure Policy deny effect covers resource type {rtype}",
            ),
            resolution=resolution,
        )


def _denied_hit(mode: str, denied_types: frozenset[str], target_types: tuple[str, ...]) -> set[str]:
    targets = {t for t in target_types}
    if mode == "not_allowed":
        return {t for t in targets if _matches(t, denied_types)}
    # allowed: any target type NOT in the allow-list is denied.
    return {t for t in targets if not _matches(t, denied_types)}


def _arm_resource_types(
    target_types: tuple[str, ...],
    resource_type_map: Mapping[str, str],
) -> tuple[str, ...]:
    mapped: set[str] = set()
    missing: set[str] = set()
    for resource_type in target_types:
        if "/" in resource_type:
            mapped.add(resource_type)
            continue
        arm_type = resource_type_map.get(resource_type)
        if arm_type is None:
            missing.add(resource_type)
            continue
        mapped.add(arm_type)
    if missing:
        values = ", ".join(sorted(missing))
        raise AzurePreflightError(f"ARM resource type mapping is missing for: {values}")
    return tuple(sorted(mapped))


def _matches(resource_type: str, listed: frozenset[str]) -> bool:
    """Case-insensitive membership; ARM types are case-insensitive."""
    lowered = resource_type.casefold()
    return any(lowered == entry.casefold() for entry in listed)


def _parse_definition(
    definition: Mapping[str, Any], *, assignment_params: Any
) -> tuple[str, frozenset[str], str] | None:
    """Return ``(mode, types, policy_ref)`` for a resource-type deny, or None.

    ``mode`` is ``"not_allowed"`` or ``"allowed"``. Only ``deny`` effects on the
    ``type`` field are recognized; any other rule shape returns ``None`` (a
    probe never emits an ungrounded / misparsed finding).
    """
    props = definition.get("properties")
    if not isinstance(props, Mapping):
        return None
    rule = props.get("policyRule")
    if not isinstance(rule, Mapping):
        return None
    params = _merged_params(props.get("parameters"), assignment_params)
    if not _is_deny(rule.get("then"), params):
        return None
    condition = _unwrap(rule.get("if"))
    if not isinstance(condition, Mapping):
        return None
    policy_ref = _policy_ref(definition)
    parsed_condition = _parse_type_condition(condition, params)
    if parsed_condition is None:
        return None
    mode, types = parsed_condition
    return mode, types, policy_ref


def _parse_type_condition(
    condition: Mapping[str, Any],
    params: Mapping[str, Any],
) -> tuple[str, frozenset[str]] | None:
    negated = _unwrap(condition.get("not"))
    if isinstance(negated, Mapping):
        types = _type_in_values(negated, params)
        return None if types is None else ("allowed", types)

    types = _type_in_values(condition, params)
    if types is not None:
        return "not_allowed", types

    children = condition.get("allOf")
    if not isinstance(children, list) or not 1 <= len(children) <= 8:
        return None
    parsed: tuple[str, frozenset[str]] | None = None
    for child in children:
        unwrapped = _unwrap(child)
        if not isinstance(unwrapped, Mapping):
            return None
        child_types = _type_in_values(unwrapped, params)
        if child_types is not None:
            if parsed is not None:
                return None
            parsed = ("not_allowed", child_types)
            continue
        child_negated = _unwrap(unwrapped.get("not"))
        if isinstance(child_negated, Mapping):
            child_types = _type_in_values(child_negated, params)
            if child_types is None or parsed is not None:
                return None
            parsed = ("allowed", child_types)
            continue
        if not _is_type_exists_guard(unwrapped):
            return None
    return parsed


def _is_type_exists_guard(condition: Mapping[str, Any]) -> bool:
    return condition == {"value": "[field('type')]", "exists": True}


def _type_in_values(
    condition: Mapping[str, Any], params: Mapping[str, Any]
) -> frozenset[str] | None:
    field_name = condition.get("field")
    if not isinstance(field_name, str) or field_name.casefold() not in _TYPE_FIELDS:
        return None
    raw = condition.get("in")
    if raw is None and "equals" in condition:
        value = _resolve(condition.get("equals"), params)
        return frozenset({str(value)}) if isinstance(value, str) else None
    resolved = _resolve(raw, params)
    if isinstance(resolved, list):
        return frozenset(str(item) for item in resolved if isinstance(item, str))
    return None


def _is_deny(then: Any, params: Mapping[str, Any]) -> bool:
    if not isinstance(then, Mapping):
        return False
    effect = _resolve(then.get("effect"), params)
    return isinstance(effect, str) and effect.casefold() == "deny"


def _unwrap(node: Any) -> Any:
    """Unwrap a single-child ``allOf`` / ``anyOf`` wrapper around a condition."""
    guard = 0
    while isinstance(node, Mapping) and guard < 8:
        guard += 1
        for key in ("allOf", "anyOf"):
            children = node.get(key)
            if isinstance(children, list) and len(children) == 1:
                node = children[0]
                break
        else:
            break
    return node


def _merged_params(definition_params: Any, assignment_params: Any) -> dict[str, Any]:
    """Merge assignment parameter values over definition defaults."""
    merged: dict[str, Any] = {}
    if isinstance(definition_params, Mapping):
        for name, spec in definition_params.items():
            if isinstance(spec, Mapping) and "defaultValue" in spec:
                merged[name] = spec["defaultValue"]
    if isinstance(assignment_params, Mapping):
        for name, spec in assignment_params.items():
            if isinstance(spec, Mapping) and "value" in spec:
                merged[name] = spec["value"]
    return merged


def _resolve(token: Any, params: Mapping[str, Any]) -> Any:
    """Resolve an ``[parameters('name')]`` token against ``params``; else pass through."""
    if isinstance(token, str):
        name = _parameter_name(token)
        if name is not None:
            return params.get(name)
    return token


def _parameter_name(token: str) -> str | None:
    stripped = token.strip()
    prefix = "[parameters('"
    suffix = "')]"
    if stripped.startswith(prefix) and stripped.endswith(suffix):
        return stripped[len(prefix) : -len(suffix)]
    return None


def _policy_ref(definition: Mapping[str, Any]) -> str:
    name = definition.get("name")
    if isinstance(name, str) and name:
        return name
    ref = definition.get("id")
    return ref if isinstance(ref, str) and ref else "unknown-policy"


__all__ = ["AzurePolicyGuardrailProbe", "AzurePolicyProbeConfig"]
