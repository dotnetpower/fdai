# Application Runtime Bundles implementation ledger

This ledger tracks the application-neutral runtime extension separately from the successful
bounded HTTP demonstration. Its design owner is
[Application Runtime Bundles](../../roadmap/deployment/lifecycle-runtime-bundles.md).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Component release and independent private runtime contract | implemented | `current change`; `packages/deployment-cli/tests/test_lifecycle_release.py`, `lifecycle/hub/tests/test_application_release.py`, `lifecycle/agent/tests/test_application_release.py`; included in the 361-pass focused selection below | Existing v1 remains bounded HTTP; v2 carries immutable component images, not installation authority. |
| Runtime rendering and native recovery | implemented | `current change`; `lifecycle/agent/tests/test_runtime_bundle.py`, `test_native_scope.py`, `test_cli.py`, `test_deployment_scope.py` and CLI `test_lifecycle_native.py`; 128 passed; final runtime-bundle selection 45 passed including a separately spawned Python process | Private references, security/resource bounds, optional Services, CronJobs, UID fencing, durable replay, same-schema/update/removal guards and conservative scheduled-effect holds. |
| Operator handoff and automation inventory | implemented | [Deployment handoff](../../runbooks/hub-lifecycle-deployment-handoff.md), [experience backlog](../../runbooks/hub-lifecycle-operator-experience.md), existing [operator guide](../../runbooks/hub-lifecycle-operator-guide.md); four translated pairs passed quality/parity checks | Actual target evidence stays private. UXH-01 through UXH-18 are proposed design work, not implemented UI. |
| Real FDAI Azure qualification and operational effects | deferred | No real FDAI deployment or application-effect receipt in this change | Requires a separately authorized target, prepared infrastructure/references and independent effect observations. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-22 | in-progress | Define a product-neutral runtime input contract after distinguishing bounded HTTP evidence from complete FDAI installation | `current change`; design, critique and acceptance criteria in the linked owner | Implement and validate all bounded runtime, ownership and recovery surfaces; no live qualification claimed. |
| 2026-10-23 | implemented | Add v2 image publication and independently pinned private runtime rendering without product-name execution branches; preserve old native bytes and guard scheduled recovery | `current change`; 361 passed, 2 skipped in the focused Agent/CLI/Hub selection; 128 passed in the updated runtime/native/CLI/RBAC selection; Ruff and strict mypy passed for the changed source | Keep cloud qualification and the proposed UI redesign separate; complete final immutable-candidate delivery checks before publication. |

### Remaining work

- [x] Publish/import component releases without changing existing v1 signatures or behavior.
- [x] Validate independently reviewed private bundles and exact signed configuration pins before
  any mutation, including wrong product/namespace/Entity/reference/security input.
- [x] Express the FDAI backend, Console, sidecar, initialization and scheduled-work shape
  as data through the same entry point as a single HTTP application.
- [x] Preserve native UID fencing, dry-run, bounded execution, rollback, interruption and replay
  for every supported object kind; block unsupported persistent/schema/topology effects.
- [x] Finish the bilingual operational handoff and identify each manual boundary and available
  command versus missing automation.
- [x] Pass focused tests, strict source type checks, lint, translation quality/parity, punctuation,
  readable-Hangul and documentation links for the task-owned inputs. Exact-head publication
  checks and their results belong in the draft PR; CI remains authoritative for integration.
- [ ] Perform separately authorized real FDAI qualification before claiming installed readiness.
