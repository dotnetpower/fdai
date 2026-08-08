"""Runtime skill snapshot and inspection tests."""

from __future__ import annotations

from fdai.core.skills import RuntimeSkill, RuntimeSkillDisclosure, SkillCatalog, skill_body_digest


class _Verifier:
    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        return True


def _catalog(name: str, *, enabled: bool) -> SkillCatalog:
    body = f"private body for {name}"
    raw = f"""---
name: {name}
version: 1.0.0
description: Metadata for {name}.
source: publisher.example
body_sha256: "{skill_body_digest(body)}"
required_tools: [query_inventory]
allowed_agents: [Bragi]
---
{body}
""".encode()
    catalog = SkillCatalog().install(raw, verifier=_Verifier())
    if enabled:
        catalog = catalog.enable(
            name,
            available_tools=frozenset({"query_inventory"}),
            known_agents=frozenset({"Bragi"}),
        )
    return catalog


def test_startup_snapshot_publish_is_atomic_and_inspection_is_metadata_only() -> None:
    disclosure = RuntimeSkillDisclosure(
        catalog=_catalog("old-skill", enabled=False),
        verifier=_Verifier(),
        agent="Bragi",
        available_tools=frozenset({"query_inventory"}),
    )

    before = disclosure.inspect()
    disclosure.publish_snapshot(
        catalog=_catalog("new-skill", enabled=True),
        verifier=_Verifier(),
    )
    after = disclosure.inspect()

    assert [item["name"] for item in before["skills"]] == ["old-skill"]
    assert [item["name"] for item in after["skills"]] == ["new-skill"]
    assert after["eligible_count"] == 1
    assert after["skills"][0]["eligibility_reason"] == "eligible_pending_trust_recheck"
    assert after["mutation_controls"] is False
    assert "private body" not in repr(before)
    assert "private body" not in repr(after)


def test_rejection_diagnostics_remain_content_free_after_snapshot_publish() -> None:
    disclosure = RuntimeSkillDisclosure(
        catalog=SkillCatalog(),
        verifier=_Verifier(),
        agent="Bragi",
        available_tools=frozenset({"query_inventory"}),
    )
    disclosure.publish_snapshot(
        catalog=_catalog("disabled-skill", enabled=False),
        verifier=_Verifier(),
    )

    try:
        disclosure.load("disabled-skill")
    except ValueError:
        pass

    inspection = disclosure.inspect()
    assert inspection["diagnostics"][-1]["reason"] == "skill_disabled"
    assert "private body for disabled-skill" not in repr(inspection)
