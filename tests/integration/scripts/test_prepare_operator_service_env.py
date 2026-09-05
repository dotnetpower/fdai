"""Local independent Operator environment preparation regression tests."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts/deployment/local/prepare-operator-service-env.sh"
_BASH = shutil.which("bash") or "bash"
_TRANSPORT_ENV_KEYS = (
    "FDAI_KAFKA_BOOTSTRAP_SERVERS",
    "FDAI_SEMANTIC_TURN_REQUEST_TOPIC",
    "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC",
    "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC",
    "FDAI_SEMANTIC_TURN_OUTBOX_NAMESPACE",
    "FDAI_READ_INVESTIGATION_REQUEST_TOPIC",
    "FDAI_HIL_DECISION_TOPIC",
)


def _isolated_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for key in _TRANSPORT_ENV_KEYS:
        environment.pop(key, None)
    return environment


def _repo(tmp_path: Path, *, semantic: str) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts/deployment/local").mkdir(parents=True)
    shutil.copy2(_SCRIPT, repo / "scripts/deployment/local/prepare-operator-service-env.sh")
    (repo / ".fdai").mkdir()
    semantic_values = {
        "complete": (
            "FDAI_KAFKA_BOOTSTRAP_SERVERS=example.servicebus.windows.net:9093\n"
            "FDAI_SEMANTIC_TURN_REQUEST_TOPIC=operator.semantic-turn.requests\n"
            "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC=core.semantic-turn.projections\n"
            "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC=fdai.pantheon.objects\n"
            "FDAI_READ_INVESTIGATION_REQUEST_TOPIC=operator.read-investigation.requests\n"
            "FDAI_HIL_DECISION_TOPIC=fdai.hil.decisions\n"
        ),
        "partial": "FDAI_SEMANTIC_TURN_REQUEST_TOPIC=operator.semantic-turn.requests\n",
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
        env=_isolated_environment(),
        check=True,
        capture_output=True,
        text=True,
    )

    rendered = (repo / ".fdai/local-operator-service.env").read_text(encoding="utf-8")
    assert "prepared local independent Operator Service environment" in completed.stdout
    assert (
        "FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS=http://localhost:5273,http://127.0.0.1:5273"
    ) in rendered
    if semantic == "complete":
        expected_namespace = "local-" + hashlib.sha256(str(repo).encode()).hexdigest()[:16]
        assert "FDAI_KAFKA_BOOTSTRAP_SERVERS=example.servicebus.windows.net:9093" in rendered
        assert "FDAI_SEMANTIC_TURN_REQUEST_TOPIC=operator.semantic-turn.requests" in rendered
        assert "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC=core.semantic-turn.projections" in rendered
        assert "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC=fdai.pantheon.objects" in rendered
        assert f"FDAI_SEMANTIC_TURN_OUTBOX_NAMESPACE={expected_namespace}" in rendered
        assert (
            "FDAI_READ_INVESTIGATION_REQUEST_TOPIC=operator.read-investigation.requests" in rendered
        )
        assert "FDAI_HIL_DECISION_TOPIC=fdai.hil.decisions" in rendered
        assert "FDAI_OPERATOR_SERVICE_LOCAL_AZURE_NARRATOR=" not in rendered
    else:
        assert "FDAI_SEMANTIC_TURN_REQUEST_TOPIC=" not in rendered
        assert "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC=" not in rendered
        assert "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC=" not in rendered
        assert "FDAI_SEMANTIC_TURN_OUTBOX_NAMESPACE=" not in rendered
        assert "FDAI_READ_INVESTIGATION_REQUEST_TOPIC=" not in rendered
        assert "FDAI_HIL_DECISION_TOPIC=" not in rendered
        assert "FDAI_OPERATOR_SERVICE_LOCAL_AZURE_NARRATOR=1" in rendered


def test_rejects_partial_semantic_transport(tmp_path: Path) -> None:
    repo = _repo(tmp_path, semantic="partial")

    completed = subprocess.run(  # noqa: S603 - test-controlled script and environment
        [_BASH, str(repo / "scripts/deployment/local/prepare-operator-service-env.sh")],
        cwd=repo,
        env=_isolated_environment(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "MUST already be configured together" in completed.stderr
    assert not (repo / ".fdai/local-operator-service.env").exists()
