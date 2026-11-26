"""Governed approval and emergency revocation for skill-source artifacts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai.core.skills.catalog import SkillCatalog, parse_skill_markdown
from fdai.core.skills.source_registry import SkillSourceStore
from fdai.core.supply_chain.installer import TrustedArtifactInstaller
from fdai.core.supply_chain.skill_quarantine import (
    SkillQuarantineState,
    SkillQuarantineStore,
    SkillRevocationStore,
    SkillUpdateCandidateStore,
)
from fdai.core.supply_chain.skill_source_pipeline import (
    SkillSourceRefreshService,
    SkillSourceVerifierFactory,
)


@dataclass(frozen=True, slots=True)
class ApprovedSkillCandidate:
    source_id: str
    candidate_id: str
    skill_name: str
    version: str
    enabled: bool = False


@dataclass(frozen=True, slots=True)
class SkillSourceRevocationResult:
    source_id: str
    revoked_digests: tuple[str, ...]
    disabled_artifact_ids: tuple[str, ...]


class SkillSourceRevoker(Protocol):
    async def revoke_source(
        self, *, source_id: str, reason: str, revoked_at: datetime
    ) -> SkillSourceRevocationResult: ...


class SkillSourceAdministrationService:
    def __init__(
        self,
        *,
        sources: SkillSourceStore,
        quarantine: SkillQuarantineStore,
        candidates: SkillUpdateCandidateStore,
        revocations: SkillRevocationStore,
        refresher: SkillSourceRefreshService,
        installer: TrustedArtifactInstaller,
        verifier_factory: SkillSourceVerifierFactory,
        revoker: SkillSourceRevoker,
        catalog: SkillCatalog | None = None,
        refresh_runtime: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._sources = sources
        self._quarantine = quarantine
        self._candidates = candidates
        self._revocations = revocations
        self._refresher = refresher
        self._installer = installer
        self._verifier_factory = verifier_factory
        self._revoker = revoker
        self._catalog = catalog or SkillCatalog()
        self._refresh_runtime = refresh_runtime

    async def approve_candidate(
        self, *, source_id: str, candidate_id: str, now: datetime
    ) -> ApprovedSkillCandidate:
        source = await self._sources.get(source_id)
        if source is None or not source.enabled:
            raise LookupError("enabled skill source not found")
        candidate = await self._candidates.get(candidate_id)
        if candidate is None:
            raise LookupError("skill update candidate not found")
        artifact = await self._quarantine.get(candidate.quarantine_id)
        if artifact is None or artifact.source_id != source_id:
            raise ValueError("skill update candidate does not belong to source")
        if artifact.state is not SkillQuarantineState.PROPOSED:
            raise ValueError("skill update candidate is not proposed")
        if await self._revocations.is_revoked(
            source_id=source_id,
            artifact_digest=artifact.artifact_digest,
        ):
            raise ValueError("revoked skill artifact cannot be approved")
        verifier = self._verifier_factory(source, artifact.publisher_signature)
        self._catalog = await self._refresher.install_approved(
            candidate,
            catalog=self._catalog,
            installer=self._installer,
            verifier=verifier,
            now=now,
        )
        root = next(item for item in artifact.files if item.path.endswith("/SKILL.md"))
        installed = parse_skill_markdown(root.content)
        if self._refresh_runtime is not None:
            await self._refresh_runtime()
        return ApprovedSkillCandidate(
            source_id=source_id,
            candidate_id=candidate_id,
            skill_name=installed.manifest.name,
            version=installed.manifest.version,
        )

    async def revoke_source(
        self, *, source_id: str, reason: str, revoked_at: datetime
    ) -> SkillSourceRevocationResult:
        if not reason.strip() or len(reason) > 512:
            raise ValueError("skill source revocation reason MUST be bounded")
        if await self._sources.get(source_id) is None:
            raise LookupError("skill source not found")
        result = await self._revoker.revoke_source(
            source_id=source_id,
            reason=reason.strip(),
            revoked_at=revoked_at,
        )
        if self._refresh_runtime is not None:
            await self._refresh_runtime()
        return result


__all__ = [
    "ApprovedSkillCandidate",
    "SkillSourceAdministrationService",
    "SkillSourceRevocationResult",
    "SkillSourceRevoker",
]
