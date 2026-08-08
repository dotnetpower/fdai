"""Profile / Pack layer - named rule bundles with extend chains + overrides.

Design contract: ``docs/roadmap/rules-and-detection/rule-catalog-profiles.md``.

Public surface:

- :class:`Profile` / :class:`ProfileRule` - typed view over
  ``shared/contracts/profile/schema.json``.
- :class:`ProfileRegistry` - loads YAML profiles from a directory tree
  (upstream: ``rule-catalog/profiles/``; fork overlay:
  ``rule-catalog/profiles-overrides/``).
- :meth:`ProfileRegistry.resolve` - deterministic merge of the
  ``extends`` chain into a flat :class:`ResolvedProfile` (rule id ->
  resolved parameters + mode + severity).
- :class:`ProfileResolutionError` - raised on cycles, unknown parents,
  unknown rule ids, or severity downgrade attempts.

The registry is data-first: it never touches the runtime pipeline
directly. The composition root binds a resolved profile to
``ControlLoop`` / ``T0Engine`` / ``RiskGate`` at process start; a fork
swaps the profile at composition time, not at hot-path time.
"""

from __future__ import annotations

from .models import (
    Profile,
    ProfileResolutionError,
    ProfileRule,
    ResolvedProfile,
    ResolvedRule,
)
from .registry import ProfileRegistry

__all__ = [
    "Profile",
    "ProfileRegistry",
    "ProfileResolutionError",
    "ProfileRule",
    "ResolvedProfile",
    "ResolvedRule",
]
