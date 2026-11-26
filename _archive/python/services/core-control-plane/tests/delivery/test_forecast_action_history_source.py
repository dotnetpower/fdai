from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.forecast_history_sources import (
    ActionAuditHistoryRead,
    ActionAuditHistoryRow,
    ActionAuditHistorySource,
)
from fdai.shared.providers.audit_hash import GENESIS_HASH, next_hash

START = datetime(2026, 10, 1, tzinfo=UTC)
END = START + timedelta(hours=1)
KNOWN = END + timedelta(minutes=10)
TARGET = "resource:test"


def audit_row(**state: object) -> ActionAuditHistoryRow:
    entry = {"kind": "thor.action-run-save", "correlation_id": "test-corr", "revision": 1}
    return ActionAuditHistoryRow(
        seq=73,
        recorded_at=START + timedelta(minutes=1),
        entry=entry,
        previous_hash=GENESIS_HASH,
        entry_hash=next_hash(GENESIS_HASH, entry),
        state={
            "correlation_id": "test-corr",
            "action_type": "fdai.test",
            "resource_id": TARGET,
            "state": "succeeded",
            **state,
        },
    )


class Reader:
    def __init__(self, result: ActionAuditHistoryRead) -> None:
        self.result = result
        self.queries: list[dict[str, object]] = []

    async def read_action_audit(
        self,
        *,
        subject_ref: str,
        start_at: datetime,
        end_at: datetime,
        known_at: datetime,
        limit: int,
    ) -> ActionAuditHistoryRead:
        self.queries.append(
            {
                "subject_ref": subject_ref,
                "start_at": start_at,
                "end_at": end_at,
                "known_at": known_at,
                "limit": limit,
            }
        )
        return self.result


@pytest.mark.parametrize(
    ("rows", "truncated", "reason"),
    [
        ((audit_row(),), False, "action_history_proof_unavailable"),
        ((replace(audit_row(), entry_hash="f" * 64),), False, "audit_chain_gap_or_hash_mismatch"),
        ((audit_row(shadow_mode=True, outcome="shadow_success"),), False, None),
        ((replace(audit_row(), entry=None, state=None),), False, "audit_record_redacted"),
        (
            (replace(audit_row(), recorded_at=KNOWN + timedelta(seconds=1)),),
            False,
            "audit_record_out_of_scope",
        ),
        ((audit_row(resource_id="resource:other"),), False, "action_state_malformed"),
        ((audit_row(state="execution_unknown"),), False, None),
        ((audit_row(state="effect_pending"),), False, None),
        ((audit_row(), replace(audit_row(), seq=75)), False, "audit_chain_gap_or_hash_mismatch"),
        ((audit_row(),), True, "result_limit"),
        ((audit_row(),) * 257, False, "result_limit"),
        ((audit_row(correlation_id="other-corr"),), False, "action_correlation_mismatch"),
        ((audit_row(complete=True, watermark="caller-assertion"),), False, None),
        ((), False, "audit_chain_window_empty"),
        ((), True, "result_limit"),
    ],
    ids=[
        "no-anchor-or-watermark",
        "singleton-corrupt-hash",
        "shadow-is-not-intervention",
        "redacted-other-target-is-not-absence",
        "future-known-at",
        "wrong-target",
        "execution-unknown",
        "effect-pending",
        "noncontiguous-segment",
        "truncated",
        "oversized-without-truncated-flag",
        "correlation-mismatch",
        "caller-assertion-is-not-proof",
        "empty-is-unknown",
        "empty-truncated",
    ],
)
async def test_audit_witness_never_certifies_event_time_history(
    rows: tuple[ActionAuditHistoryRow, ...], truncated: bool, reason: str | None
) -> None:
    reader = Reader(ActionAuditHistoryRead(rows, truncated))
    read = await ActionAuditHistorySource(reader=reader).read(
        subject_ref=TARGET, start_at=START, end_at=END, known_at=KNOWN
    )

    assert read.checkpoint.complete is False
    assert read.records == ()
    assert read.checkpoint.limitation is not None
    assert "action_history_proof_unavailable" in read.checkpoint.limitation.split("+")
    if reason is not None:
        assert reason in read.checkpoint.limitation.split("+")
    assert read.checkpoint.subject_ref == TARGET
    assert read.checkpoint.known_at == KNOWN
    assert read.checkpoint.watermark == (
        f"audit-seq:{rows[-1].seq}:{rows[-1].entry_hash}" if rows else "audit-empty"
    )
    assert read.checkpoint.evidence_ref.startswith("state-store-audit-chain:")
    assert read.exhausted is (not truncated and len(rows) <= 256)
    assert reader.result.rows == rows
    assert reader.queries == [
        {
            "subject_ref": TARGET,
            "start_at": START,
            "end_at": END,
            "known_at": KNOWN,
            "limit": 257,
        }
    ]
