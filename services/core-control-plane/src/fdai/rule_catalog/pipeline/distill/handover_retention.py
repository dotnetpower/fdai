"""Source-bound private package retention; preserve audit and retry identity."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai_service_contracts import DocumentEnvelope
from fdai_service_contracts.handover_knowledge import HandoverKnowledgeNotice


def retention_descriptor(
    notice: HandoverKnowledgeNotice, envelopes: tuple[DocumentEnvelope, ...]
) -> dict[str, Any]:
    """Retain exact source policy separately from candidate text so scrubbed claims stay fenced."""
    documents = []
    for envelope in envelopes:
        manifest = envelope.artifact_manifest
        if manifest is None:
            raise ValueError("semantic package retention requires the original artifact manifest")
        documents.append(
            {
                "document_id": str(envelope.document_id),
                "version_id": str(envelope.version_id),
                "source_sha256": envelope.source_sha256,
                "access": manifest.access.model_dump(mode="json"),
                "retention": manifest.retention.model_dump(mode="json"),
            }
        )
    if not 1 <= len(documents) <= 4:
        raise ValueError("semantic package retention requires one to four source documents")
    return {
        "source_id": notice.source_id,
        "source_key": notice.source_key,
        "source_revision": notice.goal_revision,
        "source_digest": notice.source_digest,
        "documents": documents,
    }


def retention_decision(
    descriptor: Mapping[str, Any],
    policies: Mapping[str, Any],
    *,
    at: datetime,
    withdrawn: bool,
    retired: bool,
) -> tuple[bool, bool]:
    """Return monotonic retirement and scrub eligibility; unknown legal hold forbids erasure."""
    if at.utcoffset() is None:
        raise ValueError("semantic retention clock must include a timezone")
    documents = descriptor.get("documents")
    current = policies.get("documents")
    if not isinstance(documents, list) or not 1 <= len(documents) <= 4:
        raise ValueError("semantic retention descriptor is unavailable")
    if not isinstance(current, list) or len(current) != len(documents):
        return True, False
    retire = retired or withdrawn or policies.get("source_current") is not True
    can_scrub = True
    for original, row in zip(documents, current, strict=True):
        if not isinstance(row, Mapping) or (
            row.get("document_id") != original["document_id"]
            or row.get("version_id") != original["version_id"]
        ):
            return True, False
        policy = row.get("retention")
        if not isinstance(policy, Mapping):
            retire, can_scrub = True, False
            continue
        can_scrub = can_scrub and policy.get("legal_hold") is False
        if (
            row.get("active") is not True
            or row.get("available") is not True
            or row.get("state") != "ready"
            or row.get("disposition") != "governed_knowledge"
            or row.get("index_state") != "active"
            or row.get("retention_state") != "live"
            or row.get("source_sha256") != original["source_sha256"]
            or row.get("access") != original["access"]
            or not isinstance(row.get("purposes"), list)
            or "manual_distillation" not in row["purposes"]
            or policy.get("policy_version") != original["retention"].get("policy_version")
        ):
            retire = True
        for value in (
            original["retention"].get("derived_expires_at"),
            policy.get("derived_expires_at"),
        ):
            if value is not None:
                try:
                    deadline = datetime.fromisoformat(value)
                    if deadline.utcoffset() is None:
                        raise ValueError("retention time is not timezone-aware")
                except (TypeError, ValueError):
                    return True, False
                retire = retire or at >= deadline
    return retire, retire and can_scrub


__all__ = ["retention_decision", "retention_descriptor"]
