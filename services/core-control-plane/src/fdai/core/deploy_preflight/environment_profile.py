"""Deployment Environment Profile cache - Wave P.4.

Records "which guardrails apply to a scope" so a deploy can read the
cache instead of re-probing every time. Refreshed via the Inventory
delta stream: when an ``Inventory.delta()`` batch touches a scope the
cache holds a profile for, the profile is invalidated and re-built.

Design invariants
-----------------

- **Read-only cache**: consumers observe profiles; the update path is
  a single :meth:`DeploymentEnvironmentProfileCache.upsert` call the
  refresh task owns.
- **Bounded staleness**: every profile carries a
  ``captured_at``; a caller MAY apply a TTL via
  :meth:`DeploymentEnvironmentProfileCache.get_fresh`. A stale entry
  is not returned - the caller falls back to a re-probe.
- **Deterministic**: two profiles built from the same inputs compare
  equal. Sequence-order-independent by construction (uses
  :class:`frozenset` internally for the rule id set) but the surface
  types expose sorted tuples so callers see a stable order.
- **CSP-neutral, no I/O**: only :mod:`shared.contracts.models` shapes
  and stdlib types. The refresh path calls
  :class:`~fdai.shared.providers.inventory.Inventory` in the
  composition root, never in ``core/``.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class DeploymentEnvironmentProfile:
    """One cached profile: which guardrails apply to a given scope.

    ``scope`` is an opaque, CSP-neutral scope handle (subscription id,
    resource-group name, aggregate label); ``rule_ids`` is a sorted
    tuple so serialization is stable across re-builds.
    """

    scope: str
    rule_ids: tuple[str, ...]
    resource_type_counts: Mapping[str, int]
    captured_at: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.scope:
            raise ValueError("scope MUST be non-empty")
        if not self.captured_at:
            raise ValueError("captured_at MUST be non-empty")
        # rule_ids MUST be sorted so equality is order-independent.
        if list(self.rule_ids) != sorted(self.rule_ids):
            raise ValueError("rule_ids MUST be sorted (use build_profile())")
        if any(v < 0 for v in self.resource_type_counts.values()):
            raise ValueError("resource_type_counts MUST be non-negative")

    def with_rule_ids(
        self, rule_ids: Iterable[str], *, captured_at: str
    ) -> DeploymentEnvironmentProfile:
        """Return a new profile with a fresh rule-id set + timestamp.

        Used by the refresh path when an Inventory delta changes which
        rules apply; the resource-type-count block is untouched.
        """

        return DeploymentEnvironmentProfile(
            scope=self.scope,
            rule_ids=tuple(sorted(set(rule_ids))),
            resource_type_counts=dict(self.resource_type_counts),
            captured_at=captured_at,
            metadata=dict(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly serialization for the read-only console."""

        return {
            "scope": self.scope,
            "rule_ids": list(self.rule_ids),
            "resource_type_counts": dict(self.resource_type_counts),
            "captured_at": self.captured_at,
            "metadata": dict(self.metadata),
        }


def build_profile(
    *,
    scope: str,
    rule_ids: Iterable[str],
    resource_type_counts: Mapping[str, int],
    captured_at: str,
    metadata: Mapping[str, str] | None = None,
) -> DeploymentEnvironmentProfile:
    """Assemble a profile with the rule-id tuple sorted / deduplicated.

    The sole entry point that produces well-formed profiles; direct
    construction of :class:`DeploymentEnvironmentProfile` is allowed
    but the caller MUST sort ``rule_ids`` beforehand.
    """

    return DeploymentEnvironmentProfile(
        scope=scope,
        rule_ids=tuple(sorted(set(rule_ids))),
        resource_type_counts=dict(resource_type_counts),
        captured_at=captured_at,
        metadata=dict(metadata or {}),
    )


class DeploymentEnvironmentProfileCache:
    """Thread-safe in-memory cache keyed by scope.

    Fits the composition-root need: a refresh task consumes an
    :class:`~fdai.shared.providers.inventory.Inventory` delta
    stream and calls :meth:`upsert` / :meth:`invalidate`; the Preflight
    analyzer reads via :meth:`get_fresh` and falls back to re-probing
    when the entry is stale or missing.
    """

    def __init__(self) -> None:
        self._by_scope: dict[str, DeploymentEnvironmentProfile] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def upsert(self, profile: DeploymentEnvironmentProfile) -> None:
        """Insert or replace the profile for ``profile.scope``."""

        with self._lock:
            self._by_scope[profile.scope] = profile

    def invalidate(self, scope: str) -> bool:
        """Drop the cached entry for ``scope`` if present.

        Returns ``True`` if an entry was removed, ``False`` when there
        was nothing to drop. Used by the refresh task when an Inventory
        delta invalidates a scope but a fresh profile is not yet built.
        """

        with self._lock:
            return self._by_scope.pop(scope, None) is not None

    def clear(self) -> None:
        """Drop every cached entry (test helper / admin operation)."""

        with self._lock:
            self._by_scope.clear()

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def get(self, scope: str) -> DeploymentEnvironmentProfile | None:
        """Return the cached profile for ``scope`` regardless of age."""

        with self._lock:
            return self._by_scope.get(scope)

    def get_fresh(
        self,
        scope: str,
        *,
        now: str,
        max_age_seconds: int,
    ) -> DeploymentEnvironmentProfile | None:
        """Return the cached profile only when younger than ``max_age_seconds``.

        Timestamps are ISO-8601 strings; the comparison is delegated to
        :func:`_iso_delta_seconds` to keep this module stdlib-only.
        Returns ``None`` when the entry is missing OR stale; the caller
        MUST fall back to re-probing.
        """

        if max_age_seconds < 0:
            raise ValueError("max_age_seconds MUST be non-negative")
        entry = self.get(scope)
        if entry is None:
            return None
        try:
            age = _iso_delta_seconds(entry.captured_at, now)
        except (ValueError, TypeError):
            # Fail closed: an unparseable timestamp (ValueError) OR a mixed
            # naive/aware pair (TypeError from subtracting offset-naive and
            # offset-aware datetimes - both shapes are within the documented
            # ISO domain) is treated as stale, so the caller re-probes
            # rather than trusting a freshness check that could not be made.
            return None
        if age > max_age_seconds:
            return None
        return entry

    def scopes(self) -> tuple[str, ...]:
        """Every cached scope, sorted."""

        with self._lock:
            return tuple(sorted(self._by_scope))

    def __len__(self) -> int:
        with self._lock:
            return len(self._by_scope)


def apply_inventory_delta(
    cache: DeploymentEnvironmentProfileCache,
    *,
    changed_scopes: Iterable[str],
) -> int:
    """Invalidate every profile whose scope appears in ``changed_scopes``.

    Convenience helper the refresh task calls after
    :meth:`~fdai.shared.providers.inventory.Inventory.delta`
    returns; returns the number of entries actually dropped so the
    caller can log the refresh footprint.
    """

    dropped = 0
    for scope in changed_scopes:
        if cache.invalidate(scope):
            dropped += 1
    return dropped


# ---------------------------------------------------------------------------
# ISO-8601 helper (stdlib only)
# ---------------------------------------------------------------------------


def _iso_delta_seconds(older: str, newer: str) -> float:
    """Return ``newer - older`` in seconds.

    Accepts ``YYYY-MM-DDTHH:MM:SS[.ffffff][Z|+HH:MM]``; raises
    :class:`ValueError` on any parse failure so the caller can treat
    the entry as stale (fail-closed).
    """

    from datetime import datetime

    def _parse(s: str) -> datetime:
        # ``datetime.fromisoformat`` handles the offset shape
        # ``+00:00`` but not the trailing ``Z``; normalize it.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)

    return (_parse(newer) - _parse(older)).total_seconds()


__all__ = [
    "DeploymentEnvironmentProfile",
    "DeploymentEnvironmentProfileCache",
    "apply_inventory_delta",
    "build_profile",
]
