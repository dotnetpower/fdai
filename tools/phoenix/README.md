# Arize Phoenix (LLM trace viewer)

An optional, development-only viewer for FDAI's measured LLM token usage. FDAI mirrors each
metered model call to Phoenix as one OpenInference `LLM` span, so you can inspect token counts,
latency, and per-conversation grouping in the Phoenix UI.

It is **off by default**, adds no runtime dependency, and grants no authority. The durable
metering store (PostgreSQL) stays the system of record for usage and cost.

## What is exported

Bounded metadata only: `session.id` (the correlation id), `llm.model_name`,
`llm.token_count.{prompt,completion,total}`, cached prompt tokens, duration, and the `fdai.*`
attributes (capability, tier, mode, usage scope, turn family, disposition, locale, profile digest,
and cost when priced). Prompt and completion text is never exported.

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
