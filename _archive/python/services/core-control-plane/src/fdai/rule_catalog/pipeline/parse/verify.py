"""Rule-set verifier - parsed mappings → the P1 loader.

Wraps :func:`load_rule_from_mapping` in an aggregate-issue shape so a
collector caller (CLI, PR pipeline) can report *every* schema /
cross-reference violation across an entire source, not just the first.

Deliberately kept as its own module (not a method on :class:`Parser`)
because verification requires the ActionType catalog + ResourceType
registry + schema registry - dependencies the parser itself has no
business owning. The composition root (CLI, orchestrator) wires them
in.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai.rule_catalog.pipeline.parse.parser import ParsedRule
from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry
from fdai.rule_catalog.schema.rule import (
    RuleCatalogError,
    load_rule_from_mapping,
)
from fdai.shared.contracts.models import OntologyActionType, Rule
from fdai.shared.contracts.registry import SchemaRegistry


@dataclass(frozen=True, slots=True)
class RuleVerificationIssue:
    """One issue surfaced by the verifier.

    ``origin`` mirrors :class:`ParsedRule.origin` so the caller can
    correlate an error back to the source file that emitted it.
    """

    origin: str
    key: str
    message: str


@dataclass(frozen=True, slots=True)
class RuleVerificationReport:
    """Aggregate of one verification pass."""

    verified: tuple[Rule, ...]
    issues: tuple[RuleVerificationIssue, ...]

    @property
    def verified_count(self) -> int:
        return len(self.verified)

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def passed(self) -> bool:
        return not self.issues


def verify_parsed_rules(
    rules: Iterable[ParsedRule],
    *,
    schema_registry: SchemaRegistry,
    action_types: Iterable[OntologyActionType],
    resource_types: ResourceTypeRegistry,
    policies_root: Path | None = None,
    remediation_root: Path | None = None,
) -> RuleVerificationReport:
    """Validate each parsed rule with the P1 loader.

    Duplicate ``id`` detection matches :func:`load_rule_catalog`: a
    second entry with the same ``id`` is flagged and skipped from the
    ``verified`` set.

    ``policies_root`` / ``remediation_root`` - same semantics as
    :func:`load_rule_from_mapping`. Pass ``None`` to skip the on-disk
    check (typical for a snapshot whose Rego / template refs live in
    the *target* repo, not the *source* snapshot).
    """
    action_type_names = {a.name for a in action_types}
    resource_type_ids = resource_types.ids()

    verified: list[Rule] = []
    issues: list[RuleVerificationIssue] = []
    seen_ids: dict[str, str] = {}

    for parsed in rules:
        try:
            normalized = _with_dispatch_baseline(parsed.raw)
            rule = load_rule_from_mapping(
                normalized,
                schema_registry=schema_registry,
                action_type_names=action_type_names,
                resource_type_ids=resource_type_ids,
                origin=parsed.origin,
                policies_root=policies_root,
                remediation_root=remediation_root,
            )
        except RuleCatalogError as exc:
            for issue in exc.issues:
                issues.append(
                    RuleVerificationIssue(
                        origin=parsed.origin,
                        key=issue.key,
                        message=issue.message,
                    )
                )
            continue

        prior = seen_ids.get(rule.id)
        if prior is not None:
            issues.append(
                RuleVerificationIssue(
                    origin=parsed.origin,
                    key=f"{parsed.origin}:id",
                    message=f"duplicate rule id {rule.id!r} (also in {prior})",
                )
            )
            continue
        seen_ids[rule.id] = parsed.origin
        verified.append(rule)

    return RuleVerificationReport(
        verified=tuple(verified),
        issues=tuple(issues),
    )


def _with_dispatch_baseline(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Add explicit Rule v2 dispatch metadata when an upstream source omits it."""

    normalized = dict(raw)
    resource_type = normalized.get("resource_type")
    if isinstance(resource_type, str) and resource_type:
        normalized.setdefault("applies_to", [resource_type])
        normalized.setdefault(
            "submission_criteria",
            [{"kind": "resource_type_registered", "value": resource_type}],
        )
    normalized.setdefault("triggered_by", ["*"])
    normalized.setdefault("evaluates", ["*"])
    normalized.setdefault("required_interfaces", ["Evaluable", "Remediable"])
    normalized.setdefault("scope_predicates", {})
    if normalized.get("schema_version") == "1.0.0":
        normalized["schema_version"] = "2.0.0"
    return normalized
