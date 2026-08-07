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

`PYTEST_ARGS` accepts bounded reporting, filtering, failure-control, and parallelism options such
as `-q`, `-v`, `-k`, `-m`, `-x`, `--no-cov`, `--tb`, `--maxfail`, `-n`, and `--dist`. It doesn't
accept additional test paths, response files, root overrides, or plugin-specific collection
options. The runner always supplies the paths owned by the selected service.

List the selected paths without running pytest with:

```bash
uv run python scripts/automation/run-service-tests.py isolated-executor --list
```

`--list` can't be combined with pytest arguments. A malformed manifest, an empty service suite,
an out-of-repository path, or a path that overlaps another service fails before pytest starts.
