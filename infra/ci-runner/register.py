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


def registration_script(repository: str, runner_name: str, parallelism: int = 1) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Expected owner/repository")
    if not re.fullmatch(r"[A-Za-z0-9-]+", runner_name):
        raise ValueError("Expected an alphanumeric VM name")
    if not 1 <= parallelism <= 5:
        raise ValueError("Runner parallelism must be between 1 and 5")
    return f"""#!/usr/bin/env bash
set -euo pipefail
ulimit -c 0
test -f /var/lib/fdai-ci-bootstrap-ready
/usr/local/sbin/fdai-ci-storage
if (( $(nproc) < {parallelism * 3 + 1} )); then
  echo "Insufficient CPU capacity for the requested runner resource limits" >&2
  exit 1
fi
awk '/MemTotal:/ {{ if ($2 < {(parallelism * 12 + 2) * 1024 * 1024}) exit 1 }}' /proc/meminfo || {{
  echo "Insufficient memory capacity for the requested runner resource limits" >&2
  exit 1
}}
test -n "${{ACTIONS_RUNNER_INPUT_TOKEN:?registration token environment is required}}"
export ACTIONS_RUNNER_INPUT_TOKEN
for slot in $(seq 1 {parallelism}); do
  suffix=""
  [[ "$slot" == 1 ]] || suffix="-$slot"
  runner_home="/opt/actions-runner$suffix"
  runner_name="{runner_name}$suffix"
  work="/mnt/fdai-ci/work$suffix"
  cache="/mnt/fdai-ci/cache$suffix"
  tools="/mnt/fdai-ci/toolcache$suffix"
  storage="/usr/local/sbin/fdai-ci-storage$suffix"
  if [[ ! -d "$runner_home" ]]; then
    install -d -o fdairunner -g fdairunner "$runner_home"
    # Copy distribution files only, never registration credentials or mutable state.
    cp -a /opt/actions-runner/bin /opt/actions-runner/externals \\
      /opt/actions-runner/config.sh /opt/actions-runner/env.sh \\
      /opt/actions-runner/run.sh /opt/actions-runner/run-helper.sh.template \\
      /opt/actions-runner/run-helper.cmd.template /opt/actions-runner/safe_sleep.sh \\
      "$runner_home/"
    chown -R fdairunner:fdairunner "$runner_home"
  fi
  install -d -o fdairunner -g fdairunner "$runner_home/_diag" "$work" "$cache" "$tools"
  cd "$runner_home"
  if [[ -f .runner ]]; then
    python3 - "$runner_name" <<'PY'
import json, sys
with open(".runner", encoding="utf-8-sig") as source:
    config = json.load(source)
if config.get("agentName") != sys.argv[1] or config.get("gitHubUrl", "").rstrip("/") != "https://github.com/{repository}":
    raise SystemExit("Existing runner configuration does not match the approved target")
PY
  else
    sudo --preserve-env=ACTIONS_RUNNER_INPUT_TOKEN -u fdairunner ./config.sh \\
      --unattended --url https://github.com/{repository} --name "$runner_name" \\
      --labels fdai-ci,fdai-ci-ssd --work "$work"
  fi
  if [[ ! -f .service ]]; then
    printf '%s\\n' "AGENT_TOOLSDIRECTORY=$tools" "XDG_CACHE_HOME=$cache" >> .env
    ./svc.sh install fdairunner
  fi
  service_name="$(cat .service)"
  if [[ "$slot" != 1 ]]; then
    printf '%s\\n' '#!/usr/bin/env bash' 'set -euo pipefail' \\
      '/usr/local/sbin/fdai-ci-storage' \\
      "install -d -o fdairunner -g fdairunner $work $cache $tools" > "$storage"
    chmod 0755 "$storage"
  fi
  install -d "/etc/systemd/system/$service_name.d"
  printf '%s\\n' '[Unit]' 'RequiresMountsFor=/mnt' '[Service]' \\
    'LimitCORE=0' "ExecStartPre=+$storage" \\
    > "/etc/systemd/system/$service_name.d/storage.conf"
  systemctl daemon-reload
  systemctl set-property "$service_name" CPUQuota=300% MemoryHigh=10G MemoryMax=12G TasksMax=8192
  if ! systemctl is-active --quiet "$service_name"; then
    ./svc.sh start
  fi
  systemctl is-active "$service_name"
  echo "FDAI_CI_SLOT_READY slot=$slot"
done
unset ACTIONS_RUNNER_INPUT_TOKEN
echo "FDAI_CI_RUNNER_REGISTERED slots={parallelism}"
"""


def command_payload(
    repository: str,
    vm_name: str,
    location: str,
    token: str,
    parallelism: int = 1,
) -> dict[str, Any]:
    return {
        "location": location,
        "properties": {
            "source": {"script": registration_script(repository, vm_name, parallelism)},
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
    parser.add_argument("--parallelism", type=int, choices=range(1, 6), default=1)
    args = parser.parse_args()
    registration_script(args.repository, args.vm_name, args.parallelism)
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
    expected_names = {
        args.vm_name if slot == 1 else f"{args.vm_name}-{slot}"
        for slot in range(1, args.parallelism + 1)
    }
    for runner in runners["runners"]:
        if runner["name"] not in expected_names:
            continue
        if runner["busy"]:
            raise SystemExit("An affected CI runner is busy; wait before changing resource limits")
        labels = {label["name"] for label in runner["labels"]}
        if not {"fdai-ci", "fdai-ci-ssd"} <= labels or any(
            label.startswith("fdai-deploy") for label in labels
        ):
            raise SystemExit("Existing runner name does not belong to the isolated CI pool")
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
    _request(
        url,
        bearer,
        command_payload(args.repository, args.vm_name, vm["location"], token, args.parallelism),
    )
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
