"""Application socket bind conflict candidate tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from fdai.delivery.kubernetes.socket_bind import socket_bind_conflict_findings

_CUTOFF = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "body",
    [
        "listen failed with EADDRINUSE",
        "nc: bind: Address already in use",
        "OSError: [Errno 98] address unavailable",
    ],
)
def test_socket_bind_conflict_recognizes_reviewed_signatures_without_raw_body(body: str) -> None:
    records = _records()
    records[0]["body"] = body

    findings = socket_bind_conflict_findings(
        records,
        evidence_complete=True,
        evidence_cutoff=_CUTOFF,
    )

    assert findings[0]["reason"] == "application_socket_bind_conflict_candidate"
    assert findings[0]["resource"]["uid"] == "pod-uid"
    assert findings[0]["container"] == "sidecar"
    assert findings[0]["occurrence_count"] == 1
    assert body not in str(findings)


def test_socket_bind_conflict_abstains_on_truncated_or_stale_evidence() -> None:
    stale = _records()
    stale[0]["observed_at"] = "2026-08-04T11:40:00Z"

    assert not socket_bind_conflict_findings(
        _records(), evidence_complete=False, evidence_cutoff=_CUTOFF
    )
    assert not socket_bind_conflict_findings(stale, evidence_complete=True, evidence_cutoff=_CUTOFF)


def test_socket_bind_conflict_abstains_on_future_or_missing_uid_record() -> None:
    future = _records()
    future[0]["observed_at"] = (_CUTOFF + timedelta(seconds=1)).isoformat()
    missing_uid = _records()
    missing_uid[0].pop("pod_uid")

    assert not socket_bind_conflict_findings(
        future, evidence_complete=True, evidence_cutoff=_CUTOFF
    )
    assert not socket_bind_conflict_findings(
        missing_uid, evidence_complete=True, evidence_cutoff=_CUTOFF
    )


def test_socket_bind_conflict_rejects_malformed_or_unreviewed_body() -> None:
    oversized = _records()
    oversized[0]["body"] = "EADDRINUSE" + "x" * 1_024
    unrelated = _records()
    unrelated[0]["body"] = "connection refused"

    assert not socket_bind_conflict_findings(
        oversized, evidence_complete=True, evidence_cutoff=_CUTOFF
    )
    assert not socket_bind_conflict_findings(
        unrelated, evidence_complete=True, evidence_cutoff=_CUTOFF
    )


def test_socket_bind_conflict_is_metamorphic_to_order_and_identity_rename() -> None:
    records = [*_records(), {**_records()[0], "observed_at": "2026-08-04T11:58:00Z"}]
    expected = socket_bind_conflict_findings(
        records, evidence_complete=True, evidence_cutoff=_CUTOFF
    )
    renamed = deepcopy(records)
    for record in renamed:
        record["namespace"] = "renamed-app"
        record["pod"] = "renamed-pod"

    assert (
        socket_bind_conflict_findings(
            list(reversed(records)), evidence_complete=True, evidence_cutoff=_CUTOFF
        )
        == expected
    )
    renamed_finding = socket_bind_conflict_findings(
        renamed, evidence_complete=True, evidence_cutoff=_CUTOFF
    )[0]
    assert renamed_finding["resource"]["namespace"] == "renamed-app"
    assert renamed_finding["resource"]["name"] == "renamed-pod"


def _records() -> list[dict[str, object]]:
    return [
        {
            "namespace": "example-app",
            "pod": "api-1",
            "pod_uid": "pod-uid",
            "container": "sidecar",
            "observed_at": "2026-08-04T11:59:00Z",
            "body": "listen failed with EADDRINUSE",
        }
    ]
