# mypy: disable-error-code="attr-defined,arg-type,no-any-return,misc,has-type"
"""Durable turn and preference state mixin for Bragi."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from fdai.agents._framework.bragi_models import ConversationSession, Turn
from fdai.agents._framework.bragi_publication import turn_event_payload
from fdai.agents._framework.bragi_runtime_helpers import (
    _payload_digest,
    _preference_from_index_row,
    _published_turn_outbox_tombstone,
    _session_sequence_key,
    _turn_claim_expired,
    _turn_outbox_key,
)
from fdai.agents._framework.outbox_publication import await_bounded_publication
from fdai.shared.providers.state_store import StateStore

_BRAGI_STATE_PREFIX = "pantheon/bragi"
_USER_PREFERENCE_INDEX_PREFIX = f"{_BRAGI_STATE_PREFIX}/user-preference-index/"
_USER_PREFERENCE_INDEX_SCAN_LIMIT = 1_000
_TURN_OUTBOX_PENDING_SCAN_LIMIT = 5_000
_TURN_OUTBOX_TOMBSTONE_RETENTION = 1_024
_TURN_OUTBOX_CLAIM_LEASE = timedelta(minutes=5)
_MAX_PROGRESS_KEYS = 5_000
_DURABLE_PROGRESS_RETENTION = _MAX_PROGRESS_KEYS
_MAX_PROGRESS_STEPS = 64
_MAX_CONTRIBUTORS = 2


class BragiTurnRuntimeMixin:
    """Checkpoint and replay Bragi turn publication state."""

    _state_store: StateStore | None
    _last_preference_index_refresh: dict[str, Any] | None

    async def _publish_turn(self, payload: dict[str, Any]) -> None:
        if self.bus is None:
            self.record_behavior("turn:publication_pending")
            return
        if not await self._claim_turn_publication(payload):
            return
        try:
            await await_bounded_publication(
                self.bus.publish("Bragi", "object.turn", payload),
                lease=_TURN_OUTBOX_CLAIM_LEASE,
            )
            await asyncio.shield(self._mark_turn_published(payload))
        except Exception:
            await self._reset_turn_publication_pending(payload)
            raise

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

    async def _claim_turn_publication(self, payload: Mapping[str, Any]) -> bool:
        if self._state_store is None:
            return True
        key = _turn_outbox_key(str(payload["session_ref"]), int(payload["turn_index"]))
        for _attempt in range(16):
            stored = await self._state_store.read_state(key)
            if stored is None:
                raise RuntimeError("Bragi turn outbox row disappeared before publication")
            status = stored.get("status")
            if status == "published":
                return False
            now = self._clock()
            if status == "publishing" and not _turn_claim_expired(stored, now):
                return False
            revision = int(stored.get("revision", 1))
            advanced = await self._state_store.compare_and_set_state(
                key,
                {
                    **dict(stored),
                    "status": "publishing",
                    "revision": revision + 1,
                    "claim_owner": self.spec.name,
                    "claimed_at": now.isoformat(),
                },
                expected_revision=revision,
            )
            if advanced:
                return True
        raise RuntimeError("Bragi turn publication claim CAS retry limit exceeded")

    async def _reset_turn_publication_pending(self, payload: Mapping[str, Any]) -> None:
        if self._state_store is None:
            return
        key = _turn_outbox_key(str(payload["session_ref"]), int(payload["turn_index"]))
        for _attempt in range(16):
            stored = await self._state_store.read_state(key)
            if stored is None or stored.get("status") == "published":
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

    async def _mark_turn_published(self, payload: Mapping[str, Any]) -> None:
        if self._state_store is None:
            return
        key = _turn_outbox_key(str(payload["session_ref"]), int(payload["turn_index"]))
        for _attempt in range(16):
            stored = await self._state_store.read_state(key)
            if stored is None or stored.get("status") == "published":
                return
            revision = int(stored.get("revision", 1))
            advanced = await self._state_store.compare_and_set_state(
                key,
                _published_turn_outbox_tombstone(stored, revision=revision + 1),
                expected_revision=revision,
            )
            if advanced:
                await self._compact_turn_outbox_tombstones()
                self._turn_outbox_pending = max(0, self._turn_outbox_pending - 1)
                return
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
        published = 0
        if self.bus is not None:
            pending_rows, pending_total = await self._state_store.read_state_page(
                f"{_BRAGI_STATE_PREFIX}/turn-outbox/",
                limit=_TURN_OUTBOX_PENDING_SCAN_LIMIT,
                field="status",
                value="pending",
            )
            publishing_rows, publishing_total = await self._state_store.read_state_page(
                f"{_BRAGI_STATE_PREFIX}/turn-outbox/",
                limit=_TURN_OUTBOX_PENDING_SCAN_LIMIT,
                field="status",
                value="publishing",
            )
            self._turn_outbox_pending = pending_total + publishing_total
            rows = (*pending_rows, *publishing_rows)
            for row in reversed(rows[:_TURN_OUTBOX_PENDING_SCAN_LIMIT]):
                payload = row.get("payload")
                if not isinstance(payload, Mapping):
                    raise RuntimeError("Bragi turn outbox row is malformed")
                if await self._claim_turn_publication(payload):
                    try:
                        await await_bounded_publication(
                            self.bus.publish("Bragi", "object.turn", dict(payload)),
                            lease=_TURN_OUTBOX_CLAIM_LEASE,
                        )
                        await asyncio.shield(self._mark_turn_published(payload))
                    except Exception:
                        await self._reset_turn_publication_pending(payload)
                        raise
                    published += 1
        recovered_publications = await self.recover_bragi_publications()
        self._turn_outbox_pending = max(0, self._turn_outbox_pending - published)
        return progress, published + recovered_publications

    async def maintenance_tick(self) -> None:
        await super().maintenance_tick()
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
