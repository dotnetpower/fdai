"""Vertical registry - the onboarding seam for a new operational domain.

FDAI ships three verticals (Resilience, Change Safety, Cost Governance),
but "replace an organization" means the set must grow - security posture,
compliance, patch management - **without editing `core/`**. This registry
is that seam: a fork describes a new domain as a
:class:`VerticalDescriptor` and registers it at the composition root; the
control loop enumerates the registry instead of hard-coding the three.

The registry is deterministic and validating, not a plugin loader: it
holds inert descriptors, rejects a misconfigured onboarding at
registration time (duplicate id; an enabled vertical with no rule source
- a domain that detects nothing), and defaults every new vertical to
**shadow mode** (`Mode.SHADOW`) so onboarding can never silently enable
autonomous action. Promotion to enforce stays a separate, reviewed change
per the shadow-first rule.

Design contract:
[scope-expansion.md](../../../../docs/roadmap/fork-and-sequencing/scope-expansion.md)
and the DI-seam model in
[project-structure.md](../../../../docs/roadmap/architecture/project-structure.md).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from fdai.shared.contracts.models import Category, Mode


class VerticalRegistrationError(ValueError):
    """Raised when a descriptor is rejected at registration time."""


@dataclass(frozen=True, slots=True)
class VerticalDescriptor:
    """One operational domain onboarded into the control loop.

    ``vertical_id`` is a stable, ASCII, kebab-case identifier used in
    config, audit, and metrics. ``rule_source_ids`` names the rule-catalog
    sources this vertical draws findings from; an **enabled** vertical
    MUST name at least one (a domain with no source detects nothing).
    ``default_mode`` is ``Mode.SHADOW`` and MUST stay shadow at onboarding
    - promotion to enforce is a separate reviewed change.
    """

    vertical_id: str
    display_name: str
    category: Category
    rule_source_ids: tuple[str, ...] = ()
    enabled: bool = False
    default_mode: Mode = Mode.SHADOW


class VerticalRegistry:
    """Deterministic, validating registry of onboarded verticals."""

    def __init__(self) -> None:
        self._by_id: dict[str, VerticalDescriptor] = {}

    def register(self, descriptor: VerticalDescriptor) -> None:
        """Register ``descriptor``, rejecting a misconfigured onboarding.

        Raises :class:`VerticalRegistrationError` when the id is empty or
        non-ASCII, when it duplicates an existing vertical, when an enabled
        vertical names no rule source, or when a descriptor tries to
        onboard directly in enforce mode (which would skip the shadow-first
        gate).
        """
        vid = descriptor.vertical_id
        if not vid:
            raise VerticalRegistrationError("vertical_id MUST be non-empty")
        if not vid.isascii():
            raise VerticalRegistrationError(
                f"vertical_id '{vid}' MUST be ASCII (config / audit / metrics key)"
            )
        if vid in self._by_id:
            raise VerticalRegistrationError(
                f"vertical_id '{vid}' is already registered; ids MUST be unique"
            )
        if descriptor.default_mode is not Mode.SHADOW:
            raise VerticalRegistrationError(
                f"vertical '{vid}' MUST onboard in shadow mode; promotion to "
                "enforce is a separate reviewed change"
            )
        if descriptor.enabled and not descriptor.rule_source_ids:
            raise VerticalRegistrationError(
                f"enabled vertical '{vid}' MUST name at least one rule source "
                "(a domain with no source detects nothing)"
            )
        self._by_id[vid] = descriptor

    def register_all(self, descriptors: Iterable[VerticalDescriptor]) -> None:
        """Register each descriptor in order; the first failure aborts."""
        for descriptor in descriptors:
            self.register(descriptor)

    def get(self, vertical_id: str) -> VerticalDescriptor:
        """Return the descriptor for ``vertical_id`` or raise ``KeyError``."""
        return self._by_id[vertical_id]

    def has(self, vertical_id: str) -> bool:
        """True iff ``vertical_id`` is registered."""
        return vertical_id in self._by_id

    def all(self) -> Sequence[VerticalDescriptor]:
        """Return all descriptors in a stable, id-sorted order."""
        return [self._by_id[vid] for vid in sorted(self._by_id)]

    def enabled(self) -> Sequence[VerticalDescriptor]:
        """Return the enabled descriptors in a stable, id-sorted order."""
        return [d for d in self.all() if d.enabled]


__all__ = [
    "VerticalDescriptor",
    "VerticalRegistrationError",
    "VerticalRegistry",
]
