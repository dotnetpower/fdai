"""Atomic approved-intent read-model persistence over current API-owned document metadata."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from fdai_service_contracts import DocumentEnvelope, DocumentVersion
from fdai_service_contracts.ontology_query import content_digest

from fdai.agents import approval_state_key
from fdai.core.ontology_platform.document_intent import (
    DocumentIntentDiff,
    DocumentIntentEvent,
    IntentServiceProperties,
)
from fdai.delivery.identity.handover_review_identity import HandoverIdentityReader
from fdai.delivery.identity.handover_semantic_sources import _validate_envelope
from fdai.delivery.persistence.postgres_ontology import PostgresOntologyInstanceStore
from fdai.delivery.persistence.postgres_ontology_records import _require_type_ref
from fdai.shared.providers.ontology_instance import (
    OntologyObjectRecord,
    canonical_json_mapping,
    normalize_object_record,
    pin_object_record,
    validate_object_record,
)


@dataclass(frozen=True, slots=True)
class PostgresDocumentIntent:
    """Core-private provenance plus the existing graph, never an alternative source registry."""

    graph: PostgresOntologyInstanceStore
    identities: HandoverIdentityReader
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def staged_envelope(self, document: UUID, version: UUID) -> DocumentEnvelope | None:
        """Read one worker-owned normalized envelope through its restricted function."""
        async with await self.graph._connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT fdai_document_intent_envelope(%s,%s) AS envelope",
                    (document, version),
                )
            ).fetchone()
        raw = row["envelope"] if row else None
        return DocumentEnvelope.model_validate(raw) if isinstance(raw, Mapping) else None

    async def current_target_revision(self, envelope: DocumentEnvelope) -> int:
        """Return the exact private target revision for deterministic add/update compilation."""
        properties = self.intent_properties(envelope)
        async with await self.graph._connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT revision FROM document_intent_resource WHERE id=%s",
                    (properties.id,),
                )
            ).fetchone()
        return int(row["revision"]) if row is not None else 0

    async def current_source_digests(self, document: UUID, version: UUID) -> tuple[str, ...]:
        async with await self.graph._connect() as connection:
            rows = await (
                await connection.execute(
                    "SELECT digest FROM document_intent_projection "
                    "WHERE document_id=%s AND version_id=%s "
                    "AND status IN ('applied','restored') ORDER BY digest LIMIT 65",
                    (document, version),
                )
            ).fetchall()
        if len(rows) > 64:
            raise ValueError("document intent source withdrawal exceeds its bound")
        return tuple(str(row["digest"]) for row in rows)

    @staticmethod
    def intent_properties(envelope: DocumentEnvelope) -> IntentServiceProperties:
        if len(envelope.units) != 1 or envelope.artifact_manifest is None:
            raise ValueError("intent source requires one explicit normalized unit and manifest")
        typed = json.loads(envelope.units[0].text)
        if (
            not isinstance(typed, dict)
            or set(typed) != {"kind", "properties"}
            or typed["kind"] != "fdai.declared-intent.business-service.v1"
        ):
            raise ValueError("source is not an explicit typed BusinessService intent document")
        return IntentServiceProperties.model_validate(typed["properties"])

    async def source(
        self, connection: psycopg.AsyncConnection[Any], document: UUID, version: UUID
    ) -> DocumentVersion:
        row = await (
            await connection.execute(
                "SELECT fdai_document_intent_source(%s,%s) AS source", (document, version)
            )
        ).fetchone()
        raw = row["source"] if row else None
        if not isinstance(raw, Mapping):
            raise PermissionError("current document intent source is unavailable")
        source = DocumentVersion.model_validate(
            {key: value for key, value in raw.items() if not key.startswith("_row_")}
        )
        if (
            raw["_row_revision"] != source.revision
            or raw["_row_state"] != source.state.value
            or raw["_row_active"] is not True
            or not source.active
            or not source.available
            or source.state.value not in {"ready", "ready_with_warnings"}
            or source.disposition.value != "governed_knowledge"
            or source.index_state.value != "active"
            or source.retention_state.value != "live"
            or source.protection_state.value != "none"
            or "manual_distillation" not in source.purposes
            or any(
                expiry is not None and expiry <= self.clock()
                for expiry in (
                    source.retention.source_expires_at,
                    source.retention.derived_expires_at,
                )
            )
        ):
            raise PermissionError("document intent requires a current governed admitted source")
        return source

    @staticmethod
    def check_access(source: DocumentVersion, principal: str, groups: tuple[str, ...]) -> None:
        if principal != source.uploader_id and not set(groups).intersection(
            source.access.reader_groups
        ):
            raise PermissionError("current source access is denied")

    async def prepare(
        self,
        envelope: DocumentEnvelope,
        *,
        requester_ref: str,
        scope_ref: str,
        operation: str,
        expected_revision: int,
    ) -> str:
        """Compile one explicit machine-authored intent unit, not natural-language meaning."""
        properties = self.intent_properties(envelope)
        manifest = envelope.artifact_manifest
        if manifest is None:
            raise ValueError("intent source requires an artifact manifest")
        human = await self.identities.read(requester_ref)
        if human is None or human.subject_ref != requester_ref or not human.current(self.clock()):
            raise PermissionError("current authenticated intent requester is unavailable")
        async with await self.graph._connect() as connection:
            await self.graph._set_timeout(connection)
            source = await self.source(connection, envelope.document_id, envelope.version_id)
            self.check_access(source, requester_ref, human.group_ids)
            if (
                source.scope_ref != scope_ref
                or source.source_sha256 != envelope.source_sha256
                or source.access != manifest.access
                or source.retention != manifest.retention
                or envelope.collection_id != source.access.collection_id
                or envelope.access_descriptor_ref != source.access.reference
                or envelope.purposes != source.purposes
            ):
                raise PermissionError("intent envelope does not match current governed source")
            _validate_envelope(
                envelope,
                {
                    "purposes": list(source.purposes),
                    "access": source.access.model_dump(mode="json"),
                    "retention": source.retention.model_dump(mode="json"),
                    "protection_state": source.protection_state.value,
                },
                source.source_sha256,
                self.clock(),
            )
            diff = DocumentIntentDiff.model_validate(
                {
                    "operation": operation,
                    "document_id": source.document_id,
                    "version_id": source.version_id,
                    "source_revision": source.revision,
                    "source_digest": "sha256:" + source.source_sha256,
                    "envelope_digest": content_digest(envelope.model_dump(mode="json")),
                    "acl_digest": content_digest(source.access.model_dump(mode="json")),
                    "ontology_release": self.graph._release.digest,
                    "expected_revision": expected_revision,
                    "scope_ref": scope_ref,
                    "requester_ref": requester_ref,
                    "properties": properties.model_dump(mode="json"),
                }
            )
            record = self.record(diff)
            validate_object_record(record, self.graph._object_types)
            await self.recheck(connection, diff)
            await connection.execute(
                "INSERT INTO document_intent_projection"
                "(digest,diff,envelope,document_id,version_id,target_id) "
                "VALUES (%s,%s::jsonb,%s::jsonb,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    diff.digest,
                    diff.model_dump_json(),
                    envelope.model_dump_json(),
                    source.document_id,
                    source.version_id,
                    properties.id,
                ),
            )
        return diff.digest

    def record(self, diff: DocumentIntentDiff) -> OntologyObjectRecord:
        properties = diff.properties.model_dump(mode="json", exclude_none=True)
        return normalize_object_record(
            pin_object_record(
                OntologyObjectRecord(
                    id=diff.properties.id, object_type="BusinessService", properties=properties
                ),
                self.graph._release,
            )
        )

    async def packet(
        self, connection: psycopg.AsyncConnection[Any], digest: str, *, lock: bool = False
    ) -> Mapping[str, Any]:
        statement = (
            "SELECT * FROM document_intent_projection WHERE digest=%s FOR UPDATE"
            if lock
            else "SELECT * FROM document_intent_projection WHERE digest=%s"
        )
        cursor = await connection.execute(statement, (digest,))
        row = await cursor.fetchone()
        if row is None:
            raise ValueError("document intent packet is unavailable")
        if DocumentIntentDiff.model_validate(row["diff"]).digest != digest:
            raise ValueError("document intent packet content changed")
        return dict(row)

    async def recheck(
        self, connection: psycopg.AsyncConnection[Any], diff: DocumentIntentDiff
    ) -> DocumentVersion:
        source = await self.source(connection, diff.document_id, diff.version_id)
        if (
            source.revision != diff.source_revision
            or "sha256:" + source.source_sha256 != diff.source_digest
            or content_digest(source.access.model_dump(mode="json")) != diff.acl_digest
            or source.scope_ref != diff.scope_ref
            or diff.ontology_release != self.graph._release.digest
            or diff.properties.effective_from > self.clock()
            or (
                diff.properties.effective_to is not None
                and diff.properties.effective_to <= self.clock()
            )
        ):
            raise PermissionError("document source, release, ACL or effective interval changed")
        return source

    async def transition(self, digest: str, phase: str, receipt: Mapping[str, Any]) -> None:
        async with await self.graph._connect() as connection:
            await connection.execute(
                "INSERT INTO document_intent_transition(digest,phase,correlation_id,receipt) "
                "VALUES (%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING",
                (
                    digest,
                    phase,
                    receipt["correlation_id"],
                    json.dumps(dict(receipt), sort_keys=True),
                ),
            )
            current = await (
                await connection.execute(
                    "SELECT receipt FROM document_intent_transition "
                    "WHERE digest=%s AND phase=%s AND correlation_id=%s",
                    (digest, phase, receipt["correlation_id"]),
                )
            ).fetchone()
            if current is None or current["receipt"] != dict(receipt):
                raise ValueError("document intent transition replay conflicts")

    async def review(self, digest: str) -> DocumentIntentDiff:
        async with await self.graph._connect() as connection:
            packet = await self.packet(connection, digest)
            diff = DocumentIntentDiff.model_validate(packet["diff"])
            await self.recheck(connection, diff)
            envelope = DocumentEnvelope.model_validate(packet["envelope"])
            if content_digest(envelope.model_dump(mode="json")) != diff.envelope_digest:
                raise ValueError("document intent envelope commitment changed")
            data = json.loads(envelope.units[0].text)
            if IntentServiceProperties.model_validate(data["properties"]) != diff.properties:
                raise ValueError("document intent does not match its exact typed source")
            validate_object_record(self.record(diff), self.graph._object_types)
            return diff

    async def authorize_review(self, reviewer: str, digest: str) -> bool:
        human = await self.identities.read(reviewer)
        if (
            human is None
            or human.subject_ref != reviewer
            or not human.current(self.clock())
            or not set(human.roles).intersection({"Approver", "Owner"})
        ):
            return False
        try:
            diff = await self.review(digest)
            async with await self.graph._connect() as connection:
                source = await self.recheck(connection, diff)
                if reviewer.casefold() in {
                    diff.requester_ref.casefold(),
                    source.uploader_id.casefold(),
                }:
                    return False
                self.check_access(source, reviewer, human.group_ids)
            return human.current(self.clock())
        except (PermissionError, ValueError):
            return False

    async def apply(self, digest: str, correlation: str) -> DocumentIntentEvent:
        """Source, exact approval, provenance and target CAS share one graph transaction."""
        async with await self.graph._connect() as connection:
            await self.graph._set_timeout(connection)
            await connection.execute("SELECT pg_advisory_xact_lock(%s)", (8_419_450_268,))
            packet = await self.packet(connection, digest, lock=True)
            diff = DocumentIntentDiff.model_validate(packet["diff"])
            source = await self.recheck(connection, diff)
            approval_key = approval_state_key(correlation, "final", None)
            row = await (
                await connection.execute(
                    "SELECT value FROM state_kv WHERE key=%s FOR SHARE", (approval_key,)
                )
            ).fetchone()
            approval = row["value"].get("approval", {}) if row else {}
            if (
                approval.get("producer_principal") != "Var"
                or approval.get("kind") != "document_intent_projection"
                or approval.get("state") != "approved"
                or approval.get("params") != {"intent_digest": digest}
                or approval.get("correlation_id") != correlation
                or approval.get("action_type") != "document.review-intent-diff"
                or approval.get("resource_id") != "document-intent:" + digest[7:]
                or approval.get("action_run_identity") is not None
                or len(approval.get("approvers", [])) != 1
                or source.uploader_id in approval["approvers"]
            ):
                raise PermissionError("exact independent document intent approval is unavailable")
            for reviewer in approval["approvers"]:
                human = await self.identities.read(reviewer)
                if (
                    human is None
                    or human.subject_ref != reviewer
                    or not human.current(self.clock())
                    or not set(human.roles).intersection({"Approver", "Owner"})
                    or reviewer.casefold()
                    in {diff.requester_ref.casefold(), source.uploader_id.casefold()}
                ):
                    raise PermissionError("intent approval reviewer is not currently eligible")
                self.check_access(source, reviewer, human.group_ids)
            sealed = await (
                await connection.execute(
                    "SELECT receipt FROM document_intent_transition "
                    "WHERE digest=%s AND phase='approved_sealed' AND correlation_id=%s",
                    (digest, correlation),
                )
            ).fetchone()
            if sealed is None:
                raise PermissionError("Saga approval audit is required before projection")
            required = await (
                await connection.execute(
                    "SELECT phase,receipt FROM document_intent_transition "
                    "WHERE digest=%s AND correlation_id=%s "
                    "AND phase=ANY(%s::text[])",
                    (
                        digest,
                        correlation,
                        ["candidate", "reviewed", "verdict", "verdict_sealed"],
                    ),
                )
            ).fetchall()
            if len(required) != 4 or any(
                DocumentIntentEvent.model_validate(row["receipt"]).outcome != "pending"
                for row in required
            ):
                raise PermissionError(
                    "independent reviewed and audited intent judgment is required"
                )
            if packet["status"] == "applied":
                return DocumentIntentEvent.create(
                    "applied",
                    digest,
                    correlation,
                    applied_revision=int(packet["applied_revision"]),
                )
            if packet["status"] != "candidate":
                raise PermissionError("retired document intent cannot be replayed")
            target = await (
                await connection.execute(
                    "SELECT * FROM document_intent_resource WHERE id=%s FOR UPDATE",
                    (diff.properties.id,),
                )
            ).fetchone()
            if (target is None and diff.expected_revision != 0) or (
                target is not None and target["revision"] != diff.expected_revision
            ):
                raise ValueError("document intent target revision changed")
            if target is not None:
                owner = await (
                    await connection.execute(
                        "SELECT document_id FROM document_intent_projection "
                        "WHERE target_id=%s AND status IN ('applied','restored') "
                        "AND applied_revision=%s",
                        (diff.properties.id, diff.expected_revision),
                    )
                ).fetchone()
                if owner is None or owner["document_id"] != diff.document_id:
                    raise PermissionError("document intent conflicts with another source owner")
            record = self.record(diff)
            reference = _require_type_ref(record.type_ref)
            properties = canonical_json_mapping(record.properties, path="intent.properties")[1]
            revision = diff.expected_revision + 1
            await connection.execute(
                "INSERT INTO document_intent_resource"
                "(id,object_type,properties,revision,type_version,catalog_digest) "
                "VALUES (%s,'BusinessService',%s::jsonb,%s,%s,%s) "
                "ON CONFLICT(id) DO UPDATE SET properties=EXCLUDED.properties,"
                "revision=EXCLUDED.revision,type_version=EXCLUDED.type_version,"
                "catalog_digest=EXCLUDED.catalog_digest",
                (
                    record.id,
                    properties,
                    revision,
                    reference.version,
                    reference.catalog_digest,
                ),
            )
            before = (
                None
                if target is None
                else {key: value for key, value in target.items() if key != "updated_at"}
            )
            await connection.execute(
                "UPDATE document_intent_projection SET status='superseded' "
                "WHERE target_id=%s AND status IN ('applied','restored')",
                (record.id,),
            )
            await connection.execute(
                "UPDATE document_intent_projection SET status='applied',"
                "before_image=%s::jsonb,applied_revision=%s,approval_key=%s WHERE digest=%s",
                (json.dumps(before), revision, approval_key, digest),
            )
            event = DocumentIntentEvent.create(
                "applied", digest, correlation, applied_revision=revision
            )
            await connection.execute(
                "INSERT INTO document_intent_transition(digest,phase,correlation_id,receipt) "
                "VALUES (%s,'applied',%s,%s::jsonb)",
                (digest, correlation, event.model_dump_json()),
            )
        return event

    async def observe(self, event: DocumentIntentEvent) -> DocumentIntentEvent:
        """Use independent committed reads, not the writer's API result or connection."""
        matched = False
        try:
            async with await self.graph._connect() as connection:
                packet = await self.packet(connection, event.intent_digest)
                diff = DocumentIntentDiff.model_validate(packet["diff"])
                await self.recheck(connection, diff)
                matched = (
                    packet["status"] == "applied"
                    and packet["applied_revision"] == event.applied_revision
                )
            async with await self.graph._connect() as connection:
                actual = await (
                    await connection.execute(
                        "SELECT * FROM document_intent_resource WHERE id=%s",
                        (diff.properties.id,),
                    )
                ).fetchone()
                matched = (
                    matched
                    and actual is not None
                    and (
                        actual["revision"] == event.applied_revision
                        and actual["properties"] == self.record(diff).properties
                        and actual["catalog_digest"] == diff.ontology_release
                    )
                )
        except (PermissionError, ValueError):
            matched = False
        return DocumentIntentEvent.create(
            "verified",
            event.intent_digest,
            event.correlation_id,
            outcome="matched" if matched else "mismatched",
            applied_revision=event.applied_revision,
        )

    async def rollback(self, event: DocumentIntentEvent) -> DocumentIntentEvent:
        async with await self.graph._connect() as connection:
            await self.graph._set_timeout(connection)
            await connection.execute("SELECT pg_advisory_xact_lock(%s)", (8_419_450_268,))
            packet = await self.packet(connection, event.intent_digest, lock=True)
            diff = DocumentIntentDiff.model_validate(packet["diff"])
            sealed = await (
                await connection.execute(
                    "SELECT receipt FROM document_intent_transition "
                    "WHERE digest=%s AND phase='verified_sealed' AND correlation_id=%s",
                    (event.intent_digest, event.correlation_id),
                )
            ).fetchone()
            if sealed is None or sealed["receipt"].get("outcome") != "mismatched":
                raise PermissionError("rollback requires Saga-audited independent mismatch")
            if packet["status"] == "rolled_back":
                return DocumentIntentEvent.create(
                    "rolled_back",
                    event.intent_digest,
                    event.correlation_id,
                    outcome="rolled_back",
                    applied_revision=event.applied_revision,
                )
            if packet["status"] != "applied":
                raise ValueError("intent rollback cannot replace a later source revision")
            target = await (
                await connection.execute(
                    "SELECT * FROM document_intent_resource WHERE id=%s FOR UPDATE",
                    (diff.properties.id,),
                )
            ).fetchone()
            if target is None or target["revision"] != event.applied_revision:
                raise ValueError("intent rollback target changed; arbitration required")
            if packet["before_image"] is None:
                await connection.execute(
                    "DELETE FROM document_intent_resource WHERE id=%s", (diff.properties.id,)
                )
            else:
                before = packet["before_image"]
                await connection.execute(
                    "UPDATE document_intent_resource SET object_type=%s,properties=%s::jsonb,"
                    "revision=%s,type_version=%s,catalog_digest=%s WHERE id=%s",
                    (
                        before["object_type"],
                        json.dumps(before["properties"]),
                        event.applied_revision + 1,
                        before["type_version"],
                        before["catalog_digest"],
                        diff.properties.id,
                    ),
                )
                await connection.execute(
                    "UPDATE document_intent_projection SET status='restored',applied_revision=%s "
                    "WHERE target_id=%s AND status='superseded' AND applied_revision=%s",
                    (
                        event.applied_revision + 1,
                        diff.properties.id,
                        diff.expected_revision,
                    ),
                )
            await connection.execute(
                "UPDATE document_intent_projection SET status='rolled_back' WHERE digest=%s",
                (event.intent_digest,),
            )
            result = DocumentIntentEvent.create(
                "rolled_back",
                event.intent_digest,
                event.correlation_id,
                outcome="rolled_back",
                applied_revision=event.applied_revision,
            )
            await connection.execute(
                "INSERT INTO document_intent_transition(digest,phase,correlation_id,receipt) "
                "VALUES (%s,'rolled_back',%s,%s::jsonb)",
                (event.intent_digest, event.correlation_id, result.model_dump_json()),
            )
            return result

    async def active_revision(self, digest: str) -> int | None:
        async with await self.graph._connect() as connection:
            packet = await self.packet(connection, digest)
            return (
                int(packet["applied_revision"])
                if packet["status"] in {"applied", "restored"}
                else None
            )

    async def pending(self, owner: str) -> tuple[DocumentIntentEvent, ...]:
        async with await self.graph._connect() as connection:
            rows = await (
                await connection.execute(
                    "SELECT receipt FROM document_intent_transition WHERE published_at IS NULL "
                    "AND receipt->>'producer_principal'=%s ORDER BY created_at LIMIT 50",
                    (owner,),
                )
            ).fetchall()
        return tuple(DocumentIntentEvent.model_validate(row["receipt"]) for row in rows)

    async def published(self, event: DocumentIntentEvent) -> None:
        async with await self.graph._connect() as connection:
            await connection.execute(
                "UPDATE document_intent_transition SET published_at=COALESCE(published_at,NOW()) "
                "WHERE digest=%s AND phase=%s AND receipt=%s::jsonb",
                (event.intent_digest, event.phase, event.model_dump_json()),
            )
