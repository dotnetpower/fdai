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

from aiopspilot.shared.contracts.models import Mode, OntologyActionType, TriggerKind
from aiopspilot.shared.contracts.registry import SchemaRegistry

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

    if aggregated:
        raise ActionTypeCatalogError(aggregated)

    return tuple(loaded)


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
