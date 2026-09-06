# Core Control Plane distribution profile with the reviewed Cost Governance package installed.

ARG BASE_IMAGE_REGISTRY=docker.io

FROM ${BASE_IMAGE_REGISTRY}/library/golang@sha256:640a234f4bea3e399c056b7b8f9c667c4939befae8db2f14e9785e16eccd4205 AS opa-builder

ARG OPA_VERSION=v1.18.2
ARG OPA_GRPC_VERSION=v1.83.1
ARG OPA_X_CRYPTO_VERSION=v0.55.0
ARG OPA_X_TEXT_VERSION=v0.41.0
ARG OPA_ORAS_VERSION=v2.6.2
RUN /usr/local/go/bin/go mod download "github.com/open-policy-agent/opa@${OPA_VERSION}" \
    && opa_dir="$(/usr/local/go/bin/go env GOPATH)/pkg/mod/github.com/open-policy-agent/opa@${OPA_VERSION}" \
    && chmod -R u+w "${opa_dir}" \
    && cd "${opa_dir}" \
    && /usr/local/go/bin/go mod edit -require="google.golang.org/grpc@${OPA_GRPC_VERSION}" \
    && /usr/local/go/bin/go mod edit -require="golang.org/x/crypto@${OPA_X_CRYPTO_VERSION}" \
    && /usr/local/go/bin/go mod edit -require="golang.org/x/text@${OPA_X_TEXT_VERSION}" \
    && /usr/local/go/bin/go mod edit -require="oras.land/oras-go/v2@${OPA_ORAS_VERSION}" \
    && CGO_ENABLED=0 /usr/local/go/bin/go build -mod=mod -o /go/bin/opa . \
    && test "$(/usr/local/go/bin/go version -m /go/bin/opa | awk '$2 == "google.golang.org/grpc" {print $3}')" = "${OPA_GRPC_VERSION}" \
    && test "$(/usr/local/go/bin/go version -m /go/bin/opa | awk '$2 == "golang.org/x/crypto" {print $3}')" = "${OPA_X_CRYPTO_VERSION}" \
    && test "$(/usr/local/go/bin/go version -m /go/bin/opa | awk '$2 == "golang.org/x/text" {print $3}')" = "${OPA_X_TEXT_VERSION}" \
    && test "$(/usr/local/go/bin/go version -m /go/bin/opa | awk '$2 == "oras.land/oras-go/v2" {print $3}')" = "${OPA_ORAS_VERSION}" \
    && /go/bin/opa version

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
COPY extensions/cost-governance/ ./extensions/cost-governance/
COPY services/operator-service/pyproject.toml ./services/operator-service/pyproject.toml
COPY services/document-ingestion-api/pyproject.toml ./services/document-ingestion-api/pyproject.toml
COPY services/document-processing-worker/pyproject.toml ./services/document-processing-worker/pyproject.toml
COPY services/isolated-executor/pyproject.toml ./services/isolated-executor/pyproject.toml
COPY packages/github-app-auth/ ./packages/github-app-auth/
COPY packages/service-contracts/ ./packages/service-contracts/
COPY services/core-control-plane/ ./services/core-control-plane/
RUN uv build --wheel --package fdai-github-app-auth --out-dir /wheels \
    && uv build --wheel --package fdai-service-contracts --out-dir /wheels \
    && uv build --wheel --package fdai-core-control-plane --out-dir /wheels \
    && uv build --wheel --package fdai-cost-governance --out-dir /wheels \
    && uv sync --frozen --package fdai-cost-governance --no-dev --no-editable \
        --no-install-package fdai \
        --no-install-package fdai-github-app-auth \
        --no-install-package fdai-service-contracts \
        --no-install-package fdai-core-control-plane \
        --no-install-package fdai-cost-governance \
    && uv pip install --python /app/.venv/bin/python --no-deps \
        /wheels/fdai_github_app_auth-*.whl \
        /wheels/fdai_service_contracts-*.whl \
        /wheels/fdai_core_control_plane-*.whl \
        /wheels/fdai_cost_governance-*.whl \
    && /app/.venv/bin/python -c "from fdai_cost_governance import load_package_resources; assert len(load_package_resources()) == 38" \
    && test -x /app/.venv/bin/fdai-core-control-plane \
    && test "$(head -n 1 /app/.venv/bin/fdai-core-control-plane)" = "#!/app/.venv/bin/python"

FROM ${BASE_IMAGE_REGISTRY}/library/python@sha256:540c7d91f98ff6880174c40e99067bf5941eb54d818a7a5e094d188b196a934d AS runtime

ARG OPENSSL_LIBS_VERSION=3.5.8-r0
ARG SQLITE_LIBS_VERSION=3.53.4-r0
ARG UTIL_LINUX_LIBS_VERSION=2.42.3-r1
RUN apk add --no-cache --upgrade \
        "libcrypto3=${OPENSSL_LIBS_VERSION}" \
        "libssl3=${OPENSSL_LIBS_VERSION}" \
    && apk add --no-cache --repository https://dl-cdn.alpinelinux.org/alpine/edge/main \
        "libuuid=${UTIL_LINUX_LIBS_VERSION}" \
        "sqlite-libs=${SQLITE_LIBS_VERSION}" \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip \
        /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
    && mkdir -p /home/fdai/.cache \
    && chown -R 65532:65532 /home/fdai

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AZURE_MCP_COLLECT_TELEMETRY=false \
    FDAI_HEALTH_PORT=8000 \
    HOME=/home/fdai \
    PATH="/app/.venv/bin:${PATH}" \
    XDG_CACHE_HOME=/home/fdai/.cache

WORKDIR /app
COPY --from=builder --chown=65532:65532 /app/.venv /app/.venv
COPY --from=opa-builder /go/bin/opa /usr/local/bin/opa
COPY --chown=65532:65532 rule-catalog/ /app/rule-catalog/
COPY --chown=65532:65532 policies/ /app/policies/
COPY --chown=65532:65532 config/ /app/config/
COPY --chown=65532:65532 docs/internals/sregym-absorption-ledger.json /app/docs/internals/sregym-absorption-ledger.json
COPY --chown=65532:65532 services/assets/resolved-models.json /app/resolved-models.json
COPY --chown=65532:65532 services/core-control-plane/tests/scenarios/ /app/services/core-control-plane/tests/scenarios/
COPY --chown=65532:65532 alembic/ /app/alembic/
COPY --chown=65532:65532 alembic.ini /app/alembic.ini
COPY --chown=65532:65532 scripts/deployment/local/materialize-authoritative-catalogs.py /app/scripts/deployment/local/materialize-authoritative-catalogs.py
USER 65532
RUN test -x /app/.venv/bin/fdai-core-control-plane \
    && /app/.venv/bin/python -c "from fdai_cost_governance import load_resource_manifest; assert load_resource_manifest()['candidate_state'] == 'inert'"
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/live',timeout=2).read()"]
ENTRYPOINT ["fdai-core-control-plane"]
