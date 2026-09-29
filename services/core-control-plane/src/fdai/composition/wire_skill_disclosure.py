"""Startup binding for durable runtime skill disclosure snapshots."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.core.skills import RuntimeSkillDisclosure, SkillBundleTrustVerifier, SkillTrustVerifier
from fdai.core.supply_chain import (
    SkillBundleTrustVerifierFactory,
    SkillTrustVerifierFactory,
    TrustedArtifactKind,
    TrustedArtifactStore,
    load_skill_bundle_catalog,
    load_skill_catalog,
)


@dataclass(frozen=True, slots=True)
class SkillDisclosureStartupReadiness:
    """Proof that both trusted skill snapshots were rebuilt before readiness."""

    skill_count: int
    enabled_skill_count: int
    bundle_count: int
    enabled_bundle_count: int

    @property
    def ready(self) -> bool:
        return True


async def publish_trusted_skill_disclosure_snapshots(
    disclosure: RuntimeSkillDisclosure,
    *,
    store: TrustedArtifactStore,
    skill_verifier_factory: SkillTrustVerifierFactory,
    bundle_verifier_factory: SkillBundleTrustVerifierFactory,
    skill_verifier: SkillTrustVerifier,
    bundle_verifier: SkillBundleTrustVerifier,
    available_tools: frozenset[str],
    known_agents: frozenset[str],
) -> SkillDisclosureStartupReadiness:
    """Reconstruct and publish signed skill snapshots before serving traffic.

    The reconstruction is intentionally ordered: single skills load first so
    governed bundles can validate exact member versions and enabled state
    against that candidate catalog. Publication happens only after both
    candidates are verified, so a tampered bundle record fails startup without
    replacing either runtime snapshot.
    """

    skill_records = await store.list(TrustedArtifactKind.SKILL)
    skill_catalog = load_skill_catalog(
        skill_records,
        skill_verifier_factory,
        available_tools,
        known_agents,
    )
    bundle_records = await store.list(TrustedArtifactKind.SKILL_BUNDLE)
    bundle_catalog = load_skill_bundle_catalog(
        bundle_records,
        bundle_verifier_factory,
        skills=skill_catalog,
        skill_verifier=skill_verifier,
        available_tools=available_tools,
        known_agents=known_agents,
    )

    disclosure.publish_snapshot(catalog=skill_catalog, verifier=skill_verifier)
    disclosure.publish_bundle_snapshot(catalog=bundle_catalog, verifier=bundle_verifier)
    skills = skill_catalog.list()
    bundles = bundle_catalog.list()
    return SkillDisclosureStartupReadiness(
        skill_count=len(skills),
        enabled_skill_count=sum(item.enabled for item in skills),
        bundle_count=len(bundles),
        enabled_bundle_count=sum(item.enabled for item in bundles),
    )


__all__ = [
    "SkillDisclosureStartupReadiness",
    "publish_trusted_skill_disclosure_snapshots",
]
