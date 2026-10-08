"""Tests for durable code-security review summaries in the state store."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.security.code_findings.review_signal import CodeSecurityReviewError
from fdai.delivery.persistence.state_store_code_security_review import (
    CodeSecurityReviewConflictError,
    code_security_review_state_key,
    record_code_security_review,
    record_review_from_environment,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_REVISION = "a" * 40


def _package(issue_count: int = 1) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "kind": "code-security-review",
        "repository_alias": "example-service",
        "revision": _REVISION,
        "review_digest": "4" * 64,
        "issue_count": issue_count,
        "by_priority": {"P0": 0, "P1": issue_count, "P2": 0, "P3": 0, "P4": 0},
        "by_severity": {
            "critical": 0,
            "high": issue_count,
            "medium": 0,
            "low": 0,
            "undetermined": 0,
        },
        "by_confidence": {
            "hypothesis": 0,
            "reported": 0,
            "corroborated": 0,
            "verified": issue_count,
            "proven": 0,
        },
        "known_exploited_count": 0,
        "exposure": "exposed",
        "coverage_complete": True,
        "top_issue_ids": ["FDAI-SEC-0123456789ab"][:issue_count],
        "review_required": True,
        "grants_authority": False,
    }


async def test_review_is_recorded_once_and_is_idempotent() -> None:
    store = InMemoryStateStore()
    at = datetime(2026, 10, 7, tzinfo=UTC)
    assert await record_code_security_review(store, _package(), recorded_at=at) is True
    assert await record_code_security_review(store, _package(), recorded_at=at) is False
    row = await store.read_state(code_security_review_state_key("example-service", _REVISION))
    assert row is not None
    assert row["package"]["by_confidence"]["verified"] == 1
    assert row["recorded_at"] == at.isoformat()


async def test_different_review_for_same_revision_is_refused() -> None:
    store = InMemoryStateStore()
    await record_code_security_review(store, _package())
    changed = {**_package(), "review_digest": "5" * 64}
    with pytest.raises(CodeSecurityReviewConflictError):
        await record_code_security_review(store, changed)


async def test_invalid_package_is_never_written() -> None:
    store = InMemoryStateStore()
    leaking = {**_package(), "path": "src/app.py"}
    with pytest.raises(CodeSecurityReviewError):
        await record_code_security_review(store, leaking)
    assert (
        await store.read_state(code_security_review_state_key("example-service", _REVISION)) is None
    )


async def test_environment_recording_requires_a_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FDAI_STATE_STORE_DSN", raising=False)
    monkeypatch.delenv("FDAI_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="FDAI_STATE_STORE_DSN"):
        await record_review_from_environment(_package())


def _sourced(trigger: str, request_id: str | None) -> dict[str, object]:
    return {
        **_package(),
        "schema_version": "1.1.0",
        "source": {
            "kind": "git_repository",
            "provider": "github",
            "revision_kind": "commit",
            "trigger": trigger,
            "request_id": request_id,
        },
        "producers": ["Opengrep"],
    }


async def test_same_findings_from_another_trigger_are_a_duplicate_not_a_conflict() -> None:
    store = InMemoryStateStore()
    assert await record_code_security_review(store, _sourced("cli", None)) is True
    assert (
        await record_code_security_review(store, _sourced("console", "operator-" + "b" * 32))
        is False
    )
    row = await store.read_state(code_security_review_state_key("example-service", _REVISION))
    assert row is not None and row["package"]["source"]["trigger"] == "cli"
    with pytest.raises(CodeSecurityReviewConflictError):
        await record_code_security_review(store, {**_sourced("cli", None), "exposure": "internal"})


async def test_issue_summaries_are_recorded_once_beside_the_review() -> None:
    from fdai.delivery.persistence.state_store_code_security_review import (
        code_security_issues_state_key,
    )

    store = InMemoryStateStore()
    summary = {
        "issue_id": "FDAI-SEC-0123456789ab",
        "priority": "P1",
        "due_days": 7,
        "severity": "high",
        "confidence": "verified",
        "weakness_class": "command_injection",
        "cwe_ids": [78],
        "advisory_ids": [],
        "package": None,
        "producers": ["Opengrep"],
        "known_exploited": False,
    }
    await record_code_security_review(store, _package(), issues=[summary])
    key = code_security_issues_state_key("example-service", _REVISION)
    row = await store.read_state(key)
    assert row is not None and row["review_digest"] == "4" * 64
    assert row["issues"] == [summary] and row["truncated"] is False
    await record_code_security_review(store, _package(), issues=[], issues_truncated=True)
    again = await store.read_state(key)
    assert again is not None and again["issues"] == [summary]
    with pytest.raises(ValueError):
        await record_code_security_review(store, _package(), issues=[{**summary, "path": "x.py"}])
