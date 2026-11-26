# `services/core-control-plane/src/fdai/shared/telemetry`

This subsystem wires structured logging, OpenTelemetry traces, and metrics into the
composition root. Every log line carries a `correlation_id`, and every metric maps to a
named source in
[goals-and-metrics.md](../../../../../../docs/roadmap/architecture/goals-and-metrics.md).

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
stores files with mode `0600`, and retains at most 4 MiB from the latest 24 hours.
Every append checks that shared byte cap under the same lock. At the cap it keeps
the newest half-window and an explicit `log_retention_truncated` marker before appending,
instead of copying the entire log on every write. Oversized existing files are reclaimed
on handler startup even if another process recently compacted them. Age-based compaction
is coordinated across processes on startup and at most once every five minutes. Lock acquisition is
bounded so a stalled writer doesn't block the application logging path indefinitely.
Malformed records and records without a timezone-aware timestamp are removed during
compaction.

This file is a bounded diagnostic cache, not the append-only operational audit store.
Byte retention can discard older diagnostic rows before 24 hours; the explicit marker
prevents consumers from treating the retained tail as complete history. It does not delete
Events, Incidents, audit records, or activity projections.

Structured records are capped at 64 KiB. Oversized records retain their timestamp,
level, logger, correlation id, bounded message and exception, selected scalar context,
and original byte count. Repeated warning-or-higher aiokafka failures and Pantheon
observer failures keep the first record and periodic summaries with `suppressed_count`;
different rendered failures and correlation episodes are never combined. Pantheon
observer recovery records the complete bridge-owned failure count.

Pytest runs don't attach the automatic local file handler. Tests that exercise expected
failure paths therefore stay in pytest capture instead of becoming hardening candidates.
Tests for the handler pass an explicit temporary path.

Availability logs include stable fields such as backend mode and model name. They don't
include provider endpoints, credentials, or customer resource identifiers.

Staging, production, and installed-package runs continue to emit JSON to stdout only.
The `.fdai/` directory is excluded from Git.
