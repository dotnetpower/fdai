# Benchmark plugins

This directory contains independently packaged adapters for external evaluation harnesses. FDAI's
generic contracts live under `src/fdai/benchmarking/`; no harness package is installed with the
base FDAI distribution.

## Layout

| Path | Purpose |
|------|---------|
| `sregym/` | SREGym conductor lifecycle plugin. |
| `<name>/pyproject.toml` | Independent dependencies and `fdai.benchmark_adapters` entry point. |
| `<name>/tests/` | Harness-specific transport and lifecycle tests. |

## Adding a plugin

Create a separate distribution, implement `BenchmarkAdapter`, and expose a factory through the
`fdai.benchmark_adapters` entry-point group. Keep harness protocols and optional dependencies in
that distribution. Use existing FDAI provider contracts for evidence and the governed execution
path for mutations.

The owning design is
[`docs/roadmap/interfaces/benchmark-adapters.md`](../docs/roadmap/interfaces/benchmark-adapters.md).
