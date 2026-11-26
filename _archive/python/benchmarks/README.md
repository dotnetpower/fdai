# Evaluation drivers

This directory retains independently packaged adapters for external evaluation harnesses. FDAI's
generic contracts live in the separate `evaluation-sdk/` distribution. No harness package is
installed with the base FDAI distribution or its root `dev` extra.

> **Runtime status:** The SDK-host integration is dormant because the current Core distribution
> has no `EvaluationHost` composition. Package tests and wheel builds remain active preservation
> gates. The repository-level CyberGym shadow runner is independent of that missing host and keeps
> its existing explicit command path.

## Layout

| Path | Purpose |
|------|---------|
| `sregym/` | SREGym conductor lifecycle driver. |
| `cybergym/` | CyberGym-E2E source workspace and artifact driver. |
| `<name>/pyproject.toml` | Independent SDK-only package dependencies. |
| `<name>/services/core-control-plane/tests/` | Harness-specific transport and lifecycle tests. |

## Adding a driver

Create a separate distribution and implement `EvaluationAdapter` from `fdai-evaluation-sdk`.
The driver initiates a session through an injected `EvaluationHost`; FDAI doesn't discover or
load benchmark entry points in production. Keep harness protocols, datasets, validators, and
optional dependencies in the driver distribution. Request semantic capabilities for evidence and
use the governed host path for mutations.

The retained design and reactivation boundary are in
[`docs/roadmap/interfaces/benchmark-adapters.md`](../docs/roadmap/interfaces/benchmark-adapters.md).
