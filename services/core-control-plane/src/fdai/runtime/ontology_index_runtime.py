"""Authenticated enrollment and off-path reconciliation for the isolated instance index."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal

from fdai_service_contracts.ontology_query import content_digest
from pydantic import AwareDatetime, BaseModel, ConfigDict

from fdai.agents import (
    ContextIndexMessage,
    PantheonRuntime,
    recover_context_index_publications,
    request_context_index,
)
from fdai.core.conversation.semantic_manifest import (
    CatalogQueryManifestProvider,
    semantic_principal_scope_digest,
)
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import QueryManifest
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.interfaces import compile_interfaces
from fdai.core.ontology_platform.object_sets import ObjectSetService
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.delivery.catalog_search.generation import build_ontology_semantic_generation
from fdai.delivery.catalog_search.ontology_candidate_reader import OntologyInstanceCandidateReader
from fdai.delivery.catalog_search.ontology_index_lifecycle import IndexScope, IndexTransition
from fdai.delivery.catalog_search.ontology_index_workers import (
    IndexPreparationRequest,
    OntologyContextIndexWorkers,
)
from fdai.delivery.catalog_search.ontology_snapshot_store import OntologyGenerationSnapshotStore
from fdai.delivery.catalog_search.ontology_vector_store import OntologyVectorSnapshotStore
from fdai.delivery.catalog_search.ranking import CatalogRankingPolicy
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog
from fdai.shared.contracts.models import OntologyRelease
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.providers.knowledge import Embedder
from fdai.shared.providers.ontology_instance import OntologyInstanceStore, OntologyObjectRecord
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.state_store import StateStore


class _Enrollment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    principal: Principal
    scope: IndexScope
    issued_at: AwareDatetime
    expires_at: AwareDatetime


def build_ontology_index_runtime(
    *,
    store: StateStore,
    ontology_store: OntologyInstanceStore,
    catalog: OntologyCatalog,
    release: OntologyRelease,
    embedder: Embedder,
    clock: Callable[[], datetime],
    projection_lock: ResourceLock | None = None,
) -> OntologyIndexRuntime | None:
    """Bind real adapters only with governed embedding metadata; never call a provider here."""
    space = getattr(embedder, "embedding_space_id", None)
    model = getattr(embedder, "embedding_model_version", None)
    dimension = getattr(embedder, "dim", None)
    if (
        not isinstance(space, str)
        or not space.strip()
        or not isinstance(model, str)
        or not model.strip()
        or type(dimension) is not int
        or dimension <= 0
    ):
        return None
    gateway = SecuredObjectSetQueryGateway(
        service=ObjectSetService(
            store=ontology_store,
            interfaces=compile_interfaces(
                interfaces=catalog.interface_types,
                implementations=catalog.interface_implementations,
                object_types=catalog.object_types,
                release=release,
            ),
            object_type_names=frozenset(item.name for item in catalog.object_types),
        ),
        object_types={item.name: item for item in catalog.object_types},
        ontology_release=release,
        evaluation_cutoff=clock,
        max_as_of_skew=timedelta(seconds=5),
    )
    manifests = CatalogQueryManifestProvider(
        release=release,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        interfaces=catalog.interface_types,
        action_types=catalog.action_types,
        functions=operational_function_types(catalog.function_types),
    )
    runtime = OntologyIndexRuntime(
        store=store,
        gateway=gateway,
        manifest_for=lambda principal: manifests.manifest_for(
            principal=principal, purpose="operations-review"
        ),
        clock=clock,
        embedding_space_id=space,
        embedding_model_version=model,
        embedding_dimension=dimension,
    )
    snapshots = OntologyGenerationSnapshotStore(store)
    vectors = OntologyVectorSnapshotStore(
        store,
        embedder=embedder,
        embedding_space_id=space,
        embedding_model_version=model,
        embedding_dimension=dimension,
    )
    runtime.workers = OntologyContextIndexWorkers(
        store=store,
        snapshots=snapshots,
        vectors=vectors,
        reader=OntologyInstanceCandidateReader(
            snapshots=snapshots,
            vectors=vectors,
            ranking_policy=CatalogRankingPolicy(),
            semantic_search_available=False,
        ),
        resolve_source=runtime.source,
        clock=clock,
        embedding_space_id=space,
        embedding_model_version=model,
        embedding_dimension=dimension,
        projection_lock=projection_lock,
    )
    return runtime


class OntologyIndexRuntime:
    """Enroll only current authenticated contexts; models never supply scope or source data.

    Query ingress records bounded ephemeral enrollment, never embeds or waits for a build.
    Reconciliation publishes owned lifecycle requests and restores only audited read caches.
    A worker replica resolves only a still-current service-owned enrollment receipt.
    """

    def __init__(
        self,
        *,
        store: StateStore,
        gateway: SecuredObjectSetQueryGateway,
        manifest_for: Callable[[Principal], QueryManifest],
        clock: Callable[[], datetime],
        embedding_space_id: str,
        embedding_model_version: str,
        embedding_dimension: int,
    ) -> None:
        self._store, self._gateway, self._manifest_for, self._clock = (
            store,
            gateway,
            manifest_for,
            clock,
        )
        self._space, self._model, self._dimension = (
            embedding_space_id,
            embedding_model_version,
            embedding_dimension,
        )
        self._enrollments: dict[str, _Enrollment] = {}
        self._attempted: dict[str, str] = {}
        self._restored: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._enrollment_lock = asyncio.Lock()
        self.workers: OntologyContextIndexWorkers | None = None

    async def source(self, scope: IndexScope) -> tuple[QueryManifest, SecuredObjectSetQueryGateway]:
        raw = await self._store.read_state(f"ontology-index-enrollment:v1:{scope.digest}")
        if raw is None:
            raise PermissionError("ontology index requires current authenticated enrollment")
        enrollment = _Enrollment.model_validate(raw)
        if (
            enrollment.scope != scope
            or enrollment.expires_at <= self._clock()
            or enrollment.issued_at > self._clock() + timedelta(seconds=5)
            or enrollment.expires_at - enrollment.issued_at != timedelta(minutes=5)
            or enrollment.principal.role.value != scope.role.value
            or semantic_principal_scope_digest(
                principal=enrollment.principal, purpose=scope.purpose
            )
            != scope.principal_scope_digest
        ):
            raise PermissionError("ontology index requires current authenticated enrollment")
        manifest = self._manifest_for(enrollment.principal)
        if (
            manifest.coverage_receipt.principal_scope_digest != scope.principal_scope_digest
            or manifest.principal_role != scope.role
            or manifest.purposes != (scope.purpose,)
        ):
            raise PermissionError("ontology index manifest enrollment mismatch")
        return manifest, self._gateway

    async def query(
        self, query: str, limit: int, context: FunctionInvocationContext
    ) -> dict[str, object]:
        if (
            context.caller_agent != "Bragi"
            or context.purposes != ("operations-review",)
            or not context.principal_ref
            or not context.principal_ref.strip()
        ):
            raise PermissionError("ontology index requires authenticated presentation context")
        principal = Principal(
            id=context.principal_ref,
            role=Role(context.caller_role.value),
            groups=frozenset(context.principal_groups),
        )
        expected = semantic_principal_scope_digest(principal=principal, purpose=context.purposes[0])
        if context.principal_scope_digest != expected:
            raise PermissionError("ontology index authenticated principal scope mismatch")
        scope = IndexScope(
            principal_scope_digest=expected, role=context.caller_role, purpose=context.purposes[0]
        )
        async with asyncio.timeout(2), self._enrollment_lock:
            self._expire_enrollments()
            if scope.digest not in self._enrollments and len(self._enrollments) >= 8:
                raise ValueError("ontology index enrollment capacity unavailable")
            now = self._clock()
            enrollment = _Enrollment(
                principal=principal,
                scope=scope,
                issued_at=now,
                expires_at=now + timedelta(minutes=5),
            )
            await self._store.write_state(
                f"ontology-index-enrollment:v1:{scope.digest}", enrollment.model_dump(mode="json")
            )
            self._enrollments[scope.digest] = enrollment
        if self.workers is None:
            raise ValueError("ontology instance index workers unavailable")
        return await self.workers.query_function(query, limit, context)

    def _expire_enrollments(self) -> None:
        for key, enrollment in tuple(self._enrollments.items()):
            if enrollment.expires_at <= self._clock():
                if self.workers is not None:
                    self.workers.release_scope(enrollment.scope)
                del self._enrollments[key]
                self._attempted.pop(key, None)
                self._restored.pop(key, None)

    async def run(self, runtime: PantheonRuntime, stop: asyncio.Event) -> None:
        """Run bounded background reconciliation under the existing runtime supervisor."""
        while not stop.is_set():
            try:
                await self.reconcile(runtime)
            except (ValueError, PermissionError, TimeoutError, RuntimeError) as exc:
                logging.getLogger(__name__).warning(
                    "ontology_index_reconciliation_unavailable",
                    extra={"failure_type": type(exc).__name__},
                )
            try:
                await asyncio.wait_for(stop.wait(), timeout=30)
            except TimeoutError:
                continue

    async def reconcile(self, runtime: PantheonRuntime) -> None:
        if self.workers is None:
            return
        async with asyncio.timeout(30), self._lock:
            self._expire_enrollments()
            failure: ValueError | PermissionError | TimeoutError | RuntimeError | None = None
            try:
                async with asyncio.timeout(5):
                    await recover_context_index_publications(runtime.agents, self.workers.bindings)
            except (ValueError, PermissionError, TimeoutError, RuntimeError) as exc:
                failure = exc
            for enrollment in tuple(self._enrollments.values()):
                try:
                    async with asyncio.timeout(3):
                        await self._reconcile_scope(runtime, enrollment.scope)
                except (ValueError, PermissionError, TimeoutError, RuntimeError) as exc:
                    failure = failure or exc
            if failure is not None:
                raise failure

    async def _reconcile_scope(self, runtime: PantheonRuntime, scope: IndexScope) -> None:
        if self.workers is None:
            return
        pointer = await self.workers.lifecycle.read(scope)
        if not await self.workers.transition_completed(pointer):
            return
        manifest, gateway = await self.source(scope)
        names = tuple(
            sorted(str(item["name"]) for item in manifest.descriptors if item["kind"] == "object")
        )
        observed = await gateway.scan_snapshot(
            object_type_names=names,
            purpose=scope.purpose,
            as_of=self._clock(),
            candidate_limit=20_000 - len(manifest.descriptors) - len(manifest.unavailable),
            projection_request=ProjectionRequest(
                caller_role=scope.role,
                declared_purposes=frozenset({scope.purpose}),
                principal_scope_digest=scope.principal_scope_digest,
            ),
        )
        source_generation = observed.graph.source_generation
        if not source_generation or observed.ontology_release_digest != manifest.release_digest:
            raise ValueError("ontology index reconciliation source unavailable")
        build = build_ontology_semantic_generation(
            manifest=manifest,
            runtime_objects=tuple(
                OntologyObjectRecord(
                    id=record.id,
                    object_type=record.object_type,
                    properties={
                        name: value
                        for name, value in record.properties.items()
                        if name != "__redactions__"
                        and name not in record.properties.get("__redactions__", {})
                    },
                )
                for record in observed.graph.objects
            ),
            embedding_space_id=self._space,
            embedding_model_version=self._model,
            embedding_dimension=self._dimension,
        )
        target = pointer.active
        if target is not None and (
            target.generation_digest == build.metadata.generation_digest
            and target.source_generation == source_generation
            and target.manifest_digest == manifest.manifest_digest
        ):
            if self._restored.get(scope.digest) != target.digest:
                if await self.workers.restore_current(scope):
                    self._restored[scope.digest] = target.digest
            return
        retire_target = (
            pointer.retained[0] if target is not None and len(pointer.retained) == 8 else None
        )
        identity = content_digest(
            {
                "scope": scope.digest,
                "enrollment_issued_at": self._enrollments[scope.digest].issued_at.isoformat(),
                "revision": pointer.revision,
                "source": source_generation,
                "generation": build.metadata.generation_digest,
                "retire_target": retire_target.digest if retire_target is not None else None,
            }
        )
        requested_at = self._clock()
        phase: Literal["transition", "prepare"]
        if target is not None:
            body = IndexTransition(
                command_id=identity,
                scope=scope,
                operation="retire" if retire_target is not None else "invalidate",
                expected_revision=pointer.revision,
                expected_active_digest=target.digest,
                target=retire_target,
                requested_at=requested_at,
                expires_at=requested_at + timedelta(seconds=120),
            ).model_dump(mode="json")
            phase = "transition"
        else:
            body = IndexPreparationRequest(
                scope=scope,
                source_generation=source_generation,
                expected_revision=pointer.revision,
                expected_active_digest=None,
                requested_at=requested_at,
            ).model_dump(mode="json")
            phase = "prepare"
        message = ContextIndexMessage.create(phase=phase, correlation_id=identity, body=body)
        request_key = f"ontology-index-request:v1:{identity}"
        await self._store.write_state_if_absent(request_key, message.model_dump(mode="json"))
        stored = await self._store.read_state(request_key)
        message = ContextIndexMessage.model_validate(stored)
        if message.correlation_id != identity or message.phase != phase:
            raise ValueError("ontology index reconciliation request identity mismatch")
        if phase == "prepare":
            saved_request = IndexPreparationRequest.model_validate(message.body)
            if (
                saved_request.scope != scope
                or saved_request.source_generation != source_generation
                or saved_request.expected_revision != pointer.revision
                or saved_request.expected_active_digest is not None
            ):
                raise ValueError("ontology index reconciliation request scope mismatch")
            expires_at = saved_request.requested_at + timedelta(seconds=120)
        else:
            saved_transition = IndexTransition.model_validate(message.body)
            if (
                saved_transition.scope != scope
                or saved_transition.operation
                != ("retire" if retire_target is not None else "invalidate")
                or saved_transition.command_id != identity
                or saved_transition.expected_revision != pointer.revision
                or saved_transition.expected_active_digest != (target.digest if target else None)
                or saved_transition.target != retire_target
            ):
                raise ValueError("ontology index reconciliation transition scope mismatch")
            expires_at = saved_transition.expires_at
        if await self.workers.journal.replay(message, "Muninn") is not None:
            return
        if expires_at <= self._clock():
            raise ValueError("ontology index reconciliation request expired without owner outcome")
        await request_context_index(runtime, message)
        self._attempted[scope.digest] = identity
        self._restored.pop(scope.digest, None)
