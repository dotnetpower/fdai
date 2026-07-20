"""Runtime governed skill bundle disclosure tests."""

from __future__ import annotations

import pytest

from fdai.core.skills import RuntimeSkill, RuntimeSkillDisclosure, SkillCatalog, skill_body_digest
from fdai.core.skills.bundle_catalog import SkillBundleCatalog, SkillBundleResolutionError
from fdai.core.skills.bundle_manifest import RuntimeSkillBundle, encode_skill_bundle_manifest


class _SkillVerifier:
    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        return True


class _BundleVerifier:
    def __init__(self, *, trusted: bool = True) -> None:
        self.trusted = trusted

    def verify(self, bundle: RuntimeSkillBundle, raw_manifest: bytes) -> bool:
        return self.trusted and bundle.raw_manifest == raw_manifest


def _runtime() -> tuple[RuntimeSkillDisclosure, SkillBundleCatalog]:
    skill_verifier = _SkillVerifier()
    skills = SkillCatalog()
    for name, version, tool, body in (
        ("inventory-evidence", "1.0.0", "query_inventory", "PRIVATE-INVENTORY-BODY"),
        ("log-evidence", "2.0.0", "query_log", "PRIVATE-LOG-BODY"),
    ):
        raw = f"""---
name: {name}
version: {version}
description: Evidence for {name}.
source: publisher.example
body_sha256: "{skill_body_digest(body)}"
required_tools: [{tool}]
allowed_agents: [Bragi]
---
{body}
""".encode()
        skills = skills.install(raw, verifier=skill_verifier).enable(
            name,
            available_tools=frozenset({tool}),
            known_agents=frozenset({"Bragi"}),
        )
    bundle_verifier = _BundleVerifier()
    raw_bundle = encode_skill_bundle_manifest(
        {
            "name": "incident-evidence-pack",
            "version": "1.0.0",
            "description": "Reviewed incident evidence procedures.",
            "source": "publisher.example",
            "members": [
                {"name": "inventory-evidence", "version": "==1.0.0"},
                {"name": "log-evidence", "version": "==2.0.0"},
            ],
            "allowed_agents": ["Bragi"],
            "required_tools": ["query_inventory", "query_log"],
            "instruction": "PRIVATE-BUNDLE-INSTRUCTION",
        }
    )
    bundles = (
        SkillBundleCatalog()
        .install(raw_bundle, verifier=bundle_verifier)
        .enable(
            "incident-evidence-pack",
            skills=skills,
            bundle_verifier=bundle_verifier,
            skill_verifier=skill_verifier,
            available_tools=frozenset({"query_inventory", "query_log"}),
            known_agents=frozenset({"Bragi"}),
        )
    )
    return (
        RuntimeSkillDisclosure(
            catalog=skills,
            verifier=skill_verifier,
            agent="Bragi",
            available_tools=frozenset({"query_inventory", "query_log"}),
            bundle_catalog=bundles,
            bundle_verifier=bundle_verifier,
            known_agents=frozenset({"Bragi"}),
        ),
        bundles,
    )


def test_bundle_inspection_is_metadata_only_and_load_is_complete() -> None:
    runtime, _bundles = _runtime()

    inspection = runtime.inspect()
    listed = runtime.list_bundles(query="incident", limit=10)
    described = runtime.describe_bundle("incident-evidence-pack")
    loaded = runtime.load_bundle("incident-evidence-pack")

    assert inspection["installed_bundle_count"] == 1
    assert inspection["eligible_bundle_count"] == 1
    assert inspection["bundles"][0]["trust_status"] == "rechecked_on_load"
    assert listed["returned_count"] == 1
    assert described["bundle"]["compatible"] is True
    assert loaded["instruction"] == "PRIVATE-BUNDLE-INSTRUCTION"
    assert [member["body"] for member in loaded["members"]] == [
        "PRIVATE-INVENTORY-BODY\n",
        "PRIVATE-LOG-BODY\n",
    ]
    assert "PRIVATE" not in repr(inspection)
    assert "PRIVATE" not in repr(listed)
    assert "PRIVATE" not in repr(described)


def test_bundle_load_rejection_diagnostic_contains_no_private_content() -> None:
    runtime, bundles = _runtime()
    runtime.publish_bundle_snapshot(
        catalog=bundles.disable("incident-evidence-pack"),
        verifier=_BundleVerifier(),
    )

    with pytest.raises(SkillBundleResolutionError):
        runtime.load_bundle("incident-evidence-pack")

    diagnostic = runtime.diagnostics()[-1]
    assert diagnostic["reason"] == "skill_bundle_disabled"
    assert "PRIVATE" not in repr(diagnostic)
