"""ActionType catalog loader - reads YAML instances from
``rule-catalog/action-types/`` and validates against the ontology
``action-type`` JSON Schema plus the :class:`OntologyActionType` pydantic
model. Aggregates every issue in a single :class:`ActionTypeCatalogError`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from fdai.rule_catalog.schema.probe import (
    ProbeCatalogError,
    load_probe_catalog,
    probe_ids,
)
from fdai.shared.contracts.models import (
    ActionInterface,
    Autonomy,
    Mode,
    OntologyActionType,
    Operation,
    TriggerKind,
)
from fdai.shared.contracts.registry import SchemaRegistry

_ACTION_TYPE_SCHEMA_NAME = "ontology/action-type"

# The only extension keys allowed inside an ``argument_schema`` property.
# Anything else that looks like an ``x-fdai-*`` key is a typo and is a
# fatal load error, so a misspelled redact hint cannot silently leak a
# secret (action-ontology.md 5.2 / 8).
_ALLOWED_ARG_EXTENSION_KEYS: frozenset[str] = frozenset(
    {"x-fdai-redact", "x-fdai-audit-safe"}
)


@dataclass(frozen=True, slots=True)
class ActionTypeIssue:
    key: str
    message: str


class ActionTypeCatalogError(ValueError):
    """Aggregate error surfaced when loading an ActionType YAML fails."""

    def __init__(self, issues: list[ActionTypeIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{i.key}: {i.message}" for i in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"action-type catalog validation failed: {preview}{suffix}")


def _yaml_load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_action_type_from_mapping(
    raw: Mapping[str, Any],
    *,
    schema_registry: SchemaRegistry,
    origin: str = "<mapping>",
) -> OntologyActionType:
    """Validate a single ActionType mapping and return the pydantic model.

    - Aggregates JSON Schema violations and pydantic issues under one
      :class:`ActionTypeCatalogError`.
    - Enforces the P1 upstream invariant: ``default_mode == "shadow"``
      (a fork may loosen this only via a governance PR that also updates
      the promotion gate).
    """
    issues: list[ActionTypeIssue] = []

    schema = schema_registry.get(_ACTION_TYPE_SCHEMA_NAME)
    validator = Draft202012Validator(dict(schema))
    for err in sorted(validator.iter_errors(dict(raw)), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in err.absolute_path) or "<root>"
        issues.append(ActionTypeIssue(key=f"{origin}:{path}", message=err.message))

    if issues:
        raise ActionTypeCatalogError(issues)

    try:
        model = OntologyActionType.model_validate(raw)
    except ValueError as exc:
        errors = getattr(exc, "errors", None)
        if callable(errors):
            for e in errors():
                loc = ".".join(str(p) for p in e.get("loc", ()))
                issues.append(ActionTypeIssue(key=f"{origin}:{loc}", message=e["msg"]))
        else:
            issues.append(ActionTypeIssue(key=f"{origin}:<root>", message=str(exc)))
        raise ActionTypeCatalogError(issues) from exc

    if model.default_mode is not Mode.SHADOW:
        raise ActionTypeCatalogError(
            [
                ActionTypeIssue(
                    key=f"{origin}:default_mode",
                    message=(
                        "upstream ActionType MUST default to shadow "
                        "(coding-conventions.instructions.md § shadow-first)"
                    ),
                )
            ]
        )

    if (
        model.trigger_kind is not None
        and model.trigger_kind.kind in (TriggerKind.OPERATOR_REQUEST, TriggerKind.BOTH)
        and not model.argument_schema
    ):
        raise ActionTypeCatalogError(
            [
                ActionTypeIssue(
                    key=f"{origin}:argument_schema",
                    message=(
                        "operator_request / both ActionType MUST declare a non-empty "
                        "argument_schema so the console can validate arguments at the "
                        "coordinator boundary (action-ontology.md 8)"
                    ),
                )
            ]
        )

    return model


def _iter_yaml_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.glob("*.yaml")):
        if path.name == "README.md":
            continue
        yield path


def load_action_type_catalog(
    root: Path,
    *,
    schema_registry: SchemaRegistry,
    overlay_root: Path | None = None,
    probes_root: Path | None = None,
) -> tuple[OntologyActionType, ...]:
    """Load every ActionType YAML under ``root`` (non-recursive).

    Fails closed: any issue in any file raises a single
    :class:`ActionTypeCatalogError` carrying every issue across every file.
    Duplicate ``name`` across files is a hard error.

    When ``overlay_root`` is provided and contains ``<name>.yaml`` files,
    each overlay is deep-merged onto the corresponding upstream mapping
    before the pydantic model is validated. This is the "file-based
    overlay" layer described in
    [action-ontology.md](../../../../docs/roadmap/action-ontology.md) 7.1;
    fork-only overrides (an overlay file with no matching upstream entry)
    are rejected so a typo cannot silently introduce a phantom
    ActionType. Overlay precedence is the R1 rule: file-overlay wins on
    every key it declares; upstream stays for every key the overlay
    omits.

    ``probes_root`` is optional; when provided, every ActionType with a
    ``live_probe_ref`` is cross-checked against the probe catalog at
    ``probes_root``. An unknown probe id is a hard load error so a
    misspelled reference is caught at startup, not at first probe call
    ([implementation-plan.md](../../../../docs/roadmap/implementation-plan.md)
    Wave M1.3). The cross-check is skipped when ``probes_root`` is
    ``None`` (e.g. tests that stub the probe catalog).
    """
    aggregated: list[ActionTypeIssue] = []
    loaded: list[OntologyActionType] = []
    seen_names: dict[str, str] = {}

    overlays: dict[str, tuple[Path, Mapping[str, Any]]] = {}
    if overlay_root is not None and overlay_root.is_dir():
        for overlay_path in _iter_yaml_files(overlay_root):
            try:
                overlay_raw = _yaml_load(overlay_path)
            except yaml.YAMLError as exc:
                aggregated.append(
                    ActionTypeIssue(
                        key=overlay_path.name,
                        message=f"invalid overlay YAML: {exc}",
                    )
                )
                continue
            if not isinstance(overlay_raw, Mapping):
                aggregated.append(
                    ActionTypeIssue(
                        key=overlay_path.name,
                        message="overlay top-level must be a mapping",
                    )
                )
                continue
            overlay_name = overlay_raw.get("name")
            if not isinstance(overlay_name, str) or not overlay_name:
                aggregated.append(
                    ActionTypeIssue(
                        key=overlay_path.name,
                        message="overlay MUST declare 'name'",
                    )
                )
                continue
            if overlay_name in overlays:
                aggregated.append(
                    ActionTypeIssue(
                        key=overlay_path.name,
                        message=(
                            f"duplicate overlay name {overlay_name!r} "
                            f"(also in {overlays[overlay_name][0].name})"
                        ),
                    )
                )
                continue
            overlays[overlay_name] = (overlay_path, overlay_raw)

    for path in _iter_yaml_files(root):
        try:
            raw = _yaml_load(path)
        except yaml.YAMLError as exc:
            aggregated.append(ActionTypeIssue(key=path.name, message=f"invalid YAML: {exc}"))
            continue
        if not isinstance(raw, Mapping):
            aggregated.append(ActionTypeIssue(key=path.name, message="top-level must be a mapping"))
            continue

        upstream_name = raw.get("name")
        merged: Mapping[str, Any] = raw
        if isinstance(upstream_name, str) and upstream_name in overlays:
            overlay_path, overlay_raw = overlays.pop(upstream_name)
            merged = _deep_merge_overlay(raw, overlay_raw)

        try:
            model = load_action_type_from_mapping(
                merged, schema_registry=schema_registry, origin=path.name
            )
        except ActionTypeCatalogError as exc:
            aggregated.extend(exc.issues)
            continue

        prior = seen_names.get(model.name)
        if prior is not None:
            aggregated.append(
                ActionTypeIssue(
                    key=path.name,
                    message=f"duplicate ActionType name {model.name!r} (also in {prior})",
                )
            )
            continue
        seen_names[model.name] = path.name
        loaded.append(model)

    # Any overlay left in the map has no matching upstream. Reject rather
    # than silently accept - a typo in overlay 'name' MUST fail loudly.
    for stray_name, (stray_path, _) in overlays.items():
        aggregated.append(
            ActionTypeIssue(
                key=stray_path.name,
                message=(
                    f"overlay names {stray_name!r} which does not exist in upstream {root.name!r}"
                ),
            )
        )

    if probes_root is not None:
        aggregated.extend(_check_live_probe_refs(loaded, probes_root, seen_names))

    aggregated.extend(_check_name_collisions(seen_names))
    aggregated.extend(_check_catalog_policy(loaded, seen_names))

    if aggregated:
        raise ActionTypeCatalogError(aggregated)

    return tuple(loaded)


def _check_live_probe_refs(
    action_types: list[OntologyActionType],
    probes_root: Path,
    origin_by_name: Mapping[str, str],
) -> list[ActionTypeIssue]:
    """Cross-check every ``live_probe_ref`` against the probe catalog.

    Fail-closed on a probe-catalog load error so a broken probe manifest
    does not silently disable the cross-check.
    """

    try:
        catalog = load_probe_catalog(probes_root)
    except ProbeCatalogError as exc:
        return [
            ActionTypeIssue(
                key="probes",
                message=(
                    "probe catalog failed to load; live_probe_ref cross-check "
                    f"could not run ({exc})"
                ),
            )
        ]
    known_ids = probe_ids(catalog)

    issues: list[ActionTypeIssue] = []
    for at in action_types:
        if at.live_probe_ref is None:
            continue
        if at.live_probe_ref not in known_ids:
            origin = origin_by_name.get(at.name, "<unknown>")
            issues.append(
                ActionTypeIssue(
                    key=f"{origin}:live_probe_ref",
                    message=(
                        f"unknown probe id {at.live_probe_ref!r} "
                        "(not registered in rule-catalog/probes/)"
                    ),
                )
            )
    return issues


def _check_catalog_policy(
    action_types: list[OntologyActionType],
    origin_by_name: Mapping[str, str],
) -> list[ActionTypeIssue]:
    """Catalog-entry policy: safety-critical fields the JSON Schema leaves
    optional (the Day-1 non-breaking backfill in action-ontology.md 10)
    MUST be present on a REAL catalog entry.

    ``load_action_type_from_mapping`` stays permissive so unit-test model
    fixtures need only the pydantic-required fields; this stricter gate
    runs only in ``load_action_type_catalog`` (upstream + fork custom
    roots). Every shipped ActionType already satisfies it, so the check
    fails closed: a new catalog entry cannot ship with a missing autonomy
    ceiling, blast radius, trigger, category, or execution path - the
    fields the RiskGate reads to decide *whether* and *how* to run
    (action-ontology.md 2). Without this, a missing field silently
    inherited a permissive default instead of blocking registration.
    """

    issues: list[ActionTypeIssue] = []
    for at in action_types:
        origin = origin_by_name.get(at.name, at.name)
        if at.category is None:
            issues.append(
                ActionTypeIssue(
                    key=f"{origin}:category",
                    message=(
                        "catalog ActionType MUST declare a category "
                        "(remediation|ops|governance) (action-ontology.md 3)"
                    ),
                )
            )
        if at.trigger_kind is None:
            issues.append(
                ActionTypeIssue(
                    key=f"{origin}:trigger_kind",
                    message="catalog ActionType MUST declare trigger_kind (action-ontology.md 1)",
                )
            )
        if at.execution_path is None:
            issues.append(
                ActionTypeIssue(
                    key=f"{origin}:execution_path",
                    message=(
                        "catalog ActionType MUST declare execution_path "
                        "(execution-model.md 5)"
                    ),
                )
            )
        if at.blast_radius is None:
            issues.append(
                ActionTypeIssue(
                    key=f"{origin}:blast_radius",
                    message=(
                        "catalog ActionType MUST declare blast_radius so autonomy "
                        "never fails open on an unknown impact surface "
                        "(action-ontology.md 2)"
                    ),
                )
            )
        cbt = at.ceiling_by_tier
        if cbt is None or cbt.t0 is None or cbt.t1 is None or cbt.t2 is None:
            issues.append(
                ActionTypeIssue(
                    key=f"{origin}:ceiling_by_tier",
                    message=(
                        "catalog ActionType MUST declare ceiling_by_tier for t0, t1, "
                        "and t2 (execution-model.md 2.2)"
                    ),
                )
            )
        elif cbt.t2.max_autonomy is not Autonomy.SHADOW_ONLY:
            issues.append(
                ActionTypeIssue(
                    key=f"{origin}:ceiling_by_tier.t2.max_autonomy",
                    message=(
                        "ceiling_by_tier.t2.max_autonomy MUST be shadow_only in the "
                        "catalog; T2 is hard-capped to shadow-only by the ceiling "
                        "module, and raising it is an operator-authored Rego-overlay "
                        "concern (policies/action_types/), never a YAML ceiling "
                        "(action-ontology.md 8)"
                    ),
                )
            )
        asch = at.argument_schema
        if asch is not None:
            if asch.get("type") != "object" or asch.get("additionalProperties") is not False:
                issues.append(
                    ActionTypeIssue(
                        key=f"{origin}:argument_schema",
                        message=(
                            "argument_schema MUST set type: object and "
                            "additionalProperties: false so the console cannot pass "
                            "unspecified arguments (action-ontology.md 5)"
                        ),
                    )
                )
            _walk_argument_schema_props(asch, "", origin, issues, set())
        if at.operation in (Operation.DROP, Operation.PURGE) and (
            ActionInterface.DATA_PLANE_MUTATING not in at.interfaces
        ):
            issues.append(
                ActionTypeIssue(
                    key=f"{origin}:interfaces",
                    message=(
                        "operation drop/purge destroys data/schema and MUST declare "
                        "the DataPlaneMutating interface so the risk gate applies the "
                        "data-plane HIL gate; omitting it would silently downgrade the "
                        "risk classification (action-ontology.md 8)"
                    ),
                )
            )
        tk = at.trigger_kind
        if tk is not None:
            for scenario in tk.restrict_to_scenarios:
                if not isinstance(scenario, str) or not scenario.strip():
                    issues.append(
                        ActionTypeIssue(
                            key=f"{origin}:trigger_kind.restrict_to_scenarios",
                            message=(
                                "restrict_to_scenarios entries MUST be non-empty "
                                "scenario ids (action-ontology.md 1)"
                            ),
                        )
                    )
    return issues


def _canonical_action_name(name: str) -> str:
    """Collapse separators and case so near-duplicate names collide."""

    return re.sub(r"[-_.]+", "-", name.lower())


def _check_name_collisions(origin_by_name: Mapping[str, str]) -> list[ActionTypeIssue]:
    """Reject two distinct ActionType names that differ only by separator or
    case (e.g. ``ops.restart-service`` vs ``ops.restart_service``).

    Near-duplicate names are a typo-squatting hazard: the file-overlay layer
    matches by exact name, so a near-miss silently becomes a phantom custom
    ActionType instead of tightening the intended one, and an operator
    reading an audit entry cannot tell the two apart
    (action-ontology critique #17).
    """

    by_canonical: dict[str, list[str]] = {}
    for name in origin_by_name:
        by_canonical.setdefault(_canonical_action_name(name), []).append(name)
    issues: list[ActionTypeIssue] = []
    for _canonical, names in sorted(by_canonical.items()):
        if len(names) > 1:
            joined = ", ".join(sorted(names))
            for name in sorted(names):
                issues.append(
                    ActionTypeIssue(
                        key=f"{origin_by_name[name]}:name",
                        message=(
                            f"ActionType name {name!r} collides with {{{joined}}} "
                            "(names differing only by separator or case are rejected "
                            "as a typo-squatting hazard) (action-ontology.md 2)"
                        ),
                    )
                )
    return issues


def _walk_argument_schema_props(
    node: Mapping[str, Any],
    path: str,
    origin: str,
    issues: list[ActionTypeIssue],
    redaction_paths: set[str],
) -> None:
    """Recursively validate ``argument_schema`` redaction hints and collect
    the dotted paths flagged ``x-fdai-redact: true``.

    Enforces (action-ontology.md 5.2 / 8):
    - Only ``x-fdai-redact`` / ``x-fdai-audit-safe`` extension keys exist;
      any other ``x-fdai-*`` key is a fatal typo guard.
    - A property MUST NOT set both hints.
    - ``x-fdai-redact: true`` is only valid on a leaf ``string``/``number``
      property (redacting a whole object would drop audit-relevant keys).
    """

    props = node.get("properties")
    if not isinstance(props, Mapping):
        return
    for name, prop in props.items():
        if not isinstance(prop, Mapping):
            continue
        child = f"{path}.{name}" if path else str(name)
        ext = {k for k in prop if isinstance(k, str) and k.startswith("x-fdai")}
        for unknown in sorted(ext - _ALLOWED_ARG_EXTENSION_KEYS):
            issues.append(
                ActionTypeIssue(
                    key=f"{origin}:argument_schema.{child}",
                    message=(
                        f"unknown extension key {unknown!r}; only x-fdai-redact / "
                        "x-fdai-audit-safe are allowed so a misspelled redact hint "
                        "cannot silently leak a secret (action-ontology.md 5.2)"
                    ),
                )
            )
        redact = prop.get("x-fdai-redact") is True
        safe = prop.get("x-fdai-audit-safe") is True
        ptype = prop.get("type")
        is_object = ptype == "object" or "properties" in prop
        if redact and safe:
            issues.append(
                ActionTypeIssue(
                    key=f"{origin}:argument_schema.{child}",
                    message=(
                        "property MUST NOT set both x-fdai-redact and "
                        "x-fdai-audit-safe (a field is either redacted or audit-safe)"
                    ),
                )
            )
        if redact:
            if is_object or ptype not in ("string", "number"):
                issues.append(
                    ActionTypeIssue(
                        key=f"{origin}:argument_schema.{child}",
                        message=(
                            "x-fdai-redact: true MUST be on a leaf string/number "
                            "property (action-ontology.md 5.2)"
                        ),
                    )
                )
            else:
                redaction_paths.add(child)
        # Allowlist, not denylist: a free-text string (no content constraint)
        # can carry a secret or PII typed mid-tool-call, so the author MUST
        # explicitly declare whether it is redacted or audit-safe. A new
        # free-text field can no longer default to being persisted verbatim
        # (action-ontology critique #22).
        constrained = any(k in prop for k in ("enum", "pattern", "const", "format"))
        if ptype == "string" and not is_object and not constrained and not redact and not safe:
            issues.append(
                ActionTypeIssue(
                    key=f"{origin}:argument_schema.{child}",
                    message=(
                        "free-text string property MUST declare x-fdai-redact: true "
                        "(strip before audit) or x-fdai-audit-safe: true (safe to "
                        "persist); an unconstrained string can carry a secret typed "
                        "mid-tool-call (action-ontology.md 5.2)"
                    ),
                )
            )
        if is_object:
            _walk_argument_schema_props(prop, child, origin, issues, redaction_paths)


def argument_schema_redaction_paths(action_type: OntologyActionType) -> frozenset[str]:
    """Return the dotted ``argument_schema`` paths flagged ``x-fdai-redact:
    true``. The audit redactor strips these before an ``operator_request``
    argument blob is persisted so a secret typed mid-tool-call never lands
    verbatim in the append-only audit log (action-ontology.md 5.2)."""

    if action_type.argument_schema is None:
        return frozenset()
    paths: set[str] = set()
    _walk_argument_schema_props(
        action_type.argument_schema, "", action_type.name, [], paths
    )
    return frozenset(paths)


def _deep_merge_overlay(upstream: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Recursive merge: overlay wins on every key it declares.

    Nested mappings are merged key-by-key; every other value type
    (list, scalar) is replaced wholesale. Lists are NOT concatenated
    because ``preconditions`` / ``stop_conditions`` are ordered sets
    and a fork that wants to add is expected to declare the full list.
    """

    result: dict[str, Any] = dict(upstream)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], Mapping) and isinstance(value, Mapping):
            result[key] = _deep_merge_overlay(result[key], value)
        else:
            result[key] = value
    return result


def action_type_names(catalog: Iterable[OntologyActionType]) -> set[str]:
    return {a.name for a in catalog}


__all__ = [
    "ActionTypeCatalogError",
    "ActionTypeIssue",
    "action_type_names",
    "argument_schema_redaction_paths",
    "load_action_type_catalog",
    "load_action_type_from_mapping",
]
