---
title: Runtime Parity - Authoritative Local Development and Test Fixtures
---
# Runtime Parity - Authoritative Local Development and Test Fixtures
**Goal**: automated tests remain deterministic and secret-free, while every interactive local Console session shows the operator's actual Azure development environment. Azure deployment still uses the **deployer's Azure permissions + region catalog to decide which LLM and other resources are provisioned**. Three truths hold at the same time:

- **Automated-test truth**: pytest and committed mocks may bind deterministic fakes. They use an explicit test-fixture builder and never represent observed Azure state.
- **Full-stack local truth**: `Console Web: Full Stack` uses browser Entra sign-in with the same App Role checks as deployment. The server's Azure CLI session supplies provider credentials for the Azure development data plane only. Inventory, model availability, agent activity, Process state, promotion evidence, and audit data appear only from authoritative providers. Missing sources render unavailable or explicitly empty; the Console never substitutes generated examples.
- **Deploy truth**: `terraform apply` provisions the Azure-side realizations of the CSP-neutral contracts. The **LLM subset is deployer-scoped**: the bootstrap resolver queries the deployer's identity against the target region's catalog, provisions **only what the deployer has permission to create**, and records the resolved `{capability → deployment}` mapping plus resolver input provenance in the artifact.

All profiles share **one control path**: only composition-root adapters and credentials differ ([project-structure.md § Customization via Dependency Injection](../architecture/project-structure.md#customization-via-dependency-injection)). Its reviewed docstring records the existing boundary and does not create a runtime, change state ownership, or allow fixtures. Adding a real Azure client is a fork-side injection; it MUST NOT edit `core/`.

## Implementation status
### Implementation scope
| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Automated-test fixture isolation | implemented | `tests/`, `console/tests/`, and the fixture-only composition paths exercised by the repository test suites | Deterministic fixtures remain outside authoritative interactive profiles. |
| Authenticated live Console route assurance | in-progress | `console/playwright.live.config.ts`, `console/tests/live-e2e/operator_service.py`, `console/tests/live-e2e/console-routes.spec.ts`, and `console/tests/live-e2e/ontology-query-assurance*.ts`; focused route checks and provenance tests passed | A governed artifact binds the exact source revision, canonical run-configuration digest, workspace patch digest, authentication attestation, and per-turn request and projection ids. The full route, ontology cohort, and critique rounds remain open. |
| Live observation consumer isolation | implemented | `services/operator-service/src/fdai_operator_service/environment.py`, `services/operator-service/src/fdai_operator_service/composition.py`, `console/tests/live-e2e/operator_service.py`, and focused regressions; 41 tests passed | `FDAI_LIVE_STAGE_CONSUMER_GROUP_ID` binds each independently running Operator process or replica to a distinct group. The E2E launcher always replaces inherited values with a UUID-scoped group. |
| Agent refresh latest-state hydration | validated | Focused stream tests: 9 passed; authenticated `/agents` reloads reached `Watching 2 / Idle 13 / Unobserved 0` in 224 ms, 232 ms, and 228 ms | The Agent hub seeds one latest validated `agent.state` event per agent into each new subscriber. Generic Live remains future-only, and neither hub provides durable history replay. |
| Authenticated local Live event path | validated | Controlled 2026-08-13 Browser Entra run through `aw.change.events`, Core, `aw.pipeline.stages`, Operator SSE, and the existing authenticated Live DOM | The run preserved the authoritative ontology and rendered the event plus all four accepted stages. It did not validate a deployed revision, the browser Notifications API, or closed-browser push delivery. |
| Local control-loop change-event ingress | validated | `.vscode/tasks.json`, `infra/modules/compute/container-apps/inventory_job.tf`, `tests/integration/infra/test_inventory_repair_wiring.py`; one local run published 5 authoritative `inventory.resource_changed` events and the authenticated Live surface reported `Runtime observed` with `5 routed events` | The local inventory reconciliation task binds `FDAI_INVENTORY_RECOVERY_DELTA=1` exactly as the VNet-integrated deployed job does, so the Activity Log delta reaches `aw.change.events` in both venues. The deployed job still disables the delta when no infrastructure subnet exists. |
| Local and deployed composition parity | implemented | `.vscode/tasks.json`, `.vscode/launch.json`, `scripts/deployment/local/`, `infra/`, `fdai_operator_service/composition.py`, service integration tests, and focused Operator checks (`51 passed`) | Composition roots select credentials and adapters without changing evidence authority. Local and deployed Operator composition register the same Reader-scoped `GET /browser-evidence` route and authoritative data-source identity; missing PostgreSQL remains unavailable rather than synthetic. |
| Standalone A3 channel-edge parity | implemented | `channel_edge/`; `prepare-channel-edge-env.sh`; `.vscode/tasks.json`; `infra/services/operator-service`; platform edge identity/RBAC; focused edge and local-launch checks | Both venues run the same Operator-distribution ASGI factory, PostgreSQL stores, semantic EventBus bridge, provider routes, and readiness logic on port 8014. Local uses private 0600 provider input and Redpanda; deployed uses Key Vault references, Event Hubs Kafka, and a dedicated non-executor Managed Identity. Missing provider configuration leaves the optional capability unavailable rather than synthetic. |
| Explicit primary-worktree full-stack startup | implemented | `.vscode/tasks.json`, `prepare-console-full-stack.sh`, `start-console-services.sh`, `run-console-service.sh`, `developer-workflow.py`, and focused startup contract tests | Folder-open no longer runs migrations, authoritative refreshes, or application services. Preparation restores local dependencies, reuses seven independently fingerprinted stages, and doesn't require a running stack for cache reuse. The supervisor releases the start caller after process spawn, continues the complete readiness gate, and exposes an explicit wait task. |
| Optional ten-minute local recovery watchdog | implemented | `.vscode/tasks.json`, `watch-console-services.sh`, `developer-workflow.py`, and focused workspace task contracts | The singleton task checks the six-component readiness contract every 600 seconds. It skips a healthy stack and uses the standard preparation and supervisor paths on failure, preserving the fixed local ports and service ownership rules. |
| Local diagnostic logging resilience | implemented | `capture-local-service-log.py`, `fdai.shared.telemetry.logging`, and focused telemetry and launcher checks | Warning retention appends without per-record compaction, local file capture is isolated from terminal backpressure, oversized records are bounded, and repeated dependency failures preserve first, periodic, and distinct-failure evidence. |
| Folder-open dev-access route stabilization | implemented | `tools/dev-access/scripts/vscode-startup.sh`; `tests/integration/infra/test_dev_access.py`; focused dev-access tests | The task opens Azure VPN Client at most once, retries the mirrored WSL route eight times over a bounded seven-second grace window, applies DNS after a direct route appears, and retains exit `20` for a real disconnect. Workstations without local state and direct-VNet machines remain quiet. |
| Repository-scoped roadmap campaign capacity | implemented | `roadmap_verification_watchdog.py`, `test_roadmap_verification_watchdog.py`, and the randomized campaign operator contract in `scripts/README.md` | FDAI session leases and recent Copilot activity are both counted only for this repository. Linked worktrees resolve the primary checkout before deriving the VS Code workspace id. Another workspace cannot hold FDAI work, while the 900-second activity window and two-session campaign ceiling still protect concurrent FDAI editing. |
| Semantic planning tier parity | implemented | `composition/semantic_query_model_targets.py`; `composition/wire_semantic_query.py`; resolved model artifacts; focused tier-routing and composition tests | Local and deployed Core load the same capability artifact, bind the resolved narrator or `t1.judge` pool as T1, and keep T2 optional. Only an unavailable or deterministically invalid T1 proposal can retry its stage with T2. |
| Permission-aware observation campaign parity | implemented | `config/observation-sources.yaml`; `fdai.delivery.observation_campaign*`; `.vscode/tasks.json`; `infra/modules/compute/container-apps/observation_campaign_job.tf`; focused Core, Operator, Console, workspace, and infrastructure checks | Local and deployed profiles use the same source catalog, due state, runner, normalized activity contract, and one-minute wake. Runtime artifacts are still required before validation. |
| Local validation database isolation | implemented | `infra/local/docker-compose.yml`, `scripts/automation/validation_queue_context.py`, local preparation scripts, and focused validation and migration integration tests | Runtime state stays on local PostgreSQL port `5432`; destructive migration validation uses a separate local PostgreSQL cluster on port `5433`. |
| FDAI workspace and profile pressure controls | implemented | `.vscode/settings.json`, `.vscode/fdai.code-profile`, `scripts/automation/configure-vscode-profile.py`, `tests/integration/scripts/test_vscode_workspace_performance.py`; focused profile and workspace checks | Resource-scoped analysis controls stay in the workspace, and shared configuration retains only settings owned by selected extensions. Copilot compacts agent history at 80% of the selected model's context window, the portable profile rejects Remote WSL Pylance machine settings that it cannot isolate, and nonzero terminal exits remain observable without a duplicate VS Code toast. |
| Isolated Console E2E developer loop | implemented | `console/playwright.config.ts`, `console/playwright.live.config.ts`, `console/scripts/playwright-port-pool.ts`, its focused tests, and the Playwright guidance in `.github/skills/vscode-profile-onboarding/SKILL.md`; Console typecheck and concurrent focused desktop E2E passed | Each session atomically leases one of ten frontend/API port pairs, shares it with workers, isolates artifacts by slot, and reclaims exited-PID locks without changing the full desktop and mobile matrix. |
| Same-checkout backend startup reuse | implemented | `local-service-input-digest.py`, `run-local-service.sh`, `run-local-service-child.py`, `developer-workflow.py`, `.vscode/tasks.json`, and focused launcher and workspace task tests | Reuse requires an exact service-source, private-environment, dependency, supervision-code, and launch-command fingerprint. A stale managed task is replaced automatically. Startup then requires all six standard local components, including a fresh Core heartbeat, to pass bounded readiness. Shutdown escalates after a bounded grace period. A port or runtime lock owned outside the checkout still fails startup. |
| FDAI Pylance launch ceiling runtime proof | deferred | A clean FDAI Remote WSL restart still launched Pylance with the bundled VS Code Node executable and without `--max-old-space-size=2048`. VS Code Server 1.133 creates one Remote Machine settings resource independently of the active profile service. | Blocked pending an isolated runtime. A shared Remote Machine override would also affect excluded workspaces, so runtime isolation requires a separate VS Code Server data root or WSL distribution before the ceiling can be enabled. |

### Implementation history
| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-25 | implemented | Restored the Core service root's required `llm` object forwarding to its child module. The protected root now validates before planning and the deployed environment remains bound to the exact attested model configuration. | `current change`; Core Terraform validation and focused service-deploy contract check. | Recreate the exact protected Core plan before apply. |
| 2026-08-25 | implemented | Added the optional `console: keep full stack ready (10m)` task. It applies the existing bounded six-component readiness check every 600 seconds, emits a skip for a healthy topology, and enters the standard preparation and supervisor path only when readiness fails. | `current change`; `.vscode/tasks.json`; `scripts/deployment/local/watch-console-services.sh`; `tests/integration/scripts/test_vscode_workspace_performance.py`; focused workspace contract tests passed 4 cases; shell syntax and VS Code diagnostics passed. | No implementation work remains for the optional local recovery watchdog. |
| 2026-08-24 | implemented | Removed Microsoft Terraform language-server settings from the HashiCorp-only workspace and portable profile, and removed unused Live Server settings from the workspace. The context-usage indicator remains enabled as designed. | `current change`; `.vscode/settings.json`; `.vscode/fdai.code-profile`; focused profile and workspace contract tests passed 13 cases. | No remaining implementation work for extension-owned shared settings. |
| 2026-08-23 | implemented | Decoupled preparation cache validity from runtime health, split preparation into seven ordered stage fingerprints, and made Docker volume identity invalidate database-backed stages. Full-stack start now returns after supervised process spawn while the supervisor continues the 60-second gate; `console: wait full stack ready` provides an explicit blocking check, and Core-only recovery waits for a fresh Pantheon heartbeat. | `current change`; `.vscode/tasks.json`; `scripts/automation/{developer-workflow.py,local-service-input-digest.py}`; `scripts/deployment/local/{prepare-console-full-stack,prepare-console-state,start-console-services,run-console-service}.sh`; focused startup contract suites passed 38 cases; shell syntax and VS Code diagnostics passed. | No remaining implementation work for the bounded local startup response path. |
| 2026-08-22 | validated | Extended the clean Console startup readiness gate from 15 seconds to 60 seconds so Core Runtime can complete bounded provider initialization and emit its first Pantheon heartbeat. Replaced unbounded Bash `/dev/tcp` ownership checks with 250 ms IPv4 and IPv6 socket probes that close the inherited service lock before connecting, so a filtered loopback port cannot retain an owner-only lock past the readiness deadline. | [Issue #254](https://github.com/dotnetpower/fdai/issues/254); `current change`; `scripts/automation/run-local-service.sh`; `scripts/deployment/local/start-console-services.sh`; focused launcher and workspace task contracts passed 28 tests; a clean standard start reached 6/6 readiness and HTTP 200 on ports 5273 and 8010-8013 with all six managed locks held. | No remaining work for #254. |
| 2026-08-22 | implemented | Replaced folder-open full-stack startup with the explicit `console: start full stack` task, consolidated nine single-caller preparation tasks, and replaced eight service task blocks plus the separate readiness task with one supervisor. The supervisor retains one allowlisted launcher, lock, fingerprint, log, and process lifecycle per service. The task inventory fell from 29 to 11. | `current change`; `.vscode/tasks.json`; `scripts/deployment/local/{prepare-console-full-stack,start-console-services,run-console-service}.sh`; focused workspace task contract passed 4 tests; all three scripts passed `bash -n`. | Run the explicit full-stack task when the Console topology is needed. |
| 2026-08-21 | implemented | Scoped critical model completeness checks to plans that can change cognitive deployments. Development-gateway targeted plans still converge the existing model account and caller RBAC, but skip unrelated model resolution because their target set contains no cognitive deployment. | `current change`; `.github/workflows/deploy-dev.yml`; focused model-lifecycle and protected-workflow tests; protected runs `32435485872` and `32435748272` exposed the pre-Terraform mismatch. | Rerun the exact Event Bus migration plan; design a separate Foundry multi-publisher endpoint migration before changing the model registry. |
| 2026-08-21 | implemented | Corrected the development-gateway exception after its empty capability map implied deletion of an existing embedding deployment. Gateway-targeted plans now retain model resolution while making completeness findings non-blocking. | Protected plan run `32456242726`; `current change`; focused model-lifecycle and protected-workflow suites passed 44 tests. | Rerun the exact Event Bus migration plan and require no model deployment change before apply. |
| 2026-08-21 | implemented | Filtered `hil-only` resolver records from the Terraform capability input while retaining them in the sealed evidence artifact. | Protected plan run `32460379091` exposed the boundary mismatch; `current change`; focused model-lifecycle checks passed 9 tests. | Rerun the exact Event Bus migration plan and require no model deployment change before apply. |
| 2026-08-19 | implemented | Removed warning-log write amplification and local terminal backpressure from the service hot path. Warning records append under a bounded cross-process lock, compaction runs on a shared five-minute cadence, structured records and terminal buffers have byte ceilings, and repeated aiokafka or Pantheon observer failures retain distinct first and periodic evidence plus recovery counts. | `current change`; focused telemetry, launcher, provider-integration, and framework-layout checks; 16 critique rounds left no finding above Low. | Live processes must restart before they use this revision. Runtime exit-gate and deployment evidence remain unchanged. |
| 2026-08-19 | implemented | Applied the same four-complete-window catch-up bound to local and deployed jobs. The first local live run showed that an unbounded sequence of individually bounded windows could still consume the source-level timeout before a terminal cursor write. | [Issue #217](https://github.com/dotnetpower/fdai/issues/217); the pre-bound local run reported `source_timeout`; focused shared-provider and runner checks pass 31 cases after the bound. | Retain completed local and deployed-revision campaign evidence. |
| 2026-08-19 | implemented | Kept Activity Log backlog recovery identical in local and deployed observation jobs. Both use the same timestamp-only adaptive windows, complete-window cursor checkpoints, 10,000-result and 2,000,000-byte ceilings, and immediate `source_catchup` continuation while retaining normal intervals for unrelated failures. | [Issue #217](https://github.com/dotnetpower/fdai/issues/217); focused provider and runner checks pass 30 cases; the behavior remains in the shared source catalog and campaign package. | Retain the completed local campaign, then obtain the existing open deployed-revision campaign evidence. |
| 2026-08-19 | implemented | Stopped the venue gate's own scope from shrinking silently. `main([])` reports only the trees it was handed and its test asserted the exit code alone, so deleting a row from `SCANNED_TREES` would have kept the gate green. A test now derives the expected set from the repository layout and immediately found `services/core-control-plane/src/fdai_core_service` unscanned, because the core service ships two packages. The gate covers 7 trees; that package contained no violation, so this closes a coverage hole rather than a defect. | `current change`; `tests/integration/scripts/test_venue_capability_contract.py` passed 5 cases, and the new test failed with `core-control-plane has 2 source packages` before the table was corrected; the gate reports OK across 7 source trees and all ten pre-push structural gates passed. | The gate's detection stays textual, so an indirect reintroduction through a computed key is still not caught. |
| 2026-08-19 | implemented | Added one bounded grace window to the folder-open dev-access task after a WSL restart exposed a transient route as a disconnected-VPN warning. Azure VPN Client opens once; a direct route ends the retry immediately and applies WSL DNS; an indirect route after eight probes still reports the existing actionable error. | `current change`; behavioral startup harnesses cover immediate readiness, recovery on the third probe, and permanent disconnect with one client launch, eight retries, seven waits, no DNS apply, and exit `20`. | No implementation work remains for transient folder-open route propagation. Private endpoint diagnosis still uses the explicit `doctor.sh` targets. |
| 2026-08-17 | validated | Materialized the reviewed ActionType palette and workflow catalog into `operator-projection:workflow:workflow.action-type-list` and `workflow.catalog`, so Workflow builder renders declared building blocks instead of an unavailable state. | Current change; `test_materialize_authoritative_catalogs.py` 5 passed; an authenticated `/workflow-builder` load rendered 48 ActionTypes and 12 workflows with their triggers, step counts, and modes. | Surfaces backed by runtime evidence rather than a reviewed declaration still answer `503`. |
| 2026-08-17 | validated | Materialized `operator-projection:operations:stewardship.coverage` from the reviewed `config/agent-stewardship.yaml` through the existing Core coverage report, so Agent oversight renders measured ownership instead of an unavailable state. | Current change; `test_materialize_authoritative_catalogs.py` 3 passed including a console-contract invariant test; an authenticated `/agent-oversight` load reported `AGENTS 15`, `MAINTAINERS 2`, `AUTONOMOUS 1`, and the Core-computed finding table with no unavailable block. | Surfaces whose evidence is produced at runtime rather than declared in the repository still answer `503`. |
| 2026-08-17 | implemented | Removed operator-facing remediation copy that named `OperatorApiConfig.<field>`, a symbol that exists nowhere in this repository, across the stewardship, workflow authoring, promotion gate, rule catalog, ontology, and pantheon panels. | Current change; focused console checks passed 71 tests across 9 files, Console typecheck clean, catalog key parity held for all five affected pairs, and an authenticated pass over the six panels rendered no reference to the removed symbol. | Wiring those routes remains separate work; the panels now state only the observable condition. |
| 2026-08-17 | validated | Declared the remaining unserved read surfaces (`/capabilities`, `/skills`, `/forecast-learning`, `/operator-memory`) and stopped the conversation assurance panel from rendering a raw transport code. | Current change; focused Operator composition tests `50 passed`, Console typecheck clean, assurance catalog key parity checked; an authenticated pass over the Agents, Governance, Evidence, and Settings submenus left no `404` and no raw `HTTP nnn` in any rendered body. | None for this surface set. Registered routes whose projection is unwired still answer `503` with a server-owned reason. |
| 2026-08-17 | validated | Declared the unserved `/onboarding`, `/configuration-baselines`, and `/conversation-delivery` surfaces, each owning its own source so a panel renders a reason about itself. | Current change; focused Operator composition tests `50 passed`; an authenticated pass over all 13 Operations screens produced no error alert, no `404`, and no raw transport code in the rendered body. | Decide whether the lost onboarding, baseline, and delivery capabilities are rebuilt behind the service boundary; they previously imported Core providers directly. |
| 2026-08-17 | validated | Declared the unserved `/finops` and `/kpi/autonomy` measurement surfaces in the read data-source registry, and tolerated the registry's `503` signal in the optional Overview projections. | Current change; focused Operator composition tests `49 passed` and Console dashboard-loading tests `3 passed`, both mutation-verified; an authenticated pass over the six Overview screens produced no error alert and removed every `404`. | Materialize or retire the `promotion-gate.list` projection, which has a reader but no writer in this distribution. |
| 2026-08-13 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance, and moved machine-scoped Pylance launch controls to the FDAI profile. | Current change in `.vscode/fdai.code-profile`, `.vscode/settings.json`, `scripts/automation/configure-vscode-profile.py`, and focused profile/workspace tests: 9 passed. | Record the FDAI Pylance process argument and centralized validation receipt. |
| 2026-08-13 | deferred | Removed the ineffective Pylance machine settings, rejected duplicate profile JSON keys, and added a contract that prevents their return. | A clean Remote WSL process command lacked the configured heap argument; focused profile and workspace tests: 11 passed. | Use a separately rooted VS Code Server or WSL distribution, then prove the heap argument from the restarted process command. |
| 2026-08-13 | implemented | Added a dedicated local PostgreSQL cluster for destructive validation and taught the detached validation queue to load only its generated DSN. | Current change; Compose config passed, focused queue and local-env tests passed (68 tests), and the isolated migration upgrade/downgrade checks passed (2 tests). | No remaining implementation work for local validation database isolation. |
| 2026-08-13 | in-progress | Replaced the live Console test's retired backend path with an independent Operator Service using production adapters and test-only bearer verification, then moved the isolated stack to IPv6 loopback so readiness failures remain bounded. | Current change in `console/playwright.live.config.ts`, `console/tests/live-e2e/operator_service.py`, and `console/tests/live-e2e/console-routes.spec.ts`; focused Overview check: 1 passed in 5.1 seconds. | Run all 50 registered routes, then complete at least 10 assurance rounds and 10 critique/hardening rounds until only Low-or-lower findings remain. |
| 2026-08-13 | in-progress | Made the capability catalog distinguish an optional missing projection from an unexpected failure and constrained the live exception to `404 /capabilities`. | Current change in `console/src/routes/capabilities.tsx`, `console/src/routes/capabilities.test.ts`, and `console/tests/live-e2e/console-routes.spec.ts`; focused unit tests: 7 passed; focused authenticated live check: 1 passed. | Repair the remaining failing routes, then complete the open assurance and critique/hardening rounds. |
| 2026-08-13 | validated | Bound the Live observation consumer group through the Operator environment and composition, isolated the E2E launcher with a UUID-scoped group, and proved the authenticated local event path from canonical ingress to the existing Live DOM. | Current change in the Operator environment, composition, launcher, and focused regressions; 41 tests passed. Controlled Browser Entra evidence rendered the event and all four accepted stages. | Record equivalent evidence from a deployed revision. Browser Notifications API and closed-browser push delivery remain outside this evidence. |
| 2026-08-13 | in-progress | Bound ontology assurance artifacts to exact source, configuration, workspace, authentication, request, and projection provenance before they can become governed evidence. | Current change in `console/tests/live-e2e/ontology-query-assurance*.ts`; focused Vitest: 25 passed; Console typecheck passed. | Obtain the exact centralized validation receipt, then run one authenticated probe before the seeded bilingual 100-case cohort. |
| 2026-08-13 | implemented | Added a trusted-workspace aggregate task that prepares local state once and starts all five backend services plus the Console SPA without per-service confirmation clicks. | Current change in `.vscode/tasks.json` and `tests/integration/scripts/test_vscode_workspace_performance.py`; focused workspace task tests: 3 passed. | No remaining implementation work for automatic local full-stack startup. |
| 2026-08-13 | implemented | Added preparation-time materialization of reviewed Rule and Ontology catalogs for both local startup and deployed Operator state. | Current change in `.vscode/tasks.json`, `scripts/deployment/local/materialize-authoritative-catalogs.py`, `infra/modules/operator-api/container-app/`, and `.github/workflows/deploy-dev.yml`; focused materializer, Operator, and deployment tests passed. | Record protected deployed evidence that migration completes before catalog materialization. |
| 2026-08-13 | implemented | Added race-safe, process-local latest-state hydration for new Agent SSE subscribers while preserving future-only generic Live delivery. | Current change in the Operator stream hub, composition, and focused regressions; stream tests: 9 passed; Ruff passed for all touched Python files. | Validate immediate Agent fleet hydration in the authenticated browser session. |
| 2026-08-13 | validated | Verified immediate Agent fleet hydration through the existing authenticated Browser Entra session after restarting the Operator with the changed code. | Three `/agents` reloads reached `Watching 2 / Idle 13 / Unobserved 0` in 224 ms, 232 ms, and 228 ms, well below the 15-second runtime heartbeat interval. | No remaining implementation work for Agent refresh latest-state hydration. |
| 2026-08-13 | implemented | Replaced the fixed 160000-token Copilot agent-history compaction threshold with 80% of the selected model's context window. | Current change in `.vscode/settings.json` and `tests/integration/scripts/test_vscode_workspace_performance.py`; VS Code JSON diagnostics passed, and the focused compaction contract test passed (1 test). | No remaining implementation work for proportional Copilot conversation compaction. |
| 2026-08-14 | implemented | Made repeated automatic full-stack task requests preserve each running singleton instead of opening the VS Code task-instance picker. | Current change in `.vscode/tasks.json` and `tests/integration/scripts/test_vscode_workspace_performance.py`; the focused automatic-start contract test passed (1 test). | No remaining implementation work for click-free duplicate startup requests. |
| 2026-08-14 | implemented | Added one permission-aware observation campaign for every registered source and wired the same due-checked CLI into full-stack local and the deployed Container Apps Job. | `current change`; versioned activity contract, source catalog, provider probes, persistent runner, Operator projection, Console lane, and focused checks. | Retain one governed local run and one deployed-revision run over the same catalog digest before claiming validation. |
| 2026-08-14 | implemented | Aligned mocked Terraform coverage with the retired ingestion co-host path and the independent Document Ingestion API and Document Processing Worker service roots. | `current change`; Terraform validation passed and focused ingestion tests passed 5 cases. | Keep the deployment guides and mocked tests aligned with the independent service roots. |
| 2026-08-14 | implemented | Removed the isolated Playwright startup probe stall and added direct desktop E2E entry points for the repository root and VS Code. | `current change`; Console typecheck passed, live discovery listed 58 tests from 4 `*.spec.ts` files, and the focused desktop E2E passed 1 test in 2.8 seconds. | No remaining implementation work for the isolated Console E2E developer loop. |
| 2026-08-14 | implemented | Added an atomic ten-slot port pool for concurrent fixture and live Playwright sessions, with paired frontend and Operator API ports plus slot-scoped artifacts. | `current change`; allocator tests passed 6 cases, Console typecheck passed, and two focused Playwright processes passed concurrently on frontend ports `5274` and `5275` with no remaining listener or lock. | No remaining implementation work for concurrent isolated Playwright port allocation. |
| 2026-08-14 | implemented | Aligned local and deployed semantic planning on one T1-first model cascade instead of binding T2 as the initial planner. | `current change`; focused planner and composition checks pass on the same resolved artifact contract used by both venues. | Retain governed local and deployed records of T1 selection and bounded T2 escalation. |
| 2026-08-15 | implemented | Added the same payload-free browser-evidence metadata route and data-source ownership to local and deployed Operator composition. | `current change`; focused Operator checks `51 passed`; Operator boundary and independent-service gates passed. | Retain one authenticated deployed read receipt and add the Console metadata panel. |
| 2026-08-15 | implemented | Restricted folder-open full-stack startup to the primary checkout after two linked workspaces raced for the standard Console, Operator, and Core processes. | Current change in `.vscode/tasks.json` and `tests/integration/scripts/test_vscode_workspace_performance.py`; focused automatic-start contract passed. | No remaining implementation work for linked-worktree automatic startup isolation. |
| 2026-08-15 | implemented | Made the local service launcher assert the singleton a service actually owns, so a run whose runtime lock or port already belongs to another instance stops before starting a doomed child. | `current change`; `scripts/automation/run-local-service.sh` and `tests/integration/scripts/test_run_local_service.py`; launcher tests passed 11 cases and both live backend tasks reported `service already running` instead of a provider stack trace. | The Console dev server is started directly by its task, so its port collision still surfaces as a Vite error. |
| 2026-08-15 | implemented | Replaced the per-job and per-app attempt-count products in deployment readiness polling with one cumulative migration deadline and one cumulative revision deadline. | `current change`; `.github/workflows/deploy-dev.yml`; focused workflow contract tests passed. | The remaining readiness waits stay provider-bound and are reported through their declared deadlines. |
| 2026-08-15 | implemented | Refused to start a migration job once the shared deadline left no budget to observe it, so a started job can no longer be abandoned unobserved. | `current change`; `.github/workflows/deploy-dev.yml`; focused workflow contract tests passed. | No residual work for migration observation bounds. |
| 2026-08-15 | implemented | Refused to start a migration job unless one poll cycle plus the ARM start round trip still fits inside the shared deadline. | `current change`; `.github/workflows/deploy-dev.yml`; focused workflow contract tests passed. | The margin is a fixed 45-second estimate, so a start slower than the margin can still be reported as incomplete while the job runs; the step fails loudly rather than silently. |
| 2026-08-15 | implemented | Corrected the evidence in the deadline and margin rows above: no focused test asserts those values, so the workflow was verified by YAML parsing and the deployment contract suites while the bounds are enforced by the step itself. | `current change`; `deploy-dev.yml` parses as valid YAML and the script integration suites passed 1151 cases. | A focused assertion on the declared deadline values remains open. |
| 2026-08-17 | implemented | Made roadmap automation session capacity repository-scoped. The default WSL workspace-storage id is derived from the canonical remote URI, an exact storage path can be supplied for other VS Code remotes, and recent activity in another repository no longer holds FDAI. | `current change`; `roadmap_verification_watchdog.py`, focused watchdog tests, and the operator contract in `scripts/README.md`. | No remaining work for campaign session scope. |
| 2026-08-17 | implemented | Corrected linked-worktree session counting. The original repository-scoped implementation hashed the campaign worktree path and found no VS Code storage, so a linked campaign could count zero FDAI sessions. It now derives the primary checkout from Git's common directory before hashing the workspace URI. | `current change`; `roadmap_verification_watchdog.py` and a real linked-worktree regression in `test_roadmap_verification_watchdog.py`; the focused watchdog suite passed 9 cases. | No remaining work for linked-worktree workspace identity. |
| 2026-08-17 | implemented | Restated the deployment README's trace-continuity sentence in the required display terms. A bare `finding` in operator-facing prose failed `display-terminology` inside central validation, which rejected main and stopped every lane and every landing. | `current change`; `infra/README.md` and the user-guide pair; `display-terminology` reports OK across 524 documents and translations verify 185/185. | None for this change. |
| 2026-08-17 | implemented | Isolated durable semantic outbox claims for alternate local Operator processes without changing the standard local or deployed namespace. A test-only Operator can bind `FDAI_SEMANTIC_TURN_OUTBOX_NAMESPACE` to its run id, while production defaults continue to share one replica-safe queue. | `current change`; focused environment, composition, repository lease, and runner checks passed 114 cases; strict mypy passed. | Retain exact-source Browser evidence from the namespaced assurance runner. |
| 2026-08-17 | validated | Bound the local venue to the same authoritative control-loop ingress as deployment. The Activity Log recovery delta was enabled for the deployed inventory job but left at its `False` default locally, so `aw.change.events` received nothing and the authenticated Live surface reported `Source unavailable` while every transport component was healthy. | `current change`; `.vscode/tasks.json` and `tests/integration/infra/test_inventory_repair_wiring.py`; focused infrastructure and constitution checks passed 14 cases; one local run published 5 authoritative `inventory.resource_changed` events that produced `ingest`, `route`, `verify`, and `audit` frames with `source: runtime-observed`, and the Live surface changed to `Runtime observed`. | Enumerate every remaining venue-selected capability flag in one contract instead of guarding each binding separately. |
| 2026-08-18 | implemented | Enumerated the venue-selected capability flags of the core control plane in one contract. `runtime/venue.py` resolves `FDAI_EXECUTION_VENUE` once and owns the transport-security, workload-identity, inventory-source, event-bus, and observation-transport bindings; `bootstrap.py` and the inventory, observation, and analyzer CLIs read from that table instead of comparing raw strings with per-site defaults. An unrecognized value is now rejected instead of resolving to the weaker local transport. `check-venue-capability-contract.py` fails on a reintroduced ad hoc read or literal comparison and runs in the pre-push structural gates, `verify.sh`, and CI. | `current change`; `tests/runtime` passed 209 focused cases; the gate's integration test passed 4 cases including two negative fixtures; `tests/delivery` passed 1489 cases; task-scoped Ruff, format, and strict mypy passed. | Bring the operator, document-ingestion, and document-worker services under the same contract; each still resolves the venue independently. |
| 2026-08-18 | implemented | Made the capability table load-bearing after review found three of its five entries had no production consumer, which meant the contract documented intent rather than selecting behavior. `inventory_source`, `event_bus_implementation`, and `observation_transport` are gone; the remaining two are split into `bus_identity_binding` and `workload_identity_source`, which name what they actually select, and the inventory, observation, and analyzer identity branches read the capability instead of comparing the venue enum. A focused test scans the source tree and fails when a declared capability has no accessor in production code, so the table cannot drift back into documentation. | `current change`; `tests/runtime`, `tests/delivery`, and the gate's integration test passed 1703 focused cases with 3 skips; task-scoped Ruff, format, and strict mypy passed; the venue contract gate passed. | Bring the operator, document-ingestion, and document-worker services under the same contract; each still resolves the venue independently. |
| 2026-08-18 | implemented | Brought every FDAI service under the same venue contract. The table moved to `packages/service-contracts/src/fdai_service_contracts/venue.py` because an independent service cannot import the core control plane, and `fdai/runtime/venue.py` now re-exports it. The Operator, Document Ingestion API, Document Processing Worker, and isolated Executor compositions read `resolve_execution_venue()` and the capability accessors instead of four private parsers with four different error types. `document_provider_binding` is a new capability with consumers in both document services, and `bus_security_protocol` now returns a literal type so a table edit to an undeclared protocol fails type checking rather than downgrading a transport. The gate scans all six source trees. | `current change`; `packages/service-contracts/tests`, `services/core-control-plane/tests/runtime`, `tests/integration/scripts/test_venue_capability_contract.py`, and all four independent service suites passed 874 focused cases with 1 skip; `tests/delivery` passed 1689 cases with 3 skips; task-scoped Ruff, format, and mypy passed; the venue gate reported OK across 6 source trees; `check-independent-services.py` passed. | The gate's detection stays textual, so an indirect reintroduction through a computed key is still not caught. |
| 2026-08-20 | implemented | Added local and deployed composition for the standalone A3 channel edge without changing the five-distribution topology. Both venues use the same Operator-owned runtime and differ only in provider credentials, Kafka security, secret source, and scale. | `current change`; focused edge checks passed 74 cases, local launch checks passed 3 cases, platform and Operator-service Terraform roots validated, and the independent-service check remained at five distributions. | Retain one governed local provider receipt and one protected deployed plan/apply/rollback receipt. |
| 2026-08-20 | implemented | Disabled VS Code's terminal exit alert in the FDAI workspace after diagnostics found a healthy PTY host and shell startup while the editor's default setting notified on nonzero exits from interacted integrated terminals. The change suppresses only the duplicate toast; terminal output, task status, and process exit codes remain observable. | `current change`; `.vscode/settings.json`; `tests/integration/scripts/test_vscode_workspace_performance.py`; focused workspace contract and VS Code JSON diagnostics. | No implementation work remains for the terminal exit toast. |
| 2026-08-20 | implemented | Aligned local and protected deployed migration failure bounds across the frozen legacy lineage and all five service-owned branches. Every connection has a 10-second deadline, every database lock wait has a 5-minute deadline, and one protected migration stage has a cumulative 20-minute deadline before Terraform apply. | `current change`; focused migration, A3 route, and protected deployment checks passed 282 cases with 1 environment-gated skip; all three migration entry points passed strict mypy. | Retain the successful exact Core apply and post-apply health receipt. |
| 2026-08-20 | implemented | Added the same 15-minute PostgreSQL statement deadline to local legacy migration, local service-branch migration, and protected service coordination. The server cancels long-running DDL before the 20-minute workflow deadline, so a disconnected runner cannot leave an abandoned transaction holding the cross-service advisory lock. | `current change`; focused migration deadline checks; all three entry points passed strict mypy; disposable PostgreSQL canceled an over-budget statement and reported zero advisory locks after disconnect. | Retain the successful exact Core apply and post-apply health receipt. |
| 2026-08-20 | implemented | Moved question-campaign table creation from the legacy compatibility head to the Core service branch. Both local preparation and protected deployment now converge through the same single writer whether legacy `0086` or the Core branch runs first. | `current change`; service migration inventory checks; disposable PostgreSQL passed both migration orders; fresh adoption passed for all five services. | Retain the successful exact Core apply and post-apply health receipt. |
| 2026-08-20 | implemented | Made automatic backend startup reuse a process that still owns this checkout's service log lock after VS Code loses task-instance metadata. The reuse path emits a terminal marker and doesn't spawn another child. A final 15-second gate requires Core ownership plus successful Console, Operator API, Document Ingestion API, Document Processing Worker, and isolated Executor probes. Port and runtime-lock ownership from another checkout remain startup failures. | `current change`; `scripts/automation/run-local-service.sh`, `developer-workflow.py`, `.vscode/tasks.json`, and focused launcher, readiness, and workspace task checks. | No implementation work remains for same-checkout backend task reconnection and post-start readiness. |
| 2026-08-20 | implemented | Hardened the reuse decision after review. Every runner records private 0600 metadata with a SHA-256 fingerprint over its service-owned source, generated environment, dependency declarations, supervision code, and exact launch command. A stale same-checkout runner is validated by cwd, service identity, owner PID, and child process group before automatic replacement; another checkout or unmanaged process is never adopted. The child shim makes its recorded PID the real session leader and receives `SIGTERM` if its wrapper dies. Core emits a two-second Pantheon heartbeat and readiness requires one no older than ten seconds. A service that exceeds the ten-second graceful shutdown window is force-stopped so it cannot retain the singleton lock indefinitely. | `current change`; focused launcher, digest, heartbeat, orphan-recovery, and workspace checks. Controlled local restarts reached 6/6 ready in one attempt, all seven metadata records matched live owners and exact child process groups, the measured Core heartbeat remained within 5.4 seconds, and ports `8010`-`8013` plus `5273` returned `200`. | No implementation work remains for stale-input reuse, Core liveness, parent-loss cleanup, or bounded local shutdown. |

### Remaining work
- [ ] Establish an FDAI-only Remote WSL server data root or WSL distribution, then record a restarted Pylance process command containing `--max-old-space-size=2048` without changing the excluded workspace.
- [ ] Record passing evidence for all 50 registered Console routes, then complete at least 10 assurance rounds and 10 critique/hardening rounds with no unresolved finding above Low severity.
- [ ] Record a deployed-revision event that reaches an authenticated Live DOM through a replica-specific `FDAI_LIVE_STAGE_CONSUMER_GROUP_ID`; track browser Notifications API and closed-browser push delivery separately if those capabilities enter scope.
- [ ] Record a protected deployment receipt showing the Operator schema migration succeeds before the catalog Job writes the reviewed Rule and Ontology reference projections.
- [ ] Retain a governed local and deployed observation campaign pair with the same catalog digest,
  including authorized, unavailable, partial, skipped, and completed source outcomes plus
  snapshot-first/live Agent Activity deduplication.
- [ ] Retain governed local and protected deployed A3 channel-edge receipts that prove the same
  webhook route, semantic terminal digest, provider acknowledgement class, and rollback outcome.
- [ ] Replace the venue gate's textual detection with an import-graph or AST check, so a venue
  read reached through a computed key or an indirect alias fails the same way a literal one does
  ([#152](https://github.com/dotnetpower/fdai/issues/152)).

## Audit - What Works Local, What Needs Azure
Snapshot as of 2026-07-21. "Automated test" means pytest or a committed mock invoked by the
test runner. "Full-stack local" means the VS Code compound launch using browser Entra for the
operator and the current Azure CLI context for server-side Azure adapters. Test fixtures are never
enabled by that launch profile.

### Fully working in automated tests (no Azure needed)
| Subsystem | Local backend | Notes |
|-----------|---------------|-------|
| T0 deterministic engine | `opa` binary + Rego policies + rule catalog | 100% offline; the CI parity gate proves this |
| Rule catalog loader + shadow eval pipeline | filesystem YAML | no cloud calls |
| Risk gate + promotion registry | in-memory `ActionPromotionRegistry` | seam swappable |
| Executor + resource lock | in-process | fixture-only; never an interactive executor |
| Audit + T2 recovery state | `InMemoryStateStore` (hash-chain verified) | prod backend = Postgres; the same receipt and route keys feed deterministic chat reads |
| Event ingest + trust router | in-process | no bus wired |
| Verticals (Resilience / FinOps / Change Safety) | pure decision modules | no cloud |
| Quality gate | `StaticVerifier` + `MatchTypeCrossCheckModel` + `InMemoryGroundingSource` | see [llm-strategy.md § T2](../architecture/llm-strategy.md#t2--reasoning-tier-quality-gate-required) |
| T1 similarity | `DeterministicEmbeddingModel` + `InMemoryPatternLibrary` | hash-based, no real embeddings |

Operator browser E2E tests use Playwright against the real Vite SPA with an explicit dev-test
profile. Route interception supplies a declared synthetic read-source manifest, incidents, agent
frames, and chat SSE response. These fixtures exist only inside the test runner and never activate
for `Console Web: Full Stack`. Backend integration tests separately exercise the same request and
bounded terminal turn-timing contract through the real Starlette route and evidence resolver.

Both isolated Playwright configurations discover only `*.spec.ts` files so colocated unit tests
cannot load an incompatible test runtime. The fixture runner starts Vite immediately and waits for
its `ready in` stdout marker instead of probing an unused loopback URL or dual-stack port. Each
process atomically leases one of ten slots: frontend ports `5274-5283` pair with live Operator API
ports `8020-8029`. Playwright workers inherit the parent's slot, exited-PID locks are reclaimed,
and traces, screenshots, and videos use a slot-scoped output directory. From the repository root,
`npm --prefix console run test:e2e:quick` runs the desktop slice, and the `console: Playwright quick
(desktop)` VS Code test task exposes the same path. The existing `npm --prefix console run
test:e2e` command remains the complete desktop and mobile matrix.

The complementary `npm --prefix console run test:e2e:live` suite starts an isolated Operator Service
with production data adapters and test-only identity verification, without route interception. It
visits every registered Console panel, waits for the panel boundary to settle, rejects browser
exceptions, shared error states, and unexpected Operator API `4xx`/`5xx` responses, and verifies that
the tested route inventory remains synchronized with the production registry. Exact unavailable
contracts remain visible without being treated as runtime defects. The suite also submits a
deterministic current-time turn and an allowlisted Microsoft Learn web search through the live
Command Deck, then requires verified or grounded terminal evidence. A governed ontology-assurance artifact records the exact source revision, canonical run configuration and digest, workspace patch digest, authentication attestation, and exact request and projection ids; the runner rejects malformed source or workspace provenance before its first request.

### Backed by dev-up.sh (still local)

| Subsystem | Local backend | Prod backend |
|-----------|---------------|--------------|
| Runtime state store and service integration | `pgvector/pgvector:pg16` on `:5432` | Azure PostgreSQL Flexible + pgvector |
| Destructive migration validation | Separate `pgvector/pgvector:pg16` cluster on `:5433` | Isolated CI validation database |
| Event bus (integration tests) | Redpanda on `:19092` (Kafka wire) | Event Hubs Kafka on `:9093` |

### Fixed workspace ports

Committed VS Code settings keep each local web surface on one predictable port. The design mock
site is static and separate from the authenticated Console full stack.

| Surface | Default address | Workspace entry point |
|---------|-----------------|-----------------------|
| Design mocks | `http://127.0.0.1:5373` | `Design Mocks: Static Site` launch or `design mocks: serve (5373)` task |
| Console SPA | `http://127.0.0.1:5273` | `Console Web: Full Stack` (recommended) or `Console Web: Frontend` (SPA only) |
| Operator API | `http://127.0.0.1:8010` | `Console Web: Operator API` |
| Document Ingestion API | `http://127.0.0.1:8011` | `Console Web: Document Ingestion API` |
| Document Processing Worker health | `http://127.0.0.1:8012` | `Console Web: Document Processing Worker` |
| Isolated Executor health | `http://127.0.0.1:8013` | `Console Web: Isolated Executor` |

The `Console Web: Full Stack` compound starts the five independently packaged backend services and
the Console SPA. Its launches import only service-owned distributions; they don't restore the
retired top-level package, co-host document processing, or an in-process Operator API compatibility
path. The local Isolated Executor is a durable shadow consumer with no managed-resource identity;
an authority-cutover setting in this venue fails startup. The compound doesn't start static design
mocks or fixture applications.

The process launcher sets `FDAI_EXECUTION_VENUE=local` independently from `RUNTIME_ENV`. Local service
state uses Docker PostgreSQL on `127.0.0.1:5432` with the owning role for Core, Operator, Document
Ingestion API, Document Processing Worker, and Isolated Executor, and local event transport uses Docker
Redpanda on `127.0.0.1:19092`. A deployed Azure process sets `FDAI_EXECUTION_VENUE=deployed` and uses its
service-owned Azure Database for PostgreSQL DSN and Event Hubs Kafka endpoint. Venue selection never changes evidence authority, promotion state, human identity, or executor authority.

The `database_host_binding` deployment mode changes only the deployed service's non-secret `POSTGRES_HOST` binding. Every service root requires a non-empty host, the sealed guard rejects other command or environment drift, and exact apply must repeat the plan's mode and digests. Local composition continues to use its loopback host, so the transition does not change execution venue or reuse a deployed DSN locally.

Opening a workspace doesn't start the Console topology; run `console: start full stack` explicitly
from the trusted primary checkout so setup never competes with editor initialization. The task
verifies shared-Git ownership, runs `prepare-console-full-stack.sh`, then runs
`start-console-services.sh`. Preparation always restores runtime PostgreSQL on port `5432`, the
isolated validation PostgreSQL cluster on port `5433`, Redpanda, and ClamAV before it evaluates
seven ordered stage fingerprints: local migrations, runtime environment, authoritative inventory,
Settings projections, catalog projections, service environments, and Entra redirects. A stage is
reused from its exact inputs and required outputs without requiring an already-running application
stack. Database-backed stages also include the local PostgreSQL volume identity, so recreated
volumes cannot inherit stale file markers. `--force` invalidates every stage.

For an interactive session that should recover a stopped backend automatically, run
`console: keep full stack ready (10m)`. The task checks the same six-component readiness contract
every 600 seconds. A healthy result is skipped without restarting anything. An unavailable result
runs the standard preparation and supervisor paths, which retain ports `5273` and `8010`-`8013`.
Stopping the task stops future checks and any supervisor that the watchdog started; it doesn't
adopt or stop an independently started healthy stack.

The supervisor launches each allowlisted `run-console-service.sh` in parallel with its own lock, fingerprint, log, and lifecycle. It emits `started` after all launchers are spawned, which releases the `console: start full stack` caller, then continues the 60-second gate and forwards shutdown. Run `console: wait full stack ready` before browser validation or another operation that requires the complete topology. That task requires checkout-owned Core, a recent heartbeat, and healthy service probes. The Core-only recovery task also waits for a fresh Pantheon heartbeat instead of treating process spawn as readiness. Changed or foreign ownership replaces only the managed task or fails.

The ordered preparation refreshes read-only Azure Resource Graph inventory and materializes sanitized model, runtime Settings, Rule, and Ontology projections only when their stage inputs change. These declarations do not create findings, observed inventory, readiness, or execution authority. An unavailable or unauthorized provider leaves inventory explicitly unavailable instead of substituting fixture data. Full-stack startup requires a trusted workspace and committed policy without weakening authority.
Loopback ownership checks use bounded 250 ms IPv4 and IPv6 socket probes and do not retain the
service lock while connecting. Shutdown allows ten seconds before stopping the child group;
wrapper loss signals its leader. Run `console: prepare full stack` before an individual service or
debug launch.
The ignored local runtime environment records the validation cluster as
`FDAI_VALIDATION_DATABASE_URL`; the detached validation queue maps only that value to
`FDAI_DATABASE_URL` for selected integration tests. It never supplies the active runtime DSN.
A separate cluster is required because Alembic role changes are cluster-global.
The same migration creates the principal-scoped `conversation_image` repository in local and
deployed PostgreSQL. Command Deck history therefore restores sent images through the same
authenticated Operator API route in both profiles; neither profile stores inline base64 in turn
metadata or browser transcript caches.
The compound completes `console: prepare full stack` before starting its children, so only stale
migration, backend-environment, projection, inventory, or Entra stages run. The Operator environment derives
its JWT audience from the browser API scope, requires matching browser and Azure tenants, disables
raw-group fallback with unmatchable local slots, and connects through `SET ROLE fdai_operator`. Run
the preparation task first for a standalone Core Runtime or Operator API debug launch.
The preparation sequence safely retries both fixed loopback origins into the configured Entra SPA
registration. The helper preserves redirects, permits loopback HTTP only, and stops when the active
tenant or registration permission is wrong. Local Event Hubs token refreshes stay pinned to prepared
`AZURE_TENANT_ID` and `AZURE_SUBSCRIPTION_ID`; default-account changes cannot replace their issuer.
When a resolved-model artifact is present, the same preparation step validates its narrator
endpoint as an HTTPS origin and writes `FDAI_LLM_ENDPOINT` with `LLM_RESOLVED_MODELS_PATH` into the
private local runtime environment. A missing or malformed narrator endpoint stops preparation
before Terraform or Azure provider access instead of allowing the core runtime to fail after launch.
An optional local configuration-baseline conversation binds three ignored artifacts through `FDAI_CONFIGURATION_BASELINE_JSON`, `FDAI_CONFIGURATION_BASELINE_DOCX`, and `FDAI_CONFIGURATION_OBSERVATION_JSON`. Supply all three to the Operator API launch after the full-stack preparation step. Avoid editing the generated `.fdai/local-runtime.env` because preparation replaces that file.
Partial configuration, a baseline integrity mismatch, or a DOCX digest mismatch stops Operator API startup; callers cannot replace the pinned scope, version, digest, or document. When the binding succeeds, local composition registers the same context for deterministic chat and the GET-only Configuration baselines panel.
The panel runs the configured observation source per request, reports an absent binding as unavailable, never substitutes fixtures or cached Azure state, and binds campaign state to PostgreSQL when available.
Campaign revisions and audit receipts survive restart; without persistence, review is not configured and no in-memory fallback is used. Local composition registers the pinned artifact as the only active immutable registry entry, so history cannot invent unconfigured versions.
Deployment requires absolute mounted baseline JSON and DOCX paths plus `FDAI_CONFIGURATION_BASELINE_RESOURCE_GROUP` in the reader allowlist, reusing that reader's Managed Identity and bounded HTTP client.
Missing identity, scope escape, malformed files, or integrity mismatch blocks startup; success adds only read evidence, durable campaign/report state, and independently reviewed shadow scheduling.
While startup probes run, the browser keeps the initial skeleton and retries only fetch-level `GET /iam/self` failures for about 28 seconds.
An HTTP response, authentication failure, malformed payload, or exhausted schedule stops at the existing access-recovery surface.
After IAM bootstrap succeeds, Dashboard treats `GET /kpi` as its required backbone and leaves the
route skeleton as soon as that response resolves. Optional FinOps, promotion-gate, and autonomy
projections join independently; `404`, `501`, or `503` renders them unavailable and never fails the complete Dashboard.
Every browser Operator API request also has a configurable 30-second default timeout. A stalled fetch
is aborted and enters the existing route error surface instead of leaving a permanent skeleton.
Each long-running Console task permits one VS Code instance. The core task and debug launch also
share `.fdai/core-runtime.lock`; a second process fails before joining Kafka consumer groups. This
prevents task/debug overlap from creating duplicate Pantheon consumers and continuous rebalancing.
The core runtime, Operator API, and frontend tasks use separate dedicated terminal groups and clear only
their own previous output when restarted. Operator API startup stays silent and never takes editor focus.
VS Code marks each background task ready only after the
Pantheon bridge starts, Uvicorn completes application startup, or Vite publishes its local address,
respectively, so a spawned process isn't presented as a ready service.
The standard local Azure profile uses the same lock by default when `FDAI_RUNTIME_LOCK_FILE` is unset, so a direct `python -m fdai` launch cannot bypass the singleton guard. Production runtimes continue to use a process lock only when the deployment configures one explicitly.
The core runtime remains the only Pantheon owner, and local and deployed interactive reads use the same execution-mode policy and fail startup when intent IDs, Heimdall ownership, or plan bindings drift. Embedded direct Pantheon chat delegation is fixture-only. With `FDAI_OPERATOR_API_EMBED_PANTHEON=0`, the Operator API reaches Bragi's conversational port through bounded request and response logical topics on the
existing `fdai.pantheon.objects` transport. A startup probe confirms the response consumer before traffic is accepted. The client reuses a joining consumer across retries and allows a 20-second initial Event Hubs group join.
`GET /chat/health` reads semantic bridge worker readiness directly and does not require a durable
`conversation/chat.health` projection row. It returns HTTP 200 with `starting` or `event-bridge`
mode so a missing unrelated projection cannot be reported as an unreachable model.
Production replicas share the server consumer group so one replica answers each request. The singleton local core uses a process-scoped server group so a restart begins at the current physical-topic offset instead of replaying unrelated Pantheon traffic from a previous process.
Requests carry salted SHA-256 user and session references rather than raw identities; timeouts or invalid responses become an explicit agent-to-Bragi handoff instead of a fabricated specialist answer. The same latency profile selects the same direct, streamed, or detached mode; only measured provider latency and configured evidence availability can change it.
The long-running core and Operator API tasks preserve their terminal output in
`.fdai/logs/core-runtime.log` and `.fdai/logs/operator-api.log`. Every captured child-output line begins
with a Python logging-style timestamp containing milliseconds and the local timezone abbreviation,
for example `2026-07-28 15:25:53,717 KST`. Each log also records service start and stop timestamps
plus the child exit code and uses private local permissions. Logs rotate at 1 MiB with up to three
previous generations retained. A bounded terminal queue prevents a stalled VS Code terminal from
blocking complete file capture; oversized entries are truncated at the configured file ceiling and
carry an explicit marker. These gitignored diagnostics survive a task terminal closing; they
don't replace the structured `warnings.jsonl` warning and error record. The core terminal keeps its
machine-readable JSON stream, while the core file renders those records as `LEVEL: logger: message`
lines to match the Operator API log. The local Operator API uses the same structured logger and honors
`FDAI_LOG_LEVEL` with an `INFO` default. Its Uvicorn access log is disabled, and `aiokafka`, `httpx`,
and `weasyprint` records below `WARNING` are suppressed while FDAI lifecycle and decision records
remain at `INFO`. The Event Hubs adapter also suppresses aiokafka's context-free per-socket
authentication success messages and emits one `event_bus_consumer_started` record per logical
consumer with its topic, consumer group, client id, and authentication mechanism. Dependency
warnings and errors remain visible. Identical warning-or-higher aiokafka failures retain the first
record and a periodic `suppressed_count` summary, while different rendered failures remain separate.
The local warning file appends each record without full-file compaction; startup and a shared
five-minute cadence enforce the 24-hour retention window. Structured records are bounded at 64 KiB.
Short-lived readiness consumers cancel and drain fetch I/O
before closing their group coordinator and socket, so an intentional probe shutdown isn't reported
as a transport failure. Startup model latency probes use a bounded Azure Responses API
output-token budget supported by every configured reasoning candidate. Core readiness samples use
stable `startup-readiness:<probe-id>` correlation ids, and Operator API latency samples use stable
`operator-api:*:latency-probe` correlation ids, so measured probe usage isn't filed as uncorrelated
traffic.
In both local and deployed consoles, an agent-card Ask action allocates a fresh user-scoped
conversation key while persisting the selected agent in the conversation summary before submit.
The browser never uses a stable per-agent key to resume an earlier transcript implicitly.
Core, Operator API, debugger, and local tasks place the owning service and shared contract SDK
source directories first on the Python import path. Another worktree's editable-install metadata
therefore can't launch stale source or cross the independent-service implementation boundary.

### Workspace context hygiene

VS Code excludes dependencies, caches, generated reports, local state, secrets, Terraform state, scratch output,
and `.improve/` from Explorer, search, and file watching. This reduces editor load, keeps local artifacts out of workspace search,
and prevents duplicate Problems entries from worktree copies. These discovery preferences don't change evidence, identity, authority,
or runtime adapters; source, tests, and owning design docs remain searchable, and Terraform indexing preserves tracked `.tf` directories.

The workspace also disables `terminal.integrated.showExitAlert`. A nonzero process exit remains visible in terminal output and task status, but VS Code doesn't raise a second toast after an interacted shell closes. This setting doesn't change shell integration, exit codes, task execution, or background-service readiness.

Pylance analysis covers the five service source roots, shared packages, independently packaged SDK
and benchmark sources, and repository maintenance scripts. Background workspace indexing is
disabled; open files still receive IntelliSense and diagnostics, and focused tests remain available
through the test runner. Pylance does not follow symlinked folders and records warning-level
language-server messages. Disabled library-source type inference bounds analysis work without
`light` mode. A profile-local Node.js heap ceiling is not claimed: Remote WSL machine settings are
shared by the server instance and a clean process-command check did not contain the attempted heap
argument. Configured workspace analysis, open-file diagnostics,
IntelliSense, and navigation therefore remain available. The validation worktree and linked local
artifacts cannot duplicate the workspace analysis set or add information-level log churn. The Chat context-usage
indicator remains enabled so a developer can move long work to the recorded session handover before the prompt reaches its limit. Copilot compacts agent conversation history at 80% of the selected model's context window, preserving automatic limit protection without a fixed early threshold. Next edit suggestions remain disabled; Chat, inline completions, context usage, and session records remain available.

The workspace loads the canonical `.github/copilot-instructions.md` entry point and the repository
`.github/hooks` directory. Nested `AGENTS.md` discovery and user-level Claude or Copilot hook
directories remain disabled for FDAI, so the same instruction or tool hook cannot enter one request
through multiple discovery paths. The dedicated `git: auto-pull` task owns background remote sync;
VS Code built-in autofetch remains disabled in this workspace.

The workspace associates only `.github/workflows/deploy-dev.yml` with the plain YAML language
mode. The GitHub Actions extension can report unresolved-action and dynamic `GITHUB_ENV` context
errors for this workflow even when the referenced action tag exists and the value is available to
the next step. Plain YAML validation remains active. Remote action-tag verification, repository
workflow contract tests, and GitHub Actions runtime validation remain authoritative; no other
workflow loses GitHub Actions language support.

Workspace settings contain only resource-scoped Pylance controls. Machine-scoped Node.js settings
are absent because the shared Remote WSL server cannot isolate them by profile. The profile keeps HashiCorp Terraform as the single language server, and workstation
cleanup does not reduce it. Unused extensions outside the profile may be uninstalled locally.
The WSL bootstrap applies path-free machine settings that Profile sync cannot carry. These
editor settings never select identity, evidence, runtime, promotion, or execution authority.

The optional `dev-access: configure VPN on folder open` task activates only when the workstation
has local state for the isolated P2S development-access stack. A connected VPN causes the task to
restore the transient WSL Resolver binding without changing FDAI runtime resources. A disconnected
VPN opens Azure VPN Client once. The task then probes the mirrored WSL route eight times over a
bounded seven-second grace window, which absorbs route propagation after WSL or VPN restart. A
direct route applies DNS and completes successfully; a route that remains indirect reports the
Problems-panel error, and the developer still completes Entra sign-in and MFA. Workstations without
local dev-access state receive no prompt or network change.

### Console data in local development

The data-source declaration, local authentication, workload evidence, and inventory query
contracts are owned by [Console Read Boundary](console-read-boundary.md). This parity document
retains the remaining local/deployed runtime bindings below.

Runtime policies use the same StateStore record in deployment and when local PostgreSQL is
configured. Without durable local state, the source manifest reports the settings store as
unavailable or non-durable instead of claiming persistence. Readers see the sanitized environment,
durable override, and effective value projection. Owners can update only the allowlist through
optimistic revision and atomic audit checks. IRP changes apply to the next eligible alert; analyzer,
inventory, and retention cadence changes apply to the next Job or tick. Logging level and case
retention/deletion day changes are labeled restart required and are loaded when the headless runtime
starts. No setting grants the local Operator API an executor identity or changes ActionType and Workflow
promotion state.

Incident auto-open enablement, minimum severity, repeat threshold, and repeat window are also
startup-bound. The headless runtime loads durable effective values. An embedded local Pantheon uses
the same validated environment, defaults, and accepted-versus-held handoff outcome instead of a
separate fixed severity or window.

Detection readiness uses the same boundary. Deployment always reads Muninn StateSnapshots from
PostgreSQL. Interactive local registers `/detection-readiness` only when local PostgreSQL is
configured; otherwise the route and source manifest report unavailable. The local browser never
substitutes Azure CLI inventory or recomputes Heimdall's decision.

The standard full-stack launch keeps narrator endpoint reconciliation enabled. Its independent
Operator Service binds a local-only narrator adapter only for `RUNTIME_ENV=dev`, reads
`LLM_RESOLVED_MODELS_PATH`, and uses a short-lived Azure CLI token without importing Core or
receiving executor authority. Health redacts endpoints, and model-only answers remain unverified.
The startup hook may allowlist the current public IP when permitted. Automated tests set
`FDAI_NARRATOR_AUTO_OPEN_AOAI=0`, and an unconfigured, unauthorized, or unreachable model safely
falls back to the deterministic answerer for that turn.
Full-stack preparation emits `LLM_MODE=azure` and `LLM_RESOLVED_MODELS_PATH` from an explicit override, then a validated `.fdai/resolved-models-vision.json`, then repository-local `resolved-models.json`, and binds metering to the read-model PostgreSQL instance. A vision artifact is eligible only when it also satisfies the core composition floor: a bindable T1 embedding plus either a bindable primary/secondary T2 pair or explicit top-level `hil-only` mode. An incompatible vision artifact falls back to the canonical artifact instead of stopping Core Runtime after preparation reported success. The LLM Cost panel and `query_llm_usage` chat capability share that measured reader in local and deployed profiles. Cost uses only
explicit deployment-to-family bindings; missing families stay unpriced. Conversation Assurance uses
the same local PostgreSQL conversation and assessment stores as deployment and always runs
deterministic terminal checks. Semantic review activates only with two distinct resolved model
families; a narrator-only or `hil-only` secondary stays inconclusive instead of using one model.
Without the artifact, model and assurance inference remain unavailable and no fixture replaces them.
When PostgreSQL StateStore is configured, both profiles persist ontology-owned failed-answer
attributions as idempotent hold-first adequacy reviews with a shadow audit record. Interactive local
without durable state leaves the optional review sink unavailable. Neither profile performs replay,
creates a proposal, or promotes a review from this intake path.

When `FDAI_MONITOR_WORKSPACE_ID` is configured, explicit Command Deck `query_log` commands use
the same bounded Azure Monitor Logs provider in both profiles. Interactive local obtains its data
plane token from the current Azure CLI context; deployment uses the dedicated Operator API managed
identity selected by `FDAI_MI_CLIENT_ID`. The workspace is server-configured and cannot be changed
by the browser. If the workspace, identity, permission, or telemetry is unavailable, the query
holds as unavailable without a fixture or model fallback.
Local preparation reads the workspace customer GUID from the applied Terraform `log_workspace_customer_id` output. If an older or targeted state does not expose that output, it lists workspaces only inside the applied resource group and accepts the fallback only when exactly one workspace exists. Zero workspaces leave the provider unavailable, and multiple workspaces stop preparation instead of choosing one implicitly. Regeneration removes any stale local workspace id.
The local runtime environment generator also supplies the applied subscription and resource group
to the bounded Azure read-investigation adapter. When Terraform emits both the optional development
operations gateway URL and its Easy Auth audience, NSG and VNet peering questions use the local
Azure CLI identity to call only the gateway's registered read operations. A missing pair disables
the wrapper, while a configured gateway failure reports unavailable without a direct-ARM fallback.
The gateway uses separate reader and executor managed identities and does not give the local read
API an execution identity. Upstream Terraform enables the development-only mutation operations for
the configured executor principal and passes the gateway URL and audience only to the headless core
Container App. That runtime binds `AzureGatewayDirectApiExecutor`; the Operator API keeps its read-only
gateway transport and never receives enforce capability. The executor must first request a server-issued dry-run receipt
for the exact registered operation, arguments, and idempotency, audit, stop-condition, rollback,
and impact evidence. The gateway confirms the target through a bounded reader-identity ARM GET,
stores the receipt in private Blob storage for five minutes, and consumes it once with ETag
compare-and-swap before taking the target-scoped resource lease and calling ARM. Caller-asserted,
changed, expired, or replayed receipts fail before mutation. An ARM
long-running operation remains `submitted`; only the executor can resolve its server-owned status
URL through the original idempotency key. A stale pending claim is recovered with ETag
compare-and-swap after its bounded timeout instead of remaining blocked indefinitely.
Repeated identical plans return the same unconsumed receipt. A consumed or expired plan needs a
new idempotency key. ARM throttling honors a bounded `Retry-After` for at most three attempts, while
mutation `5xx` responses remain ambiguous and aren't automatically repeated.

The same read-investigation wiring constructs the bounded Azure subscription-health provider. It defaults to a resource-group allowlist; interactive local selects server-owned `subscription` mode with a 1,000-resource cap because its authoritative inventory already reads the complete subscription, while deployment retains `resource_groups` unless deliberately bound with an appropriately scoped reader identity.
Browser and model input cannot change the mode. The local factory injects the provider only when read-investigation wiring is present,
preserving the read-only data-plane boundary.

Direct Command Deck reads also use the same owner-scoped run-ledger executor in both profiles.
Interactive local binds it to the configured local PostgreSQL database; deployment binds it to
Azure PostgreSQL. Both persist the canonical request digest, lease, usage, and terminal result so a
completed retry replays without another provider call. Browser input cannot select the ledger
owner, widen the Azure scope, or replace the server-owned reader credential.

Both profiles share the bounded PostgreSQL type map and `InventoryQuery` verifier. Interactive local
reads current state from the Azure CLI graph and scoped Activity Log through its reader token;
deployment uses promoted PostgreSQL inventory and its dedicated reader managed identity. Both fix
subscription and resource-group scope at composition, re-resolve follow-up selectors, and apply the
same 30-day Activity Log rules. Browser or model input cannot widen scope, and missing or mismatched
history evidence remains unavailable instead of falling back to snapshot inference.

The local factory starts all 15 agents by default. `FDAI_START_PANTHEON` is a disable-only control:
unset means enabled, while `0`, `false`, `no`, or `off` disables the runtime. When Event Hubs is
configured, the agents use that Azure transport under a dedicated local consumer group. Otherwise,
the local in-process EventBus carries real Pantheon messages and exposes the agent SSE snapshot. It
does not create Azure evidence, durable state, or execution authority. If Kafka rejects a configured
topic during startup, the Event Hubs adapter closes the failed consumer before surfacing the error.

Forecast learning uses the same PostgreSQL episode store and Heimdall handlers in both profiles.
It activates only when `FDAI_FORECAST_TARGETS_JSON` is configured. Deployment supplies raw ticks
through the opt-in Container Apps Job; local development can invoke the same mechanical tick CLI
without creating synthetic metrics or giving the console a write path.

The local runtime environment generator reads transport settings from applied Terraform outputs,
including semantic logical/physical topics used by deadline-bound durable replay. It compares the Terraform
executor identity subscription with Azure CLI and stops before lookup or file creation when they differ.
Both profiles execute the same explicitly typed semantic JSONB claim and projection statements.
It also derives a non-identifying consumer instance hash from the local user and host so concurrent
developers never join the same Event Hubs Kafka consumer group. Automation can set
`FDAI_LOCAL_CONSUMER_INSTANCE` to a lowercase alphanumeric-and-hyphen identifier of at most 20
characters when it needs a stable explicit name. Generated core, Pantheon, and Operator request groups
use that instance, while deployed Operator request groups use their runtime hostname. Live and Agent
observation use different process-local replay rules. The generic Live stage hub remains future-only.
The Agent hub retains one latest validated `agent.state` event per agent and seeds those values while
registering each new subscriber under the same lock. This bounded process-local snapshot hydrates a
refresh without polling, but it is not durable history replay and disappears when the Operator process
restarts. `FDAI_LIVE_STAGE_CONSUMER_GROUP_ID` must still be distinct for every independently running
Operator process or replica so each hub consumes the complete `fdai.pipeline.stages` stream. Its default
preserves single-process compatibility only. The isolated E2E launcher always replaces an inherited
value with a UUID-scoped group and never joins the group used by the browser-serving Operator.

Workflow definitions use the deployment enforce allowlist; ActionTypes retain promotion and risk gates.
Enforce requires Azure event transport and a durable database shared with workflow approval evidence.
Both expose body-free resume, safe cancel, and bounded effect-free retry over durable Process state.
They repeat App Role and allowlist checks, share the attempt cap, and reject unsafe retry or cancel.
Thor never receives the developer credential; execution stays in the deployed Managed Identity runtime.
Scenario replay, recording executors, VM-task fakes, synthetic data, and scope fixtures stay pytest-only.
The explicit pytest fixture builder binds a synthetic inventory graph and registers no Azure
inventory warmup or shutdown lifecycle; interactive local composition always keeps the live Azure provider.

When FDAI's Azure PostgreSQL, Event Hubs, runtime, or executor resources are absent, the associated
surfaces are unavailable or empty with no runtime claim. Repository catalogs and schemas remain
visible because they are configuration-as-code, not observed runtime evidence.
Local and deployed Operator API factories load the same validated Best Practice definitions for the
Rules `Controls` reference view. This parity does not create a runtime claim: without an
authoritative evidence provider, both factories expose every control and requirement as `Unknown`
with source `not_connected`.
Both factories also register the read-only catalog query function in the same ontology release, so
local and deployed Command Deck turns share its typed, bounded, non-mutating evidence contract.

The local API exposes `GET /system/data-sources`. In the standard full stack, the production
PostgreSQL read-model adapter points to local pgvector. Before accepting traffic, the local Operator API
runs a bounded `SELECT 1` through that adapter. A failed probe stops startup instead of exposing a
partially connected console. After the probe succeeds, PostgreSQL-backed entries report
`available` and `reachable=true`; configured remote and Azure request-time sources remain `unknown`
until their own evidence contract verifies them.
`FDAI_DATABASE_URL` and `FDAI_AUTHORITATIVE_OPERATOR_API_BASE_URL` select mutually exclusive source
profiles. Configuring both stops startup before either provider is constructed so the manifest can
never describe local PostgreSQL while allowlisted requests are served by the remote API.
Remote forwarding matches only decoded canonical allowlisted paths; normalized, encoded,
duplicated-separator, and control-character variants remain local. It discards upstream cache
directives and emits `Cache-Control: no-store` for every proxied response so authenticated
operational evidence never enters a browser or shared cache. A remote failure before response
headers becomes a bounded JSON `503`; a failure after headers closes the response body without
sending a second ASGI response start.

Runtime skill inspection follows the same rule. Production reconstructs the enabled catalog from
signed PostgreSQL trusted-artifact records before accepting traffic. Interactive local exposes the
same Reader-gated `/skills` contract and narrator verbs with an empty fail-closed snapshot unless a
durable verified store is explicitly composed; it never invents installed skills or load outcomes.

Agent Activity keeps live runtime frames separate from durable source projections. Local and deployed profiles both load `GET /agents/activity` before applying `/agents/stream`, and neither
copies scan or read history into the action audit chain. Selecting an observed agent still shows its live state, current work, runtime binding, state timestamp, stream provenance, and incident
context without inferring an audit event.
The headless Pantheon publishes health-derived `agent.runtime-state` frames on the same
`fdai.pipeline.stages` transport that carries control-loop progress. The Operator API distinguishes
runtime-state frames from stage frames and forwards only agents whose consumers are live and whose
health probe isn't in error. Interactive local and deployment use this same cross-process path; the
local profile changes the PostgreSQL binding, not agent activation or stream semantics.
The browser also retains the newest 100 observed SSE frames for the lifetime of the tab and renders
them as a separate live journal. Runtime heartbeats prove connectivity but don't count as work;
collecting, analyzing, deciding, executing, approving, auditing, Incident, and handoff frames do.
This journal is bounded and non-durable, resets on reload, preserves each frame's recorded source,
and never substitutes for the append-only audit log.

Completed conversation review follows the same split. Interactive local transport can publish the
bounded Bragi `object.turn` envelope, but it does not fabricate a reviewer or durable proposal
store. The deployed headless runtime records deterministic ineligible/unsupported reasons and uses
the Azure reviewer only when two distinct model families resolve. PostgreSQL holds restart-safe
review and draft state; the production Operator API projects those rows without sharing process memory
or adding an approval endpoint.

Approval decision delivery also keeps one shape across restarts. Production records the signed A1
decision in PostgreSQL before publishing it, checkpoints delivery attempts, and drains eligible
undelivered receipts at startup and on a periodic loop. Terminal delivered or abandoned receipts
never regress, and shutdown stops recovery before closing the event transport. Deployment can tune
the interval, publish timeout, and total attempt ceiling through
`FDAI_HIL_DECISION_RECOVERY_INTERVAL_SECONDS`,
`FDAI_HIL_DECISION_PUBLISH_TIMEOUT_SECONDS`, and
`FDAI_HIL_DECISION_MAX_DELIVERY_ATTEMPTS`. Tests use the same registry contract with an in-memory
store and publisher; interactive local never invents an approver or bypasses signed callback auth.

Headless Bragi semantic routing uses the same bound embedding capability as T1. Deployments may set
`FDAI_AGENT_SEMANTIC_COSINE_THRESHOLD` and `FDAI_AGENT_SEMANTIC_MARGIN_THRESHOLD`; invalid values
fail startup. Without an embedding binding the port keeps deterministic explicit, read-intent, and
domain routing. Embedding is a conversational fallback only and never enters typed action traffic.

Semantic query planning follows the same tier contract in every venue. Core uses resolved narrator
or `t1.judge` candidates for the initial frame and plan proposals. It may retry the failed stage
once with a separately resolved T2 reasoner only when the T1 proposal is unavailable or fails
deterministic validation. A valid clarification, scope denial, or evidence hold never changes model
tier. Missing T1 capacity makes semantic planning unavailable; it never starts with T2.

### Azure-backed integrations

| Subsystem | Status | Gap |
|-----------|--------|-----|
| Permission-aware Azure observation | Local and deployment use the same registered source catalog, due gate, bounded provider probes, PostgreSQL result state, and Agent Activity contract | Runtime validation remains open until governed local and deployed runs prove the same catalog digest and source outcomes |
| Azure Monitor Logs KQL | Production and local adapters share `AzureLogAnalyticsQueryProvider` | Requires server-owned `FDAI_MONITOR_WORKSPACE_ID`; explicit `query_log` fails closed when unavailable |
| Managed Identity token (`WorkloadIdentity`) | Deployed adapter exists | interactive local publishes to the deployed executor; fixture tests may use a local issuer |
| Governed execution backend | Provider-neutral Protocol, profile registry, durable PostgreSQL ledger, bubblewrap/VM adapters, and Azure Container Apps Job adapter exist | profiles are disabled by default; local interactive has no executor binding, and live Azure Job evidence remains required before promotion |
| Browser evidence | Provider-neutral contracts, optional Playwright adapter, PostgreSQL artifacts, and GET-only inspection exist | unbound by default; interactive local has no executor identity and renders unavailable until an isolated restricted-egress browser runtime and exact origin policies are configured |
| Key Vault secret provider (`SecretProvider`) | deployment injects Key Vault references | interactive adapters use environment references; fixture values remain test-only |
| GitOps PR publisher | Real GitHub adapter exists | interactive execution uses the configured adapter; recording publishers are test-only |
The [Permission-Aware Observation Campaign](../operations/observation-campaign.md) coordinates
periodic coverage checks for inventory, Activity Log, Resource and Service Health, metrics, Log
Analytics, guest-log, network, cost, and recovery sources. The authoritative inventory CLI owns
full reconciliation. Full-stack local and deployment run the same source catalog and due-checked
CLIs. Local PostgreSQL and the approved local read credential replace their managed deployment
bindings without changing scheduling, cursor, normalization, or evidence semantics. The Operator
API reads promoted PostgreSQL state and never owns an in-process inventory or log refresh.
The local graph default is 500 resources plus the synthetic subscription root. Larger inventories
set `truncated=true` instead of silently claiming complete coverage.
Local projection preserves discovered relationships only when the link type is registered, both
endpoint ids are selected, and the endpoint types match their resource records. An exact
type-matching duplicate of an already projected relationship is an idempotent no-op. Unknown,
mismatched, dangling, self, conflicting duplicate, and over-limit links are dropped with a
count-only warning; the complete resource snapshot remains available and reports `truncated=true`.
If the Resource Graph CLI extension or ARG request is unavailable, local discovery falls back to
core `az resource list`. The fallback preserves registered resource coverage but may report a
partial graph because that command does not return relationship-bearing properties for every type.

## Parity Contract (MUST)

Every seam that touches an out-of-process dependency MUST provide:

1. **A Protocol in `shared/providers/`** - the neutral wire contract. `core/` imports the
   Protocol only. This already holds for `EventBus`, `StateStore`, `SecretProvider`,
   `WorkloadIdentity`, `Inventory`, and the LLM seams (`EmbeddingModel`,
   `CrossCheckModel`, `VerifierPolicy`, `GroundingSource`).
2. **A test-fake implementation** - deterministic, in-process, and secret-free. It is selected
  only by automated tests or committed mock/example applications through an explicit fixture
  builder, never by the interactive local Console.
3. **A runtime adapter** - the interactive profile may use a bounded local adapter for transport
  and SSE while Azure adapters remain under `delivery/azure/` (never `core/`). Adapter selection
  does not enable or disable the Pantheon.
4. **Fail-fast or unavailable in the mismatch case** - an interactive or deployed runtime never
  falls back to a test fake. A required startup source fails startup; an optional read panel
  renders unavailable. Silent fallback is **prohibited** (matches the "no HIL-silent fallback" rule in
   [llm-strategy.md § Bootstrap Provisioner](../architecture/llm-strategy.md#bootstrap-provisioner)).

Every test that exercises the pipeline runs in mode (1)+(2) so the CI parity gate never
needs an Azure token.

Automated action tests wait for the agent run to reach its expected terminal state; an observed
intermediate state such as `verdicted` does not count as completion. CI also disables narrator
endpoint auto-open so deterministic parity tests never invoke Azure CLI or change firewall rules.

Execution backend parity follows the same rule. Automated tests may bind the in-memory ledger and
mock HTTP transport. Interactive local may inspect a disabled profile through a shadow health or
plan probe, but it does not submit work or receive Thor's identity. Deployment binds the same
provider-neutral coordinator to PostgreSQL and the injected executor `WorkloadIdentity`; the Azure
adapter remains under `delivery/azure/`. See
[Governed Execution Backends](../interfaces/execution-backends.md).

## Deployer-Scoped LLM Provisioning

Protected full plans that can change cognitive deployments run the resolver and seal its exact manifest for apply. A development-gateway targeted plan still resolves the current capability map
to preserve its existing model-account, caller-RBAC, and ingestion dependencies. Completeness findings remain non-blocking because its target set contains no cognitive deployment.

![Deployer-Scoped LLM Provisioning. The main stages are [terraform apply\], az account show / + resolve deployer principal, Bootstrap audit entry: / deployer_object_id, sub, region, read rule-catalog/llm-registry.yaml, query Azure catalog: / Foundry / AOAI SKUs available / in var.region, deployer has / Cognitive Services Contributor / on target subscription?, emit warning: / skip LLM provisioning / mark T2 capability = HIL-only, preferred family available / AND deployer sub has quota?, mark this capability HIL-only / continue with remaining, provision deployment / cap_tpm from registry, mixed-model invariant: / primary.publisher != secondary.publisher?, abort with clear error / (fork must expand preferences).](../../diagrams/generated/fdai-roadmap-deployment-dev-and-deploy-parity-01.en.svg)

**Deployer permission gates** (checked by the resolver before touching the catalog):

| Check | Failure mode | Follow-up |
|-------|--------------|-----------|
| `az account show` returns a signed-in principal | abort - deployer must run `az login` | one-line diagnostic |
| Principal has `Cognitive Services Contributor` (or `Owner`) on the target subscription | skip LLM provisioning, mark all `t2.*` and `t1.judge` capabilities as `hil-only`, emit warning | fork can grant the role and re-run |
| Region exposes at least one family from each capability's preferences | mark just the affected capability `hil-only`, warn | fork can expand preferences in `llm-registry.yaml` and re-run |
| Deployer's subscription has quota for the requested `capacity_tpm` | reduce to the largest available capacity ≥ 20% of requested; refuse below that | fork requests quota increase |
| Mixed-model invariant (`t2.reasoner.primary.publisher != t2.reasoner.secondary.publisher`) after resolution | **abort** - do NOT partially deploy a T2 tier that would fail the quality gate | fork adjusts preferences |

The resolver artifact contains the deployer's `object_id`, subscription, region, resolved capability map, and reasons. Identical registry + catalog + permission + quota inputs produce
identical JSON. The resolver caller owns appending that evidence to the audit store.

## Work Plan (phased, additive)

Every phase leaves the tree buildable + testable at `head`. Multi-cloud is **TBD**
throughout ([copilot-instructions § Implementation Focus](../../../.github/copilot-instructions.md#implementation-focus-must)).

**Status as of 2026-07-21**: W-A through W-G are **shipped**; W-H (docs sync) shipped
alongside the initial draft of this document; W-I (reconciler weekly job) remains deferred.
Each work item below reflects what actually landed - code, tests, and gate coverage.

### W-A: Config schema for LLM + dev-mode flag ✅ *(baseline, shipped)*

- Add `LlmConfig` to `services/core-control-plane/src/fdai/shared/config/schema.json` + `models.py`:
  - `mode`: `local-fake` | `azure`. `local-fake` is an explicit test/mock binding; deployment
    environment does not select it.
  - `resolved_models_path`: optional KV secret name or filesystem path.
  - `capabilities`: list of capability names (`t1.embedding`, `t1.judge`,
    `t2.reasoner.primary`, `t2.reasoner.secondary`) - mirrors the registry.
  - `t2_primary_latency_routing`: bool, default `true`. Latency routing of
    the T2 primary proposer among its same-publisher candidate pool
    (invariant-safe; enforced on). Takes effect only when the resolver emits
    a >= 2 pool (`--emit-primary-pool`); set `false` to pin the single
    primary. See [llm-strategy.md](../architecture/llm-strategy.md) section
    "T2 Primary Latency Pool".
- Fail-fast validator: `mode == "azure"` requires `resolved_models_path` present.
- Tests: schema + pydantic validators.

### W-B: `rule-catalog/llm-registry.yaml` + schema  ✅ *(catalog-as-code, shipped)*

- New file: `rule-catalog/llm-registry.yaml` with upstream defaults (mini → Opus tier).
- JSON Schema: `rule-catalog/schema/llm-registry.schema.json`.
- Python loader: `fdai.rule_catalog.schema.llm_registry` with the aggregating
  fail-close pattern used elsewhere (see `exemption.py`).
- Tests: schema validation, mixed-model invariant check.

### W-C: Bootstrap resolver CLI  ✅ *(deployer-scoped, shipped)*

- New: `services/core-control-plane/src/fdai/rule_catalog/schema/llm_resolver_cli.py`.
- Inputs: `--registry`, `--region`, `--subscription-id`, `--dry-run`, `--out`.
- Fixture mode requires catalog, permission, and quota JSON inputs for offline CI.
- `--use-azure-cli` uses the existing `az login` context and optional `AZURE_CONFIG_DIR`
  to query model catalogs, role assignments, usage/quota, and provisioned capacity read-only.
- Emits `resolved-models.json` (or `--dry-run` prints to stdout).
- Enforces every check in [Deployer-Scoped LLM Provisioning](#deployer-scoped-llm-provisioning).
- Tests: mock the two SDK clients; assert precedence + mixed-model invariant + `hil-only`
  fallback + idempotent output on same inputs.

### W-D: Azure OpenAI Terraform module + preflight  ✅ *(infra, shipped)*

- New: `infra/modules/llm/azure-openai/`.
  - `main.tf`: `azurerm_cognitive_account` (kind=`OpenAI`) + N
    `azurerm_cognitive_deployment` from `resolved_capabilities`.
  - `variables.tf`: `enable_llm` (default `false` so bare-minimum deploys still succeed),
    `resolved_capabilities` (object list from resolver).
  - `outputs.tf`: `endpoint`, `deployments` map, `resource_id`.
- Role assignment: executor MI → `Cognitive Services OpenAI User` on the account.
- Root `infra/main.tf` wires the module conditionally on `var.enable_llm`.
- Update `infra/README.md` with the deploy flow: resolver first → `terraform apply` with
  `enable_llm=true`.

### W-E: Azure OpenAI adapter classes  ✅ *(delivery, shipped)*

- `services/core-control-plane/src/fdai/delivery/azure/llm/embeddings.py` - `AzureOpenAIEmbeddingModel`
  implementing `EmbeddingModel`, using injected async `httpx` + `WorkloadIdentity`.
- `services/core-control-plane/src/fdai/delivery/azure/llm/cross_check.py` - `AzureOpenAICrossCheckModel`
  implementing `CrossCheckModel`.
- Timeout, retry-after honouring, structured output (`response_format={"type":"json_object"}`)
  - see [llm-strategy.md § Provider Abstraction](../architecture/llm-strategy.md#provider-abstraction).
- Tests: use `httpx.MockTransport` + recorded fixtures - no live network.

### W-F: Composition-root wiring  ✅ *(binding, shipped)*

- Extend `Container` with `embedding_model: EmbeddingModel`, `cross_check_models`,
  `verifier_policy`, `grounding_source` fields.
- `default_container(config)` binds deterministic fakes for `local-fake` and returns an
  unbound container for `azure`. Runtime bootstrap then calls
  `bind_azure_llm_bindings`/`wire_azure_container`, loads `resolved-models.json`, and binds
  adapters per capability. A missing entry fails fast.
- Tests: both branches; assert `local-fake` never imports `delivery.azure.llm`.

### W-G: Fixture identity + secret + inventory adapters  ✅ *(test support, shipped)*

- `EnvSecretProvider` in `shared/providers/testing/` (renamed to
  `shared/providers/local/` to reflect dev usage).
- `LocalWorkloadIdentity` - issues an in-memory OIDC token accepted only by fixture adapters
  (no network). Interactive local never uses it as Thor's identity.
- `FileFixtureInventory` - reads `Resource` records from any YAML fixture the fork passes to its constructor (`fixture=Path(...)`); upstream ships zero seed fixtures, and the recommended convention is `services/core-control-plane/tests/scenarios/inventory/*.yaml` alongside the frozen scenario replay so verticals can dry-run without ARG.
- Tests + docstrings show the exact fork-side pattern.

### W-H: Docs sync  *(this phase)*

- ✅ This document itself.
- Update [deploy-and-onboard.md § Runtime Configuration Matrix](deploy-and-onboard.md#runtime-configuration-matrix)
  to add `LLM_MODE`, `LLM_RESOLVED_MODELS_PATH`.
- Update [deploy-and-onboard.md § Azure Resource Inventory](deploy-and-onboard.md#azure-resource-inventory-minimum-set)
  to add row 11 (Azure OpenAI, opt-in).
- Update [tech-stack.md § Local Development](../architecture/tech-stack.md#local-development) to
  distinguish authoritative interactive adapters from explicit fixtures.
- Update [llm-strategy.md § Bootstrap Provisioner](../architecture/llm-strategy.md#bootstrap-provisioner)
  to reference this doc for the deployer-permission gates.

### W-I: Reconciler weekly Job  *(later phase - deferred)*

Kept as future work. Full design already in
[llm-strategy.md § Reconciler Job](../architecture/llm-strategy.md#reconciler-job); ships as a
`infra/modules/compute/container-apps-job/` reuse plus a Python entry point.

## Fork-Side Override Points

Everything above stays customer-agnostic. A fork customises without touching `core/` by:

- Providing its own `llm-registry.yaml` with region/compliance overrides.
- Supplying `AZURE_TENANT_ID` / `AZURE_SUBSCRIPTION_ID` env pointing at the fork's
  subscription. **This repo never stores those values.**
- Registering additional LLM providers (e.g. Anthropic direct API) by binding a fork-owned
  `CrossCheckModel` implementation in its composition root - the `azure-foundry` /
  `external` / `hil-only` toggle in
  [llm-strategy.md § Mixed-Model Family Strategies](../architecture/llm-strategy.md#mixed-model-family-strategies).

## Verification Gates

Each work item MUST be provable at CI time:

- The explicit fixture profile imports zero `delivery.azure.*` modules. Interactive local uses the
  Azure adapters selected by its authoritative profile.
- Identical input, App Roles, promotion state, and risk configuration produce the same local and
  deployed verdict and Process transition.
- Interactive local starts all 15 agents by default. It uses Azure transport when Event Hubs is
  configured and bounded in-process EventBus/SSE otherwise, without recording/in-memory executors.
- Terraform plan with `enable_llm=false` succeeds on a fresh subscription with only
  `Reader` role - proving the LLM module is truly opt-in.
- Resolver dry-run against a recorded region catalog produces a stable
  `resolved-models.json` hash - proving idempotency.
