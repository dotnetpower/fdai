"""Bind follow-up references from Core-owned stored result handles."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.reasoning_handles import ResultHandle, ResultHandleRef, TypedRowKey

from fdai.core.conversation.result_handle_store import (
    ResultHandleBinding,
    ResultHandleGetStatus,
    ResultHandleStore,
)
from fdai.core.ontology_platform import (
    ObjectPredicate,
    ObjectPredicateOperator,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
)
from fdai.core.ontology_platform.query_gateway import (
    SecuredObjectSetQueryGateway,
    UnsupportedObjectSetAsOfError,
)
from fdai.shared.ontology.acl import ProjectionRequest

from .semantic_reasoning_admission import FormAdmission
from .semantic_reasoning_form import MentionForm
from .semantic_reasoning_handles import (
    ReferenceBinding,
    ReferenceOutcome,
    ReferenceReceipt,
    reference_mention,
)

_RESOURCE = "Resource"
_SNAPSHOT_REFERENCE_FIELDS = frozenset(
    {
        "name",
        "revision_name",
        "ready_revision_name",
        "running_status",
        "source_observed_at",
        "inventory_read_at",
        "provisioning_status",
        "type",
        "status",
        "location",
    }
)


@dataclass(frozen=True, slots=True)
class StoredReferenceContext:
    """Per-request context needed to bind opaque result-handle references."""

    session_id: str
    references: tuple[ResultHandleRef, ...]
    store: ResultHandleStore


async def bind_stored_references(
    admission: FormAdmission,
    *,
    references: tuple[ResultHandleRef, ...],
    store: ResultHandleStore | None,
    binding: ResultHandleBinding,
    gateway: SecuredObjectSetQueryGateway,
    projection_request: ProjectionRequest,
    purpose: str,
    as_of: datetime | Callable[[], datetime],
) -> ReferenceReceipt | None:
    """Bind prior-result mentions from the newest opaque stored handle reference."""

    if store is None or not references:
        return None
    loaded = await store.get(
        references[0],
        binding=binding,
        allowed_snapshot_fields=_SNAPSHOT_REFERENCE_FIELDS,
    )
    outcome = _outcome_for_status(loaded.status)
    handle = loaded.handle
    row_map: dict[str, tuple[str, str | None]] = {}
    source_generation: str | None = None
    if loaded.status is ResultHandleGetStatus.BOUND and handle is not None:
        row_map, source_generation = await _authorized_row_map(
            handle,
            gateway=gateway,
            projection_request=projection_request,
            purpose=purpose,
            as_of=as_of,
        )
    bindings: dict[str, ReferenceBinding] = {}
    for goal in admission.form.goals:
        mention_id = reference_mention(admission, goal.id)
        if mention_id is None or mention_id in bindings:
            continue
        mention = admission.form.mention(mention_id)
        bindings[mention_id] = _bind_one(
            mention_id,
            mention.form,
            mention.position,
            handle_ref=references[0].handle_ref,
            row_keys=handle.row_keys if handle is not None else (),
            row_map=row_map,
            fallback=outcome,
            source_generation=source_generation,
        )
    return ReferenceReceipt(tuple(bindings.values()))


def _bind_one(
    mention_id: str,
    form: MentionForm,
    position: int | None,
    *,
    handle_ref: str,
    row_keys: tuple[TypedRowKey, ...],
    row_map: dict[str, tuple[str, str | None]],
    fallback: ReferenceOutcome,
    source_generation: str | None,
) -> ReferenceBinding:
    if fallback is not ReferenceOutcome.BOUND:
        return ReferenceBinding(mention_id, fallback, form, handle_id=handle_ref)
    if not row_keys:
        return ReferenceBinding(mention_id, ReferenceOutcome.EMPTY, form, handle_id=handle_ref)
    if form is MentionForm.ANAPHOR:
        if len(row_keys) != 1:
            return ReferenceBinding(
                mention_id, ReferenceOutcome.AMBIGUOUS, form, handle_id=handle_ref
            )
        selected = row_keys[0]
    else:
        if position is None or position == 0:
            return ReferenceBinding(
                mention_id, ReferenceOutcome.OUT_OF_RANGE, form, handle_id=handle_ref
            )
        index = position - 1 if position > 0 else len(row_keys) + position
        if index < 0 or index >= len(row_keys):
            return ReferenceBinding(
                mention_id, ReferenceOutcome.OUT_OF_RANGE, form, handle_id=handle_ref
            )
        selected = row_keys[index]
    row = row_map.get(selected.model_dump_json())
    if row is None:
        return ReferenceBinding(
            mention_id, ReferenceOutcome.UNAVAILABLE, form, handle_id=handle_ref
        )
    object_id, resource_type = row
    return ReferenceBinding(
        mention_id,
        ReferenceOutcome.BOUND,
        form,
        row_ids=(object_id,),
        handle_id=handle_ref,
        source_generation=source_generation,
        resource_type=resource_type,
    )


async def _authorized_row_map(
    handle: ResultHandle,
    *,
    gateway: SecuredObjectSetQueryGateway,
    projection_request: ProjectionRequest,
    purpose: str,
    as_of: datetime | Callable[[], datetime],
) -> tuple[dict[str, tuple[str, str | None]], str | None]:
    row_keys = handle.row_keys
    if not row_keys:
        return {}, None
    expected = {key.model_dump_json(): key for key in row_keys}
    if handle.row_identities:
        return await _authorized_identity_row_map(
            handle,
            expected=expected,
            gateway=gateway,
            projection_request=projection_request,
            purpose=purpose,
            as_of=as_of,
        )
    try:
        secured = await gateway.materialize(
            ObjectSetDefinition(
                selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name=_RESOURCE),
                as_of=as_of() if callable(as_of) else as_of,
                purpose=purpose,
                limit=1000,
                include_relationships=False,
            ),
            projection_request=projection_request,
        )
    except UnsupportedObjectSetAsOfError:
        return {}, None
    if secured.receipt.truncated:
        return {}, secured.receipt.source_generation
    mapped: dict[str, tuple[str, str | None]] = {}
    for record in secured.materialization.graph.objects:
        kind = record.properties.get("type")
        for candidate in _candidate_row_keys(record.id):
            dumped = candidate.model_dump_json()
            if dumped in expected:
                mapped[dumped] = (record.id, kind if isinstance(kind, str) else None)
    return mapped, secured.receipt.source_generation


async def _authorized_identity_row_map(
    handle: ResultHandle,
    *,
    expected: dict[str, TypedRowKey],
    gateway: SecuredObjectSetQueryGateway,
    projection_request: ProjectionRequest,
    purpose: str,
    as_of: datetime | Callable[[], datetime],
) -> tuple[dict[str, tuple[str, str | None]], str | None]:
    try:
        secured = await gateway.materialize(
            ObjectSetDefinition(
                selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name=_RESOURCE),
                predicates=(
                    ObjectPredicate(
                        property="id",
                        operator=ObjectPredicateOperator.IN,
                        values=handle.row_identities,
                    ),
                ),
                as_of=as_of() if callable(as_of) else as_of,
                purpose=purpose,
                limit=len(handle.row_identities),
                include_relationships=False,
            ),
            projection_request=projection_request,
        )
    except UnsupportedObjectSetAsOfError:
        return {}, None
    if secured.receipt.truncated:
        return {}, secured.receipt.source_generation
    readable = {record.id: record for record in secured.materialization.graph.objects}
    mapped: dict[str, tuple[str, str | None]] = {}
    for row_key, identity in zip(handle.row_keys, handle.row_identities, strict=True):
        record = readable.get(identity)
        dumped = row_key.model_dump_json()
        if record is None or dumped not in expected:
            continue
        if dumped not in {
            candidate.model_dump_json() for candidate in _candidate_row_keys(identity)
        }:
            continue
        kind = record.properties.get("type")
        mapped[dumped] = (record.id, kind if isinstance(kind, str) else None)
    return mapped, secured.receipt.source_generation


def _candidate_row_keys(object_id: str) -> tuple[TypedRowKey, TypedRowKey]:
    return (
        TypedRowKey(
            row_type="semantic_query_row",
            row_digest=content_digest({"row_id": object_id}),
        ),
        TypedRowKey(
            row_type="semantic_query_row",
            row_digest=content_digest({"node_id": "resources", "row_id": object_id}),
        ),
    )


def _outcome_for_status(status: ResultHandleGetStatus) -> ReferenceOutcome:
    return {
        ResultHandleGetStatus.BOUND: ReferenceOutcome.BOUND,
        ResultHandleGetStatus.FOREIGN: ReferenceOutcome.FOREIGN,
        ResultHandleGetStatus.UNAVAILABLE: ReferenceOutcome.UNAVAILABLE,
        ResultHandleGetStatus.EXPIRED: ReferenceOutcome.EXPIRED,
    }[status]


__all__ = ["bind_stored_references"]
