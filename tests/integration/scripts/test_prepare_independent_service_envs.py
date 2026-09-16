"""Local independent service environment preparation regression tests."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts/deployment/local/prepare-independent-service-envs.sh"
_BASH = shutil.which("bash") or "bash"


def test_scopes_only_executor_state_store_to_its_service_role(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    script = repo / "scripts/deployment/local/prepare-independent-service-envs.sh"
    script.parent.mkdir(parents=True)
    shutil.copy2(_SCRIPT, script)
    state_dir = repo / ".fdai"
    state_dir.mkdir()
    state_dir.joinpath("local-runtime.env").write_text(
        "FDAI_EXECUTION_VENUE=local\n"
        "FDAI_STATE_STORE_DSN=postgresql://example.invalid/fdai"
        "?options=-c%20role%3Dfdai_core\n"
        "FDAI_KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:19092\n"
        "FDAI_DATABASE_URL=postgresql+psycopg://example.invalid/fdai\n",
        encoding="utf-8",
    )
    state_dir.joinpath("local-operator-service.env").write_text(
        "FDAI_EXECUTION_VENUE=local\n"
        "FDAI_DATABASE_URL=postgresql+psycopg://example.invalid/fdai"
        "?options=-c%20role%3Dfdai_operator\n",
        encoding="utf-8",
    )

    subprocess.run(  # noqa: S603 - test-controlled script and environment
        [_BASH, str(script)],
        cwd=repo,
        env=dict(os.environ),
        check=True,
        capture_output=True,
        text=True,
    )

    api = state_dir.joinpath("local-document-ingestion-api.env").read_text(encoding="utf-8")
    worker = state_dir.joinpath("local-document-processing-worker.env").read_text(encoding="utf-8")
    executor = state_dir.joinpath("local-isolated-executor.env").read_text(encoding="utf-8")

    assert "FDAI_STATE_STORE_DSN=" not in api
    assert "FDAI_STATE_STORE_DSN=" not in worker
    assert (
        "FDAI_STATE_STORE_DSN=postgresql://example.invalid/fdai?options=-c%20role%3Dfdai_executor\n"
    ) in executor
    assert "role%3Dfdai_core" not in executor
