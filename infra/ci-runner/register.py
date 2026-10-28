#!/usr/bin/env python3
"""Register an isolated CI VM without placing its token in CLI arguments or Terraform."""

from __future__ import annotations

import argparse
import http.client
import json
import re
import subprocess
import time
import urllib.parse
import uuid
from typing import Any


def _json_command(arguments: list[str]) -> Any:
    result = subprocess.run(  # noqa: S603 - fixed gh/az commands, never shell-expanded
        arguments, check=True, capture_output=True, text=True, timeout=60
    )
    return json.loads(result.stdout)


def registration_script(repository: str, runner_name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Expected owner/repository")
    if not re.fullmatch(r"[A-Za-z0-9-]+", runner_name):
        raise ValueError("Expected an alphanumeric VM name")
    return f"""#!/usr/bin/env bash
set -euo pipefail
ulimit -c 0
test -f /var/lib/fdai-ci-bootstrap-ready
/usr/local/sbin/fdai-ci-storage
install -d -o fdairunner -g fdairunner /opt/actions-runner/_diag
cd /opt/actions-runner
if [[ -f .runner ]]; then
  echo "Runner is already configured; inspect it rather than replacing it" >&2
  exit 1
fi
test -n "${{ACTIONS_RUNNER_INPUT_TOKEN:?registration token environment is required}}"
export ACTIONS_RUNNER_INPUT_TOKEN
sudo --preserve-env=ACTIONS_RUNNER_INPUT_TOKEN -u fdairunner ./config.sh \\
  --unattended --url https://github.com/{repository} --name {runner_name} \\
  --labels fdai-ci,fdai-ci-ssd --work /mnt/fdai-ci/work
unset ACTIONS_RUNNER_INPUT_TOKEN
printf '%s\\n' 'AGENT_TOOLSDIRECTORY=/opt/hostedtoolcache' \\
  'XDG_CACHE_HOME=/mnt/fdai-ci/cache' >> .env
./svc.sh install fdairunner
service_name="$(cat .service)"
install -d "/etc/systemd/system/$service_name.d"
printf '%s\\n' '[Unit]' 'RequiresMountsFor=/mnt' '[Service]' \\
  'LimitCORE=0' \\
  'ExecStartPre=+/usr/local/sbin/fdai-ci-storage' \\
  > "/etc/systemd/system/$service_name.d/storage.conf"
systemctl daemon-reload
./svc.sh start
systemctl is-active "$service_name"
echo FDAI_CI_RUNNER_REGISTERED
"""


def command_payload(repository: str, vm_name: str, location: str, token: str) -> dict[str, Any]:
    return {
        "location": location,
        "properties": {
            "source": {"script": registration_script(repository, vm_name)},
            "protectedParameters": [{"name": "ACTIONS_RUNNER_INPUT_TOKEN", "value": token}],
            "timeoutInSeconds": 300,
            "asyncExecution": False,
        },
    }


def _request(url: str, bearer: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    target = urllib.parse.urlsplit(url)
    if target.scheme != "https" or target.netloc != "management.azure.com":
        raise ValueError("Run Command requests must target the Azure management HTTPS endpoint")
    data = None if payload is None else json.dumps(payload).encode()
    connection = http.client.HTTPSConnection("management.azure.com", timeout=60)
    try:
        connection.request(
            "GET" if payload is None else "PUT",
            target.path + ("?" + target.query if target.query else ""),
            body=data,
            headers={"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        if not 200 <= response.status < 300:
            raise RuntimeError(f"Azure Run Command request failed: HTTP {response.status}")
        return json.load(response)
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--vm-name", required=True)
    parser.add_argument("--subscription", required=True)
    args = parser.parse_args()
    registration_script(args.repository, args.vm_name)
    account = _json_command(["az", "account", "show", "-o", "json"])
    if account["id"] != args.subscription:
        raise SystemExit("Active Azure subscription does not match the approved target")
    policy = _json_command(
        ["gh", "api", f"repos/{args.repository}/actions/permissions/fork-pr-contributor-approval"]
    )
    if policy["approval_policy"] != "all_external_contributors":
        raise SystemExit(
            "Require approval for all external contributors before public CI enrollment"
        )
    vm = _json_command(
        [
            "az",
            "vm",
            "show",
            "--subscription",
            args.subscription,
            "-g",
            args.resource_group,
            "-n",
            args.vm_name,
            "-o",
            "json",
        ]
    )
    if (vm.get("identity") or {}).get("type", "None") != "None":
        raise SystemExit("CI VM must not have a managed identity")
    runners = _json_command(["gh", "api", f"repos/{args.repository}/actions/runners?per_page=100"])
    if any(runner["name"] == args.vm_name for runner in runners["runners"]):
        raise SystemExit("Runner name already exists; inspect current registration before retrying")
    token = _json_command(
        ["gh", "api", "-X", "POST", f"repos/{args.repository}/actions/runners/registration-token"]
    )["token"]
    bearer = _json_command(["az", "account", "get-access-token", "-o", "json"])["accessToken"]
    command_name = "fdai-ci-register-" + uuid.uuid4().hex[:12]
    url = (
        f"https://management.azure.com{vm['id']}/runCommands/{command_name}?api-version=2025-04-01"
    )
    print(f"Registration command: {command_name}", flush=True)
    print("Submitting registration using protected parameters", flush=True)
    _request(url, bearer, command_payload(args.repository, args.vm_name, vm["location"], token))
    deadline = time.monotonic() + 360
    while time.monotonic() < deadline:
        result = _request(url + "&$expand=instanceView", bearer)
        properties = result["properties"]
        view = properties.get("instanceView", {})
        state = view.get("executionState", "")
        print(f"Registration execution state: {state or 'Pending'}", flush=True)
        if state in {"Failed", "Canceled", "TimedOut"}:
            raise SystemExit(
                "Registration failed; inspect VM Run Command status without printing secrets"
            )
        if state == "Succeeded":
            if view.get("exitCode") != 0:
                raise SystemExit("Registration command returned a nonzero exit code")
            print("Registration command completed; verify GitHub online state independently")
            return
        if properties.get("provisioningState") == "Failed":
            raise SystemExit("Registration provisioning failed")
        time.sleep(10)
    raise SystemExit("Registration deadline exceeded; inspect state before retrying")


if __name__ == "__main__":
    main()
