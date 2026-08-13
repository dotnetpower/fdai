"""Package-backed JSON Schema registry and boundary validator."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from typing import Any, Protocol, runtime_checkable

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError


@runtime_checkable
class SchemaRegistry(Protocol):
    """Return raw JSON Schemas by name and optional semantic version."""

    def get(self, name: str, version: str | None = None) -> Mapping[str, object]: ...

    def names(self) -> list[str]: ...


class SchemaNotFoundError(LookupError):
    """Raised when a schema registry cannot resolve a name and version."""


_PACKAGE_SCHEMAS: dict[tuple[str, str], str] = {
    ("action", "1.0.0"): "schemas/action/1.0.0.json",
    ("agent-operational-activity", "1.0.0"): "schemas/agent-operational-activity/1.0.0.json",
    ("document-deletion-request", "1.0.0"): "schemas/document-deletion-request/1.0.0.json",
    ("core-operator-projection", "1.0.0"): "schemas/core-operator-projection/1.0.0.json",
    ("core-operator-projection", "1.1.0"): "schemas/core-operator-projection/1.1.0.json",
    ("core-operator-projection", "1.2.0"): "schemas/core-operator-projection/1.2.0.json",
    ("document-ingestion-activity", "1.0.0"): "schemas/document-ingestion-activity/1.0.0.json",
    ("document-ingestion-activity", "1.1.0"): "schemas/document-ingestion-activity/1.1.0.json",
    ("document-worker-audit", "1.0.0"): "schemas/document-worker-audit/1.0.0.json",
    ("document-worker-index", "1.0.0"): "schemas/document-worker-index/1.0.0.json",
    ("executor-command", "1.0.0"): "schemas/executor-command/1.0.0.json",
    ("executor-receipt", "1.0.0"): "schemas/executor-receipt/1.0.0.json",
    ("executor-receipt", "1.1.0"): "schemas/executor-receipt/1.1.0.json",
    ("operator-core-request", "1.0.0"): "schemas/operator-core-request/1.0.0.json",
    ("operator-core-request", "1.1.0"): "schemas/operator-core-request/1.1.0.json",
    ("operator-core-request", "1.2.0"): "schemas/operator-core-request/1.2.0.json",
    ("operator-core-request", "1.3.0"): "schemas/operator-core-request/1.3.0.json",
    ("service-upgrade-receipt", "1.0.0"): "schemas/service-upgrade-receipt/1.0.0.json",
}


class PackageResourceSchemaRegistry:
    """Load immutable JSON Schemas shipped in ``fdai_service_contracts``."""

    def __init__(self, package: str = "fdai_service_contracts") -> None:
        self._package = package
        self._cache: dict[tuple[str, str], Mapping[str, object]] = {}

    def get(self, name: str, version: str | None = None) -> Mapping[str, object]:
        target_version = version or self._latest_version(name)
        if target_version is None:
            raise SchemaNotFoundError(f"unknown schema name: {name!r}")
        cached = self._cache.get((name, target_version))
        if cached is not None:
            return cached
        relative_path = _PACKAGE_SCHEMAS.get((name, target_version))
        if relative_path is None:
            raise SchemaNotFoundError(f"unknown schema: name={name!r} version={target_version!r}")
        raw = resources.files(self._package).joinpath(relative_path).read_text(encoding="utf-8")
        loaded = json.loads(raw)
        if not isinstance(loaded, dict):
            raise SchemaNotFoundError(f"schema {name!r} is not a JSON object")
        self._cache[(name, target_version)] = loaded
        return loaded

    def names(self) -> list[str]:
        """List every unversioned schema name in the package."""

        return sorted({name for name, _version in _PACKAGE_SCHEMAS})

    def _latest_version(self, name: str) -> str | None:
        versions = [version for schema_name, version in _PACKAGE_SCHEMAS if schema_name == name]
        if not versions:
            return None
        return max(versions, key=_semver_key)


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Secret-free structured JSON Schema validation issue."""

    path: str
    message: str


class ContractValidationError(ValueError):
    """Raised when a boundary instance fails contract validation."""

    def __init__(self, schema: str, issues: list[ValidationIssue]) -> None:
        self.schema = schema
        self.issues = issues
        preview = "; ".join(f"{issue.path}: {issue.message}" for issue in issues[:3])
        suffix = f" (+{len(issues) - 3} more)" if len(issues) > 3 else ""
        super().__init__(f"{schema} validation failed: {preview}{suffix}")


@runtime_checkable
class ContractValidator(Protocol):
    """Validate one mapping against a named schema."""

    def validate(
        self,
        schema_name: str,
        instance: Mapping[str, Any],
        *,
        version: str | None = None,
    ) -> None: ...


class JsonSchemaContractValidator:
    """Validate boundary records with JSON Schema draft 2020-12."""

    def __init__(self, registry: SchemaRegistry) -> None:
        self._registry = registry
        self._cache: dict[tuple[str, str | None], Draft202012Validator] = {}

    def validate(
        self,
        schema_name: str,
        instance: Mapping[str, Any],
        *,
        version: str | None = None,
    ) -> None:
        validator = self._cache.get((schema_name, version))
        if validator is None:
            schema = self._registry.get(schema_name, version)
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema, format_checker=FormatChecker())
            self._cache[(schema_name, version)] = validator
        errors = sorted(validator.iter_errors(dict(instance)), key=lambda error: list(error.path))
        if errors:
            raise ContractValidationError(schema_name, [_issue(error) for error in errors])


def _issue(error: JsonSchemaValidationError) -> ValidationIssue:
    path = "/" + "/".join(str(part) for part in error.absolute_path)
    return ValidationIssue(path=path or "/", message=error.message)


def _semver_key(version: str) -> tuple[int, int, int]:
    major, minor, patch = version.split(".", 2)
    return int(major), int(minor), int(patch)


__all__ = [
    "ContractValidationError",
    "ContractValidator",
    "JsonSchemaContractValidator",
    "PackageResourceSchemaRegistry",
    "SchemaNotFoundError",
    "SchemaRegistry",
    "ValidationIssue",
]
