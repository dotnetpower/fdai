"""Postgres audit adapters for verified T1 pattern growth."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

import psycopg
from fdai.core.measurement.pattern_growth import OutcomeRecord
from fdai.core.tiers.t1_lightweight import EmbeddingModel, LearnedAction, OperationalCaseContext
from fdai.delivery.measurement.outcome_contract import accepted_outcome_timestamp
from fdai.shared.contracts.models import ResponseOutcome
from fdai.shared.providers.state_store import StateStore
from psycopg.rows import dict_row

_WATERMARK_KEY = "measurement:pattern_growth:watermark"
_RESPONSE_WATERMARK_KEY = "measurement:dynamic_learning:watermark"
_OUTCOME_KIND = "measurement.action_outcome.v1"
_CONTEXT_KIND = "measurement.growth_context.v1"
_CONTEXT_FIELDS = ("embedding_projection", "params", "rule_id", "incident_id", "operational_case")
_SUPPORTED_RESPONSE_VERSIONS = {"1.0.0", "1.1.0"}


async def _advance_watermark(store: StateStore, key: str, seq: int) -> None:
    """A slower concurrent consumer must never rewind a completed source page."""
    for _ in range(8):
        state = await store.read_state(key)
        if state is None:
            if await store.write_state_if_absent(key, {"seq": seq, "revision": 1}):
                return
            continue
        if int(state.get("seq", 0)) >= seq:
            return
        revision = int(state.get("revision", 0))
        if await store.compare_and_set_state(
            key, {"seq": seq, "revision": revision + 1}, expected_revision=revision
        ):
            return
    raise RuntimeError("measurement source watermark revision conflict")


class PostgresVerifiedOutcomeSource:
    """Yield only explicitly verified, provenance-complete outcome records."""

    def __init__(
        self,
        *,
        dsn: str,
        state_store: StateStore,
        statement_timeout_ms: int = 15_000,
        connect_timeout_s: int = 10,
    ) -> None:
        if not dsn:
            raise ValueError("dsn MUST be non-empty")
        self._dsn = dsn
        self._state_store = state_store
        self._statement_timeout_ms = statement_timeout_ms
        self._connect_timeout_s = connect_timeout_s

    def outcomes(self) -> AsyncIterator[OutcomeRecord]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[OutcomeRecord]:
        state = await self._state_store.read_state(_WATERMARK_KEY) or {}
        after_seq = int(state.get("seq") or 0)
        rows = await self._rows(after_seq)
        high_water = after_seq
        for row in rows:
            high_water = max(high_water, int(row["seq"]))
        for row in _latest_outcome_rows(rows):
            entry = _mapping(row["entry"])
            record = _outcome_record(entry, recorded_at=row["created_at"])
            if record is not None:
                yield record
            else:
                await self._state_store.append_audit_entry(
                    {
                        "actor": "Norns",
                        "action_kind": "measurement.pattern_growth.source_rejected",
                        "source_seq": int(row["seq"]),
                        "reason": "pattern_outcome_invalid_or_unsupported",
                        "execution_authority": False,
                        "promotion_authority": False,
                    }
                )
            await _advance_watermark(self._state_store, _WATERMARK_KEY, int(row["seq"]))
        if high_water > after_seq:
            await _advance_watermark(self._state_store, _WATERMARK_KEY, high_water)

    async def _rows(self, after_seq: int) -> list[Mapping[str, Any]]:
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            row_factory=dict_row,
            connect_timeout=self._connect_timeout_s,
        ) as connection:
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._statement_timeout_ms),),
            )
            cursor = await connection.execute(
                "SELECT seq, entry, created_at FROM audit_log WHERE seq > %s "
                "AND action_kind = %s ORDER BY seq ASC LIMIT 1000",
                (after_seq, _OUTCOME_KIND),
            )
            return list(await cursor.fetchall())


class PostgresResponseOutcomeSource:
    """Yield strict ResponseOutcome records under an independent watermark."""

    def __init__(
        self,
        *,
        dsn: str,
        state_store: StateStore,
        statement_timeout_ms: int = 15_000,
        connect_timeout_s: int = 10,
    ) -> None:
        if not dsn:
            raise ValueError("dsn MUST be non-empty")
        self._dsn = dsn
        self._state_store = state_store
        self._statement_timeout_ms = statement_timeout_ms
        self._connect_timeout_s = connect_timeout_s

    def outcomes(self) -> AsyncIterator[ResponseOutcome]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[ResponseOutcome]:
        state = await self._state_store.read_state(_RESPONSE_WATERMARK_KEY) or {}
        after_seq = int(state.get("seq") or 0)
        rows = await self._rows(after_seq)
        high_water = max((int(row["seq"]) for row in rows), default=after_seq)
        for row in rows:
            outcome = _response_outcome(_mapping(row["entry"]))
            if outcome is not None:
                yield outcome
            else:
                await self._state_store.append_audit_entry(
                    {
                        "actor": "Norns",
                        "action_kind": "dynamic.learning.source_rejected",
                        "source_seq": int(row["seq"]),
                        "reason": "response_outcome_invalid_or_unsupported",
                        "execution_authority": False,
                        "promotion_authority": False,
                    }
                )
            await _advance_watermark(self._state_store, _RESPONSE_WATERMARK_KEY, int(row["seq"]))
        if high_water > after_seq:
            await _advance_watermark(self._state_store, _RESPONSE_WATERMARK_KEY, high_water)

    async def _rows(self, after_seq: int) -> list[Mapping[str, Any]]:
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            row_factory=dict_row,
            connect_timeout=self._connect_timeout_s,
        ) as connection:
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._statement_timeout_ms),),
            )
            cursor = await connection.execute(
                "SELECT seq, entry FROM audit_log WHERE seq > %s "
                "AND action_kind = %s ORDER BY seq ASC LIMIT 1000",
                (after_seq, _OUTCOME_KIND),
            )
            return list(await cursor.fetchall())


class PostgresVerifiedPatternBuilder:
    """Build a pattern only from the explicit verified-outcome audit contract."""

    def __init__(
        self,
        *,
        dsn: str,
        embedding_model: EmbeddingModel,
        statement_timeout_ms: int = 15_000,
        connect_timeout_s: int = 10,
    ) -> None:
        self._dsn = dsn
        self._embedding_model = embedding_model
        self._statement_timeout_ms = statement_timeout_ms
        self._connect_timeout_s = connect_timeout_s

    async def build(self, record: OutcomeRecord) -> tuple[Sequence[float], LearnedAction] | None:
        entry = await self._entry(record.action_id)
        if entry is None:
            return None
        # Re-read the authoritative latest outcome on every retry, rather than
        # trusting a pending copy after correction, rollback, or source eviction.
        current = _outcome_record(entry, recorded_at=entry.get("recorded_at"))
        if current != record:
            return None
        projection = entry.get("embedding_projection")
        params = entry.get("params")
        rule_id = entry.get("rule_id")
        incident_id = entry.get("incident_id")
        operational_case_raw = entry.get("operational_case")
        if (
            not isinstance(projection, str)
            or not projection
            or not isinstance(params, Mapping)
            or not isinstance(rule_id, str)
            or not rule_id
            or not isinstance(incident_id, str)
            or not incident_id
        ):
            return None
        operational_case = None
        if isinstance(operational_case_raw, Mapping):
            try:
                operational_case = OperationalCaseContext.from_mapping(operational_case_raw)
            except ValueError:
                return None
        if rule_id.startswith("learned.operational.") and operational_case is None:
            return None
        if operational_case is not None and operational_case.action_type != record.action_type_id:
            return None
        vector = await self._embedding_model.embed(projection)
        if len(vector) != 384:
            raise ValueError(f"growth embedding dim MUST be 384; got {len(vector)}")
        if any(not math.isfinite(float(value)) for value in vector):
            raise ValueError("growth embedding values MUST be finite")
        signature_material = {
            "action_type_id": record.action_type_id,
            "operational_case": (
                operational_case.to_mapping() if operational_case is not None else None
            ),
            "params": dict(params),
            "rule_id": rule_id,
        }
        try:
            encoded_signature = json.dumps(
                signature_material,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            ).encode()
        except (TypeError, ValueError):
            return None
        signature = hashlib.sha256(encoded_signature).hexdigest()
        return (
            vector,
            LearnedAction(
                signature=signature,
                rule_id=rule_id,
                action_type=record.action_type_id,
                params=dict(params),
                incident_id=incident_id,
                success_rate=1.0,
                reuse_count=1,
                operational_case=operational_case,
            ),
        )

    async def _entry(self, action_id: str) -> Mapping[str, Any] | None:
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            row_factory=dict_row,
            connect_timeout=self._connect_timeout_s,
        ) as connection:
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._statement_timeout_ms),),
            )
            cursor = await connection.execute(
                "SELECT entry, created_at FROM audit_log WHERE action_kind = %s "
                "AND entry->>'action_id' = %s ORDER BY seq DESC LIMIT 1",
                (_OUTCOME_KIND, action_id),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            context_cursor = await connection.execute(
                "SELECT entry FROM audit_log WHERE action_kind = %s "
                "AND entry->>'action_id' = %s ORDER BY seq DESC LIMIT 1",
                (_CONTEXT_KIND, action_id),
            )
            context = await context_cursor.fetchone()
        merged = merge_growth_context(
            _mapping(row["entry"]), _mapping(context["entry"]) if context is not None else {}
        )
        return {**merged, "recorded_at": row["created_at"]}


def merge_growth_context(outcome: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    """Overlay the recorded growth context under the verified outcome; the outcome wins."""
    return {**{key: context[key] for key in _CONTEXT_FIELDS if key in context}, **outcome}


def _mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return value if isinstance(value, Mapping) else {}


def _latest_outcome_rows(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    latest_by_action: dict[str, Mapping[str, Any]] = {}
    unidentified: list[Mapping[str, Any]] = []
    for row in rows:
        entry = _mapping(row.get("entry"))
        action_id = entry.get("action_id")
        if not isinstance(action_id, str) or not action_id:
            unidentified.append(row)
            continue
        current = latest_by_action.get(action_id)
        if current is None or int(row["seq"]) > int(current["seq"]):
            latest_by_action[action_id] = row
    return sorted((*unidentified, *latest_by_action.values()), key=lambda row: int(row["seq"]))


def _outcome_record(
    entry: Mapping[str, Any],
    *,
    recorded_at: Any,
) -> OutcomeRecord | None:
    if "schema_version" in entry:
        version = entry["schema_version"]
        if not isinstance(version, str) or version not in _SUPPORTED_RESPONSE_VERSIONS:
            return None
    required = (
        entry.get("action_id"),
        entry.get("action_type_id"),
        entry.get("observed_at"),
    )
    if not all(isinstance(value, str) and 0 < len(value) <= 512 for value in required):
        return None
    verification_passed = entry.get("verification_passed")
    if (
        entry.get("execution_mode") != "enforce"
        or not isinstance(verification_passed, bool)
        or not isinstance(entry.get("rollback_succeeded"), bool)
    ):
        return None
    observed_at = accepted_outcome_timestamp(
        entry["observed_at"],
        recorded_at=recorded_at,
    )
    if observed_at is None:
        return None
    return OutcomeRecord(
        action_id=str(entry["action_id"]),
        action_type_id=str(entry["action_type_id"]),
        observed_at=observed_at,
        was_auto=entry.get("decision") == "auto",
        was_verified=verification_passed,
        was_rolled_back=entry.get("rollback_succeeded") is True,
    )


def _response_outcome(entry: Mapping[str, Any]) -> ResponseOutcome | None:
    version = entry.get("schema_version")
    if not isinstance(version, str) or version not in _SUPPORTED_RESPONSE_VERSIONS:
        return None
    contract = {
        key: value
        for key, value in entry.items()
        if key
        not in {
            "actor",
            "action_kind",
            "mode",
            "scorable",
            "verification_passed",
            "outcome_revision_digest",
        }
    }
    try:
        return ResponseOutcome.model_validate(contract)
    except ValueError:
        return None


__all__ = [
    "PostgresResponseOutcomeSource",
    "PostgresVerifiedOutcomeSource",
    "PostgresVerifiedPatternBuilder",
    "merge_growth_context",
]
