"""Governed skill bundle lifecycle and resolution tests."""

from __future__ import annotations

import pytest

from fdai.core.skills.bundle_catalog import (
    SkillBundleCatalog,
    SkillBundleRejectionReason,
    SkillBundleResolutionError,
)
from fdai.core.skills.bundle_manifest import (
    RuntimeSkillBundle,
    encode_skill_bundle_manifest,
)
from fdai.core.skills.catalog import RuntimeSkill, SkillCatalog, skill_body_digest


class _SkillVerifier:
    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        return True


class _BundleVerifier:
    def __init__(self, *, trusted: bool = True) -> None:
        self.trusted = trusted

    def verify(self, bundle: RuntimeSkillBundle, raw_manifest: bytes) -> bool:
        return self.trusted and bundle.raw_manifest == raw_manifest


def _skill_catalog(
    *,
    inventory_version: str = "1.0.0",
    enable_logs: bool = True,
) -> SkillCatalog:
    catalog = SkillCatalog()
    verifier = _SkillVerifier()
    for name, version, tool in (
        ("inventory-evidence", inventory_version, "query_inventory"),
        ("log-evidence", "2.0.0", "query_log"),
    ):
        body = f"Complete procedure for {name}."
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
        catalog = catalog.install(raw, verifier=verifier)
        if name != "log-evidence" or enable_logs:
            catalog = catalog.enable(
                name,
                available_tools=frozenset({tool}),
                known_agents=frozenset({"Bragi"}),
            )
    return catalog


def _bundle_document(
    *,
    name: str = "incident-evidence-pack",
    members: list[dict[str, str]] | None = None,
    required_tools: list[str] | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "version": "1.0.0",
        "description": "Reviewed incident evidence procedures.",
        "source": "publisher.example",
        "members": members
        or [
            {"name": "inventory-evidence", "version": "==1.0.0"},
            {"name": "log-evidence", "version": "==2.0.0"},
        ],
        "allowed_agents": ["Bragi"],
        "required_tools": required_tools or ["query_inventory", "query_log"],
        "instruction": "Use members in declared order.",
    }


def _installed_bundle_catalog(
    document: dict[str, object] | None = None,
) -> SkillBundleCatalog:
    return SkillBundleCatalog().install(
        encode_skill_bundle_manifest(document or _bundle_document()),
        verifier=_BundleVerifier(),
    )


def _enable(
    bundles: SkillBundleCatalog,
    skills: SkillCatalog,
    name: str = "incident-evidence-pack",
) -> SkillBundleCatalog:
    return bundles.enable(
        name,
        skills=skills,
        bundle_verifier=_BundleVerifier(),
        skill_verifier=_SkillVerifier(),
        available_tools=frozenset({"query_inventory", "query_log"}),
        known_agents=frozenset({"Bragi", "Saga"}),
    )


def test_disabled_first_enable_and_ordered_atomic_resolution() -> None:
    skills = _skill_catalog()
    installed = _installed_bundle_catalog()
    assert installed.get("incident-evidence-pack").enabled is False

    enabled = _enable(installed, skills)
    resolved = enabled.resolve(
        "incident-evidence-pack",
        skills=skills,
        bundle_verifier=_BundleVerifier(),
        skill_verifier=_SkillVerifier(),
        agent="Bragi",
        available_tools=frozenset({"query_inventory", "query_log"}),
        known_agents=frozenset({"Bragi", "Saga"}),
        max_chars=8_192,
    )

    assert [member.descriptor.name for member in resolved.members] == [
        "inventory-evidence",
        "log-evidence",
    ]
    assert resolved.effective_agents == ("Bragi",)
    assert resolved.required_tools == ("query_inventory", "query_log")
    assert [member.name for member in resolved.replay.members] == [
        "inventory-evidence",
        "log-evidence",
    ]


@pytest.mark.parametrize(
    ("skills", "reason"),
    [
        (_skill_catalog(enable_logs=False), SkillBundleRejectionReason.MEMBER_DISABLED),
        (
            _skill_catalog(inventory_version="1.1.0"),
            SkillBundleRejectionReason.VERSION_INCOMPATIBLE,
        ),
    ],
)
def test_enable_fails_closed_for_disabled_or_incompatible_member(
    skills: SkillCatalog,
    reason: SkillBundleRejectionReason,
) -> None:
    with pytest.raises(SkillBundleResolutionError) as caught:
        _enable(_installed_bundle_catalog(), skills)
    assert caught.value.reason is reason


def test_no_widening_requires_declared_member_tools_and_effective_agent() -> None:
    undeclared = _installed_bundle_catalog(_bundle_document(required_tools=["query_inventory"]))
    with pytest.raises(SkillBundleResolutionError) as dependency:
        _enable(undeclared, _skill_catalog())
    assert dependency.value.reason is SkillBundleRejectionReason.DEPENDENCY_UNDECLARED

    enabled = _enable(_installed_bundle_catalog(), _skill_catalog())
    with pytest.raises(SkillBundleResolutionError) as agent:
        enabled.resolve(
            "incident-evidence-pack",
            skills=_skill_catalog(),
            bundle_verifier=_BundleVerifier(),
            skill_verifier=_SkillVerifier(),
            agent="Saga",
            available_tools=frozenset({"query_inventory", "query_log"}),
            known_agents=frozenset({"Bragi", "Saga"}),
            max_chars=8_192,
        )
    assert agent.value.reason is SkillBundleRejectionReason.AGENT_NOT_ALLOWED


def test_cycle_nested_and_ambiguous_member_names_have_exact_reasons() -> None:
    cycle_a = _bundle_document(
        name="cycle-a",
        members=[{"name": "cycle-b", "version": "==1.0.0"}],
        required_tools=[],
    )
    cycle_b = _bundle_document(
        name="cycle-b",
        members=[{"name": "cycle-a", "version": "==1.0.0"}],
        required_tools=[],
    )
    bundles = _installed_bundle_catalog(cycle_a).install(
        encode_skill_bundle_manifest(cycle_b), verifier=_BundleVerifier()
    )
    with pytest.raises(SkillBundleResolutionError) as cycle:
        _enable(bundles, _skill_catalog(), "cycle-a")
    assert cycle.value.reason is SkillBundleRejectionReason.DEPENDENCY_CYCLE

    nested = _bundle_document(
        members=[{"name": "other-pack", "version": "==1.0.0"}],
        required_tools=[],
    )
    other = _bundle_document(name="other-pack")
    nested_catalog = _installed_bundle_catalog(nested).install(
        encode_skill_bundle_manifest(other), verifier=_BundleVerifier()
    )
    with pytest.raises(SkillBundleResolutionError) as nested_error:
        _enable(nested_catalog, _skill_catalog())
    assert nested_error.value.reason is SkillBundleRejectionReason.NESTED_UNSUPPORTED

    ambiguous = _installed_bundle_catalog(_bundle_document(name="inventory-evidence")).install(
        encode_skill_bundle_manifest(
            _bundle_document(
                members=[{"name": "inventory-evidence", "version": "==1.0.0"}],
                required_tools=["query_inventory"],
            )
        ),
        verifier=_BundleVerifier(),
    )
    with pytest.raises(SkillBundleResolutionError) as ambiguous_error:
        _enable(ambiguous, _skill_catalog())
    assert ambiguous_error.value.reason is SkillBundleRejectionReason.AMBIGUOUS_MEMBER


def test_member_update_invalidates_new_resolution_but_snapshot_survives_lifecycle() -> None:
    skills = _skill_catalog()
    enabled = _enable(_installed_bundle_catalog(), skills)
    snapshot = enabled.resolve(
        "incident-evidence-pack",
        skills=skills,
        bundle_verifier=_BundleVerifier(),
        skill_verifier=_SkillVerifier(),
        agent="Bragi",
        available_tools=frozenset({"query_inventory", "query_log"}),
        known_agents=frozenset({"Bragi"}),
        max_chars=8_192,
    )
    disabled = enabled.disable("incident-evidence-pack")
    uninstalled = disabled.uninstall("incident-evidence-pack")

    assert snapshot.replay.version == "1.0.0"
    assert [member.version for member in snapshot.replay.members] == ["1.0.0", "2.0.0"]
    assert uninstalled.list() == ()
    with pytest.raises(SkillBundleResolutionError) as updated:
        enabled.resolve(
            "incident-evidence-pack",
            skills=_skill_catalog(inventory_version="1.1.0"),
            bundle_verifier=_BundleVerifier(),
            skill_verifier=_SkillVerifier(),
            agent="Bragi",
            available_tools=frozenset({"query_inventory", "query_log"}),
            known_agents=frozenset({"Bragi"}),
            max_chars=8_192,
        )
    assert updated.value.reason is SkillBundleRejectionReason.VERSION_INCOMPATIBLE


def test_trust_and_combined_budget_fail_without_partial_result() -> None:
    enabled = _enable(_installed_bundle_catalog(), _skill_catalog())
    with pytest.raises(SkillBundleResolutionError) as trust:
        enabled.resolve(
            "incident-evidence-pack",
            skills=_skill_catalog(),
            bundle_verifier=_BundleVerifier(trusted=False),
            skill_verifier=_SkillVerifier(),
            agent="Bragi",
            available_tools=frozenset({"query_inventory", "query_log"}),
            known_agents=frozenset({"Bragi"}),
            max_chars=8_192,
        )
    assert trust.value.reason is SkillBundleRejectionReason.TRUST_FAILED

    with pytest.raises(SkillBundleResolutionError) as budget:
        enabled.resolve(
            "incident-evidence-pack",
            skills=_skill_catalog(),
            bundle_verifier=_BundleVerifier(),
            skill_verifier=_SkillVerifier(),
            agent="Bragi",
            available_tools=frozenset({"query_inventory", "query_log"}),
            known_agents=frozenset({"Bragi"}),
            max_chars=10,
        )
    assert budget.value.reason is SkillBundleRejectionReason.BUDGET_EXCEEDED
