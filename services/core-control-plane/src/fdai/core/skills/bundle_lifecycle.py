"""Audited lifecycle orchestration for immutable governed skill bundles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from fdai.core.skills.bundle_catalog import SkillBundleCatalog
from fdai.core.skills.bundle_manifest import (
    SkillBundleTrustVerifier,
    parse_skill_bundle_manifest,
)
from fdai.core.skills.catalog import SkillCatalog, SkillTrustVerifier


class SkillBundleLifecycleAudit(Protocol):
    async def append(self, event: Mapping[str, Any]) -> None: ...


@dataclass(frozen=True, slots=True)
class SkillBundleLifecycle:
    """Apply one lifecycle transition and append its content-free evidence."""

    audit: SkillBundleLifecycleAudit

    async def install(
        self,
        catalog: SkillBundleCatalog,
        raw_manifest: bytes,
        *,
        verifier: SkillBundleTrustVerifier,
        actor: str,
        reason: str,
        at: datetime,
    ) -> SkillBundleCatalog:
        parsed = parse_skill_bundle_manifest(raw_manifest)
        candidate = catalog.install(raw_manifest, verifier=verifier)
        await self._append(
            "skill_bundle.installed",
            parsed.manifest.name,
            candidate,
            actor=actor,
            reason=reason,
            at=at,
            previous_enabled=None,
        )
        return candidate

    async def enable(
        self,
        catalog: SkillBundleCatalog,
        name: str,
        *,
        skills: SkillCatalog,
        bundle_verifier: SkillBundleTrustVerifier,
        skill_verifier: SkillTrustVerifier,
        available_tools: frozenset[str],
        known_agents: frozenset[str],
        actor: str,
        reason: str,
        at: datetime,
    ) -> SkillBundleCatalog:
        previous = catalog.get(name)
        candidate = catalog.enable(
            name,
            skills=skills,
            bundle_verifier=bundle_verifier,
            skill_verifier=skill_verifier,
            available_tools=available_tools,
            known_agents=known_agents,
        )
        await self._append(
            "skill_bundle.enabled",
            name,
            candidate,
            actor=actor,
            reason=reason,
            at=at,
            previous_enabled=previous.enabled,
        )
        return candidate

    async def disable(
        self,
        catalog: SkillBundleCatalog,
        name: str,
        *,
        actor: str,
        reason: str,
        at: datetime,
    ) -> SkillBundleCatalog:
        previous = catalog.get(name)
        candidate = catalog.disable(name)
        await self._append(
            "skill_bundle.disabled",
            name,
            candidate,
            actor=actor,
            reason=reason,
            at=at,
            previous_enabled=previous.enabled,
        )
        return candidate

    async def uninstall(
        self,
        catalog: SkillBundleCatalog,
        name: str,
        *,
        actor: str,
        reason: str,
        at: datetime,
    ) -> SkillBundleCatalog:
        previous = catalog.get(name)
        candidate = catalog.uninstall(name)
        await self.audit.append(
            {
                "action_kind": "skill_bundle.uninstalled",
                "bundle_name": name,
                "bundle_version": previous.manifest.version,
                "bundle_digest": previous.manifest.digest,
                "previous_enabled": previous.enabled,
                "enabled": None,
                "actor": _required("actor", actor),
                "reason": _required("reason", reason),
                "timestamp": _timestamp(at),
            }
        )
        return candidate

    async def _append(
        self,
        kind: str,
        name: str,
        catalog: SkillBundleCatalog,
        *,
        actor: str,
        reason: str,
        at: datetime,
        previous_enabled: bool | None,
    ) -> None:
        bundle = catalog.get(name)
        await self.audit.append(
            {
                "action_kind": kind,
                "bundle_name": name,
                "bundle_version": bundle.manifest.version,
                "bundle_digest": bundle.manifest.digest,
                "previous_enabled": previous_enabled,
                "enabled": bundle.enabled,
                "actor": _required("actor", actor),
                "reason": _required("reason", reason),
                "timestamp": _timestamp(at),
            }
        )


def _required(label: str, value: str) -> str:
    if not value.strip():
        raise ValueError(f"skill bundle lifecycle {label} MUST be non-empty")
    return value.strip()


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("skill bundle lifecycle timestamp MUST include timezone")
    return value.isoformat()


__all__ = ["SkillBundleLifecycle", "SkillBundleLifecycleAudit"]
