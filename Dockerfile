# Minimal runtime image for the core control plane.
#
# Multi-stage:
#   1. digest-pinned Python 3.13 Alpine builder + uv resolves the frozen lockfile.
#   2. the same digest starts a clean runtime that receives only the venv and data.
#
# Notes:
# - No cloud SDK is required at runtime for local-fake mode; httpx +
#   pydantic + jsonschema are enough. Azure adapters are imported lazily
#   by bind_azure_llm_bindings() when llm.mode='azure'.
# - Runs as a numeric nonroot user (uid 65532). Container Apps enforces read-only fs
#   on the app volume by default; only the writable OTel/temp mounts are
#   used.

FROM python@sha256:399babc8b49529dabfd9c922f2b5eea81d611e4512e3ed250d75bd2e7683f4b0 AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apk add --no-cache build-base zlib-dev
RUN pip install --no-cache-dir uv==0.4.30

WORKDIR /app
COPY pyproject.toml uv.lock LICENSE README.md ./
RUN uv sync --frozen --no-dev --extra serve --no-install-project --no-editable

COPY src/ ./src/
COPY rule-catalog/ ./rule-catalog/
COPY policies/ ./policies/
RUN uv sync --frozen --no-dev --extra serve --no-editable

# ----------------------------------------------------------------------------
FROM python@sha256:399babc8b49529dabfd9c922f2b5eea81d611e4512e3ed250d75bd2e7683f4b0 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app/src"

WORKDIR /app
COPY --from=builder --chown=65532:65532 /app/.venv /app/.venv
COPY --chown=65532:65532 rule-catalog/ /app/rule-catalog/
COPY --chown=65532:65532 policies/ /app/policies/
# App source colocated at /app/src (on PYTHONPATH) so path-relative catalog
# resolution (``prod.py`` computes the catalog root from ``__file__``) finds
# /app/rule-catalog + /app/policies in the container exactly as in a repo
# checkout. Without this the read-API prod factory cannot load the ontology
# / views / reporting catalogs.
COPY --chown=65532:65532 src/ /app/src/
# Schema migrations (raw-SQL alembic revisions). alembic is a runtime
# dependency, so a one-off Container Apps Job can run `alembic upgrade head`
# against the state store using the same image (no separate migration image).
COPY --chown=65532:65532 alembic/ /app/alembic/
COPY --chown=65532:65532 alembic.ini /app/alembic.ini

USER 65532
ENTRYPOINT ["python", "-m", "fdai"]
