"""Translate Azure Policy definitions into inert, reviewed-grammar Rule candidates.

A candidate is produced only when a policy's complete condition and effect fit a small supported
grammar over a reviewed alias map (``rule-catalog/translation/azure-policy/aliases.yaml``).
Everything else is refused with a reason, and a refusal is the expected outcome for most built-in
policies. Candidates are inert: they are never written to the Rule catalog, carry the source policy
and translator digests, and can enter the catalog only through the Mimir quality gate after a
differential comparison with Azure Policy compliance state.

Semantics:

- Conditions compile to a three-valued tree. A subtree outside the grammar is unknown, but an
  ``allOf`` with a constant false member, or an ``anyOf`` with a constant true member, is decided
  without it.
- A candidate requires every property its decided conditions read, so a resource without an
  observed value abstains instead of being judged. Under that requirement an ``exists`` condition
  on an ``unobserved`` alias is constant; on a ``defaulted`` alias it can't be decided.
- String comparison is case-insensitive, like Azure Policy. A boolean or enabled/disabled literal
  that can't match the projected value compares as unequal.
- Parameters resolve only from their default values. The effect must be ``Audit`` or ``Deny``;
  ``Modify``, ``DeployIfNotExists``, ``AuditIfNotExists``, and ``Disabled`` are refused.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml

_CODECS: Final = frozenset({"boolean", "string", "enabled_disabled"})
_ABSENCE: Final = frozenset({"unobserved", "defaulted", "request_only"})
_OPERATORS: Final = ("equals", "notEquals", "in", "notIn", "exists")
_PARAMETER = re.compile(r"^\[parameters\('([^']+)'\)\]$")
_SEVERITY: Final = {"deny": "high", "audit": "medium"}
_MODULE_PATH: Final = Path(__file__)


class AzurePolicyTranslationError(ValueError):
    """The alias map or a produced candidate is invalid."""


class _RefusedError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class AliasEntry:
    alias: str
    resource_type: str
    property: str | None
    codec: str
    absence: str


@dataclass(frozen=True, slots=True)
class AliasMap:
    resource_types: Mapping[str, str]
    aliases: Mapping[str, AliasEntry]
    digest: str


def load_alias_map(path: Path) -> AliasMap:
    """Load the reviewed alias map, rejecting an unreviewed or inconsistent entry."""

    content = path.read_bytes()
    raw = yaml.safe_load(content)
    if not isinstance(raw, Mapping) or raw.get("review_state") != "reviewed":
        raise AzurePolicyTranslationError("alias map MUST be reviewed")
    types = raw.get("resource_types")
    entries = raw.get("aliases")
    if not isinstance(types, Mapping) or not isinstance(entries, list):
        raise AzurePolicyTranslationError("alias map is malformed")
    resource_types = {str(key).casefold(): str(value) for key, value in types.items()}
    aliases: dict[str, AliasEntry] = {}
    for item in entries:
        if not isinstance(item, Mapping):
            raise AzurePolicyTranslationError("alias entry is malformed")
        entry = AliasEntry(
            alias=str(item.get("alias", "")),
            resource_type=str(item.get("resource_type", "")),
            property=item.get("property"),
            codec=str(item.get("codec", "")),
            absence=str(item.get("absence", "")),
        )
        if (
            not entry.alias
            or entry.resource_type not in resource_types.values()
            or entry.codec not in _CODECS
            or entry.absence not in _ABSENCE
            or (entry.absence == "request_only") != (entry.property is None)
            or not str(item.get("rationale", "")).strip()
        ):
            raise AzurePolicyTranslationError(f"alias entry {entry.alias!r} is invalid")
        if entry.alias.casefold() in aliases:
            raise AzurePolicyTranslationError(f"alias {entry.alias!r} is duplicated")
        aliases[entry.alias.casefold()] = entry
    return AliasMap(
        resource_types=resource_types,
        aliases=aliases,
        digest="sha256:" + hashlib.sha256(content).hexdigest(),
    )


def translator_digest(alias_map: AliasMap) -> str:
    """Bind a candidate to this translator's source and the alias map it used."""

    source = hashlib.sha256(_MODULE_PATH.read_bytes()).hexdigest()
    return "sha256:" + hashlib.sha256(f"{source}:{alias_map.digest}".encode()).hexdigest()


# --- intermediate representation -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Const:
    value: bool


@dataclass(frozen=True, slots=True)
class _Leaf:
    property: str
    codec: str
    operator: str
    values: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class _And:
    members: tuple[_Node, ...]


@dataclass(frozen=True, slots=True)
class _Or:
    members: tuple[_Node, ...]


@dataclass(frozen=True, slots=True)
class _Not:
    member: _Node


_Node = _Const | _Leaf | _And | _Or | _Not


@dataclass(frozen=True, slots=True)
class _Compiled:
    node: _Node | None
    requires: frozenset[str]
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class TranslationResult:
    """One policy's candidate, or the reason it can't be translated."""

    policy_name: str
    status: str
    reason: str | None
    rule: Mapping[str, Any] | None = None
    rego: str | None = None
    translation: Mapping[str, Any] | None = None


def translate_policy(
    definition: Mapping[str, Any],
    *,
    alias_map: AliasMap,
    content_hash: str,
    origin: str,
    resolved_ref: str,
    retrieved_at: str,
    rule_id_prefix: str = "azure-policy.translated",
) -> TranslationResult:
    """Translate one Azure Policy definition, or return a refusal with its reason."""

    name = str(definition.get("name") or "")
    try:
        return _translate(
            definition,
            name=name,
            alias_map=alias_map,
            content_hash=content_hash,
            origin=origin,
            resolved_ref=resolved_ref,
            retrieved_at=retrieved_at,
            rule_id_prefix=rule_id_prefix,
        )
    except _RefusedError as refused:
        return TranslationResult(policy_name=name, status="refused", reason=refused.reason)


def _translate(
    definition: Mapping[str, Any],
    *,
    name: str,
    alias_map: AliasMap,
    content_hash: str,
    origin: str,
    resolved_ref: str,
    retrieved_at: str,
    rule_id_prefix: str,
) -> TranslationResult:
    properties = definition.get("properties")
    if not name or not isinstance(properties, Mapping):
        raise _RefusedError("malformed_definition")
    if properties.get("mode") not in {"Indexed", "All"}:
        raise _RefusedError("unsupported_mode")
    rule = properties.get("policyRule")
    if not isinstance(rule, Mapping) or not isinstance(rule.get("then"), Mapping):
        raise _RefusedError("malformed_definition")
    parameters = properties.get("parameters") or {}
    if not isinstance(parameters, Mapping):
        raise _RefusedError("malformed_definition")
    context = _Context(alias_map=alias_map, parameters=parameters)
    effect = context.literal(rule["then"].get("effect"))
    if not isinstance(effect, str) or effect.casefold() not in _SEVERITY:
        raise _RefusedError("unsupported_effect")
    resource_type, conditions = _split_type(rule.get("if"), context)
    context.resource_type = resource_type
    compiled = context.compile_all(conditions)
    if compiled.node is None:
        raise _RefusedError(compiled.reason or "unsupported_condition")
    if isinstance(compiled.node, _Const):
        raise _RefusedError("constant_condition")
    if not compiled.requires:
        raise _RefusedError("no_observed_property")
    guid = name.casefold()
    package_suffix = re.sub(r"[^a-z0-9]", "_", guid)
    # The OPA evaluator derives the package from the path, so both use Rego identifiers.
    reference = f"policies/azure_policy_candidates/p_{package_suffix}.rego"
    display = str(properties.get("displayName") or name)
    rule_id = f"{rule_id_prefix}.{guid}"
    severity = _SEVERITY[effect.casefold()]
    rego = _rego(
        f"fdai.azure_policy_candidates.p_{package_suffix}",
        resource_type,
        compiled.node,
        metadata={
            "title": display,
            "description": f"Inert translation of Azure Policy definition {name}.",
            "rule_id": rule_id,
            "severity": severity,
        },
    )
    version = str(
        properties.get("version") or (properties.get("metadata") or {}).get("version") or "1.0.0"
    )
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        version = "1.0.0"
    evaluates = sorted(f"property.{resource_type}.{item}" for item in compiled.requires)
    candidate = {
        "schema_version": "2.0.0",
        "id": rule_id,
        "version": version,
        "source": "azure_policy",
        "severity": severity,
        "category": "security",
        "resource_type": resource_type,
        "applies_to": [resource_type],
        "triggered_by": ["resource.configuration.observed"],
        "evaluates": evaluates,
        "required_interfaces": ["Evaluable", "Remediable"],
        "submission_criteria": [
            {"kind": "resource_type_registered", "value": resource_type},
            *({"kind": "property_exists", "value": item} for item in evaluates),
        ],
        "check_logic": {"kind": "rego", "reference": reference},
        "remediation": {"template_ref": f"remediation/azure-builtin/{name}.md"},
        "remediates": "remediate.azure-policy-managed",
        "parameters": {
            "azure_policy_name": name,
            "azure_policy_display_name": display,
            "azure_policy_effect_default": effect,
        },
        "provenance": {
            "source_url": (
                f"https://github.com/Azure/azure-policy/blob/main/built-in-policies/{origin}"
            ),
            "source_version": version,
            "resolved_ref": resolved_ref,
            "content_hash": content_hash,
            "license": "MIT",
            "redistribution": "embeddable",
            "retrieved_at": retrieved_at,
        },
    }
    translation = {
        "policy_name": name,
        "policy_content_hash": content_hash,
        "translator_digest": translator_digest(alias_map),
        "alias_map_digest": alias_map.digest,
        "condition_parameters": sorted(context.used_parameters - {"effect"}),
        "rego_digest": "sha256:" + hashlib.sha256(rego.encode()).hexdigest(),
        "activation": "inert",
    }
    return TranslationResult(
        policy_name=name,
        status="translated",
        reason=None,
        rule=candidate,
        rego=rego,
        translation=translation,
    )


class _Context:
    def __init__(self, *, alias_map: AliasMap, parameters: Mapping[str, Any]) -> None:
        self.alias_map = alias_map
        self.parameters = parameters
        self.used_parameters: set[str] = set()
        self.resource_type = ""

    def literal(self, value: Any) -> Any:
        if isinstance(value, str) and value.startswith("["):
            match = _PARAMETER.match(value)
            if match is None:
                raise _RefusedError("expression_literal")
            parameter = self.parameters.get(match.group(1))
            if not isinstance(parameter, Mapping) or "defaultValue" not in parameter:
                raise _RefusedError("parameter_without_default")
            self.used_parameters.add(match.group(1))
            return parameter["defaultValue"]
        return value

    def compile_all(self, members: Sequence[Any]) -> _Compiled:
        return _combine_and([self.compile(item) for item in members])

    def compile(self, node: Any) -> _Compiled:
        if not isinstance(node, Mapping):
            return _Compiled(None, frozenset(), "malformed_condition")
        if "allOf" in node:
            members = node["allOf"]
            if not isinstance(members, list):
                return _Compiled(None, frozenset(), "malformed_condition")
            return _combine_and([self.compile(item) for item in members])
        if "anyOf" in node:
            members = node["anyOf"]
            if not isinstance(members, list):
                return _Compiled(None, frozenset(), "malformed_condition")
            return _combine_or([self.compile(item) for item in members])
        if "not" in node:
            inner = self.compile(node["not"])
            if inner.node is None:
                return inner
            if isinstance(inner.node, _Const):
                return _Compiled(_Const(not inner.node.value), inner.requires)
            return _Compiled(_Not(inner.node), inner.requires)
        if "count" in node:
            return _Compiled(None, frozenset(), "count_condition")
        if "value" in node:
            return _Compiled(None, frozenset(), "value_condition")
        if "field" in node:
            try:
                return self._leaf(node)
            except _RefusedError as refused:
                return _Compiled(None, frozenset(), refused.reason)
        return _Compiled(None, frozenset(), "malformed_condition")

    def _leaf(self, node: Mapping[str, Any]) -> _Compiled:
        field = str(node["field"])
        operators = [item for item in node if item != "field"]
        if len(operators) != 1 or operators[0] not in _OPERATORS:
            raise _RefusedError("unsupported_operator")
        operator = operators[0]
        if "[*]" in field:
            raise _RefusedError("array_alias")
        entry = self.alias_map.aliases.get(field.casefold())
        if entry is None:
            raise _RefusedError("unmapped_field")
        if entry.resource_type != self.resource_type:
            raise _RefusedError("alias_type_mismatch")
        raw = self.literal(node[operator])
        if operator == "exists":
            wanted = _boolean(raw)
            if wanted is None:
                raise _RefusedError("malformed_condition")
            if entry.absence == "defaulted":
                raise _RefusedError("exists_on_defaulted_alias")
            present = entry.absence == "unobserved"
            requires = frozenset({entry.property}) if entry.property else frozenset()
            return _Compiled(_Const(present == wanted), requires)
        values = tuple(raw) if operator in {"in", "notIn"} else (raw,)
        if operator in {"in", "notIn"} and not isinstance(raw, list):
            raise _RefusedError("malformed_condition")
        negated = operator in {"notEquals", "notIn"}
        if entry.absence == "request_only":
            # Absent on every stored resource: equality never holds.
            return _Compiled(_Const(negated), frozenset())
        if entry.property is None:
            raise _RefusedError("unmapped_field")
        encoded = tuple(
            item for item in (_encode(entry.codec, value) for value in values) if item is not None
        )
        requires = frozenset({entry.property})
        if not encoded:
            return _Compiled(_Const(negated), requires)
        return _Compiled(
            _Leaf(entry.property, entry.codec, "in" if not negated else "notIn", encoded),
            requires,
        )


def _split_type(node: Any, context: _Context) -> tuple[str, list[Any]]:
    members = node.get("allOf") if isinstance(node, Mapping) and "allOf" in node else [node]
    if not isinstance(members, list):
        raise _RefusedError("malformed_condition")
    types = [
        item
        for item in members
        if isinstance(item, Mapping) and str(item.get("field", "")).casefold() == "type"
    ]
    if len(types) != 1 or set(types[0]) != {"field", "equals"}:
        raise _RefusedError("type_condition")
    value = context.literal(types[0]["equals"])
    resource_type = context.alias_map.resource_types.get(str(value).casefold())
    if resource_type is None:
        raise _RefusedError("unmapped_resource_type")
    return resource_type, [item for item in members if item is not types[0]]


def _combine_and(members: list[_Compiled]) -> _Compiled:
    supported = [item for item in members if item.node is not None]
    requires = frozenset().union(*(item.requires for item in supported))
    if any(isinstance(item.node, _Const) and not item.node.value for item in supported):
        return _Compiled(_Const(False), requires)
    unsupported = [item for item in members if item.node is None]
    if unsupported:
        return _Compiled(None, frozenset(), unsupported[0].reason)
    nodes = tuple(item.node for item in supported if not isinstance(item.node, _Const))
    if not nodes:
        return _Compiled(_Const(True), requires)
    return _Compiled(nodes[0] if len(nodes) == 1 else _And(nodes), requires)  # type: ignore[arg-type]


def _combine_or(members: list[_Compiled]) -> _Compiled:
    supported = [item for item in members if item.node is not None]
    requires = frozenset().union(*(item.requires for item in supported))
    if any(isinstance(item.node, _Const) and item.node.value for item in supported):
        return _Compiled(_Const(True), requires)
    unsupported = [item for item in members if item.node is None]
    if unsupported:
        return _Compiled(None, frozenset(), unsupported[0].reason)
    nodes = tuple(item.node for item in supported if not isinstance(item.node, _Const))
    if not nodes:
        return _Compiled(_Const(False), requires)
    return _Compiled(nodes[0] if len(nodes) == 1 else _Or(nodes), requires)  # type: ignore[arg-type]


def _boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.casefold() in {"true", "false"}:
        return value.casefold() == "true"
    return None


def _encode(codec: str, value: Any) -> Any:
    """Return the projected value a literal can equal, or None when it can never match."""

    if codec == "boolean":
        return _boolean(value)
    if codec == "enabled_disabled":
        if isinstance(value, str) and value.casefold() in {"enabled", "disabled"}:
            return value.casefold() == "enabled"
        return None
    if not isinstance(value, str):
        raise _RefusedError("literal_type")
    return value.casefold()


def _rego(
    package: str,
    resource_type: str,
    root: _Node,
    *,
    metadata: Mapping[str, str],
) -> str:
    rules: list[str] = []

    def emit(node: _Node) -> str:
        name = f"c{len(rules)}"
        rules.append("")
        index = len(rules) - 1
        if isinstance(node, _Leaf):
            rules[index] = f"{name} if {{\n  {_leaf_expression(node)}\n}}\n"
        elif isinstance(node, _And):
            children = [emit(item) for item in node.members]
            body = "\n  ".join(children)
            rules[index] = f"{name} if {{\n  {body}\n}}\n"
        elif isinstance(node, _Or):
            children = [emit(item) for item in node.members]
            rules[index] = "\n".join(f"{name} if {{\n  {child}\n}}\n" for child in children)
        elif isinstance(node, _Not):
            child = emit(node.member)
            rules[index] = f"{name} if {{\n  not {child}\n}}\n"
        else:  # pragma: no cover - constants never reach code generation
            raise AzurePolicyTranslationError("constant condition reached code generation")
        return name

    root_name = emit(root)
    header = (
        "# METADATA\n"
        f"# title: {json.dumps(metadata['title'])}\n"
        f"# description: {json.dumps(metadata['description'])}\n"
        "# custom:\n"
        f"#   rule_id: {metadata['rule_id']}\n"
        f"#   severity: {metadata['severity']}\n"
        "#   category: security\n"
        f"package {package}\n\n"
        "# Generated by the Azure Policy translator. Inert candidate; do not edit.\n\n"
        "import rego.v1\n\ndefault deny := false\n\n"
        f'deny if {{\n  input.resource.type == "{resource_type}"\n  {root_name}\n}}\n\n'
    )
    return header + "\n".join(rules)


def _leaf_expression(leaf: _Leaf) -> str:
    value = f"input.resource.props.{leaf.property}"
    if leaf.codec == "string":
        # A value of another type never compares, so it can't satisfy a negated condition either.
        guard = f"is_string({value})"
        accessor = f"lower({value})"
        members = ", ".join(json.dumps(item) for item in leaf.values)
    else:
        guard = f"is_boolean({value})"
        accessor = value
        members = ", ".join("true" if item else "false" for item in leaf.values)
    expression = f"{accessor} in {{{members}}}"
    return f"{guard}\n  " + (f"not {expression}" if leaf.operator == "notIn" else expression)


@dataclass(frozen=True, slots=True)
class SnapshotTranslation:
    """Every definition's outcome in one pinned snapshot, plus the identities they bind."""

    resolved_ref: str
    translator_digest: str
    alias_map_digest: str
    results: tuple[TranslationResult, ...]

    def summary(self) -> dict[str, Any]:
        reasons: dict[str, int] = {}
        for item in self.results:
            key = "translated" if item.status == "translated" else str(item.reason)
            reasons[key] = reasons.get(key, 0) + 1
        return {
            "resolved_ref": self.resolved_ref,
            "translator_digest": self.translator_digest,
            "alias_map_digest": self.alias_map_digest,
            "definitions": len(self.results),
            "outcomes": dict(sorted(reasons.items())),
            "translated": sorted(item.policy_name for item in self.results if item.rule),
            "activation": "inert",
        }


def translate_snapshot(
    tree_root: Path,
    *,
    alias_map: AliasMap,
    resolved_ref: str,
    retrieved_at: str,
) -> SnapshotTranslation:
    """Translate every definition in a pinned snapshot tree, first copy of each GUID only."""

    if re.fullmatch(r"[0-9a-f]{40}", resolved_ref) is None or set(resolved_ref) == {"0"}:
        raise AzurePolicyTranslationError("resolved_ref MUST be a pinned commit SHA")
    seen: set[str] = set()
    results: list[TranslationResult] = []
    for path in sorted(tree_root.rglob("*.json")):
        content = path.read_bytes()
        try:
            document = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AzurePolicyTranslationError(f"{path}: not valid JSON") from exc
        if not isinstance(document, Mapping) or "properties" not in document:
            continue
        name = str(document.get("name") or "").casefold()
        if not name or name in seen:
            continue
        seen.add(name)
        results.append(
            translate_policy(
                document,
                alias_map=alias_map,
                content_hash="sha256:" + hashlib.sha256(content).hexdigest(),
                origin=path.relative_to(tree_root).as_posix(),
                resolved_ref=resolved_ref,
                retrieved_at=retrieved_at,
            )
        )
    return SnapshotTranslation(
        resolved_ref=resolved_ref,
        translator_digest=translator_digest(alias_map),
        alias_map_digest=alias_map.digest,
        results=tuple(results),
    )


__all__ = [
    "AliasEntry",
    "AliasMap",
    "AzurePolicyTranslationError",
    "SnapshotTranslation",
    "TranslationResult",
    "load_alias_map",
    "translate_policy",
    "translate_snapshot",
    "translator_digest",
]
