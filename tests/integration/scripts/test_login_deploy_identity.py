from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_LOGIN = _ROOT / "scripts" / "deployment" / "azure" / "login-deploy-identity.sh"
_CONFIG = (_ROOT / "scripts" / "deployment" / "azure" / "set-gh-actions-config.sh").read_text(
    encoding="utf-8"
)
_SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
_TENANT = "00000000-0000-0000-0000-000000000002"
_CLIENT_ID = "00000000-0000-0000-0000-000000000003"
_PRINCIPAL_ID = "00000000-0000-0000-0000-000000000004"
_WORKFLOWS = (
    "deploy-dev.yml",
    "destroy-env.yml",
    "infra-drift.yml",
    "model-lifecycle-reconcile.yml",
    "model-settings-projection.yml",
    "operational-history-certification.yml",
    "service-deploy.yml",
    "sre-demo-lab.yml",
)


def _token(principal_id: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"oid": principal_id}).encode()).decode()
    return f"header.{payload.rstrip('=')}.signature"


def _fake_az(tmp_path: Path) -> Path:
    calls = tmp_path / "az-calls"
    binary = tmp_path / "az"
    binary.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$FAKE_AZ_CALLS"
case "$1 $2" in
  "account clear") exit 0 ;;
  "login --identity") exit 0 ;;
  "account show")
    if [[ " $* " == *" --subscription "* ]]; then
      printf '%s\n%s\n' "$FAKE_AZ_SUBSCRIPTION" "$FAKE_AZ_TENANT"
    else
      printf '%s\n' "$FAKE_AZ_TENANT"
    fi
    ;;
  "account set") exit 0 ;;
  "account get-access-token") printf '%s\n' "$FAKE_AZ_TOKEN" ;;
  *) exit 9 ;;
esac
""",
        encoding="ascii",
    )
    binary.chmod(0o755)
    return calls


def _run(
    tmp_path: Path,
    *,
    principal_id: str = _PRINCIPAL_ID,
) -> tuple[subprocess.CompletedProcess[str], str]:
    calls = _fake_az(tmp_path)
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    github_env = tmp_path / "github-env"
    result = subprocess.run(  # noqa: S603 - controlled repository script
        [str(_LOGIN), _SUBSCRIPTION, _TENANT, _CLIENT_ID, _PRINCIPAL_ID],
        cwd=_ROOT,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_ENV": str(github_env),
            "FAKE_AZ_CALLS": str(calls),
            "FAKE_AZ_SUBSCRIPTION": _SUBSCRIPTION,
            "FAKE_AZ_TENANT": _TENANT,
            "FAKE_AZ_TOKEN": _token(principal_id),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return result, calls.read_text(encoding="ascii") if calls.exists() else ""


def test_login_selects_client_id_and_verifies_token_oid(tmp_path: Path) -> None:
    result, calls = _run(tmp_path)

    assert result.returncode == 0
    assert f"login --identity --client-id {_CLIENT_ID}" in calls
    assert f"account show --subscription {_SUBSCRIPTION}" in calls
    assert "account get-access-token --resource-type arm" in calls
    assert "exact deploy identity and Azure context verified" in result.stdout


def test_login_rejects_mismatched_token_oid(tmp_path: Path) -> None:
    result, calls = _run(
        tmp_path,
        principal_id="00000000-0000-0000-0000-000000000005",
    )

    assert result.returncode == 1
    assert "token oid does not match" in result.stderr
    assert "account get-access-token --resource-type arm" in calls


def test_login_rejects_missing_identity_before_azure_access(tmp_path: Path) -> None:
    calls = _fake_az(tmp_path)
    result = subprocess.run(  # noqa: S603 - controlled repository script
        [str(_LOGIN), _SUBSCRIPTION, _TENANT, "", _PRINCIPAL_ID],
        cwd=_ROOT,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path / "runner-temp"),
            "FAKE_AZ_CALLS": str(calls),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "must be configured GUIDs" in result.stderr
    assert not calls.exists()


def test_all_deploy_workflows_bind_and_verify_the_stable_identity() -> None:
    for workflow_name in _WORKFLOWS:
        workflow = (_ROOT / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
        assert "DEPLOY_RUNNER_CLIENT_ID: ${{ vars.DEPLOY_RUNNER_CLIENT_ID }}" in workflow
        assert "DEPLOY_RUNNER_PRINCIPAL_ID: ${{ vars.DEPLOY_RUNNER_PRINCIPAL_ID }}" in workflow
        assert "login-deploy-identity.sh" in workflow
        assert '"$DEPLOY_RUNNER_CLIENT_ID" "$DEPLOY_RUNNER_PRINCIPAL_ID"' in workflow
        assert "az login --identity" not in workflow


def test_onboarding_publishes_both_stable_identity_coordinates() -> None:
    assert "gh variable set DEPLOY_RUNNER_CLIENT_ID" in _CONFIG
    assert "$(out deploy_runner_client_id)" in _CONFIG
    assert "gh variable set DEPLOY_RUNNER_PRINCIPAL_ID" in _CONFIG
    assert "$(out deploy_runner_principal_id)" in _CONFIG
