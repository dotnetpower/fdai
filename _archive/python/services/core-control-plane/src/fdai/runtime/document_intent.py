"""Governed-envelope command boundary for the private approved-intent namespace."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fdai_service_contracts import DocumentEnvelope

from fdai.agents import PantheonBus, publish_document_intent_source
from fdai.core.conversation.session import Principal
from fdai.core.ontology_platform.document_intent import DocumentIntentDiff
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.delivery.identity.handover_review_identity import HandoverIdentityReader
from fdai.delivery.persistence.postgres_document_intent import PostgresDocumentIntent
from fdai.delivery.persistence.postgres_document_intent_reader import document_intent_gateway
from fdai.delivery.persistence.postgres_ontology import PostgresOntologyInstanceStore


@dataclass(frozen=True, slots=True)
class DocumentIntentRuntime:
    """Same local/deployed adapters; callers bind an already authenticated server principal."""

    repository: PostgresDocumentIntent

    async def submit(
        self,
        bus: PantheonBus,
        envelope: DocumentEnvelope,
        *,
        principal: Principal,
        scope_ref: str,
        operation: str,
        expected_revision: int,
    ) -> tuple[str, str]:
        digest = await self.repository.prepare(
            envelope,
            requester_ref=principal.id,
            scope_ref=scope_ref,
            operation=operation,
            expected_revision=expected_revision,
        )
        correlation = "document-intent:" + digest[7:]
        await publish_document_intent_source(bus, intent_digest=digest, correlation_id=correlation)
        return digest, correlation

    async def review_diff(self, digest: str, *, principal: Principal) -> DocumentIntentDiff:
        """Let an independent reviewer inspect exactly what Var's opaque ticket binds."""
        human = await self.repository.identities.read(principal.id)
        if (
            human is None
            or human.subject_ref != principal.id
            or not human.current(self.repository.clock())
            or not set(human.roles).intersection({"Approver", "Owner"})
        ):
            raise PermissionError("current intent review role is required")
        diff = await self.repository.review(digest)
        async with await self.repository.graph._connect() as connection:
            source = await self.repository.recheck(connection, diff)
            self.repository.check_access(source, principal.id, human.group_ids)
        return diff

    async def submit_current(
        self,
        bus: PantheonBus,
        envelope: DocumentEnvelope,
        *,
        principal: Principal,
    ) -> tuple[str, str]:
        """Compile the current add/update operation from the private source-owned target."""
        manifest = envelope.artifact_manifest
        if manifest is None or manifest.scope_ref is None:
            raise PermissionError("current intent source scope is unavailable")
        revision = await self.repository.current_target_revision(envelope)
        return await self.submit(
            bus,
            envelope,
            principal=principal,
            scope_ref=manifest.scope_ref,
            operation="update" if revision else "add",
            expected_revision=revision,
        )

    async def withdraw_current(
        self,
        bus: PantheonBus,
        *,
        document_id: UUID,
        version_id: UUID,
        correlation_id: str,
    ) -> int:
        digests = await self.repository.current_source_digests(document_id, version_id)
        for digest in digests:
            await publish_document_intent_source(
                bus,
                intent_digest=digest,
                correlation_id=f"{correlation_id}:{digest[7:]}",
            )
        return len(digests)

    def query(self, *, principal: Principal) -> SecuredObjectSetQueryGateway:
        return document_intent_gateway(self.repository, principal)


def build_document_intent_runtime(
    *, graph: PostgresOntologyInstanceStore, identities: HandoverIdentityReader
) -> DocumentIntentRuntime:
    """Construct without provider I/O or enabling any external executor."""
    return DocumentIntentRuntime(PostgresDocumentIntent(graph, identities))
