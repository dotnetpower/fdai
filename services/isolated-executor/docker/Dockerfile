# Isolated Executor image built from its owned distribution and shared contracts.

ARG BASE_IMAGE_REGISTRY=docker.io

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
COPY services/core-control-plane/pyproject.toml ./services/core-control-plane/pyproject.toml
COPY services/operator-service/pyproject.toml ./services/operator-service/pyproject.toml
COPY services/document-ingestion-api/pyproject.toml ./services/document-ingestion-api/pyproject.toml
COPY services/document-processing-worker/pyproject.toml ./services/document-processing-worker/pyproject.toml
COPY packages/service-contracts/ ./packages/service-contracts/
COPY services/isolated-executor/ ./services/isolated-executor/
RUN uv build --wheel --package fdai-service-contracts --out-dir /wheels \
    && uv build --wheel --package fdai-isolated-executor-service --out-dir /wheels \
    && uv sync --frozen --package fdai-isolated-executor-service --no-dev --no-editable \
        --no-install-package fdai \
        --no-install-package fdai-service-contracts \
        --no-install-package fdai-isolated-executor-service \
    && uv pip install --python /app/.venv/bin/python --no-deps \
        /wheels/fdai_service_contracts-*.whl \
        /wheels/fdai_isolated_executor_service-*.whl \
    && test -x /app/.venv/bin/fdai-isolated-executor-service \
    && test "$(head -n 1 /app/.venv/bin/fdai-isolated-executor-service)" = "#!/app/.venv/bin/python"

FROM ${BASE_IMAGE_REGISTRY}/library/python@sha256:540c7d91f98ff6880174c40e99067bf5941eb54d818a7a5e094d188b196a934d AS runtime

ARG OPENSSL_LIBS_VERSION=3.5.8-r0
ARG SQLITE_LIBS_VERSION=3.53.4-r0
RUN apk add --no-cache --upgrade \
        "libcrypto3=${OPENSSL_LIBS_VERSION}" \
        "libssl3=${OPENSSL_LIBS_VERSION}" \
    && apk add --no-cache --repository https://dl-cdn.alpinelinux.org/alpine/edge/main \
        "sqlite-libs=${SQLITE_LIBS_VERSION}" \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip \
        /usr/local/lib/python3.13/site-packages/pip-*.dist-info

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AZURE_MCP_COLLECT_TELEMETRY=false \
    HOME=/tmp/fdai \
    PATH="/app/.venv/bin:${PATH}" \
    XDG_CACHE_HOME=/tmp/fdai/.cache

WORKDIR /app
COPY --from=builder --chown=65532:65532 /app/.venv /app/.venv
USER 65532
RUN test -x /app/.venv/bin/fdai-isolated-executor-service
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"FDAI_ISOLATED_EXECUTOR_HEALTH_PORT\",\"8000\")}/live',timeout=2).read()"]
ENTRYPOINT ["fdai-isolated-executor-service"]
