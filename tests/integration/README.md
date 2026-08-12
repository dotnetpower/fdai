# Integration tests

This directory owns repository-level integration, structural, packaging, and automation tests
that do not belong to one deployable service. Service-local tests stay under
`services/<service-id>/tests/` and remain independently runnable.

## Layout

| Path | Responsibility |
|------|----------------|
| Root `test_*.py` files | Cross-service composition, deployment parity, and repository structural gates |
| `infra/` | Static infrastructure topology and identity-boundary contracts |
| `scripts/` | Deterministic tests for repository, release, deployment, and validation automation |
| `services/` | Distribution, image, migration, and package-isolation contracts |
| `evaluation/` | Versioned evaluation inputs consumed by focused integration tests |
| `service-suites.json` | Exclusive test ownership and execution order for the five runtime services |

## Service suites

[`service-suites.json`](service-suites.json) assigns unit, contract, integration, and smoke
tests to each of the five deployable runtime services:

- **Unit** tests exercise service-local domain or adapter logic.
- **Contract** tests verify schemas, wire formats, package boundaries, and parity.
- **Integration** tests cover composition, persistence, and multi-component behavior.
- **Smoke** tests check the smallest service health or startup surface.

The paths are non-overlapping and explicit. A new service test must be assigned to one group before
the service-suite manifest can load, so an unclassified file cannot silently bypass service CI.

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

List the selected group paths without running pytest with:

```bash
uv run python scripts/automation/run-service-tests.py isolated-executor --list
```

Use `--all --list` to inspect the complete canonical path union without running pytest.

`--list` can't be combined with pytest arguments. A malformed manifest, an empty service suite,
an unclassified service file, an out-of-repository path, or an overlapping ownership claim fails
before pytest starts. The runner also requires the manifest's service ids and order to match
`config/service-decomposition.json` exactly. Unknown manifest keys fail instead of being ignored.
