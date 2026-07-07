"""ProfileRegistry - directory-driven profile loader + resolver.

Semantics:

- Upstream ships ``rule-catalog/profiles/`` with the ``baseline``,
  ``recommended``, and ``strict`` chain (see
  ``docs/roadmap/rule-catalog-profiles.md``).
- A fork adds a sibling directory ``rule-catalog/profiles-overrides/``
  that the registry deep-merges over the upstream tree at load. A
  profile id present in both wins from the overlay; a profile only in
  the overlay is added; a profile only upstream stays as-is. The
  overlay MAY declare ``extends`` referencing an upstream profile id.
- ``resolve(profile_id)`` walks the ``extends`` graph and applies the
  merge rules in
  ``docs/roadmap/rule-catalog-profiles.md § Resolution``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

from .models import (
    Profile,
    ProfileMode,
    ProfileResolutionError,
    ProfileRule,
    ResolvedProfile,
    ResolvedRule,
    SeverityOverride,
    severity_at_or_above_floor,
)


class ProfileRegistry:
    """In-memory index of :class:`Profile` objects."""

    def __init__(self, *, profiles: Iterable[Profile]) -> None:
        self._by_id: dict[str, Profile] = {}
        for profile in profiles:
            if profile.id in self._by_id:
                raise ProfileResolutionError(f"duplicate profile id {profile.id!r}")
            self._by_id[profile.id] = profile
        # Populated by ``from_directories`` when a fork overlay replaces
        # an upstream profile of the same id. Empty tuple otherwise.
        # Tuple of ``(profile_id, overlay_file, new_title)`` triples so a
        # caller (CLI, CI reporter) can surface the swap explicitly.
        self._overlay_replacements: tuple[tuple[str, str, str], ...] = ()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, profile_id: str) -> Profile | None:
        return self._by_id.get(profile_id)

    def all(self) -> tuple[Profile, ...]:
        return tuple(self._by_id.values())

    def overlay_replacements(self) -> tuple[tuple[str, str, str], ...]:
        """Return the (profile_id, overlay_path, overlay_title) triples
        that were replaced when a fork overlay shadowed an upstream
        profile.

        Empty tuple when the registry was built purely from upstream
        (no overlays passed) or when overlays only added new ids.
        Callers use this to log or fail a CI job when a fork silently
        overrode an upstream profile without declaring intent.
        """
        return self._overlay_replacements

    def resolve(
        self,
        profile_id: str,
        *,
        rule_severity_floors: Mapping[str, SeverityOverride] | None = None,
        known_rule_ids: Iterable[str] | None = None,
        strict: bool = True,
    ) -> ResolvedProfile:
        """Flatten ``extends`` graph and merge rules into a
        :class:`ResolvedProfile`.

        ``rule_severity_floors`` - optional mapping of rule id to its
        authored severity floor. When supplied, any profile-level
        ``severity_override`` that downgrades below the floor raises
        :class:`ProfileResolutionError` (fail-closed: an authoring
        mistake surfaces at load, not at runtime).

        ``known_rule_ids`` - the ids the caller has already validated
        exist in the rule catalog. Any profile rule id NOT in that set
        raises :class:`ProfileResolutionError`.

        ``strict`` - defaults to True (fail-closed). When True AND
        ``known_rule_ids`` is None, :meth:`resolve` refuses to run and
        raises :class:`ProfileResolutionError` - a caller that does
        not know the rule catalog cannot safely materialize a profile.
        The escape hatch is ``strict=False`` (explicit opt-in to
        lenient mode) which allows unknown rule ids to pass through;
        this is intended only for authoring / preview tools.
        """
        if strict and known_rule_ids is None:
            raise ProfileResolutionError(
                "resolve(strict=True) requires `known_rule_ids` - the caller "
                "MUST pass the rule-catalog rule ids so an unknown reference "
                "surfaces at load rather than as a silent runtime abstain. "
                "Pass `strict=False` for authoring / preview tools that "
                "intentionally accept unknown rule ids."
            )
        if profile_id not in self._by_id:
            raise ProfileResolutionError(f"unknown profile id {profile_id!r}")

        ordered = _topological_order(self._by_id, profile_id)
        merged_rules: dict[str, ResolvedRule] = {}
        merged_profile_params: dict[str, object] = {}
        title: str = ""

        floors = dict(rule_severity_floors or {})
        known = set(known_rule_ids or ())

        for pid in ordered:
            profile = self._by_id[pid]
            merged_profile_params.update(profile.parameters)
            title = profile.title  # last one wins (the leaf profile's title)
            for authored in profile.rules:
                if known and authored.id not in known:
                    raise ProfileResolutionError(
                        f"profile {pid!r} references unknown rule id {authored.id!r}"
                    )
                if authored.disabled:
                    merged_rules.pop(authored.id, None)
                    continue

                existing = merged_rules.get(authored.id)
                mode = _pick_mode(existing, authored)
                severity = _pick_severity(existing, authored)
                params = _merge_params(
                    profile_defaults=merged_profile_params,
                    inherited=existing.parameters if existing else {},
                    authored=authored.parameters,
                )

                # Severity floor check - only when the resolved value
                # is set AND a floor exists.
                if severity is not None:
                    floor = floors.get(authored.id)
                    if floor is not None and not severity_at_or_above_floor(severity, floor):
                        raise ProfileResolutionError(
                            f"profile {pid!r} rule {authored.id!r} severity_override "
                            f"{severity.value!r} downgrades below authored floor "
                            f"{floor.value!r}"
                        )

                merged_rules[authored.id] = ResolvedRule(
                    id=authored.id,
                    mode=mode,
                    severity_override=severity,
                    parameters=params,
                )

        ordered_rules = tuple(sorted(merged_rules.values(), key=lambda r: r.id))
        return ResolvedProfile(id=profile_id, title=title, rules=ordered_rules)

    # ------------------------------------------------------------------
    # Loader
    # ------------------------------------------------------------------

    @classmethod
    def from_directories(
        cls,
        *,
        upstream: Path | str,
        overlays: Iterable[Path | str] = (),
    ) -> ProfileRegistry:
        """Load ``upstream`` then overlay each entry in ``overlays``.

        Missing directories are treated as empty (upstream ships
        overlays empty by design). The loader validates each YAML
        against the schema before construction so malformed files
        fail-fast at import.

        Scan scope: each source directory is walked **recursively** by
        ``rglob("*.yaml")``, which is the documented contract - the
        upstream ships ``rule-catalog/profiles/`` with a top-level
        curated set plus a ``collected/`` subtree for machine-imported
        compliance profiles, and both trees MUST land in one registry.
        Overlay authors that want to keep a private, non-loaded
        directory alongside their profiles should place it under a
        sibling path (e.g. ``profiles-overrides.drafts/``) rather
        than under the loaded directory. Files with a leading ``.``
        (Unix "hidden") are skipped so editor autosaves and
        ``.git/**`` remnants do not accidentally join the load.
        """
        validator = _schema_validator()
        merged: dict[str, Profile] = {}
        overlay_replacements: list[tuple[str, str, str]] = []
        upstream_ids: set[str] = set()
        for i, source in enumerate((upstream, *overlays)):
            is_overlay = i > 0
            base = Path(source)
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*.yaml")):
                # Skip hidden files / directories (e.g. `.git`, `.DS_Store`,
                # editor swap files) - they are never part of a shipped
                # profile.
                if any(part.startswith(".") for part in path.parts):
                    continue
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
                if raw is None:
                    continue
                errors = sorted(validator.iter_errors(raw), key=lambda e: list(e.path))
                if errors:
                    first = errors[0]
                    where = ".".join(str(p) for p in first.absolute_path) or "<root>"
                    raise ProfileResolutionError(f"{path}: {where}: {first.message}")
                profile = _profile_from_dict(raw)
                if is_overlay and profile.id in upstream_ids:
                    overlay_replacements.append((profile.id, str(path), profile.title))
                merged[profile.id] = profile  # overlay wins on same id
                if not is_overlay:
                    upstream_ids.add(profile.id)
        registry = cls(profiles=merged.values())
        registry._overlay_replacements = tuple(overlay_replacements)
        return registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _schema_validator() -> Draft202012Validator:
    return Draft202012Validator(dict(PackageResourceSchemaRegistry().get("profile")))


def _profile_from_dict(data: Mapping[str, Any]) -> Profile:
    rules = tuple(
        ProfileRule(
            id=r["id"],
            mode=ProfileMode(r["mode"]) if r.get("mode") else None,
            severity_override=(
                SeverityOverride(r["severity_override"]) if r.get("severity_override") else None
            ),
            parameters=dict(r.get("parameters") or {}),
            disabled=bool(r.get("disabled", False)),
        )
        for r in data["rules"]
    )
    return Profile(
        id=data["id"],
        title=data["title"],
        rules=rules,
        extends=tuple(data.get("extends") or ()),
        parameters=dict(data.get("parameters") or {}),
        description=data.get("description"),
        schema_version=data["schema_version"],
    )


def _topological_order(profiles: Mapping[str, Profile], root: str) -> tuple[str, ...]:
    """Return the extend chain ending at ``root`` in dependency order."""
    order: list[str] = []
    visited: set[str] = set()
    stack: set[str] = set()

    def walk(pid: str) -> None:
        if pid in visited:
            return
        if pid in stack:
            raise ProfileResolutionError(f"cycle in profile extends: {' -> '.join([*stack, pid])}")
        profile = profiles.get(pid)
        if profile is None:
            raise ProfileResolutionError(f"profile references unknown parent {pid!r}")
        stack.add(pid)
        for parent in profile.extends:
            walk(parent)
        stack.discard(pid)
        visited.add(pid)
        order.append(pid)

    walk(root)
    return tuple(order)


def _pick_mode(existing: ResolvedRule | None, authored: ProfileRule) -> ProfileMode:
    if authored.mode is not None:
        return authored.mode
    if existing is not None:
        return existing.mode
    return ProfileMode.SHADOW  # safe default per architecture instructions


def _pick_severity(existing: ResolvedRule | None, authored: ProfileRule) -> SeverityOverride | None:
    if authored.severity_override is not None:
        return authored.severity_override
    if existing is not None:
        return existing.severity_override
    return None


def _merge_params(
    *,
    profile_defaults: Mapping[str, object],
    inherited: Mapping[str, object],
    authored: Mapping[str, object],
) -> Mapping[str, object]:
    merged: dict[str, object] = {}
    merged.update(profile_defaults)
    merged.update(inherited)
    merged.update(authored)
    return merged


__all__ = ["ProfileRegistry"]
