"""Build deterministic evidence manifests for verified chat claims."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from fdai.delivery.read_api.routes.chat_claim_models import (
    AtomicClaim,
    EvidenceEntry,
    EvidenceManifest,
)
from fdai.delivery.read_api.routes.chat_claim_text import optional_text


def build_evidence_manifest(
    view_context: Mapping[str, Any],
    entries: tuple[EvidenceEntry, ...],
    claims: tuple[AtomicClaim, ...],
    *,
    complete: bool,
) -> EvidenceManifest:
    used_refs = {ref for claim in claims for ref in claim.evidence_refs}
    used_entries = tuple(entry for entry in entries if entry.ref in used_refs)
    route_id = optional_text(view_context.get("routeId"))
    captured_at = optional_text(view_context.get("capturedAt"))
    authority = evidence_authority(view_context)
    manifest_payload = {
        "schema_version": 1,
        "authority": authority,
        "route_id": route_id,
        "captured_at": captured_at,
        "complete": complete,
        "source_entry_count": len(entries),
        "entries": [entry.to_dict() for entry in used_entries],
    }
    canonical = json.dumps(manifest_payload, sort_keys=True, separators=(",", ":"))
    return EvidenceManifest(
        schema_version=1,
        manifest_id=f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}",
        authority=authority,
        route_id=route_id,
        captured_at=captured_at,
        complete=complete,
        source_entry_count=len(entries),
        entries=used_entries,
    )


def evidence_authority(view_context: Mapping[str, Any]) -> str:
    tool = view_context.get("_tool_evidence")
    if isinstance(tool, Mapping):
        authority = optional_text(tool.get("authority"))
        return authority or "server_read_model"
    web = view_context.get("_web_evidence")
    if isinstance(web, Mapping) and web.get("status") == "matched":
        return "public_web_snapshot"
    if isinstance(view_context.get("_agent_evidence"), Mapping):
        return "pantheon_runtime"
    concept = view_context.get("_concept_evidence")
    if isinstance(concept, Mapping):
        authority = optional_text(concept.get("authority"))
        return authority or "fdai_glossary"
    return "client_snapshot"
