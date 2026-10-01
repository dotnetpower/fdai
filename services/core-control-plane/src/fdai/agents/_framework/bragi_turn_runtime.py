# mypy: disable-error-code="attr-defined,arg-type,no-any-return,misc,has-type"
"""Durable turn and preference state mixin for Bragi."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from fdai.agents._framework.bragi_models import ConversationSession, Turn
from fdai.agents._framework.bragi_publication import turn_event_payload
from fdai.agents._framework.bragi_runtime_helpers import (
    _TURN_OUTBOX_CLAIM_LEASE,
    _payload_digest,
    _preference_from_index_row,
    _published_turn_outbox_tombstone,
    _session_sequence_key,
    _turn_claim_expired,
    _turn_outbox_key,
)
from fdai.agents._framework.outbox_publication import (
    PublicationClaim,
    claim_matches,
    new_publication_claim_owner,
    publish_claimed_outbox,
)
from fdai.shared.providers.state_store import StateStore

_BRAGI_STATE_PREFIX = "pantheon/bragi"
_USER_PREFERENCE_INDEX_PREFIX = f"{_BRAGI_STATE_PREFIX}/user-preference-index/"
_USER_PREFERENCE_INDEX_SCAN_LIMIT = 1_000
_TURN_OUTBOX_PENDING_SCAN_LIMIT = 5_000
_TURN_OUTBOX_TOMBSTONE_RETENTION = 1_024
_TURN_OUTBOX_MAINTENANCE_PAGE = 16
_MAX_PROGRESS_KEYS = 5_000
_DURABLE_PROGRESS_RETENTION = _MAX_PROGRESS_KEYS
_MAX_PROGRESS_STEPS = 64
_MAX_CONTRIBUTORS = 2


class BragiTurnRuntimeMixin:
    """Checkpoint and replay Bragi turn publication state."""

    _state_store: StateStore | None
    _last_preference_index_refresh: dict[str, Any] | None

    async def _publish_turn(self, payload: dict[str, Any]) -> None:
        bus = self.bus
        if bus is None:
            self.record_behavior("turn:publication_pending")
            return
        await self._publish_claimed_turn(bus, payload)

    async def _publish_claimed_turn(self, bus: Any, payload: dict[str, Any]) -> bool:
        claim = await self._claim_turn_publication(payload)
        return await publish_claimed_outbox(
            claim,
            publish=lambda: bus.publish("Bragi", "object.turn", payload),
            mark_published=lambda active_claim: self._mark_turn_published(payload, active_claim),
            release=lambda active_claim: self._reset_turn_publication_pending(
                payload, active_claim
            ),
            lease=_TURN_OUTBOX_CLAIM_LEASE,
        )

    async def _reserve_turn_index(self, session_id: str, session: ConversationSession) -> int:
        if self._state_store is None:
            turn_index = session.next_turn_index
            session.next_turn_index += 1
            return turn_index
        key = _session_sequence_key(session_id)
        for _attempt in range(16):
            stored = await self._state_store.read_state(key)
            if stored is None:
                turn_index = session.next_turn_index
                record = {
                    "schema_version": "1.0.0",
                    "revision": 1,
                    "session_id": session_id,
                    "next_turn_index": turn_index + 1,
                }
                if await self._state_store.write_state_if_absent(key, record):
                    session.next_turn_index = max(session.next_turn_index, turn_index + 1)
                    return turn_index
                continue
            next_index = stored.get("next_turn_index")
            revision = stored.get("revision")
            if (
                stored.get("schema_version") != "1.0.0"
                or not isinstance(next_index, int)
                or isinstance(next_index, bool)
                or next_index < 0
                or not isinstance(revision, int)
                or isinstance(revision, bool)
            ):
                raise RuntimeError("durable Bragi turn sequence is malformed")
            advanced = await self._state_store.compare_and_set_state(
                key,
                {**dict(stored), "revision": revision + 1, "next_turn_index": next_index + 1},
                expected_revision=revision,
            )
            if advanced:
                session.next_turn_index = max(session.next_turn_index, next_index + 1)
                return next_index
        raise RuntimeError("Bragi turn sequence CAS retry limit exceeded")

    async def _checkpoint_turn_payload(
        self, *, session: ConversationSession, turn: Turn
    ) -> dict[str, Any]:
        payload = turn_event_payload(
            session_id=session.session_id,
            user_id=session.user_id,
            session_generation=session.generation,
            turn=turn,
            contributor_limit=_MAX_CONTRIBUTORS,
        )
        if self._state_store is None:
            return payload
        key = _turn_outbox_key(str(payload["session_ref"]), turn.turn_index)
        record = {
            "schema_version": "1.0.0",
            "revision": 1,
            "status": "pending",
            "session_ref": payload["session_ref"],
            "turn_index": turn.turn_index,
            "payload": payload,
        }
        created = await self._state_store.write_state_if_absent(key, record)
        if created:
            self._turn_outbox_pending += 1
            return payload
        stored = await self._state_store.read_state(key)
        if not isinstance(stored, Mapping):
            raise RuntimeError("Bragi turn outbox row disappeared")
        stored_payload = stored.get("payload")
        if stored.get("status") == "published":
            if isinstance(stored_payload, Mapping):
                return dict(stored_payload)
            stored_digest = str(stored.get("payload_digest") or "")
            payload_digest = _payload_digest(payload)
            if stored_digest and stored_digest != payload_digest:
                raise RuntimeError("Bragi turn outbox idempotency collision")
            return payload
        revision = int(stored.get("revision", 1))
        advanced = await self._state_store.compare_and_set_state(
            key,
            {**record, "revision": revision + 1},
            expected_revision=revision,
        )
        if not advanced:
            raise RuntimeError("Bragi turn outbox update conflicted")
        self._turn_outbox_pending += 1
        return payload

    async def _claim_turn_publication(self, payload: Mapping[str, Any]) -> PublicationClaim | None:
        if self._state_store is None:
            return PublicationClaim(
                owner=new_publication_claim_owner(self.spec.name),
                claimed_at=self._clock().isoformat(),
            )
        key = _turn_outbox_key(str(payload["session_ref"]), int(payload["turn_index"]))
        for _attempt in range(16):
            stored = await self._state_store.read_state(key)
            if stored is None:
                raise RuntimeError("Bragi turn outbox row disappeared before publication")
            status = stored.get("status")
            if status == "published":
                return None
            now = self._clock()
            if status == "publishing" and not _turn_claim_expired(stored, now):
                return None
            revision = int(stored.get("revision", 1))
            claimed_at = now.isoformat()
            claim_owner = new_publication_claim_owner(self.spec.name)
            advanced = await self._state_store.compare_and_set_state(
                key,
                {
                    **dict(stored),
                    "status": "publishing",
                    "revision": revision + 1,
                    "claim_owner": claim_owner,
                    "claimed_at": claimed_at,
                },
                expected_revision=revision,
            )
            if advanced:
                return PublicationClaim(owner=claim_owner, claimed_at=claimed_at)
        raise RuntimeError("Bragi turn publication claim CAS retry limit exceeded")

    async def _reset_turn_publication_pending(
        self, payload: Mapping[str, Any], claim: PublicationClaim
    ) -> None:
        if self._state_store is None:
            return
        key = _turn_outbox_key(str(payload["session_ref"]), int(payload["turn_index"]))
        for _attempt in range(16):
            stored = await self._state_store.read_state(key)
            if stored is None or stored.get("status") != "publishing":
                return
            if not claim_matches(stored, claim):
                return
            revision = int(stored.get("revision", 1))
            advanced = await self._state_store.compare_and_set_state(
                key,
                {
                    **dict(stored),
                    "status": "pending",
                    "revision": revision + 1,
                    "claim_owner": "",
                    "claimed_at": "",
                },
                expected_revision=revision,
            )
            if advanced:
                return
        raise RuntimeError("Bragi turn publication release CAS retry limit exceeded")

    async def _mark_turn_published(
        self, payload: Mapping[str, Any], claim: PublicationClaim
    ) -> bool:
        if self._state_store is None:
            return True
        key = _turn_outbox_key(str(payload["session_ref"]), int(payload["turn_index"]))
        for _attempt in range(16):
            stored = await self._state_store.read_state(key)
            if stored is None or stored.get("status") == "published":
                return False
            if not claim_matches(stored, claim):
                return False
            revision = int(stored.get("revision", 1))
            advanced = await self._state_store.compare_and_set_state(
                key,
                _published_turn_outbox_tombstone(stored, revision=revision + 1),
                expected_revision=revision,
            )
            if advanced:
                await self._compact_turn_outbox_tombstones()
                self._turn_outbox_pending = max(0, self._turn_outbox_pending - 1)
                return True
        raise RuntimeError("Bragi turn publication CAS retry limit exceeded")

    async def _compact_turn_outbox_tombstones(self) -> None:
        if self._state_store is None:
            return
        await self._state_store.delete_states_beyond(
            f"{_BRAGI_STATE_PREFIX}/turn-outbox/",
            retain_newest=_TURN_OUTBOX_PENDING_SCAN_LIMIT + _TURN_OUTBOX_TOMBSTONE_RETENTION,
        )

    async def recover_state(self) -> tuple[int, int]:
        """Restore durable progress and unpublished turn outbox rows."""

        if self._state_store is None:
            return 0, 0
        progress_rows = await self._state_store.read_states(
            f"{_BRAGI_STATE_PREFIX}/progress/",
            limit=_MAX_PROGRESS_KEYS * _MAX_PROGRESS_STEPS,
        )
        progress = 0
        for row in reversed(progress_rows):
            correlation_id = str(row.get("correlation_id") or "")
            step = row.get("step")
            if correlation_id and isinstance(step, Mapping):
                self._progress.setdefault(correlation_id, []).append(dict(step))
                self._progress[correlation_id] = self._progress[correlation_id][
                    -_MAX_PROGRESS_STEPS:
                ]
                progress += 1
        published = await self._drive_turn_outbox(limit=_TURN_OUTBOX_PENDING_SCAN_LIMIT)
        recovered_publications = await self.recover_bragi_publications()
        return progress, published + recovered_publications

    async def _drive_turn_outbox(self, *, limit: int) -> int:
        """Publish pending or lease-expired turn rows, deferring each failed or malformed row."""

        store = self._state_store
        bus = self.bus
        if store is None or bus is None:
            return 0
        prefix = f"{_BRAGI_STATE_PREFIX}/turn-outbox/"
        published = 0
        attempted = 0
        attempted_keys: set[str] = set()
        while attempted < limit:
            remaining = limit - attempted
            pending_rows, pending_total = await store.read_state_page(
                prefix, limit=remaining, field="status", value="pending"
            )
            publishing_rows, publishing_total = await store.read_state_page(
                prefix, limit=remaining, field="status", value="publishing"
            )
            self._turn_outbox_pending = pending_total + publishing_total
            rows = (*pending_rows, *publishing_rows)
            if not rows:
                break
            progress = 0
            for row in reversed(rows[:remaining]):
                payload = row.get("payload")
                if (
                    not isinstance(payload, Mapping)
                    or not isinstance(payload.get("session_ref"), str)
                    or not isinstance(payload.get("turn_index"), int)
                    or isinstance(payload.get("turn_index"), bool)
                ):
                    row_key = (
                        "invalid:"
                        + hashlib.sha256(
                            json.dumps(row, sort_keys=True, default=str).encode()
                        ).hexdigest()
                    )
                    if row_key not in attempted_keys:
                        attempted_keys.add(row_key)
                        attempted += 1
                        self.record_behavior("turn_outbox:recovery_invalid_row")
                    continue
                outbox_key = _turn_outbox_key(
                    str(payload["session_ref"]), int(payload["turn_index"])
                )
                if outbox_key in attempted_keys:
                    continue
                attempted_keys.add(outbox_key)
                attempted += 1
                try:
                    if await self._publish_claimed_turn(bus, dict(payload)):
                        published += 1
                        progress += 1
                except Exception:
                    self.record_behavior("turn_outbox:recovery_publish_failed")
                    continue
            if progress == 0:
                break
        if self._turn_outbox_pending > 0 and attempted >= limit:
            self.record_behavior("turn_outbox:recovery_deferred")
        return published

    async def maintenance_tick(self) -> None:
        await super().maintenance_tick()
        try:
            await self._drive_turn_outbox(limit=_TURN_OUTBOX_MAINTENANCE_PAGE)
            await self.recover_bragi_publications(limit=_TURN_OUTBOX_MAINTENANCE_PAGE)
        except Exception:
            self.record_behavior("publication_outbox:maintenance_recovery_failed")
        refreshed = await self.refresh_user_preference_index()
        if refreshed:
            self.record_behavior("maintenance_tick:user_preference_index_refreshed", refreshed)

    async def refresh_user_preference_index(self) -> int:
        """Republish bounded durable UserPreference rows without changing routing authority."""

        if self._state_store is None:
            self._last_preference_index_refresh = {
                "refreshed_at": self._clock().isoformat(),
                "rows_scanned": 0,
                "preferences_published": 0,
                "evidence_state": "not_configured",
                "execution_authority": False,
            }
            return 0
        rows = await self._state_store.read_states(
            _USER_PREFERENCE_INDEX_PREFIX,
            limit=_USER_PREFERENCE_INDEX_SCAN_LIMIT,
        )
        published = 0
        invalid = 0
        for row in rows:
            try:
                preference = _preference_from_index_row(row)
            except (KeyError, TypeError, ValueError):
                invalid += 1
                continue
            if await self.publish_user_preference(preference):
                published += 1
        self._last_preference_index_refresh = {
            "refreshed_at": self._clock().isoformat(),
            "rows_scanned": len(rows),
            "preferences_published": published,
            "invalid_rows": invalid,
            "evidence_state": "measured",
            "execution_authority": False,
        }
        if invalid:
            self.record_behavior("user_preference_index:invalid_row", invalid)
        return published
