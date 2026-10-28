# Arize Phoenix (LLM trace viewer)

An optional, development-only viewer for FDAI's measured LLM token usage. FDAI mirrors each
metered model call to Phoenix as one OpenInference `LLM` span, so you can inspect token counts,
latency, and per-conversation grouping in the Phoenix UI.

It is **off by default**, adds no runtime dependency, and grants no authority. The durable
metering store (PostgreSQL) stays the system of record for usage and cost.

## What is exported

Two kinds of span reach Phoenix, both grouped by `session.id` (the correlation id):

- **Metered calls** (control-plane T1/T2 reasoning, embeddings): token counts, cached tokens,
  model, capability, tier, mode, and cost when priced. No message text.
- **Conversation calls** (semantic planning, question form, adaptive answer, judgment): model,
  latency, token counts, request and response hashes, and redaction counts. With
  `FDAI_PHOENIX_CAPTURE_CONTENT` set, also the input and output messages, so the Phoenix UI shows
  the question and the answer.

Message text is the same redacted, bounded text that FDAI's provider-input minimization already
produces; secrets and PII are replaced before it reaches a span. Content capture is refused for a
non-loopback endpoint, so conversation text never leaves the machine.

The sink uses its own OpenTelemetry `TracerProvider`, so these spans do not reach any other
exporter such as the Console or Azure Monitor pipeline.

## Start Phoenix

```bash
docker compose -f tools/phoenix/compose.yaml up -d
```

The UI is at `http://127.0.0.1:6006`. Phoenix listens on loopback only.

## Enable the export in FDAI

Set these variables in the environment of the Core service before it starts:

| Variable | Default | Purpose |
|----------|---------|---------|
| `FDAI_PHOENIX_TRACING_ENABLED` | off | Feature flag. Truthy values: `1`, `true`, `yes`, `on`. |
| `FDAI_PHOENIX_OTLP_ENDPOINT` | none | OTLP/gRPC endpoint, for example `http://127.0.0.1:4317`. Required when enabled. |
| `FDAI_PHOENIX_PROJECT_NAME` | `fdai` | Phoenix project that groups the spans. |
| `FDAI_PHOENIX_CAPTURE_CONTENT` | off | Add redacted conversation messages to spans. Loopback endpoints only. |
| `FDAI_PHOENIX_ALLOW_REMOTE_ENDPOINT` | off | Required to export to a non-loopback endpoint. |

If the flag is on but the endpoint is missing, invalid, or remote without the override, the export
stays disabled and Core logs one `phoenix_tracing_disabled` warning with the reason. An export
failure never breaks a model call or the metering write.

This is a development diagnostic. It does not use the Settings-managed capability flag path.

## Stop Phoenix

```bash
docker compose -f tools/phoenix/compose.yaml down        # keep traces
docker compose -f tools/phoenix/compose.yaml down -v     # delete traces
```
