"""Runtime composition of the exemption lifecycle worker from the installed catalog."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fdai.runtime import configuration, delivery
from fdai.runtime.exemption_lifecycle import (
    ExemptionLifecycleWorker,
    build_runtime_exemption_lifecycle_worker,
    load_catalog_exemptions,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_CONTAINER = SimpleNamespace(
    config=SimpleNamespace(rule_governance=SimpleNamespace(exemption_alert_lead_days=14))
)


def _write_exemption(root: Path, exemption_id: str = "e.soon") -> None:
    directory = root / "exemptions"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{exemption_id}.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "id": exemption_id,
                "rule_id": "rule-a",
                "scope": {
                    "subscription_id": "00000000-0000-0000-0000-000000000000",
                    "resource_group": "rg-a",
                },
                "justification": "Waived while a migration is being completed for this scope.",
                "requested_by": "00000000-0000-0000-0000-000000000001",
                "approved_by": "00000000-0000-0000-0000-000000000002",
                "state": "active",
                "created_at": "2026-08-01T00:00:00Z",
                "expires_at": "2026-08-25T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )


def _build(environment: dict[str, str] | None = None):
    return build_runtime_exemption_lifecycle_worker(
        _CONTAINER, None, InMemoryStateStore(), environment or {}
    )


async def test_no_catalog_exemption_means_no_worker(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(configuration, "_resolve_catalog_root", lambda: tmp_path)

    assert await _build() is None


async def test_an_installed_exemption_composes_the_worker(tmp_path, monkeypatch) -> None:
    _write_exemption(tmp_path)
    monkeypatch.setattr(configuration, "_resolve_catalog_root", lambda: tmp_path)
    monkeypatch.setattr(delivery, "_build_notification_router", lambda *a, **k: object())

    worker = await _build()

    assert isinstance(worker, ExemptionLifecycleWorker)


async def test_the_operator_can_disable_the_worker(tmp_path, monkeypatch) -> None:
    _write_exemption(tmp_path)
    monkeypatch.setattr(configuration, "_resolve_catalog_root", lambda: tmp_path)
    monkeypatch.setattr(delivery, "_build_notification_router", lambda *a, **k: object())

    assert await _build({"FDAI_EXEMPTION_LIFECYCLE_ENABLED": "false"}) is None


async def test_a_router_failure_never_blocks_startup(tmp_path, monkeypatch) -> None:
    _write_exemption(tmp_path)
    monkeypatch.setattr(configuration, "_resolve_catalog_root", lambda: tmp_path)

    def broken(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("router unavailable")

    monkeypatch.setattr(delivery, "_build_notification_router", broken)

    assert await _build() is None


def test_the_exemption_only_loader_fails_closed_on_an_invalid_file(tmp_path) -> None:
    (tmp_path / "exemptions").mkdir()
    (tmp_path / "exemptions" / "bad.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError):
        load_catalog_exemptions(tmp_path)


def test_the_exemption_only_loader_returns_valid_exemptions(tmp_path) -> None:
    _write_exemption(tmp_path)

    assert [item.id for item in load_catalog_exemptions(tmp_path)] == ["e.soon"]
    assert load_catalog_exemptions(tmp_path / "missing") == ()
