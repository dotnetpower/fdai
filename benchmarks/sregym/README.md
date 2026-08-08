# SREGym evaluation driver

This package translates the SREGym conductor lifecycle into the benchmark-neutral
`fdai-evaluation-sdk` contracts. It is installed only in an evaluation driver environment and is
not part of the FDAI runtime distribution.

## Layout

| Path | Purpose |
|------|---------|
| `src/fdai_bench_sregym/adapter.py` | Translates conductor stages to SDK requests, tasks, and results. |
| `src/fdai_bench_sregym/plugin.py` | Provides the temporary environment factory for compatibility callers. |
| `Dockerfile` | Layers FDAI and the plugin onto the reviewed SREGym agent base. |
| `services/core-control-plane/tests/` | Verifies transport validation and fail-closed lifecycle behavior. |

## Current scope

The driver implements `/status`, `/get_app`, and `/submit`. It requests neutral observation
capabilities and receives an `EvaluationHost` from its launcher. FDAI owns event construction,
decision interpretation, authority attenuation, and cleanup behind that public interface.

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
