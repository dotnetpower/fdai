"""Governance-artifact kind discriminator.

Every governance catalog-as-code artifact declares a ``kind`` so a file is
self-describing and a single dispatch point can route it (rule-governance.md
"YAML Shapes": ``kind: rule-set | assignment | exemption | override``). Adding a
new artifact kind is additive - one enum member plus its per-kind schema - which
is why the discriminator is part of the extensible governance-artifact envelope
rather than inferred only from the on-disk directory.

Pure and I/O-free.
"""

from __future__ import annotations

from enum import StrEnum


class GovernanceKind(StrEnum):
    """The kind of a governance catalog-as-code artifact."""

    RULE_SET = "rule-set"
    ASSIGNMENT = "assignment"
    EXEMPTION = "exemption"
    OVERRIDE = "override"


__all__ = ["GovernanceKind"]
