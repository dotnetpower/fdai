from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts/deployment/azure/verify-authoritative-catalogs.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_authoritative_catalogs", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Store:
    def __init__(self, values: dict[str, dict[str, object]]) -> None:
        self._values = values

    async def read_state(self, key: str) -> dict[str, object] | None:
        return self._values.get(key)


@pytest.mark.asyncio
async def test_verify_compares_every_immutable_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    expected = {
        "immutable": {"_revision": "sha256:abc", "value": 1},
        "evidence-health": {"dynamic": True},
        "release-diff": {"dynamic": True},
    }
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://example.invalid/fdai")
    monkeypatch.setattr(
        module,
        "_materializer",
        lambda _root: SimpleNamespace(
            catalog_snapshots=lambda _repo: expected,
            ONTOLOGY_EVIDENCE_HEALTH_KEY="evidence-health",
            ONTOLOGY_RELEASE_DIFF_KEY="release-diff",
        ),
    )
    monkeypatch.setattr(
        module,
        "PostgresStateStore",
        lambda config: _Store({"immutable": expected["immutable"]}),
    )

    assert await module.verify(_ROOT) == 1


@pytest.mark.asyncio
async def test_verify_rejects_a_postgresql_projection_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://example.invalid/fdai")
    monkeypatch.setattr(
        module,
        "_materializer",
        lambda _root: SimpleNamespace(
            catalog_snapshots=lambda _repo: {"immutable": {"value": 1}},
            ONTOLOGY_EVIDENCE_HEALTH_KEY="evidence-health",
            ONTOLOGY_RELEASE_DIFF_KEY="release-diff",
        ),
    )
    monkeypatch.setattr(
        module,
        "PostgresStateStore",
        lambda config: _Store({"immutable": {"value": 2}}),
    )

    with pytest.raises(RuntimeError, match="readback mismatch"):
        await module.verify(_ROOT)
