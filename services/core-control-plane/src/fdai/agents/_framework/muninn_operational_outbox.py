"""Muninn - Memory (Wave 2 behavior).

Muninn owns the state / context store used by other agents. In Wave 2
the implementation is a simple in-memory KV; fork adapters swap in a
persistent backend (Postgres, pgvector).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from fdai.agents._framework.adapters import canonical_json_digest
from fdai.agents._framework.base import Agent
from fdai.agents._framework.outbox_publication import (
    PublicationClaim,
    claim_expired,
    new_publication_claim_owner,
    publish_claimed_outbox,
)
from fdai.core.operational_learning import (
    OperatingPatternCompiler,
    PatternCase,
)
from fdai.core.operational_learning.patterns import valid_pattern_publication_envelope


def _readiness_generated_at(record: Mapping[str, Any]) -> datetime | None:
    raw = record.get("generated_at")
    if not isinstance(raw, str):
        return None
    try:
        generated_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return generated_at if generated_at.tzinfo is not None else None


_MAX_OPERATING_PATTERN_CASES = 100
_MAX_CONVERSATION_PROJECTIONS = 50_000
_CONVERSATION_PROJECTION_RECOVERY_PAGE = 128
_PUBLICATION_OUTBOX_RETAIN = 5_000
# Compaction runs every N published rows (and on maintenance) so a publish costs O(1) amortized.
_PUBLICATION_COMPACTION_INTERVAL = 64
_PUBLICATION_CAS_ATTEMPTS = 8
_PUBLICATION_CLAIM_LEASE = timedelta(minutes=5)
_PUBLICATION_MAINTENANCE_PAGE = 16
_PROJECTION_PREFIX = "pantheon/muninn/conversation-projections"
_OPERATIONAL_OUTBOX_PREFIX = "pantheon/muninn/operational-outbox"
_DEFAULT_PROVIDER_TIMEOUT_SECONDS = 5.0
_MAX_CONTEXT_FETCH_SAMPLES = 512
_MAX_CONTEXT_UNAVAILABLE_FACTS = 128
_PROTECTED_CONVERSATION_BUCKETS = frozenset(
    {"conversation_turns", "conversations", "user_preferences"}
)


class MuninnOperationalOutboxMixin:
    """Behavior-preserving extracted runtime methods."""

    _publication_outbox_last_failure: dict[str, Any] | None

    async def _materialize_operating_pattern(self: Any, payload: dict[str, Any]) -> None:
        if not valid_pattern_publication_envelope(payload):
            self.record_behavior("operating_pattern:invalid_payload")
            return
        if (
            payload.get("producer_principal") != "Norns"
            or payload.get("kind") != "operational_pattern"
        ):
            self.record_behavior("operating_pattern:invalid_producer")
            return
        if self._durable_state_store is None:
            raise RuntimeError("operating pattern durable store is unavailable")
        pattern_id = payload.get("pattern_id")
        cohort_key = payload.get("cohort_key")
        scope = payload.get("access_scope_digest")
        purpose = payload.get("purpose")
        snapshot_key = payload.get("cohort_snapshot_ref")
        if (
            not isinstance(pattern_id, str)
            or len(pattern_id) != 64
            or any(character not in "0123456789abcdef" for character in pattern_id)
            or not isinstance(cohort_key, str)
            or not cohort_key.startswith("operational-case-fingerprint-cohort:v2:")
            or len(cohort_key) != len("operational-case-fingerprint-cohort:v2:") + 64
            or payload.get("correlation_id") != cohort_key
            or payload.get("idempotency_key") != f"operating-pattern:{pattern_id}"
            or not isinstance(snapshot_key, str)
            or not snapshot_key.startswith(f"{cohort_key}:snapshot:")
            or len(snapshot_key) != len(cohort_key) + len(":snapshot:") + 64
        ):
            self.record_behavior("operating_pattern:invalid_payload")
            return
        projections = self._case_projection_store(str(scope))
        cohort = await projections.read_state(snapshot_key)
        if (
            not isinstance(cohort, Mapping)
            or cohort.get("access_scope_digest") != scope
            or cohort.get("purpose") != purpose
        ):
            self.record_behavior("operating_pattern:scope_mismatch")
            return
        raw_cases = cohort.get("cases")
        if (
            not isinstance(raw_cases, list)
            or not 2 <= len(raw_cases) <= _MAX_OPERATING_PATTERN_CASES
        ):
            self.record_behavior("operating_pattern:invalid_payload")
            return
        try:
            if snapshot_key != f"{cohort_key}:snapshot:{_cohort_digest(raw_cases)}":
                self.record_behavior("operating_pattern:invalid_snapshot")
                return
            cases = tuple(PatternCase.from_mapping(record["case"]) for record in raw_cases)
            compiled = OperatingPatternCompiler().compile(
                cases, reviewed_at=self._case_history_clock()
            )
        except (KeyError, TypeError, ValueError):
            self.record_behavior("operating_pattern:invalid_payload")
            return
        if compiled is None or compiled.pattern_id != pattern_id:
            self.record_behavior("operating_pattern:cohort_changed")
            return
        if self._case_history is None:
            raise RuntimeError("operating pattern case evidence is unavailable")
        for case_ref in compiled.immutable_case_refs:
            if not await self._case_history.current_revision_available(
                case_ref=case_ref,
                access_scope_digest=str(scope),
                purpose=str(purpose),
                now=self._case_history_clock(),
            ):
                self.record_behavior("operating_pattern:case_unavailable")
                return
        record = {
            "schema_version": "1.0.0",
            "pattern_id": pattern_id,
            "access_scope_digest": scope,
            "purpose": purpose,
            "cohort_key": cohort_key,
            "candidate": compiled.to_rule_candidate_mapping(),
            "cases": [case.to_mapping() for case in cases],
            "execution_authority": False,
            "promotion_authority": False,
        }
        key = f"{cohort_key}:pattern:{pattern_id}"
        existing = await projections.read_state(key)
        if existing is not None and existing != record:
            raise ValueError("operating pattern immutable identity conflict")
        if existing is None:
            await projections.write_state_if_absent(key, record)
            if await projections.read_state(key) != record:
                raise ValueError("operating pattern immutable identity conflict")
        if self.bus is not None:
            snapshot = {
                "producer_principal": "Muninn",
                "kind": "operating_pattern_retained",
                "correlation_id": cohort_key,
                "idempotency_key": f"operating-pattern-retained:{pattern_id}",
                "pattern_id": pattern_id,
                "access_scope_digest": scope,
                "purpose": purpose,
                "execution_authority": False,
                "promotion_authority": False,
            }
            outbox_key = f"{_OPERATIONAL_OUTBOX_PREFIX}/operating-pattern-retained/{pattern_id}"
            await self._publish_with_outbox(outbox_key, "object.state-snapshot", snapshot)
        self.record_behavior("operating_pattern:retained")

    async def _claim_publication(
        self: Any,
        key: str,
        topic: str | dict[str, Any],
        payload: dict[str, Any] | None = None,
    ) -> PublicationClaim | None:
        if payload is None:
            if not isinstance(topic, dict):
                raise ValueError("Muninn publication payload is invalid")
            actual_payload = topic
            actual_topic = "object.context-index"
        elif isinstance(topic, str):
            actual_payload = payload
            actual_topic = topic
        else:
            raise ValueError("Muninn publication topic is invalid")
        store = self._durable_state_store
        if store is None:
            return PublicationClaim(
                owner=new_publication_claim_owner(self.spec.name),
                claimed_at=self._case_history_clock().isoformat(),
            )
        idempotency_key = str(actual_payload.get("idempotency_key") or "")
        correlation_id = str(actual_payload.get("correlation_id") or "")
        if not idempotency_key or not correlation_id:
            raise ValueError("Muninn publication payload requires correlation and idempotency")
        record = {
            "kind": "muninn_publication_outbox",
            "revision": 1,
            "state": "pending",
            "outbox_key": key,
            "idempotency_key": idempotency_key,
            "correlation_id": correlation_id,
            "topic": actual_topic,
            "payload": dict(actual_payload),
            "payload_digest": _payload_digest(actual_payload),
        }
        await store.write_state_with_audit_if_absent(
            key,
            record,
            {
                "kind": "muninn_publication_checkpointed",
                "principal": "Muninn",
                "idempotency_key": idempotency_key,
                "correlation_id": correlation_id,
                "grants_authority": False,
            },
        )
        for attempt in range(_PUBLICATION_CAS_ATTEMPTS):
            existing = await store.read_state(key)
            if existing is None or existing.get("payload_digest") != record["payload_digest"]:
                raise ValueError("Muninn publication outbox identity conflict")
            if existing.get("topic") != actual_topic or existing.get("payload") != actual_payload:
                raise ValueError("Muninn publication outbox identity conflict")
            if existing.get("state") == "published":
                return None
            now = self._case_history_clock()
            if existing.get("state") == "publishing" and not claim_expired(
                claimed_at=existing.get("claimed_at"),
                now=now,
                lease=_PUBLICATION_CLAIM_LEASE,
            ):
                return None
            if existing.get("state") not in {"pending", "publishing"}:
                raise ValueError("Muninn publication outbox state is invalid")
            revision = int(existing.get("revision", 0))
            claimed_at = now.isoformat()
            claim_owner = new_publication_claim_owner(self.spec.name)
            updated = {
                **dict(existing),
                "revision": revision + 1,
                "state": "publishing",
                "claim_owner": claim_owner,
                "claimed_at": claimed_at,
            }
            if await store.compare_and_set_state_with_audit(
                key,
                updated,
                expected_revision=revision,
                audit_entry={
                    "kind": "muninn_publication_claimed",
                    "principal": "Muninn",
                    "idempotency_key": idempotency_key,
                    "correlation_id": correlation_id,
                    "grants_authority": False,
                },
            ):
                self._publication_outbox_claimed_at.set(key, claimed_at)
                return PublicationClaim(owner=claim_owner, claimed_at=claimed_at)
            self.record_behavior("publication_outbox:cas_retry")
            await asyncio.sleep(0 if attempt == 0 else min(0.001 * attempt, 0.01))
        self.record_behavior("publication_outbox:cas_exhausted")
        raise RuntimeError("Muninn publication outbox CAS did not converge")

    async def _mark_publication_published(
        self: Any,
        key: str,
        payload: dict[str, Any],
        claim: PublicationClaim,
    ) -> bool:
        store = self._durable_state_store
        if store is None:
            return True
        for attempt in range(_PUBLICATION_CAS_ATTEMPTS):
            current = await store.read_state(key)
            if current is None or current.get("payload_digest") != _payload_digest(payload):
                raise ValueError("Muninn publication outbox identity conflict")
            if current.get("state") == "published":
                return False
            if current.get("state") != "publishing":
                raise ValueError("Muninn publication outbox state is invalid")
            if (
                str(current.get("claim_owner") or "") != claim.owner
                or str(current.get("claimed_at") or "") != claim.claimed_at
            ):
                return False
            revision = int(current.get("revision", 0))
            updated = {
                **dict(current),
                "revision": revision + 1,
                "state": "published",
                "claim_owner": "",
                "claimed_at": "",
            }
            if await store.compare_and_set_state_with_audit(
                key,
                updated,
                expected_revision=revision,
                audit_entry={
                    "kind": "muninn_publication_published",
                    "principal": "Muninn",
                    "idempotency_key": updated["idempotency_key"],
                    "correlation_id": updated["correlation_id"],
                    "grants_authority": False,
                },
            ):
                self._publication_outbox_claimed_at.pop(key, None)
                self._publications_since_compaction += 1
                if self._publications_since_compaction >= _PUBLICATION_COMPACTION_INTERVAL:
                    await self._compact_publication_outbox()
                return True
            self.record_behavior("publication_outbox:cas_retry")
            self._publication_outbox_last_failure = {
                "reason": "cas_retry",
                "observed_at": self._case_history_clock().isoformat(),
            }
            await asyncio.sleep(0 if attempt == 0 else min(0.001 * attempt, 0.01))
        self.record_behavior("publication_outbox:cas_exhausted")
        self._publication_outbox_last_failure = {
            "reason": "cas_exhausted",
            "observed_at": self._case_history_clock().isoformat(),
        }
        raise RuntimeError("Muninn publication outbox CAS did not converge")

    async def _release_publication_claim(
        self: Any,
        key: str,
        payload: dict[str, Any],
        claim: PublicationClaim,
    ) -> None:
        store = self._durable_state_store
        if store is None:
            return
        for attempt in range(_PUBLICATION_CAS_ATTEMPTS):
            current = await store.read_state(key)
            if current is None or current.get("state") != "publishing":
                return
            if current.get("payload_digest") != _payload_digest(payload):
                raise ValueError("Muninn publication outbox identity conflict")
            if (
                str(current.get("claim_owner") or "") != claim.owner
                or str(current.get("claimed_at") or "") != claim.claimed_at
            ):
                return
            revision = int(current.get("revision", 0))
            updated = {
                **dict(current),
                "revision": revision + 1,
                "state": "pending",
                "claim_owner": "",
                "claimed_at": "",
            }
            if await store.compare_and_set_state(
                key,
                updated,
                expected_revision=revision,
            ):
                self._publication_outbox_claimed_at.pop(key, None)
                return
            await asyncio.sleep(0 if attempt == 0 else min(0.001 * attempt, 0.01))
        raise RuntimeError("Muninn publication outbox release CAS did not converge")

    async def _publish_with_outbox(
        self: Any,
        outbox_key: str,
        topic: str,
        payload: dict[str, Any],
    ) -> bool:
        if self.bus is None:
            return False
        bus = self.bus
        claim = await self._claim_publication(outbox_key, topic, payload)
        return await publish_claimed_outbox(
            claim,
            publish=lambda: bus.publish("Muninn", topic, payload),
            mark_published=lambda active_claim: self._mark_publication_published(
                outbox_key, payload, active_claim
            ),
            release=lambda active_claim: self._release_publication_claim(
                outbox_key, payload, active_claim
            ),
            lease=_PUBLICATION_CLAIM_LEASE,
        )

    async def _compact_publication_outbox(self: Any) -> None:
        store = self._durable_state_store
        if store is None:
            return
        await store.delete_states_beyond(
            _OPERATIONAL_OUTBOX_PREFIX + "/",
            retain_newest=_PUBLICATION_OUTBOX_RETAIN,
        )
        self._publications_since_compaction = 0

    async def maintenance_tick(self: Any) -> None:
        await Agent.maintenance_tick(self)
        await self.recover_operational_publications(limit=_PUBLICATION_MAINTENANCE_PAGE)
        if self._publications_since_compaction:
            await self._compact_publication_outbox()

    async def recover_operational_publications(
        self: Any,
        *,
        limit: int = _PUBLICATION_OUTBOX_RETAIN,
    ) -> int:
        """Republish durable operational outbox rows left pending before startup."""
        store = self._durable_state_store
        if store is None or self.bus is None:
            return 0
        published = 0
        attempted = 0
        while attempted < limit:
            remaining = limit - attempted
            pending_rows, _pending_total = await store.read_state_page(
                _OPERATIONAL_OUTBOX_PREFIX + "/",
                limit=remaining,
                field="state",
                value="pending",
            )
            publishing_rows, _publishing_total = await store.read_state_page(
                _OPERATIONAL_OUTBOX_PREFIX + "/",
                limit=remaining,
                field="state",
                value="publishing",
            )
            rows = (*pending_rows, *publishing_rows)
            if not rows:
                break
            progress = 0
            for row in rows[:remaining]:
                topic = row.get("topic")
                payload = row.get("payload")
                if topic not in {"object.context-index", "object.state-snapshot"} or not isinstance(
                    payload, dict
                ):
                    self.record_behavior("publication_outbox:invalid")
                    attempted += 1
                    continue
                outbox_key = self._outbox_key_for_recovery(row)
                attempted += 1
                if await self._publish_with_outbox(outbox_key, str(topic), dict(payload)):
                    published += 1
                    progress += 1
            if progress == 0:
                break
        if published:
            self.record_behavior("publication_outbox:recovered", published)
        if attempted >= limit:
            self.record_behavior("publication_outbox:recovery_deferred")
        return published


def _cohort_digest(cases: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(cases, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _payload_digest(payload: Mapping[str, Any]) -> str:
    return canonical_json_digest(payload)


__all__ = ["MuninnOperationalOutboxMixin"]
