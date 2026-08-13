# Core Control Plane image built from its owned distribution and shared contracts.

ARG BASE_IMAGE_REGISTRY=docker.io

FROM ${BASE_IMAGE_REGISTRY}/library/golang@sha256:0178a641fbb4858c5f1b48e34bdaabe0350a330a1b1149aabd498d0699ff5fb2 AS opa-builder

ARG OPA_VERSION=v1.18.2
ARG OPA_GRPC_VERSION=v1.82.1
ARG OPA_X_TEXT_VERSION=v0.39.0
RUN /usr/local/go/bin/go mod download "github.com/open-policy-agent/opa@${OPA_VERSION}" \
    && opa_dir="$(/usr/local/go/bin/go env GOPATH)/pkg/mod/github.com/open-policy-agent/opa@${OPA_VERSION}" \
    && chmod -R u+w "${opa_dir}" \
    && cd "${opa_dir}" \
    && /usr/local/go/bin/go mod edit -require="google.golang.org/grpc@${OPA_GRPC_VERSION}" \
    && /usr/local/go/bin/go mod edit -require="golang.org/x/text@${OPA_X_TEXT_VERSION}" \
    && CGO_ENABLED=0 /usr/local/go/bin/go build -mod=mod -o /go/bin/opa . \
    && test "$(/usr/local/go/bin/go version -m /go/bin/opa | awk '$2 == "google.golang.org/grpc" {print $3}')" = "${OPA_GRPC_VERSION}" \
    && test "$(/usr/local/go/bin/go version -m /go/bin/opa | awk '$2 == "golang.org/x/text" {print $3}')" = "${OPA_X_TEXT_VERSION}" \
    && /go/bin/opa version

FROM ${BASE_IMAGE_REGISTRY}/library/python@sha256:9fdbf2e3e82628351513560b121e2ee6ce31cac212be9e070c5a5e2769fb5e76 AS builder

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
COPY services/operator-service/pyproject.toml ./services/operator-service/pyproject.toml
COPY services/document-ingestion-api/pyproject.toml ./services/document-ingestion-api/pyproject.toml
COPY services/document-processing-worker/pyproject.toml ./services/document-processing-worker/pyproject.toml
COPY services/isolated-executor/pyproject.toml ./services/isolated-executor/pyproject.toml
COPY packages/service-contracts/ ./packages/service-contracts/
COPY services/core-control-plane/ ./services/core-control-plane/
RUN uv build --wheel --package fdai-service-contracts --out-dir /wheels \
    && uv build --wheel --package fdai-core-control-plane --out-dir /wheels \
    && uv sync --frozen --package fdai-core-control-plane --no-dev --no-editable \
        --no-install-package fdai \
        --no-install-package fdai-service-contracts \
        --no-install-package fdai-core-control-plane \
    && uv pip install --python /app/.venv/bin/python --no-deps \
        /wheels/fdai_service_contracts-*.whl \
        /wheels/fdai_core_control_plane-*.whl \
    && test -x /app/.venv/bin/fdai-core-control-plane \
    && test "$(head -n 1 /app/.venv/bin/fdai-core-control-plane)" = "#!/app/.venv/bin/python"

FROM ${BASE_IMAGE_REGISTRY}/library/python@sha256:9fdbf2e3e82628351513560b121e2ee6ce31cac212be9e070c5a5e2769fb5e76 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AZURE_MCP_COLLECT_TELEMETRY=false \
    FDAI_HEALTH_PORT=8000 \
    HOME=/tmp/fdai \
    PATH="/app/.venv/bin:${PATH}" \
    XDG_CACHE_HOME=/tmp/fdai/.cache

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
RUN test -x /app/.venv/bin/fdai-core-control-plane
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/live',timeout=2).read()"]
ENTRYPOINT ["fdai-core-control-plane"]
