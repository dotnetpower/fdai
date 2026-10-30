#!/usr/bin/env bash
# Run only on a new, dedicated Ubuntu image builder. This never registers a runner.
set -euo pipefail

if [[ $# != 2 || ! "$2" =~ ^[0-9a-f]{40}$ ]]; then
  printf '%s\n' 'Usage: provision-vm-image.sh <source-root> <source-commit-sha>' >&2
  exit 2
fi
source_root=$(cd -- "$1" && pwd)
source_sha=$2
if [[ "$(id -u)" != 0 || "$(uname -m)" != x86_64 ]]; then
  printf '%s\n' 'A clean root-owned Ubuntu x86_64 image builder is required.' >&2
  exit 1
fi
# shellcheck source=/dev/null
source /etc/os-release
if [[ "$ID" != ubuntu || "$VERSION_ID" != 24.04 ]]; then
  printf '%s\n' 'The approved base image must be Ubuntu 24.04.' >&2
  exit 1
fi
if [[ -n "${GITHUB_RUNNER_CREDENTIAL:-}${GITHUB_TOKEN:-}${GITHUB_PAT:-}${GH_TOKEN:-}${AZURE_CLIENT_SECRET:-}" ]]; then
  printf '%s\n' 'Credential-bearing environments are not accepted by the image builder.' >&2
  exit 1
fi
for path in /opt/actions-runner /home/runner /root/.azure /root/.config/gh \
  /var/lib/fdai-ci-image-ready; do
  if [[ -e "$path" ]]; then
    printf '%s\n' 'The builder is not clean; no existing runner or authenticated host is accepted.' >&2
    exit 1
  fi
done

export DEBIAN_FRONTEND=noninteractive
install -d -m 0700 /opt/fdai-ci/image-work
export TMPDIR=/opt/fdai-ci/image-work
apt-get update -y
apt-get install -y --no-install-recommends ca-certificates curl gnupg jq python3 tini unzip tzdata tzdata-legacy
install -d -m 0755 /opt/fdai-ci
install -m 0644 "$source_root/infra/ci-runner/toolchain.json" /opt/fdai-ci/toolchain.json
install -m 0755 "$source_root/infra/ci-runner/verify-toolchain.py" /opt/fdai-ci/verify-toolchain.py
install -m 0755 "$source_root/infra/ci-runner/provision-toolchain.sh" /opt/fdai-ci/provision-toolchain.sh
timeout 2400 /opt/fdai-ci/provision-toolchain.sh

useradd --create-home --home-dir /home/runner --shell /bin/bash runner
usermod -aG docker runner
install -d -o runner -g runner /opt/actions-runner /opt/hostedtoolcache /home/runner/_work
runner_version=2.338.2
runner_sha256=baebf204307bac6193480852732f0aba2ae97b6c5597c244f4d5558390147c40
archive=/opt/fdai-ci/image-work/actions-runner.tar.gz
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 --max-time 180 \
  "https://github.com/actions/runner/releases/download/v${runner_version}/actions-runner-linux-x64-${runner_version}.tar.gz" \
  --output "$archive"
printf '%s  %s\n' "$runner_sha256" "$archive" | sha256sum --check --strict
tar -xzf "$archive" -C /opt/actions-runner
rm -f -- "$archive"
/opt/actions-runner/bin/installdependencies.sh
chown -R runner:runner /opt/actions-runner
install -o root -g root -m 0755 "$source_root/infra/ci-runner-aca/broker-entrypoint.py" \
  /opt/fdai-ci/broker-entrypoint.py
systemctl enable --now docker
systemctl is-active --quiet docker
docker info >/dev/null
/opt/fdai-ci/verify-toolchain.py

# The listener bundles its action JavaScript runtime. Workflows select Node/npm with setup-node.
# No config.sh, JIT config, bootstrap ticket, GitHub credential or Azure login is used here.
printf '{"source_sha":"%s","runner_version":"%s","registration":"absent"}\n' \
  "$source_sha" "$runner_version" > /var/lib/fdai-ci-image-ready
chmod 0644 /var/lib/fdai-ci-image-ready
rm -rf -- /opt/fdai-ci/image-work /var/lib/apt/lists/*
printf '%s\n' 'vm_image_toolchain_ready'
