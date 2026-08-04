"""Bounded application log signal candidate tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from fdai.delivery.kubernetes.log_signals import bounded_log_signal_findings

_CUTOFF = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("body", "signal"),
    [
        ("JSONDecodeError malformed payload", "message_decode_failure"),
        ("partition offset stalled", "stream_progress_blocked"),
        ("worker exception failed", "application_failure"),
    ],
)
def test_log_signals_require_repeated_recent_exact_uid_records(body: str, signal: str) -> None:
    later = _record(body)
    later["observed_at"] = "2026-08-04T11:59:01Z"
    findings = bounded_log_signal_findings(
        [_record(body), later], evidence_complete=True, evidence_cutoff=_CUTOFF
    )
    assert findings[0]["signal_class"] == signal
    assert findings[0]["occurrence_count"] == 2
    assert body not in str(findings)


def test_log_signals_abstain_on_truncated_single_or_stale_evidence() -> None:
    records = [_record("worker exception failed")]
    stale = [_record("worker exception failed"), _record("worker exception failed")]
    for record in stale:
        record["observed_at"] = "2026-08-04T11:40:00Z"
    assert not bounded_log_signal_findings(
        records * 2, evidence_complete=False, evidence_cutoff=_CUTOFF
    )
    assert not bounded_log_signal_findings(records, evidence_complete=True, evidence_cutoff=_CUTOFF)
    assert not bounded_log_signal_findings(stale, evidence_complete=True, evidence_cutoff=_CUTOFF)


def test_log_signals_abstain_on_missing_uid_oversized_or_unrecognized_body() -> None:
    missing = [_record("worker exception failed"), _record("worker exception failed")]
    missing[0].pop("pod_uid")
    oversized = [_record("error" + "x" * 1_024)] * 2
    unknown = [_record("healthy request"), _record("healthy request")]
    assert not bounded_log_signal_findings(missing, evidence_complete=True, evidence_cutoff=_CUTOFF)
    assert not bounded_log_signal_findings(
        oversized, evidence_complete=True, evidence_cutoff=_CUTOFF
    )
    assert not bounded_log_signal_findings(unknown, evidence_complete=True, evidence_cutoff=_CUTOFF)


def test_log_signals_do_not_count_exact_duplicate_delivery_twice() -> None:
    record = _record("worker exception failed")

    assert not bounded_log_signal_findings(
        [record, deepcopy(record)],
        evidence_complete=True,
        evidence_cutoff=_CUTOFF,
    )


def test_log_signals_are_metamorphic_to_order_and_identity_rename() -> None:
    later = _record("worker exception failed")
    later["observed_at"] = "2026-08-04T11:59:01Z"
    records = [_record("worker exception failed"), later]
    expected = bounded_log_signal_findings(records, evidence_complete=True, evidence_cutoff=_CUTOFF)
    renamed = deepcopy(records)
    for record in renamed:
        record["namespace"] = "renamed-app"
    assert (
        bounded_log_signal_findings(
            list(reversed(records)), evidence_complete=True, evidence_cutoff=_CUTOFF
        )
        == expected
    )
    assert (
        bounded_log_signal_findings(renamed, evidence_complete=True, evidence_cutoff=_CUTOFF)[0][
            "resource"
        ]["namespace"]
        == "renamed-app"
    )


def _record(body: str) -> dict[str, object]:
    return {
        "namespace": "example-app",
        "pod": "api-1",
        "pod_uid": "pod-uid",
        "container": "api",
        "observed_at": "2026-08-04T11:59:00Z",
        "body": body,
    }
