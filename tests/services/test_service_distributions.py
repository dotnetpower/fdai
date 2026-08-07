from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = REPO_ROOT / "services"

EXPECTED = {
    "core-control-plane": ("fdai-core-control-plane", "fdai-core-control-plane"),
    "operator-service": ("fdai-operator-service", "fdai-operator-service"),
    "document-ingestion-api": (
        "fdai-document-ingestion-api",
        "fdai-document-ingestion-api",
    ),
    "document-processing-worker": (
        "fdai-document-processing-worker",
        "fdai-document-processing-worker",
    ),
    "isolated-executor": (
        "fdai-isolated-executor-service",
        "fdai-isolated-executor-service",
    ),
}


def test_five_service_distributions_have_owned_entrypoints() -> None:
    assert {path.name for path in SERVICE_ROOT.iterdir() if path.is_dir()} == set(EXPECTED)
    distributions: set[str] = set()
    scripts: set[str] = set()
    for service_id, (distribution, script) in EXPECTED.items():
        project = tomllib.loads((SERVICE_ROOT / service_id / "pyproject.toml").read_text())
        assert project["project"]["name"] == distribution
        assert script in project["project"]["scripts"]
        assert "fdai-service-contracts==0.1.0" in project["project"]["dependencies"]
        distributions.add(distribution)
        scripts.add(script)
    assert len(distributions) == 5
    assert len(scripts) == 5


def test_service_contract_sdk_contains_no_fdai_implementation_import() -> None:
    source = REPO_ROOT / "service-contracts" / "src" / "fdai_service_contracts"
    text = "\n".join(path.read_text(encoding="utf-8") for path in source.glob("*.py"))
    assert "from fdai." not in text
    assert "import fdai." not in text
