"""Runtime skill digest, trust, gating, and prompt projection tests."""

from __future__ import annotations

import pytest

from fdai.core.skills import (
    RuntimeSkill,
    SkillCatalog,
    SkillCatalogError,
    skill_body_digest,
)


class _Verifier:
    def __init__(self, trusted: bool = True) -> None:
        self.trusted = trusted

    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        return self.trusted


def _skill(*, digest: str | None = None, agents: str = "[Bragi]") -> bytes:
    body = "Use query_inventory for evidence. Never invoke an executor directly."
    body_hash = digest or skill_body_digest(body)
    return f"""---
name: inventory-evidence
version: 1.0.0
description: Collect bounded inventory evidence.
source: source:inventory-evidence
body_sha256: "{body_hash}"
required_tools: [query_inventory]
allowed_agents: {agents}
---
{body}
""".encode()


def test_verified_skill_installs_disabled_and_enables_with_known_refs() -> None:
    installed = SkillCatalog().install(_skill(), verifier=_Verifier())

    assert installed.get("inventory-evidence").enabled is False
    assert installed.get("inventory-evidence").raw_markdown == _skill()
    assert installed.get("inventory-evidence").references == ()
    enabled = installed.enable(
        "inventory-evidence",
        available_tools=frozenset({"query_inventory"}),
        known_agents=frozenset({"Bragi"}),
    )

    prompt = enabled.prompt_for(
        agent="Bragi",
        available_tools=frozenset({"query_inventory"}),
        max_chars=2_000,
    )
    assert 'trusted="true"' in prompt
    assert "Never invoke an executor directly." in prompt


def test_digest_or_trust_failure_does_not_install() -> None:
    with pytest.raises(SkillCatalogError, match="digest"):
        SkillCatalog().install(_skill(digest="0" * 64), verifier=_Verifier())
    with pytest.raises(SkillCatalogError, match="trust"):
        SkillCatalog().install(_skill(), verifier=_Verifier(False))


def test_enable_rejects_missing_tool_or_unknown_agent() -> None:
    catalog = SkillCatalog().install(_skill(), verifier=_Verifier())

    with pytest.raises(SkillCatalogError, match="unavailable tools"):
        catalog.enable(
            "inventory-evidence",
            available_tools=frozenset(),
            known_agents=frozenset({"Bragi"}),
        )
    with pytest.raises(SkillCatalogError, match="unknown agents"):
        catalog.enable(
            "inventory-evidence",
            available_tools=frozenset({"query_inventory"}),
            known_agents=frozenset({"Saga"}),
        )


def test_agent_allowlist_hides_skill_from_other_agents() -> None:
    enabled = (
        SkillCatalog()
        .install(_skill(), verifier=_Verifier())
        .enable(
            "inventory-evidence",
            available_tools=frozenset({"query_inventory"}),
            known_agents=frozenset({"Bragi"}),
        )
    )

    assert (
        enabled.prompt_for(
            agent="Saga",
            available_tools=frozenset({"query_inventory"}),
            max_chars=2_000,
        )
        == ""
    )


def test_prompt_budget_fails_without_partial_skill_instructions() -> None:
    enabled = (
        SkillCatalog()
        .install(_skill(), verifier=_Verifier())
        .enable(
            "inventory-evidence",
            available_tools=frozenset({"query_inventory"}),
            known_agents=frozenset({"Bragi"}),
        )
    )

    with pytest.raises(SkillCatalogError, match="budget"):
        enabled.prompt_for(
            agent="Bragi",
            available_tools=frozenset({"query_inventory"}),
            max_chars=10,
        )


def test_enabled_skill_fails_if_required_tool_disappears() -> None:
    enabled = (
        SkillCatalog()
        .install(_skill(), verifier=_Verifier())
        .enable(
            "inventory-evidence",
            available_tools=frozenset({"query_inventory"}),
            known_agents=frozenset({"Bragi"}),
        )
    )

    with pytest.raises(SkillCatalogError, match="lost required tools"):
        enabled.prompt_for(agent="Bragi", available_tools=frozenset(), max_chars=2_000)


def test_unknown_front_matter_key_is_rejected() -> None:
    raw = _skill().replace(b"version: 1.0.0\n", b"version: 1.0.0\ninstall: npm\n")
    with pytest.raises(SkillCatalogError, match="unknown keys"):
        SkillCatalog().install(raw, verifier=_Verifier())
