"""Trust-verify and durably install extensions and skills as disabled artifacts."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from fdai.core.capability_catalog.extensions import (
    ExtensionManager,
    ExtensionPackage,
    ExtensionTrustVerifier,
)
from fdai.core.skills.bundle_catalog import SkillBundleCatalog
from fdai.core.skills.bundle_manifest import (
    SkillBundleTrustVerifier,
    parse_skill_bundle_manifest,
)
from fdai.core.skills.catalog import SkillCatalog, SkillTrustVerifier, parse_skill_markdown
from fdai.core.supply_chain.artifacts import (
    TrustedArtifactKind,
    TrustedArtifactRecord,
    TrustedArtifactState,
    TrustedArtifactStore,
)
from fdai.core.supply_chain.skill_bundle import encode_skill_bundle

_EMPTY_REFERENCES: Mapping[str, bytes] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class TrustedArtifactInstaller:
    """Keep trust verification, disabled-first install, and durability atomic to callers."""

    store: TrustedArtifactStore

    async def install_extension(
        self,
        manager: ExtensionManager,
        package: ExtensionPackage,
        *,
        archive: bytes,
        signature: bytes,
        verifier: ExtensionTrustVerifier,
        now: datetime,
    ) -> ExtensionManager:
        candidate = manager.install(package, archive=archive, verifier=verifier)
        manifest = package.manifest
        await self.store.put(
            TrustedArtifactRecord(
                kind=TrustedArtifactKind.EXTENSION,
                artifact_id=manifest.extension_id,
                version=manifest.version,
                source=manifest.source,
                content_sha256=manifest.archive_sha256,
                artifact=archive,
                signature=signature,
                state=TrustedArtifactState.DISABLED,
                revision=1,
                created_at=now,
                updated_at=now,
            ),
            expected_revision=0,
        )
        return candidate

    async def install_skill(
        self,
        catalog: SkillCatalog,
        raw_markdown: bytes,
        *,
        references: Mapping[str, bytes] = _EMPTY_REFERENCES,
        signature: bytes,
        verifier: SkillTrustVerifier,
        now: datetime,
    ) -> SkillCatalog:
        reference_snapshot = MappingProxyType(dict(references))
        candidate = catalog.install_bundle(raw_markdown, reference_snapshot, verifier=verifier)
        skill = parse_skill_markdown(raw_markdown)
        stored_artifact = (
            encode_skill_bundle(raw_markdown, reference_snapshot)
            if reference_snapshot
            else raw_markdown
        )
        await self.store.put(
            TrustedArtifactRecord(
                kind=TrustedArtifactKind.SKILL,
                artifact_id=skill.manifest.name,
                version=skill.manifest.version,
                source=skill.manifest.source,
                content_sha256=hashlib.sha256(stored_artifact).hexdigest(),
                artifact=stored_artifact,
                signature=signature,
                state=TrustedArtifactState.DISABLED,
                revision=1,
                created_at=now,
                updated_at=now,
            ),
            expected_revision=0,
        )
        return candidate

    async def install_skill_bundle(
        self,
        catalog: SkillBundleCatalog,
        raw_manifest: bytes,
        *,
        signature: bytes,
        verifier: SkillBundleTrustVerifier,
        now: datetime,
    ) -> SkillBundleCatalog:
        candidate = catalog.install(raw_manifest, verifier=verifier)
        manifest = parse_skill_bundle_manifest(raw_manifest).manifest
        await self.store.put(
            TrustedArtifactRecord(
                kind=TrustedArtifactKind.SKILL_BUNDLE,
                artifact_id=manifest.name,
                version=manifest.version,
                source=manifest.source,
                content_sha256=hashlib.sha256(raw_manifest).hexdigest(),
                artifact=raw_manifest,
                signature=signature,
                state=TrustedArtifactState.DISABLED,
                revision=1,
                created_at=now,
                updated_at=now,
            ),
            expected_revision=0,
        )
        return candidate
