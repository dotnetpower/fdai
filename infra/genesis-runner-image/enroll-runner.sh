#!/usr/bin/env bash
# Read one short-lived GitHub registration token from stdin. Never accept it as an argument.
set -euo pipefail
set +x
ulimit -c 0

repository_url=""
slot=""
runner_name=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repository-url) repository_url="$2"; shift 2 ;;
    --slot) slot="$2"; shift 2 ;;
    --runner-name) runner_name="$2"; shift 2 ;;
    *) echo "fdai-enroll-runner: unsupported argument" >&2; exit 64 ;;
  esac
done

[[ "$repository_url" =~ ^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || {
  echo "fdai-enroll-runner: repository URL is invalid" >&2
  exit 64
}
[[ "$slot" =~ ^[1-5]$ ]] || {
  echo "fdai-enroll-runner: slot must be from 1 through 5" >&2
  exit 64
}
[[ "$runner_name" =~ ^vm-runner-[a-z0-9][a-z0-9-]{0,62}$ ]] || {
  echo "fdai-enroll-runner: runner name is invalid" >&2
  exit 64
}
IFS= read -r token
[[ "$token" =~ ^[^[:space:]]{20,4096}$ ]] || {
  echo "fdai-enroll-runner: registration input is invalid" >&2
  exit 64
}

runner_version="$(jq -r .github_runner_version /etc/fdai-runner-image.json)"
archive="/opt/fdai/runner/actions-runner-linux-x64-${runner_version}.tar.gz"
runner_home="$HOME/actions-runner"
if [[ "$slot" != "1" ]]; then
  runner_home="${runner_home}-${slot}"
fi
[[ ! -L "$runner_home" ]] || {
  echo "fdai-enroll-runner: runner home cannot be a symbolic link" >&2
  exit 65
}
install -d -m 0700 "$runner_home"
if [[ ! -x "$runner_home/config.sh" ]]; then
  tar -xzf "$archive" -C "$runner_home"
fi
cd "$runner_home"
[[ ! -e .runner ]] || {
  echo "fdai-enroll-runner: runner slot is already configured" >&2
  exit 65
}

export ACTIONS_RUNNER_INPUT_TOKEN="$token"
export ACTIONS_RUNNER_INPUT_URL="$repository_url"
trap 'unset ACTIONS_RUNNER_INPUT_TOKEN ACTIONS_RUNNER_INPUT_URL; token=""' EXIT
./config.sh \
  --unattended \
  --name "$runner_name" \
  --labels self-hosted,fdai-deploy,fdai-deploy-candidate \
  --work _work \
  --disableupdate \
  >/dev/null 2>&1
unset ACTIONS_RUNNER_INPUT_TOKEN ACTIONS_RUNNER_INPUT_URL
token=""

sudo -n ./svc.sh install "$USER" >/dev/null 2>&1
sudo -n ./svc.sh start >/dev/null 2>&1
sudo -n ./svc.sh status >/dev/null 2>&1
printf 'enrollment_complete slot=%s runner_name=%s\n' "$slot" "$runner_name"
