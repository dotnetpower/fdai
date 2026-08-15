"""Startup binding for the governed rule-catalog profile.

``FDAI_PROFILE_ID`` selects one profile from ``rule-catalog/profiles/`` or a
fork overlay under ``rule-catalog/profiles-overrides/``. The composition root
resolves it exactly once here and folds the result into the loaded rule tuple
before :class:`~fdai.core.tiers.t0_deterministic.index.RuleIndex` is built, so
the deterministic tier and the safety check that evaluates the same indexed
``Rule`` observe one immutable result
(``docs/roadmap/rules-and-detection/rule-catalog-profiles.md`` section 4).

A profile selects and grades rules. It never promotes: a profile-declared
``enforce`` mode is reported for diagnostics only, and execution authority
still comes solely from the authoritative promotion registry.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fdai.core.rule_catalog_profiles import ProfileRegistry, ProfileResolutionError
from fdai.core.rule_catalog_profiles.models import ProfileMode, SeverityOverride
from fdai.shared.contracts.models import Rule, Severity

_LOGGER = logging.getLogger("fdai.startup")

PROFILE_ID_ENV = "FDAI_PROFILE_ID"
"""Governed environment knob naming the profile to bind at startup."""

_PROFILES_DIRNAME = "profiles"
_OVERRIDES_DIRNAME = "profiles-overrides"


@dataclass(frozen=True, slots=True)
class RuleProfileBinding:
    """One immutable startup resolution of the governed profile.

    ``rules`` is the activated subset in ascending rule-id order. Every
    consumer receives this same tuple; nothing re-resolves the profile.
    """

    profile_id: str
    title: str
    digest: str
    rules: tuple[Rule, ...]
    excluded_rule_ids: tuple[str, ...]
    escalated_rule_ids: tuple[str, ...]
    enforce_requested_rule_ids: tuple[str, ...]
    shadow_requested_rule_ids: tuple[str, ...] = ()

    def diagnostics(self) -> dict[str, object]:
        """Return the startup diagnostic fields.

        Only the profile id, the digest, and counts are exposed. Rule
        parameters can carry tenant values, so they contribute to the digest
        but never to a log record.
        """
        return {
            "profile_id": self.profile_id,
            "profile_digest": self.digest,
            "activated_rules": len(self.rules),
            "excluded_rules": len(self.excluded_rule_ids),
            "escalated_rules": len(self.escalated_rule_ids),
            "enforce_requested_rules": len(self.enforce_requested_rule_ids),
            "shadow_requested_rules": len(self.shadow_requested_rule_ids),
        }


def build_profile_registry(catalog_root: Path) -> ProfileRegistry:
    """Load the upstream profile tree plus the fork overlay when present."""
    return ProfileRegistry.from_directories(
        upstream=catalog_root / _PROFILES_DIRNAME,
        overlays=(catalog_root / _OVERRIDES_DIRNAME,),
    )


def resolve_rule_profile(
    rules: Sequence[Rule],
    *,
    profile_id: str,
    registry: ProfileRegistry,
) -> RuleProfileBinding:
    """Resolve ``profile_id`` against ``rules`` and return the bound result.

    Raises :class:`ProfileResolutionError` when the profile is unknown, refers
    to a rule the catalog does not ship, downgrades an authored severity floor,
    or activates no rule at all.
    """
    catalog_by_id: dict[str, Rule] = {}
    for rule in rules:
        if rule.id in catalog_by_id:
            raise ProfileResolutionError(f"duplicate rule id in catalog: {rule.id!r}")
        catalog_by_id[rule.id] = rule

    floors: dict[str, SeverityOverride] = {
        rule_id: SeverityOverride(rule.severity.value) for rule_id, rule in catalog_by_id.items()
    }
    resolved = registry.resolve(
        profile_id,
        rule_severity_floors=floors,
        known_rule_ids=catalog_by_id.keys(),
        strict=True,
    )
    if not resolved.rules:
        raise ProfileResolutionError(
            f"profile {profile_id!r} activates no catalog rule; refusing to bind "
            "an empty deterministic tier"
        )

    activated: list[Rule] = []
    escalated: list[str] = []
    enforce_requested: list[str] = []
    shadow_requested: list[str] = []
    for resolved_rule in resolved.rules:
        source = catalog_by_id[resolved_rule.id]
        update: dict[str, object] = {}
        if resolved_rule.severity_override is not None:
            severity = Severity(resolved_rule.severity_override.value)
            if severity is not source.severity:
                update["severity"] = severity
                escalated.append(resolved_rule.id)
        if resolved_rule.parameters:
            merged = {**source.parameters, **resolved_rule.parameters}
            if merged != source.parameters:
                update["parameters"] = merged
        if resolved_rule.mode is ProfileMode.ENFORCE:
            enforce_requested.append(resolved_rule.id)
        else:
            shadow_requested.append(resolved_rule.id)
        activated.append(source.model_copy(update=update) if update else source)

    excluded = sorted(set(catalog_by_id) - set(resolved.ids()))
    return RuleProfileBinding(
        profile_id=resolved.id,
        title=resolved.title,
        digest=_digest(resolved.id, activated),
        rules=tuple(activated),
        excluded_rule_ids=tuple(excluded),
        escalated_rule_ids=tuple(escalated),
        enforce_requested_rule_ids=tuple(enforce_requested),
        shadow_requested_rule_ids=tuple(shadow_requested),
    )


def bind_rule_profile(
    rules: Sequence[Rule],
    *,
    catalog_root: Path,
    environ: Mapping[str, str] | None = None,
) -> RuleProfileBinding | None:
    """Bind the governed profile named by ``FDAI_PROFILE_ID``.

    Returns ``None`` when the knob is absent or blank, which keeps the
    unprofiled default of loading the whole catalog. Any other failure is
    fail-closed: startup must not silently fall back to a wider rule set than
    the operator selected.
    """
    source = os.environ if environ is None else environ
    profile_id = source.get(PROFILE_ID_ENV, "").strip()
    if not profile_id:
        return None
    binding = resolve_rule_profile(
        rules,
        profile_id=profile_id,
        registry=build_profile_registry(catalog_root),
    )
    _LOGGER.info("rule_profile_bound", extra=binding.diagnostics())
    return binding


def _digest(profile_id: str, activated: Iterable[Rule]) -> str:
    """Return a stable sha256 over the bound profile.

    The digest covers the applied severity and parameters, so two runtimes
    reporting the same digest resolved the same rule set from the same inputs.
    """
    canonical = json.dumps(
        {
            "profile_id": profile_id,
            "rules": [
                {
                    "id": rule.id,
                    "version": rule.version,
                    "severity": rule.severity.value,
                    "parameters": rule.parameters,
                }
                for rule in activated
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "PROFILE_ID_ENV",
    "RuleProfileBinding",
    "bind_rule_profile",
    "build_profile_registry",
    "resolve_rule_profile",
]
