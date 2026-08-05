"""Tests for real local semantic model wiring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fdai.delivery.operator_api.dev.model_wiring import _build_local_embedder


def _write_resolved(path: Path, *, status: str = "resolved") -> None:
    path.write_text(
        json.dumps(
            {
                "capabilities": [
                    {
                        "name": "t1.embedding",
                        "status": status,
                        "family": "text-embedding-3-small",
                    }
                ],
                "narrator": {"endpoint": "https://example.openai.azure.com/"},
            }
        ),
        encoding="utf-8",
    )


def test_local_embedder_uses_resolved_embedding_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = tmp_path / "resolved-models.json"
    _write_resolved(resolved)
    monkeypatch.delenv("FDAI_EMBEDDING_ENDPOINT", raising=False)
    monkeypatch.delenv("FDAI_EMBEDDING_DEPLOYMENT", raising=False)

    embedder, shutdown_callbacks = _build_local_embedder(resolved)

    assert embedder is not None
    assert embedder.dim == 384
    assert len(shutdown_callbacks) == 1


def test_local_embedder_fails_closed_on_partial_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = tmp_path / "resolved-models.json"
    _write_resolved(resolved)
    monkeypatch.setenv("FDAI_EMBEDDING_ENDPOINT", "https://override.example/")
    monkeypatch.delenv("FDAI_EMBEDDING_DEPLOYMENT", raising=False)

    with pytest.raises(ValueError, match="configured together"):
        _build_local_embedder(resolved)


def test_local_embedder_is_absent_for_unresolved_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = tmp_path / "resolved-models.json"
    _write_resolved(resolved, status="hil-only")
    monkeypatch.delenv("FDAI_EMBEDDING_ENDPOINT", raising=False)
    monkeypatch.delenv("FDAI_EMBEDDING_DEPLOYMENT", raising=False)

    assert _build_local_embedder(resolved) == (None, ())


def test_local_embedder_is_absent_when_resolved_models_are_not_provisioned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FDAI_EMBEDDING_ENDPOINT", raising=False)
    monkeypatch.delenv("FDAI_EMBEDDING_DEPLOYMENT", raising=False)

    assert _build_local_embedder(tmp_path / "missing.json") == (None, ())


def test_local_embedder_honors_off_toggle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = tmp_path / "resolved-models.json"
    _write_resolved(resolved)
    monkeypatch.setenv("FDAI_INVENTORY_SEMANTIC_ENABLED", "off")
    monkeypatch.setenv("FDAI_EMBEDDING_ENDPOINT", "https://override.example/")
    monkeypatch.setenv("FDAI_EMBEDDING_DEPLOYMENT", "embedding-example")

    assert _build_local_embedder(resolved) == (None, ())
