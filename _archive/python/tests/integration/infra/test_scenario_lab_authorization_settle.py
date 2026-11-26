"""Run-grant settle wait and one-time pure-authorization apply retry for the scenario lab."""

from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "sre-demo-lab.yml"
DIAGNOSTICS = REPO_ROOT / "scripts" / "deployment" / "scenario-lab" / "terraform_diagnostics.py"
MODULE = runpy.run_path(str(DIAGNOSTICS))
BASH = shutil.which("bash")
GRANTED_AT = 1_790_000_000


def _step_script(name: str) -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    start = workflow.index(f"      - name: {name}\n")
    end = workflow.find("\n      - name: ", start + 1)
    step = workflow[start : end if end != -1 else len(workflow)]
    return "\n".join(
        line.removeprefix("          ") for line in step.split("run: |\n", 1)[1].splitlines()
    )


def _tool(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body, encoding="utf-8")
    path.chmod(0o755)


# --- grant settle wait -------------------------------------------------------------------------


def _run_settle(
    tmp_path: Path,
    *,
    remove_after_run: str,
    granted_at: str,
    clock: list[int],
    effective: list[bool],
) -> tuple[subprocess.CompletedProcess[str], int, int]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "clock").write_text("\n".join(str(value) for value in clock) + "\n", "utf-8")
    (tmp_path / "effective").write_text(
        "\n".join("yes" if value else "no" for value in effective) + "\n", "utf-8"
    )
    _tool(
        bin_dir,
        "az",
        'printf "az\\n" >>"$FAKE_CALLS"\n'
        'answer="$(head -n 1 "$FAKE_EFFECTIVE")"\n'
        'tail -n +2 "$FAKE_EFFECTIVE" >"$FAKE_EFFECTIVE.next"\n'
        'mv "$FAKE_EFFECTIVE.next" "$FAKE_EFFECTIVE"\n'
        '[[ "$answer" == "yes" ]] || exit 1\n'
        'printf \'{"value":[{"actions":["*"]}]}\\n\'\n',
    )
    _tool(
        bin_dir,
        "date",
        'now="$(head -n 1 "$FAKE_CLOCK")"\n'
        'tail -n +2 "$FAKE_CLOCK" >"$FAKE_CLOCK.next"\n'
        'mv "$FAKE_CLOCK.next" "$FAKE_CLOCK"\n'
        'printf "%s\\n" "$now"\n',
    )
    _tool(bin_dir, "sleep", 'printf "sleep %s\\n" "$1" >>"$FAKE_CALLS"\n')
    environment = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "RESOURCE_GROUP_ID": "/subscriptions/example/resourceGroups/example",
        "REMOVE_AFTER_RUN": remove_after_run,
        "GRANTED_AT_EPOCH": granted_at,
        "FAKE_CALLS": str(tmp_path / "calls"),
        "FAKE_CLOCK": str(tmp_path / "clock"),
        "FAKE_EFFECTIVE": str(tmp_path / "effective"),
    }
    (tmp_path / "calls").write_text("", encoding="utf-8")
    result = subprocess.run(  # noqa: S603 - resolved Bash and an extracted repository step.
        [str(BASH), "-c", _step_script("Wait for the run grant to settle")],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=60,
    )
    calls = (tmp_path / "calls").read_text(encoding="utf-8").splitlines()
    return result, calls.count("az"), sum(line == "sleep 30" for line in calls)


def test_a_pre_existing_grant_needs_no_settle_wait(tmp_path: Path) -> None:
    result, checks, sleeps = _run_settle(
        tmp_path, remove_after_run="false", granted_at="", clock=[], effective=[]
    )

    assert result.returncode == 0
    assert "pre-existing scenario-lab grant needs no settle wait" in result.stdout
    assert (checks, sleeps) == (0, 0)


def test_a_new_grant_ages_ten_minutes_while_the_permission_check_repeats(tmp_path: Path) -> None:
    clock = [GRANTED_AT + 40 + 30 * step for step in range(20)]
    result, checks, sleeps = _run_settle(
        tmp_path,
        remove_after_run="true",
        granted_at=str(GRANTED_AT),
        clock=clock,
        effective=[True] * 20,
    )

    assert result.returncode == 0, result.stderr
    assert (checks, sleeps) == (20, 19)
    assert "The scenario-lab grant is 610 seconds old and effective." in result.stdout


def test_an_old_grant_still_needs_a_passing_permission_check(tmp_path: Path) -> None:
    clock = [GRANTED_AT + 700, GRANTED_AT + 730]
    result, checks, sleeps = _run_settle(
        tmp_path,
        remove_after_run="true",
        granted_at=str(GRANTED_AT),
        clock=clock,
        effective=[False, True],
    )

    assert result.returncode == 0, result.stderr
    assert (checks, sleeps) == (2, 1)


def test_a_grant_that_never_settles_fails_within_the_bounded_window(tmp_path: Path) -> None:
    clock = [GRANTED_AT + 40 + 30 * step for step in range(40)]
    result, checks, sleeps = _run_settle(
        tmp_path,
        remove_after_run="true",
        granted_at=str(GRANTED_AT),
        clock=clock,
        effective=[False] * 40,
    )

    assert result.returncode == 1
    assert result.stderr == "scenario-lab grant did not settle within its bounded window.\n"
    assert checks == sleeps + 1
    assert clock[checks - 1] + 30 > GRANTED_AT + 900


def test_a_new_grant_without_a_creation_time_fails_closed(tmp_path: Path) -> None:
    result, checks, sleeps = _run_settle(
        tmp_path, remove_after_run="true", granted_at="", clock=[], effective=[]
    )

    assert result.returncode == 1
    assert result.stderr == "scenario-lab grant creation time is unavailable.\n"
    assert (checks, sleeps) == (0, 0)


def test_the_grant_step_records_when_this_run_created_the_grant() -> None:
    grant = _step_script("Grant bounded scenario-lab deployment authority")
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "printf 'granted_at_epoch=%s\\n' \"$(date -u +%s)\"" in grant
    assert "printf 'granted_at_epoch=\\n'" in grant
    assert grant.index("az role assignment create") < grant.index("granted_at_epoch=%s")
    assert workflow.index("      - name: Wait for the run grant to settle\n") < workflow.index(
        "      - name: Start retained scenario-lab compute and data\n"
    )
    assert "GRANTED_AT_EPOCH: ${{ steps.deployment-authority.outputs.granted_at_epoch }}" in (
        workflow
    )


# --- pure authorization classification ---------------------------------------------------------


def _diagnostic(detail: str, severity: str = "error") -> str:
    return json.dumps(
        {
            "type": "diagnostic",
            "diagnostic": {"severity": severity, "summary": "updating leak", "detail": detail},
        }
    )


AUTHORIZATION = (
    "unexpected status 403 (403 Forbidden) with error: AuthorizationFailed: The client "
    "leak-client does not have authorization to perform action over scope leak-scope"
)


@pytest.mark.parametrize(
    ("lines", "eligible"),
    [
        ([_diagnostic(AUTHORIZATION), _diagnostic(AUTHORIZATION)], True),
        (
            [
                _diagnostic("TooManyRequests Code=Throttled", severity="warning"),
                _diagnostic(AUTHORIZATION),
            ],
            True,
        ),
        ([_diagnostic(AUTHORIZATION), _diagnostic("ERROR CODE: RequestDisallowedByPolicy")], False),
        ([_diagnostic(AUTHORIZATION + "; inner error RequestDisallowedByPolicy")], False),
        ([_diagnostic(AUTHORIZATION + " (unexpected status 409)")], False),
        ([_diagnostic('Status=403 Code="LinkedAuthorizationFailed"')], False),
        ([_diagnostic("unexpected status 403 (403 Forbidden)")], False),
        ([_diagnostic("the provider crashed without a code")], False),
        ([json.dumps({"type": "apply_errored", "hook": {"resource": {"addr": "a.b"}}})], False),
        ([], False),
    ],
)
def test_only_pure_authorization_failures_are_retry_eligible(
    tmp_path: Path, lines: list[str], eligible: bool
) -> None:
    log = tmp_path / "apply.log"
    log.write_text("".join(line + "\n" for line in lines), encoding="utf-8")

    result = subprocess.run(  # noqa: S603 - fixed interpreter and repository script.
        [sys.executable, str(DIAGNOSTICS), "authorization-only", str(log)],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == (0 if eligible else 1)
    assert result.stdout == (
        f"Terraform apply diagnostic authorization-only: {'yes' if eligible else 'no'}\n"
    )
    assert "leak" not in result.stdout + result.stderr


# --- retry plan subset -------------------------------------------------------------------------


def _change(
    address: str, actions: list[str], before: object, after: object, **extra: object
) -> dict:
    change: dict[str, object] = {"actions": actions, "before": before, "after": after}
    change.update(extra)
    return {"address": address, "change": change}


def _tags(expiry: str) -> dict[str, object]:
    return {"tags": {"fdai:expires-at": expiry, "fdai:managed": "true"}, "name": "leak-name"}


OLD = _tags("2026-09-29T15:00:00Z")
NEW = _tags("2026-09-29T18:47:00Z")
REVIEWED = {
    "resource_changes": [
        _change("azurerm_nat_gateway.egress", ["update"], OLD, NEW),
        _change("azurerm_kubernetes_cluster.scenario_lab", ["update"], OLD, NEW),
        _change("azurerm_linux_virtual_machine.stress", ["update"], OLD, NEW),
        _change("azurerm_subnet.aks", ["no-op"], OLD, OLD),
    ]
}


def _subset(tmp_path: Path, retry: dict) -> subprocess.CompletedProcess[str]:
    reviewed_path = tmp_path / "reviewed.json"
    retry_path = tmp_path / "retry.json"
    reviewed_path.write_text(json.dumps(REVIEWED), encoding="utf-8")
    retry_path.write_text(json.dumps(retry), encoding="utf-8")
    return subprocess.run(  # noqa: S603 - fixed interpreter and repository script.
        [sys.executable, str(DIAGNOSTICS), "plan-subset", str(reviewed_path), str(retry_path)],
        capture_output=True,
        check=False,
        text=True,
    )


def test_a_retry_plan_inside_the_reviewed_plan_is_accepted(tmp_path: Path) -> None:
    retry = {
        "resource_changes": [
            _change("azurerm_nat_gateway.egress", ["update"], OLD, NEW),
            _change("azurerm_kubernetes_cluster.scenario_lab", ["no-op"], NEW, NEW),
            _change("azurerm_linux_virtual_machine.stress", ["update"], OLD, NEW),
            _change("azurerm_subnet.aks", ["no-op"], OLD, OLD),
        ]
    }

    result = _subset(tmp_path, retry)

    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        "Scenario lab retry plan: 0 create, 2 update, 0 delete or replace, 0 import.\n"
    )
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (_change("azurerm_public_ip.egress", ["update"], OLD, NEW), "new address"),
        (
            _change("azurerm_nat_gateway.egress", ["delete", "create"], OLD, NEW),
            "action change",
        ),
        (_change("azurerm_subnet.aks", ["delete"], OLD, None), "action change"),
        (
            _change("azurerm_nat_gateway.egress", ["update"], OLD, NEW, importing={"id": "leak"}),
            "new import",
        ),
        (
            _change(
                "azurerm_nat_gateway.egress",
                ["update"],
                OLD,
                {**NEW, "sku_name": "leak-sku"},
            ),
            "new attribute change",
        ),
        (_change("azurerm_nat_gateway.egress /leak", ["update"], OLD, NEW), "new address"),
    ],
)
def test_a_retry_plan_that_leaves_the_reviewed_plan_is_refused(
    tmp_path: Path, change: dict, reason: str
) -> None:
    result = _subset(tmp_path, {"resource_changes": [change]})

    assert result.returncode == 1
    assert f"({reason})" in result.stderr
    assert "leak" not in result.stdout + result.stderr


def test_an_unreadable_plan_comparison_fails_closed(tmp_path: Path) -> None:
    result = _subset(tmp_path, {"resource_changes": [{"address": "azurerm_x.y"}]})

    assert result.returncode == 1
    assert result.stderr == "scenario-lab retry plan comparison is unavailable.\n"


def test_plan_subset_compares_changed_attribute_paths_only() -> None:
    changed = MODULE["_changed_paths"]({"before": OLD, "after": NEW})

    assert changed == frozenset({"tags.fdai:expires-at"})


# --- apply step retry flow ---------------------------------------------------------------------


FAKE_TERRAFORM = """
printf '%s\\n' "$1" >>"$FAKE_CALLS"
case "$1" in
  apply)
    count="$(grep -c '^apply$' "$FAKE_CALLS")"
    if [[ "$count" == "1" ]]; then
      cat "$FAKE_FIRST_APPLY_LOG"
      exit "$FAKE_FIRST_APPLY_EXIT"
    fi
    exit "$FAKE_SECOND_APPLY_EXIT"
    ;;
  plan)
    exit "$FAKE_PLAN_EXIT"
    ;;
  show)
    cat "$FAKE_RETRY_PLAN_JSON"
    ;;
esac
"""


def _run_apply(
    tmp_path: Path,
    *,
    first_log: list[str],
    first_exit: int = 1,
    retry: dict | None = None,
    plan_exit: int = 0,
    second_exit: int = 0,
    action: str = "apply",
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    _tool(bin_dir, "terraform", FAKE_TERRAFORM)
    _tool(bin_dir, "sleep", 'printf "sleep %s\\n" "$1" >>"$FAKE_CALLS"\n')
    (tmp_path / "first.log").write_text("".join(line + "\n" for line in first_log), "utf-8")
    (tmp_path / "sre-demo-lab-plan.json").write_text(json.dumps(REVIEWED), encoding="utf-8")
    (tmp_path / "retry.json").write_text(
        json.dumps(retry if retry is not None else {"resource_changes": []}), encoding="utf-8"
    )
    (tmp_path / "calls").write_text("", encoding="utf-8")
    environment = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "GITHUB_WORKSPACE": str(REPO_ROOT),
        "RUNNER_TEMP": str(tmp_path),
        "REQUESTED_ACTION": action,
        "FAKE_CALLS": str(tmp_path / "calls"),
        "FAKE_FIRST_APPLY_LOG": str(tmp_path / "first.log"),
        "FAKE_FIRST_APPLY_EXIT": str(first_exit),
        "FAKE_SECOND_APPLY_EXIT": str(second_exit),
        "FAKE_PLAN_EXIT": str(plan_exit),
        "FAKE_RETRY_PLAN_JSON": str(tmp_path / "retry.json"),
    }
    result = subprocess.run(  # noqa: S603 - resolved Bash and an extracted repository step.
        [str(BASH), "-c", _step_script("Apply exact plan")],
        capture_output=True,
        check=False,
        cwd=tmp_path,
        env=environment,
        text=True,
        timeout=60,
    )
    return result, (tmp_path / "calls").read_text(encoding="utf-8").splitlines()


RETRY_INSIDE = {"resource_changes": [_change("azurerm_nat_gateway.egress", ["update"], OLD, NEW)]}


def test_a_successful_apply_needs_no_retry(tmp_path: Path) -> None:
    result, calls = _run_apply(tmp_path, first_log=[], first_exit=0)

    assert result.returncode == 0
    assert calls == ["apply"]
    assert result.stdout == "scenario-lab Terraform apply completed.\n"


def test_a_pure_authorization_failure_retries_once_inside_the_reviewed_plan(
    tmp_path: Path,
) -> None:
    result, calls = _run_apply(
        tmp_path, first_log=[_diagnostic(AUTHORIZATION)] * 2, retry=RETRY_INSIDE
    )

    assert result.returncode == 0, result.stderr
    assert calls == ["apply", "sleep 300", "plan", "show", "apply"]
    assert "Terraform apply diagnostic Azure codes: AuthorizationFailed, HTTP403" in result.stdout
    assert "Scenario lab retry plan: 0 create, 1 update, 0 delete or replace, 0 import." in (
        result.stdout
    )
    assert result.stdout.endswith(
        "scenario-lab Terraform apply completed after one authorization retry.\n"
    )
    assert "leak" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("first_log", "action"),
    [
        (
            [_diagnostic(AUTHORIZATION), _diagnostic("ERROR CODE: RequestDisallowedByPolicy")],
            "apply",
        ),
        ([_diagnostic("unexpected status 409 with error: AnotherOperationInProgress: x")], "apply"),
        ([_diagnostic(AUTHORIZATION)], "recreate-aks"),
    ],
)
def test_other_failures_are_not_retried(tmp_path: Path, first_log: list[str], action: str) -> None:
    result, calls = _run_apply(tmp_path, first_log=first_log, retry=RETRY_INSIDE, action=action)

    assert result.returncode == 1
    assert calls == ["apply"]
    assert result.stderr.endswith(
        "scenario-lab Terraform apply failed; raw output remains runner-local.\n"
    )


def test_a_retry_plan_outside_the_reviewed_plan_is_never_applied(tmp_path: Path) -> None:
    outside = {"resource_changes": [_change("azurerm_public_ip.egress", ["update"], OLD, NEW)]}

    result, calls = _run_apply(tmp_path, first_log=[_diagnostic(AUTHORIZATION)], retry=outside)

    assert result.returncode == 1
    assert calls == ["apply", "sleep 300", "plan", "show"]
    assert "leaves the reviewed plan: azurerm_public_ip.egress (new address)" in result.stderr


def test_a_failed_retry_plan_or_retry_apply_is_not_retried_again(tmp_path: Path) -> None:
    failed_plan, plan_calls = _run_apply(
        tmp_path / "plan", first_log=[_diagnostic(AUTHORIZATION)], plan_exit=1
    )
    failed_apply, apply_calls = _run_apply(
        tmp_path / "apply",
        first_log=[_diagnostic(AUTHORIZATION)],
        retry=RETRY_INSIDE,
        second_exit=1,
    )

    assert failed_plan.returncode == 1
    assert plan_calls == ["apply", "sleep 300", "plan"]
    assert "scenario-lab retry plan failed; raw output remains runner-local." in failed_plan.stderr
    assert failed_apply.returncode == 1
    assert apply_calls == ["apply", "sleep 300", "plan", "show", "apply"]
    assert failed_apply.stderr.endswith(
        "scenario-lab Terraform retry apply failed; raw output remains runner-local.\n"
    )
