FROM sregym-agent-base:latest

WORKDIR /opt/fdai

COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
COPY rule-catalog/ ./rule-catalog/
COPY policies/ ./policies/
COPY evaluation-sdk/ ./evaluation-sdk/
COPY benchmarks/sregym/ ./benchmarks/sregym/

RUN python -m pip install --break-system-packages ./evaluation-sdk . ./benchmarks/sregym

ENV FDAI_CATALOG_ROOT=/opt/fdai/rule-catalog
ENV FDAI_POLICIES_ROOT=/opt/fdai/policies

WORKDIR /logs
