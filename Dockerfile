# Minimal runtime image for the core control plane.
#
# Multi-stage:
#   1. digest-pinned Python 3.13 Debian slim builder + uv resolves the frozen lockfile.
#   2. the same digest starts a clean runtime that receives only the venv and data.
#
# Notes:
# - The frozen runtime includes the ADLS Gen2 async SDK used by the opt-in
#   production ingestion gateway. Azure adapters still initialize only in
#   their production composition paths; local-fake mode makes no cloud call.
# - Runs as a numeric nonroot user (uid 65532). Container Apps enforces read-only fs
#   on the app volume by default; only the writable OTel/temp mounts are
#   used.
# - BASE_IMAGE_REGISTRY lets a disconnected tenant build from an internal
#   registry mirror (`--build-arg BASE_IMAGE_REGISTRY=myacr.azurecr.io`) without
#   editing this file. The digest pin stays in place, so a mirror that serves
#   different content fails the pull instead of shipping unreviewed bytes.

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

FROM ${BASE_IMAGE_REGISTRY}/library/python@sha256:9d7f287598e1a5a978c015ee176d8216435aaf335ed69ac3c38dd1bbb10e8d64 AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.11.32
COPY --from=opa-builder /go/bin/opa /usr/local/bin/opa

WORKDIR /app
COPY pyproject.toml uv.lock LICENSE README.md ./
RUN uv sync --frozen --no-dev --extra serve --extra pdf-report --extra azure-mcp --no-install-workspace --no-editable

COPY src/ ./src/
COPY evaluation-sdk/ ./evaluation-sdk/
COPY benchmarks/sregym/pyproject.toml ./benchmarks/sregym/pyproject.toml
COPY benchmarks/cybergym/pyproject.toml ./benchmarks/cybergym/pyproject.toml
COPY rule-catalog/ ./rule-catalog/
COPY policies/ ./policies/
RUN uv sync --frozen --package fdai --no-dev --extra serve --extra pdf-report --extra azure-mcp --no-editable
RUN test -x /app/.venv/bin/fdai-isolated-executor

# ----------------------------------------------------------------------------
FROM ${BASE_IMAGE_REGISTRY}/library/python@sha256:9d7f287598e1a5a978c015ee176d8216435aaf335ed69ac3c38dd1bbb10e8d64 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AZURE_MCP_COLLECT_TELEMETRY=false \
    DOTNET_BUNDLE_EXTRACT_BASE_DIR=/tmp/.net \
    HOME=/tmp/fdai \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app/src" \
    XDG_CACHE_HOME=/tmp/fdai/.cache

WORKDIR /app
RUN apt-get update \
    && apt-get install --yes --no-install-recommends libicu72 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder --chown=65532:65532 /app/.venv /app/.venv
COPY --from=builder /usr/local/bin/opa /usr/local/bin/opa
COPY --chown=65532:65532 rule-catalog/ /app/rule-catalog/
COPY --chown=65532:65532 policies/ /app/policies/
COPY --chown=65532:65532 config/ /app/config/
COPY --chown=65532:65532 docs/internals/sregym-absorption-ledger.json /app/docs/internals/sregym-absorption-ledger.json
COPY --chown=65532:65532 resolved-models.json /app/resolved-models.json
COPY --chown=65532:65532 tests/scenarios/ /app/tests/scenarios/
# App source colocated at /app/src (on PYTHONPATH) so path-relative catalog
# resolution (``prod.py`` computes the catalog root from ``__file__``) finds
# /app/rule-catalog + /app/policies in the container exactly as in a repo
# checkout. Without this the Operator API prod factory cannot load the ontology
# / views / reporting catalogs.
COPY --chown=65532:65532 src/ /app/src/
# Schema migrations (raw-SQL alembic revisions). alembic is a runtime
# dependency, so a one-off Container Apps Job can run `alembic upgrade head`
# against the state store using the same image (no separate migration image).
COPY --chown=65532:65532 alembic/ /app/alembic/
COPY --chown=65532:65532 alembic.ini /app/alembic.ini

USER 65532
RUN test -x /app/.venv/bin/fdai-isolated-executor \
    && python -c "import fdai.runtime.isolated_executor_cli"
ENTRYPOINT ["python", "-m", "fdai"]
