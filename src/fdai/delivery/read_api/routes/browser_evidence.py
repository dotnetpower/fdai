"""Read-only projection of browser evidence artifact metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.delivery.read_api.routes.panels import PanelQueryError
from fdai.shared.providers.browser_evidence import BrowserEvidenceArtifactStore


class BrowserEvidencePanel:
    path = "/browser-evidence"
    name = "browser-evidence"

    def __init__(self, store: BrowserEvidenceArtifactStore) -> None:
        self._store = store

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        try:
            limit = int(params.get("limit", "100"))
        except ValueError as exc:
            raise PanelQueryError("limit MUST be an integer") from exc
        if not 1 <= limit <= 200:
            raise PanelQueryError("limit MUST be in [1, 200]")
        artifacts = await self._store.list_artifacts(limit=limit)
        return {
            "read_only": True,
            "shadow_only": True,
            "count": len(artifacts),
            "artifacts": [
                {
                    "artifact_id": artifact.artifact_id,
                    "policy_id": artifact.policy_id,
                    "policy_version": artifact.policy_version,
                    "canonical_source_url": artifact.canonical_source_url,
                    "canonical_final_url": artifact.canonical_final_url,
                    "captured_at": artifact.captured_at.isoformat(),
                    "expires_at": artifact.expires_at.isoformat(),
                    "selectors": list(artifact.selectors),
                    "screenshot_hash": artifact.screenshot_hash,
                    "text_hash": artifact.text_hash,
                    "snapshot_hash": artifact.snapshot_hash,
                    "redaction_count": sum(
                        entry.replacements for entry in artifact.redaction_manifest
                    ),
                    "prompt_injection_findings": list(artifact.prompt_injection_findings),
                    "browser_version": artifact.browser_version,
                    "chain_of_custody_audit_ref": (artifact.chain_of_custody_audit_ref),
                    "content_digest": artifact.content_digest,
                    "untrusted": artifact.untrusted,
                    "can_authorize_action": artifact.can_authorize_action,
                    "isolation_verified": artifact.isolation.verified,
                }
                for artifact in artifacts
            ],
            "capture_controls": False,
            "promotion_controls": False,
            "mutation_controls": False,
        }


__all__ = ["BrowserEvidencePanel"]
