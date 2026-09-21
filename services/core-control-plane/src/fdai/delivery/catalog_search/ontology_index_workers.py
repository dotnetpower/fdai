"""Mechanical source, validation, and audit-seal workers for owned ContextIndex events."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Annotated

from fdai_service_contracts.ontology_query import content_digest
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter

from fdai.agents import ContextIndexMessage, ContextIndexWorkerBindings
from fdai.core.executor.lock import ResourceLockManager
from fdai.core.ontology_platform import QueryManifest
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.state_store import StateStore

from .ontology_candidate_reader import (
    OntologyCandidateSearchResult,
    OntologyInstanceCandidateReader,
)
from .ontology_index_journal import OntologyIndexJournal
from .ontology_index_lifecycle import (
    IndexGeneration,
    IndexPointer,
    IndexScope,
    IndexTerminal,
    IndexTransition,
    OntologyIndexLifecycle,
)
from .ontology_index_retention import reclaim_retired_index
from .ontology_snapshot_store import OntologyGenerationSnapshotStore, OntologyStagedProjection
from .ontology_snapshot_validation import (
    OntologySnapshotValidation,
    validate_snapshot_against_current_graph,
)
from .ontology_vector_store import OntologyVectorSnapshotStore

_Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
_PREFIX = "ontology-context-evidence:v1:"
_VALIDATION = TypeAdapter(OntologySnapshotValidation)
SourceResolver = Callable[
    [IndexScope], Awaitable[tuple[QueryManifest, SecuredObjectSetQueryGateway]]
]


class IndexPreparationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    scope: IndexScope
    source_generation: str = Field(min_length=1, max_length=256)
    expected_revision: int = Field(strict=True, ge=0)
    expected_active_digest: _Digest | None
    requested_at: AwareDatetime


class _PreparedBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    request: IndexPreparationRequest
    snapshot_digest: _Digest
    source_projection_digest: _Digest
    vector_digest: _Digest
    generation_digest: _Digest
    manifest_digest: _Digest
    ontology_release_digest: _Digest
    built_at: AwareDatetime

    @property
    def staged(self) -> OntologyStagedProjection:
        return OntologyStagedProjection(
            self.snapshot_digest,
            self.source_projection_digest,
            self.request.source_generation,
        )


class _ValidatedBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    prepared: _PreparedBody
    validation: OntologySnapshotValidation


class _IntentBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    command: IndexTransition
    validation_message_key: str


class _SealedIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    intent: _IntentBody
    intent_seal_digest: _Digest


class _SealedTerminal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    terminal: IndexTerminal
    terminal_seal_digest: _Digest


class _ControlValidation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    command: IndexTransition
    validation: OntologySnapshotValidation | None


class OntologyContextIndexWorkers:
    """Implement owned event phases, retaining exact immutable replay records.

    The composition-owned resolver supplies current authenticated scope and ACL
    gateways, never model-selected source objects. Saga callbacks are invoked only
    after the owner wrapper has durably appended the exact event to its audit.
    Stored validation and seals are required again inside the pointer admission.
    This binds local mechanics, not relevance qualification or runtime promotion.
    """

    def __init__(
        self,
        *,
        store: StateStore,
        snapshots: OntologyGenerationSnapshotStore,
        vectors: OntologyVectorSnapshotStore,
        reader: OntologyInstanceCandidateReader,
        resolve_source: SourceResolver,
        clock: Callable[[], datetime],
        embedding_space_id: str,
        embedding_model_version: str,
        embedding_dimension: int,
        projection_lock: ResourceLock | None = None,
    ) -> None:
        self._store, self._snapshots, self._vectors, self._reader = (
            store,
            snapshots,
            vectors,
            reader,
        )
        self._resolve_source, self._clock = resolve_source, clock
        self._space, self._model, self._dimension = (
            embedding_space_id,
            embedding_model_version,
            embedding_dimension,
        )
        self.lifecycle = OntologyIndexLifecycle(store=store, admit=self._admit, clock=clock)
        self.journal = OntologyIndexJournal(store)
        self._projection_lock = projection_lock or ResourceLockManager()

    @property
    def bindings(self) -> ContextIndexWorkerBindings:
        return ContextIndexWorkerBindings(
            muninn=self.muninn,
            heimdall=self.heimdall,
            saga=self.saga,
            published=self.journal.published,
            pending=self._pending,
        )

    async def _pending(self, owner: str) -> tuple[ContextIndexMessage, ...]:
        await self.journal.acknowledge_pending(owner)
        return await self.journal.pending(owner)

    async def search_current(
        self,
        query: str,
        *,
        scope: IndexScope,
        as_of: datetime,
        limit: int = 20,
    ) -> OntologyCandidateSearchResult:
        """Consume only the exact current pointer with its durable Saga terminal seal."""
        pointer = await self.lifecycle.read(scope)
        target, terminal = pointer.active, pointer.terminal
        if target is None or terminal is None:
            raise ValueError("ontology instance index has no current active generation")
        seal = await self._store.read_state(f"{_PREFIX}terminal-seal:{terminal.command.digest}")
        if seal is None or _SealedTerminal.model_validate(seal).terminal != terminal:
            raise ValueError("ontology instance index terminal audit is unavailable")
        manifest, gateway = await self._source(scope)
        if manifest.manifest_digest != target.manifest_digest:
            self._reader.invalidate(principal_scope_digest=scope.principal_scope_digest)
            raise ValueError("ontology instance index manifest changed")
        result = await self._reader.search(
            query,
            staged=OntologyStagedProjection(
                target.snapshot_digest,
                target.source_projection_digest,
                target.source_generation,
            ),
            manifest=manifest,
            gateway=gateway,
            as_of=as_of,
            limit=limit,
        )
        if await self.lifecycle.read(scope) != pointer:
            self._reader.invalidate(principal_scope_digest=scope.principal_scope_digest)
            raise ValueError("ontology instance index changed during the query")
        return result

    async def transition_completed(self, pointer: IndexPointer) -> bool:
        """Require terminal audit and completed cache/cleanup before a successor transition."""
        terminal = pointer.terminal
        if terminal is None:
            return pointer.revision == 0
        raw = await self._store.read_state(f"{_PREFIX}terminal-seal:{terminal.command.digest}")
        if raw is None:
            return False
        sealed = _SealedTerminal.model_validate(raw)
        if sealed.terminal != terminal:
            raise ValueError("ontology index terminal completion identity mismatch")
        request = ContextIndexMessage.create(
            phase="terminal_sealed",
            correlation_id=terminal.command.command_id,
            body=sealed.model_dump(mode="json"),
        )
        ready = await self.journal.replay(request, "Muninn")
        if ready is None:
            return False
        if (
            ready.phase != "ready"
            or ready.body.get("revision") != pointer.revision
            or ready.body.get("scope_digest") != pointer.scope.digest
            or (
                pointer.active is not None
                and ready.body.get("generation_digest") != pointer.active.digest
            )
            or (pointer.active is None and ready.body.get("available") is not False)
        ):
            raise ValueError("ontology index ready completion identity mismatch")
        return True

    def release_scope(self, scope: IndexScope) -> None:
        """Drop process-local read data without changing durable activation or audit state."""
        self._reader.invalidate(principal_scope_digest=scope.principal_scope_digest)

    async def restore_current(self, scope: IndexScope) -> bool:
        """Rehydrate only the already audited active pointer, without new lifecycle authority."""
        pointer = await self.lifecycle.read(scope)
        target, terminal = pointer.active, pointer.terminal
        if target is None or terminal is None:
            return False
        seal = await self._store.read_state(f"{_PREFIX}terminal-seal:{terminal.command.digest}")
        if seal is None or _SealedTerminal.model_validate(seal).terminal != terminal:
            raise ValueError("ontology instance index terminal audit is unavailable")
        manifest, _gateway = await self._source(scope)
        if manifest.manifest_digest != target.manifest_digest:
            raise ValueError("ontology instance index manifest changed")
        record = await self._store.read_state(
            f"{_PREFIX}validation:{target.validation_receipt_digest}"
        )
        if record is None:
            raise ValueError("ontology reader independent validation is unavailable")
        validated = _ValidatedBody.model_validate(record)
        if self._target(validated) != target:
            raise ValueError("ontology reader validation target mismatch")
        await self._reader.prepare(
            staged=validated.prepared.staged,
            vector_digest=target.vector_digest,
            manifest=manifest,
            validation=validated.validation,
        )
        if await self.lifecycle.read(scope) != pointer:
            self._reader.invalidate(principal_scope_digest=scope.principal_scope_digest)
            raise ValueError("ontology reader recovery lost its current pointer identity")
        return True

    async def query_function(
        self,
        query: str,
        limit: int,
        context: FunctionInvocationContext,
    ) -> dict[str, object]:
        """Project candidate facts for the exact authenticated typed Function invocation."""
        if (
            context.principal_scope_digest is None
            or context.principal_ref is None
            or context.caller_agent != "Bragi"
            or context.purposes != ("operations-review",)
        ):
            raise PermissionError(
                "ontology candidate function requires authenticated presentation scope"
            )
        scope = IndexScope(
            principal_scope_digest=context.principal_scope_digest,
            role=context.caller_role,
            purpose=context.purposes[0],
        )
        result = await self.search_current(query, scope=scope, as_of=self._clock(), limit=limit)
        authorized = result.authorized
        candidates = (
            [
                {
                    "id": record.id,
                    "object_type": record.object_type,
                    "properties": dict(record.properties),
                    "revision": record.revision,
                }
                for record in authorized.objects
            ]
            if authorized is not None
            else []
        )
        payload = {
            "candidates": candidates,
            "evidence_refs": list(authorized.query_receipt_digests)
            if authorized is not None
            else [],
            "candidate_count": result.matched_candidate_count,
            "truncated": result.truncated,
            "principal_scope_digest": scope.principal_scope_digest,
            "ontology_release_digest": result.ontology_release_digest,
            "query_digest": content_digest({"query": query, "limit": limit}),
            "authority": "candidate_only",
            "execution_authority": False,
            "exhaustive": False,
        }
        return {**payload, "result_digest": content_digest(payload)}

    def _require_current_request(self, request: IndexPreparationRequest) -> None:
        age = self._clock() - request.requested_at
        if age < timedelta(seconds=-5) or age >= timedelta(seconds=120):
            raise ValueError("ontology preparation request is outside its original deadline")

    async def _prepare_source(self, request: IndexPreparationRequest) -> _PreparedBody:
        self._require_current_request(request)
        remaining = (request.requested_at + timedelta(seconds=120) - self._clock()).total_seconds()
        async with asyncio.timeout(min(120, remaining)):
            manifest, gateway = await self._source(request.scope)
            staged = await self._snapshots.stage_manifest_from_gateway(
                gateway=gateway,
                manifest=manifest,
                as_of=self._clock(),
                expected_source_generation=request.source_generation,
                embedding_space_id=self._space,
                embedding_model_version=self._model,
                embedding_dimension=self._dimension,
            )
            build = await self._snapshots.read(
                staged.snapshot_digest,
                manifest=manifest,
                source_generation=staged.source_generation,
                source_projection_digest=staged.source_projection_digest,
            )
            if build is None:
                raise ValueError("ontology preparation source completion is unavailable")
            self._require_current_request(request)
            vector_digest = await self._vectors.stage(
                snapshots=self._snapshots,
                snapshot_digest=staged.snapshot_digest,
                manifest=manifest,
                source_generation=staged.source_generation,
                source_projection_digest=staged.source_projection_digest,
            )
            self._require_current_request(request)
            return _PreparedBody(
                request=request,
                snapshot_digest=staged.snapshot_digest,
                source_projection_digest=staged.source_projection_digest,
                vector_digest=vector_digest,
                generation_digest=build.metadata.generation_digest,
                manifest_digest=manifest.manifest_digest,
                ontology_release_digest=manifest.release_digest,
                built_at=self._clock(),
            )

    async def muninn(self, message: ContextIndexMessage) -> ContextIndexMessage:
        existing = await self._replay(message, "Muninn")
        if existing is not None and message.phase != "terminal_sealed":
            return existing
        if message.phase == "transition":
            command = IndexTransition.model_validate(message.body)
            if command.operation == "activate" or command.command_id != message.correlation_id:
                raise ValueError(
                    "ontology transition ingress requires an exact non-build operation"
                )
            await self._check_control(command, validator_id="Muninn-preparation")
            output = ContextIndexMessage.create(
                phase="transition_prepared",
                correlation_id=message.correlation_id,
                body=command.model_dump(mode="json"),
            )
        elif message.phase == "transition_validated":
            await self._require_published_record(message, "Heimdall")
            controlled = _ControlValidation.model_validate(message.body)
            intent = _IntentBody(
                command=controlled.command,
                validation_message_key=message.idempotency_key,
            )
            output = ContextIndexMessage.create(
                phase="intent",
                correlation_id=message.correlation_id,
                body=intent.model_dump(mode="json"),
            )
        elif message.phase == "prepare":
            request = IndexPreparationRequest.model_validate(message.body)
            self._require_current_request(request)
            remaining = (
                request.requested_at + timedelta(seconds=120) - self._clock()
            ).total_seconds()
            async with (
                asyncio.timeout(min(120, remaining)),
                self._projection_lock.acquire(f"ontology-index-projection:{request.scope.digest}"),
            ):
                completed = await self._replay(message, "Muninn")
                if completed is not None:
                    return completed
                prepared = await self._prepare_source(request)
                output = ContextIndexMessage.create(
                    phase="prepared",
                    correlation_id=message.correlation_id,
                    body=prepared.model_dump(mode="json"),
                )
                return await self._record(message, output, "Muninn")
        elif message.phase == "validated":
            await self._require_published_record(message, "Heimdall")
            validated = _ValidatedBody.model_validate(message.body)
            prepared = validated.prepared
            self._require_current_request(prepared.request)
            target = self._target(validated)
            command = IndexTransition(
                command_id=message.correlation_id,
                scope=prepared.request.scope,
                operation="activate",
                expected_revision=prepared.request.expected_revision,
                expected_active_digest=prepared.request.expected_active_digest,
                target=target,
                requested_at=prepared.request.requested_at,
                expires_at=prepared.request.requested_at + timedelta(seconds=120),
            )
            intent = _IntentBody(command=command, validation_message_key=message.idempotency_key)
            output = ContextIndexMessage.create(
                phase="intent",
                correlation_id=message.correlation_id,
                body=intent.model_dump(mode="json"),
            )
        elif message.phase == "intent_sealed":
            await self._require_published_record(message, "Saga")
            sealed = _SealedIntent.model_validate(message.body)
            terminal = await self.lifecycle.apply(sealed.intent.command)
            output = ContextIndexMessage.create(
                phase="terminal",
                correlation_id=message.correlation_id,
                body=terminal.model_dump(mode="json"),
            )
        elif message.phase == "terminal_sealed":
            await self._require_published_record(message, "Saga")
            sealed_terminal = _SealedTerminal.model_validate(message.body)
            command = sealed_terminal.terminal.command
            pointer = await self.lifecycle.read(command.scope)
            if pointer.terminal != sealed_terminal.terminal:
                raise ValueError("ontology reader activation lost its current pointer identity")
            if command.operation == "retire" and command.target is not None:
                async with (
                    asyncio.timeout(120),
                    self._projection_lock.acquire(
                        f"ontology-index-projection:{command.scope.digest}"
                    ),
                ):
                    await reclaim_retired_index(
                        store=self._store,
                        lifecycle=self.lifecycle,
                        target=command.target,
                    )
            active_target = pointer.active
            if active_target is None:
                self._reader.invalidate(principal_scope_digest=command.scope.principal_scope_digest)
                output = ContextIndexMessage.create(
                    phase="ready",
                    correlation_id=message.correlation_id,
                    body={
                        "scope_digest": command.scope.digest,
                        "revision": pointer.revision,
                        "available": False,
                        "execution_authority": False,
                    },
                )
                return await self._record(message, output, "Muninn")
            manifest, _gateway = await self._source(command.scope)
            validation_record = await self._store.read_state(
                f"{_PREFIX}validation:{active_target.validation_receipt_digest}"
            )
            if validation_record is None:
                raise ValueError("ontology reader independent validation is unavailable")
            validation = _ValidatedBody.model_validate(validation_record)
            await self._reader.prepare(
                staged=validation.prepared.staged,
                vector_digest=active_target.vector_digest,
                manifest=manifest,
                validation=validation.validation,
            )
            after = await self.lifecycle.read(command.scope)
            if after != pointer:
                self._reader.invalidate(principal_scope_digest=command.scope.principal_scope_digest)
                raise ValueError("ontology reader activation was invalidated during preparation")
            output = ContextIndexMessage.create(
                phase="ready",
                correlation_id=message.correlation_id,
                body={
                    "scope_digest": command.scope.digest,
                    "revision": pointer.revision,
                    "generation_digest": active_target.digest,
                    "execution_authority": False,
                },
            )
        else:
            raise ValueError("Muninn received an unsupported ontology index phase")
        return await self._record(message, output, "Muninn")

    async def heimdall(self, message: ContextIndexMessage) -> ContextIndexMessage:
        if message.phase not in {"prepared", "transition_prepared"}:
            raise ValueError("Heimdall validates only prepared ontology snapshots")
        existing = await self._replay(message, "Heimdall")
        if existing is not None:
            return existing
        await self._require_published_record(message, "Muninn")
        if message.phase == "transition_prepared":
            command = IndexTransition.model_validate(message.body)
            checked = await self._check_control(command, validator_id="Heimdall")
            output = ContextIndexMessage.create(
                phase="transition_validated",
                correlation_id=message.correlation_id,
                body=_ControlValidation(command=command, validation=checked).model_dump(
                    mode="json"
                ),
            )
            return await self._record(message, output, "Heimdall")
        prepared = _PreparedBody.model_validate(message.body)
        self._require_current_request(prepared.request)
        manifest, gateway = await self._source(prepared.request.scope)
        validation = await validate_snapshot_against_current_graph(
            snapshots=self._snapshots,
            staged=prepared.staged,
            gateway=gateway,
            manifest=manifest,
            as_of=self._clock(),
            embedding_space_id=self._space,
            embedding_model_version=self._model,
            embedding_dimension=self._dimension,
            validator_id="Heimdall",
        )
        build = await self._snapshots.read(
            prepared.snapshot_digest,
            manifest=manifest,
            source_generation=prepared.request.source_generation,
            source_projection_digest=prepared.source_projection_digest,
        )
        if build is None or validation.generation_digest != prepared.generation_digest:
            raise ValueError("ontology validation source generation identity mismatch")
        for offset in range(0, len(build.documents), 1000):
            self._require_current_request(prepared.request)
            await self._vectors.read(
                prepared.vector_digest,
                snapshot_digest=prepared.snapshot_digest,
                generation=build.metadata,
                document_ids=tuple(
                    item.rule_id for item in build.documents[offset : offset + 1000]
                ),
            )
        self._require_current_request(prepared.request)
        output = ContextIndexMessage.create(
            phase="validated",
            correlation_id=message.correlation_id,
            body=_ValidatedBody(prepared=prepared, validation=validation).model_dump(mode="json"),
        )
        await self._immutable(f"{_PREFIX}validation:{validation.receipt_digest}", output.body)
        return await self._record(message, output, "Heimdall")

    async def saga(self, message: ContextIndexMessage) -> ContextIndexMessage:
        if message.phase not in {"intent", "terminal"}:
            raise ValueError("Saga seals only ontology transition intent and terminal evidence")
        existing = await self._replay(message, "Saga")
        if existing is not None:
            return existing
        await self._require_published_record(message, "Muninn")
        seal = content_digest({"audited_message": message.content_key, "auditor": "Saga"})
        if message.phase == "intent":
            intent = _IntentBody.model_validate(message.body)
            await self._immutable(
                f"{_PREFIX}intent:{intent.command.digest}", intent.model_dump(mode="json")
            )
            sealed = _SealedIntent(intent=intent, intent_seal_digest=seal)
            await self._immutable(
                f"{_PREFIX}seal:{intent.command.digest}", sealed.model_dump(mode="json")
            )
            output = ContextIndexMessage.create(
                phase="intent_sealed",
                correlation_id=message.correlation_id,
                body=sealed.model_dump(mode="json"),
            )
        else:
            terminal = IndexTerminal.model_validate(message.body)
            pointer = await self.lifecycle.read(terminal.command.scope)
            if pointer.terminal != terminal:
                raise ValueError("ontology terminal audit does not match the durable pointer")
            sealed_terminal = _SealedTerminal(terminal=terminal, terminal_seal_digest=seal)
            await self._immutable(
                f"{_PREFIX}terminal-seal:{terminal.command.digest}",
                sealed_terminal.model_dump(mode="json"),
            )
            output = ContextIndexMessage.create(
                phase="terminal_sealed",
                correlation_id=message.correlation_id,
                body=sealed_terminal.model_dump(mode="json"),
            )
        return await self._record(message, output, "Saga")

    async def _admit(self, command: IndexTransition) -> str | None:
        raw = await self._store.read_state(f"{_PREFIX}seal:{command.digest}")
        if raw is None:
            return None
        sealed = _SealedIntent.model_validate(raw)
        if sealed.intent.command != command:
            return None
        message = await self._message(sealed.intent.validation_message_key, "Heimdall")
        if message.phase == "transition_validated":
            controlled = _ControlValidation.model_validate(message.body)
            if controlled.command != command:
                return None
            if command.operation == "rollback" and (
                controlled.validation is None or controlled.validation.validator_id != "Heimdall"
            ):
                return None
            await self._check_control(command, validator_id="Muninn-admission-recheck")
            return sealed.intent_seal_digest
        validated = _ValidatedBody.model_validate(message.body)
        if self._target(validated) != command.target:
            return None
        manifest, gateway = await self._source(command.scope)
        if manifest.manifest_digest != validated.prepared.manifest_digest:
            return None
        await validate_snapshot_against_current_graph(
            snapshots=self._snapshots,
            staged=validated.prepared.staged,
            gateway=gateway,
            manifest=manifest,
            as_of=self._clock(),
            embedding_space_id=self._space,
            embedding_model_version=self._model,
            embedding_dimension=self._dimension,
            validator_id="Muninn-admission-recheck",
        )
        return sealed.intent_seal_digest

    async def _check_control(
        self,
        command: IndexTransition,
        *,
        validator_id: str,
    ) -> OntologySnapshotValidation | None:
        pointer = await self.lifecycle.read(command.scope)
        if (
            command.operation == "activate"
            or pointer.revision != command.expected_revision
            or command.expected_active_digest != (pointer.active.digest if pointer.active else None)
        ):
            raise ValueError("ontology lifecycle validation requires an exact current pointer")
        if command.operation == "invalidate":
            return None
        target = command.target
        if target is None or target not in pointer.retained:
            raise ValueError("ontology lifecycle validation requires a retained target")
        if command.operation == "retire":
            return None
        manifest, gateway = await self._source(command.scope)
        staged = OntologyStagedProjection(
            target.snapshot_digest,
            target.source_projection_digest,
            target.source_generation,
        )
        return await validate_snapshot_against_current_graph(
            snapshots=self._snapshots,
            staged=staged,
            gateway=gateway,
            manifest=manifest,
            as_of=self._clock(),
            embedding_space_id=self._space,
            embedding_model_version=self._model,
            embedding_dimension=self._dimension,
            validator_id=validator_id,
        )

    def _target(self, validated: _ValidatedBody) -> IndexGeneration:
        prepared, validation = validated.prepared, validated.validation
        if (
            validation.validator_id != "Heimdall"
            or validation.snapshot_digest != prepared.snapshot_digest
            or validation.generation_digest != prepared.generation_digest
            or validation.source_generation != prepared.request.source_generation
            or validation.source_projection_digest != prepared.source_projection_digest
            or validation.manifest_digest != prepared.manifest_digest
            or validation.principal_scope_digest != prepared.request.scope.principal_scope_digest
        ):
            raise ValueError("ontology independent validation does not match prepared identity")
        return IndexGeneration(
            scope=prepared.request.scope,
            manifest_digest=prepared.manifest_digest,
            ontology_release_digest=prepared.ontology_release_digest,
            source_generation=prepared.request.source_generation,
            source_projection_digest=prepared.source_projection_digest,
            snapshot_digest=prepared.snapshot_digest,
            vector_digest=prepared.vector_digest,
            generation_digest=prepared.generation_digest,
            validation_receipt_digest=validation.receipt_digest,
            embedding_space_id=self._space,
            embedding_model_version=self._model,
            embedding_dimension=self._dimension,
        )

    async def _source(
        self, scope: IndexScope
    ) -> tuple[QueryManifest, SecuredObjectSetQueryGateway]:
        manifest, gateway = await self._resolve_source(scope)
        if (
            manifest.principal_role != scope.role
            or manifest.purposes != (scope.purpose,)
            or manifest.coverage_receipt.principal_scope_digest != scope.principal_scope_digest
        ):
            raise ValueError("ontology source resolver returned a different authenticated scope")
        return manifest, gateway

    async def _message(self, key: str, owner: str) -> ContextIndexMessage:
        return await self.journal.message(key, owner)

    async def _require_published_record(self, message: ContextIndexMessage, owner: str) -> None:
        await self.journal.require_message(message, owner)

    async def _replay(self, message: ContextIndexMessage, owner: str) -> ContextIndexMessage | None:
        return await self.journal.replay(message, owner)

    async def _record(
        self,
        request: ContextIndexMessage,
        result: ContextIndexMessage,
        owner: str,
    ) -> ContextIndexMessage:
        return await self.journal.record(request, result, owner)

    async def _immutable(self, key: str, value: dict[str, object]) -> None:
        await self.journal.immutable(key, value)
