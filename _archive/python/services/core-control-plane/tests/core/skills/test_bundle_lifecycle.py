"""Audited governed skill bundle lifecycle tests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.core.skills import RuntimeSkill, SkillCatalog, skill_body_digest
from fdai.core.skills.bundle_catalog import SkillBundleCatalog
from fdai.core.skills.bundle_lifecycle import SkillBundleLifecycle
from fdai.core.skills.bundle_manifest import RuntimeSkillBundle, encode_skill_bundle_manifest

_NOW = datetime(2026, 7, 20, 13, 0, tzinfo=UTC)


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def append(self, event: Mapping[str, Any]) -> None:
        self.events.append(dict(event))


class _SkillVerifier:
    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        return True


class _BundleVerifier:
    def verify(self, bundle: RuntimeSkillBundle, raw_manifest: bytes) -> bool:
        return bundle.raw_manifest == raw_manifest


def _skills() -> SkillCatalog:
    body = "PRIVATE-SKILL-BODY"
    raw = f"""---
name: inventory-evidence
version: 1.0.0
description: Inventory evidence.
source: publisher.example
body_sha256: "{skill_body_digest(body)}"
required_tools: [query_inventory]
allowed_agents: [Bragi]
---
{body}
""".encode()
    return (
        SkillCatalog()
        .install(raw, verifier=_SkillVerifier())
        .enable(
            "inventory-evidence",
            available_tools=frozenset({"query_inventory"}),
            known_agents=frozenset({"Bragi"}),
        )
    )


def _bundle() -> bytes:
    return encode_skill_bundle_manifest(
        {
            "name": "inventory-pack",
            "version": "1.0.0",
            "description": "Reviewed inventory procedure.",
            "source": "publisher.example",
            "members": [{"name": "inventory-evidence", "version": "==1.0.0"}],
            "allowed_agents": ["Bragi"],
            "required_tools": ["query_inventory"],
            "instruction": "PRIVATE-BUNDLE-INSTRUCTION",
        }
    )


async def test_lifecycle_is_audited_content_free_and_disable_is_reversible() -> None:
    audit = _Audit()
    lifecycle = SkillBundleLifecycle(audit)
    skills = _skills()
    installed = await lifecycle.install(
        SkillBundleCatalog(),
        _bundle(),
        verifier=_BundleVerifier(),
        actor="owner-1",
        reason="Reviewed signature.",
        at=_NOW,
    )
    enabled = await lifecycle.enable(
        installed,
        "inventory-pack",
        skills=skills,
        bundle_verifier=_BundleVerifier(),
        skill_verifier=_SkillVerifier(),
        available_tools=frozenset({"query_inventory"}),
        known_agents=frozenset({"Bragi"}),
        actor="owner-1",
        reason="Enable reviewed procedure.",
        at=_NOW,
    )
    disabled = await lifecycle.disable(
        enabled,
        "inventory-pack",
        actor="owner-1",
        reason="Rollback bundle activation.",
        at=_NOW,
    )
    restored = await lifecycle.enable(
        disabled,
        "inventory-pack",
        skills=skills,
        bundle_verifier=_BundleVerifier(),
        skill_verifier=_SkillVerifier(),
        available_tools=frozenset({"query_inventory"}),
        known_agents=frozenset({"Bragi"}),
        actor="owner-1",
        reason="Restore reviewed activation.",
        at=_NOW,
    )

    assert restored.get("inventory-pack").enabled is True
    assert [event["action_kind"] for event in audit.events] == [
        "skill_bundle.installed",
        "skill_bundle.enabled",
        "skill_bundle.disabled",
        "skill_bundle.enabled",
    ]
    assert audit.events[-1]["previous_enabled"] is False
    assert all("PRIVATE" not in repr(event) for event in audit.events)


async def test_disable_then_uninstall_retains_identity_evidence() -> None:
    audit = _Audit()
    lifecycle = SkillBundleLifecycle(audit)
    installed = await lifecycle.install(
        SkillBundleCatalog(),
        _bundle(),
        verifier=_BundleVerifier(),
        actor="owner-1",
        reason="Reviewed signature.",
        at=_NOW,
    )
    uninstalled = await lifecycle.uninstall(
        installed,
        "inventory-pack",
        actor="owner-1",
        reason="Retire unused bundle.",
        at=_NOW,
    )

    assert uninstalled.list() == ()
    assert audit.events[-1]["bundle_version"] == "1.0.0"
    assert audit.events[-1]["bundle_digest"]
