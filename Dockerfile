# Minimal, distroless-ish runtime image for the core control plane.
#
# Multi-stage:
#   1. base + uv install → resolve + install dependencies with a lockfile.
#   2. runtime → copy only site-packages + the aiopspilot package.
#
# Notes:
# - No cloud SDK is required at runtime for local-fake mode; httpx +
#   pydantic + jsonschema are enough. Azure adapters are imported lazily
#   by bind_azure_llm_bindings() when llm.mode='azure'.
# - Runs as non-root (uid 10001). Container Apps enforces read-only fs
#   on the app volume by default; only the writable OTel/temp mounts are
#   used.

FROM python:3.13-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir uv==0.4.30

WORKDIR /app
COPY pyproject.toml uv.lock LICENSE README.md ./
RUN uv sync --frozen --no-dev --no-install-project --no-editable

COPY src/ ./src/
COPY rule-catalog/ ./rule-catalog/
COPY policies/ ./policies/
RUN uv sync --frozen --no-dev --no-editable

# ----------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin aiopspilot

WORKDIR /app
COPY --from=builder --chown=aiopspilot:aiopspilot /app/.venv /app/.venv
COPY --from=builder --chown=aiopspilot:aiopspilot /app/src /app/src
COPY --chown=aiopspilot:aiopspilot rule-catalog/ /app/rule-catalog/
COPY --chown=aiopspilot:aiopspilot policies/ /app/policies/

USER 10001
ENTRYPOINT ["python", "-m", "aiopspilot"]
