# Lifecycle Configuration implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Configuration schema with axis and owner annotations | implemented | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py`; `packages/deployment-cli/tests/test_lifecycle_configuration.py`; `uv run --project packages/deployment-cli pytest -q --no-cov packages/deployment-cli/tests/test_lifecycle_configuration.py` passed | Keys without `x-fdai-axis` or `x-fdai-owner`, and keys on authority axes, are rejected before package use |
| Configuration layers and override coverage | implemented | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py`; `packages/deployment-cli/tests/test_lifecycle_configuration.py`; `uv run --project packages/deployment-cli pytest -q --no-cov packages/deployment-cli/tests/test_lifecycle_configuration.py` passed | Layer resolution is a pure library operation; a Release without a matching override block isn't deployable |
| Configuration package, signing, and predecessor checks | not-started | Design only: Customer Git and configuration packages section | One signed package per merged revision |
| Sealed values | not-started | Design only: Value classes and Customer Git and configuration packages sections | Encrypted to the installation key. The Hub stores ciphertext and digests. |
| Secret references | implemented | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py`; `packages/deployment-cli/tests/test_lifecycle_configuration.py`; `uv run --project packages/deployment-cli pytest -q --no-cov packages/deployment-cli/tests/test_lifecycle_configuration.py` passed | Pre-signing validation rejects literal secret values and allows Key Vault references; package signing and sealing remain separate work |
| Customer repository template | not-started | Design only: Examples section | Placeholders only |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-02 | not-started | Adopted the ledger with the accepted ADR-0003 design. No implementation exists. | `current change`; `docs/roadmap/deployment/lifecycle-configuration.md`, `docs/roadmap/architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance.md`; design-route, roadmap-tracking, translation, punctuation, and link checks | Every item below |
| 2026-10-04 | implemented | Added a pure deployment CLI library for Release configuration schema annotations, deterministic layer resolution, deployability gating on matching Entity override blocks, and pre-signing literal secret-value rejection while allowing Key Vault references. | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py`; `packages/deployment-cli/tests/test_lifecycle_configuration.py`; `uv run --project packages/deployment-cli pytest -q --no-cov packages/deployment-cli/tests/test_lifecycle_configuration.py` passed; `uv run --project packages/deployment-cli ruff check packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py packages/deployment-cli/tests/test_lifecycle_configuration.py` passed; `uv run --project packages/deployment-cli ruff format --check packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py packages/deployment-cli/tests/test_lifecycle_configuration.py` passed; `uv run --project packages/deployment-cli mypy --strict packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py` passed | Package signing, predecessor checks, sealing, Hub import, and the customer repository template remain open |

### Remaining work

- [x] Add axis and owner annotations to the Release configuration schema, and record a validator
  test that rejects an unannotated key and a key on an authority axis.
- [x] Add layer resolution, and record tests for most-specific version-range selection and for a
  Release that isn't deployable without a matching override block.
- [ ] Add the packager, and record tests that reject an unsigned package, a predecessor gap, and a
  forked revision.
- [ ] Add sealing, and record a test in which the Hub stores only ciphertext and digests and an
  installation decrypts with its own key.
- [x] Record a test that a package containing a secret value is rejected before signing.
- [ ] Publish a customer repository template and a configuration-key onboarding runbook that use
  placeholders only.
