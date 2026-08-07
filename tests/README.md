# `tests/`

Cross-subsystem regression suites and shared fixtures.

Unit tests colocate with each subsystem under `src/fdai/**`; this directory
holds only cross-subsystem regression, property tests, and scenario fixtures.

## Service suites

[`service-suites.json`](service-suites.json) assigns unit, contract, integration, and smoke
tests to each of the five deployable runtime services. The assignment is logical: tests stay near
their current subsystem while each service gets an independently runnable verification boundary.

Run one service suite with:

```bash
make service-test SERVICE=isolated-executor PYTEST_ARGS="-q"
```

List the selected paths without running pytest with:

```bash
uv run python scripts/automation/run-service-tests.py isolated-executor --list
```
