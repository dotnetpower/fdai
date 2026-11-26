from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/deployment/service/apply_image_build_override.py"
SERVICE_IDS = (
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
)
DISTRIBUTIONS = {
    "core-control-plane": "fdai-core-control-plane",
    "operator-service": "fdai-operator-service",
    "document-ingestion-api": "fdai-document-ingestion-api",
    "document-processing-worker": "fdai-document-processing-worker",
    "isolated-executor": "fdai-isolated-executor-service",
}


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("apply_image_build_override_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repository(tmp_path: Path, *, state: str = "active") -> Path:
    root = tmp_path / "repository"
    (root / "config").mkdir(parents=True)
    payload = {
        "schema_version": 1,
        "state": state,
        "distribution_version": "0.1.2",
        "services": list(SERVICE_IDS),
        "purpose": "corrected-n-minus-one-transition-artifacts",
    }
    (root / "config/service-image-build-override.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    lock_entries = []
    for service_id in SERVICE_IDS:
        service_root = root / "services" / service_id
        service_root.mkdir(parents=True)
        (service_root / "pyproject.toml").write_text(
            f'[project]\nname = "{DISTRIBUTIONS[service_id]}"\nversion = "0.1.3"\n',
            encoding="utf-8",
        )
        lock_entries.append(
            f'[[package]]\nname = "{DISTRIBUTIONS[service_id]}"\nversion = "0.1.3"\n'
        )
    (root / "uv.lock").write_text("\n".join(lock_entries), encoding="utf-8")
    return root


def test_active_override_materializes_all_five_versions(tmp_path: Path) -> None:
    module = _module()
    root = _repository(tmp_path)

    assert module.apply_override(root) == "0.1.2"

    for service_id in SERVICE_IDS:
        assert 'version = "0.1.2"' in (root / "services" / service_id / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    assert (root / "uv.lock").read_text(encoding="utf-8").count('version = "0.1.2"') == 5


def test_inactive_override_does_not_mutate_checkout(tmp_path: Path) -> None:
    module = _module()
    root = _repository(tmp_path, state="inactive")
    before = (root / "uv.lock").read_bytes()

    assert module.apply_override(root) is None
    assert (root / "uv.lock").read_bytes() == before


def test_override_rejects_noncanonical_service_order(tmp_path: Path) -> None:
    module = _module()
    root = _repository(tmp_path)
    path = root / "config/service-image-build-override.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["services"].reverse()
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(module.ImageBuildOverrideError, match="service order"):
        module.apply_override(root)
