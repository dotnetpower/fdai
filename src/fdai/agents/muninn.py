"""Muninn - Memory (Wave 2 behavior).

Muninn owns the state / context store used by other agents. In Wave 2
the implementation is a simple in-memory KV; fork adapters swap in a
persistent backend (Postgres, pgvector).
"""

from __future__ import annotations

from typing import Any

from fdai.agents._framework.adapters import InMemoryStateStore
from fdai.agents._framework.base import Agent
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
    capped_list,
    mentioned,
)
from fdai.agents._framework.pantheon import _MUNINN


class Muninn(Agent):
    """Wave-2 Muninn: state / context store proxy."""

    def __init__(self, *, state_store: InMemoryStateStore | None = None) -> None:
        super().__init__(spec=_MUNINN)
        self.state_store = state_store or InMemoryStateStore()

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.turn":
            turn_id = str(payload.get("turn_id") or payload.get("id", ""))
            if turn_id:
                self.state_store.put("conversation_turns", turn_id, payload)
        elif (
            topic == "object.audit-entry"
            and payload.get("kind") == "document_ingestion"
            and payload.get("stage") == "protection_check"
            and (
                (
                    payload.get("audited_topic") == "object.verdict"
                    and payload.get("decision") == "admit"
                )
                or (
                    payload.get("audited_topic") == "object.approval"
                    and payload.get("decision") == "approved"
                )
            )
        ):
            await self._request_document_index(payload)

    async def _request_document_index(self, audited: dict[str, Any]) -> None:
        """Publish the content-free command that unlocks document indexing."""
        upload_id = str(audited.get("upload_id") or "")
        document_id = str(audited.get("document_id") or "")
        correlation_id = str(audited.get("correlation_id") or "")
        if not upload_id or not document_id or not correlation_id:
            self.record_behavior("document_index:invalid")
            return
        command = {
            "producer_principal": "Muninn",
            "kind": "document_ingestion",
            "stage": "indexing",
            "command": "index",
            "correlation_id": correlation_id,
            "idempotency_key": str(audited.get("idempotency_key") or ""),
            "resource_id": document_id,
            "document_id": document_id,
            "upload_id": upload_id,
        }
        self.record_behavior("document_index:requested")
        if self.bus is not None:
            await self.bus.publish("Muninn", "object.context-index", command)

    def get_context(self, bucket: str, key: str) -> Any | None:
        return self.state_store.get(bucket, key)

    def put_context(self, bucket: str, key: str, value: Any) -> None:
        self.state_store.put(bucket, key, value)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        data = self.state_store.data
        facts = {
            **capability_facts(self.spec),
            "buckets": capped_list(sorted(data)),
            "buckets_count": len(data),
            "total_keys": sum(len(v) for v in data.values()),
        }
        buckets = mentioned(question, data)
        if buckets:
            bucket = buckets[0]
            facts.update({"bucket": bucket, "key_count": len(data[bucket])})
            answer = f"Bucket {bucket!r} holds {len(data[bucket])} key(s)."
            return IntrospectionResult(answer=answer, facts=facts)
        answer = (
            f"Holding {len(data)} state bucket(s) with "
            f"{sum(len(v) for v in data.values())} key(s) total."
        )
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["Muninn"]
