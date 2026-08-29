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
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from importlib import resources
from typing import Annotated, Any
from uuid import UUID

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    """Reviewed lifecycle state.

    The expiry job records ``active -> expired``. A reviewed revocation records
    ``active -> revoked``. Both target states are terminal; ``revoked_at`` is
    audit metadata, not a scheduled future transition.
    """

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

    @field_validator("created_at", "expires_at", "revoked_at")
    @classmethod
    def _require_utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp MUST include an explicit UTC offset")
        if value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("timestamp MUST use UTC")
        return value

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

    @model_validator(mode="after")
    def _require_consistent_revocation(self) -> Exemption:
        has_revoked_at = self.revoked_at is not None
        has_revoked_by = self.revoked_by is not None
        if self.state is ExemptionState.REVOKED:
            if not has_revoked_at or not has_revoked_by:
                raise ValueError("revoked state MUST set both revoked_at and revoked_by")
            if self.revoked_at is not None and self.revoked_at < self.created_at:
                raise ValueError("revoked_at MUST be at or after created_at")
        elif has_revoked_at or has_revoked_by:
            raise ValueError("non-revoked state MUST NOT set revoked_at or revoked_by")
        return self


# ---------------------------------------------------------------------------
# Configured maximum duration (rule-governance.md "Exemptions")
# ---------------------------------------------------------------------------


def exemption_duration_issue(
    exemption: Exemption, *, max_duration: timedelta
) -> ExemptionIssue | None:
    """Return an issue when ``exemption`` exceeds the configured maximum duration.

    Pure and deterministic: compares ``expires_at - created_at`` (both already
    validated UTC timestamps) against ``max_duration``
    (``AppConfig.rule_governance.exemption_max_duration_days``). Returns ``None``
    when the exemption's duration is within bound. The load boundary
    (:func:`fdai.rule_catalog.schema.governance_catalog.load_governance_catalog`)
    aggregates this alongside every other exemption issue and fails closed.
    """
    duration = exemption.expires_at - exemption.created_at
    if duration <= max_duration:
        return None
    return ExemptionIssue(
        key=f"{exemption.id}:expires_at",
        message=(f"exemption duration {duration} exceeds the configured maximum {max_duration}"),
    )


def exemption_duration_issues(
    exemptions: Iterable[Exemption], *, max_duration: timedelta
) -> list[ExemptionIssue]:
    """Return every :func:`exemption_duration_issue` across ``exemptions``."""
    issues: list[ExemptionIssue] = []
    for exemption in exemptions:
        issue = exemption_duration_issue(exemption, max_duration=max_duration)
        if issue is not None:
            issues.append(issue)
    return issues


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _load_json_schema() -> dict[str, Any]:
    raw = resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_FILE).read_text(encoding="utf-8")
    return json.loads(raw)  # type: ignore[no-any-return]


def parse_exemption_json(text: str) -> dict[str, Any]:
    """Parse one exemption document and reject duplicate keys at any depth."""

    def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    raw = json.loads(text, object_pairs_hook=_unique_object)
    if not isinstance(raw, dict):
        raise ValueError("top-level JSON must be an object")
    return raw


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
    "exemption_duration_issue",
    "exemption_duration_issues",
    "load_exemption_from_mapping",
    "parse_exemption_json",
]
