"""Local channel-edge environment preparation contract tests."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts/deployment/local/prepare-channel-edge-env.sh"
_BASH = shutil.which("bash") or "bash"


def _repo(tmp_path: Path, *, provider_mode: int = 0o600) -> Path:
    repo = tmp_path / "repo"
    script = repo / "scripts/deployment/local/prepare-channel-edge-env.sh"
    script.parent.mkdir(parents=True)
    shutil.copy2(_SCRIPT, script)
    fdai = repo / ".fdai"
    fdai.mkdir()
    (fdai / "local-runtime.env").write_text(
        "\n".join(
            (
                "FDAI_DATABASE_URL=postgresql://local.example.invalid/fdai",
                "FDAI_KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:19092",
                "FDAI_SEMANTIC_TURN_REQUEST_TOPIC=operator.semantic-turn.requests",
                "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC=core.semantic-turn.projections",
                "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC=aw.pantheon.objects",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    provider = fdai / "local-channel-edge-input.env"
    provider.write_text(
        "\n".join(
            (
                "FDAI_CHANNEL_EDGE_ENABLED_CHANNELS=slack",
                'FDAI_CHANNEL_EDGE_PRINCIPAL_SCOPES_JSON=\'{"principal-example":{"scope_ref":"scope://example","roles":["Reader"]}}\'',
                "FDAI_SLACK_SIGNING_SECRET='signing secret with spaces'",
                "FDAI_SLACK_BOT_TOKEN='test token with spaces'",
                "FDAI_SLACK_TEAM_ID=team-example",
                'FDAI_SLACK_PRINCIPAL_MAP_JSON=\'{"sender-example":"principal-example"}\'',
            )
        )
        + "\n",
        encoding="utf-8",
    )
    provider.chmod(provider_mode)
    return repo


def test_prepare_channel_edge_env_preserves_private_values_and_role(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    result = subprocess.run(  # noqa: S603 - resolved Bash runs a task-owned fixture script.
        [_BASH, str(repo / "scripts/deployment/local/prepare-channel-edge-env.sh")],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    output = repo / ".fdai/local-channel-edge.env"
    assert output.stat().st_mode & 0o077 == 0
    shell = subprocess.run(  # noqa: S603 - resolved Bash reads the generated private fixture.
        [
            _BASH,
            "-c",
            "set -a; source .fdai/local-channel-edge.env; "
            "printf '%s\\n' \"$FDAI_DATABASE_ROLE|$FDAI_SLACK_SIGNING_SECRET\"",
        ],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
        env={**os.environ, "PATH": os.environ.get("PATH", "")},
    )
    assert shell.stdout.strip() == "fdai_operator|signing secret with spaces"
    assert "role%3Dfdai_operator" in output.read_text(encoding="utf-8")


def test_prepare_channel_edge_env_rejects_open_provider_file(tmp_path: Path) -> None:
    repo = _repo(tmp_path, provider_mode=0o644)

    result = subprocess.run(  # noqa: S603 - resolved Bash runs a task-owned fixture script.
        [_BASH, str(repo / "scripts/deployment/local/prepare-channel-edge-env.sh")],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "MUST NOT be readable" in result.stderr
    assert not (repo / ".fdai/local-channel-edge.env").exists()
