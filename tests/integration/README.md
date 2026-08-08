# `services/core-control-plane/tests/`

Cross-subsystem regression suites and shared fixtures.

Unit tests colocate with each subsystem under `services/core-control-plane/src/fdai/**`; this directory
holds only cross-subsystem regression, property tests, and scenario fixtures.

## Service suites

[`service-suites.json`](service-suites.json) assigns unit, contract, integration, and smoke
tests to each of the five deployable runtime services. The assignment is logical: tests stay near
their current subsystem while each service gets an independently runnable verification boundary.

Run one service suite with:

```bash
make service-test SERVICE=isolated-executor
```

Run all five service suites in canonical topology order with:

```bash
make service-test-all
```

For bounded reporting, filtering, failure-control, or parallelism options, invoke the runner
directly so its allowlist validates each argument:

```bash
uv run --extra dev python scripts/automation/run-service-tests.py isolated-executor -- -q -x
```

The runner accepts options such as `-q`, `-v`, `-k`, `-m`, `-x`, `--no-cov`, `--tb`,
`--maxfail`, `-n`, and `--dist`. It doesn't accept additional test paths, response files, root
overrides, or plugin-specific collection options. The runner always supplies the paths owned by
the selected service. Make targets intentionally don't interpolate free-form arguments through a
shell.

List the selected paths without running pytest with:

```bash
uv run python scripts/automation/run-service-tests.py isolated-executor --list
```

Use `--all --list` to inspect the complete canonical path union without running pytest.

`--list` can't be combined with pytest arguments. A malformed manifest, an empty service suite,
an out-of-repository path, or a path that overlaps another service fails before pytest starts.
The runner also requires the manifest's service ids and order to match
`config/service-decomposition.json` exactly. Unknown manifest keys fail instead of being ignored.

Coverage patterns require every service source and every test in the shared-contract,
ingestion-gateway, isolated-Executor runtime, and isolated-Executor infrastructure cohorts to have
exactly one owner. A new file in one of these file-owned cohorts can't bypass its service suite.
