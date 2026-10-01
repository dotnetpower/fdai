"""Bounded off-path schema fingerprint clustering for Huginn."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai_service_contracts.compatibility import canonical_digest

from fdai.agents._framework.topics import stable_idempotency_key
from fdai.shared.providers.state_store import StateStore

_MAX_FINGERPRINTS = 128
_STATE_PREFIX = "pantheon/huginn/schema-clusters/"


def schema_fingerprint(raw: Mapping[str, Any]) -> dict[str, str]:
    """Return a content-free top-level field and value-kind fingerprint."""

    return {
        str(key)[:128]: _kind(value)
        for key, value in sorted(raw.items(), key=lambda item: str(item[0]))[:64]
        if str(key) != "operator_request_receipt"
    }


@dataclass(frozen=True, slots=True)
class SchemaClusterEvidence:
    """Inert evidence record published by Huginn maintenance."""

    payload: dict[str, Any]
    state_key: str


class HuginnSchemaLearningLedger:
    """Bounded fingerprint store; clustering stays off the hot path."""

    def __init__(
        self, *, state_store: StateStore | None, capacity: int = _MAX_FINGERPRINTS
    ) -> None:
        if capacity < 1:
            raise ValueError("schema learning capacity MUST be positive")
        self._state_store = state_store
        self._capacity = capacity
        self._pending: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def record(self, raw: Mapping[str, Any]) -> None:
        """Record only a bounded content-free fingerprint."""

        source = str(raw.get("source") or "unknown")[:128]
        event_type = str(raw.get("event_type") or "generic")[:128]
        fields = schema_fingerprint(raw)
        digest = canonical_digest({"source": source, "event_type": event_type, "fields": fields})
        self._pending[digest] = {
            "schema_version": "1.0.0",
            "kind": "huginn.schema_cluster_evidence",
            "event_type": "schema_cluster.evidence",
            "source": source,
            "correlation_id": "schema-cluster:" + digest[:32],
            "resource_id": "schema-fingerprint:" + digest[:32],
            "observed_event_type": event_type,
            "schema_fingerprint_digest": digest,
            "field_kinds": fields,
            "authority": "inert_evidence_only",
            "normalization_changed": False,
            "idempotency_key": stable_idempotency_key(
                "huginn-schema-cluster",
                source,
                event_type,
                digest,
            ),
        }
        self._pending.move_to_end(digest)
        while len(self._pending) > self._capacity:
            self._pending.popitem(last=False)

    async def next_evidence(self) -> SchemaClusterEvidence | None:
        """Return one unpublished inert evidence item, idempotent across restarts."""

        for digest, payload in list(self._pending.items()):
            state_key = _STATE_PREFIX + digest
            if self._state_store is not None:
                created = await self._state_store.write_state_if_absent(
                    state_key,
                    {
                        "schema_version": "1.0.0",
                        "kind": "huginn.schema_cluster_published",
                        "schema_fingerprint_digest": digest,
                    },
                )
                if not created:
                    del self._pending[digest]
                    continue
            del self._pending[digest]
            return SchemaClusterEvidence(payload=dict(payload), state_key=state_key)
        return None

    def pending_count(self) -> int:
        """Return bounded pending fingerprints for health and tests."""

        return len(self._pending)


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list | tuple):
        return "array"
    return "other"


__all__ = [
    "HuginnSchemaLearningLedger",
    "SchemaClusterEvidence",
    "schema_fingerprint",
]
