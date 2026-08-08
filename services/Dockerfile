# Five independently releasable FDAI service images.
#
# Each final target installs its owned service distribution as a wheel and
# starts only that distribution's console entry point. Runtime images do not
# carry the repository source tree or a PYTHONPATH compatibility path.

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

FROM ${BASE_IMAGE_REGISTRY}/library/python@sha256:9d7f287598e1a5a978c015ee176d8216435aaf335ed69ac3c38dd1bbb10e8d64 AS service-build-base

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.11.32

WORKDIR /app
COPY pyproject.toml uv.lock LICENSE README.md ./
COPY evaluation-sdk/ ./evaluation-sdk/
COPY benchmarks/sregym/pyproject.toml ./benchmarks/sregym/pyproject.toml
COPY benchmarks/cybergym/pyproject.toml ./benchmarks/cybergym/pyproject.toml
COPY extensions/code-assurance/pyproject.toml ./extensions/code-assurance/pyproject.toml
COPY service-contracts/ ./service-contracts/
COPY services/ ./services/
COPY src/ ./src/

FROM service-build-base AS core-control-plane-builder
RUN uv build --wheel --package fdai-core-control-plane --out-dir /wheels \
    && uv sync --frozen --package fdai-core-control-plane --no-dev --no-editable --no-install-package fdai \
    && uv pip install --python /app/.venv/bin/python --reinstall --no-deps /wheels/fdai_core_control_plane-*.whl \
    && test -x /app/.venv/bin/fdai-core-control-plane

FROM service-build-base AS operator-service-builder
RUN uv build --wheel --package fdai-operator-service --out-dir /wheels \
    && uv sync --frozen --package fdai-operator-service --no-dev --no-editable \
    && uv pip install --python /app/.venv/bin/python --reinstall --no-deps /wheels/fdai_operator_service-*.whl \
    && test -x /app/.venv/bin/fdai-operator-service

FROM service-build-base AS document-ingestion-api-builder
RUN uv build --wheel --package fdai-document-ingestion-api --out-dir /wheels \
    && uv sync --frozen --package fdai-document-ingestion-api --no-dev --no-editable \
    && uv pip install --python /app/.venv/bin/python --reinstall --no-deps /wheels/fdai_document_ingestion_api-*.whl \
    && test -x /app/.venv/bin/fdai-document-ingestion-api

FROM service-build-base AS document-processing-worker-builder
RUN uv build --wheel --package fdai-document-processing-worker --out-dir /wheels \
    && uv sync --frozen --package fdai-document-processing-worker --no-dev --no-editable \
    && uv pip install --python /app/.venv/bin/python --reinstall --no-deps /wheels/fdai_document_processing_worker-*.whl \
    && test -x /app/.venv/bin/fdai-document-processing-worker

FROM service-build-base AS isolated-executor-builder
RUN uv build --wheel --package fdai-isolated-executor-service --out-dir /wheels \
    && uv sync --frozen --package fdai-isolated-executor-service --no-dev --no-editable \
    && uv pip install --python /app/.venv/bin/python --reinstall --no-deps /wheels/fdai_isolated_executor_service-*.whl \
    && test -x /app/.venv/bin/fdai-isolated-executor-service

FROM ${BASE_IMAGE_REGISTRY}/library/python@sha256:9d7f287598e1a5a978c015ee176d8216435aaf335ed69ac3c38dd1bbb10e8d64 AS runtime-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AZURE_MCP_COLLECT_TELEMETRY=false \
    HOME=/tmp/fdai \
    PATH="/app/.venv/bin:${PATH}" \
    XDG_CACHE_HOME=/tmp/fdai/.cache

WORKDIR /app

FROM runtime-base AS core-control-plane
COPY --from=core-control-plane-builder --chown=65532:65532 /app/.venv /app/.venv
COPY --from=opa-builder /go/bin/opa /usr/local/bin/opa
COPY --chown=65532:65532 rule-catalog/ /app/rule-catalog/
COPY --chown=65532:65532 policies/ /app/policies/
COPY --chown=65532:65532 config/ /app/config/
COPY --chown=65532:65532 docs/internals/sregym-absorption-ledger.json /app/docs/internals/sregym-absorption-ledger.json
COPY --chown=65532:65532 services/assets/resolved-models.json /app/resolved-models.json
COPY --chown=65532:65532 tests/scenarios/ /app/tests/scenarios/
COPY --chown=65532:65532 alembic/ /app/alembic/
COPY --chown=65532:65532 alembic.ini /app/alembic.ini
USER 65532
RUN test -x /app/.venv/bin/fdai-core-control-plane
ENTRYPOINT ["fdai-core-control-plane"]

FROM runtime-base AS operator-service
COPY --from=operator-service-builder --chown=65532:65532 /app/.venv /app/.venv
USER 65532
RUN test -x /app/.venv/bin/fdai-operator-service
ENTRYPOINT ["fdai-operator-service"]

FROM runtime-base AS document-ingestion-api
COPY --from=document-ingestion-api-builder --chown=65532:65532 /app/.venv /app/.venv
COPY --chown=65532:65532 config/agent-stewardship.yaml /app/config/agent-stewardship.yaml
USER 65532
RUN test -x /app/.venv/bin/fdai-document-ingestion-api
ENTRYPOINT ["fdai-document-ingestion-api"]

FROM runtime-base AS document-processing-worker
COPY --from=document-processing-worker-builder --chown=65532:65532 /app/.venv /app/.venv
USER 65532
RUN test -x /app/.venv/bin/fdai-document-processing-worker
ENTRYPOINT ["fdai-document-processing-worker"]

FROM runtime-base AS isolated-executor
COPY --from=isolated-executor-builder --chown=65532:65532 /app/.venv /app/.venv
USER 65532
RUN test -x /app/.venv/bin/fdai-isolated-executor-service
ENTRYPOINT ["fdai-isolated-executor-service"]
