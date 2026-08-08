#!/usr/bin/env bash
# Runs inside the Azure runner VM. Arguments are base64 encoded so the local
# command shell never interprets GitHub tokens or runner coordinates.
set -euo pipefail

REPO="$(printf '%s' "${1:?repository payload is required}" | base64 -d)"
RUNNER_USER="$(printf '%s' "${2:?runner user payload is required}" | base64 -d)"
PARALLELISM="${3:?parallelism is required}"
TOKEN="$(printf '%s' "${4:?registration token payload is required}" | base64 -d)"
REMOVE_TOKEN="$(printf '%s' "${5:?remove token payload is required}" | base64 -d)"
BASE_HOME="/home/${RUNNER_USER}/actions-runner"

install_runner() {
  local runner_home="$1"
  if [[ -x "$runner_home/config.sh" ]]; then
    return
  fi
  install -d -o "$RUNNER_USER" -g "$RUNNER_USER" "$runner_home"
  local runner_version
  runner_version="$(
    curl -fsSL https://api.github.com/repos/actions/runner/releases/latest \
      | jq -r .tag_name \
      | sed 's/^v//'
  )"
  curl -fsSL -o "$runner_home/runner.tar.gz" \
    "https://github.com/actions/runner/releases/download/v${runner_version}/actions-runner-linux-x64-${runner_version}.tar.gz"
  tar -xzf "$runner_home/runner.tar.gz" -C "$runner_home"
  rm -f "$runner_home/runner.tar.gz"
  chown -R "$RUNNER_USER":"$RUNNER_USER" "$runner_home"
}

for slot in $(seq 1 "$PARALLELISM"); do
  runner_home="$BASE_HOME"
  runner_name="$(hostname)"
  if [[ "$slot" -gt 1 ]]; then
    runner_home="$BASE_HOME-$slot"
    runner_name="$(hostname)-$slot"
  fi
  install_runner "$runner_home"
  cd "$runner_home"
  if [[ -f .runner ]]; then
    ./svc.sh stop || true
    ./svc.sh uninstall || true
    sudo -u "$RUNNER_USER" ./config.sh remove --token "$REMOVE_TOKEN"
  fi
  sudo -u "$RUNNER_USER" ./config.sh --unattended \
    --url "https://github.com/$REPO" \
    --token "$TOKEN" \
    --name "$runner_name" \
    --labels self-hosted,fdai-deploy
  ./svc.sh install "$RUNNER_USER"
  ./svc.sh start
  ./svc.sh status
done

for runner_home in "$BASE_HOME"-[2-5]; do
  [[ -d "$runner_home" ]] || continue
  slot="${runner_home##*-}"
  if [[ "$slot" -le "$PARALLELISM" ]]; then
    continue
  fi
  cd "$runner_home"
  if [[ -f .runner ]]; then
    ./svc.sh stop || true
    ./svc.sh uninstall || true
    sudo -u "$RUNNER_USER" ./config.sh remove --token "$REMOVE_TOKEN"
  fi
  rm -rf -- "$runner_home"
done

echo "FDAI_RUNNER_REGISTRATION_OK slots=$PARALLELISM"
