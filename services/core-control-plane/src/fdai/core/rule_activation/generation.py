"""Deterministic construction and resolution of Rule activation generations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime

from fdai_service_contracts.rule_activation import (
    RuleActivationGeneration,
    RuleActivationMember,
    rule_activation_generation_digest,
)

from fdai.shared.contracts.models import Rule


def build_rule_activation_generation(
    rules: Sequence[Rule],
    *,
    profile_id: str,
    profile_version: str,
    created_at: datetime,
    catalog_digest: str | None = None,
) -> RuleActivationGeneration:
    """Build a complete content-addressed generation from validated Rule objects."""

    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("Rule activation generation clock MUST be timezone-aware")
    canonical_rules = sorted(rules, key=lambda rule: rule.id)
    if not canonical_rules:
        raise ValueError("Rule activation generation MUST contain at least one Rule")
    members = tuple(
        RuleActivationMember(
            rule_id=rule.id,
            rule_version=str(rule.version),
            rule_digest=rule_digest(rule),
        )
        for rule in canonical_rules
    )
    resolved_catalog_digest = catalog_digest or _digest(
        [rule.model_dump(mode="json") for rule in canonical_rules]
    )
    if len(resolved_catalog_digest) != 64 or any(
        character not in "0123456789abcdef" for character in resolved_catalog_digest
    ):
        raise ValueError("Rule activation catalog digest MUST be lowercase SHA-256")
    generation_digest = rule_activation_generation_digest(
        profile_id=profile_id,
        profile_version=profile_version,
        catalog_digest=resolved_catalog_digest,
        members=members,
    )
    return RuleActivationGeneration(
        generation_id=f"rule-activation-{generation_digest[:32]}",
        generation_digest=generation_digest,
        profile_id=profile_id,
        profile_version=profile_version,
        catalog_digest=resolved_catalog_digest,
        members=members,
        created_at=created_at,
    )


def resolve_rule_activation_generation(
    generation: RuleActivationGeneration,
    available: Mapping[str, Rule],
) -> tuple[Rule, ...]:
    """Resolve exact Rule objects or reject installed-artifact drift."""

    resolved: list[Rule] = []
    for member in generation.members:
        rule = available.get(member.rule_id)
        if (
            rule is None
            or str(rule.version) != member.rule_version
            or rule_digest(rule) != member.rule_digest
        ):
            raise RuntimeError(
                f"active Rule generation does not match installed artifact: {member.rule_id}"
            )
        resolved.append(rule)
    return tuple(resolved)


def rule_digest(rule: Rule) -> str:
    """Return the canonical digest of one complete Rule artifact."""

    return _digest(rule.model_dump(mode="json"))


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "build_rule_activation_generation",
    "resolve_rule_activation_generation",
    "rule_digest",
]
