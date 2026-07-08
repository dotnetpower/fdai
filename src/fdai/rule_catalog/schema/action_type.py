"""ActionType catalog loader - reads YAML instances from
``rule-catalog/action-types/`` and validates against the ontology
``action-type`` JSON Schema plus the :class:`OntologyActionType` pydantic
model. Aggregates every issue in a single :class:`ActionTypeCatalogError`.
"""

from __future__ import annotations

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
from fdai.shared.contracts.models import Mode, OntologyActionType, TriggerKind
from fdai.shared.contracts.registry import SchemaRegistry

_ACTION_TYPE_SCHEMA_NAME = "ontology/action-type"


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
        asch = at.argument_schema
        if asch is not None and (
            asch.get("type") != "object" or asch.get("additionalProperties") is not False
        ):
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
    return issues


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
    "load_action_type_catalog",
    "load_action_type_from_mapping",
]
