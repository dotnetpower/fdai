# Local Configuration Publication implementation ledger

This ledger records source evidence for the bounded local venue, not Git review, Hub
acceptance, a globally unique publisher or an installed configuration.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Durable local publication and read-only inspection | implemented | `current change`; #2363; `lifecycle_configuration_publication*.py`, shared artifact codec and actual CLI integration; 211 focused cases passed; strict mypy (4 source files) and Ruff passed | Original bytes and stable receipts; actual 256-package/16-MiB bounds; complete-chain historical retry without head rewind; no Git review or Hub authority. |
| Protected-merge automation and authoritative venue registration | not-started | Parent configuration owner and #1823 | A local venue is not global identity or review evidence. |
| Actual onboarding, import and installation effects | not-started | Parent configuration owner and #1823 | Independent operational qualification remains required. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-22 | not-started | Recorded the venue-scoped design and critique before implementation; no historical delivery is invented. | Current paired owner; existing builder/reader and private-output contracts. | Implement and verify the bounded source capability below. |
| 2026-10-22 | implemented | Added the schema-1 private journal, serialized publication, exact post-commit artifact recovery, historical retries, read-only inspection and real CLI. Unknown/corrupt state, transaction sidecars, conflicts and bounds hold without reset. | `current change`; #2363; focused command below: 211 passed; Ruff passed; strict mypy: 4 source files passed. Real subprocess exit and competing fresh process, native SQLite, independent cryptographic reader and no-network/no-subprocess CLI guards are exercised. | Exact-head delivery evidence is tracked in #2363; global venue registration, protected-merge automation and actual installation qualification remain separate. |

### Remaining work

- [x] Persist original packages and stable receipts atomically under one private venue lock.
- [x] Preserve v1/v2 and existing CLI compatibility with independent reader verification.
- [x] Verify concurrency, conflict, privacy, actual retention limits and post-commit artifact recovery.
- [x] Wire real local publish and read-only inspection commands with explicit unverified boundaries.
- [x] Record focused source checks below; immutable gates, required CI and protected integration
  are tracked in #2363 rather than claimed from these local checks.
- [ ] Separately deliver a protected-merge pipeline with authoritative venue/identity and actual
  onboarding, Hub acceptance and installation-effect evidence; local publication does not satisfy it.

Focused source command:

```bash
.venv/bin/pytest -q -c pyproject.toml --no-cov packages/deployment-cli/tests/test_lifecycle_configuration_cli.py packages/deployment-cli/tests/test_lifecycle_configuration_package.py packages/deployment-cli/tests/test_lifecycle_configuration_entities.py packages/deployment-cli/tests/test_lifecycle_configuration_publication.py packages/deployment-cli/tests/test_lifecycle_configuration_publication_bounds.py
```

Result: **211 passed**. No live Git-provider, Azure, model, key-onboarding or installation action ran.
