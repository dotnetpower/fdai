"""PR-native governance writers for retire-rule and grant-exemption.

Both `governance.retire-rule` and `governance.grant-exemption` declare
`execution_path: pr_native`. These writers render the exact reviewed
catalog-as-code document a pull request would carry. They are pure: nothing here
touches the filesystem, opens a pull request, or changes runtime state, so a
rendered document has no effect until an approved, distinct-approver merge lands
it (``docs/roadmap/decisioning/action-ontology-lifecycle.md``).

`governance.promote-action-type` is deliberately absent. Its catalog entry
declares `execution_path: direct_api`, so a PR-native writer is the wrong shape
for it and the correct dispatcher is a separate design decision.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

_RULE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
_EXEMPTION_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_RESOURCE_GROUP_MAX = 90
_JUSTIFICATION_MIN = 20
_JUSTIFICATION_MAX = 500
_SCHEMA_VERSION = "1.0.0"


class GovernanceWriterError(ValueError):
    """Raised when an input violates a governance-writer invariant."""


class RetirementMode(StrEnum):
    """How far a retirement moves the rule out of the enforce set."""

    SHADOW_ONLY = "shadow_only"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class GovernanceDocument:
    """One rendered document plus the repository path a pull request writes it to.

    ``execution_path`` is always ``pr_native`` and ``applied`` is always False:
    rendering carries no authority.
    """

    path: str
    document: Mapping[str, Any]
    execution_path: str = "pr_native"
    applied: bool = False


def render_rule_retirement(
    *,
    rule_id: str,
    mode: RetirementMode,
    justification: str,
    requested_by: str,
    approved_by: str,
    decided_at: datetime,
) -> GovernanceDocument:
    """Render the reviewed retirement record for one rule."""
    _require_rule_id(rule_id)
    _require_justification(justification)
    _require_distinct_principals(requested_by, approved_by)
    _require_aware(decided_at, "decided_at")
    return GovernanceDocument(
        path=f"rule-catalog/retirements/{rule_id}.yaml",
        document={
            "schema_version": _SCHEMA_VERSION,
            "rule_id": rule_id,
            "mode": mode.value,
            "justification": justification,
            "requested_by": requested_by,
            "approved_by": approved_by,
            "decided_at": _rfc3339(decided_at),
        },
    )


def render_exemption_grant(
    *,
    exemption_id: str,
    rule_id: str,
    subscription_id: str,
    justification: str,
    requested_by: str,
    approved_by: str,
    created_at: datetime,
    expires_at: datetime,
    resource_group: str | None = None,
    resource_ref: str | None = None,
) -> GovernanceDocument:
    """Render the reviewed, time-boxed exemption record for one rule.

    The scope MUST name a resource group or a single resource. A
    subscription-only scope is a subscription-wide override, which is a rule
    retirement rather than an exemption.
    """
    if _EXEMPTION_ID.fullmatch(exemption_id) is None:
        raise GovernanceWriterError("exemption_id MUST be a bounded lowercase identifier")
    _require_rule_id(rule_id)
    _require_justification(justification)
    _require_distinct_principals(requested_by, approved_by)
    if _UUID.fullmatch(subscription_id) is None:
        raise GovernanceWriterError("subscription_id MUST be a lowercase UUID")
    _require_aware(created_at, "created_at")
    _require_aware(expires_at, "expires_at")
    if expires_at <= created_at:
        raise GovernanceWriterError("expires_at MUST be after created_at")
    scope: dict[str, str] = {"subscription_id": subscription_id}
    if resource_group is not None:
        if not resource_group.strip() or len(resource_group) > _RESOURCE_GROUP_MAX:
            raise GovernanceWriterError("resource_group MUST be a bounded non-empty string")
        scope["resource_group"] = resource_group
    if resource_ref is not None:
        if not resource_ref.strip():
            raise GovernanceWriterError("resource_ref MUST be a non-empty string")
        scope["resource_ref"] = resource_ref
    if "resource_group" not in scope and "resource_ref" not in scope:
        raise GovernanceWriterError(
            "exemption scope MUST name a resource group or resource; a "
            "subscription-wide grant is a rule retirement, not an exemption"
        )
    return GovernanceDocument(
        path=f"rule-catalog/exemptions/{exemption_id}.json",
        document={
            "schema_version": _SCHEMA_VERSION,
            "id": exemption_id,
            "rule_id": rule_id,
            "scope": scope,
            "justification": justification,
            "requested_by": requested_by,
            "approved_by": approved_by,
            "state": "active",
            "created_at": _rfc3339(created_at),
            "expires_at": _rfc3339(expires_at),
        },
    )


def _require_rule_id(rule_id: str) -> None:
    if _RULE_ID.fullmatch(rule_id) is None:
        raise GovernanceWriterError("rule_id MUST be a bounded lowercase identifier")


def _require_justification(justification: str) -> None:
    if not _JUSTIFICATION_MIN <= len(justification) <= _JUSTIFICATION_MAX:
        raise GovernanceWriterError(
            f"justification MUST be {_JUSTIFICATION_MIN}-{_JUSTIFICATION_MAX} characters"
        )
    if "\x00" in justification:
        raise GovernanceWriterError("justification MUST NOT contain control bytes")


def _require_distinct_principals(requested_by: str, approved_by: str) -> None:
    for name, value in (("requested_by", requested_by), ("approved_by", approved_by)):
        if _UUID.fullmatch(value) is None:
            raise GovernanceWriterError(f"{name} MUST be a lowercase Entra OID")
    if requested_by == approved_by:
        raise GovernanceWriterError("approved_by MUST differ from requested_by")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise GovernanceWriterError(f"{name} MUST be timezone-aware")


def _rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "GovernanceDocument",
    "GovernanceWriterError",
    "RetirementMode",
    "render_exemption_grant",
    "render_rule_retirement",
]
