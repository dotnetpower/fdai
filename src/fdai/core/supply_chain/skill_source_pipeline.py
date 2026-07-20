"""Refresh approved sources into quarantine and disabled install candidates."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from fdai.core.skills.catalog import (
    SkillCatalog,
    SkillTrustVerifier,
    parse_skill_markdown,
)
from fdai.core.skills.source_registry import SkillSource
from fdai.core.supply_chain.installer import TrustedArtifactInstaller
from fdai.core.supply_chain.skill_quarantine import (
    DeterministicSkillScanner,
    QuarantinedSkillArtifact,
    QuarantinedSkillFile,
    SkillQuarantineState,
    SkillQuarantineStore,
    SkillScanVerdict,
    SkillUpdateCandidate,
    SkillUpdateCandidateStore,
    quarantine_artifact_digest,
)
from fdai.shared.providers.skill_source import SkillSourceAdapter, SkillSourceFile


class SkillSourceVerifierFactory(Protocol):
    def __call__(self, source: SkillSource, signature: bytes) -> SkillTrustVerifier: ...


@dataclass(frozen=True, slots=True)
class SkillSourceRefreshResult:
    artifact: QuarantinedSkillArtifact | None
    candidate: SkillUpdateCandidate | None
    etag: str | None
    not_modified: bool = False


class SkillSourceRefreshService:
    """Fetch exact files, scan, verify, and create an inert update candidate."""

    def __init__(
        self,
        *,
        quarantine: SkillQuarantineStore,
        candidates: SkillUpdateCandidateStore,
        scanner: DeterministicSkillScanner,
        verifier_factory: SkillSourceVerifierFactory,
        scanner_version: str,
    ) -> None:
        self._quarantine = quarantine
        self._candidates = candidates
        self._scanner = scanner
        self._verifier_factory = verifier_factory
        self._scanner_version = scanner_version

    async def refresh(
        self,
        source: SkillSource,
        adapter: SkillSourceAdapter,
        *,
        fetched_at: datetime,
        prior_etag: str | None = None,
        prior_installed_digest: str | None = None,
    ) -> SkillSourceRefreshResult:
        if not source.enabled:
            raise ValueError("skill source MUST be enabled before refresh")
        revision = await adapter.resolve_revision(
            repository=source.location,
            prior_etag=prior_etag,
        )
        if revision.not_modified:
            return SkillSourceRefreshResult(None, None, revision.etag, not_modified=True)
        if revision.revision is None:
            raise RuntimeError("modified skill source did not return a revision")
        root = f"{source.allowed_path}/SKILL.md"
        signature_path = f"{source.allowed_path}/SKILL.md.sig"
        initial = await adapter.fetch_files(
            repository=source.location,
            revision=revision.revision,
            paths=(root, signature_path),
        )
        by_path = {item.path: item for item in initial}
        raw_markdown = by_path[root].content
        signature = by_path[signature_path].content
        skill = parse_skill_markdown(raw_markdown)
        if skill.manifest.source != source.source_id:
            raise ValueError("skill manifest source does not match registered source")
        reference_paths = tuple(
            f"{source.allowed_path}/{reference.path}" for reference in skill.manifest.references
        )
        references = (
            await adapter.fetch_files(
                repository=source.location,
                revision=revision.revision,
                paths=reference_paths,
            )
            if reference_paths
            else ()
        )
        files = tuple(_quarantine_file(item) for item in (by_path[root], *references))
        digest = quarantine_artifact_digest(files)
        fetched = QuarantinedSkillArtifact(
            quarantine_id=f"skill-quarantine-{digest[:24]}",
            source_id=source.source_id,
            source_revision=revision.revision,
            artifact_digest=digest,
            files=files,
            publisher_signature=signature,
            fetched_at=fetched_at,
            prior_installed_digest=prior_installed_digest,
        )
        scanned = self._scanner.scan(fetched, scanner_version=self._scanner_version)
        if scanned.verdict is SkillScanVerdict.BLOCK:
            await self._quarantine.put(scanned)
            return SkillSourceRefreshResult(scanned, None, revision.etag)
        verifier = self._verifier_factory(source, signature)
        if not verifier.verify(skill, raw_markdown):
            blocked = replace(
                scanned,
                state=SkillQuarantineState.BLOCKED,
                verdict=SkillScanVerdict.BLOCK,
            )
            await self._quarantine.put(blocked)
            return SkillSourceRefreshResult(blocked, None, revision.etag)
        proposed = replace(scanned, state=SkillQuarantineState.PROPOSED)
        await self._quarantine.put(proposed)
        candidate = SkillUpdateCandidate(
            candidate_id=f"skill-update-{digest[:24]}",
            quarantine_id=proposed.quarantine_id,
            artifact_digest=digest,
            prior_installed_digest=prior_installed_digest,
            created_at=fetched_at,
        )
        await self._candidates.put(candidate)
        return SkillSourceRefreshResult(proposed, candidate, revision.etag)

    async def install_approved(
        self,
        candidate: SkillUpdateCandidate,
        *,
        catalog: SkillCatalog,
        installer: TrustedArtifactInstaller,
        verifier: SkillTrustVerifier,
        now: datetime,
    ) -> SkillCatalog:
        artifact = await self._quarantine.get(candidate.quarantine_id)
        if artifact is None or artifact.state is not SkillQuarantineState.PROPOSED:
            raise ValueError("only proposed quarantine artifacts can be installed")
        if artifact.artifact_digest != candidate.artifact_digest or not candidate.disabled:
            raise ValueError("skill update candidate does not match quarantine content")
        root = next(item for item in artifact.files if item.path.endswith("/SKILL.md"))
        skill = parse_skill_markdown(root.content)
        reference_content = {
            reference.path: next(
                item.content for item in artifact.files if item.path.endswith(f"/{reference.path}")
            )
            for reference in skill.manifest.references
        }
        return await installer.install_skill(
            catalog,
            root.content,
            references=reference_content,
            signature=artifact.publisher_signature,
            verifier=verifier,
            now=now,
        )


def _quarantine_file(value: SkillSourceFile) -> QuarantinedSkillFile:
    return QuarantinedSkillFile(
        path=value.path,
        content_sha256=hashlib.sha256(value.content).hexdigest(),
        content=value.content,
        media_type=value.media_type,
        is_symlink=value.is_symlink,
    )


__all__ = [
    "SkillSourceRefreshResult",
    "SkillSourceRefreshService",
    "SkillSourceVerifierFactory",
]
