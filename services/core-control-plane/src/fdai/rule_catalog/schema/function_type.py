"""Fail-closed loader for reviewed ontology FunctionType declarations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from fdai.rule_catalog.schema.ontology_provenance import ontology_provenance_error
from fdai.shared.contracts.models import OntologyFunctionType
from fdai.shared.contracts.registry import SchemaRegistry

_FUNCTION_TYPE_SCHEMA_NAME = "ontology/function-type"


@dataclass(frozen=True, slots=True)
class FunctionTypeIssue:
    key: str
    message: str


class FunctionTypeCatalogError(ValueError):
    """Aggregate every FunctionType declaration validation failure."""

    def __init__(self, issues: list[FunctionTypeIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{item.key}: {item.message}" for item in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"function-type catalog validation failed: {preview}{suffix}")


def ontology_function_artifact_digest(declaration: OntologyFunctionType) -> str:
    """Hash the canonical executable contract represented by a FunctionType."""

    payload = declaration.model_dump(
        mode="json",
        exclude={"artifact_digest", "provenance"},
        exclude_none=True,
    )
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def load_function_type_from_mapping(
    raw: Mapping[str, Any],
    *,
    schema_registry: SchemaRegistry,
    origin: str = "<mapping>",
) -> OntologyFunctionType:
    """Validate and materialize one bounded ontology FunctionType declaration."""

    validator = Draft202012Validator(dict(schema_registry.get(_FUNCTION_TYPE_SCHEMA_NAME)))
    issues = [
        FunctionTypeIssue(
            key=f"{origin}:" + (".".join(str(part) for part in error.absolute_path) or "<root>"),
            message=error.message,
        )
        for error in sorted(validator.iter_errors(dict(raw)), key=lambda item: list(item.path))
    ]
    if issues:
        raise FunctionTypeCatalogError(issues)

    try:
        declaration = OntologyFunctionType.model_validate(raw)
    except ValueError as exc:
        raise FunctionTypeCatalogError(_model_issues(exc, origin=origin)) from exc

    for field_name, schema in (
        ("input_schema", declaration.input_schema),
        ("output_schema", declaration.output_schema),
    ):
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise FunctionTypeCatalogError(
                [
                    FunctionTypeIssue(
                        key=f"{origin}:{field_name}",
                        message=f"invalid JSON Schema: {exc.message}",
                    )
                ]
            ) from exc
    return declaration


def load_function_type_catalog(
    root: Path,
    *,
    schema_registry: SchemaRegistry,
) -> tuple[OntologyFunctionType, ...]:
    """Load reviewed FunctionTypes and reject duplicates or stale digests."""

    aggregated: list[FunctionTypeIssue] = []
    loaded: list[OntologyFunctionType] = []
    seen_names: dict[str, tuple[str, str]] = {}
    for path in _iter_yaml_files(root):
        raw = _load_mapping(path, aggregated)
        if raw is None:
            continue
        try:
            declaration = load_function_type_from_mapping(
                raw,
                schema_registry=schema_registry,
                origin=path.name,
            )
        except FunctionTypeCatalogError as exc:
            aggregated.extend(exc.issues)
            continue

        prior = seen_names.get(declaration.name)
        if prior is not None:
            prior_version, prior_file = prior
            qualifier = (
                "name/version" if prior_version == declaration.version else "name across versions"
            )
            aggregated.append(
                FunctionTypeIssue(
                    key=path.name,
                    message=(
                        f"duplicate FunctionType {qualifier} {declaration.name!r}"
                        f"@{declaration.version} (also in {prior_file})"
                    ),
                )
            )
            continue
        seen_names[declaration.name] = (declaration.version, path.name)

        expected_artifact_digest = ontology_function_artifact_digest(declaration)
        if declaration.artifact_digest != expected_artifact_digest:
            aggregated.append(
                FunctionTypeIssue(
                    key=f"{path.name}:artifact_digest",
                    message=(
                        "artifact_digest mismatch: expected "
                        f"{expected_artifact_digest}, got {declaration.artifact_digest}"
                    ),
                )
            )
            continue
        provenance_error = ontology_provenance_error(declaration)
        if provenance_error is not None:
            aggregated.append(
                FunctionTypeIssue(key=f"{path.name}:provenance", message=provenance_error)
            )
            continue
        loaded.append(declaration)

    if aggregated:
        raise FunctionTypeCatalogError(aggregated)
    return tuple(loaded)


def _load_mapping(
    path: Path,
    aggregated: list[FunctionTypeIssue],
) -> Mapping[str, Any] | None:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        aggregated.append(FunctionTypeIssue(key=path.name, message=f"invalid YAML: {exc}"))
        return None
    if not isinstance(raw, Mapping):
        aggregated.append(FunctionTypeIssue(key=path.name, message="top-level must be a mapping"))
        return None
    return raw


def _model_issues(exc: ValueError, *, origin: str) -> list[FunctionTypeIssue]:
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return [FunctionTypeIssue(key=f"{origin}:<root>", message=str(exc))]
    return [
        FunctionTypeIssue(
            key=f"{origin}:" + ".".join(str(part) for part in error.get("loc", ())),
            message=error["msg"],
        )
        for error in errors()
    ]


def _iter_yaml_files(root: Path) -> Iterator[Path]:
    yield from sorted(root.glob("*.yaml"))


__all__ = [
    "FunctionTypeCatalogError",
    "FunctionTypeIssue",
    "load_function_type_catalog",
    "load_function_type_from_mapping",
    "ontology_function_artifact_digest",
]
