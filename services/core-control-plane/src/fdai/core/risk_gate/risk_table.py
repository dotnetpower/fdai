"""Risk-classification first-match table - Axis A of the RiskGate.

Loads ``rule-catalog/risk-classification.yaml`` and evaluates a feature
vector against it, first-match wins (risk-classification.md,
execution-model.md 2.0). The result is the authoritative baseline the
six-axis ceiling (:mod:`fdai.core.risk_gate.ceiling`) combines with
via ``min()``.

Pure and deterministic: no I/O beyond the one-time YAML load; evaluation
is a pure function of the feature vector, so replay reproduces the verdict.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

# Every dimension a rule condition MAY reference. A condition naming an
# unknown key fails at load (risk-classification.md § Classification
# Dimensions).
_KNOWN_DIMENSIONS: frozenset[str] = frozenset(
    {
        "policy_violation",
        "destructive",
        "irreversible",
        "reversible",
        "blast_radius",
        "rollback_path",
        "environment",
        "data_plane_touched",
        "graph_stale",
        "cross_resource_impact",
        "cost_impact_monthly",
        "verifier_confidence",
        "allowlist_prod_auto",
    }
)

_COMPARE_RE = re.compile(r"^(>=|<=|>|<|==)\s*(-?\d+(?:\.\d+)?)$")


class RiskLevel(StrEnum):
    """Terminal risk-table verdict."""

    AUTO = "auto"
    HIL = "hil"
    DENY = "deny"


# Strictness ordering used to validate rule ordering (deny before hil
# before auto). Higher value = more permissive.
_LEVEL_STRICTNESS: dict[RiskLevel, int] = {
    RiskLevel.DENY: 0,
    RiskLevel.HIL: 1,
    RiskLevel.AUTO: 2,
}


@dataclass(frozen=True, slots=True)
class FeatureVector:
    """Signals the risk table matches against.

    Every field is optional; an unset (``None``) signal never satisfies a
    condition, so a rule that needs it simply does not match and evaluation
    falls through to the next rule (ultimately the fail-close default).
    """

    policy_violation: bool | None = None
    destructive: bool | None = None
    irreversible: bool | None = None
    reversible: bool | None = None
    blast_radius: str | None = None
    rollback_path: str | None = None
    environment: str | None = None
    data_plane_touched: bool | None = None
    graph_stale: bool | None = None
    cross_resource_impact: int | None = None
    cost_impact_monthly: float | None = None
    verifier_confidence: float | None = None
    allowlist_prod_auto: bool | None = None

    def as_lookup(self) -> dict[str, Any]:
        return asdict(self)


class RiskTableError(ValueError):
    """Raised when the risk-classification table fails to load/validate."""

    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__("risk-classification table invalid: " + "; ".join(issues))


@dataclass(frozen=True, slots=True)
class _Equality:
    key: str
    expected: object

    def matches(self, lookup: dict[str, Any]) -> bool:
        actual = lookup.get(self.key)
        return actual is not None and actual == self.expected


@dataclass(frozen=True, slots=True)
class _NumericCompare:
    key: str
    op: str
    threshold: float

    def matches(self, lookup: dict[str, Any]) -> bool:
        actual = lookup.get(self.key)
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            return False
        if self.op == ">=":
            return actual >= self.threshold
        if self.op == "<=":
            return actual <= self.threshold
        if self.op == ">":
            return actual > self.threshold
        if self.op == "<":
            return actual < self.threshold
        return actual == self.threshold


_Condition = _Equality | _NumericCompare


@dataclass(frozen=True, slots=True)
class RiskRule:
    rule_id: str
    decision: RiskLevel
    reason: str
    quorum: int = 1
    is_default: bool = False
    conditions: tuple[_Condition, ...] = field(default_factory=tuple)

    def matches(self, lookup: dict[str, Any]) -> bool:
        if self.is_default:
            return True
        return all(c.matches(lookup) for c in self.conditions)


@dataclass(frozen=True, slots=True)
class RiskTableVerdict:
    decision: RiskLevel
    rule_id: str
    quorum: int
    reason: str


@dataclass(frozen=True, slots=True)
class RiskTable:
    version: str
    owner_group: str
    rules: tuple[RiskRule, ...]

    def evaluate(self, vector: FeatureVector) -> RiskTableVerdict:
        """Return the first matching rule's verdict (first-match wins)."""
        lookup = vector.as_lookup()
        for rule in self.rules:
            if rule.matches(lookup):
                return RiskTableVerdict(
                    decision=rule.decision,
                    rule_id=rule.rule_id,
                    quorum=rule.quorum,
                    reason=rule.reason,
                )
        # Unreachable when a default rule is present (the loader requires
        # one), but fail-closed regardless.
        return RiskTableVerdict(
            decision=RiskLevel.HIL, rule_id="implicit-default", quorum=1, reason="no rule matched"
        )


def _make_condition(key: str, value: Any, issues: list[str]) -> _Condition | None:
    if key not in _KNOWN_DIMENSIONS:
        issues.append(f"unknown dimension {key!r}")
        return None
    if isinstance(value, str):
        m = _COMPARE_RE.match(value.strip())
        if m is not None:
            return _NumericCompare(key=key, op=m.group(1), threshold=float(m.group(2)))
    return _Equality(key=key, expected=value)


def _parse_conditions(if_block: Any, issues: list[str]) -> tuple[_Condition, ...]:
    pairs: list[tuple[str, Any]] = []
    if isinstance(if_block, dict) and "all" in if_block:
        items = if_block["all"]
        if not isinstance(items, list):
            issues.append("`if.all` MUST be a list")
            return ()
        for item in items:
            if not isinstance(item, dict):
                issues.append("each `if.all` item MUST be a mapping")
                continue
            pairs.extend(item.items())
    elif isinstance(if_block, dict):
        pairs.extend(if_block.items())
    else:
        issues.append("`if` MUST be a mapping")
        return ()
    conditions: list[_Condition] = []
    for key, value in pairs:
        cond = _make_condition(str(key), value, issues)
        if cond is not None:
            conditions.append(cond)
    return tuple(conditions)


def load_risk_table_from_mapping(raw: Any) -> RiskTable:
    """Validate a parsed risk-table mapping and return a :class:`RiskTable`."""
    issues: list[str] = []
    if not isinstance(raw, dict):
        raise RiskTableError(["top-level document MUST be a mapping"])
    version = raw.get("version")
    owner_group = raw.get("owner_group")
    if not isinstance(version, str):
        issues.append("`version` MUST be a string")
    if not isinstance(owner_group, str):
        issues.append("`owner_group` MUST be a string")
    raw_rules = raw.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise RiskTableError(issues + ["`rules` MUST be a non-empty list"])

    rules: list[RiskRule] = []
    default_count = 0
    for index, raw_rule in enumerate(raw_rules):
        if not isinstance(raw_rule, dict):
            issues.append(f"rule[{index}] MUST be a mapping")
            continue
        rule_id = str(raw_rule.get("id", f"rule-{index}"))
        reason = str(raw_rule.get("reason", ""))
        if "default" in raw_rule:
            level = _coerce_level(raw_rule["default"], index, issues)
            default_count += 1
            rules.append(RiskRule(rule_id=rule_id, decision=level, reason=reason, is_default=True))
            continue
        level = _coerce_level(raw_rule.get("decision"), index, issues)
        quorum = raw_rule.get("quorum", 1)
        if not isinstance(quorum, int) or isinstance(quorum, bool) or quorum < 1:
            issues.append(f"rule[{index}] quorum MUST be an integer >= 1")
            quorum = 1
        conditions = _parse_conditions(raw_rule.get("if"), issues)
        rules.append(
            RiskRule(
                rule_id=rule_id,
                decision=level,
                reason=reason,
                quorum=quorum,
                conditions=conditions,
            )
        )

    _validate_ordering(rules, issues)
    if default_count != 1:
        issues.append(f"exactly one `default` rule required, found {default_count}")
    default_rules = [r for r in rules if r.is_default]
    if default_rules and default_rules[0].decision is RiskLevel.AUTO:
        issues.append(
            "the `default` (fail-close) rule MUST NOT be `auto`; an unmatched event MUST "
            "fail toward safety (hil or deny). Otherwise an ActionType with env_scope=any "
            "that defers prod handling to this table would auto-execute in prod"
        )
    if issues:
        raise RiskTableError(issues)
    return RiskTable(version=str(version), owner_group=str(owner_group), rules=tuple(rules))


def _coerce_level(value: Any, index: int, issues: list[str]) -> RiskLevel:
    try:
        return RiskLevel(value)
    except ValueError:
        issues.append(f"rule[{index}] decision {value!r} is not one of auto/hil/deny")
        return RiskLevel.HIL


def _validate_ordering(rules: list[RiskRule], issues: list[str]) -> None:
    """Deny rules first, then hil, then auto, then the default catch-all."""
    seen_strictness = -1
    for rule in rules:
        if rule.is_default:
            continue
        strict = _LEVEL_STRICTNESS[rule.decision]
        if strict < seen_strictness:
            issues.append(
                f"rule {rule.rule_id!r} ({rule.decision.value}) is out of order: "
                "deny rules MUST precede hil, hil MUST precede auto"
            )
        seen_strictness = max(seen_strictness, strict)


def load_risk_table(path: Path) -> RiskTable:
    """Load and validate the risk-classification table from a YAML file."""
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return load_risk_table_from_mapping(raw)


__all__ = [
    "FeatureVector",
    "RiskLevel",
    "RiskRule",
    "RiskTable",
    "RiskTableError",
    "RiskTableVerdict",
    "load_risk_table",
    "load_risk_table_from_mapping",
]
