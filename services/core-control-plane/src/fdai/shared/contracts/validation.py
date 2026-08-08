"""Boundary validation - the DI seam that decides *how untrusted input is checked*.

Per ``coding-conventions.instructions.md``:

- Validate untrusted input **at system boundaries only** (event ingress, API,
  config, rule-catalog load) - never sprinkle defensive checks through core.
- **Fail closed**: on ambiguity or verification failure, abstain or escalate,
  never execute.

Core modules therefore depend on the :class:`EventValidator` /
:class:`ContractValidator` :class:`~typing.Protocol` interfaces, not on the
concrete implementation. The upstream default,
:class:`JsonSchemaContractValidator`, uses JSON Schema draft-2020-12 (via the
``jsonschema`` package) sourced from an injected :class:`SchemaRegistry`.
A fork MAY register a stricter or vendor-augmented validator without touching
``core/``.

The concrete validator is *stateless* apart from its cached compiled schemas;
callers instantiate one per composition root (there is no shared global).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as _JsonSchemaValidationError

from .registry import SchemaRegistry

# ---------------------------------------------------------------------------
# DI seams (Protocols)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Structured issue emitted by a validator. English only, secret-free."""

    path: str
    message: str


class ContractValidationError(ValueError):
    """Raised when an instance fails validation.

    Carries a list of :class:`ValidationIssue` so callers can surface a
    structured error to an audit entry or a boundary log without leaking
    the raw payload.
    """

    def __init__(self, schema: str, issues: list[ValidationIssue]) -> None:
        self.schema = schema
        self.issues = issues
        preview = "; ".join(f"{i.path}: {i.message}" for i in issues[:3])
        suffix = f" (+{len(issues) - 3} more)" if len(issues) > 3 else ""
        super().__init__(f"{schema} validation failed: {preview}{suffix}")


@runtime_checkable
class ContractValidator(Protocol):
    """Validate an instance against a named schema."""

    def validate(
        self,
        schema_name: str,
        instance: Mapping[str, Any],
        *,
        version: str | None = None,
    ) -> None:
        """Raise :class:`ContractValidationError` on failure; return None on success."""
        ...


@runtime_checkable
class EventValidator(Protocol):
    """Domain-specialized alias - validates a single :class:`Event` instance.

    Kept as a distinct Protocol so a fork MAY apply event-specific extra rules
    (e.g. deny event ``source`` values outside an allowlist) without also
    changing action / rule validation semantics.
    """

    def validate(self, instance: Mapping[str, Any]) -> None: ...


# ---------------------------------------------------------------------------
# Upstream default: JSON-Schema-backed validator
# ---------------------------------------------------------------------------


class JsonSchemaContractValidator:
    """Default :class:`ContractValidator`.

    Uses JSON Schema draft-2020-12 loaded from an injected
    :class:`SchemaRegistry`. Compiled validators are cached per
    ``(schema_name, version)`` for the lifetime of the instance.
    """

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
            # Draft202012Validator.check_schema raises if the schema itself is
            # malformed - that is a startup bug, not a runtime user error.
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema)
            self._cache[(schema_name, version)] = validator

        errors = sorted(validator.iter_errors(dict(instance)), key=lambda e: list(e.path))
        if errors:
            issues = [_issue(e) for e in errors]
            raise ContractValidationError(schema_name, issues)


class JsonSchemaEventValidator:
    """Convenience :class:`EventValidator` wrapping :class:`JsonSchemaContractValidator`."""

    def __init__(self, validator: ContractValidator) -> None:
        self._validator = validator

    def validate(self, instance: Mapping[str, Any]) -> None:
        self._validator.validate("event", instance)


def _issue(err: _JsonSchemaValidationError) -> ValidationIssue:
    path = "/" + "/".join(str(p) for p in err.absolute_path)
    return ValidationIssue(path=path or "/", message=err.message)


__all__ = [
    "ContractValidationError",
    "ContractValidator",
    "EventValidator",
    "JsonSchemaContractValidator",
    "JsonSchemaEventValidator",
    "ValidationIssue",
]
