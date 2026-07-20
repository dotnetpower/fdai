"""Bounded metadata disclosure and trust-rechecked runtime skill reads."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fdai.core.skills.catalog import RuntimeSkill, SkillTrustVerifier

from fdai.core.skills.errors import SkillCatalogError
from fdai.core.skills.references import (
    SkillReferenceArtifact,
    SkillReferenceManifest,
    verify_reference_artifacts,
)

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_MAX_INDEX_CHARS = 32 * 1024


@dataclass(frozen=True, slots=True)
class SkillDiagnostic:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class SkillReferenceReplayMetadata:
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class SkillReplayMetadata:
    operation: str
    skill_name: str
    skill_version: str
    raw_markdown_sha256: str
    body_sha256: str
    references: tuple[SkillReferenceReplayMetadata, ...]


@dataclass(frozen=True, slots=True)
class SkillDescriptor:
    name: str
    version: str
    description: str
    source: str
    required_tools: tuple[str, ...]
    allowed_agents: tuple[str, ...]
    enabled: bool
    references: tuple[SkillReferenceManifest, ...]


@dataclass(frozen=True, slots=True)
class SkillIndexEntry:
    descriptor: SkillDescriptor
    query_token_overlap: int


@dataclass(frozen=True, slots=True)
class SkillIndexResult:
    entries: tuple[SkillIndexEntry, ...]
    query_tokens: tuple[str, ...]
    projected_chars: int
    diagnostics: tuple[SkillDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class SkillDescriptorResult:
    descriptor: SkillDescriptor
    replay: SkillReplayMetadata
    diagnostics: tuple[SkillDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class SkillLoadResult:
    descriptor: SkillDescriptor
    body: str
    replay: SkillReplayMetadata
    diagnostics: tuple[SkillDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class SkillReferenceResult:
    descriptor: SkillDescriptor
    reference: SkillReferenceManifest
    content: bytes
    replay: SkillReplayMetadata
    diagnostics: tuple[SkillDiagnostic, ...]


class SkillRejectionReason(StrEnum):
    NOT_INSTALLED = "skill_not_installed"
    DISABLED = "skill_disabled"
    AGENT_NOT_ALLOWED = "skill_agent_not_allowed"
    REQUIRED_TOOLS_UNAVAILABLE = "skill_required_tools_unavailable"
    TRUST_VERIFICATION_FAILED = "skill_trust_verification_failed"
    STORED_ARTIFACT_INVALID = "skill_stored_artifact_invalid"
    INDEX_BUDGET_EXCEEDED = "skill_index_budget_exceeded"
    BODY_BUDGET_EXCEEDED = "skill_body_budget_exceeded"
    REFERENCE_NOT_DECLARED = "skill_reference_not_declared"
    REFERENCE_BUDGET_EXCEEDED = "skill_reference_budget_exceeded"


class SkillAccessError(SkillCatalogError):
    """A read-only skill operation was rejected with a stable machine reason."""

    def __init__(
        self,
        reason: SkillRejectionReason,
        *,
        replay: SkillReplayMetadata | None = None,
    ) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.replay = replay
        self.diagnostics = (SkillDiagnostic(code=reason.value, message="skill read rejected"),)


def list_skills(
    skills: Mapping[str, RuntimeSkill],
    *,
    query: str,
    agent: str,
    available_tools: frozenset[str],
    max_chars: int,
) -> SkillIndexResult:
    if max_chars < 1:
        raise ValueError("skill index budget MUST be positive")
    query_tokens = tuple(sorted(set(_TOKEN_PATTERN.findall(query.lower()))))
    entries: list[SkillIndexEntry] = []
    for name in sorted(skills):
        skill = skills[name]
        if not _is_eligible(skill, agent=agent, available_tools=available_tools):
            continue
        descriptor = _descriptor(skill)
        searchable = " ".join((descriptor.name, descriptor.description, *descriptor.required_tools))
        searchable_tokens = set(_TOKEN_PATTERN.findall(searchable.lower()))
        entries.append(
            SkillIndexEntry(
                descriptor=descriptor,
                query_token_overlap=len(set(query_tokens) & searchable_tokens),
            )
        )
    entries.sort(key=lambda entry: (-entry.query_token_overlap, entry.descriptor.name))
    projected_chars = sum(len(_index_projection(entry)) for entry in entries)
    if projected_chars > min(max_chars, _MAX_INDEX_CHARS):
        raise SkillAccessError(SkillRejectionReason.INDEX_BUDGET_EXCEEDED)
    return SkillIndexResult(
        entries=tuple(entries),
        query_tokens=query_tokens,
        projected_chars=projected_chars,
        diagnostics=(
            SkillDiagnostic(code="skill_index_ready", message="eligible skill index built"),
        ),
    )


def describe_skill(skills: Mapping[str, RuntimeSkill], name: str) -> SkillDescriptorResult:
    skill = _get_skill(skills, name)
    return SkillDescriptorResult(
        descriptor=_descriptor(skill),
        replay=_replay(skill, operation="describe_skill"),
        diagnostics=(SkillDiagnostic(code="skill_described", message="skill metadata returned"),),
    )


def load_skill(
    skills: Mapping[str, RuntimeSkill],
    name: str,
    *,
    agent: str,
    available_tools: frozenset[str],
    verifier: SkillTrustVerifier,
    max_chars: int,
) -> SkillLoadResult:
    if max_chars < 1:
        raise ValueError("skill body budget MUST be positive")
    skill = _get_skill(skills, name)
    _require_eligible(skill, agent=agent, available_tools=available_tools, operation="load_skill")
    _verify_stored_skill(skill, verifier=verifier, operation="load_skill")
    if len(skill.body) > max_chars:
        raise SkillAccessError(
            SkillRejectionReason.BODY_BUDGET_EXCEEDED,
            replay=_replay(skill, operation="load_skill"),
        )
    return SkillLoadResult(
        descriptor=_descriptor(skill),
        body=skill.body,
        replay=_replay(skill, operation="load_skill"),
        diagnostics=(SkillDiagnostic(code="skill_loaded", message="skill body verified"),),
    )


def read_skill_reference(
    skills: Mapping[str, RuntimeSkill],
    name: str,
    path: str,
    *,
    agent: str,
    available_tools: frozenset[str],
    verifier: SkillTrustVerifier,
    max_bytes: int,
) -> SkillReferenceResult:
    if max_bytes < 1:
        raise ValueError("skill reference budget MUST be positive")
    skill = _get_skill(skills, name)
    _require_eligible(
        skill,
        agent=agent,
        available_tools=available_tools,
        operation="read_skill_reference",
    )
    _verify_stored_skill(skill, verifier=verifier, operation="read_skill_reference")
    artifact = next(
        (candidate for candidate in skill.references if candidate.manifest.path == path),
        None,
    )
    if artifact is None:
        raise SkillAccessError(
            SkillRejectionReason.REFERENCE_NOT_DECLARED,
            replay=_replay(skill, operation="read_skill_reference"),
        )
    if len(artifact.content) > max_bytes:
        raise SkillAccessError(
            SkillRejectionReason.REFERENCE_BUDGET_EXCEEDED,
            replay=_replay(skill, operation="read_skill_reference"),
        )
    return SkillReferenceResult(
        descriptor=_descriptor(skill),
        reference=artifact.manifest,
        content=artifact.content,
        replay=_replay(skill, operation="read_skill_reference"),
        diagnostics=(
            SkillDiagnostic(code="skill_reference_read", message="skill reference verified"),
        ),
    )


def _get_skill(skills: Mapping[str, RuntimeSkill], name: str) -> RuntimeSkill:
    try:
        return skills[name]
    except KeyError as exc:
        raise SkillAccessError(SkillRejectionReason.NOT_INSTALLED) from exc


def _is_eligible(
    skill: RuntimeSkill,
    *,
    agent: str,
    available_tools: frozenset[str],
) -> bool:
    manifest = skill.manifest
    return (
        skill.enabled
        and (not manifest.allowed_agents or agent in manifest.allowed_agents)
        and set(manifest.required_tools) <= available_tools
    )


def _require_eligible(
    skill: RuntimeSkill,
    *,
    agent: str,
    available_tools: frozenset[str],
    operation: str,
) -> None:
    replay = _replay(skill, operation=operation)
    if not skill.enabled:
        raise SkillAccessError(SkillRejectionReason.DISABLED, replay=replay)
    if skill.manifest.allowed_agents and agent not in skill.manifest.allowed_agents:
        raise SkillAccessError(SkillRejectionReason.AGENT_NOT_ALLOWED, replay=replay)
    if not set(skill.manifest.required_tools) <= available_tools:
        raise SkillAccessError(SkillRejectionReason.REQUIRED_TOOLS_UNAVAILABLE, replay=replay)


def _verify_stored_skill(
    skill: RuntimeSkill,
    *,
    verifier: SkillTrustVerifier,
    operation: str,
) -> None:
    from fdai.core.skills.catalog import parse_skill_markdown

    replay = _replay(skill, operation=operation)
    if not skill.raw_markdown:
        raise SkillAccessError(SkillRejectionReason.STORED_ARTIFACT_INVALID, replay=replay)
    try:
        parsed = parse_skill_markdown(skill.raw_markdown)
    except SkillCatalogError as exc:
        raise SkillAccessError(
            SkillRejectionReason.STORED_ARTIFACT_INVALID,
            replay=replay,
        ) from exc
    if parsed.manifest != skill.manifest or parsed.body != skill.body:
        raise SkillAccessError(SkillRejectionReason.STORED_ARTIFACT_INVALID, replay=replay)
    if not verifier.verify(parsed, skill.raw_markdown):
        raise SkillAccessError(SkillRejectionReason.TRUST_VERIFICATION_FAILED, replay=replay)
    try:
        verify_reference_artifacts(parsed.manifest.references, skill.references)
    except SkillCatalogError as exc:
        raise SkillAccessError(
            SkillRejectionReason.STORED_ARTIFACT_INVALID,
            replay=replay,
        ) from exc


def _descriptor(skill: RuntimeSkill) -> SkillDescriptor:
    manifest = skill.manifest
    return SkillDescriptor(
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        source=manifest.source,
        required_tools=manifest.required_tools,
        allowed_agents=manifest.allowed_agents,
        enabled=skill.enabled,
        references=manifest.references,
    )


def _replay(skill: RuntimeSkill, *, operation: str) -> SkillReplayMetadata:
    return SkillReplayMetadata(
        operation=operation,
        skill_name=skill.manifest.name,
        skill_version=skill.manifest.version,
        raw_markdown_sha256=hashlib.sha256(skill.raw_markdown).hexdigest(),
        body_sha256=skill.manifest.body_sha256,
        references=tuple(
            SkillReferenceReplayMetadata(
                path=reference.path,
                sha256=reference.sha256,
                size_bytes=reference.size_bytes,
            )
            for reference in skill.manifest.references
        ),
    )


def _index_projection(entry: SkillIndexEntry) -> str:
    descriptor = entry.descriptor
    references = ",".join(
        f"{reference.path}:{reference.sha256}:{reference.size_bytes}:{reference.media_type}"
        for reference in descriptor.references
    )
    return "|".join(
        (
            descriptor.name,
            descriptor.version,
            descriptor.description,
            descriptor.source,
            ",".join(descriptor.required_tools),
            ",".join(descriptor.allowed_agents),
            references,
            str(entry.query_token_overlap),
        )
    )


__all__ = [
    "SkillAccessError",
    "SkillCatalogError",
    "SkillDescriptor",
    "SkillDescriptorResult",
    "SkillDiagnostic",
    "SkillIndexEntry",
    "SkillIndexResult",
    "SkillLoadResult",
    "SkillReferenceArtifact",
    "SkillReferenceManifest",
    "SkillReferenceReplayMetadata",
    "SkillReferenceResult",
    "SkillRejectionReason",
    "SkillReplayMetadata",
]
