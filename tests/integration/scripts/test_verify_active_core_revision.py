from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "deployment"
    / "azure"
    / "verify_active_core_revision.py"
)


@pytest.fixture(scope="module")
def module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_active_core_revision", _SCRIPT)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def _revision(*, bound: bool = True) -> dict[str, object]:
    environment = [{"name": "RUNTIME_ENV", "value": "dev"}]
    if bound:
        environment.extend(
            (
                {"name": "LLM_MODE", "value": "azure"},
                {"name": "LLM_RESOLVED_MODELS_PATH", "value": "/app/resolved-models.json"},
                {"name": "LLM_RESOLVED_MODELS_SHA256", "value": "a" * 64},
            )
        )
    return {
        "name": "core--revision",
        "properties": {
            "active": True,
            "healthState": "Healthy",
            "provisioningState": "Provisioned",
            "template": {
                "containers": [
                    {
                        "name": "core",
                        "image": "ghcr.io/example/core@sha256:" + "b" * 64,
                        "env": environment,
                    }
                ]
            },
        },
    }


def _write(root: Path, payload: object) -> Path:
    path = root / "revision.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_returns_healthy_bound_revision(module: ModuleType, tmp_path: Path) -> None:
    result = module.active_core_binding(_write(tmp_path, _revision()), require_model_binding=True)

    assert result == {
        "revision": "core--revision",
        "image": "ghcr.io/example/core@sha256:" + "b" * 64,
        "image_digest": "b" * 64,
        "runtime_model_digest": "a" * 64,
    }


def test_allows_unbound_revision_only_for_explicit_bootstrap(
    module: ModuleType, tmp_path: Path
) -> None:
    path = _write(tmp_path, _revision(bound=False))

    assert (
        module.active_core_binding(path, require_model_binding=False)["runtime_model_digest"] == ""
    )
    with pytest.raises(module.ActiveCoreRevisionError, match="no exact model binding"):
        module.active_core_binding(path, require_model_binding=True)


@pytest.mark.parametrize("field", ["active", "healthState", "provisioningState"])
def test_rejects_ineligible_revision(module: ModuleType, tmp_path: Path, field: str) -> None:
    payload = _revision()
    properties = payload["properties"]
    assert isinstance(properties, dict)
    properties[field] = False if field == "active" else "Failed"

    with pytest.raises(module.ActiveCoreRevisionError, match="not active, healthy"):
        module.active_core_binding(_write(tmp_path, payload), require_model_binding=True)
