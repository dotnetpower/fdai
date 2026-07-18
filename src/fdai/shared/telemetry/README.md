# `src/fdai/shared/telemetry`

This subsystem wires structured logging, OpenTelemetry traces, and metrics into the
composition root. Every log line carries a `correlation_id`, and every metric maps to a
named source in
[goals-and-metrics.md](../../../../docs/roadmap/architecture/goals-and-metrics.md).

## Files

| File | Purpose |
|------|---------|
| `logging.py` | JSON stdout logging and the retained local warning file handler. |
| `correlation.py` | Async-safe correlation context shared by logs and traces. |
| `tracing.py` | OpenTelemetry tracer provider setup. |
| `metrics.py` | OpenTelemetry meter provider setup. |
| `setup.py` | One-call telemetry initialization for the composition root. |

## Running locally

When `runtime.env` is `dev` and FDAI runs from a source checkout, the composition root
writes `WARNING`, `ERROR`, and `CRITICAL` records to:

```text
.fdai/logs/warnings.jsonl
```

The file remains JSON Lines so local automation can parse the same fields emitted to
stdout. The handler uses a cross-process lock, stores the directory with mode `0700`,
stores files with mode `0600`, and retains only records from the latest 24 hours. It
compacts on startup, before each write, and every five minutes while the process runs.
Malformed records and records without a timezone-aware timestamp are removed during
compaction.

Pytest runs don't attach the automatic local file handler. Tests that exercise expected
failure paths therefore stay in pytest capture instead of becoming hardening candidates.
Tests for the handler pass an explicit temporary path.

Availability logs include stable fields such as backend mode and model name. They don't
include provider endpoints, credentials, or customer resource identifiers.

Staging, production, and installed-package runs continue to emit JSON to stdout only.
The `.fdai/` directory is excluded from Git.
