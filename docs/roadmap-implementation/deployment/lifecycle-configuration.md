# Lifecycle Configuration implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Configuration schema with axis and owner annotations | not-started | Design only: `docs/roadmap/deployment/lifecycle-configuration.md` Value classes section | Keys on authority axes are rejected |
| Configuration layers and override coverage | not-started | Design only: Configuration layers section | A Release without a matching override block isn't deployable |
| Configuration package, signing, and predecessor checks | not-started | Design only: Customer Git and configuration packages section | One signed package per merged revision |
| Sealed values | not-started | Design only: Value classes and Customer Git and configuration packages sections | Encrypted to the installation key. The Hub stores ciphertext and digests. |
| Secret references | not-started | Design only: Secrets section | Values stay in Key Vault and are read through the existing CSI path |
| Customer repository template | not-started | Design only: Examples section | Placeholders only |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-02 | not-started | Adopted the ledger with the accepted ADR-0003 design. No implementation exists. | `current change`; `docs/roadmap/deployment/lifecycle-configuration.md`, `docs/roadmap/architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance.md`; design-route, roadmap-tracking, translation, punctuation, and link checks | Every item below |

### Remaining work

- [ ] Add axis and owner annotations to the Release configuration schema, and record a validator
  test that rejects an unannotated key and a key on an authority axis.
- [ ] Add layer resolution, and record tests for most-specific version-range selection and for a
  Release that isn't deployable without a matching override block.
- [ ] Add the packager, and record tests that reject an unsigned package, a predecessor gap, and a
  forked revision.
- [ ] Add sealing, and record a test in which the Hub stores only ciphertext and digests and an
  installation decrypts with its own key.
- [ ] Record a test that a package containing a secret value is rejected before signing.
- [ ] Publish a customer repository template and a configuration-key onboarding runbook that use
  placeholders only.
