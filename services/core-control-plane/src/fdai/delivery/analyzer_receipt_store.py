"""Retention-bounded analyzer finding receipt persistence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from fdai.delivery.analyzer_tick import AnalyzerFindingReceipt
from fdai.shared.providers.state_store import StateStore

ANALYZER_RECEIPT_STATE_PREFIX = "runtime:analyzer-finding-receipt:"
ANALYZER_RUN_RECEIPT_STATE_PREFIX = "runtime:analyzer-tick-receipt:"
ANALYZER_RUN_RECEIPT_SCHEMA_VERSION = "1.3.0"
DEFAULT_ANALYZER_RECEIPT_RETENTION = 500
#: Per-tick observation values. A finding that outlives one tick keeps the same
#: window-bucket idempotency key, so a later tick re-reports the same outcome
#: with a later reading. These fields therefore vary within one receipt
#: identity and are excluded from the immutable-content comparison, matching
#: the Operator lifecycle projection, which also excludes them when it decides
#: whether receipts sharing one identity conflict.
_PER_TICK_OBSERVATION_FIELDS = frozenset({"detection_latency_seconds", "recorded_at"})


def _immutable_content(value: Mapping[str, object]) -> dict[str, object]:
    """Return the receipt content that one identity MUST NOT restate differently."""

    return {name: item for name, item in value.items() if name not in _PER_TICK_OBSERVATION_FIELDS}


@dataclass(frozen=True, slots=True)
class StateStoreAnalyzerReceiptStore:
    """Persist idempotent, presentation-safe receipts in tracked state."""

    state_store: StateStore
    retain_newest: int = DEFAULT_ANALYZER_RECEIPT_RETENTION

    def __post_init__(self) -> None:
        if not 1 <= self.retain_newest <= 10_000:
            raise ValueError("analyzer receipt retention MUST be in [1, 10000]")

    async def record(self, receipt: AnalyzerFindingReceipt) -> None:
        """Record one outcome once and trim only older receipt projections.

        A repeat tick that restates the same outcome is an idempotent no-op and
        keeps the first observation, so ``detection_latency_seconds`` stays a
        detection measurement rather than the finding's age. Restating an
        identity with different immutable content is still a collision.
        """
        identity = f"{receipt.idempotency_key}\n{receipt.publication.value}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        key = f"{ANALYZER_RECEIPT_STATE_PREFIX}{digest}"
        value = receipt.to_dict()
        if not await self.state_store.write_state_if_absent(key, value):
            existing = await self.state_store.read_state(key)
            if existing is None or _immutable_content(existing) != _immutable_content(value):
                raise ValueError("analyzer receipt identity collision")
        await self.state_store.delete_states_beyond(
            ANALYZER_RECEIPT_STATE_PREFIX,
            retain_newest=self.retain_newest,
        )


@dataclass(frozen=True, slots=True)
class StateStoreAnalyzerRunReceiptStore:
    """Retain bounded complete tick reports for operational evidence."""

    state_store: StateStore
    retain_newest: int = DEFAULT_ANALYZER_RECEIPT_RETENTION

    def __post_init__(self) -> None:
        if not 1 <= self.retain_newest <= 10_000:
            raise ValueError("analyzer run receipt retention MUST be in [1, 10000]")

    async def record(
        self,
        *,
        run_id: str,
        tick_id: str = "0",
        recorded_at: datetime,
        report: Mapping[str, object],
    ) -> None:
        """Record one tick result idempotently and reject identity reuse."""

        if not run_id.strip() or len(run_id) > 256:
            raise ValueError("analyzer run receipt id MUST be bounded text")
        if not tick_id.strip() or len(tick_id) > 64 or any(char.isspace() for char in tick_id):
            raise ValueError("analyzer tick receipt id MUST be bounded and contain no whitespace")
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise ValueError("analyzer run receipt time MUST be timezone-aware")
        canonical_report = json.dumps(
            report,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        report_digest = hashlib.sha256(canonical_report.encode("utf-8")).hexdigest()
        attempt_digest = hashlib.sha256(
            f"{run_id}\n{tick_id}\n{report_digest}".encode()
        ).hexdigest()
        key = f"{ANALYZER_RUN_RECEIPT_STATE_PREFIX}{attempt_digest}"
        value: dict[str, object] = {
            "schema_version": ANALYZER_RUN_RECEIPT_SCHEMA_VERSION,
            "run_id": run_id,
            "tick_id": tick_id,
            "attempt_id": report_digest,
            "recorded_at": recorded_at.isoformat(),
            "report_digest": report_digest,
            "report": dict(report),
            "execution_authority": False,
        }
        if not await self.state_store.write_state_if_absent(key, value):
            existing = await self.state_store.read_state(key)
            immutable_fields = (
                "schema_version",
                "run_id",
                "tick_id",
                "attempt_id",
                "report_digest",
                "report",
                "execution_authority",
            )
            if existing is None or any(
                existing.get(field) != value[field] for field in immutable_fields
            ):
                raise ValueError("analyzer run receipt identity collision")
        await self.state_store.delete_states_beyond(
            ANALYZER_RUN_RECEIPT_STATE_PREFIX,
            retain_newest=self.retain_newest,
        )


__all__ = [
    "ANALYZER_RUN_RECEIPT_SCHEMA_VERSION",
    "ANALYZER_RECEIPT_STATE_PREFIX",
    "ANALYZER_RUN_RECEIPT_STATE_PREFIX",
    "DEFAULT_ANALYZER_RECEIPT_RETENTION",
    "StateStoreAnalyzerReceiptStore",
    "StateStoreAnalyzerRunReceiptStore",
]
