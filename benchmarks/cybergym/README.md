# CyberGym evaluation driver

This independent package maps CyberGym-E2E tasks to the benchmark-neutral
`fdai-evaluation-sdk`. It does not import FDAI runtime, core, agent, delivery, or composition
implementations.

## Layout

| Path | Purpose |
|------|---------|
| `src/fdai_bench_cybergym/adapter.py` | Maps `e2e` and `patch-only` tasks, declared outputs, and external validation receipts. |
| `services/core-control-plane/tests/test_adapter.py` | Verifies both modes, bounds, hidden-oracle isolation, and SDK runner compatibility. |

## Contracts

`e2e` accepts only a source workspace and declares `poc.bin` plus `fix.patch`. `patch-only`
accepts a source workspace, crash log, and benchmark-provided PoC, then declares `fix.patch`.
The adapter has no field for a ground-truth PoC, hidden tests, oracle, or grader.

The external validator runs after the FDAI task and maps its four stage receipts to
`ExternalValidationReceipt`. That receipt is always untrusted evidence and cannot authorize an
FDAI action.

## Running official tasks

The repository-level runner executes one official task in shadow-only mode. It requires Docker,
`/usr/bin/bwrap`, an authenticated GitHub Copilot CLI npm installation, a CyberGym-E2E checkout,
and downloaded task data. Point the runner at the checkout and the dataset's `projects` directory:

```bash
export CYBERGYM_E2E_ROOT=/path/to/CyberGym-E2E
export CYBERGYM_DATA_ROOT=/path/to/cybergym-data/projects

.venv/bin/python scripts/benchmarking/run_cybergym.py check \
  <project>/<task> --mode patch-only
.venv/bin/python scripts/benchmarking/run_cybergym.py run \
  <project>/<task> --mode patch-only --output-root .fdai/cybergym
```

The runner materializes source in a disposable, resource-bounded Docker container. Copilot edits
only the task workspace and output directory through bubblewrap, and the validator runs in fresh
containers that receive hidden validation inputs only after agent execution. A `patch-only` run
succeeds when stage 3 passes the project tests and stage 4 runs the benchmark PoC against the
patched program with exit status 0. Replacing a crash with a nonzero exit does not pass stage 4.
Each run writes `result.json`, `fix.patch`, a bounded agent log, and per-stage JSON receipts beneath
the output root.

## Testing

Run the package tests from the repository root:

```bash
PYTHONPATH=evaluation-sdk/src:benchmarks/cybergym/src .venv/bin/python -m pytest \
  -q --no-cov benchmarks/cybergym/tests
```
