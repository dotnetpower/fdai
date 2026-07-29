"""CyberGym installed-adapter plugin tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai_evaluation_sdk import EVALUATION_API_VERSION

from fdai_bench_cybergym.plugin import create_plugin


def _manifest(tmp_path: Path, **overrides: object) -> Path:
    payload: dict[str, object] = {
        "session_id": "session-1",
        "task_id": "task-1",
        "mode": "e2e",
        "source_workspace_ref": "curl/arvo_66012",
        "deadline": "2026-07-29T12:00:00+00:00",
    }
    payload.update(overrides)
    path = tmp_path / "task.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_plugin_requires_task_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CYBERGYM_TASK_MANIFEST", raising=False)
    with pytest.raises(RuntimeError, match="CYBERGYM_TASK_MANIFEST"):
        create_plugin().create_adapter()


def test_plugin_loads_e2e_manifest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CYBERGYM_TASK_MANIFEST", str(_manifest(tmp_path)))
    plugin = create_plugin()
    adapter = plugin.create_adapter()
    assert plugin.api_version == EVALUATION_API_VERSION
    assert plugin.plugin_id == "cybergym"
    assert adapter.adapter_id == "cybergym"


@pytest.mark.parametrize(
    "payload",
    (
        [],
        {"mode": "e2e"},
        {
            "session_id": "session-1",
            "task_id": "task-1",
            "mode": "unknown",
            "source_workspace_ref": "curl/arvo_66012",
            "deadline": "2026-07-29T12:00:00+00:00",
        },
    ),
)
def test_plugin_rejects_invalid_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: object,
) -> None:
    path = tmp_path / "task.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("CYBERGYM_TASK_MANIFEST", str(path))
    with pytest.raises(RuntimeError, match="manifest"):
        create_plugin().create_adapter()
