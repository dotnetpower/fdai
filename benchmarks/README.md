# Evaluation drivers

This directory contains independently packaged adapters for external evaluation harnesses. FDAI's
generic contracts live in the separate `evaluation-sdk/` distribution. No harness package is
installed with the base FDAI distribution.

## Layout

| Path | Purpose |
|------|---------|
| `sregym/` | SREGym conductor lifecycle driver. |
| `cybergym/` | CyberGym-E2E source workspace and artifact driver. |
| `<name>/pyproject.toml` | Independent SDK-only package dependencies. |
| `<name>/tests/` | Harness-specific transport and lifecycle tests. |

## Adding a driver

Create a separate distribution and implement `EvaluationAdapter` from `fdai-evaluation-sdk`.
The driver initiates a session through an injected `EvaluationHost`; FDAI doesn't discover or
load benchmark entry points in production. Keep harness protocols, datasets, validators, and
optional dependencies in the driver distribution. Request semantic capabilities for evidence and
use the governed host path for mutations.

The owning design is
[`docs/roadmap/interfaces/benchmark-adapters.md`](../docs/roadmap/interfaces/benchmark-adapters.md).
