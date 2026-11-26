# SREGym evaluation driver

This package translates the SREGym conductor lifecycle into the benchmark-neutral
`fdai-evaluation-sdk` contracts. It is not part of the FDAI runtime distribution or the root
`dev` extra.

> **Runtime status:** Dormant. The adapter and package tests are retained, but the current Core
> distribution does not provide the `EvaluationHost` required to run an SREGym session. Building
> the image does not reactivate the integration.

## Layout

| Path | Purpose |
|------|---------|
| `src/fdai_bench_sregym/adapter.py` | Translates conductor stages to SDK requests, tasks, and results. |
| `src/fdai_bench_sregym/plugin.py` | Provides the temporary environment factory for compatibility callers. |
| `Dockerfile` | Layers FDAI and the plugin onto the reviewed SREGym agent base. |
| `tests/` | Verifies transport validation and fail-closed lifecycle behavior. |

## Current scope

The retained driver implements `/status`, `/get_app`, and `/submit`. Its contract requests neutral
observation capabilities and expects an `EvaluationHost` from its launcher. No current FDAI
launcher supplies that host.

The package does not inspect SREGym problem definitions, oracles, or grading internals. Metric,
log, trace, and Kubernetes integrations remain separate provider implementations that should bind
through FDAI's existing provider and governed execution contracts. Until those providers and
promoted execution bindings are installed, FDAI returns a held result instead of claiming a
successful diagnosis or mitigation.

## Container image

Build the reviewed SREGym base image first, then build the FDAI layer from the FDAI repository
root:

```bash
docker build -f benchmarks/sregym/Dockerfile -t fdai-sregym-agent:latest .
```

The repository `.dockerignore` excludes local runtime state, resolved model files, logs, temporary
artifacts, and secrets from the build context.

## Testing

Run the package tests from the repository root:

```bash
PYTHONPATH=evaluation-sdk/src:benchmarks/sregym/src .venv/bin/python -m pytest \
  -q --no-cov benchmarks/sregym/tests
```
