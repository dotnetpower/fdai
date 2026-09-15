"""Current accepted handover sources for inert semantic compilation, with independent ACL reads."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import (
    Callable,
    Mapping,
)
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from fdai_service_contracts import DocumentEnvelope
from fdai_service_contracts.handover_checklist import (
    acceptance_complete,
    project_checklist,
)
from fdai_service_contracts.handover_knowledge import (
    HandoverKnowledgeNotice,
    knowledge_source_digest,
)

from fdai.core.human_assignment.knowledge_source import HandoverKnowledgeSourceCheck
from fdai.delivery.identity.handover_envelopes import HandoverEnvelopeReader
from fdai.delivery.persistence.postgres_core_handover_review import PostgresCoreHandoverReview


@dataclass(frozen=True, slots=True)
class CurrentAcceptedHandoverSources:
    """Admission before content, full normalized lineage, and repeat current-source verification.

    Compiler source access requires the existing manual_distillation purpose. Acceptance alone
    does not authorize extraction, reveal arbitrary documents, or assert current provider truth.
    """

    check: HandoverKnowledgeSourceCheck
    reviewers: PostgresCoreHandoverReview
    envelopes: HandoverEnvelopeReader
    clock: Callable[[], datetime]

    async def read(self, notice: HandoverKnowledgeNotice) -> tuple[DocumentEnvelope, ...]:
        """Return at most four complete admitted envelopes; truncation never proves completeness."""
        async with asyncio.timeout(30):
            initial = await self._accepted(notice)
            evidence = initial["evidence"]
            documents = sorted({(item["evidence_ref"], item["digest"]) for item in evidence})
            if not 1 <= len(documents) <= 4:
                raise ValueError(
                    "semantic source document count is unavailable or exceeds its bound"
                )
            await self._reviewers(notice, initial, documents)
            envelopes: list[DocumentEnvelope] = []
            for reference, digest in documents:
                parts = reference.split(":")
                if len(parts) != 3 or parts[0] != "doc":
                    raise ValueError("semantic source requires an immutable document citation")
                document, version = UUID(parts[1]), UUID(parts[2])
                metadata = await self._metadata(notice, document, version, digest)
                envelope = await self.envelopes.read(document, version)
                _validate_envelope(envelope, metadata, digest, self.clock())
                if await self._metadata(notice, document, version, digest) != metadata:
                    raise ValueError("semantic source admission changed during content read")
                envelopes.append(envelope)
            await self._reviewers(notice, initial, documents)
            if await self._accepted(notice) != initial:
                raise ValueError("semantic source changed during content reads")
            notice.require_current(self.clock())
            return tuple(envelopes)

    async def _accepted(self, notice: HandoverKnowledgeNotice) -> Mapping[str, Any]:
        decision = await self.check.check(notice)
        if decision.disposition != "admitted":
            raise ValueError("semantic source admission is unavailable")
        record = await self.check.reader.read(notice)
        if (
            record is None
            or knowledge_source_digest(record) != notice.source_digest
            or record.get("state") != "accepted"
            or not acceptance_complete(project_checklist(record))
        ):
            raise ValueError("semantic source requires independent exact-goal acceptance")
        return record

    async def _reviewers(
        self,
        notice: HandoverKnowledgeNotice,
        record: Mapping[str, Any],
        documents: list[tuple[str, str]],
    ) -> None:
        subject = record["subject_ref"]
        for field, role in (("owner_review", "owner"), ("backup_review", "backup")):
            review = record.get(field)
            if review is None:
                continue
            reviewer = review["reviewer_ref"]
            if notice.source == "core" or role == "owner":
                eligible = await self.reviewers.may_review(
                    reviewer_ref=reviewer,
                    agent_name=record["agent_name"],
                    scope_ref=record["scope_ref"],
                    role="owner" if role == "owner" else "backup",
                )
            else:
                eligible = await self._operator_backup(record, reviewer)
            if not eligible:
                raise ValueError("semantic source reviewer is no longer eligible")
            for reference, digest in documents:
                if not await self.reviewers.verify(
                    subject_ref=subject,
                    evidence_ref=reference,
                    digest=digest,
                    reviewer_ref=reviewer,
                ):
                    raise ValueError("semantic source reviewer document access is unavailable")

    async def _operator_backup(self, record: Mapping[str, Any], reviewer: str) -> bool:
        if record.get("scope_ref") != "scope:platform":
            return False
        async with await self.reviewers.source._connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT value FROM state_kv WHERE "
                    "key='operator-projection:operations:stewardship.coverage'",
                )
            ).fetchone()
        if row is None or row["value"].get("_revision") != record.get("source_revision"):
            return False
        return any(
            agent.get("name") == record["agent_name"]
            and any(
                steward.get("kind") == "user"
                and steward.get("id") == reviewer
                and steward.get("responsibility") == "accountable"
                and steward.get("duty") in {"backup", "escalation"}
                for steward in agent.get("stewards", [])
            )
            for agent in row["value"].get("map", {}).get("agents", [])
        )

    async def _metadata(
        self,
        notice: HandoverKnowledgeNotice,
        document: UUID,
        version: UUID,
        digest: str,
    ) -> Mapping[str, Any]:
        async with await self.reviewers.source._connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT fdai_core_handover_source_metadata(%s,%s,%s,%s,%s) AS metadata",
                    (notice.source_key, notice.goal_revision, document, version, digest),
                )
            ).fetchone()
        if row is None or not isinstance(row["metadata"], Mapping):
            raise ValueError("semantic source purpose or current metadata is unavailable")
        return dict(row["metadata"])


def _validate_envelope(
    envelope: DocumentEnvelope,
    metadata: Mapping[str, Any],
    digest: str,
    at: datetime,
) -> None:
    manifest = envelope.artifact_manifest
    if (
        envelope.source_sha256 != digest
        or manifest is None
        or "manual_distillation" not in envelope.purposes
        or "manual_distillation" not in metadata.get("purposes", [])
        or envelope.access_descriptor_ref != metadata.get("access", {}).get("reference")
        or envelope.collection_id != metadata.get("access", {}).get("collection_id")
        or envelope.protection_state.value != metadata.get("protection_state")
        or manifest.access.model_dump(mode="json") != metadata.get("access")
        or manifest.retention.model_dump(mode="json") != metadata.get("retention")
    ):
        raise ValueError(
            "semantic envelope does not match admitted purpose, identity, access, or retention"
        )
    normalized = json.dumps(
        envelope.model_dump(mode="json", exclude={"artifact_manifest"}),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    entries = [entry for entry in manifest.entries if entry.kind.value == "normalized_envelope"]
    if (
        len(entries) != 1
        or not entries[0].retained
        or entries[0].content_sha256 != hashlib.sha256(normalized).hexdigest()
        or entries[0].size_bytes != len(normalized)
        or (entries[0].expires_at is not None and at >= entries[0].expires_at)
        or (
            manifest.retention.derived_expires_at is not None
            and at >= manifest.retention.derived_expires_at
        )
    ):
        raise ValueError("semantic normalized envelope commitment or retained window is invalid")


__all__ = ["CurrentAcceptedHandoverSources"]
