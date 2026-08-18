from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.delivery import rule_collector_job_cli
from fdai.delivery.rule_collector_job_cli import record_success_receipts
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _receipt() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "source_id": "example-source",
        "resolved_revision": "abc123",
        "content_sha256": "0" * 64,
        "license": "Apache-2.0",
        "redistribution": "embeddable",
        "verified_rules": 3,
        "verified_at": datetime(2026, 8, 19, tzinfo=UTC).isoformat(),
        "schema_validated": True,
        "provenance_validated": True,
    }


def _summary(receipt: dict[str, object] | None = None) -> dict[str, Any]:
    collect: dict[str, object] = {}
    if receipt is not None:
        collect["success_receipt"] = receipt
    return {
        "entries": [
            {
                "source_id": "example-source",
                "collect_exit_code": 0,
                "collect": collect,
            }
        ]
    }


async def test_success_receipt_persistence_is_restart_idempotent() -> None:
    store = InMemoryStateStore()
    summary = _summary(_receipt())

    assert await record_success_receipts(store, summary) == 1
    assert await record_success_receipts(store, summary) == 0

    states = await store.read_states("runtime:collector-success:", limit=10)
    assert len(states) == 1
    assert states[0]["resolved_revision"] == "abc123"
    assert len(tuple(store.audit_entries)) == 1


async def test_invalid_success_receipt_is_not_persisted() -> None:
    store = InMemoryStateStore()
    receipt = _receipt()
    receipt["provenance_validated"] = False

    with pytest.raises(ValueError, match="provenance validation"):
        await record_success_receipts(store, _summary(receipt))

    assert await store.read_states("runtime:collector-success:", limit=10) == ()
    assert tuple(store.audit_entries) == ()


def test_job_wrapper_forces_verify_and_records_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: list[str] = []

    def fake_watcher(argv: list[str]) -> int:
        seen.extend(argv)
        print(json.dumps(_summary(_receipt())))
        return 0

    monkeypatch.setattr(rule_collector_job_cli, "watcher_main", fake_watcher)
    store = InMemoryStateStore()

    assert rule_collector_job_cli.main([], store=store) == 0
    payload = json.loads(capsys.readouterr().out)

    assert "--verify" in seen
    assert payload["recorded_success_receipts"] == 1


def test_job_wrapper_sanitizes_persistence_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_watcher(argv: list[str]) -> int:  # noqa: ARG001
        print(json.dumps(_summary(_receipt())))
        return 0

    monkeypatch.setattr(rule_collector_job_cli, "watcher_main", fake_watcher)

    assert rule_collector_job_cli.main([], store=None) == 2
    assert "RuntimeError" in capsys.readouterr().err
