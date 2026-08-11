"""Local independent Operator environment preparation regression tests."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts/deployment/local/prepare-operator-service-env.sh"
_BASH = shutil.which("bash") or "bash"


def _repo(tmp_path: Path, *, semantic: str) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts/deployment/local").mkdir(parents=True)
    shutil.copy2(_SCRIPT, repo / "scripts/deployment/local/prepare-operator-service-env.sh")
    (repo / ".fdai").mkdir()
    semantic_values = {
        "complete": (
            "FDAI_KAFKA_BOOTSTRAP_SERVERS=example.servicebus.windows.net:9093\n"
            "FDAI_SEMANTIC_TURN_REQUEST_TOPIC=operator-core-request\n"
            "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC=core-operator-projection\n"
        ),
        "partial": "FDAI_SEMANTIC_TURN_REQUEST_TOPIC=operator-core-request\n",
        "absent": "",
    }[semantic]
    (repo / ".fdai/local-runtime.env").write_text(
        "AZURE_TENANT_ID=tenant\n"
        "FDAI_DATABASE_URL=postgresql://example.invalid/fdai\n"
        "RUNTIME_ENV=dev\n"
        f"{semantic_values}",
        encoding="utf-8",
    )
    (repo / "console").mkdir()
    (repo / "console/.env.local").write_text(
        "VITE_MSAL_TENANT_ID=tenant\nVITE_MSAL_API_SCOPE=api://audience/access\n",
        encoding="utf-8",
    )
    return repo


@pytest.mark.parametrize("semantic", ["complete", "absent"])
def test_prepares_semantic_transport_or_local_narrator(tmp_path: Path, semantic: str) -> None:
    repo = _repo(tmp_path, semantic=semantic)

    completed = subprocess.run(  # noqa: S603 - test-controlled script and environment
        [_BASH, str(repo / "scripts/deployment/local/prepare-operator-service-env.sh")],
        cwd=repo,
        env={**os.environ},
        check=True,
        capture_output=True,
        text=True,
    )

    rendered = (repo / ".fdai/local-operator-service.env").read_text(encoding="utf-8")
    assert "prepared local independent Operator Service environment" in completed.stdout
    if semantic == "complete":
        assert "FDAI_KAFKA_BOOTSTRAP_SERVERS=example.servicebus.windows.net:9093" in rendered
        assert "FDAI_SEMANTIC_TURN_REQUEST_TOPIC=operator-core-request" in rendered
        assert "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC=core-operator-projection" in rendered
        assert "FDAI_OPERATOR_SERVICE_LOCAL_AZURE_NARRATOR=" not in rendered
    else:
        assert "FDAI_SEMANTIC_TURN_REQUEST_TOPIC=" not in rendered
        assert "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC=" not in rendered
        assert "FDAI_OPERATOR_SERVICE_LOCAL_AZURE_NARRATOR=1" in rendered


def test_rejects_partial_semantic_transport(tmp_path: Path) -> None:
    repo = _repo(tmp_path, semantic="partial")

    completed = subprocess.run(  # noqa: S603 - test-controlled script and environment
        [_BASH, str(repo / "scripts/deployment/local/prepare-operator-service-env.sh")],
        cwd=repo,
        env={**os.environ},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "MUST already be configured together" in completed.stderr
    assert not (repo / ".fdai/local-operator-service.env").exists()
