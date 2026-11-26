from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "deployment" / "azure" / "verify_job_image.py"
)
_EXPECTED_IMAGE = "example.azurecr.io/fdai@sha256:" + "a" * 64


@pytest.fixture(scope="module")
def module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_job_image", _SCRIPT)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def _write_job(root: Path, *, image: str = _EXPECTED_IMAGE) -> Path:
    path = root / "job.json"
    path.write_text(
        json.dumps(
            {
                "properties": {
                    "provisioningState": "Succeeded",
                    "template": {
                        "containers": [
                            {
                                "name": "inventory",
                                "image": image,
                            }
                        ]
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_accepts_exact_digest_pinned_job_image(module: ModuleType, tmp_path: Path) -> None:
    result = module.verify_job_image(
        _write_job(tmp_path),
        container_name="inventory",
        expected_image=_EXPECTED_IMAGE,
    )

    assert result == {"container": "inventory", "image_digest": "a" * 64}


def test_rejects_stale_job_image(module: ModuleType, tmp_path: Path) -> None:
    stale_image = "example.azurecr.io/fdai@sha256:" + "b" * 64

    with pytest.raises(module.JobImageVerificationError, match="does not match"):
        module.verify_job_image(
            _write_job(tmp_path, image=stale_image),
            container_name="inventory",
            expected_image=_EXPECTED_IMAGE,
        )


@pytest.mark.parametrize(
    ("provisioning_state", "containers", "message"),
    [
        ("Failed", [{"name": "inventory", "image": _EXPECTED_IMAGE}], "not successfully"),
        ("Succeeded", [], "missing or ambiguous"),
        (
            "Succeeded",
            [
                {"name": "inventory", "image": _EXPECTED_IMAGE},
                {"name": "inventory", "image": _EXPECTED_IMAGE},
            ],
            "missing or ambiguous",
        ),
    ],
)
def test_rejects_invalid_job_state(
    module: ModuleType,
    tmp_path: Path,
    provisioning_state: str,
    containers: list[dict[str, str]],
    message: str,
) -> None:
    path = tmp_path / "job.json"
    path.write_text(
        json.dumps(
            {
                "properties": {
                    "provisioningState": provisioning_state,
                    "template": {"containers": containers},
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.JobImageVerificationError, match=message):
        module.verify_job_image(
            path,
            container_name="inventory",
            expected_image=_EXPECTED_IMAGE,
        )
