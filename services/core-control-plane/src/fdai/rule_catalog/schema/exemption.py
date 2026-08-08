"""PolicyExemption model + fail-fast loader.

Mirror of ``rule-catalog/schema/exemption.json`` - the JSON Schema is the
source of truth for structural validation at the boundary; this pydantic
model layers on invariants the schema cannot express (requester ≠
approver; expires_at > created_at).

The loader follows the same aggregate-issue pattern as
:mod:`fdai.shared.config.loader` - every problem is reported in one
:class:`ExemptionError` so a reviewer sees the full remediation list in
one shot.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from importlib import resources
from typing import Annotated, Any
from uuid import UUID

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator

_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_SCHEMA_FILE = "exemption.schema.json"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExemptionIssue:
    key: str
    message: str


class ExemptionError(ValueError):
    """Aggregate error surfaced at the exemption-load boundary."""

    def __init__(self, issues: list[ExemptionIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{i.key}: {i.message}" for i in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"exemption validation failed: {preview}{suffix}")


# ---------------------------------------------------------------------------
# Enums & model
# ---------------------------------------------------------------------------


class ExemptionState(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ExemptionScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subscription_id: UUID
    resource_group: Annotated[str, Field(min_length=1, max_length=90)] | None = None
    resource_ref: Annotated[str, Field(min_length=1)] | None = None

    @model_validator(mode="after")
    def _require_bounded_scope(self) -> ExemptionScope:
        # Scope MUST be bounded to a resource-group-equivalent grouping or
        # narrower (architecture.instructions.md § Human Override). A
        # subscription-only scope (both resource_group and resource_ref
        # absent) is a subscription-wide override, which is rejected -
        # disabling a rule subscription-wide is a rule RETIREMENT, not an
        # override, and must go through the catalog pipeline. Enforced
        # here (not just documented) so a hand-authored / fork exemption
        # cannot silently suppress a rule across a whole subscription.
        if self.resource_group is None and self.resource_ref is None:
            raise ValueError(
                "exemption scope MUST set resource_group or resource_ref - "
                "subscription-wide overrides are rejected "
                "(architecture.instructions.md § Human Override)"
            )
        return self


class Exemption(BaseModel):
    """Time-boxed, audited exemption artifact."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )

    schema_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")]
    rule_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")]
    scope: ExemptionScope
    justification: Annotated[str, Field(min_length=20, max_length=2048)]
    requested_by: UUID
    approved_by: UUID
    state: ExemptionState
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    revoked_by: UUID | None = None

    @model_validator(mode="after")
    def _require_distinct_approver(self) -> Exemption:
        if self.requested_by == self.approved_by:
            raise ValueError(
                "requested_by MUST differ from approved_by "
                "(architecture.instructions.md § HIL Approval Integrity)"
            )
        return self

    @model_validator(mode="after")
    def _require_expiry_in_future_of_creation(self) -> Exemption:
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at MUST be strictly after created_at")
        return self


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _load_json_schema() -> dict[str, Any]:
    raw = resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_FILE).read_text(encoding="utf-8")
    return json.loads(raw)  # type: ignore[no-any-return]


def load_exemption_from_mapping(raw: Mapping[str, Any]) -> Exemption:
    """Validate ``raw`` and return an :class:`Exemption` on success.

    Aggregates schema + pydantic issues into a single
    :class:`ExemptionError`.
    """
    issues: list[ExemptionIssue] = []

    schema = _load_json_schema()
    validator = Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(dict(raw)), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in err.absolute_path) or "<root>"
        issues.append(ExemptionIssue(key=path, message=err.message))

    if issues:
        raise ExemptionError(issues)

    try:
        return Exemption.model_validate(raw)
    except ValueError as exc:
        # pydantic ValidationError is a subclass of ValueError.
        errors = getattr(exc, "errors", None)
        if callable(errors):
            for e in errors():
                loc = ".".join(str(p) for p in e.get("loc", ()))
                issues.append(ExemptionIssue(key=loc or "<root>", message=e["msg"]))
        else:
            issues.append(ExemptionIssue(key="<root>", message=str(exc)))
        raise ExemptionError(issues) from exc


__all__ = [
    "Exemption",
    "ExemptionError",
    "ExemptionIssue",
    "ExemptionScope",
    "ExemptionState",
    "load_exemption_from_mapping",
]
