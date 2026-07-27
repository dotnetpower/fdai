# SREGym benchmark plugin

This package translates the SREGym conductor lifecycle into the brand-neutral FDAI benchmark
contracts. It is installed only in a benchmark runner environment and is not part of the FDAI
runtime distribution.

## Layout

| Path | Purpose |
|------|---------|
| `src/fdai_bench_sregym/adapter.py` | Translates conductor stages and submissions. |
| `src/fdai_bench_sregym/plugin.py` | Registers the `sregym` entry point. |
| `tests/` | Verifies transport validation and fail-closed lifecycle behavior. |

## Current scope

The plugin implements `/status`, `/get_app`, and `/submit`. It does not inspect SREGym problem
definitions, oracles, or grading internals. Metric, log, trace, and Kubernetes integrations are
separate provider implementations that should bind through FDAI's existing provider and governed
execution contracts. Until those providers are installed, the plugin must not report a successful
diagnosis or mitigation by itself.

## Testing

Run the package tests from the repository root:

```bash
PYTHONPATH=src:benchmarks/sregym/src .venv/bin/python -m pytest \
  -q --no-cov benchmarks/sregym/tests
```
