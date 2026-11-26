"""Fail-closed reconstruction of governed skill bundles from durable records."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Protocol

from fdai.core.skills import (
    SkillBundleCatalog,
    SkillBundleTrustVerifier,
    SkillCatalog,
    SkillTrustVerifier,
    parse_skill_bundle_manifest,
)
from fdai.core.supply_chain.artifacts import (
    TrustedArtifactKind,
    TrustedArtifactRecord,
    TrustedArtifactState,
)


class SkillBundleTrustVerifierFactory(Protocol):
    def __call__(self, record: TrustedArtifactRecord, /) -> SkillBundleTrustVerifier: ...


class TrustedSkillBundleLoadError(ValueError):
    """A durable governed bundle cannot be trusted and startup must stop."""


def load_skill_bundle_catalog(
    records: Iterable[TrustedArtifactRecord],
    verifier_factory: SkillBundleTrustVerifierFactory,
    *,
    skills: SkillCatalog,
    skill_verifier: SkillTrustVerifier,
    available_tools: frozenset[str],
    known_agents: frozenset[str],
) -> SkillBundleCatalog:
    durable_records = tuple(records)
    if any(record.kind is not TrustedArtifactKind.SKILL_BUNDLE for record in durable_records):
        raise TrustedSkillBundleLoadError("bundle restart received non-bundle records")
    if any(
        record.state not in {TrustedArtifactState.DISABLED, TrustedArtifactState.ENABLED}
        for record in durable_records
    ):
        raise TrustedSkillBundleLoadError("bundle restart records contain invalid states")
    artifact_ids = tuple(record.artifact_id for record in durable_records)
    if len(set(artifact_ids)) != len(artifact_ids):
        raise TrustedSkillBundleLoadError("bundle restart records contain duplicate artifact ids")

    catalog = SkillBundleCatalog()
    for record in sorted(durable_records, key=lambda item: item.artifact_id):
        if hashlib.sha256(record.artifact).hexdigest() != record.content_sha256:
            raise TrustedSkillBundleLoadError(
                f"trusted bundle {record.artifact_id!r} content digest mismatch"
            )
        bundle = parse_skill_bundle_manifest(record.artifact)
        manifest = bundle.manifest
        if (
            record.artifact_id != manifest.name
            or record.version != manifest.version
            or record.source != manifest.source
        ):
            raise TrustedSkillBundleLoadError(
                f"trusted bundle {record.artifact_id!r} identity does not match manifest"
            )
        verifier = verifier_factory(record)
        catalog = catalog.install(record.artifact, verifier=verifier)
        if record.state is TrustedArtifactState.ENABLED:
            catalog = catalog.enable(
                manifest.name,
                skills=skills,
                bundle_verifier=verifier,
                skill_verifier=skill_verifier,
                available_tools=available_tools,
                known_agents=known_agents,
            )
    return catalog


__all__ = [
    "SkillBundleTrustVerifierFactory",
    "TrustedSkillBundleLoadError",
    "load_skill_bundle_catalog",
]
