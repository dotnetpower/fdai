"""Decode and project one bounded Operator semantic turn."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid5

from fdai.core.conversation.semantic_runtime import (
    SemanticTurnResult as RuntimeSemanticTurnResult,
)
from fdai.core.conversation.session import Principal, Role, Turn
from fdai_service_contracts import (
    OperatorRole,
    SemanticTurnDisposition,
    SemanticTurnRequest,
)
from fdai_service_contracts import (
    SemanticTurnResult as ContractSemanticTurnResult,
)
from fdai_service_contracts.ontology_query import TaskStatus, content_digest

from .contract_codecs import (
    OPERATOR_PROJECTION_PRODUCER_V12,
    OPERATOR_REQUEST_CONSUMER_V12,
)

_PROJECTION_NAMESPACE = UUID("00000000-0000-0000-0000-000000000000")
_ROLE_ORDER = (
    OperatorRole.READER,
    OperatorRole.CONTRIBUTOR,
    OperatorRole.APPROVER,
    OperatorRole.OWNER,
)
_ROLE_MAP = {
    OperatorRole.READER: Role.READER,
    OperatorRole.CONTRIBUTOR: Role.CONTRIBUTOR,
    OperatorRole.APPROVER: Role.APPROVER,
    OperatorRole.OWNER: Role.OWNER,
}


class SemanticTurnRejectedError(ValueError):
    """Reject one malformed or unauthorized semantic request before runtime I/O."""


class SemanticTurnRuntime(Protocol):
    """Subset of ``SemanticConversationRuntime`` required by the event processor."""

    async def handle(
        self,
        *,
        utterance: str,
        prior_turns: tuple[Turn, ...],
        principal: Principal,
        cancelled: asyncio.Event | None = None,
    ) -> RuntimeSemanticTurnResult: ...


class SemanticTurnResultStore(Protocol):
    """Atomically retain the canonical projection for one idempotency key."""

    async def get(self, idempotency_key: str) -> bytes | None: ...

    async def put_if_absent(self, idempotency_key: str, projection: bytes) -> bool: ...


class SemanticTurnProcessor:
    """Validate, execute, evidence-gate, and idempotently project semantic turns.

    The injected runtime may be unavailable. In that state every valid request
    terminates as a schema-valid hold without fabricating model or provider evidence.
    """

    def __init__(
        self,
        *,
        runtime: SemanticTurnRuntime | None,
        results: SemanticTurnResultStore,
        purpose: str = "operations-review",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not purpose:
            raise ValueError("semantic turn purpose MUST be non-empty")
        self._runtime = runtime
        self._results = results
        self._purpose = purpose
        self._now = now or (lambda: datetime.now(UTC))

    async def process(
        self,
        payload: Mapping[str, Any],
        *,
        cancelled: asyncio.Event | None = None,
    ) -> bytes:
        """Return one canonical v1.2 projection or reject invalid boundary input."""

        envelope, request, requested_at = _decode_request(payload)
        principal = _principal(request)
        if request.purpose != self._purpose:
            raise SemanticTurnRejectedError("semantic_purpose_not_allowed")

        idempotency_key = str(envelope["idempotency_key"])
        try:
            prior = await self._results.get(idempotency_key)
        except Exception:  # noqa: BLE001 - persistence detail must not cross the wire
            return self._held_projection(
                envelope,
                request,
                reason_code="semantic_result_store_unavailable",
            )
        if prior is not None:
            try:
                return _canonical_projection(prior)
            except Exception:  # noqa: BLE001 - corrupt persistence fails closed
                return self._held_projection(
                    envelope,
                    request,
                    reason_code="semantic_result_store_unavailable",
                )

        result = await self._execute(
            request=request,
            requested_at=requested_at,
            principal=principal,
            cancelled=cancelled,
        )
        projection = self._projection(envelope, request, result)
        try:
            created = await self._results.put_if_absent(idempotency_key, projection)
            if created:
                return projection
            winner = await self._results.get(idempotency_key)
        except Exception:  # noqa: BLE001 - persistence detail must not cross the wire
            return self._held_projection(
                envelope,
                request,
                reason_code="semantic_result_store_unavailable",
            )
        if winner is None:
            return self._held_projection(
                envelope,
                request,
                reason_code="semantic_result_store_unavailable",
            )
        try:
            return _canonical_projection(winner)
        except Exception:  # noqa: BLE001 - corrupt persistence fails closed
            return self._held_projection(
                envelope,
                request,
                reason_code="semantic_result_store_unavailable",
            )

    async def _execute(
        self,
        *,
        request: SemanticTurnRequest,
        requested_at: datetime,
        principal: Principal,
        cancelled: asyncio.Event | None,
    ) -> ContractSemanticTurnResult:
        if request.cancelled or (cancelled is not None and cancelled.is_set()):
            return _terminal_result(request, "cancelled", "semantic_request_cancelled")
        now = _aware_utc(self._now(), field="semantic processor clock")
        deadline = _aware_utc(request.deadline_at, field="semantic deadline_at")
        remaining = (deadline - now).total_seconds()
        if remaining <= 0:
            return _terminal_result(request, "held", "semantic_deadline_exceeded")
        if self._runtime is None:
            return _terminal_result(request, "held", "semantic_runtime_unavailable")

        runtime_cancelled = asyncio.Event()
        runtime_task = asyncio.create_task(
            self._runtime.handle(
                utterance=request.utterance,
                prior_turns=_prior_turns(request, requested_at=requested_at),
                principal=principal,
                cancelled=runtime_cancelled,
            )
        )
        cancellation_task = asyncio.create_task(cancelled.wait()) if cancelled is not None else None
        waiters: set[asyncio.Task[object]] = {runtime_task}
        if cancellation_task is not None:
            waiters.add(cancellation_task)
        try:
            done, pending = await asyncio.wait(
                waiters,
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancellation_task is not None and cancellation_task in done:
                runtime_cancelled.set()
                runtime_task.cancel()
                await asyncio.gather(runtime_task, return_exceptions=True)
                return _terminal_result(request, "cancelled", "semantic_request_cancelled")
            if runtime_task not in done:
                runtime_cancelled.set()
                runtime_task.cancel()
                await asyncio.gather(runtime_task, return_exceptions=True)
                return _terminal_result(request, "held", "semantic_deadline_exceeded")
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            runtime_result = runtime_task.result()
            return _project_runtime_result(request, runtime_result)
        except asyncio.CancelledError:
            runtime_cancelled.set()
            runtime_task.cancel()
            await asyncio.gather(runtime_task, return_exceptions=True)
            raise
        except Exception:  # noqa: BLE001 - runtime/provider detail must not cross the wire
            return _terminal_result(request, "held", "semantic_runtime_failed")
        finally:
            if cancellation_task is not None and not cancellation_task.done():
                cancellation_task.cancel()
                await asyncio.gather(cancellation_task, return_exceptions=True)

    def _projection(
        self,
        envelope: Mapping[str, Any],
        request: SemanticTurnRequest,
        result: ContractSemanticTurnResult,
    ) -> bytes:
        semantic_result = result.model_dump(mode="json", exclude_none=True)
        evidence_digest = content_digest(semantic_result)
        projection_id = str(
            uuid5(
                _PROJECTION_NAMESPACE,
                f"{envelope['request_id']}\0{evidence_digest}",
            )
        )
        projection = {
            "schema_version": "1.2.0",
            "projection_id": projection_id,
            "request_id": envelope["request_id"],
            "correlation_id": envelope["correlation_id"],
            "idempotency_key": envelope["idempotency_key"],
            "status": result.disposition.value,
            "recorded_at": _aware_utc(self._now(), field="semantic processor clock").isoformat(),
            "payload": {"request_kind": "semantic_query"},
            "evidence_digest": evidence_digest,
            "semantic_result": semantic_result,
        }
        return OPERATOR_PROJECTION_PRODUCER_V12.encode(projection)

    def _held_projection(
        self,
        envelope: Mapping[str, Any],
        request: SemanticTurnRequest,
        *,
        reason_code: str,
    ) -> bytes:
        return self._projection(
            envelope,
            request,
            _terminal_result(request, "held", reason_code),
        )


def _decode_request(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], SemanticTurnRequest, datetime]:
    try:
        envelope = OPERATOR_REQUEST_CONSUMER_V12.decode_mapping(payload)
        if envelope.get("request_kind") != "semantic_query":
            raise SemanticTurnRejectedError("semantic_request_kind_required")
        semantic_turn = envelope.get("semantic_turn")
        if not isinstance(semantic_turn, dict):
            raise SemanticTurnRejectedError("semantic_turn_required")
        request = SemanticTurnRequest.model_validate(semantic_turn)
        requested_at_raw = envelope["requested_at"]
        if not isinstance(requested_at_raw, str):
            raise SemanticTurnRejectedError("semantic_requested_at_invalid")
        requested_at = _aware_utc(
            datetime.fromisoformat(requested_at_raw.replace("Z", "+00:00")),
            field="semantic requested_at",
        )
        _aware_utc(request.deadline_at, field="semantic deadline_at")
        return envelope, request, requested_at
    except SemanticTurnRejectedError:
        raise
    except Exception as exc:
        raise SemanticTurnRejectedError("semantic_request_invalid") from exc


def _principal(request: SemanticTurnRequest) -> Principal:
    ordinary_roles = [role for role in _ROLE_ORDER if role in request.principal.roles]
    if not ordinary_roles:
        raise SemanticTurnRejectedError("semantic_break_glass_only")
    selected = ordinary_roles[-1]
    return Principal(id=request.principal.subject_id, role=_ROLE_MAP[selected])


def _prior_turns(
    request: SemanticTurnRequest,
    *,
    requested_at: datetime,
) -> tuple[Turn, ...]:
    return tuple(
        Turn(
            turn_id=f"{request.turn_id}:prior:{index}",
            direction="inbound" if item.role == "user" else "outbound",
            content=item.content,
            timestamp=requested_at,
        )
        for index, item in enumerate(request.prior_turns)
    )


def _project_runtime_result(
    request: SemanticTurnRequest,
    result: RuntimeSemanticTurnResult,
) -> ContractSemanticTurnResult:
    if result.disposition != "answered":
        reason_codes = {
            "clarification": "semantic_clarification_required",
            "held": "semantic_evidence_held",
            "unsupported": "semantic_request_unsupported",
            "action_draft": "semantic_action_draft",
            "cancelled": "semantic_request_cancelled",
        }
        reason_code = reason_codes.get(result.disposition, "semantic_runtime_failed")
        disposition = result.disposition if result.disposition in reason_codes else "held"
        return _terminal_result(request, disposition, reason_code)

    planning = result.planning
    plan = planning.plan
    execution = result.execution
    if (
        plan is None
        or execution is None
        or result.intent_graph is None
        or result.intent_graph_evidence is None
        or planning.manifest_digest is None
        or planning.manifest_digest != plan.semantic_catalog_digest
        or execution.plan_digest != plan.plan_digest
        or execution.status != "completed"
        or not execution.receipts
        or any(receipt.status is not TaskStatus.COMPLETED for receipt in execution.receipts)
    ):
        return _terminal_result(request, "held", "semantic_evidence_incomplete")
    evidence_refs = tuple(
        dict.fromkeys(
            evidence_ref for receipt in execution.receipts for evidence_ref in receipt.evidence_refs
        )
    )
    if not evidence_refs or len(evidence_refs) > 12:
        return _terminal_result(request, "held", "semantic_evidence_incomplete")
    execution_receipt_digest = content_digest(
        {
            "plan_digest": execution.plan_digest,
            "status": execution.status,
            "output_node_ids": execution.output_node_ids,
            "receipts": [receipt.model_dump(mode="json") for receipt in execution.receipts],
        }
    )
    checks_total = len(execution.receipts)
    return ContractSemanticTurnResult(
        disposition=SemanticTurnDisposition.ANSWERED,
        reason_code="semantic_answer_verified",
        session_id=request.session_id,
        turn_id=request.turn_id,
        turn_sequence=request.turn_sequence,
        ontology_release_digest=plan.ontology_release_digest,
        principal_manifest_digest=planning.manifest_digest,
        plan_digest=plan.plan_digest,
        execution_receipt_digest=execution_receipt_digest,
        intent_graph=result.intent_graph,
        intent_graph_evidence=result.intent_graph_evidence,
        evidence_refs=evidence_refs,
        checks_completed=checks_total,
        checks_total=checks_total,
    )


def _terminal_result(
    request: SemanticTurnRequest,
    disposition: str,
    reason_code: str,
) -> ContractSemanticTurnResult:
    return ContractSemanticTurnResult(
        disposition=SemanticTurnDisposition(disposition),
        reason_code=reason_code,
        session_id=request.session_id,
        turn_id=request.turn_id,
        turn_sequence=request.turn_sequence,
    )


def _canonical_projection(encoded: bytes) -> bytes:
    loaded = json.loads(encoded)
    if not isinstance(loaded, dict):
        raise ValueError("stored semantic projection MUST be an object")
    return OPERATOR_PROJECTION_PRODUCER_V12.encode(loaded)


def _aware_utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SemanticTurnRejectedError(f"{field.replace(' ', '_')}_invalid")
    return value.astimezone(UTC)


__all__ = [
    "SemanticTurnProcessor",
    "SemanticTurnRejectedError",
    "SemanticTurnResultStore",
    "SemanticTurnRuntime",
]
