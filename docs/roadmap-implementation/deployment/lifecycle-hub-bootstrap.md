# Lifecycle Hub Bootstrap implementation ledger

This ledger tracks the local first-installation entry surface under #2711.
The [owner](../../roadmap/deployment/lifecycle-hub-bootstrap.md) defines behavior;
broader managed installation and Azure evidence remain with #1824 and #2181.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Loopback setup session and launcher | implemented | `lifecycle/hub/src/fdai_lifecycle_hub/setup_api.py`, `setup_start.py`; focused command below: 56 passed | Starts without PostgreSQL; kernel lock, one-use exchange, same-site session, exact Host/Origin, bounded strict JSON, fresh executor heartbeat and owned-process cleanup. |
| Customer-side deployment executor | implemented | `packages/deployment-cli/src/fdai_deployment_cli/bootstrap_*.py`; focused executor/regression command below: 228 passed | Existing deployment engine and exact decisions; no Azure credentials or Terraform execution in the Hub HTTP process. |
| Packaged bilingual setup surface | implemented | `lifecycle/hub/src/fdai_lifecycle_hub/setup_ui/`; `bootstrap.spec.ts`, `bootstrap-session.integration.spec.ts`; actual-route browser checks | Sixteen synthetic scenarios and one real Python session integration case passed. EN/KO geometry passed at 1440, 993 and 390 pixels, with 44-pixel visible mobile buttons. No live Azure installation is claimed. |
| Installed-wheel startup | implemented | Local Hub 0.1.1, CLI 0.1.2 and service-contracts 0.1.0 wheels built and installed with the declared dependencies | Started outside a checkout, with Runtime/Hub database bindings unset; `/setup` returned 200 and unauthenticated status returned 401. Wheel includes all three setup assets. |
| Published packages and live Azure acceptance | deferred | #2711, #2181 | Neither package publication nor a customer installation is authorized by local implementation. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-31 | in-progress | Added the reviewed Bootstrap design, isolated local session and customer-side executor boundary. | Current change: owner and task-owned source/test paths above; #2711. | Complete focused integration, package and browser checks; preserve separate live qualification. |
| 2026-10-31 | implemented | Completed local Bootstrap startup, explicit first-install decisions, private execution/recovery and bilingual packaged UI. Fixed fragment-only session activation and cleanup of executor descendants. | Current change: task-owned modules and focused commands below; wheel installation outside a checkout; actual Python-served browser measurements. | Publish only with separate authorization; retain exact installed Azure evidence and existing managed-enrollment prerequisites. |
| 2026-10-31 | implemented | Hardened the publication candidate without increasing structural debt or design-context budgets: kept Bootstrap details in its focused owner and extracted injected application review preparation. | Current change: `bootstrap_approval.py`, `standalone_application.py`, `test_standalone_approval.py`; Bootstrap executor and standalone approval selection: 47 passed; strict mypy and Ruff passed; application module reduced to 977 lines against its 978-line baseline. | Complete exact-head delivery checks; retain separate actual Azure acceptance and PyPI publication preparation evidence. |
| 2026-10-31 | implemented | Replaced an inert private-key upload marker fixture with an equivalent runtime-assembled value and retained only its exact historical secret-scan fingerprint. No cryptographic secret or broad scanning exemption was introduced. | Current change: `bootstrap.spec.ts`, `.gitleaksignore`; CI run 41088320628 attempt 1, exact failed gitleaks job 124175454758; pinned local scanner reproduced one finding before repair and no findings after repair; private/oversized key upload browser case: 1 passed. | Complete one bounded corrected publication attempt; actual Azure acceptance remains separate. |
| 2026-10-31 | implemented | Bound current-release offline-kit fixtures and version-output assertions to the package version instead of a stale patch-version literal. Production version, signature and channel verification remain unchanged. | Current change: `test_offline_prepare.py`, `test_artifacts_cli.py`, `test_cli_help_hardening.py`, `test_deployment_cli_productization.py`; CI run 41089943179 attempt 1 regression jobs 124182029199 and 124182029136; three smallest local reproducers failed before repair, then the five owning test files passed 295 tests without skips. | Verify the new exact head in CI; retain separate actual Azure acceptance and publication-owner prerequisites. |
| 2026-10-31 | implemented | Kept secret-scan SARIF upload working when a pool checkout is outside the runner home by binding HOME only for the existing pinned scan action. Scanning, reports, source guards and permissions remain enabled and unchanged. | Current change: `.github/workflows/ci.yml`, runner-layout regression in `test_check_ci_contracts.py`; CI run 41093268575 attempt 1, job 124192704499 reported no leaks before its artifact-root failure; the pool pre-fix reproducer failed, then the owning CI-contract and Constitution files passed 158 tests; CI/source-guard and Constitution checkers passed. | Verify the exact repaired CI head without disabling artifact evidence; actual Azure acceptance remains separate. |
| 2026-10-31 | implemented | Isolated Git global configuration from the action's report-scoped HOME so a checkout-provided `.gitconfig` is never treated as runner configuration. | Current change: step-scoped `GIT_CONFIG_GLOBAL=/dev/null` and the owning runner-layout assertion in `test_check_ci_contracts.py`; no token, source-guard or artifact-upload permission changed. | Verify the exact final CI revision and retain actual Azure acceptance as a separate outcome. |
| 2026-10-31 | implemented | Integrated newly protected main revisions after exact CI admission rejected a stale PR merge-object binding; preserved the admission guard and improved launcher-test startup diagnostics. | Current change follows normal merge of protected `145c31549a` and `b9ad92b5d3`; CI run 41096685276 attempt 1, job 124204451962 denied the old merge binding. The actual repository interpreter passed 568 owning tests with one existing Starlette/AnyIO warning; a native-daemon startup failure was not counted as green. | Publish the synchronized exact candidate and await protected CI; actual Azure acceptance and PyPI owner preparation remain separate. |

Focused checks from the task-owned checkout:

```bash
python -m pytest -q lifecycle/hub/tests/test_setup_api.py \
  lifecycle/hub/tests/test_setup_start.py lifecycle/hub/tests/test_cli.py \
  lifecycle/hub/tests/test_no_azure_credentials.py
# 56 passed; one existing Starlette/AnyIO deprecation warning.

python -m pytest -c pyproject.toml -q --no-cov \
  packages/deployment-cli/tests/test_bootstrap_channel.py \
  packages/deployment-cli/tests/test_bootstrap_executor.py \
  packages/deployment-cli/tests/test_bootstrap_support.py \
  packages/deployment-cli/tests/test_bootstrap_worker.py \
  packages/deployment-cli/tests/test_standalone_approval.py \
  packages/deployment-cli/tests/test_source_azure.py \
  packages/deployment-cli/tests/test_hub_image_orchestration.py \
  tests/integration/scripts/test_genesis_approval.py \
  tests/integration/scripts/test_genesis_runner_image_sku_selection.py
# 228 passed; no live Azure effects.

node lifecycle/hub/ui/node_modules/@playwright/test/cli.js test \
  --config=lifecycle/hub/ui/tests/browser/bootstrap.config.ts
# 16 synthetic cases passed; Python-session integration also passed separately.
```

The Python checks used the existing complete development interpreter, not a dependency-incomplete
TCTX daemon result. A failed conftest import reported as zero executed tests was not accepted as a
pass. Ruff and strict mypy passed for the new source. Browser screenshots were reviewed against
the production Python-served route with explicit synthetic setup/review/failure data, not a live
installation. These checks do not claim a complete accessibility certification or a 50-item UX score.
Final diff review removed an unrequested Hub deployment-request opt-out. The existing minimal
self-reported intake remains unchanged; the owning Bootstrap executor, source and Hub-image
orchestration selection passed 73 tests after that correction. Unchanged evidence above was reused.
Older support Releases without the approval adapter remain explicit compatibility blockers.
An installed-wheel restart check exposed Uvicorn signal re-raising before launcher cleanup.
The launcher now retains its shutdown handler until its executor is reaped. The focused
`python -m pytest -q lifecycle/hub/tests/test_setup_start.py` regression passed 9 tests,
including actual SIGTERM delivery, not only mocked process termination.

### Remaining work

- [x] Record focused executor, HTTP boundary, restart and approval tests with zero unexpected skips;
  the commands above passed.
- [x] Verify wheel contents and installed startup without a checkout, Runtime or Hub PostgreSQL;
  the installed Hub served the packaged UI and kept status authentication closed.
- [x] Record actual Python-served desktop, constrained and mobile EN/KO setup/review/failure scenarios;
  document width equaled viewport width at 1440, 993 and 390 pixels.
- [ ] Publish approved package versions only under separate publication authorization, and verify an exact
  customer installation with independent application readback before claiming operational readiness.
