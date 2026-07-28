# CyberGym evaluation driver

This independent package maps CyberGym-E2E tasks to the benchmark-neutral
`fdai-evaluation-sdk`. It does not import FDAI runtime, core, agent, delivery, or composition
implementations.

## Layout

| Path | Purpose |
|------|---------|
| `src/fdai_bench_cybergym/adapter.py` | Maps `e2e` and `patch-only` tasks, declared outputs, and external validation receipts. |
| `tests/test_adapter.py` | Verifies both modes, bounds, hidden-oracle isolation, and SDK runner compatibility. |

## Contracts

`e2e` accepts only a source workspace and declares `poc.bin` plus `fix.patch`. `patch-only`
accepts a source workspace, crash log, and benchmark-provided PoC, then declares `fix.patch`.
The adapter has no field for a ground-truth PoC, hidden tests, oracle, or grader.

The external validator runs after the FDAI task and maps its four stage receipts to
`ExternalValidationReceipt`. That receipt is always untrusted evidence and cannot authorize an
FDAI action.

## Testing

Run the package tests from the repository root:

```bash
PYTHONPATH=evaluation-sdk/src:benchmarks/cybergym/src .venv/bin/python -m pytest \
  -q --no-cov benchmarks/cybergym/tests
```
