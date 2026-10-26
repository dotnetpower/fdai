# Application Runtime Bundles implementation ledger

This ledger tracks the application-neutral runtime extension separately from the successful
bounded HTTP demonstration. Its design owner is
[Application Runtime Bundles](../../roadmap/deployment/lifecycle-runtime-bundles.md).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Optional signed component registry reference | implemented | `current change`; `lifecycle_release.py`; [Hub-image ledger](hub-image-deployment.md); final combined Hub/request selection: 119 passed, including backward-compatible optional coordinates, digest mismatch and seven-component admission | v2 `components.<name>.image_ref` optionally locates the existing signed digest. Old manifests and installation-local Agent repository authority remain unchanged. |
| Component release and independent private runtime contract | implemented | `current change`; `packages/deployment-cli/tests/test_lifecycle_release.py`, `lifecycle/hub/tests/test_application_release.py`, `lifecycle/agent/tests/test_application_release.py`; included in the 361-pass focused selection below | Existing v1 remains bounded HTTP; v2 carries immutable component images, not installation authority. |
| Runtime rendering and native recovery | implemented | `current change`; `lifecycle/agent/tests/test_runtime_bundle.py`, `test_native_scope.py`, `test_cli.py`, `test_deployment_scope.py` and CLI `test_lifecycle_native.py`; 128 passed; final runtime-bundle selection 45 passed including a separately spawned Python process | Private references, security/resource bounds, optional Services, CronJobs, UID fencing, durable replay, same-schema/update/removal guards and conservative scheduled-effect holds. |
| Operator handoff and automation inventory | implemented | [Deployment handoff](../../runbooks/hub-lifecycle-deployment-handoff.md), [experience backlog](../../runbooks/hub-lifecycle-operator-experience.md), existing [operator guide](../../runbooks/hub-lifecycle-operator-guide.md); four translated pairs passed quality/parity checks | Actual target evidence stays private. UXH-01 through UXH-18 are proposed design work, not implemented UI. |
| FDAI topology runtime-bundle generator and native-scope parity | implemented | `current change`; #2466, #2468, #2181; `lifecycle/manager/src/fdai_lifecycle_manager/runtime_bundle_generator.py`, `packages/deployment-cli/src/fdai_deployment_cli/hub_workload_handoff{,_inputs}.py`, `infra/hub-workload-state-handoff/`, focused Python and Terraform checks in the 2026-10-26 history row | The pure generator converts AKS `workloads` and `scheduled_jobs` maps into the runtime bundle, component images, prerequisites, and matching native scope for Core, Operator, ingestion API, document worker, four CronJobs, Services, and four HPAs. It also emits exact state-handoff variables, a digest-bound address/import/render inventory, and reviewed phase commands. |
| Real FDAI Azure qualification and operational effects | deferred | No real FDAI deployment or application-effect receipt in this change | Requires a separately authorized target, prepared infrastructure/references and independent effect observations. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-26 | implemented | Completed full-topology generator parity by emitting one bounded same-name HPA for each of the four FDAI Deployments, omitting their pinned replica counts, and binding all four names in `autoscaled_components`. Added private exact Terraform handoff inputs and phase commands for 16 native objects, plus import-only, forget-only, and zero-change plan verification. | `current change`; `lifecycle/manager/src/fdai_lifecycle_manager/{runtime_bundle_generator.py,cli.py}`, `packages/deployment-cli/src/fdai_deployment_cli/hub_workload_handoff{,_inputs}.py`, `infra/hub-workload-state-handoff/`; focused manager/CLI, deployment CLI, and Terraform commands recorded in the Hub-managed lifecycle ledger passed | Run the separately authorized full-topology import, ownership handoff, HPA lifecycle exercise, rollback import, and final zero-change verification before claiming live qualification. |
| 2026-10-24 | implemented | Added the pure FDAI topology runtime-bundle generator (`fdai-lifecycle-manager generate-runtime-bundle`), canary controller-UID `fieldRef` and `jobTemplate.metadata.labels` support in `RuntimeBundle`, Terraform-to-bundle parity and native-scope equality tests, and recorded the single-Owner 14-day development-profile reading in the EN/KO Hub operator guide. | `current change`; #2466, #2181; `lifecycle/manager/src/fdai_lifecycle_manager/runtime_bundle_generator.py`, `lifecycle/manager/src/fdai_lifecycle_manager/cli.py`, `lifecycle/agent/src/fdai_lifecycle_agent/runtime_bundle.py`, `lifecycle/manager/tests/test_runtime_bundle_generator.py`, `lifecycle/manager/tests/test_preparation.py`, `lifecycle/agent/tests/test_runtime_bundle.py`, `docs/runbooks/hub-lifecycle-operator-guide{,-ko}.md`; 61 focused tests passed. | Apply the named stewardship infrastructure prerequisites in `rg-fdai-dev-wus3` and run the live Hub Release delivery and #458 handover drill when authorized. |
| 2026-10-22 | in-progress | Define a product-neutral runtime input contract after distinguishing bounded HTTP evidence from complete FDAI installation | `current change`; design, critique and acceptance criteria in the linked owner | Implement and validate all bounded runtime, ownership and recovery surfaces; no live qualification claimed. |
| 2026-10-23 | implemented | Add v2 image publication and independently pinned private runtime rendering without product-name execution branches; preserve old native bytes and guard scheduled recovery | `current change`; 361 passed, 2 skipped in the focused Agent/CLI/Hub selection; 128 passed in the updated runtime/native/CLI/RBAC selection; Ruff and strict mypy passed for the changed source | Keep cloud qualification and the proposed UI redesign separate; complete final immutable-candidate delivery checks before publication. |

| 2026-10-25 | implemented | Extend v2 component metadata with an optional digest-matched registry reference for connected image bootstrap without changing private runtime or local Agent authority. | `current change`; [Hub-image design](../../roadmap/deployment/hub-image-deployment.md); final combined Hub/request selection: 119 passed, including optional-coordinate compatibility and digest mismatch refusal. | Publication and live installation remain separate; existing parser lint findings were not changed. |

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
