"""Source-authorized private intent namespace, separate from common observations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.conversation.semantic_manifest import semantic_principal_scope_digest
from fdai.core.conversation.session import Principal
from fdai.core.ontology_platform.document_intent import DocumentIntentDiff
from fdai.core.ontology_platform.interfaces import compile_interfaces
from fdai.core.ontology_platform.object_sets import ObjectSetService
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.core.ontology_platform.source_read_admission import (
    SourceReadAdmission,
    SourceReadAdmissionError,
    admitted_source_read,
)
from fdai.delivery.persistence.postgres_document_intent import PostgresDocumentIntent
from fdai.delivery.persistence.postgres_ontology_records import _object_from_row
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyObjectRecord,
    json_values_equal,
)


class PostgresDocumentIntentReadAdmission:
    """Read current API and directory facts; a stored approval never grants reader access."""

    def __init__(
        self, repository: PostgresDocumentIntent, principal: Principal, *, purpose: str
    ) -> None:
        self.repository = repository
        self.principal = principal
        self.purpose = purpose
        self.scope = semantic_principal_scope_digest(principal=principal, purpose=purpose)

    async def authorize(self, *, principal_scope_digest: str, purpose: str) -> SourceReadAdmission:
        if principal_scope_digest != self.scope or purpose != self.purpose:
            raise PermissionError("intent reader scope or purpose mismatch")
        human = await self.repository.identities.read(self.principal.id)
        if (
            human is None
            or human.subject_ref != self.principal.id
            or not human.current(self.repository.clock())
            or self.principal.role.value.casefold() not in {role.casefold() for role in human.roles}
        ):
            raise PermissionError("current intent reader identity is unavailable")
        proof = []
        async with await self.repository.graph._connect() as connection:
            await self.repository.graph._set_timeout(connection)
            rows = await (
                await connection.execute(
                    "SELECT * FROM document_intent_projection "
                    "WHERE status IN ('applied','restored') ORDER BY target_id LIMIT 65"
                )
            ).fetchall()
            if len(rows) > 64:
                raise SourceReadAdmissionError("intent source universe exceeds its bound")
            for row in rows:
                diff = DocumentIntentDiff.model_validate(row["diff"])
                if diff.digest != row["digest"]:
                    raise SourceReadAdmissionError("intent projection commitment changed")
                source = await self.repository.recheck(connection, diff)
                self.repository.check_access(source, human.subject_ref, human.group_ids)
                target = await (
                    await connection.execute(
                        "SELECT * FROM document_intent_resource WHERE id=%s", (row["target_id"],)
                    )
                ).fetchone()
                if (
                    target is None
                    or target["revision"] != row["applied_revision"]
                    or target["properties"] != self.repository.record(diff).properties
                    or target["catalog_digest"] != diff.ontology_release
                ):
                    raise SourceReadAdmissionError("intent graph effect is not current")
                proof.append(
                    {
                        "diff": diff.digest,
                        "source": source.model_dump(mode="json"),
                        "revision": row["applied_revision"],
                    }
                )
            count = await (
                await connection.execute("SELECT count(*) AS n FROM document_intent_resource")
            ).fetchone()
            if (
                count is None
                or count["n"] != len(rows)
                or len({row["target_id"] for row in rows}) != len(rows)
            ):
                raise SourceReadAdmissionError("intent source universe is incomplete")
        if not human.current(self.repository.clock()):
            raise PermissionError("intent reader identity expired during admission")
        return SourceReadAdmission(self.scope, purpose, content_digest(proof))


class DocumentIntentInstanceReader:
    """Protected read-only ontology interface without an observed-state writer."""

    def __init__(self, admission: PostgresDocumentIntentReadAdmission) -> None:
        self.admission = admission
        self.request = ProjectionRequest(
            caller_role=CeilingRole(admission.principal.role.value.casefold()),
            declared_purposes=frozenset({admission.purpose}),
            principal_scope_digest=admission.scope,
        )

    async def query_objects(
        self,
        *,
        object_types: Sequence[str] = (),
        object_ids: Sequence[str] = (),
        property_equals: Mapping[str, Any] | None = None,
        property_text_in: Mapping[str, Sequence[str]] | None = None,
        limit: int = 100,
        include_relationships: bool = True,
    ) -> OntologyGraphSnapshot:
        if not 1 <= limit <= 50_000:
            raise ValueError("intent query limit is outside its bound")
        async with admitted_source_read(
            self.admission, request=self.request, purpose=self.admission.purpose
        ):
            graph = self.admission.repository.graph
            async with await graph._connect() as connection:
                rows = await (
                    await connection.execute(
                        "SELECT * FROM document_intent_resource ORDER BY id LIMIT 65"
                    )
                ).fetchall()
            if len(rows) > 64:
                raise SourceReadAdmissionError("intent namespace exceeds its bound")
            selected = [
                row
                for row in rows
                if (not object_types or row["object_type"] in object_types)
                and (not object_ids or row["id"] in object_ids)
                and all(
                    key in row["properties"] and json_values_equal(row["properties"][key], value)
                    for key, value in (property_equals or {}).items()
                )
                and all(
                    row["properties"].get(key) in values
                    for key, values in (property_text_in or {}).items()
                )
            ]
            return OntologyGraphSnapshot(
                objects=tuple(
                    _object_from_row(row, releases=graph._releases) for row in selected[:limit]
                ),
                truncated=len(selected) > limit,
                source_generation="document-intent:" + content_digest(rows)[7:],
            )

    async def scan_objects(self, **kwargs: Any) -> OntologyGraphSnapshot:
        return await self.query_objects(**kwargs)

    async def get_object(self, object_id: str) -> OntologyObjectRecord | None:
        snapshot = await self.query_objects(object_ids=(object_id,), limit=1)
        return snapshot.objects[0] if snapshot.objects else None

    async def traverse(
        self, *, root_ids: Sequence[str], limit: int = 100, **_kwargs: Any
    ) -> OntologyGraphSnapshot:
        return await self.query_objects(object_ids=root_ids, limit=limit)

    async def traverse_from_type(
        self, *, root_object_type: str, limit: int = 100, **_kwargs: Any
    ) -> OntologyGraphSnapshot:
        return await self.query_objects(object_types=(root_object_type,), limit=limit)

    async def create_object_if_absent(
        self, *_args: Any, **_kwargs: Any
    ) -> OntologyObjectRecord | None:
        raise PermissionError("intent read adapter has no write authority")

    async def upsert_object(self, *_args: Any, **_kwargs: Any) -> OntologyObjectRecord:
        raise PermissionError("intent read adapter has no write authority")

    async def upsert_link(self, *_args: Any, **_kwargs: Any) -> None:
        raise PermissionError("intent read adapter has no write authority")

    async def replace_subgraph(self, *_args: Any, **_kwargs: Any) -> None:
        raise PermissionError("intent read adapter has no write authority")

    async def delete_object(self, *_args: Any, **_kwargs: Any) -> bool:
        raise PermissionError("intent read adapter has no write authority")


def document_intent_gateway(
    repository: PostgresDocumentIntent, principal: Principal, *, purpose: str = "operations-review"
) -> SecuredObjectSetQueryGateway:
    """Bind current persistence and identity to one authenticated server principal."""
    admission = PostgresDocumentIntentReadAdmission(repository, principal, purpose=purpose)
    declaration = repository.graph._object_types["BusinessService"]
    return SecuredObjectSetQueryGateway(
        service=ObjectSetService(
            store=DocumentIntentInstanceReader(admission),
            interfaces=compile_interfaces(
                interfaces=(), implementations=(), object_types=(declaration,)
            ),
            object_type_names=frozenset({"BusinessService"}),
        ),
        object_types={"BusinessService": declaration},
        ontology_release=repository.graph._release,
        evaluation_cutoff=repository.clock,
        source_read_admission=admission,
    )
