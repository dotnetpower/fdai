FROM docker.io/library/golang@sha256:0178a641fbb4858c5f1b48e34bdaabe0350a330a1b1149aabd498d0699ff5fb2 AS opa-builder

ARG OPA_VERSION=v1.18.2
ARG OPA_GRPC_VERSION=v1.82.1
ARG OPA_X_TEXT_VERSION=v0.39.0
RUN /usr/local/go/bin/go mod download "github.com/open-policy-agent/opa@${OPA_VERSION}" \
	&& opa_dir="$(/usr/local/go/bin/go env GOPATH)/pkg/mod/github.com/open-policy-agent/opa@${OPA_VERSION}" \
	&& chmod -R u+w "${opa_dir}" \
	&& cd "${opa_dir}" \
	&& /usr/local/go/bin/go mod edit -require="google.golang.org/grpc@${OPA_GRPC_VERSION}" \
	&& /usr/local/go/bin/go mod edit -require="golang.org/x/text@${OPA_X_TEXT_VERSION}" \
	&& CGO_ENABLED=0 /usr/local/go/bin/go build -mod=mod -o /go/bin/opa .

FROM sregym-agent-base@sha256:e59f24847cbafdd86f33ded2ca4e9f79fbda3e8737810cf6816af99a255bb441

WORKDIR /opt/fdai

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ ./src/
COPY rule-catalog/ ./rule-catalog/
COPY policies/ ./policies/
COPY evaluation-sdk/ ./evaluation-sdk/
COPY benchmarks/sregym/ ./benchmarks/sregym/
COPY docs/internals/sregym-absorption-ledger.json ./docs/internals/sregym-absorption-ledger.json

RUN python -m pip install --break-system-packages --no-cache-dir uv==0.11.32 \
	&& uv sync --frozen --package fdai --package fdai-benchmark-sregym --no-dev --no-editable \
	&& mkdir -p /logs \
	&& chown 65532:65532 /logs

COPY --from=opa-builder /go/bin/opa /usr/local/bin/opa

ENV FDAI_CATALOG_ROOT=/opt/fdai/rule-catalog
ENV FDAI_POLICIES_ROOT=/opt/fdai/policies
ENV PATH="/opt/fdai/.venv/bin:${PATH}"

WORKDIR /logs
USER 65532
