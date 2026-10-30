FROM mcr.microsoft.com/mirror/docker/library/ubuntu:24.04

ARG RUNNER_VERSION=2.338.2
ARG RUNNER_SHA256=baebf204307bac6193480852732f0aba2ae97b6c5597c244f4d5558390147c40

ENV DEBIAN_FRONTEND=noninteractive \
    RUNNER_ALLOW_RUNASROOT=0 \
    AGENT_TOOLSDIRECTORY=/opt/hostedtoolcache

# Bootstrap prerequisites the provisioner itself needs before it reads the manifest.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg jq pipx python-is-python3 sudo python3 tini unzip \
 && install -d -m 0755 /etc/sudoers.d \
 && printf '%s\n' 'runner ALL=(root) NOPASSWD: /usr/bin/tar, /bin/tar' > /etc/sudoers.d/fdai-ci-trivy \
 && chmod 0440 /etc/sudoers.d/fdai-ci-trivy \
 && printf '[global]\nbreak-system-packages = true\n' > /etc/pip.conf \
 && chmod 0644 /etc/pip.conf \
 && rm -rf /var/lib/apt/lists/*

# The same manifest, provisioner, and verifier every VM runner uses: one declared toolchain.
COPY toolchain.json verify-toolchain.py provision-toolchain.sh /opt/fdai-ci/
RUN chmod 0755 /opt/fdai-ci/provision-toolchain.sh /opt/fdai-ci/verify-toolchain.py \
 && /opt/fdai-ci/provision-toolchain.sh \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash runner \
 && install -d -o runner -g runner /opt/actions-runner /opt/hostedtoolcache /home/runner/_work \
 && curl --fail --silent --show-error --location --max-time 180 \
      "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz" \
      --output /tmp/runner.tar.gz \
 && echo "${RUNNER_SHA256}  /tmp/runner.tar.gz" | sha256sum --check --strict \
 && tar -xzf /tmp/runner.tar.gz -C /opt/actions-runner \
 && rm /tmp/runner.tar.gz \
 && /opt/actions-runner/bin/installdependencies.sh \
 && rm -rf /var/lib/apt/lists/* \
 && chown -R runner:runner /opt/actions-runner

COPY entrypoint.sh /opt/fdai-ci/entrypoint.sh
COPY broker-entrypoint.py /opt/fdai-ci/broker-entrypoint.py
RUN chmod 0755 /opt/fdai-ci/entrypoint.sh

# Starts as root only to read the registration credential; the job runs as `runner`.
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/opt/fdai-ci/entrypoint.sh"]
