"""Governed skill bundle prompt disclosure and replay tests."""

from __future__ import annotations

from fdai.core.prompts.skill_disclosure import compose_skill_disclosure
from fdai.core.prompts.types import (
    PromptLayer,
    PromptReplayManifest,
    SkillDisclosureRequest,
    SkillSelectionStatus,
)
from fdai.core.quality_gate._audit import _prompt_replay_manifest_fields
from fdai.core.skills.bundle_catalog import SkillBundleCatalog
from fdai.core.skills.bundle_manifest import (
    RuntimeSkillBundle,
    encode_skill_bundle_manifest,
)
from fdai.core.skills.catalog import RuntimeSkill, SkillCatalog, skill_body_digest


class _SkillVerifier:
    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        return True


class _BundleVerifier:
    def verify(self, bundle: RuntimeSkillBundle, raw_manifest: bytes) -> bool:
        return bundle.raw_manifest == raw_manifest


def _skills(*, inventory_version: str = "1.0.0") -> SkillCatalog:
    catalog = SkillCatalog()
    verifier = _SkillVerifier()
    for name, version, tool, body in (
        (
            "inventory-evidence",
            inventory_version,
            "query_inventory",
            "COMPLETE-INVENTORY-BODY",
        ),
        ("log-evidence", "2.0.0", "query_log", "COMPLETE-LOG-BODY"),
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
        catalog = catalog.install(raw, verifier=verifier).enable(
            name,
            available_tools=frozenset({tool}),
            known_agents=frozenset({"Bragi"}),
        )
    return catalog


def _bundles(skills: SkillCatalog) -> SkillBundleCatalog:
    raw = encode_skill_bundle_manifest(
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
            "instruction": "BUNDLE-INSTRUCTION",
        }
    )
    installed = SkillBundleCatalog().install(raw, verifier=_BundleVerifier())
    return installed.enable(
        "incident-evidence-pack",
        skills=skills,
        bundle_verifier=_BundleVerifier(),
        skill_verifier=_SkillVerifier(),
        available_tools=frozenset({"query_inventory", "query_log"}),
        known_agents=frozenset({"Bragi"}),
    )


def _request() -> SkillDisclosureRequest:
    return SkillDisclosureRequest(
        agent="Bragi",
        available_tools=frozenset({"query_inventory", "query_log"}),
        query="incident evidence",
        selected_bundle_names=("incident-evidence-pack",),
    )


def test_bundle_projects_complete_ordered_members_and_replay_digests() -> None:
    skills = _skills()
    bundles = _bundles(skills)

    projection = compose_skill_disclosure(
        catalog=skills,
        verifier=_SkillVerifier(),
        request=_request(),
        bundle_catalog=bundles,
        bundle_verifier=_BundleVerifier(),
    )

    bundle_layer = next(
        layer for layer in projection.layers if layer.layer is PromptLayer.SKILL_BUNDLE
    )
    assert (
        bundle_layer.body.index("BUNDLE-INSTRUCTION")
        < bundle_layer.body.index("COMPLETE-INVENTORY-BODY")
        < bundle_layer.body.index("COMPLETE-LOG-BODY")
    )
    record = projection.bundle_records[0]
    assert record.status is SkillSelectionStatus.SELECTED
    assert record.version == "1.0.0"
    assert record.digest is not None
    assert record.manifest_sha256 is not None
    assert [(member.name, member.version) for member in record.members] == [
        ("inventory-evidence", "1.0.0"),
        ("log-evidence", "2.0.0"),
    ]


def test_member_update_rejects_bundle_without_any_private_content() -> None:
    original_skills = _skills()
    bundles = _bundles(original_skills)

    projection = compose_skill_disclosure(
        catalog=_skills(inventory_version="1.1.0"),
        verifier=_SkillVerifier(),
        request=_request(),
        bundle_catalog=bundles,
        bundle_verifier=_BundleVerifier(),
    )

    assert not any(layer.layer is PromptLayer.SKILL_BUNDLE for layer in projection.layers)
    record = projection.bundle_records[0]
    assert record.status is SkillSelectionStatus.REJECTED
    assert record.rejection_reason == "skill_bundle_member_version_incompatible"
    assert record.version == "1.0.0"
    assert record.digest is not None
    assert "COMPLETE-INVENTORY-BODY" not in repr(projection)
    assert "COMPLETE-LOG-BODY" not in repr(projection)


def test_bundle_replay_is_deterministic_and_serialized_into_audit() -> None:
    skills = _skills()
    bundles = _bundles(skills)
    first = compose_skill_disclosure(
        catalog=skills,
        verifier=_SkillVerifier(),
        request=_request(),
        bundle_catalog=bundles,
        bundle_verifier=_BundleVerifier(),
    )
    second = compose_skill_disclosure(
        catalog=skills,
        verifier=_SkillVerifier(),
        request=_request(),
        bundle_catalog=bundles,
        bundle_verifier=_BundleVerifier(),
    )
    assert first == second

    fields = _prompt_replay_manifest_fields(
        PromptReplayManifest(
            system_text_sha256="0" * 64,
            layer_manifest=(),
            token_estimate=0,
            skill_bundle_records=first.bundle_records,
        )
    )
    bundle = fields["skill_bundle_records"][0]
    assert bundle["name"] == "incident-evidence-pack"
    assert [member["name"] for member in bundle["members"]] == [
        "inventory-evidence",
        "log-evidence",
    ]


def test_bundle_selection_is_explicit_bounded_and_never_auto_selected() -> None:
    skills = _skills()
    bundles = _bundles(skills)
    no_selection = compose_skill_disclosure(
        catalog=skills,
        verifier=_SkillVerifier(),
        request=SkillDisclosureRequest(
            agent="Bragi",
            available_tools=frozenset({"query_inventory", "query_log"}),
            query="incident evidence",
        ),
        bundle_catalog=bundles,
        bundle_verifier=_BundleVerifier(),
    )
    assert no_selection.bundle_records == ()
    assert not any(layer.layer is PromptLayer.SKILL_BUNDLE for layer in no_selection.layers)
