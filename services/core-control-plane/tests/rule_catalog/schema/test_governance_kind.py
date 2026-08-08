"""Governance-artifact kind discriminator."""

from __future__ import annotations

from fdai.rule_catalog.schema.governance_kind import GovernanceKind


def test_kind_values() -> None:
    assert GovernanceKind.RULE_SET == "rule-set"
    assert GovernanceKind.ASSIGNMENT == "assignment"
    assert GovernanceKind.EXEMPTION == "exemption"
    assert GovernanceKind.OVERRIDE == "override"


def test_kind_round_trip() -> None:
    assert GovernanceKind("assignment") is GovernanceKind.ASSIGNMENT
    assert {k.value for k in GovernanceKind} == {
        "rule-set",
        "assignment",
        "exemption",
        "override",
    }
