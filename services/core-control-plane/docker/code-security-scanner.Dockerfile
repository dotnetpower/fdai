# FDAI code-security scan runner: the deterministic scanners, the bubblewrap sandbox, and the
# FDAI code-security CLI in one image. Every scanner binary is pinned by version and SHA-256.
#
# Build:  docker build -f services/core-control-plane/docker/code-security-scanner.Dockerfile .
# Run:    the entrypoint's `prepare` step refreshes offline vulnerability databases into /cache
#         with network access; `scan` then runs every scanner in the sandbox without network.
#         bubblewrap needs unprivileged user namespaces, so the container runtime must allow them
#         (for Docker: --security-opt seccomp=unconfined --security-opt apparmor=unconfined).

ARG BASE_IMAGE_REGISTRY=docker.io

FROM ${BASE_IMAGE_REGISTRY}/library/python@sha256:540c7d91f98ff6880174c40e99067bf5941eb54d818a7a5e094d188b196a934d AS tools

ARG OPENGREP_VERSION=v1.30.1
ARG OPENGREP_SHA256=e66f22675fae171ac1244d49b7f6a2e15a2d3613f3df9aad3c7fb2aaa1461c3a
ARG GITLEAKS_VERSION=8.30.1
ARG GITLEAKS_SHA256=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
ARG OSV_SCANNER_VERSION=v2.6.0
ARG OSV_SCANNER_SHA256=ca69b3d3cd08f889a49dc0a383122f71cc528b83803671df5fd874d97485b108
ARG TRIVY_VERSION=0.75.0
ARG TRIVY_SHA256=c6e65abddb348e25f10549df887045629cf28cc72453cd1c63acb717316b3f3f

WORKDIR /download
RUN set -eu \
    && mkdir -p /opt/scanners/bin \
    && wget -q -O opengrep "https://github.com/opengrep/opengrep/releases/download/${OPENGREP_VERSION}/opengrep_musllinux_x86" \
    && echo "${OPENGREP_SHA256}  opengrep" | sha256sum -c - \
    && install -m 0755 opengrep /opt/scanners/bin/opengrep \
    && wget -q -O gitleaks.tar.gz "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
    && echo "${GITLEAKS_SHA256}  gitleaks.tar.gz" | sha256sum -c - \
    && tar -xzf gitleaks.tar.gz gitleaks \
    && install -m 0755 gitleaks /opt/scanners/bin/gitleaks \
    && wget -q -O osv-scanner "https://github.com/google/osv-scanner/releases/download/${OSV_SCANNER_VERSION}/osv-scanner_linux_amd64" \
    && echo "${OSV_SCANNER_SHA256}  osv-scanner" | sha256sum -c - \
    && install -m 0755 osv-scanner /opt/scanners/bin/osv-scanner \
    && wget -q -O trivy.tar.gz "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" \
    && echo "${TRIVY_SHA256}  trivy.tar.gz" | sha256sum -c - \
    && tar -xzf trivy.tar.gz trivy \
    && install -m 0755 trivy /opt/scanners/bin/trivy

FROM ${BASE_IMAGE_REGISTRY}/library/python@sha256:540c7d91f98ff6880174c40e99067bf5941eb54d818a7a5e094d188b196a934d AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apk add --no-cache build-base zlib-dev
RUN pip install --no-cache-dir uv==0.11.32

WORKDIR /build
COPY pyproject.toml uv.lock LICENSE README.md ./
COPY evaluation-sdk/pyproject.toml ./evaluation-sdk/pyproject.toml
COPY benchmarks/sregym/pyproject.toml ./benchmarks/sregym/pyproject.toml
COPY benchmarks/cybergym/pyproject.toml ./benchmarks/cybergym/pyproject.toml
COPY extensions/code-assurance/pyproject.toml ./extensions/code-assurance/pyproject.toml
COPY extensions/cost-governance/pyproject.toml ./extensions/cost-governance/pyproject.toml
COPY services/operator-service/pyproject.toml ./services/operator-service/pyproject.toml
COPY services/document-ingestion-api/pyproject.toml ./services/document-ingestion-api/pyproject.toml
COPY services/document-processing-worker/pyproject.toml ./services/document-processing-worker/pyproject.toml
COPY services/isolated-executor/pyproject.toml ./services/isolated-executor/pyproject.toml
COPY services/system-knowledge-service/pyproject.toml ./services/system-knowledge-service/pyproject.toml
COPY packages/github-app-auth/ ./packages/github-app-auth/
COPY packages/service-contracts/ ./packages/service-contracts/
COPY packages/runtime-diagnostics/ ./packages/runtime-diagnostics/
COPY services/core-control-plane/ ./services/core-control-plane/
RUN uv build --wheel --package fdai-github-app-auth --out-dir /wheels \
    && uv build --wheel --package fdai-service-contracts --out-dir /wheels \
    && uv build --wheel --package fdai-runtime-diagnostics --out-dir /wheels \
    && uv build --wheel --package fdai-core-control-plane --out-dir /wheels \
    && uv sync --frozen --package fdai-core-control-plane --no-dev --no-editable \
        --no-install-package fdai \
        --no-install-package fdai-github-app-auth \
        --no-install-package fdai-service-contracts \
        --no-install-package fdai-runtime-diagnostics \
        --no-install-package fdai-core-control-plane \
    && uv pip install --python /app/.venv/bin/python --no-deps \
        /wheels/fdai_github_app_auth-*.whl \
        /wheels/fdai_service_contracts-*.whl \
        /wheels/fdai_runtime_diagnostics-*.whl \
        /wheels/fdai_core_control_plane-*.whl

FROM ${BASE_IMAGE_REGISTRY}/library/python@sha256:540c7d91f98ff6880174c40e99067bf5941eb54d818a7a5e094d188b196a934d AS runtime

RUN apk add --no-cache bubblewrap git

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp/fdai \
    PATH="/app/.venv/bin:/opt/scanners/bin:${PATH}"

WORKDIR /app
COPY --from=builder --chown=65532:65532 /app/.venv /app/.venv
COPY --from=tools /opt/scanners/bin/ /opt/scanners/bin/
COPY --chown=65532:65532 rule-catalog/code-security/ /app/rule-catalog/code-security/
COPY --chown=65532:65532 config/ /app/config/
COPY --chmod=0755 services/core-control-plane/docker/code-security-scanner-entrypoint.sh /usr/local/bin/fdai-scan-runner
USER 65532
RUN opengrep --version \
    && gitleaks version \
    && osv-scanner --version \
    && trivy --version \
    && bwrap --version \
    && python -m fdai.delivery.code_security_cli evaluate > /dev/null
ENTRYPOINT ["fdai-scan-runner"]
