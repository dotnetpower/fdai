"""Thread-safe, read-only runtime projection for trusted skills."""

from __future__ import annotations

import base64
import builtins
import hashlib
from collections import deque
from dataclasses import asdict, dataclass
from enum import StrEnum
from threading import Lock
from typing import Any, Final

from fdai.core.skills.bundle_catalog import (
    ResolvedSkillBundle,
    SkillBundleCatalog,
    SkillBundleResolutionError,
)
from fdai.core.skills.bundle_manifest import SkillBundleTrustVerifier
from fdai.core.skills.catalog import SkillCatalog, SkillTrustVerifier
from fdai.core.skills.disclosure import (
    SkillAccessError,
    SkillDescriptorResult,
    SkillIndexResult,
    SkillLoadResult,
    SkillReferenceResult,
    SkillReplayMetadata,
)

_MAX_INDEX_CHARS = 32 * 1024
_MAX_BODY_CHARS = 64 * 1024
_MAX_REFERENCE_BYTES = 256 * 1024
_MAX_DIAGNOSTICS = 100


@dataclass(frozen=True, slots=True)
class RuntimeSkillDiagnostic:
    operation: str
    name: str | None
    reference: str | None
    status: str
    reason: str
    digests: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "name": self.name,
            "reference": self.reference,
            "status": self.status,
            "reason": self.reason,
            "digests": dict(self.digests),
        }


class RuntimeSkillDisclosure:
    """Expose a fixed skill catalog without changing runtime eligibility."""

    def __init__(
        self,
        *,
        catalog: SkillCatalog,
        verifier: SkillTrustVerifier,
        agent: str,
        available_tools: frozenset[str],
        index_budget_chars: int = 8_192,
        body_budget_chars: int = 32_768,
        reference_budget_bytes: int = 64 * 1024,
        diagnostics_limit: int = _MAX_DIAGNOSTICS,
        bundle_catalog: SkillBundleCatalog | None = None,
        bundle_verifier: SkillBundleTrustVerifier | None = None,
        known_agents: frozenset[str] | None = None,
    ) -> None:
        if not agent.strip():
            raise ValueError("runtime skill agent MUST be non-empty")
        _require_budget("index", index_budget_chars, _MAX_INDEX_CHARS)
        _require_budget("body", body_budget_chars, _MAX_BODY_CHARS)
        _require_budget("reference", reference_budget_bytes, _MAX_REFERENCE_BYTES)
        if not 1 <= diagnostics_limit <= _MAX_DIAGNOSTICS:
            raise ValueError("runtime skill diagnostics limit MUST be in [1, 100]")
        if (bundle_catalog is None) != (bundle_verifier is None):
            raise ValueError("runtime bundle catalog and verifier MUST be provided together")
        self._snapshot = (catalog, verifier)
        self._snapshot_lock = Lock()
        self._bundle_snapshot = (bundle_catalog, bundle_verifier)
        self._bundle_snapshot_lock = Lock()
        self._agent: Final = agent
        self._known_agents: Final = known_agents or frozenset({agent})
        self._available_tools: Final = frozenset(available_tools)
        self._index_budget_chars: Final = index_budget_chars
        self._body_budget_chars: Final = body_budget_chars
        self._reference_budget_bytes: Final = reference_budget_bytes
        self._diagnostics: deque[RuntimeSkillDiagnostic] = deque(maxlen=diagnostics_limit)
        self._diagnostics_lock = Lock()

    def list(self, *, query: str, limit: int = 20) -> dict[str, Any]:
        if not 1 <= limit <= 50:
            self._record_rejection("list", None, None, "invalid_limit", None)
            raise ValueError("skill list limit MUST be in [1, 50]")
        catalog, _verifier = self._current_snapshot()
        try:
            result = catalog.list_skills(
                query=query,
                agent=self._agent,
                available_tools=self._available_tools,
                max_chars=self._index_budget_chars,
            )
        except SkillAccessError as exc:
            self._record_access_error("list", None, None, exc)
            raise
        entries = result.entries[:limit]
        for entry in entries:
            self._record_selected(
                "list",
                entry.descriptor.name,
                None,
                reason="skill_selected",
                replay=None,
                catalog=catalog,
            )
        payload = _payload(result)
        payload["entries"] = payload["entries"][:limit]
        payload["returned_count"] = len(entries)
        return payload

    def describe(self, name: str) -> dict[str, Any]:
        catalog, _verifier = self._current_snapshot()
        try:
            result = catalog.describe_skill(name)
        except SkillAccessError as exc:
            self._record_access_error("describe", name, None, exc)
            raise
        self._record_result("describe", name, None, result)
        return _payload(result)

    def load(self, name: str) -> dict[str, Any]:
        catalog, verifier = self._current_snapshot()
        try:
            result = catalog.load_skill(
                name,
                agent=self._agent,
                available_tools=self._available_tools,
                verifier=verifier,
                max_chars=self._body_budget_chars,
            )
        except SkillAccessError as exc:
            self._record_access_error("load", name, None, exc)
            raise
        self._record_result("load", name, None, result)
        return _payload(result)

    def read_reference(self, name: str, path: str) -> dict[str, Any]:
        catalog, verifier = self._current_snapshot()
        try:
            result = catalog.read_skill_reference(
                name,
                path,
                agent=self._agent,
                available_tools=self._available_tools,
                verifier=verifier,
                max_bytes=self._reference_budget_bytes,
            )
        except SkillAccessError as exc:
            self._record_access_error("read_reference", name, path, exc)
            raise
        self._record_result("read_reference", name, path, result)
        payload = _payload(result)
        payload["content"] = _encoded_reference(result)
        return payload

    def diagnostics(self) -> tuple[dict[str, Any], ...]:
        with self._diagnostics_lock:
            return tuple(item.to_dict() for item in self._diagnostics)

    def list_bundles(self, *, query: str, limit: int = 20) -> dict[str, Any]:
        if not 1 <= limit <= 50:
            raise ValueError("skill bundle list limit MUST be in [1, 50]")
        bundle_catalog, _bundle_verifier = self._current_bundle_snapshot()
        if bundle_catalog is None:
            return {"bundles": [], "returned_count": 0}
        normalized = query.strip().casefold()
        bundles = [
            item
            for item in self._inspect_bundles(bundle_catalog)
            if not normalized or _bundle_matches(item, normalized)
        ][:limit]
        return {"bundles": bundles, "returned_count": len(bundles)}

    def describe_bundle(self, name: str) -> dict[str, Any]:
        bundle_catalog, _bundle_verifier = self._current_bundle_snapshot()
        if bundle_catalog is None:
            raise ValueError("runtime skill bundle catalog is unavailable")
        bundle = bundle_catalog.get(name)
        item = next(
            value for value in self._inspect_bundles(bundle_catalog) if value["name"] == name
        )
        self._append(
            RuntimeSkillDiagnostic(
                operation="describe_bundle",
                name=name,
                reference=None,
                status="selected",
                reason="skill_bundle_described",
                digests=(("bundle_digest", bundle.manifest.digest),),
            )
        )
        return {"bundle": item}

    def load_bundle(self, name: str) -> dict[str, Any]:
        bundle_catalog, bundle_verifier = self._current_bundle_snapshot()
        if bundle_catalog is None or bundle_verifier is None:
            raise ValueError("runtime skill bundle catalog is unavailable")
        skill_catalog, skill_verifier = self._current_snapshot()
        try:
            resolved = bundle_catalog.resolve(
                name,
                skills=skill_catalog,
                bundle_verifier=bundle_verifier,
                skill_verifier=skill_verifier,
                agent=self._agent,
                available_tools=self._available_tools,
                known_agents=self._known_agents,
                max_chars=self._body_budget_chars,
            )
        except SkillBundleResolutionError as exc:
            self._append(
                RuntimeSkillDiagnostic(
                    operation="load_bundle",
                    name=name,
                    reference=None,
                    status="rejected",
                    reason=exc.reason.value,
                    digests=(),
                )
            )
            raise
        self._record_bundle_load(resolved)
        return _bundle_payload(resolved)

    def inspect(self) -> dict[str, Any]:
        """Return installed metadata and current eligibility without artifact content."""
        catalog, _verifier = self._current_snapshot()
        skills = []
        for skill in catalog.list():
            manifest = skill.manifest
            missing_tools = tuple(sorted(set(manifest.required_tools) - self._available_tools))
            agent_eligible = not manifest.allowed_agents or self._agent in manifest.allowed_agents
            eligible = skill.enabled and agent_eligible and not missing_tools
            skills.append(
                {
                    "name": manifest.name,
                    "version": manifest.version,
                    "description": manifest.description,
                    "source": manifest.source,
                    "enabled": skill.enabled,
                    "required_tools": list(manifest.required_tools),
                    "missing_tools": list(missing_tools),
                    "allowed_agents": list(manifest.allowed_agents),
                    "agent_eligible": agent_eligible,
                    "eligible": eligible,
                    "eligibility_reason": _eligibility_reason(
                        enabled=skill.enabled,
                        agent_eligible=agent_eligible,
                        missing_tools=missing_tools,
                    ),
                    "body_sha256": manifest.body_sha256,
                    "references": [
                        {
                            "path": reference.path,
                            "sha256": reference.sha256,
                            "size_bytes": reference.size_bytes,
                            "media_type": reference.media_type,
                        }
                        for reference in manifest.references
                    ],
                }
            )
        bundle_catalog, _bundle_verifier = self._current_bundle_snapshot()
        bundles = self._inspect_bundles(bundle_catalog) if bundle_catalog is not None else []
        return {
            "agent": self._agent,
            "available_tools": sorted(self._available_tools),
            "installed_count": len(skills),
            "eligible_count": sum(bool(skill["eligible"]) for skill in skills),
            "skills": skills,
            "installed_bundle_count": len(bundles),
            "eligible_bundle_count": sum(bool(bundle["eligible"]) for bundle in bundles),
            "bundles": bundles,
            "diagnostics": list(self.diagnostics()),
            "mutation_controls": False,
        }

    def publish_snapshot(
        self,
        *,
        catalog: SkillCatalog,
        verifier: SkillTrustVerifier,
    ) -> None:
        """Atomically publish a startup-verified catalog and verifier pair."""
        with self._snapshot_lock:
            self._snapshot = (catalog, verifier)

    def publish_bundle_snapshot(
        self,
        *,
        catalog: SkillBundleCatalog,
        verifier: SkillBundleTrustVerifier,
    ) -> None:
        """Atomically publish a startup-verified governed bundle snapshot."""
        with self._bundle_snapshot_lock:
            self._bundle_snapshot = (catalog, verifier)

    def _current_snapshot(self) -> tuple[SkillCatalog, SkillTrustVerifier]:
        with self._snapshot_lock:
            return self._snapshot

    def _current_bundle_snapshot(
        self,
    ) -> tuple[SkillBundleCatalog | None, SkillBundleTrustVerifier | None]:
        with self._bundle_snapshot_lock:
            return self._bundle_snapshot

    def _inspect_bundles(self, catalog: SkillBundleCatalog) -> builtins.list[dict[str, Any]]:
        skill_catalog, _skill_verifier = self._current_snapshot()
        skill_by_name = {skill.manifest.name: skill for skill in skill_catalog.list()}
        items: builtins.list[dict[str, Any]] = []
        for bundle in catalog.list():
            manifest = bundle.manifest
            missing = tuple(
                member.name for member in manifest.members if member.name not in skill_by_name
            )
            incompatible = tuple(
                member.name
                for member in manifest.members
                if member.name in skill_by_name
                and skill_by_name[member.name].manifest.version != member.exact_version
            )
            disabled = tuple(
                member.name
                for member in manifest.members
                if member.name in skill_by_name and not skill_by_name[member.name].enabled
            )
            missing_tools = tuple(sorted(set(manifest.required_tools) - self._available_tools))
            agent_eligible = not manifest.allowed_agents or self._agent in manifest.allowed_agents
            compatible = not missing and not incompatible and not disabled
            items.append(
                {
                    "name": manifest.name,
                    "version": manifest.version,
                    "description": manifest.description,
                    "source": manifest.source,
                    "digest": manifest.digest,
                    "enabled": bundle.enabled,
                    "members": [
                        {"name": member.name, "version": member.version}
                        for member in manifest.members
                    ],
                    "required_tools": list(manifest.required_tools),
                    "missing_tools": list(missing_tools),
                    "allowed_agents": list(manifest.allowed_agents),
                    "agent_eligible": agent_eligible,
                    "compatible": compatible,
                    "missing_members": list(missing),
                    "disabled_members": list(disabled),
                    "incompatible_members": list(incompatible),
                    "trust_status": "rechecked_on_load",
                    "eligible": (
                        bundle.enabled and compatible and not missing_tools and agent_eligible
                    ),
                }
            )
        return items

    def _record_bundle_load(self, bundle: ResolvedSkillBundle) -> None:
        digests = [("bundle_digest", bundle.replay.digest)]
        digests.extend(
            (f"member:{member.name}", member.body_sha256) for member in bundle.replay.members
        )
        self._append(
            RuntimeSkillDiagnostic(
                operation="load_bundle",
                name=bundle.manifest.name,
                reference=None,
                status="selected",
                reason="skill_bundle_loaded",
                digests=tuple(digests),
            )
        )

    def _record_result(
        self,
        operation: str,
        name: str,
        reference: str | None,
        result: SkillDescriptorResult | SkillLoadResult | SkillReferenceResult,
    ) -> None:
        self._record_selected(
            operation,
            name,
            reference,
            reason=result.diagnostics[0].code,
            replay=result.replay,
        )

    def _record_selected(
        self,
        operation: str,
        name: str,
        reference: str | None,
        *,
        reason: str,
        replay: SkillReplayMetadata | None,
        catalog: SkillCatalog | None = None,
    ) -> None:
        digests = _replay_digests(replay)
        if replay is None:
            selected_catalog = catalog or self._current_snapshot()[0]
            skill = selected_catalog.get(name)
            digests = (
                ("body_sha256", skill.manifest.body_sha256),
                ("raw_markdown_sha256", hashlib.sha256(skill.raw_markdown).hexdigest()),
            )
        self._append(
            RuntimeSkillDiagnostic(
                operation=operation,
                name=name,
                reference=reference,
                status="selected",
                reason=reason,
                digests=digests,
            )
        )

    def _record_access_error(
        self,
        operation: str,
        name: str | None,
        reference: str | None,
        error: SkillAccessError,
    ) -> None:
        self._record_rejection(operation, name, reference, error.reason.value, error.replay)

    def _record_rejection(
        self,
        operation: str,
        name: str | None,
        reference: str | None,
        reason: str,
        replay: SkillReplayMetadata | None,
    ) -> None:
        self._append(
            RuntimeSkillDiagnostic(
                operation=operation,
                name=name,
                reference=reference,
                status="rejected",
                reason=reason,
                digests=_replay_digests(replay),
            )
        )

    def _append(self, diagnostic: RuntimeSkillDiagnostic) -> None:
        with self._diagnostics_lock:
            self._diagnostics.append(diagnostic)


def _require_budget(label: str, value: int, maximum: int) -> None:
    if not 1 <= value <= maximum:
        raise ValueError(f"runtime skill {label} budget MUST be in [1, {maximum}]")


def _eligibility_reason(
    *,
    enabled: bool,
    agent_eligible: bool,
    missing_tools: tuple[str, ...],
) -> str:
    if not enabled:
        return "skill_disabled"
    if not agent_eligible:
        return "skill_agent_not_allowed"
    if missing_tools:
        return "skill_required_tools_unavailable"
    return "eligible_pending_trust_recheck"


def _payload(
    result: SkillIndexResult | SkillDescriptorResult | SkillLoadResult | SkillReferenceResult,
) -> dict[str, Any]:
    payload = _json_safe(asdict(result))
    if not isinstance(payload, dict):  # pragma: no cover - dataclass guard
        raise TypeError("runtime skill result MUST serialize to an object")
    return payload


def _json_safe(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _encoded_reference(result: SkillReferenceResult) -> dict[str, str]:
    try:
        data = result.content.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        data = base64.b64encode(result.content).decode("ascii")
        encoding = "base64"
    return {
        "data": data,
        "encoding": encoding,
        "media_type": result.reference.media_type,
        "sha256": result.reference.sha256,
    }


def _replay_digests(replay: SkillReplayMetadata | None) -> tuple[tuple[str, str], ...]:
    if replay is None:
        return ()
    digests = [
        ("body_sha256", replay.body_sha256),
        ("raw_markdown_sha256", replay.raw_markdown_sha256),
    ]
    digests.extend(
        (f"reference:{reference.path}", reference.sha256) for reference in replay.references
    )
    return tuple(digests)


def _bundle_payload(bundle: ResolvedSkillBundle) -> dict[str, Any]:
    return {
        "name": bundle.manifest.name,
        "version": bundle.manifest.version,
        "digest": bundle.manifest.digest,
        "instruction": bundle.instruction,
        "members": [
            {
                "name": member.descriptor.name,
                "version": member.descriptor.version,
                "body": member.body,
                "body_sha256": member.replay.body_sha256,
                "raw_markdown_sha256": member.replay.raw_markdown_sha256,
            }
            for member in bundle.members
        ],
        "manifest_sha256": bundle.replay.manifest_sha256,
    }


def _bundle_matches(item: dict[str, Any], normalized: str) -> bool:
    required_tools = item.get("required_tools")
    tools = (
        " ".join(str(value) for value in required_tools)
        if isinstance(required_tools, builtins.list)
        else ""
    )
    return normalized in f"{item.get('name', '')} {item.get('description', '')} {tools}".casefold()


__all__ = ["RuntimeSkillDiagnostic", "RuntimeSkillDisclosure"]
