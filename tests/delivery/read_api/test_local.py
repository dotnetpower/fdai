"""Tests for the dev-mode entrypoint at :mod:`aiopspilot.delivery.read_api._local`."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from aiopspilot.delivery.read_api import _local

_DEV_ENV = "AIOPSPILOT_READ_API_DEV_MODE"


class TestLocalEntrypoint:
    def test_refuses_without_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_DEV_ENV, raising=False)
        with pytest.raises(RuntimeError, match=_DEV_ENV):
            _local.app()

    def test_builds_and_serves_seeded_data(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_DEV_ENV, "1")
        application = _local.app()
        assert isinstance(application, Starlette)
        client = TestClient(application)
        # Seed produced at least one audit row + one HIL entry.
        audit = client.get("/audit").json()
        assert len(audit["items"]) >= 1
        hil = client.get("/hil-queue").json()
        assert len(hil["items"]) >= 1
        kpi = client.get("/kpi").json()
        assert kpi["event_count"] >= 1
        assert kpi["hil_pending"] >= 1
