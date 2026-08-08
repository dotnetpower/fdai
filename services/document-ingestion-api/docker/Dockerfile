# Document Ingestion API image built from its owned distribution and shared contracts.

ARG BASE_IMAGE_REGISTRY=docker.io

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
COPY services/core-control-plane/pyproject.toml ./services/core-control-plane/pyproject.toml
COPY services/operator-service/pyproject.toml ./services/operator-service/pyproject.toml
COPY services/document-processing-worker/pyproject.toml ./services/document-processing-worker/pyproject.toml
COPY services/isolated-executor/pyproject.toml ./services/isolated-executor/pyproject.toml
COPY packages/service-contracts/ ./packages/service-contracts/
COPY services/document-ingestion-api/ ./services/document-ingestion-api/
RUN uv build --wheel --package fdai-service-contracts --out-dir /wheels \
    && uv build --wheel --package fdai-document-ingestion-api --out-dir /wheels \
    && uv sync --frozen --package fdai-document-ingestion-api --no-dev --no-editable \
        --no-install-package fdai \
        --no-install-package fdai-service-contracts \
        --no-install-package fdai-document-ingestion-api \
    && uv pip install --python /app/.venv/bin/python --no-deps \
        /wheels/fdai_service_contracts-*.whl \
        /wheels/fdai_document_ingestion_api-*.whl \
    && test -x /app/.venv/bin/fdai-document-ingestion-api \
    && test "$(head -n 1 /app/.venv/bin/fdai-document-ingestion-api)" = "#!/app/.venv/bin/python"

FROM ${BASE_IMAGE_REGISTRY}/library/python@sha256:9fdbf2e3e82628351513560b121e2ee6ce31cac212be9e070c5a5e2769fb5e76 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AZURE_MCP_COLLECT_TELEMETRY=false \
    HOME=/tmp/fdai \
    PATH="/app/.venv/bin:${PATH}" \
    XDG_CACHE_HOME=/tmp/fdai/.cache

WORKDIR /app
COPY --from=builder --chown=65532:65532 /app/.venv /app/.venv
COPY --chown=65532:65532 config/agent-stewardship.yaml /app/config/agent-stewardship.yaml
USER 65532
RUN test -x /app/.venv/bin/fdai-document-ingestion-api
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=2).read()"]
ENTRYPOINT ["fdai-document-ingestion-api"]
