---
title: Deployment Resource Conventions
---
# Deployment Resource Conventions

This document defines the resource naming and tagging conventions for infrastructure that FDAI
provisions. Use it to keep Terraform plans deterministic, resource ownership queryable, and
deployment-specific values outside the upstream distribution.

> This contract applies to provisioned infrastructure. Runtime code consumes resource identifiers
> through configuration and does not compute names or ownership tags.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Core control plane startup probe | not-applicable | `current change`; `terraform fmt` and `terraform validate` pass on the service root | Three attempts sized a startup probe to cover a boot that opened the health port late. The runtime now opens that port before startup readiness runs, so liveness answers immediately and the probe is unnecessary. The protected update contract also rejected it, because it proves rollback only for an image and revision-suffix change. |
| CAF naming and `fdai:` ownership tags | implemented | `infra/main.tf`, `infra/bootstrap/main.tf`, and focused Terraform tests | Terraform computes names and tags; runtime code consumes outputs. |
| Event Bus product topic namespace | in-progress | `current change`; `infra/main.tf`, service defaults, deployment preparation, and focused Event Bus and Terraform checks | Active product-prefixed topics use `fdai.*`. A protected plan, exact apply, drain, and post-apply receipt are still required before the deployed namespace is validated. |
| Independent-service Terraform state roots | validated | `config/independent-service-live-evidence-manifest.json` and `config/independent-service-remote-evidence.json` | All five service roots have governed plan, apply, health, peer-isolation, and rollback evidence. |
| Legacy platform and ops-bootstrap Terraform state roots | implemented | `infra/main.tf`, `infra/bootstrap/main.tf`, `.github/workflows/deploy-dev.yml`, and focused Terraform and workflow checks | Stable backend keys and deployment mechanisms are shipped; governed apply receipts for these two roots are not retained in the repository. |
| OHL scale-out evidence target naming and tags | implemented | current change in `infra/main.tf`; `terraform -chdir=infra test -filter=tests/dev_operations_gateway.tftest.hcl` reports 8 passed | Live provisioning and recurrence evidence remain open. |
| Operator schema and catalog Job naming | implemented | `infra/main.tf`, `infra/modules/operator-api/container-app/`, `.github/workflows/deploy-dev.yml`, and focused deployment workflow tests | Deterministic names and digest-pinned images are wired; a protected apply receipt for the ordered Jobs remains open. |
| Scheduled rule collector Job | implemented | `infra/main.tf`; `infra/modules/compute/container-apps/rule_watcher_job.tf`; `tests/integration/infra/test_rule_watcher_job.py`; focused infrastructure checks (`26 passed`) and `terraform validate` | A configurable cron invokes the verified collector wrapper with the non-effect inventory identity and a native StateStore secret reference. It cannot receive the executor identity or promote a catalog entry. Protected apply and run receipts remain open. |
| Browser-evidence cleanup Job naming | implemented | `infra/main.tf`; `tests/integration/infra/test_browser_evidence_cleanup_job.py`; focused checks (`4 passed`) and `terraform validate` | `caj-<workload>[-env][-region]-browser-gc` stays within the 32-character Azure limit for every allowed environment. Protected apply evidence remains open. |
| Event Bus consumer lag alert | validated | `event_bus.py`; `infra/modules/observability/monitoring/`; protected apply run `32383519737`; live fired and resolved alert observations; focused consumer, infrastructure, and workflow checks | Bounded commits export sanitized partition progress and lag. A broker-backed heartbeat also reports assigned partitions while downstream processing is stalled, and an idle partial batch flushes at its wall-clock commit deadline. The protected monitoring-only apply changed only the scheduled-query rule, and a synthetic sanitized lag row caused the stateful alert to fire and resolve automatically. |
| Protected model resolution artifacts | implemented | `.github/workflows/deploy-dev.yml`; `model_lifecycle_reconciler.py`; focused lifecycle, plan verifier, Terraform, and CI security checks | Protected plans seal full and deployment-only manifests plus SHA-256 digests. Exact apply restores those bytes; runtime receives the same inline JSON and digest. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-22 | implemented | Preserved schema-free same-image topic transitions while requiring service-owned database migration before an image-changing sealed topic rollout. The previous unconditional skip let a newer Operator image start against the baseline service migration head and remain not ready until automatic rollback. | Failed Operator apply `32505673096`; `current change` in `service-deploy.yml`; focused workflow contract tests. | Recreate and apply the exact Operator plan, then prove semantic request and projection transport. |
| 2026-08-21 | implemented | Bound the Core semantic request and projection topics to their canonical logical names after the live migration audit found both deployed environment values empty. An empty pair disables the Core semantic consumer; it is not a runtime default. The sealed migration overlay now requires both values and still rejects a partial or unrelated environment change. | `current change`; `service_contract.py`; both Core Terraform variable boundaries; focused service deployment and semantic Terraform checks passed 143 cases; Ruff, strict mypy, Terraform formatting and validation, and independent-service structure checks passed. | Apply one reviewed Core follow-up plan and prove the authenticated request/projection round trip before classifying the Event Bus migration as validated. |
| 2026-08-21 | in-progress | Replaced the undocumented `aw.*` product prefix in active Event Bus topic contracts with the canonical `fdai.*` prefix. Historical validation rows retain the names they actually observed. Contract-specific `runtime.*`, `object.*`, `operator.*`, and `core.*` topics and non-Event-Bus channels remain outside this prefix migration. | `current change`; naming owner, Terraform topic declarations and roles, service defaults, deployment preparation, and focused Event Bus and Terraform checks. | Run a protected plan that makes every entity replacement explicit, apply the exact reviewed plan, drain or expire the old entities, and retain post-apply runtime evidence. |
| 2026-08-21 | implemented | Added a migration-only protected plan mode after live model reconciliation introduced an unrelated model replacement into the Event Bus plan. The mode targets only both Event Bus modules, topic-scoped roles, and the three topic-bearing Jobs. Its guard requires every declared old/successor action and role replacement and rejects any changed address outside that set plus the reviewed in-place updates. | Protected plan run `32466635579`; `current change` in `.github/workflows/deploy-dev.yml` and `tests/integration/scripts/test_service_deploy_workflow.py`; focused migration guard checks passed 2 cases. | Create and review a new protected migration-only plan before exact apply. |
| 2026-08-21 | in-progress | Applied the exact entity and RBAC migration, then found that independent service roots and four non-targeted legacy Jobs still retained `aw.*` environment values. Added an exact four-Job follow-up mode; independently owned Apps remain on their service-specific protected plan/apply path. | Protected plan `32475286429`; exact apply `32475924808`; `current change` in `.github/workflows/deploy-dev.yml` and focused workflow guards; live entity, RBAC, environment, and health audit. | Apply the four-Job follow-up, apply the Core, Operator, ingestion API, and processing-worker service plans, then rerun transport verification. |
| 2026-08-21 | implemented | Added a sealed `event_bus_topic_migration` service deployment mode after standard protected plans correctly rejected topic environment drift in all four independently owned Apps. The guard permits only each service's exact reviewed topic key/value transition plus the immutable image and fresh revision suffix. Exact apply skips unrelated schema migration, retains the pre-apply rollback snapshot, and still requires post-apply health and peer-isolation evidence. | Failed service plans `32477544820`, `32477555842`, `32477558699`, and `32477561442`; `current change` in `service-deploy.yml`, `guard_plan.py`, `plan_bundle.py`, and focused service deployment tests. | Create, review, and apply one sealed topic-migration plan for each affected service. |
| 2026-08-21 | implemented | Extended the sealed service topic transition to add `FDAI_EXECUTION_VENUE=deployed` only where the live Operator and ingestion Apps lacked that required fixed binding. The guard still rejects every other environment change and reports only unexpected or missing key names. | Failed Operator plan `32483661020`; live Container App environment-name audit; `current change` in `service_contract.py`, `guard_plan.py`, and focused service deployment tests. | Recreate and apply the three affected service plans, then verify every runtime binding and transport. |
| 2026-08-21 | implemented | Raised service rollout and automatic rollback health observation from 15 to 20 minutes after the Core topic revision reached `health_server_ready` 20 seconds before the old deadline but had not yet reached Azure `Healthy`; the three-minute rollback poll also ended before the prior revision's measured seven-minute startup. Both paths now emit bounded progress and fail explicitly at 20 minutes. | Core apply run `32482508143`; retained startup logs for the exact and rollback revisions; `current change` in `verify_health.sh`, `service-deploy.yml`, and focused workflow tests. | Reapply Core after its semantic transport dependency services are healthy, then retain the successful service and transport receipts. |
| 2026-08-21 | implemented | Allowed a sealed service topic plan to recover an out-of-band automatic rollback only when the complete refreshed drift target exactly equals that plan's guarded `before` resource. The normal topic, image, identity, secret, sidecar, and revision checks still govern the proposed `after` resource, and any extra drift remains blocked. | Failed recovery plans `32486301692` and `32486309732`; `current change` in `guard_plan.py`; focused positive and adversarial service plan tests passed 8 cases. | Recreate the Operator and processing-worker topic plans with their last healthy attested images. |
| 2026-08-21 | implemented | Removed the processing worker's hidden five-second cap on PostgreSQL readiness. The probe now honors its validated `connect_timeout_s` setting, which defaults to 10 seconds, after repeated live topic revisions completed Storage, Event Hubs, and embedding probes but exited on `postgres-document-metadata:probe_timeout`. | Worker apply `32487729008`; restarted replica logs; `current change` in `adapters/postgres.py` and focused worker readiness tests passed 3 cases. | Build and apply the exact corrected worker image, then retain its healthy topic and peer-isolation receipts. |
| 2026-08-21 | implemented | Allowed the sealed service topic migration mode to perform a follow-up image repair when every reviewed Event Bus environment binding is already exactly aligned. The guard still accepts the complete first-transition delta and rejects partial transitions, legacy values, command changes, and unrelated environment drift. | Failed migration plan `32490083005`, failed standard plan `32490397592`, and focused positive/adversarial plan-guard tests passed 3 cases. | Create and review a new worker topic plan with the exact corrected image. |
| 2026-08-21 | implemented | Restored the independent Core service contract for canary, raw inventory, HIL decision, and pipeline-stage topics, and made all existing semantic topic names mandatory in the guarded environment. Successful canary and inventory Jobs exposed the gap because the Core revision had the operational broker but did not start either optional consumer. | Canary execution `ca-fdai-dev-krc-core-canary-56kl90p` and inventory execution `ca-fdai-dev-krc-core-inventory-lsh1vpt` succeeded; no corresponding `canary_processed` record appeared; `current change` in the Core Terraform root, service contract, and focused deployment tests passed 6 cases. | Create, review, and apply one exact Core topic plan, then rerun canary, inventory, stage, HIL, and semantic transport checks. |
| 2026-08-21 | implemented | Allowed the sealed Core migration to change only the remaining reviewed topic bindings when earlier bindings are already exact, while still requiring every expected final value. Secret-backed environment bindings now compare their effective secret reference rather than provider `null` versus empty value serialization. | Failed Core plan `32494997800`; `current change` in `guard_plan.py`; focused first-transition, aligned-follow-up, remaining-subset, and adversarial tests passed 4 cases. | Recreate and review the exact Core plan before apply. |
| 2026-08-21 | implemented | Added the three active Event Hubs role-assignment collections to development-gateway targeted plans after Terraform rejected a plan that excluded their `for_each` moves. | Protected plan run `32454927035` exposed the missing targets; `current change` updates `.github/workflows/deploy-dev.yml`, and the focused workflow contract suite passed 34 tests. | Create and review a new protected plan, then apply and validate the migration evidence listed below. |
| 2026-08-21 | implemented | Removed an accidentally injected Python fragment from the protected-source Bash guard and added a shell-syntax regression for that exact step. | Protected run `32458761662` failed before Azure login; `current change`; focused deployment workflow suites passed 46 tests, including `bash -n` for the guard. | Create and review a new protected plan; no Terraform or Azure mutation occurred in the failed run. |
| 2026-08-18 | implemented | Gave the core control plane a bounded startup probe. Its runtime evaluates startup readiness before it opens the health port, so the liveness budget of roughly 91 seconds expired during a normal boot and every new revision entered `CrashLoopBackOff` while the previous revision stayed healthy. A startup probe defers liveness and readiness until the port answers. | `current change`; `terraform fmt`, `terraform init -backend=false`, and `terraform validate` pass on the service root; independent-service contract checks `27 passed`, service Terraform root suite passed, drift contract `7 passed`, CI contract `36 passed`. Measured cause: the failing replica logged `startup_ok` then stopped at `notification_route_unavailable` with no `health_server_ready`, system events reported repeated readiness probe failures, and a local boot took 27 s from `startup_ok` to `startup_readiness_evaluated`. | Confirm a new revision reaches `Healthy` on the deployed environment; tracked on issue #181. |
| 2026-08-18 | implemented | Removed the core startup probe binding. PR #194 made the runtime open its health port before startup readiness runs, so liveness answers immediately and no probe has to cover a slow boot. Keeping the probe also blocked every core deploy: the protected update contract proves rollback only for an image and revision-suffix change, so a plan that added a probe block was refused. | `current change`; `terraform fmt` and `terraform validate` pass on the service root. Measured cause: plan run `32113084153` showed `+ startup_probe` alongside the image change and `guard_plan.py` reported `protected update changes fields rollback cannot prove`. | Confirm the next protected plan contains only the image and revision suffix, and that the new revision reaches `Healthy`; tracked on #181. |
| 2026-08-13 | implemented | Adopted the implementation ledger without reconstructing earlier provenance and added the optional OHL VM Scale Set convention. | current change; focused Terraform tests report 8 passed. | Capture the exact protected apply and live OHL evidence. |
| 2026-08-13 | implemented | Corrected the broad state-root claim by keeping the five receipt-backed service roots `validated` and classifying the legacy platform and ops-bootstrap roots as `implemented`. | current change; `config/independent-service-live-evidence-manifest.json`, `config/independent-service-remote-evidence.json`, and roadmap, translation, and documentation checks. | Retain governed apply receipts for the platform and bootstrap roots before advancing them to `validated`. |
| 2026-08-13 | implemented | Added a deterministic Operator catalog Job that runs only after the schema migration Job succeeds. | Current change in `infra/main.tf`, `infra/modules/operator-api/container-app/`, and `.github/workflows/deploy-dev.yml`; Terraform validate passed and focused deployment tests report 22 passed. | Capture the protected apply and Job execution receipt. |
| 2026-08-15 | implemented | Added the deterministic length-safe `browser-gc` Job component for scheduled browser-evidence retention. | `current change`; focused Terraform contract checks `4 passed`; `terraform validate`. | Capture the protected apply and Job execution receipts. |
| 2026-08-17 | implemented | Declared the retirement of the auxiliary readiness transition entity and its role assignment. PR #153 returned startup readiness transitions to the multiplexed primary bus, leaving the entity without a publisher. | `current change`; `deploy-dev.yml` parses as valid YAML and the registered keys resolve to the exact Terraform addresses the protected plan reported. | Remove both entries once the retirement has been applied. |
| 2026-08-17 | implemented | Separated the trace-continuity detection window from the analyzer window. A discontinuity is keyed by its detection window, so equal windows let correlation starve while the ingress deduplicates the per-minute repeats. | `current change`; `analyzer_tick_cli.py`, the analyzer job module, and focused resolver tests: 6 passed. `terraform fmt` and `terraform validate` pass. | Record a deployed anomaly raised from repeated trace findings. |
| 2026-08-17 | implemented | Kept the new trace window argument inside the existing alignment. The infra contract tests assert exact formatted argument text, so a longer variable name shifted every aligned argument in the block and failed unrelated assertions. | `current change`; infra contract suite: 71 passed, 1 skipped. | Consider whether those assertions should match formatted text at all. |
| 2026-08-17 | not-applicable | Corrected the trace-window README description to use the approved display term `detected issue` instead of the contract term `finding`. The Terraform variable, analyzer behavior, machine records, and deployment contract are unchanged. | `current change`; focused display-terminology check passes. | None for this wording correction. |
| 2026-08-19 | implemented | Replaced the fixed rule-watcher schedule with a validated deployment variable and routed the Job through the verified collector evidence wrapper. The Job uses the existing inventory identity for image pull and StateStore secret resolution instead of inheriting the privileged executor identity. | `current change`; focused rule-collector and scheduled-Job contracts passed 26 cases; `terraform fmt -check` and `terraform validate` passed. | Retain one protected apply and scheduled-run receipt with the exact cron, image digest, identity, and validated success record. |
| 2026-08-19 | implemented | Exported sanitized per-partition Event Bus consumer progress after each bounded commit and added a Log Analytics scheduled-query alert for ingress lag. Token-expiry recycling still flushes a partial batch and remains a credential-refresh boundary, not a process restart. | `current change`; focused consumer and infrastructure checks passed 5 cases; Ruff, strict mypy, `terraform fmt -check`, and `terraform validate` passed. | Apply the monitoring plan and retain a live firing and recovery receipt before classifying the alert as validated. |
| 2026-08-19 | implemented | Replaced externally supplied model capability JSON with protected live resolution, sealed exact model artifacts into plan metadata and private blobs, and restored them for apply and runtime composition. | `current change`; focused resolver, lifecycle, plan verifier, Operator narrator, Terraform, and privileged-workflow checks passed. | Retain one protected plan/apply receipt and one proposal-only reconciler run. |
| 2026-08-20 | implemented | Added an independent broker-backed lag heartbeat for every assigned Event Bus partition. It continues to emit sanitized progress while downstream processing is stalled and no commit completes, closes broker reads within one sampling deadline, suppresses unchanged caught-up rows, and runs on local and deployed transports. | `current change`; `event_bus.py`; `test_event_bus.py`; focused Event Bus checks passed 48 cases. | Apply the monitoring plan and retain a live firing and recovery receipt before classifying the alert as validated. |
| 2026-08-20 | implemented | Exposed the existing opt-in monitoring module as an explicit protected workflow input for dev, staging, and production. Previously, `deploy-dev.yml` could enable monitoring only inside the production binding, so the implemented consumer-lag alert could not be planned or applied to dev. | `current change`; `.github/workflows/deploy-dev.yml`; focused workflow contract test. | Apply an exact dev monitoring plan and retain a live firing and recovery receipt before classifying the alert as validated. |
| 2026-08-20 | implemented | Isolated `deploy_monitoring` plans to `module.monitoring`, rejected every planned change outside that module, and blocked combining the design-mocks-only path with monitoring. Existing optional resources can remain enabled as inputs without entering the saved plan. | `current change`; `.github/workflows/deploy-dev.yml`; `tests/integration/scripts/test_service_deploy_workflow.py`; focused monitoring isolation check passed 1 case. | Run the protected monitoring-only plan, require no unexpected change, then retain live firing and recovery evidence. |
| 2026-08-20 | implemented | Made `commit_interval_seconds` a wall-clock flush deadline for an idle partial Event Bus batch. Previously, the interval was checked only after another message arrived, so the last processed offset could remain uncommitted until the next token recycle and report false lag. | `current change`; `event_bus.py`; idle-batch regression and the full focused Event Bus suite passed 49 cases; Ruff and formatting passed. | Deploy the corrected Core image and verify bounded lag and normalization across a token recycle. |
| 2026-08-20 | implemented | Kept monitoring-only plans out of live model resolution even when repository-level LLM variables are enabled. Runs `32374901098` and `32375097678` failed before Terraform because the isolated monitoring target still entered an unrelated model resolver. | `current change`; `.github/workflows/deploy-dev.yml`; focused workflow contract test. | Create and apply a fresh protected monitoring-only plan, then retain alert firing and recovery evidence. |
| 2026-08-20 | implemented | Completed protected live-preflight mappings for Azure Monitor action groups, diagnostic settings, metric alerts, and scheduled-query alerts. Run `32376699737` failed before a plan could be sealed because the profile could not classify those Terraform create actions. | `current change`; `.github/workflows/deploy-dev.yml`; focused workflow and live-preflight mapping tests. | Create and apply a fresh protected monitoring-only plan, then retain alert firing and recovery evidence. |
| 2026-08-20 | implemented | Repaired protected plan metadata sealing after run `32378121573` reached the final store step and exposed an embedded Python indentation error plus a missing `Path` import. The workflow contract now compiles that heredoc during tests. | `current change`; `.github/workflows/deploy-dev.yml`; focused embedded-Python compile and workflow checks. | Create and apply a fresh protected monitoring-only plan, then retain alert firing and recovery evidence. |
| 2026-08-20 | implemented | Allowed exact apply to restore a protected plan without runtime-image evidence when the target is infrastructure-only. Sealed monitoring plan `32379417932` correctly carries no runtime image, while the prior restore path required one unconditionally. | `current change`; `.github/workflows/deploy-dev.yml`; focused runtime-evidence branching and workflow checks. | Recreate and apply the monitoring-only plan from the corrected workflow, then retain alert firing and recovery evidence. |
| 2026-08-20 | implemented | Made the Event Bus lag scheduled-query alert stateful with AzureRM `auto_mitigation_enabled`. The first live apply `32381129117` succeeded, but ARM readback showed `autoMitigate=false`, so a fired alert could not satisfy the required automatic recovery contract. | `current change`; monitoring Terraform module; focused alert contract test; Terraform validate. | Apply the corrected rule, then retain one firing and automatic-resolution observation. |
| 2026-08-20 | validated | Applied the corrected stateful Event Bus lag rule through the protected monitoring-only path, verified ARM `autoMitigate=true`, and exercised the live condition with one sanitized synthetic lag row. The alert fired at `2026-08-20T15:36:09Z` and resolved automatically at `2026-08-20T16:02:10Z` after the configured clear periods. | Protected apply run `32383519737` changed 0 resources by creation, 1 in place, and 0 by destruction; exact alert instance observations recorded `Fired` then `Resolved`; focused alert checks passed 3 cases. | None for the Event Bus consumer lag alert deployment and stateful recovery contract. |
### Remaining work

- [ ] Retain repository-safe governed apply receipts for the legacy platform and ops-bootstrap
  roots. Each receipt must bind the backend key, exact protected plan, source revision, target
  identity, and post-apply verification before those roots advance to `validated`.
- [ ] Retain one protected Event Bus migration receipt that binds the exact plan and source
  revision, shows every `aw.*` to `fdai.*` entity replacement and role-scope update, reports no
  unrelated replacement or deletion, drains or expires old retained records, and passes the
  post-apply startup, canary, HIL, stage, inventory, and semantic transport checks.
- [ ] Record a protected apply receipt showing the OHL target keeps its deterministic name,
  application-resource-group placement, private subnet, and required `fdai:` tags.
- [ ] Record a protected apply and execution receipt showing `caj-<workload>-migrate` succeeds
  before `caj-<workload>-catalog` starts with the reviewed Core image digest.
- [ ] Record a protected apply and execution receipt for the deterministic `caj-<workload>[-env][-region]-browser-gc` Job.
- [ ] Record a protected apply and scheduled-run receipt for the rule collector Job, including its exact cron, image digest, non-effect identity, and validated provenance success record.
- [x] Protected apply run `32383519737` changed only the Event Bus scheduled-query rule, ARM
  reported `autoMitigate=true`, and the live alert fired at `2026-08-20T15:36:09Z` before
  resolving automatically at `2026-08-20T16:02:10Z` after the sanitized lag row aged out.
- [ ] Retain a protected model-resolution plan/apply receipt proving the full and deployment-only
  manifest digests match the exact runtime JSON, plus one sanitized proposal-only reconciler run.

## Resource Naming Convention

Every Azure resource this repo provisions follows the **Microsoft Cloud Adoption Framework
(CAF)** abbreviation convention. Names are deterministic, deployment-agnostic, and safe to
grep for - a rename is a Terraform diff, never a hand-edit.

Pattern:

```
<caf-prefix>-<workload>[-<component>][-<env>][-<region>][-<instance>]
```

- **workload** is the fixed literal `fdai` (product name, not a customer identifier -
  allowed under [generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
- **component** is added only when one resource kind is provisioned more than once
  (e.g. `ca-fdai-core` vs a future `ca-fdai-worker`).
- **env** (`dev`/`staging`/`prod`) and **region** (`krc`/`weu`/`eus`) suffixes are added only
  when the resource is deployed side-by-side; the day-zero deployment keeps names
  suffix-free.
- **instance** (`01`, `02`, ...) is added only when multiple copies exist in one env.

The default **resource group** is `rg-fdai` (fixed by user directive). Everything the
system provisions lives under that RG unless a resource type requires a subscription-scope
placement (none today).

### Event Bus product topic namespace

An Event Bus topic that uses the FDAI product namespace starts with `fdai.` and follows
`fdai.<domain>.<purpose>`. Current examples include `fdai.change.events`,
`fdai.pantheon.objects`, and `fdai.pipeline.stages`. A dead-letter entity appends `.dlq` to the
complete topic name, such as `fdai.change.events.dlq`.

Terraform owns provisioned topic names and passes them to each runtime through configuration.
Application defaults support local startup and must match the Terraform-selected names; they do
not create a second naming authority. The undocumented `aw.` product prefix is legacy and is not
accepted in an active topic default or new infrastructure declaration. Historical evidence keeps
the exact `aw.*` name that was observed so a later rename cannot rewrite a prior validation claim.

This product-prefix rule does not rename contract-specific `runtime.*`, `object.*`, `operator.*`,
or `core.*` topics, nor does it apply to SSE channels, OpenTelemetry keys, Entra groups, or chat
commands. Changing a provisioned Event Hub entity name is a replacement, not an in-place rename.
A deployment therefore uses a protected plan and exact apply, verifies every role scope and
producer/consumer binding, drains or expires retained records on the old entity, and records
post-apply transport evidence before deleting the old path.
An explicitly approved, non-authoritative development backlog may instead be discarded when the
exact apply deletes the legacy entities.
Use a `plan-evh-<20-hex>` request id for this cutover and an `apply-evh-<20-hex>` request id for
its exact apply. This mode targets only both Event Bus modules, topic-scoped role assignments, and
the analyzer, canary, and inventory Jobs. The guard requires every declared old/successor action,
role replacement, primary namespace update, and update to those three Jobs. It rejects every other
changed address before the plan is sealed.
After the entity cutover, use `plan-evh-jobs-<16-hex>` and `apply-evh-jobs-<16-hex>` to update
only the OOB, scheduler, baseline, and growth Jobs when a live audit finds their topic environment
stale. Independently owned Container Apps use `service-deploy.yml`; the legacy platform plan does
not regain ownership of those resources.
For those Apps, set `event_bus_topic_migration=true` on both the service plan and exact apply. The
sealed mode accepts only the service-specific reviewed topic environment values, a missing required
`FDAI_EXECUTION_VENUE=deployed` binding, immutable image, and fresh revision suffix. It skips schema
migration for this configuration-only transition while preserving rollback capture, health
verification, peer-state isolation, and live observations.

### CAF prefixes for the day-zero inventory

| Resource | CAF prefix | Char rules | Example name |
|----------|------------|------------|--------------|
| Resource Group | `rg-` | 1-90; alphanumerics + hyphens/underscores | `rg-fdai` |
| User-assigned Managed Identity | `id-` | 3-128 | `id-fdai-executor` |
| Container Apps environment | `cae-` | 2-32; alphanumerics + hyphens | `cae-fdai` |
| Container App (core) | `ca-` | 2-32 | `ca-fdai-core` |
| Container Apps Job (out-of-band) | `caj-` | 2-32 | `caj-fdai-oob`, `caj-fdai-browser-gc` |
| Virtual Machine Scale Set | `vmss-` | 1-64 | `vmss-fdai-ohl-dev-krc` |
| Event Hubs namespace | `evhns-` | 6-50 | `evhns-fdai` |
| PostgreSQL Flexible Server | `psql-` | 3-63; lowercase | `psql-fdai` |
| Key Vault | `kv-` | 3-24; alphanumerics + hyphens | `kv-fdai` |
| **Container Registry (ACR)** | `cr` | 5-50; **alphanumeric only, no hyphens** | `crfdai` |
| Log Analytics workspace | `log-` | 4-63 | `log-fdai` |
| Azure Monitor alert / action group | `alert-` / `ag-` | 1-260 / 1-260 | `alert-fdai-event-bus-consumer-lag`, `ag-fdai` |
| Foundry account (`AIServices`) | `aif-` | 2-64; alphanumerics + hyphens | `aif-fdai-search` |
| Foundry account project | `proj-` | 2-64; alphanumerics + hyphens | `proj-fdai-search` |
| Azure Bot (HIL Adaptive Cards) | `bot-` | 2-64 | `bot-fdai` |
| Static Web App | `stapp-` | 2-40 | `stapp-fdai`, `stapp-fdai-design-mocks-dev-ea` |

### Length-safety rules

- **ACR names never contain hyphens**; the prefix `cr` is fused with the workload token
  (`crfdai`). When env/region suffixes join, do not reintroduce hyphens - use one
  continuous lowercase alphanumeric string (e.g. `crfdaidevkrc01`).
- **Storage accounts** use at most 24 lowercase alphanumeric characters. Document storage
  adds a stable six-character hash derived from subscription + environment for global uniqueness.
- **Static Web Apps use their hosting region suffix.** The design-mocks resource includes the
  `design-mocks` component and the Static Web Apps region, for example
  `stapp-fdai-design-mocks-dev-ea`. This region can differ from the control-plane region because
  Static Web Apps is not available in every Azure region.
- If a legal name exceeds the character limit after adding env/region/instance, use the
  documented short-name `aip` in place of `fdai` - and only for that resource kind.
  Do not sprinkle `aip` where the full name still fits.
- The browser-evidence cleanup Job uses the short component `browser-gc`, so the longest allowed
  `caj-fdai-staging-<region>-browser-gc` form remains at or below 32 characters.

### What this rule prevents

- **Random suffixes**: A short deterministic hash is allowed where globally unique names
  require it, such as Storage. A suffix that changes on every plan blocks review.
- **Customer names or environment values in the identifier**: These values belong in
  `*.tfvars` and the tag map, not in the resource name.
- **Inline naming logic in Python**: The app reads identifiers from environment variables;
  `infra/` decides names at plan time.

## Terraform State Root Convention

Every production Terraform root has one stable root id, one environment-scoped backend key, and
one scheduled drift plan. The deployment contract currently contains seven roots:

| Root class | Count | Backend key pattern |
|------------|-------|---------------------|
| Legacy platform | 1 | `fdai-<environment>.tfstate` |
| Independent service | 5 | `services/<service>/<environment>.tfstate` |
| Ops bootstrap | 1 | `ops/bootstrap/<environment>.tfstate` |

The first bootstrap apply may use local state only while it creates the private backend. After
migration, the remote bootstrap key is authoritative. Adding a production root without a unique
backend key and drift-plan coordinate is not supported. Drift checks fail when evidence is missing
or unreadable; they never omit a registered root and report success.

The Core and Operator service roots receive the semantic-turn request and projection topic names
as environment-scoped Terraform inputs. Terraform passes the reviewed names through
`FDAI_SEMANTIC_TURN_REQUEST_TOPIC` and `FDAI_SEMANTIC_TURN_PROJECTION_TOPIC`; application code does
not derive, rename, or substitute these cross-service channels. Each Container App receives each
name once, so a legacy literal cannot shadow the Terraform-selected topic.
The root variable and its child service module declare the same optional `semantic_requests` and
`semantic_projections` fields. They also declare `semantic_physical`, the provisioned Event Hub
that carries both logical topics. The default physical topic is `fdai.pantheon.objects`, whose
existing logical-topic envelope and `.dlq` sibling preserve schema isolation, stable partition
keys, per-logical-topic hashed consumer groups, and dead-letter routing without consuming another
Event Hubs entity. The logical request and projection names remain distinct contract and
configuration values; neither becomes a standalone Azure Event Hub. Both independent roots must
pass `terraform validate` before state migration or a protected plan; a root-only field that the
child module drops is a deployment contract failure, not an optional runtime degradation.
Local runtime preparation carries the same bootstrap, logical names, and physical-topic marker into
the independent Operator environment; a partial triplet stops before either service starts.
Operator and document-ingestion migration Jobs each accept a separate digest-pinned migration
image. Empty values preserve the corresponding service image for compatibility; protected deploys
bind reviewed migration digests so schema advancement does not depend on runtime image cadence.

The Operator App image and its one-off schema migration image are independently digest-pinned.
The migration image must contain the database's current Alembic revision set; an unset migration
image falls back to the App image only for backward compatibility, not as a promotion shortcut.

The Operator module also declares `caj-<workload>-catalog` as a separate manual Container Apps Job.
It uses the digest-pinned Core image that owns the reviewed Rule and Ontology catalogs. The deploy
workflow starts it only after `caj-<workload>-migrate` succeeds. Both Jobs use the Operator managed
identity and PostgreSQL secret reference, but catalog materialization creates reference projections
only; it does not create detected runtime issues, readiness, or execution authority.

After Core state ownership moves to `services/core-control-plane/<environment>.tfstate`, the
legacy platform root retains the shared Container Apps environment and scheduled Jobs but no
longer declares the Core Container App resource. Its deterministic Core name remains available for
health and effect checks, and monitoring constructs the live ARM id from that name. The historical
source address remains only in the state-migration manifest and the legacy-plan guard. A platform
plan that proposes any create, update, replacement, or delete at that address is blocked.

The legacy platform root may retain the isolated Executor wrapper only as a rollback-compatible
deployment surface. That wrapper binds both `service_distribution` and `service_entrypoint` to
`fdai-isolated-executor-service`; empty or co-located Core values fail the module precondition before
a plan can be approved. After all five runtime state moves, every legacy Container App resource is
inactive while the Operator and ingestion migration Jobs remain legacy-state owned. Deployment
verification reads the independent Apps' live FQDNs from Azure by deterministic name; it never
reintroduces their resources into the platform state.

## Resource Tagging Convention

Naming makes a resource readable; tagging makes a fleet queryable. Every resource this
repo provisions carries a small, machine-parseable tag set. All FDAI-owned keys are
namespaced under the `fdai:` prefix so the whole set is grep-able and FDAI-provisioned
resources are unambiguous even in a **shared subscription** where other teams' resources
sit side by side. The tag map is decided in Terraform (`infra/main.tf` `base_tags`), never
computed in Python.

### Base tag set

| Tag key | Value | Source | Purpose |
|---------|-------|--------|---------|
| `fdai:managed` | `true` | constant | **Ownership marker.** The single authoritative "FDAI provisioned this" flag. `az resource list --tag fdai:managed=true` enumerates exactly what FDAI owns - the basis for blast-radius scoping, cleanup/audit cross-checks, and cost attribution. |
| `fdai:workload` | `fdai` | `var.workload` | Product/workload token; mirrors the CAF name token. |
| `fdai:env` | `day-zero` / `dev` / `staging` / `prod` | `var.env` | Environment. `day-zero` is the unqualified deployment. |
| `fdai:layer` | `control-plane` / `ops-bootstrap` | per-config | Architectural layer - the app spoke (`infra/main.tf`) vs the ops/hub bootstrap (`infra/bootstrap`). |
| `fdai:managed-by` | `terraform` | constant | Provisioning tool. |
| `fdai:vertical` | `shared` / `resilience` / `change-safety` / `cost-governance` | `var.cost_vertical` (default `shared`) | AIOps vertical the resource's cost is attributed to. Cross-vertical control-plane infra stays `shared`; per-vertical resources (e.g. the three executor MIs) override this key. |

### Why `fdai:managed` matters

The executor may run inside a subscription that also hosts resources FDAI does not own.
The ownership marker lets the control plane draw that boundary. It is the query key these
capabilities rely on, not behavior hardcoded by one script:

- **Impact scoping**: The safety invariant that an autonomous action must bound its target
  set is expressed against `fdai:managed=true`, so a fix can be constrained to resources
  FDAI created and never reach one it did not.
- **Cleanup and audit**: `terraform destroy` already removes the provisioned fleet by state.
  The marker is the out-of-band cross-check that lets a sweep or audit confirm a resource
  belongs to FDAI before it is ever considered for deletion.
- **Cost attribution**: Cost Management and Resource Graph can group spend by `fdai:vertical`
  and isolate the total FDAI footprint as the `fdai:managed=true` slice.

### Deployment-supplied tags (`additional_tags`)

Customer- and environment-specific keys are never hardcoded in `base_tags`. A deployment
supplies them through the `additional_tags` map in its uncommitted `*.tfvars`, keeping the
`fdai:` namespace:

```hcl
additional_tags = {
  "fdai:cost-center"         = "cc-1234"
  "fdai:owner"               = "team-platform"
  "fdai:criticality"         = "high"
  "fdai:data-classification" = "internal"
}
```

`additional_tags` is merged on top of `base_tags`, so a deployment can also override a base value
(e.g. pin `fdai:vertical`) without editing core.

### Per-resource overrides

A module invocation may narrow a single key with a local `merge` - e.g. the per-vertical
executor MIs set `merge(local.tags, { "fdai:vertical" = "resilience" })`. Use the same
`fdai:` namespace so a resource never carries two competing keys for one concept. Reserve
`fdai:component` for the CAF component token when one resource kind is provisioned more than
once (e.g. `core` vs `worker`), mirroring the naming convention above.

### Rules

- **Use the `fdai:` namespace for all FDAI keys**: A bare `env` or `vertical` key collides
  with other teams and defeats the grep-ability guarantee.
- **Keep customer and secret values out of `base_tags`**: These values belong in
  `additional_tags` from uncommitted `*.tfvars`, exactly like deployment-specific names.
- **Keep query values stable and lowercase**: Cost Management and Resource Graph group on
  literal values such as `true`, `dev`, and `resilience`; drift breaks aggregation.

## Related docs

| To learn about | Read |
|----------------|------|
| The concrete resource inventory and bootstrap sequence | [Deploy and Onboard](deploy-and-onboard.md) |
| The deployment lifecycle and environment model | [Deployment](deployment.md) |
| Customer-agnostic deployment configuration | [Customer-Agnostic Scope](../../../.github/instructions/generic-scope.instructions.md) |
