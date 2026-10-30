# Build from the repository root. Supply a reviewed python:3.13-slim digest.
# checkov:skip=CKV_DOCKER_7:build-controller-image.sh requires a Python 3.13 slim sha256 digest; no mutable default base is provided.
ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

RUN groupadd --gid 10001 controller \
 && useradd --uid 10001 --gid controller --no-create-home --shell /usr/sbin/nologin controller

COPY scripts/automation/runner_controller/ scripts/automation/runner_controller/
COPY scripts/automation/runner_pool_policy.py scripts/automation/runner_pool_policy.py
COPY config/ci-runner-pools.json config/ci-runner-pools.json

USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8080), timeout=2).close()"
CMD ["python", "-m", "scripts.automation.runner_controller.service"]
