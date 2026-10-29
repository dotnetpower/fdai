#!/usr/bin/env bash
# Register one ephemeral GitHub Actions runner, run exactly one job, then exit.
#
# PID 1 starts as root so the registration credential in its environment is unreadable by the
# `runner` account that executes workflow code. The credential is exchanged for a one-time
# registration token; neither value reaches the job process.
set -euo pipefail

: "${GITHUB_REPOSITORY:?owner/repository is required}"
: "${RUNNER_LABELS:?comma-separated runner labels are required}"
: "${GITHUB_RUNNER_CREDENTIAL:?runner registration credential is required}"
[[ "$GITHUB_REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || {
  echo "GITHUB_REPOSITORY must be owner/repository" >&2
  exit 1
}

runner_name="${CONTAINER_APP_JOB_EXECUTION_NAME:-fdai-ci-aca-$(hostname)}"
api="${GITHUB_API_URL:-https://api.github.com}"

# Fail before registering when the image toolchain has drifted from the manifest.
python3 /opt/fdai-ci/verify-toolchain.py --manifest /opt/fdai-ci/toolchain.json

registration_token="$(
  curl --fail --silent --show-error --max-time 30 --request POST \
    --header "Authorization: Bearer ${GITHUB_RUNNER_CREDENTIAL}" \
    --header "Accept: application/vnd.github+json" \
    "${api}/repos/${GITHUB_REPOSITORY}/actions/runners/registration-token" |
    jq -er .token
)" || {
  echo "runner registration token request failed: check the job credential and its scope" >&2
  exit 1
}
unset GITHUB_RUNNER_CREDENTIAL

cd /opt/actions-runner
export ACTIONS_RUNNER_INPUT_TOKEN="$registration_token"
unset registration_token
runuser -u runner --preserve-environment -- ./config.sh \
  --unattended --ephemeral --disableupdate \
  --url "https://github.com/${GITHUB_REPOSITORY}" \
  --name "$runner_name" \
  --labels "$RUNNER_LABELS" \
  --work /home/runner/_work
unset ACTIONS_RUNNER_INPUT_TOKEN

# A clean environment: no credential, token, or container-app identity endpoint is inherited.
exec runuser -u runner -- env -i \
  HOME=/home/runner \
  PATH=/usr/local/bin:/usr/bin:/bin \
  AGENT_TOOLSDIRECTORY=/opt/hostedtoolcache \
  RUNNER_ALLOW_RUNASROOT=0 \
  /opt/actions-runner/run.sh
