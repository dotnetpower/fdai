# FDAI code-security scan runner: the deterministic scanners, the bubblewrap sandbox, and the
# FDAI code-security CLI in one image. Downloaded binaries and rebuilt sources are digest-pinned.
#
# Build:  docker build -f services/core-control-plane/docker/code-security-scanner.Dockerfile .
#         Add `--target prover` for the proof-lane image, which also carries Node.js, gcc with
#         AddressSanitizer and UndefinedBehaviorSanitizer, a JDK, and the .NET SDK so `--prove`
#         can reproduce Python, JavaScript, native, Java, and C# issues. The images are glibc-based
#         because the sanitizer runtimes don't support musl.
# Run:    the entrypoint's `prepare` step refreshes offline vulnerability databases into /cache
#         with network access; `scan` then runs every scanner in the sandbox without network.
#         bubblewrap needs unprivileged user namespaces, so the container runtime must allow them
#         (for Docker: --security-opt seccomp=unconfined --security-opt apparmor=unconfined).

ARG BASE_IMAGE_REGISTRY=docker.io

FROM ${BASE_IMAGE_REGISTRY}/library/golang@sha256:85dc1069ac644ea3c527b177303a406eb3358192816cd7f9e5848eb658851673 AS scanner-builder

ENV GOTOOLCHAIN=local \
    CGO_ENABLED=0 \
    GOFLAGS="-p=4"

ARG SCANNER_GO_VERSION=go1.27.2
ARG SCANNER_X_NET_VERSION=v0.60.0
ARG SCANNER_X_CRYPTO_VERSION=v0.57.0
ARG SCANNER_X_TEXT_VERSION=v0.42.0
RUN test "$(go env GOVERSION)" = "${SCANNER_GO_VERSION}" && mkdir -p /out

ARG GITLEAKS_VERSION=8.30.1
ARG GITLEAKS_MODULE_SUM=h1:PmEvCfVI7ti9dV3s5aMZUY7sS2GxRvG3yzih7E+cS3w=
ARG GITLEAKS_RAR_VERSION=v2.2.0
ARG GITLEAKS_XZ_VERSION=v0.5.15
RUN go mod download "github.com/zricethezav/gitleaks/v8@v${GITLEAKS_VERSION}" \
    && test "$(go mod download -json "github.com/zricethezav/gitleaks/v8@v${GITLEAKS_VERSION}" | awk '$1 == "\"Sum\":" {gsub(/[",]/, "", $2); print $2}')" = "${GITLEAKS_MODULE_SUM}" \
    && scanner_dir="$(go env GOPATH)/pkg/mod/github.com/zricethezav/gitleaks/v8@v${GITLEAKS_VERSION}" \
    && chmod -R u+w "${scanner_dir}" \
    && cd "${scanner_dir}" \
    && go mod edit -require="golang.org/x/crypto@${SCANNER_X_CRYPTO_VERSION}" \
    && go mod edit -require="golang.org/x/text@${SCANNER_X_TEXT_VERSION}" \
    && go mod edit -require="github.com/nwaples/rardecode/v2@${GITLEAKS_RAR_VERSION}" \
    && go mod edit -require="github.com/ulikunitz/xz@${GITLEAKS_XZ_VERSION}" \
    && go build -mod=mod -ldflags="-X github.com/zricethezav/gitleaks/v8/version.Version=${GITLEAKS_VERSION}" -o /out/gitleaks . \
    && test "$(go version -m /out/gitleaks | awk '$2 == "golang.org/x/crypto" {print $3}')" = "${SCANNER_X_CRYPTO_VERSION}" \
    && test "$(go version -m /out/gitleaks | awk '$2 == "golang.org/x/text" {print $3}')" = "${SCANNER_X_TEXT_VERSION}" \
    && test "$(go version -m /out/gitleaks | awk '$2 == "github.com/nwaples/rardecode/v2" {print $3}')" = "${GITLEAKS_RAR_VERSION}" \
    && test "$(go version -m /out/gitleaks | awk '$2 == "github.com/ulikunitz/xz" {print $3}')" = "${GITLEAKS_XZ_VERSION}" \
    && /out/gitleaks version

ARG OSV_SCANNER_VERSION=v2.6.0
ARG OSV_SCANNER_MODULE_SUM=h1:hqtNLANWaKcqOC6znJX8J/23PtzV82RX23oMS9/ab4I=
RUN go mod download "github.com/google/osv-scanner/v2@${OSV_SCANNER_VERSION}" \
    && test "$(go mod download -json "github.com/google/osv-scanner/v2@${OSV_SCANNER_VERSION}" | awk '$1 == "\"Sum\":" {gsub(/[",]/, "", $2); print $2}')" = "${OSV_SCANNER_MODULE_SUM}" \
    && scanner_dir="$(go env GOPATH)/pkg/mod/github.com/google/osv-scanner/v2@${OSV_SCANNER_VERSION}" \
    && chmod -R u+w "${scanner_dir}" \
    && cd "${scanner_dir}" \
    && go mod edit -require="golang.org/x/net@${SCANNER_X_NET_VERSION}" \
    && go build -mod=mod -o /out/osv-scanner ./cmd/osv-scanner \
    && test "$(go version -m /out/osv-scanner | awk '$2 == "golang.org/x/net" {print $3}')" = "${SCANNER_X_NET_VERSION}" \
    && /out/osv-scanner --version

ARG TRIVY_VERSION=0.75.0
ARG TRIVY_MODULE_SUM=h1:iOMkI0qX3Dfo+A6lznchBvtDD4ZSu+H9RBww1z5Qz58=
RUN go mod download "github.com/aquasecurity/trivy@v${TRIVY_VERSION}" \
    && test "$(go mod download -json "github.com/aquasecurity/trivy@v${TRIVY_VERSION}" | awk '$1 == "\"Sum\":" {gsub(/[",]/, "", $2); print $2}')" = "${TRIVY_MODULE_SUM}" \
    && scanner_dir="$(go env GOPATH)/pkg/mod/github.com/aquasecurity/trivy@v${TRIVY_VERSION}" \
    && chmod -R u+w "${scanner_dir}" \
    && cd "${scanner_dir}" \
    && go mod edit -require="golang.org/x/net@${SCANNER_X_NET_VERSION}" \
    && go build -mod=mod -ldflags="-X github.com/aquasecurity/trivy/pkg/version/app.ver=${TRIVY_VERSION}" -o /out/trivy ./cmd/trivy \
    && test "$(go version -m /out/trivy | awk '$2 == "golang.org/x/net" {print $3}')" = "${SCANNER_X_NET_VERSION}" \
    && /out/trivy --version

FROM ${BASE_IMAGE_REGISTRY}/library/python@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c AS tools

ARG OPENGREP_VERSION=v1.30.1
ARG OPENGREP_SHA256=d3195b9d8d5ae93179f6aa5f5daaba6a920a5a09d38c5d5ae5e60924050210c4

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /download
RUN set -eu \
    && mkdir -p /opt/scanners/bin \
    && wget -q -O opengrep "https://github.com/opengrep/opengrep/releases/download/${OPENGREP_VERSION}/opengrep_manylinux_x86" \
    && echo "${OPENGREP_SHA256}  opengrep" | sha256sum -c - \
    && install -m 0755 opengrep /opt/scanners/bin/opengrep
COPY --from=scanner-builder /out/ /opt/scanners/bin/

FROM ${BASE_IMAGE_REGISTRY}/library/python@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
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

FROM ${BASE_IMAGE_REGISTRY}/library/python@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c AS base

# The sandbox binds the proof interpreter at a fixed path and exposes no /etc/ld.so.cache, so
# libpython must sit on the loader's default search path.
RUN apt-get update \
    && apt-get install -y --no-install-recommends bubblewrap ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes pip \
    && ln -s /usr/local/lib/libpython3.13.so.1.0 /usr/lib/x86_64-linux-gnu/libpython3.13.so.1.0

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
ENTRYPOINT ["fdai-scan-runner"]

FROM ${BASE_IMAGE_REGISTRY}/library/python@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c AS dotnet

ARG DOTNET_SDK_VERSION=10.0.401
ARG DOTNET_SDK_SHA512=51c8b999af9e8dd9998c9edc5944e19a90788862068acd38694e098889054ce8c23d4f0c5cccfa16bf187d044562359e5ee69a9f8ad0bbe913ba90311fbce25b

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates wget \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /download
RUN set -eu \
    && wget -q -O dotnet.tar.gz "https://builds.dotnet.microsoft.com/dotnet/Sdk/${DOTNET_SDK_VERSION}/dotnet-sdk-${DOTNET_SDK_VERSION}-linux-x64.tar.gz" \
    && echo "${DOTNET_SDK_SHA512}  dotnet.tar.gz" | sha512sum -c - \
    && mkdir -p /usr/lib/dotnet \
    && tar -xzf dotnet.tar.gz -C /usr/lib/dotnet

# The proof-lane image. Driven toolchains must resolve under /usr, /bin, or /lib, the sandbox's
# read-only system mounts, so the .NET SDK lives in /usr/lib/dotnet.
FROM base AS prover

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        g++ gcc libc6-dev libicu76 nodejs openjdk-21-jdk-headless \
    && rm -rf /var/lib/apt/lists/*
COPY --from=dotnet /usr/lib/dotnet/ /usr/lib/dotnet/
RUN ln -s /usr/lib/dotnet/dotnet /usr/bin/dotnet
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1
USER 65532
RUN opengrep --version \
    && gitleaks version \
    && osv-scanner --version \
    && trivy --version \
    && bwrap --version \
    && node --version \
    && gcc --version \
    && javac -version \
    && dotnet --list-sdks \
    && python -m fdai.delivery.code_security_cli evaluate > /dev/null

# The default scan runner image: every scanner and the Python proof lane, without the other
# proof toolchains.
FROM base AS runtime

RUN opengrep --version \
    && gitleaks version \
    && osv-scanner --version \
    && trivy --version \
    && bwrap --version \
    && python -m fdai.delivery.code_security_cli evaluate > /dev/null
