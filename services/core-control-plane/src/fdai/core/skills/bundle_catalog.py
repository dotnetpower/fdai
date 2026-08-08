"""Immutable lifecycle and all-or-nothing resolution for governed skill bundles."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from fdai.core.skills.bundle_manifest import (
    RuntimeSkillBundle,
    SkillBundleManifest,
    SkillBundleTrustVerifier,
    parse_skill_bundle_manifest,
)
from fdai.core.skills.catalog import SkillCatalog, SkillCatalogError, SkillTrustVerifier
from fdai.core.skills.disclosure import (
    SkillAccessError,
    SkillLoadResult,
    SkillRejectionReason,
)


class SkillBundleRejectionReason(StrEnum):
    NOT_INSTALLED = "skill_bundle_not_installed"
    DISABLED = "skill_bundle_disabled"
    TRUST_FAILED = "skill_bundle_trust_verification_failed"
    STORED_ARTIFACT_INVALID = "skill_bundle_stored_artifact_invalid"
    AGENT_NOT_ALLOWED = "skill_bundle_agent_not_allowed"
    REQUIRED_TOOLS_UNAVAILABLE = "skill_bundle_required_tools_unavailable"
    MEMBER_MISSING = "skill_bundle_member_missing"
    MEMBER_DISABLED = "skill_bundle_member_disabled"
    MEMBER_TRUST_FAILED = "skill_bundle_member_trust_failed"
    VERSION_INCOMPATIBLE = "skill_bundle_member_version_incompatible"
    DEPENDENCY_UNDECLARED = "skill_bundle_member_dependency_undeclared"
    NO_EFFECTIVE_AGENT = "skill_bundle_no_effective_agent"
    NESTED_UNSUPPORTED = "skill_bundle_nested_bundle_unsupported"
    DEPENDENCY_CYCLE = "skill_bundle_dependency_cycle"
    AMBIGUOUS_MEMBER = "skill_bundle_member_name_ambiguous"
    BUDGET_EXCEEDED = "skill_bundle_budget_exceeded"


class SkillBundleResolutionError(SkillCatalogError):
    """Bundle resolution failed without returning a partial member set."""

    def __init__(
        self,
        reason: SkillBundleRejectionReason,
        *,
        bundle_name: str,
        member_name: str | None = None,
    ) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.bundle_name = bundle_name
        self.member_name = member_name


@dataclass(frozen=True, slots=True)
class SkillBundleMemberReplay:
    name: str
    version: str
    raw_markdown_sha256: str
    body_sha256: str


@dataclass(frozen=True, slots=True)
class SkillBundleReplay:
    name: str
    version: str
    manifest_sha256: str
    digest: str
    members: tuple[SkillBundleMemberReplay, ...]


@dataclass(frozen=True, slots=True)
class ResolvedSkillBundle:
    manifest: SkillBundleManifest
    instruction: str | None
    members: tuple[SkillLoadResult, ...]
    effective_agents: tuple[str, ...]
    required_tools: tuple[str, ...]
    replay: SkillBundleReplay


class SkillBundleCatalog:
    """Immutable governed bundle catalog; install is disabled-first."""

    __slots__ = ("_bundles",)

    def __init__(self, bundles: dict[str, RuntimeSkillBundle] | None = None) -> None:
        self._bundles: Final = MappingProxyType(dict(bundles or {}))

    def install(
        self,
        raw_manifest: bytes,
        *,
        verifier: SkillBundleTrustVerifier,
    ) -> SkillBundleCatalog:
        bundle = parse_skill_bundle_manifest(raw_manifest)
        name = bundle.manifest.name
        if name in self._bundles:
            raise SkillCatalogError(f"skill bundle {name!r} is already installed")
        if not verifier.verify(bundle, raw_manifest):
            raise SkillCatalogError("skill bundle publisher trust verification failed")
        bundles = dict(self._bundles)
        bundles[name] = bundle
        return SkillBundleCatalog(bundles)

    def enable(
        self,
        name: str,
        *,
        skills: SkillCatalog,
        bundle_verifier: SkillBundleTrustVerifier,
        skill_verifier: SkillTrustVerifier,
        available_tools: frozenset[str],
        known_agents: frozenset[str],
    ) -> SkillBundleCatalog:
        current = self.get(name)
        _validate_member_graph(name, bundles=self, skills=skills)
        effective_agents = _effective_agents(current, skills=skills, known_agents=known_agents)
        if not effective_agents:
            raise SkillBundleResolutionError(
                SkillBundleRejectionReason.NO_EFFECTIVE_AGENT,
                bundle_name=name,
            )
        _resolve(
            current,
            bundles=self,
            skills=skills,
            bundle_verifier=bundle_verifier,
            skill_verifier=skill_verifier,
            agent=effective_agents[0],
            available_tools=available_tools,
            known_agents=known_agents,
            max_chars=256 * 1024,
            require_enabled=False,
        )
        bundles = dict(self._bundles)
        bundles[name] = replace(current, enabled=True)
        return SkillBundleCatalog(bundles)

    def disable(self, name: str) -> SkillBundleCatalog:
        bundles = dict(self._bundles)
        bundles[name] = replace(self.get(name), enabled=False)
        return SkillBundleCatalog(bundles)

    def uninstall(self, name: str) -> SkillBundleCatalog:
        current = self.get(name)
        if current.enabled:
            raise SkillCatalogError("disable a skill bundle before uninstalling it")
        bundles = dict(self._bundles)
        del bundles[name]
        return SkillBundleCatalog(bundles)

    def get(self, name: str) -> RuntimeSkillBundle:
        try:
            return self._bundles[name]
        except KeyError as exc:
            raise SkillBundleResolutionError(
                SkillBundleRejectionReason.NOT_INSTALLED,
                bundle_name=name,
            ) from exc

    def list(self) -> tuple[RuntimeSkillBundle, ...]:
        return tuple(self._bundles[name] for name in sorted(self._bundles))

    def resolve(
        self,
        name: str,
        *,
        skills: SkillCatalog,
        bundle_verifier: SkillBundleTrustVerifier,
        skill_verifier: SkillTrustVerifier,
        agent: str,
        available_tools: frozenset[str],
        known_agents: frozenset[str],
        max_chars: int,
    ) -> ResolvedSkillBundle:
        if max_chars < 1:
            raise ValueError("skill bundle budget MUST be positive")
        return _resolve(
            self.get(name),
            bundles=self,
            skills=skills,
            bundle_verifier=bundle_verifier,
            skill_verifier=skill_verifier,
            agent=agent,
            available_tools=available_tools,
            known_agents=known_agents,
            max_chars=max_chars,
            require_enabled=True,
        )


def _resolve(
    bundle: RuntimeSkillBundle,
    *,
    bundles: SkillBundleCatalog,
    skills: SkillCatalog,
    bundle_verifier: SkillBundleTrustVerifier,
    skill_verifier: SkillTrustVerifier,
    agent: str,
    available_tools: frozenset[str],
    known_agents: frozenset[str],
    max_chars: int,
    require_enabled: bool,
) -> ResolvedSkillBundle:
    manifest = bundle.manifest
    name = manifest.name
    if require_enabled and not bundle.enabled:
        raise SkillBundleResolutionError(
            SkillBundleRejectionReason.DISABLED,
            bundle_name=name,
        )
    _verify_bundle(bundle, verifier=bundle_verifier)
    _validate_member_graph(name, bundles=bundles, skills=skills)
    if manifest.allowed_agents and agent not in manifest.allowed_agents:
        raise SkillBundleResolutionError(
            SkillBundleRejectionReason.AGENT_NOT_ALLOWED,
            bundle_name=name,
        )
    if not set(manifest.required_tools) <= available_tools:
        raise SkillBundleResolutionError(
            SkillBundleRejectionReason.REQUIRED_TOOLS_UNAVAILABLE,
            bundle_name=name,
        )
    effective_agents = _effective_agents(bundle, skills=skills, known_agents=known_agents)
    if agent not in effective_agents:
        raise SkillBundleResolutionError(
            SkillBundleRejectionReason.AGENT_NOT_ALLOWED,
            bundle_name=name,
        )
    loaded_members: list[SkillLoadResult] = []
    member_required_tools: set[str] = set()
    for member in manifest.members:
        try:
            skill = skills.get(member.name)
        except SkillCatalogError as exc:
            raise SkillBundleResolutionError(
                SkillBundleRejectionReason.MEMBER_MISSING,
                bundle_name=name,
                member_name=member.name,
            ) from exc
        if not skill.enabled:
            raise SkillBundleResolutionError(
                SkillBundleRejectionReason.MEMBER_DISABLED,
                bundle_name=name,
                member_name=member.name,
            )
        if skill.manifest.version != member.exact_version:
            raise SkillBundleResolutionError(
                SkillBundleRejectionReason.VERSION_INCOMPATIBLE,
                bundle_name=name,
                member_name=member.name,
            )
        member_required_tools.update(skill.manifest.required_tools)
        try:
            loaded_members.append(
                skills.load_skill(
                    member.name,
                    agent=agent,
                    available_tools=available_tools,
                    verifier=skill_verifier,
                    max_chars=64 * 1024,
                )
            )
        except SkillAccessError as exc:
            raise SkillBundleResolutionError(
                _member_rejection_reason(exc.reason),
                bundle_name=name,
                member_name=member.name,
            ) from exc
    if not member_required_tools <= set(manifest.required_tools):
        raise SkillBundleResolutionError(
            SkillBundleRejectionReason.DEPENDENCY_UNDECLARED,
            bundle_name=name,
        )
    projected_chars = len(manifest.instruction or "") + sum(
        len(member.body) for member in loaded_members
    )
    if projected_chars > max_chars:
        raise SkillBundleResolutionError(
            SkillBundleRejectionReason.BUDGET_EXCEEDED,
            bundle_name=name,
        )
    return ResolvedSkillBundle(
        manifest=manifest,
        instruction=manifest.instruction,
        members=tuple(loaded_members),
        effective_agents=effective_agents,
        required_tools=tuple(sorted(member_required_tools)),
        replay=SkillBundleReplay(
            name=name,
            version=manifest.version,
            manifest_sha256=hashlib.sha256(bundle.raw_manifest).hexdigest(),
            digest=manifest.digest,
            members=tuple(
                SkillBundleMemberReplay(
                    name=member.replay.skill_name,
                    version=member.replay.skill_version,
                    raw_markdown_sha256=member.replay.raw_markdown_sha256,
                    body_sha256=member.replay.body_sha256,
                )
                for member in loaded_members
            ),
        ),
    )


def _verify_bundle(
    bundle: RuntimeSkillBundle,
    *,
    verifier: SkillBundleTrustVerifier,
) -> None:
    try:
        parsed = parse_skill_bundle_manifest(bundle.raw_manifest)
    except (SkillCatalogError, ValueError) as exc:
        raise SkillBundleResolutionError(
            SkillBundleRejectionReason.STORED_ARTIFACT_INVALID,
            bundle_name=bundle.manifest.name,
        ) from exc
    if parsed.manifest != bundle.manifest or not verifier.verify(parsed, bundle.raw_manifest):
        raise SkillBundleResolutionError(
            SkillBundleRejectionReason.TRUST_FAILED,
            bundle_name=bundle.manifest.name,
        )


def _effective_agents(
    bundle: RuntimeSkillBundle,
    *,
    skills: SkillCatalog,
    known_agents: frozenset[str],
) -> tuple[str, ...]:
    effective = set(known_agents)
    if bundle.manifest.allowed_agents:
        effective.intersection_update(bundle.manifest.allowed_agents)
    for member in bundle.manifest.members:
        try:
            skill = skills.get(member.name)
        except SkillCatalogError:
            continue
        if skill.manifest.allowed_agents:
            effective.intersection_update(skill.manifest.allowed_agents)
    return tuple(sorted(effective))


def _validate_member_graph(
    root: str,
    *,
    bundles: SkillBundleCatalog,
    skills: SkillCatalog,
) -> None:
    skill_names = {skill.manifest.name for skill in skills.list()}
    bundle_names = {bundle.manifest.name for bundle in bundles.list()}
    for member in bundles.get(root).manifest.members:
        is_skill = member.name in skill_names
        is_bundle = member.name in bundle_names
        if is_skill and is_bundle:
            raise SkillBundleResolutionError(
                SkillBundleRejectionReason.AMBIGUOUS_MEMBER,
                bundle_name=root,
                member_name=member.name,
            )
        if is_bundle:
            reason = (
                SkillBundleRejectionReason.DEPENDENCY_CYCLE
                if _has_cycle(root, bundles=bundles)
                else SkillBundleRejectionReason.NESTED_UNSUPPORTED
            )
            raise SkillBundleResolutionError(
                reason,
                bundle_name=root,
                member_name=member.name,
            )


def _has_cycle(root: str, *, bundles: SkillBundleCatalog) -> bool:
    bundle_names = {bundle.manifest.name for bundle in bundles.list()}

    def visit(name: str, path: frozenset[str]) -> bool:
        if name in path:
            return True
        bundle = bundles.get(name)
        next_path = path | {name}
        return any(
            member.name in bundle_names and visit(member.name, next_path)
            for member in bundle.manifest.members
        )

    return visit(root, frozenset())


def _member_rejection_reason(reason: SkillRejectionReason) -> SkillBundleRejectionReason:
    if reason is SkillRejectionReason.DISABLED:
        return SkillBundleRejectionReason.MEMBER_DISABLED
    if reason in {
        SkillRejectionReason.TRUST_VERIFICATION_FAILED,
        SkillRejectionReason.STORED_ARTIFACT_INVALID,
    }:
        return SkillBundleRejectionReason.MEMBER_TRUST_FAILED
    if reason is SkillRejectionReason.AGENT_NOT_ALLOWED:
        return SkillBundleRejectionReason.AGENT_NOT_ALLOWED
    if reason is SkillRejectionReason.REQUIRED_TOOLS_UNAVAILABLE:
        return SkillBundleRejectionReason.REQUIRED_TOOLS_UNAVAILABLE
    if reason is SkillRejectionReason.BODY_BUDGET_EXCEEDED:
        return SkillBundleRejectionReason.BUDGET_EXCEEDED
    return SkillBundleRejectionReason.MEMBER_MISSING


__all__ = [
    "ResolvedSkillBundle",
    "SkillBundleCatalog",
    "SkillBundleMemberReplay",
    "SkillBundleRejectionReason",
    "SkillBundleReplay",
    "SkillBundleResolutionError",
]
