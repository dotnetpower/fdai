# Lifecycle Releases and Channels implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Legacy channel names in signed manifests | implemented | `packages/deployment-cli/src/fdai_deployment_cli/{bundle.py,trust_roots.py,deployment_kit.py}`; `packages/deployment-cli/tests/test_offline_prepare.py::test_standalone_rejects_bundle_outside_package_release_channel` passed on 2026-10-02 | `development`, `beta`, and `stable`. The CLI trusts only `development`. |
| Channel rename and custom channels | not-started | Design only: `docs/roadmap/deployment/lifecycle-releases-and-channels.md` Release channels section | Maps to `DEV`, `RELEASE_CANDIDATE`, and `RELEASE` |
| Release manifest for the Hub path | not-started | Design only: Release contents section | Adds schema range, capability maximums, downtime, and agent images |
| Promotion pipeline | not-started | Design only: Release channels section | Labels, soak time, canary health, and timeouts |
| Release recall and capability recall | not-started | Design only: Recall section | A capability recall takes precedence over operator override promotion |
| Catalog integrity metadata | not-started | Design only: Catalog integrity section | Expired metadata allows only recall roll-off and returns operator-override promotions to shadow mode |
| Schema compatibility constraint | not-started | Design only: Schema compatibility section | Migrations stay expand/contract and forward-only |
| Registry mirroring and artifact constraint | not-started | Design only: Connected installations section | Blocks a Plan until every digest is inside the boundary |
| Upgrade bundle and Target Hub import | not-started | Design only: Offline installations section | The first-installation offline package stays unchanged |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-02 | not-started | Adopted the ledger with the accepted ADR-0003 design. Recorded the existing legacy channel admission as the starting point. | `current change`; `docs/roadmap/deployment/lifecycle-releases-and-channels.md`; `uv run --project packages/deployment-cli python -m pytest -c packages/deployment-cli/pyproject.toml -q --no-cov packages/deployment-cli/tests/test_offline_prepare.py -k release_channel` passed | Every open item below |

### Remaining work

- [ ] Rename channels in new signatures, keep one-way legacy mapping for verification, and record
  tests for both names and for an unknown name.
- [ ] Add custom channels and manual channel contribution, and record a test in which a Release
  reaches a custom channel only through an authorized contributor.
- [ ] Extend the Release manifest with schema range, capability maximums, downtime, and agent
  images, and record signature and schema validation tests.
- [ ] Add the promotion pipeline, and record tests for label requirements, soak time, canary health,
  and timeouts.
- [ ] Add Release and capability recall, and record tests for roll-off priority, immediate
  capability demotion, and blocked re-promotion until a later Release lifts the recall.
- [ ] Add signed root, snapshot, and timestamp records, and record tests that reject a lower
  version, detect a recall sequence gap, and return operator-override promotions to shadow mode
  when the timestamp expires.
- [ ] Record schema-compatibility tests that block an upgrade or roll-back outside the tolerated
  range.
- [ ] Add registry mirroring and the artifact constraint, and record a test that blocks a Plan while
  a digest is missing.
- [ ] Add the signed upgrade bundle and Target Hub import, and record tests that reject a bad
  signature, a checksum mismatch, and an unsigned configuration package.
- [ ] Run the production trust-root ceremony for the vendor release key and retain its receipt.
