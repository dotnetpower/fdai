from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.case_history import (
    CaseHistoryRevision,
    CaseKind,
    CaseSourceRecord,
    build_case_history_revision,
)

T0 = datetime(2026, 7, 1, tzinfo=UTC)


def _source(record_id: str, *, value: float, seconds: int) -> CaseSourceRecord:
    payload = {"metric": "capacity_percent", "value": value}
    digest = hashlib.sha256(f"{record_id}:{value}".encode()).hexdigest()
    return CaseSourceRecord(
        record_type="forecast-outcome",
        record_id=record_id,
        record_digest=digest,
        occurred_at=T0 + timedelta(seconds=seconds),
        payload=payload,
    )


def _revision(sources: list[CaseSourceRecord]) -> CaseHistoryRevision:
    return build_case_history_revision(
        case_id="case-1",
        revision=1,
        kind=CaseKind.PREDICTION,
        correlation_id="corr-1",
        purpose="forecast-error-analysis",
        access_scope_digest="b" * 64,
        redaction_policy_version="1.0.0",
        event_time_cutoff=T0 + timedelta(hours=1),
        created_by_agent="Muninn",
        sealed_at=T0 + timedelta(hours=2),
        parent_manifest_digest=None,
        sources=sources,
    )


def test_case_history_digest_is_stable_under_input_reorder() -> None:
    first = _source("source-1", value=91.0, seconds=1)
    second = _source("source-2", value=94.0, seconds=2)
    assert _revision([first, second]).manifest_digest == _revision([second, first]).manifest_digest


def test_case_history_digest_changes_when_evidence_changes() -> None:
    first = _revision([_source("source-1", value=91.0, seconds=1)])
    changed = _revision([_source("source-1", value=92.0, seconds=1)])
    assert first.manifest_digest != changed.manifest_digest


def test_case_history_rejects_hidden_reasoning_recursively() -> None:
    with pytest.raises(ValueError, match="forbidden fields"):
        CaseSourceRecord(
            record_type="analysis",
            record_id="source-1",
            record_digest="a" * 64,
            occurred_at=T0,
            payload={"nested": {"chain_of_thought": "not allowed"}},
        )


@pytest.mark.parametrize(
    "secret_key",
    [
        "access_token",
        "AccessToken",
        "client-secret",
        "client.secret",
        "connection_string",
        "ConnectionString",
        "connection string",
        "api_key",
        "password",
        "sas-token",
    ],
)
def test_case_history_rejects_common_secret_fields_recursively(secret_key: str) -> None:
    with pytest.raises(ValueError, match="forbidden fields"):
        CaseSourceRecord(
            record_type="analysis",
            record_id="source-1",
            record_digest="a" * 64,
            occurred_at=T0,
            payload={"nested": {secret_key: "not allowed"}},
        )


@pytest.mark.parametrize(
    "secret_value",
    [
        "Bearer abcdefghijklmnopqrstuvwxyz012345",
        "Bearer%20abcdefghijklmnopqrstuvwxyz012345",
        "https://storage.example/x?sv=1&sig=abcdefghijklmnopqrstuvwxyz",
        "https://storage.example/x?sv=1%26sig%3Dabcdefghijklmnopqrstuvwxyz",
        "postgresql://operator:short-secret@db.example/app",
        "Endpoint=sb://example/;SharedAccessKey=short",
        "aaaaaaaaaa.bbbbbbbbbb.cccccccccc",
        "-----BEGIN PRIVATE KEY-----\nnot-a-real-key",
    ],
)
def test_case_history_rejects_secret_like_values_under_neutral_keys(
    secret_value: str,
) -> None:
    with pytest.raises(ValueError, match="secret-like value"):
        CaseSourceRecord(
            record_type="analysis",
            record_id="source-1",
            record_digest="a" * 64,
            occurred_at=T0,
            payload={"nested": {"detail": secret_value}},
        )
