# Release Hub image deployment implementation ledger

This ledger distinguishes local connected image bootstrap from publication and an accepted
installation in a different Azure subscription.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Connected image bootstrap | implemented | `current change`; new Hub image trust/stage/coordinator tests and request API: 119 passed in final combined validation; existing source/wrapper/productization contracts: 92 passed; 11 CLI modules passed mypy; new source/test Ruff passed | Independent public key, signed catalog and v2 component references, seven-image import/readback, exact checkout/target binding, durable request receipt and remote-host transfer. Explicit source/offline paths remain available; no in-place channel upgrade or Hub teardown. |
| Subscription request intake and operator view | implemented | `current change`; `lifecycle/release-hub/tests/test_deployment_requests.py`: 55 initial cases passed; isolated PostgreSQL storage/migration: 2 passed; offset boundary: 2 passed; Release Hub UI: 29 passed, affected follow-up: 10 passed; typecheck/build/strict mypy/Ruff passed; synthetic actual-browser filter, pagination, error/race and 1440/993/390 checks passed | Self-reported request metadata only, with private listing. Explicit Release schema 1-to-2 expansion preserves catalog bytes. Request quota, body/concurrency bounds and authentication separation are tested. Pagination can reach the entire 100,000-record retention bound. |
| Live publication and installation acceptance | not-started | No live operation performed in this change | Requires separately authorized Hub rollout, a compatible signed Release, registry access and terminal installation evidence. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-25 | in-progress | Defined the ordinary clone image path and a separate self-reported subscription request boundary while preserving explicit source and offline paths. | `current change`; [design and critique](../../roadmap/deployment/hub-image-deployment.md#design-critique-and-revised-boundary) | Complete focused implementation checks and retain live acceptance separately. |
| 2026-10-25 | implemented | Added bounded request intake, transactional idempotency and private subscription-filtered operator pagination without modifying catalog publication or lifecycle authority. | `current change`; 55 request cases, 29 UI cases, typecheck/build/Ruff and synthetic actual-browser checks passed; shared authentication/migration/startup logical batch: 144 passed, 79 PostgreSQL prerequisite skips. | Finish connected deployment integration; live Hub rollout, isolated PostgreSQL qualification and another-subscription installation acceptance remain separate. |
| 2026-10-25 | implemented | Verified actual request persistence, exact retry/conflict, reconnect and schema expansion against isolated PostgreSQL 5433; aligned pagination with the full retention bound. | `current change`; 2 PostgreSQL cases and 2 offset boundary cases passed; affected UI selection: 10 passed; typecheck/build/strict mypy/Ruff passed. Existing private-state CLI regression passed with checkout-external temporary state. | Live Hub rollout and another-subscription installation acceptance remain separately authorized operational work. |
| 2026-10-25 | implemented | Connected ordinary clone deployment to signed Hub images through the existing Foundation/application coordinator, with immutable source/target selection, no build fallback and explicit self-reported request recording. | `current change`; final combined root-runner validation: 119 passed, including isolated PostgreSQL cases; final source/wrapper/productization preservation: 92 passed; CLI mypy on 11 modules and new Hub source/tests Ruff passed. Native TCTX's missing-dependency zero-test result was not accepted; validation used the existing compatible Python 3.13 environment. | Publish/roll out only under separate authorization, then retain actual another-subscription deployment acceptance. Existing parser lint findings remain unchanged. |

### Remaining work

- [x] Record passing focused deployment, request-store/authentication, isolated PostgreSQL and UI
  checks for the current implementation in the scope and history above.
- [ ] Under separate publication/deployment authorization, roll out the Hub and CLI builds,
  publish a compatible signed Release and verify its image registry availability.
- [ ] Retain terminal health and second zero-change-plan evidence for a Hub-image installation
  in another selected Azure subscription, and independently observe its request in Release Hub.
- [ ] Implement separately reviewed in-place catalog/channel upgrades and Hub teardown before
  advertising either capability for this bootstrap.

## Focused validation

The commands below preserve the executed selectors; `python` denotes the selected existing
Python 3.13 environment, and private temporary-directory arguments are omitted. No live Hub,
Azure or registry operation was performed.

```bash
# Passed: 119 tests, including isolated PostgreSQL request storage/migration.
python3 scripts/automation/with-local-test-database.py python -m pytest -q --no-cov \
  packages/deployment-cli/tests/test_hub_image_deployment.py \
  packages/deployment-cli/tests/test_hub_image_orchestration.py \
  packages/deployment-cli/tests/test_hub_image_transport.py \
  lifecycle/release-hub/tests/test_deployment_requests.py

# Passed: 92 existing source, wrapper and productization contract tests.
python -m pytest -q --no-cov \
  packages/deployment-cli/tests/test_source_azure.py \
  tests/integration/scripts/test_contributor_deployment.py \
  tests/integration/scripts/test_deployment_cli_productization.py \
  tests/integration/scripts/test_signing_key_check.py::test_package_role_hints_name_the_kit_builder_not_the_retired_wrapper_option

# Passed: 29 initial UI tests; affected pagination follow-up: 10 tests.
npm --prefix lifecycle/release-hub/ui test
npm --prefix lifecycle/release-hub/ui run typecheck
npm --prefix lifecycle/release-hub/ui run build
```

Type checking passed for the five changed Hub source modules and eleven CLI modules. New Hub
source/tests and the final shared fixture passed Ruff. The modified application parser retains
the same two pre-existing Ruff findings as `HEAD`: `RUF009` for its `SchemaRange` default and
`TRY004` in `_workload`; this change does not claim a clean repository-wide lint run.

The commit preflight identified six format-only changes and a missing locked PyYAML dependency
in the isolated worktree environment. Restoring that checkout's frozen development environment
resolved the dependency failure. Formatting preserved all six Python ASTs, and the final native
TCTX run passed 153 Hub/source/wrapper/productization cases with no skips. Unchanged request/API
and PostgreSQL evidence above remains reusable. The staged owning-document impact, design-route,
translation and implementation-ledger checks also passed.
