"""Project catalog-matched subscription identity reads into semantic terminal results."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID, uuid5

from fdai_operator_service.adapters.subscription_scope import (
    SubscriptionScopeEvidence,
    SubscriptionScopeIntentCatalog,
    SubscriptionScopeProviderError,
)
from fdai_service_contracts import (
    SemanticTurnDisposition,
    SemanticTurnRequest,
    SemanticTurnResult,
)

_IDENTITY_NAMESPACE = UUID(int=0)


class SubscriptionScopeProvider(Protocol):
    """Read one server-owned subscription scope without accepting a selector."""

    async def read(self) -> SubscriptionScopeEvidence: ...


class SubscriptionScopeResponder:
    """Answer one catalog-matched identity request without semantic model transport."""

    def __init__(
        self,
        *,
        catalog: SubscriptionScopeIntentCatalog,
        provider: SubscriptionScopeProvider,
    ) -> None:
        self._catalog = catalog
        self._provider = provider

    def supports(self, request: SemanticTurnRequest) -> bool:
        """Return whether the request is a complete deterministic subscription read."""
        return self._catalog.matches(request.utterance)

    async def respond(self, envelope: Mapping[str, object]) -> dict[str, object]:
        """Return one verified answer or a typed unavailable terminal projection."""
        semantic_payload = envelope.get("semantic_turn")
        if not isinstance(semantic_payload, Mapping):
            raise ValueError("semantic request payload is missing")
        request = SemanticTurnRequest.model_validate(semantic_payload)
        try:
            remaining = (request.deadline_at - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                raise TimeoutError
            async with asyncio.timeout(remaining):
                evidence = await self._provider.read()
        except (SubscriptionScopeProviderError, TimeoutError):
            result = SemanticTurnResult(
                disposition=SemanticTurnDisposition.HELD,
                reason_code="subscription_scope_unavailable",
                unavailable_reason="authoritative_evidence_unavailable",
                session_id=request.session_id,
                turn_id=request.turn_id,
                turn_sequence=request.turn_sequence,
                answer=_unavailable_answer(request.locale),
            )
            return _projection(
                envelope,
                result=result,
                recorded_at=cast(str, envelope["requested_at"]),
                payload={"deterministic_read": {"kind": "subscription_scope_identity"}},
            )

        result = SemanticTurnResult(
            disposition=SemanticTurnDisposition.ANSWERED,
            reason_code="subscription_scope_verified",
            semantic_route="deterministic_read",
            session_id=request.session_id,
            turn_id=request.turn_id,
            turn_sequence=request.turn_sequence,
            deterministic_receipt_digest=evidence.receipt_digest,
            evidence_refs=(evidence.evidence_ref,),
            checks_completed=1,
            checks_total=1,
            answer=_verified_answer(request.locale, evidence),
        )
        return _projection(
            envelope,
            result=result,
            recorded_at=evidence.observed_at.isoformat(),
            payload={
                "deterministic_read": {
                    "kind": "subscription_scope_identity",
                    "authority": "azure.resource_manager.subscription",
                    "receipt_digest": evidence.receipt_digest,
                    "execution_authority": False,
                }
            },
        )


def _projection(
    envelope: Mapping[str, object],
    *,
    result: SemanticTurnResult,
    recorded_at: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    result_payload = result.model_dump(mode="json", exclude_none=True)
    encoded = json.dumps(
        result_payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    result_digest = hashlib.sha256(encoded).hexdigest()
    request_id = cast(str, envelope["request_id"])
    return {
        "schema_version": "operator-deterministic-1.0.0",
        "projection_id": str(
            uuid5(_IDENTITY_NAMESPACE, f"deterministic-read\0{request_id}\0{result_digest}")
        ),
        "request_id": request_id,
        "correlation_id": envelope["correlation_id"],
        "idempotency_key": envelope["idempotency_key"],
        "status": result.disposition.value,
        "recorded_at": recorded_at,
        "payload": dict(payload),
        "semantic_result": result_payload,
    }


def _verified_answer(locale: str, evidence: SubscriptionScopeEvidence) -> str:
    observed = evidence.observed_at.isoformat()
    display_name = _escape_markdown(evidence.display_name)
    state = _escape_markdown(evidence.state)
    if locale.casefold().startswith("ko"):
        return (
            "## 현재 Azure 구독\n\n"
            f"- 이름: {display_name}\n"
            f"- 상태: {state}\n"
            f"- 구독 ID: `{evidence.masked_subscription_id}`\n"
            f"- 관측 시각: {observed}\n\n"
            "서버에 구성된 Azure Reader 범위에서 읽었습니다. 변경 작업은 수행하지 않았습니다."
        )
    return (
        "## Current Azure subscription\n\n"
        f"- Name: {display_name}\n"
        f"- State: {state}\n"
        f"- Subscription ID: `{evidence.masked_subscription_id}`\n"
        f"- Observed at: {observed}\n\n"
        "Read from the server-configured Azure Reader scope. No changes were made."
    )


def _unavailable_answer(locale: str) -> str:
    if locale.casefold().startswith("ko"):
        return "서버에 구성된 Azure 구독 정보를 읽을 수 없습니다. 변경 작업은 수행하지 않았습니다."
    return (
        "The server-configured Azure subscription information is unavailable. No changes were made."
    )


def _escape_markdown(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    for marker in "`*_{}[]()#+-.!|>~":
        escaped = escaped.replace(marker, f"\\{marker}")
    return escaped


__all__ = ["SubscriptionScopeProvider", "SubscriptionScopeResponder"]
