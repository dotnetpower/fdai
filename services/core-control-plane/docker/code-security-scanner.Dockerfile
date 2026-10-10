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
ARG GITLEAKS_ARCHIVES_VERSION=v0.1.5
RUN go mod download "github.com/zricethezav/gitleaks/v8@v${GITLEAKS_VERSION}" \
    && test "$(go mod download -json "github.com/zricethezav/gitleaks/v8@v${GITLEAKS_VERSION}" | awk '$1 == "\"Sum\":" {gsub(/[",]/, "", $2); print $2}')" = "${GITLEAKS_MODULE_SUM}" \
    && scanner_dir="$(go env GOPATH)/pkg/mod/github.com/zricethezav/gitleaks/v8@v${GITLEAKS_VERSION}" \
    && chmod -R u+w "${scanner_dir}" \
    && cd "${scanner_dir}" \
    && go mod edit -require="golang.org/x/crypto@${SCANNER_X_CRYPTO_VERSION}" \
    && go mod edit -require="golang.org/x/text@${SCANNER_X_TEXT_VERSION}" \
    && go mod edit -require="github.com/nwaples/rardecode/v2@${GITLEAKS_RAR_VERSION}" \
    && go mod edit -require="github.com/ulikunitz/xz@${GITLEAKS_XZ_VERSION}" \
    && go mod edit -require="github.com/mholt/archives@${GITLEAKS_ARCHIVES_VERSION}" \
    && go build -mod=mod -ldflags="-X github.com/zricethezav/gitleaks/v8/version.Version=${GITLEAKS_VERSION}" -o /out/gitleaks . \
    && test "$(go version -m /out/gitleaks | awk '$2 == "golang.org/x/crypto" {print $3}')" = "${SCANNER_X_CRYPTO_VERSION}" \
    && test "$(go version -m /out/gitleaks | awk '$2 == "golang.org/x/text" {print $3}')" = "${SCANNER_X_TEXT_VERSION}" \
    && test "$(go version -m /out/gitleaks | awk '$2 == "github.com/nwaples/rardecode/v2" {print $3}')" = "${GITLEAKS_RAR_VERSION}" \
    && test "$(go version -m /out/gitleaks | awk '$2 == "github.com/ulikunitz/xz" {print $3}')" = "${GITLEAKS_XZ_VERSION}" \
    && test "$(go version -m /out/gitleaks | awk '$2 == "github.com/mholt/archives" {print $3}')" = "${GITLEAKS_ARCHIVES_VERSION}" \
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

FROM mcr.microsoft.com/azurelinux/base/core@sha256:a66ca12ae8c8c464e00cc6cc7f9deff5d2dfcd0f1314ba5dac22034ef171d3ae AS platform

RUN timeout --signal=TERM --kill-after=10 180s tdnf install -y ca-certificates

FROM platform AS python-builder

ARG PYTHON_VERSION=3.13.16
ARG PYTHON_SHA256=f4b1bfb3c79b5bb11b8d228a12504163b4c0dab4d679828d8f5f26b6cb6ab35d
ENV TMPDIR=/build/scratch
RUN mkdir -p /build/scratch \
    && timeout --signal=TERM --kill-after=10 180s tdnf install -y \
        gcc gcc-c++ binutils glibc-devel kernel-headers gawk make tar \
        openssl-devel zlib-devel libffi-devel sqlite-devel xz-devel bzip2-devel \
        expat-devel readline-devel ncurses-devel gdbm-devel util-linux-devel
WORKDIR /build
RUN curl --fail --location --retry 0 --connect-timeout 30 --max-time 180 \
        -o Python.tar.xz "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tar.xz" \
    && echo "${PYTHON_SHA256}  Python.tar.xz" | sha256sum -c - \
    && tar -xf Python.tar.xz \
    && timeout --signal=TERM --kill-after=10 900s sh -ec '\
        cd "Python-${PYTHON_VERSION}"; \
        ./configure --prefix=/usr/local --enable-shared --with-system-expat \
            --with-openssl=/usr --with-ensurepip=no --enable-loadable-sqlite-extensions; \
        make -j4; \
        make -j4 install COMPILEALL_OPTS=-j4' \
    && ln -s python3.13 /usr/local/bin/python \
    && ln -s /usr/local/lib/libpython3.13.so.1.0 /usr/lib/libpython3.13.so.1.0

FROM platform AS python-runtime
RUN timeout --signal=TERM --kill-after=10 180s tdnf install -y \
        bubblewrap git openssl-libs expat-libs sqlite-libs libffi bzip2-libs xz-libs \
        zlib readline ncurses-libs gdbm util-linux-libs libstdc++
COPY --from=python-builder /usr/local/ /usr/local/
# Bubblewrap exposes /usr but no /etc/ld.so.cache; use the loader's default library directory.
RUN ln -s /usr/local/lib/libpython3.13.so.1.0 /usr/lib/libpython3.13.so.1.0 \
    && /lib64/ld-linux-x86-64.so.2 --inhibit-cache /usr/local/bin/python3.13 --version \
    && python -c 'import ssl, sqlite3, ctypes, bz2, lzma, zlib, decimal, venv, pyexpat, readline, curses, dbm.gnu, uuid; import importlib.util; assert importlib.util.find_spec("pip") is None'

FROM ghcr.io/astral-sh/uv@sha256:0d127b3a7049b879a6e18a79c7f33fea59aa83c226464248f89cfb716a6b96f5 AS uv

FROM platform AS tools

ARG OPENGREP_VERSION=v1.30.1
ARG OPENGREP_SHA256=d3195b9d8d5ae93179f6aa5f5daaba6a920a5a09d38c5d5ae5e60924050210c4

WORKDIR /download
RUN set -eu \
    && mkdir -p /opt/scanners/bin \
    && curl --fail --location --retry 0 --connect-timeout 30 --max-time 180 \
        -o opengrep "https://github.com/opengrep/opengrep/releases/download/${OPENGREP_VERSION}/opengrep_manylinux_x86" \
    && echo "${OPENGREP_SHA256}  opengrep" | sha256sum -c - \
    && install -m 0755 opengrep /opt/scanners/bin/opengrep
COPY --from=scanner-builder /out/ /opt/scanners/bin/

FROM python-builder AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=0 \
    UV_CONCURRENT_BUILDS=4 \
    UV_CONCURRENT_INSTALLS=4 \
    UV_CONCURRENT_DOWNLOADS=4 \
    UV_HTTP_RETRIES=0 \
    UV_HTTP_TIMEOUT=30 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY --from=uv /uv /usr/local/bin/uv
RUN test "$(uv --version | cut -d ' ' -f 1-2)" = "uv 0.11.32"

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
RUN timeout --signal=TERM --kill-after=10 180s uv export --frozen --all-packages --all-extras \
        --no-emit-workspace --output-file /build/build-constraints.txt \
    && timeout --signal=TERM --kill-after=10 180s uv build --build-constraints /build/build-constraints.txt --require-hashes --wheel --package fdai-github-app-auth --out-dir /wheels \
    && timeout --signal=TERM --kill-after=10 180s uv build --build-constraints /build/build-constraints.txt --require-hashes --wheel --package fdai-service-contracts --out-dir /wheels \
    && timeout --signal=TERM --kill-after=10 180s uv build --build-constraints /build/build-constraints.txt --require-hashes --wheel --package fdai-runtime-diagnostics --out-dir /wheels \
    && timeout --signal=TERM --kill-after=10 180s uv build --build-constraints /build/build-constraints.txt --require-hashes --wheel --package fdai-core-control-plane --out-dir /wheels \
    && timeout --signal=TERM --kill-after=10 180s uv sync --frozen --package fdai-core-control-plane --no-dev --no-editable \
        --no-install-package fdai \
        --no-install-package fdai-github-app-auth \
        --no-install-package fdai-service-contracts \
        --no-install-package fdai-runtime-diagnostics \
        --no-install-package fdai-core-control-plane \
    && timeout --signal=TERM --kill-after=10 180s uv pip install --python /app/.venv/bin/python --no-deps \
        /wheels/fdai_github_app_auth-*.whl \
        /wheels/fdai_service_contracts-*.whl \
        /wheels/fdai_runtime_diagnostics-*.whl \
        /wheels/fdai_core_control_plane-*.whl \
    && timeout --signal=TERM --kill-after=10 180s /app/.venv/bin/python -m compileall -q -j4 /app/.venv/lib/python3.13

FROM python-runtime AS base

ARG FDAI_CODE_SECURITY_BUILD_INPUT_DIGEST=unbound
LABEL org.fdai.code-security.build-input-digest="${FDAI_CODE_SECURITY_BUILD_INPUT_DIGEST}"

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

FROM platform AS dotnet

ARG DOTNET_SDK_VERSION=10.0.401
ARG DOTNET_SDK_SHA512=51c8b999af9e8dd9998c9edc5944e19a90788862068acd38694e098889054ce8c23d4f0c5cccfa16bf187d044562359e5ee69a9f8ad0bbe913ba90311fbce25b

RUN timeout --signal=TERM --kill-after=10 180s tdnf install -y tar
WORKDIR /download
RUN set -eu \
    && curl --fail --location --retry 0 --connect-timeout 30 --max-time 180 \
        -o dotnet.tar.gz "https://builds.dotnet.microsoft.com/dotnet/Sdk/${DOTNET_SDK_VERSION}/dotnet-sdk-${DOTNET_SDK_VERSION}-linux-x64.tar.gz" \
    && echo "${DOTNET_SDK_SHA512}  dotnet.tar.gz" | sha512sum -c - \
    && mkdir -p /usr/lib/dotnet \
    && tar -xzf dotnet.tar.gz -C /usr/lib/dotnet

FROM mcr.microsoft.com/openjdk/jdk@sha256:673bed7263ec02e4cd33fcaf9b1d0de8869f657fb36b5cec1b051d2ef4ba2bec AS jdk

RUN sha256sum /usr/lib/jvm/msopenjdk-21/bin/java /usr/lib/jvm/msopenjdk-21/bin/javac \
        /usr/lib/jvm/msopenjdk-21/lib/modules > /jdk-content.sha256

FROM python-runtime AS node

ARG NODE_VERSION=24.21.0
ARG NODE_SHA256=fd8e59d5a511510f6a298afb548f18c7d2b1be404d8b4a27d94fbe49f56cb2d6
ARG NODE_UNDICI_VERSION=7.29.1
RUN timeout --signal=TERM --kill-after=10 180s tdnf install -y tar
WORKDIR /download
COPY services/core-control-plane/docker/node-runtime-sbom.py /download/node-runtime-sbom.py
RUN set -eu \
    && curl --fail --location --retry 0 --connect-timeout 30 --max-time 180 \
        -o node.tar.xz "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
    && echo "${NODE_SHA256}  node.tar.xz" | sha256sum -c - \
    && mkdir -p /usr/share/licenses/nodejs \
    && tar -xJf node.tar.xz -C /usr --strip-components=1 "node-v${NODE_VERSION}-linux-x64/bin/node" \
    && tar -xJOf node.tar.xz "node-v${NODE_VERSION}-linux-x64/LICENSE" > /usr/share/licenses/nodejs/LICENSE \
    && test "$(/usr/bin/node --version)" = "v${NODE_VERSION}" \
    && test "$(/usr/bin/node -p process.versions.undici)" = "${NODE_UNDICI_VERSION}" \
    && /usr/bin/node -p 'JSON.stringify(process.versions)' > /download/node-versions.json \
    && mkdir -p /usr/share/fdai \
    && python /download/node-runtime-sbom.py --versions /download/node-versions.json \
        --binary /usr/bin/node --archive-sha256 "${NODE_SHA256}" \
        --output /usr/share/fdai/node-runtime.cdx.json

# The JavaScript profile also retains the Python proof lane and every scanner.
FROM base AS prover-javascript

LABEL org.fdai.code-security.proof-profile="javascript"
COPY --from=node /usr/bin/node /usr/bin/node
COPY --from=node /usr/share/licenses/nodejs/ /usr/share/licenses/nodejs/
COPY --from=node /usr/share/fdai/node-runtime.cdx.json /usr/share/fdai/node-runtime.cdx.json
RUN opengrep --version \
    && gitleaks version \
    && osv-scanner --version \
    && trivy --version \
    && bwrap --version \
    && node --version \
    && python -m fdai.delivery.code_security_cli evaluate > /dev/null

# The full proof lane keeps every toolchain under the sandbox's read-only system mounts.
FROM prover-javascript AS prover

LABEL org.fdai.code-security.proof-profile="all"
USER root
COPY --from=jdk /jdk-content.sha256 /tmp/jdk-content.sha256
# Package installation retains the RPM inventory; pinned-image content rejects binary drift.
RUN timeout --signal=TERM --kill-after=10 180s tdnf install -y \
        gcc gcc-c++ binutils glibc-devel kernel-headers icu msopenjdk-21-21.0.12.1-1 \
    && test "$(rpm -q msopenjdk-21)" = "msopenjdk-21-21.0.12.1-1.x86_64" \
    && sha256sum -c /tmp/jdk-content.sha256 \
    && rm /tmp/jdk-content.sha256
COPY --from=dotnet /usr/lib/dotnet/ /usr/lib/dotnet/
RUN ln -s /usr/lib/dotnet/dotnet /usr/bin/dotnet \
    && test "$(readlink -f /usr/bin/java)" = "/usr/lib/jvm/msopenjdk-21/bin/java" \
    && test "$(readlink -f /usr/bin/javac)" = "/usr/lib/jvm/msopenjdk-21/bin/javac"
ENV JAVA_HOME=/usr/lib/jvm/msopenjdk-21 \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
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
