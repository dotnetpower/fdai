from __future__ import annotations

import os
import pty
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_VERIFY = _ROOT / "scripts" / "deployment" / "azure" / "verify-azure-context.sh"
_AZD_UP = _ROOT / "scripts" / "deployment" / "azure" / "azd-up.sh"
_CONTRIBUTOR_TARGET = _ROOT / "scripts" / "deployment" / "azure" / "contributor-target.sh"
_BASH = shutil.which("bash")
_SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
assert _BASH is not None


def _fake_az(tmp_path: Path) -> tuple[Path, Path]:
    calls = tmp_path / "calls"
    binary = tmp_path / "az"
    binary.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$FAKE_AZ_CALLS"
if [[ "$1 $2" == "account show" ]]; then
    if [[ " $* " == *" --subscription "* ]]; then
        if [[ "${FAKE_AZ_SHOW_FAIL:-0}" == "1" ]]; then
            exit 1
        fi
        # Real `az ... --query '[id,tenantId]' --output tsv` prints one element per
        # line. A tab-joined fake hides a parser that only ever reads the first line.
        printf '%s\n%s\n' "$FAKE_AZ_SUBSCRIPTION" "$FAKE_AZ_TENANT"
    elif [[ "$*" == *"--query [id,tenantId]"* ]]; then
        if [[ "${FAKE_AZ_ACTIVE_SHOW_FAIL:-0}" == "1" ]]; then
            exit 1
        fi
        printf '%s\n%s\n' "$FAKE_AZ_SUBSCRIPTION" "$FAKE_AZ_TENANT"
    else
        printf '%s\n' "${FAKE_AZ_ACTIVE_TENANT:-$FAKE_AZ_TENANT}"
    fi
elif [[ "$1 $2" == "account list-locations" ]]; then
    if [[ "$*" == *"'$FAKE_AZ_AVAILABLE_REGION'"* ]]; then
        printf '%s\n' "$FAKE_AZ_AVAILABLE_REGION"
    fi
elif [[ "$1 $2" == "account set" ]]; then
  exit 0
elif [[ "$1 $2" == "cloud show" ]]; then
    printf '%s\n' AzureCloud
elif [[ "$1 $2" == "provider show" ]]; then
    printf '%s\n' "${FAKE_AZ_PROVIDER_STATE:-Registered}"
elif [[ "$1 $2 $3" == "ad signed-in-user show" ]]; then
    printf '%s\n' 00000000-0000-0000-0000-000000000003
else
  exit 9
fi
""",
        encoding="ascii",
    )
    binary.chmod(0o755)
    return binary, calls


def _run(
    tmp_path: Path,
    *,
    actual_subscription: str = "sub-expected",
    actual_tenant: str = "tenant-expected",
    active_tenant: str | None = None,
    show_fails: bool = False,
) -> tuple[subprocess.CompletedProcess[str], str]:
    _binary, calls = _fake_az(tmp_path)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "FAKE_AZ_CALLS": str(calls),
        "FAKE_AZ_SUBSCRIPTION": actual_subscription,
        "FAKE_AZ_TENANT": actual_tenant,
        "FAKE_AZ_ACTIVE_TENANT": active_tenant or actual_tenant,
        "FAKE_AZ_SHOW_FAIL": "1" if show_fails else "0",
        "FAKE_AZ_ACTIVE_SHOW_FAIL": "0",
        "FAKE_AZ_AVAILABLE_REGION": "koreacentral",
    }
    result = subprocess.run(  # noqa: S603 - controlled repository script
        [str(_VERIFY), "sub-expected", "tenant-expected"],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, calls.read_text(encoding="ascii") if calls.exists() else ""


def test_exact_context_is_verified_without_mutating_active_selection(tmp_path: Path) -> None:
    result, calls = _run(tmp_path)

    assert result.returncode == 0
    assert "exact subscription and tenant verified" in result.stdout
    assert "account show --query tenantId" in calls
    assert "account show --subscription sub-expected" in calls
    assert "account set --subscription sub-expected" not in calls


def test_active_tenant_mismatch_blocks_cross_profile_subscription_lookup(
    tmp_path: Path,
) -> None:
    result, calls = _run(tmp_path, active_tenant="tenant-other")

    assert result.returncode == 1
    assert "active tenant does not match" in result.stderr
    assert "account show --subscription" not in calls
    assert "account set" not in calls


@pytest.mark.parametrize(
    ("subscription", "tenant", "message"),
    [
        ("sub-other", "tenant-expected", "subscription does not match"),
        ("sub-expected", "tenant-other", "tenant does not match"),
    ],
)
def test_mismatch_fails_before_account_set(
    tmp_path: Path,
    subscription: str,
    tenant: str,
    message: str,
) -> None:
    result, calls = _run(
        tmp_path,
        actual_subscription=subscription,
        actual_tenant=tenant,
    )

    assert result.returncode == 1
    assert message in result.stderr
    assert "account set" not in calls


def test_unavailable_expected_subscription_fails_closed(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, show_fails=True)

    assert result.returncode == 1
    assert "expected subscription is unavailable" in result.stderr
    assert "account set" not in calls


def _run_contributor_target(
    tmp_path: Path,
    *,
    answer: str,
    available_region: str = "koreacentral",
    active_show_fails: bool = False,
    has_terminal: bool = True,
) -> tuple[subprocess.CompletedProcess[str], str]:
    _binary, calls = _fake_az(tmp_path)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "FAKE_AZ_CALLS": str(calls),
        "FAKE_AZ_SUBSCRIPTION": "sub-active",
        "FAKE_AZ_TENANT": "tenant-active",
        "FAKE_AZ_AVAILABLE_REGION": available_region,
        "FAKE_AZ_ACTIVE_SHOW_FAIL": "1" if active_show_fails else "0",
    }
    for name in (
        "AZURE_LOCATION",
        "AZURE_SUBSCRIPTION_ID",
        "AZURE_TENANT_ID",
        "FDAI_AZD_CONFIRM",
        "FDAI_AZURE_REGION",
    ):
        env.pop(name, None)
    command = """
source "$1"
resolve_contributor_target "$2" || exit 1
printf '%s|%s|%s|%s|%s|%s\n' \
  "$TARGET_STATUS" "$EXPECTED_SUBSCRIPTION" "$EXPECTED_TENANT" \
  "$REGION" "$CONFIRM" "$TARGET_HAS_TERMINAL"
"""
    result = subprocess.run(  # noqa: S603 - controlled repository shell helper
        [
            _BASH,
            "-c",
            command,
            "bash",
            str(_CONTRIBUTOR_TARGET),
            "1" if has_terminal else "0",
        ],
        cwd=_ROOT,
        env=env,
        input=answer,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, calls.read_text(encoding="ascii") if calls.exists() else ""


def test_contributor_target_reads_active_login_and_accepts_default_region(
    tmp_path: Path,
) -> None:
    result, calls = _run_contributor_target(tmp_path, answer="y\n")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "run|sub-active|tenant-active|koreacentral|1|1\n"
    assert "Azure subscription: sub-active" in result.stderr
    assert "account show --query [id,tenantId]" in calls
    assert "account list-locations --query" in calls
    assert "account list-locations --subscription" not in calls


def test_contributor_target_accepts_an_available_alternate_region(tmp_path: Path) -> None:
    result, calls = _run_contributor_target(
        tmp_path,
        answer="westeurope\n",
        available_region="westeurope",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "run|sub-active|tenant-active|westeurope|1|1\n"
    assert "'westeurope'" in calls


def test_contributor_target_reprompts_after_an_unknown_region(tmp_path: Path) -> None:
    result, _calls = _run_contributor_target(
        tmp_path,
        answer="notreal\nwesteurope\n",
        available_region="westeurope",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "run|sub-active|tenant-active|westeurope|1|1\n"
    assert "region 'notreal' is not available" in result.stderr


def test_contributor_target_does_not_treat_empty_input_as_approval(tmp_path: Path) -> None:
    result, calls = _run_contributor_target(tmp_path, answer="\n")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "cancel|sub-active|tenant-active|koreacentral|0|1\n"
    assert "account list-locations" not in calls


def test_azd_wrapper_detects_a_terminal_and_cancels_before_mutation(tmp_path: Path) -> None:
    _binary, calls = _fake_az(tmp_path)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "FAKE_AZ_CALLS": str(calls),
        "FAKE_AZ_SUBSCRIPTION": "sub-active",
        "FAKE_AZ_TENANT": "tenant-active",
        "FAKE_AZ_AVAILABLE_REGION": "koreacentral",
        "FAKE_AZ_ACTIVE_SHOW_FAIL": "0",
    }
    for name in (
        "AZURE_LOCATION",
        "AZURE_SUBSCRIPTION_ID",
        "AZURE_TENANT_ID",
        "FDAI_AZD_CONFIRM",
        "FDAI_AZURE_REGION",
    ):
        env.pop(name, None)
    master, slave = pty.openpty()
    process = subprocess.Popen(  # noqa: S603 - controlled repository script
        [str(_AZD_UP)],
        cwd=_ROOT,
        env=env,
        stdin=slave,
        stdout=subprocess.DEVNULL,
        stderr=slave,
        text=False,
    )
    os.close(slave)
    try:
        os.write(master, b"n\n")
        returncode = process.wait(timeout=5)
    finally:
        os.close(master)

    assert returncode == 0
    azure_calls = calls.read_text(encoding="ascii")
    assert "account show --query [id,tenantId]" in azure_calls
    assert "account list-locations" not in azure_calls
    assert "provider register" not in azure_calls


def test_contributor_target_requires_az_login(tmp_path: Path) -> None:
    result, _calls = _run_contributor_target(
        tmp_path,
        answer="y\n",
        active_show_fails=True,
    )

    assert result.returncode == 1
    assert "run 'az login' and retry" in result.stderr


def test_noninteractive_contributor_target_requires_both_explicit_axes(
    tmp_path: Path,
) -> None:
    result, calls = _run_contributor_target(
        tmp_path,
        answer="",
        has_terminal=False,
    )

    assert result.returncode == 1
    assert "non-interactive use requires AZURE_SUBSCRIPTION_ID" in result.stderr
    assert calls == ""


def test_private_bootstrap_callers_verify_before_mutation() -> None:
    callers = {
        "infra/bootstrap/onboard.sh": "create-state-account.sh",
        "infra/bootstrap/create-state-account.sh": "az group show",
        "infra/bootstrap/preflight-policy-check.sh": "az group create",
        "infra/bootstrap/register-runner.sh": "gh api -X POST",
        "scripts/deployment/azure/set-gh-actions-config.sh": "gh variable set",
    }
    for relative, first_mutation in callers.items():
        content = (_ROOT / relative).read_text(encoding="utf-8")
        assert content.index("verify-azure-context.sh") < content.index(first_mutation)

    context_callers = (
        "infra/bootstrap/check-runner-storage-posture.sh",
        "infra/bootstrap/create-state-account.sh",
        "infra/bootstrap/onboard.sh",
        "infra/bootstrap/preflight-policy-check.sh",
        "infra/bootstrap/register-runner.sh",
        "scripts/deployment/azure/azd-up.sh",
        "scripts/deployment/azure/set-gh-actions-config.sh",
    )
    for relative in context_callers:
        content = (_ROOT / relative).read_text(encoding="utf-8")
        verifier_call = next(
            line
            for line in content.splitlines()
            if "verify-azure-context.sh" in line and not line.lstrip().startswith("#")
        )
        assert verifier_call.lstrip().startswith('/bin/bash "$HERE/')

    onboard = (_ROOT / "infra/bootstrap/onboard.sh").read_text(encoding="utf-8")
    assert onboard.count("/bin/bash ./create-state-account.sh") == 2

    workflow = (_ROOT / ".github" / "workflows" / "deploy-dev.yml").read_text(encoding="utf-8")
    assert workflow.index("Verify exact Azure context") < workflow.index(
        "Verify protected storage containers"
    )


def _fake_azd(tmp_path: Path) -> Path:
    calls = tmp_path / "azd-calls"
    binary = tmp_path / "azd"
    binary.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$FAKE_AZD_CALLS"
case "$1 $2" in
    "env select") exit 0 ;;
    "env get-value") printf '%s\n' "$FAKE_AZD_SUBSCRIPTION" ;;
    "env set") exit 0 ;;
    "auth login") exit 0 ;;
    "provision --environment") exit 0 ;;
    *) exit 9 ;;
esac
""",
        encoding="ascii",
    )
    binary.chmod(0o755)
    return calls


def test_contributor_flow_starts_azd_sign_in_when_its_local_session_is_missing(
    tmp_path: Path,
) -> None:
    calls = tmp_path / "azd-auth-calls"
    marker = tmp_path / "azd-authenticated"
    binary = tmp_path / "azd"
    binary.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$FAKE_AZD_CALLS"
if [[ "$*" == "auth login --check-status" ]]; then
    [[ -f "$FAKE_AZD_AUTH_MARKER" ]]
elif [[ "$1 $2" == "auth login" ]]; then
    touch "$FAKE_AZD_AUTH_MARKER"
else
    exit 9
fi
""",
        encoding="ascii",
    )
    binary.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "FAKE_AZD_CALLS": str(calls),
        "FAKE_AZD_AUTH_MARKER": str(marker),
    }
    command = """
source "$1"
ensure_contributor_azd_login 1 tenant-active
"""

    result = subprocess.run(  # noqa: S603 - controlled repository shell helper
        [_BASH, "-c", command, "bash", str(_CONTRIBUTOR_TARGET)],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text(encoding="ascii").splitlines() == [
        "auth login --check-status",
        "auth login --tenant-id tenant-active",
        "auth login --check-status",
    ]
    assert "starting its sign-in now" in result.stderr


def _fake_uv(tmp_path: Path) -> None:
    binary = tmp_path / "uv"
    binary.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
output=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --out|--output)
            output="$2"
            shift 2
            ;;
        *) shift ;;
    esac
done
if [[ -n "$output" ]]; then
    payload='{"schema_version":"1.0.0","capabilities":[]'
    payload+=',"mixed_model_mode":"hil-only"}'
    printf '%s\n' "$payload" > "$output"
fi
""",
        encoding="ascii",
    )
    binary.chmod(0o755)


def _fake_terraform(tmp_path: Path) -> None:
    binary = tmp_path / "terraform"
    binary.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="ascii")
    binary.chmod(0o755)


def test_azd_wrapper_rejects_mismatched_selected_environment(tmp_path: Path) -> None:
    _binary, az_calls = _fake_az(tmp_path)
    azd_calls = _fake_azd(tmp_path)
    _fake_uv(tmp_path)
    _fake_terraform(tmp_path)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "FAKE_AZ_CALLS": str(az_calls),
        "FAKE_AZ_SUBSCRIPTION": "sub-expected",
        "FAKE_AZ_TENANT": "tenant-expected",
        "FAKE_AZD_CALLS": str(azd_calls),
        "FAKE_AZD_SUBSCRIPTION": "sub-other",
        "AZURE_SUBSCRIPTION_ID": "sub-expected",
        "AZURE_TENANT_ID": "tenant-expected",
        "FDAI_AZD_WORK_DIR": str(tmp_path / "work"),
    }

    result = subprocess.run(  # noqa: S603 - controlled repository script
        [str(_AZD_UP)],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "does not match AZURE_SUBSCRIPTION_ID" in result.stderr
    assert "provision --preview" not in azd_calls.read_text(encoding="ascii")


def test_azd_wrapper_previews_after_exact_context_verification(tmp_path: Path) -> None:
    _binary, az_calls = _fake_az(tmp_path)
    azd_calls = _fake_azd(tmp_path)
    _fake_uv(tmp_path)
    _fake_terraform(tmp_path)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "FAKE_AZ_CALLS": str(az_calls),
        "FAKE_AZ_SUBSCRIPTION": _SUBSCRIPTION,
        "FAKE_AZ_TENANT": "tenant-expected",
        "FAKE_AZD_CALLS": str(azd_calls),
        "FAKE_AZD_SUBSCRIPTION": _SUBSCRIPTION,
        "AZURE_SUBSCRIPTION_ID": _SUBSCRIPTION,
        "AZURE_TENANT_ID": "tenant-expected",
        "FDAI_AZD_WORK_DIR": str(tmp_path / "work"),
    }

    result = subprocess.run(  # noqa: S603 - controlled repository script
        [str(_AZD_UP)],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    azure_calls = az_calls.read_text(encoding="ascii")
    deployment_calls = azd_calls.read_text(encoding="ascii")
    assert f"account show --subscription {_SUBSCRIPTION}" in azure_calls
    assert "account set --subscription" not in azure_calls
    assert "provider register" not in azure_calls
    assert "role assignment create" not in azure_calls
    assert "acr build" not in azure_calls
    assert "postgres flexible-server firewall-rule create" not in azure_calls
    assert "provision --environment fdai-dev" in deployment_calls
    assert "--preview" in deployment_calls


def test_azd_wrapper_reports_provider_registration_without_mutating(
    tmp_path: Path,
) -> None:
    _binary, az_calls = _fake_az(tmp_path)
    azd_calls = _fake_azd(tmp_path)
    _fake_uv(tmp_path)
    _fake_terraform(tmp_path)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "FAKE_AZ_CALLS": str(az_calls),
        "FAKE_AZ_SUBSCRIPTION": _SUBSCRIPTION,
        "FAKE_AZ_TENANT": "tenant-expected",
        "FAKE_AZ_PROVIDER_STATE": "NotRegistered",
        "FAKE_AZD_CALLS": str(azd_calls),
        "FAKE_AZD_SUBSCRIPTION": _SUBSCRIPTION,
        "AZURE_SUBSCRIPTION_ID": _SUBSCRIPTION,
        "AZURE_TENANT_ID": "tenant-expected",
        "FDAI_AZD_WORK_DIR": str(tmp_path / "work"),
    }

    result = subprocess.run(  # noqa: S603 - controlled repository script
        [str(_AZD_UP)],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "require registration" in result.stderr
    assert "provider register" not in az_calls.read_text(encoding="ascii")
    assert "provision" not in azd_calls.read_text(encoding="ascii")
