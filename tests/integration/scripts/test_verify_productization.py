from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "deployment" / "release" / "verify-productization.sh"
PROJECT_PATHS = (
    REPO_ROOT / "packages" / "service-contracts" / "pyproject.toml",
    REPO_ROOT / "services" / "core-control-plane" / "pyproject.toml",
    REPO_ROOT / "services" / "operator-service" / "pyproject.toml",
    REPO_ROOT / "services" / "document-ingestion-api" / "pyproject.toml",
    REPO_ROOT / "services" / "document-processing-worker" / "pyproject.toml",
    REPO_ROOT / "services" / "isolated-executor" / "pyproject.toml",
)


def _array_values(name: str) -> tuple[str, ...]:
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    match = re.search(rf"^{name}=\(\n(?P<body>.*?)^\)$", script, flags=re.MULTILINE | re.DOTALL)
    assert match is not None, name
    return tuple(
        line.strip()
        for line in match.group("body").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


@pytest.mark.parametrize("array_name", ("python_paths", "test_paths"))
def test_productization_validation_paths_exist(array_name: str) -> None:
    missing = [path for path in _array_values(array_name) if not (REPO_ROOT / path).exists()]

    assert missing == []


def test_productization_builds_every_independent_distribution() -> None:
    expected = {
        tomllib.loads(path.read_text(encoding="utf-8"))["project"]["name"] for path in PROJECT_PATHS
    }

    assert set(_array_values("distribution_packages")) == expected
