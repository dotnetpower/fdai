"""Orchestrate deterministic chat-claim verification."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.delivery.read_api.routes.chat_claim_evidence import collect_evidence
from fdai.delivery.read_api.routes.chat_claim_extraction import extract_claims
from fdai.delivery.read_api.routes.chat_claim_manifest import build_evidence_manifest
from fdai.delivery.read_api.routes.chat_claim_matching import verify_claim
from fdai.delivery.read_api.routes.chat_claim_models import ScreenClaimResult


def verify_screen_claims(answer: str, view_context: Mapping[str, Any]) -> ScreenClaimResult:
    """Extract atomic claims and match each against browser snapshot evidence."""

    entries = collect_evidence(view_context)
    drafts, overflow = extract_claims(answer)
    complete = not bool(
        view_context.get("_records_truncated")
        or view_context.get("_snapshot_truncated")
        or view_context.get("_snapshot_unserialisable")
    )
    claims = tuple(
        verify_claim(index, draft, entries, complete=complete)
        for index, draft in enumerate(drafts, start=1)
    )
    manifest = build_evidence_manifest(
        view_context,
        entries,
        claims,
        complete=complete,
    )
    return ScreenClaimResult(claims=claims, manifest=manifest, overflow=overflow)
