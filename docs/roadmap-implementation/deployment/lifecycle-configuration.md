# Lifecycle Configuration implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Configuration schema with axis and owner annotations | in-progress | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py`; `packages/deployment-cli/tests/test_lifecycle_configuration.py`; `uv run --project packages/deployment-cli pytest -q --no-cov packages/deployment-cli/tests/test_lifecycle_configuration.py` passed | A pure validator now rejects missing annotations, authority axes, and unknown axes; it is not yet wired into a packager |
| Configuration layers and override coverage | in-progress | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py`; `packages/deployment-cli/tests/test_lifecycle_configuration.py`; `uv run --project packages/deployment-cli pytest -q --no-cov packages/deployment-cli/tests/test_lifecycle_configuration.py` passed | A pure resolver validates all override blocks and selects the most-specific matching range; it is not yet wired into a package or Hub path |
| Configuration package, signing, and predecessor checks | not-started | Design only: Customer Git and configuration packages section | One signed package per merged revision |
| Sealed values | not-started | Design only: Value classes and Customer Git and configuration packages sections | Encrypted to the installation key. The Hub stores ciphertext and digests. |
| Secret references | in-progress | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py`; `packages/deployment-cli/tests/test_lifecycle_configuration.py`; `uv run --project packages/deployment-cli pytest -q --no-cov packages/deployment-cli/tests/test_lifecycle_configuration.py` passed | A pure pre-signing validator rejects literal secret values and malformed Key Vault references; it is not yet called by a packager and does not implement CSI reading or resolve-state reporting |
| Customer repository template | not-started | Design only: Examples section | Placeholders only |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-02 | not-started | Adopted the ledger with the accepted ADR-0003 design. No implementation exists. | `current change`; `docs/roadmap/deployment/lifecycle-configuration.md`, `docs/roadmap/architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance.md`; design-route, roadmap-tracking, translation, punctuation, and link checks | Every item below |
| 2026-10-04 | implemented | Added a pure deployment CLI library for Release configuration schema annotations, deterministic layer resolution, deployability gating on matching Entity override blocks, and pre-signing literal secret-value rejection while allowing Key Vault references. | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py`; `packages/deployment-cli/tests/test_lifecycle_configuration.py`; `uv run --project packages/deployment-cli pytest -q --no-cov packages/deployment-cli/tests/test_lifecycle_configuration.py` passed; `uv run --project packages/deployment-cli ruff check packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py packages/deployment-cli/tests/test_lifecycle_configuration.py` passed; `uv run --project packages/deployment-cli ruff format --check packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py packages/deployment-cli/tests/test_lifecycle_configuration.py` passed; `uv run --project packages/deployment-cli mypy --strict packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py` passed | Package signing, predecessor checks, sealing, Hub import, and the customer repository template remain open |
| 2026-10-04 | in-progress | Corrected the validator boundary: axis checks now allow only known non-authority ADR-0002 configuration axes, secret scanning rejects nested and malformed literal secret values, duplicate override ranges are ambiguous, and all override blocks are validated. Scope rows now state that these are pure validators not yet wired into a packager. | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py`; `packages/deployment-cli/tests/test_lifecycle_configuration.py`; `uv run --project packages/deployment-cli pytest -q --no-cov packages/deployment-cli/tests/test_lifecycle_configuration.py` passed | Wire the validators into the future packager, then implement signing, predecessor checks, sealing, Hub import, CSI read paths, resolve-state reporting, and the customer repository template |

### Remaining work

- [x] Add pure validator coverage for axis and owner annotations, including rejection of an
  unannotated key, authority axes, and unknown axes.
- [x] Add pure layer-resolution coverage for most-specific version-range selection and for a
  Release that isn't deployable without a matching override block.
- [ ] Add the packager, and record tests that reject an unsigned package, a predecessor gap, and a
  forked revision, and that call the pure schema, layer, sealed-key, and secret-reference validators.
- [ ] Add sealing, and record a test in which the Hub stores only ciphertext and digests and an
  installation decrypts with its own key.
- [x] Record pure validator tests that a package containing a secret value is rejected before
  signing.
- [ ] Publish a customer repository template and a configuration-key onboarding runbook that use
  placeholders only.
