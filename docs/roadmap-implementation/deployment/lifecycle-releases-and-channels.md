# Lifecycle Releases and Channels implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Legacy channel names in signed manifests | implemented | `packages/deployment-cli/src/fdai_deployment_cli/{bundle.py,trust_roots.py,deployment_kit.py}`; `packages/deployment-cli/tests/test_offline_prepare.py::test_standalone_rejects_bundle_outside_package_release_channel` passed on 2026-10-02 | `development`, `beta`, and `stable`. The CLI trusts only `development`. |
| Channel rename and custom channels | not-started | Design only: `docs/roadmap/deployment/lifecycle-releases-and-channels.md` Release channels section | Maps to `DEV`, `RELEASE_CANDIDATE`, and `RELEASE` |
| Release manifest for the Hub path | implemented | `packages/deployment-cli/src/fdai_deployment_cli/runtime_release.py`; `packages/deployment-cli/tests/test_runtime_release.py::test_runtime_release_v3_validates_lifecycle_manifest_fields` passed on 2026-10-04 | Local shadow-only `fdai.runtime-release.v3` validation adds schema range, capability maximums, downtime, and installation agent images. It grants no publication or execution authority. |
| Promotion pipeline | not-started | Design only: Release channels section | Labels, soak time, canary health, and timeouts |
| Release and capability recall pure decisions | implemented | `packages/deployment-cli/src/fdai_deployment_cli/runtime_release.py`; `packages/deployment-cli/tests/test_runtime_release.py::test_recall_decision_blocks_repromotion_and_orders_recall_targets` and `test_recall_lift_allows_later_candidate` passed on 2026-10-04 | Local shadow-only helpers deny recalled Release and capability candidates, compute recall-target ordering, and allow a later capability lift record only for candidates at or after the lifting Release. Publication, import, runtime demotion, and roll-off Plan priority are still open. |
| Catalog integrity metadata | not-started | Design only: Catalog integrity section | Expired metadata allows only recall roll-off and returns operator-override promotions to shadow mode |
| Schema compatibility planner constraint | implemented | `packages/deployment-cli/src/fdai_deployment_cli/runtime_release.py`; `packages/deployment-cli/tests/test_runtime_release.py::test_schema_transition_blocks_upgrade_outside_tolerated_range` passed on 2026-10-04 | Local shadow-only validator blocks upgrade or roll-back candidates outside the tolerated schema range and blocks non-forward upgrade targets. It does not implement the Hub planner. |
| Registry mirroring and artifact constraint | not-started | Design only: Connected installations section | Blocks a Plan until every digest is inside the boundary |
| Upgrade bundle and Target Hub import | not-started | Design only: Offline installations section | The first-installation offline package stays unchanged |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-02 | not-started | Adopted the ledger with the accepted ADR-0003 design. Recorded the existing legacy channel admission as the starting point. | `current change`; `docs/roadmap/deployment/lifecycle-releases-and-channels.md`; `uv run --project packages/deployment-cli python -m pytest -c packages/deployment-cli/pyproject.toml -q --no-cov packages/deployment-cli/tests/test_offline_prepare.py -k release_channel` passed | Every open item below |
| 2026-10-04 | implemented | Added local shadow-only Release v3 manifest validation, schema transition decisions, and recall re-promotion and roll-off-priority decisions. | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/runtime_release.py`; `packages/deployment-cli/src/fdai_deployment_cli/runtime_stage.py`; `packages/deployment-cli/tests/test_runtime_release.py`; `uv run --project packages/deployment-cli python -m pytest -c packages/deployment-cli/pyproject.toml -q --no-cov packages/deployment-cli/tests/test_runtime_release.py` passed; `uv run --project packages/deployment-cli ruff check packages/deployment-cli/src/fdai_deployment_cli/runtime_release.py packages/deployment-cli/src/fdai_deployment_cli/runtime_stage.py packages/deployment-cli/tests/test_runtime_release.py` passed; `uv run --project packages/deployment-cli ruff format --check packages/deployment-cli/src/fdai_deployment_cli/runtime_release.py packages/deployment-cli/src/fdai_deployment_cli/runtime_stage.py packages/deployment-cli/tests/test_runtime_release.py` passed; `uv run --project packages/deployment-cli mypy --strict packages/deployment-cli/src/fdai_deployment_cli/runtime_release.py packages/deployment-cli/src/fdai_deployment_cli/runtime_stage.py` passed | Hub publication, channel promotion, catalog metadata, mirroring, upgrade bundle import, production trust-root ceremony, and runtime recall demotion remain open. |
| 2026-10-04 | implemented | Hardened recall decisions to reject duplicate recall sequences, require signed notice digests, require capability lifts to name a later lifting Release, keep Release-scope recalls denied, and reject JSON booleans in integer revision and sequence fields. | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/runtime_release.py`; `packages/deployment-cli/tests/test_runtime_release.py`; `uv run --project packages/deployment-cli python -m pytest -c packages/deployment-cli/pyproject.toml -q --no-cov packages/deployment-cli/tests/test_runtime_release.py` passed | Hub import, roll-off Plan priority, production signature verification, and runtime recall demotion remain open. |
| 2026-10-05 | implemented | Hardened Release id ordering to require canonical ASCII SemVer and compare prerelease identifiers with numeric precedence before applying capability lift records. | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/runtime_release.py`; `packages/deployment-cli/tests/test_runtime_release.py`; `uv run --project packages/deployment-cli python -m pytest -c packages/deployment-cli/pyproject.toml -q --no-cov packages/deployment-cli/tests/test_runtime_release.py` passed; `uv run --project packages/deployment-cli ruff check packages/deployment-cli/src/fdai_deployment_cli/runtime_release.py packages/deployment-cli/src/fdai_deployment_cli/runtime_stage.py packages/deployment-cli/tests/test_runtime_release.py` passed; `uv run --project packages/deployment-cli ruff format --check packages/deployment-cli/src/fdai_deployment_cli/runtime_release.py packages/deployment-cli/src/fdai_deployment_cli/runtime_stage.py packages/deployment-cli/tests/test_runtime_release.py` passed; `uv run --project packages/deployment-cli mypy --strict packages/deployment-cli/src/fdai_deployment_cli/runtime_release.py packages/deployment-cli/src/fdai_deployment_cli/runtime_stage.py` passed | Hub import, roll-off Plan priority, production signature verification, and runtime recall demotion remain open. |

### Remaining work

- [ ] Rename channels in new signatures, keep one-way legacy mapping for verification, and record
  tests for both names and for an unknown name.
- [ ] Add custom channels and manual channel contribution, and record a test in which a Release
  reaches a custom channel only through an authorized contributor.
- [x] Extend the local Release manifest validator with schema range, capability maximums,
  downtime, and installation agent images, and record schema validation tests in
  `packages/deployment-cli/tests/test_runtime_release.py`.
- [ ] Add production Release signature validation for the Hub path after the vendor release key
  ceremony exists, and record tests using the approved verification helper.
- [ ] Add the promotion pipeline, and record tests for label requirements, soak time, canary health,
  and timeouts.
- [x] Add local Release and capability recall decision helpers, and record tests for recall-target
  ordering, blocked re-promotion, duplicate recall-sequence denial, and capability lift records in
  `packages/deployment-cli/tests/test_runtime_release.py`.
- [ ] Add roll-off Plan priority so recall roll-off to the newest eligible non-recalled Release
  outranks other Plans.
- [ ] Wire capability recall into runtime demotion after recall import exists, and record a test
  that a recalled capability returns to shadow mode immediately.
- [ ] Add signed root, snapshot, and timestamp records, and record tests that reject a lower
  version, detect a recall sequence gap, and return operator-override promotions to shadow mode
  when the timestamp expires.
- [x] Record schema-compatibility tests that block an upgrade or roll-back outside the tolerated
  range.
- [ ] Add registry mirroring and the artifact constraint, and record a test that blocks a Plan while
  a digest is missing.
- [ ] Add the signed upgrade bundle and Target Hub import, and record tests that reject a bad
  signature, a checksum mismatch, and an unsigned configuration package.
- [ ] Run the production trust-root ceremony for the vendor release key and retain its receipt.
