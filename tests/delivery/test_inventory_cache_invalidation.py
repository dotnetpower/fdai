from __future__ import annotations

import os
from pathlib import Path

import pytest

from fdai.delivery.inventory_cache_invalidation import InvalidatingInventoryDeltaProjector


async def test_advances_marker_only_after_durable_projection_succeeds(tmp_path: Path) -> None:
    marker = tmp_path / "invalidated"

    async def project(payload: object) -> str:
        assert payload == {"inventory_change": {"kind": "upsert"}}
        return "applied"

    projector = InvalidatingInventoryDeltaProjector(inner=project, marker_path=marker)
    assert await projector({"inventory_change": {"kind": "upsert"}}) == "applied"
    assert marker.read_text(encoding="ascii") == "inventory.resource_changed\n"
    assert os.stat(marker).st_mode & 0o777 == 0o600


async def test_does_not_advance_marker_when_projection_fails(tmp_path: Path) -> None:
    marker = tmp_path / "invalidated"

    async def fail(payload: object) -> None:
        del payload
        raise RuntimeError("projection failed")

    projector = InvalidatingInventoryDeltaProjector(inner=fail, marker_path=marker)
    with pytest.raises(RuntimeError, match="projection failed"):
        await projector({})
    assert not marker.exists()


async def test_marker_failure_does_not_undo_durable_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from fdai.delivery import inventory_cache_invalidation as module

    async def project(payload: object) -> str:
        del payload
        return "applied"

    def fail_marker(path: Path) -> None:
        del path
        raise OSError("cache directory unavailable")

    monkeypatch.setattr(module, "_advance_marker", fail_marker)
    projector = InvalidatingInventoryDeltaProjector(
        inner=project,
        marker_path=tmp_path / "invalidated",
    )

    assert await projector({"inventory_change": {"kind": "upsert"}}) == "applied"
    assert "inventory_cache_invalidation_marker_failed" in caplog.text


@pytest.mark.parametrize(
    "payload",
    [
        {"inventory_change": {"kind": "upsert"}},
        {"payload": {"inventory_change": {"kind": "delete"}}},
    ],
)
async def test_advances_marker_for_direct_and_nested_inventory_changes(
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    marker = tmp_path / "invalidated"

    async def project(value: object) -> str:
        del value
        return "applied"

    projector = InvalidatingInventoryDeltaProjector(inner=project, marker_path=marker)

    assert await projector(payload) == "applied"
    assert marker.exists()


async def test_does_not_invalidate_cache_for_unrelated_events(tmp_path: Path) -> None:
    marker = tmp_path / "invalidated"

    async def project(payload: object) -> str:
        del payload
        return "ignored"

    projector = InvalidatingInventoryDeltaProjector(inner=project, marker_path=marker)

    assert await projector({"event_type": "audit.done"}) == "ignored"
    assert not marker.exists()
