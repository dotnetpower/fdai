---
title: Runtime Parity - Authoritative Local Development and Test Fixtures
---
# Runtime Parity - Authoritative Local Development and Test Fixtures

**Goal**: automated tests remain deterministic and secret-free, while every interactive local Console
session shows the operator's actual Azure development environment. Azure deployment still uses the **deployer's Azure permissions + region catalog to decide which LLM and other resources are provisioned**. Three truths hold at the same time:

- **Automated-test truth**: pytest and committed mocks may bind deterministic fakes. They use an explicit test-fixture builder and never represent observed Azure state.
- **Full-stack local truth**: `Console Web: Full Stack` uses browser Entra sign-in with the same App Role checks as deployment. The server's Azure CLI session supplies provider credentials for
  the Azure development data plane only. Inventory, model availability, agent activity, Process
  state, promotion evidence, and audit data appear only from authoritative providers. Missing
  sources render unavailable or explicitly empty; the Console never substitutes generated examples.
- **Deploy truth**: `terraform apply` provisions the Azure-side realizations of the
  CSP-neutral contracts. The **LLM subset is deployer-scoped**: the bootstrap resolver
  queries the deployer's identity against the target region's catalog, provisions
  **only what the deployer has permission to create**, and records the resolved
  `{capability → deployment}` mapping plus resolver input provenance in the artifact.

All profiles share **one control path**: only composition-root adapters and credentials differ
([project-structure.md § Customization via Dependency Injection](../architecture/project-structure.md#customization-via-dependency-injection)). Its reviewed docstring records the existing boundary and does not create a runtime,
change state ownership, or allow fixtures. Adding a real Azure client is a fork-side injection; it MUST NOT edit `core/`.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Automated-test fixture isolation | implemented | `tests/`, `console/tests/`, and the fixture-only composition paths exercised by the repository test suites | Deterministic fixtures remain outside authoritative interactive profiles. |
| Authenticated live Console route assurance | in-progress | `console/playwright.live.config.ts`, `console/tests/live-e2e/operator_service.py`, `console/tests/live-e2e/console-routes.spec.ts`, and `console/tests/live-e2e/ontology-query-assurance*.ts`; focused route checks and provenance tests passed | A governed artifact binds the exact source revision, canonical run-configuration digest, workspace patch digest, authentication attestation, and per-turn request and projection ids. The full route, ontology cohort, and critique rounds remain open. |
| Live observation consumer isolation | implemented | `services/operator-service/src/fdai_operator_service/environment.py`, `services/operator-service/src/fdai_operator_service/composition.py`, `console/tests/live-e2e/operator_service.py`, and focused regressions; 41 tests passed | `FDAI_LIVE_STAGE_CONSUMER_GROUP_ID` binds each independently running Operator process or replica to a distinct group. The E2E launcher always replaces inherited values with a UUID-scoped group. |
| Authenticated local Live event path | validated | Controlled 2026-08-13 Browser Entra run through `aw.change.events`, Core, `aw.pipeline.stages`, Operator SSE, and the existing authenticated Live DOM | The run preserved the authoritative ontology and rendered the event plus all four accepted stages. It did not validate a deployed revision, the browser Notifications API, or closed-browser push delivery. |
| Local and deployed composition parity | implemented | `.vscode/tasks.json`, `.vscode/launch.json`, `scripts/deployment/local/`, `infra/`, and service integration tests | Composition roots select credentials and adapters without changing evidence authority. |
| Local validation database isolation | implemented | `infra/local/docker-compose.yml`, `scripts/automation/validation_queue_context.py`, local preparation scripts, and focused validation and migration integration tests | Runtime state stays on local PostgreSQL port `5432`; destructive migration validation uses a separate local PostgreSQL cluster on port `5433`. |
| FDAI workspace and profile pressure controls | implemented | `.vscode/settings.json`, `.vscode/fdai.code-profile`, `scripts/automation/configure-vscode-profile.py`; focused profile and workspace tests: 11 passed | Resource-scoped analysis controls stay in the workspace. The portable profile rejects Remote WSL Pylance machine settings that it cannot isolate. |
| FDAI Pylance launch ceiling runtime proof | deferred | A clean FDAI Remote WSL restart still launched Pylance with the bundled VS Code Node executable and without `--max-old-space-size=2048`. VS Code Server 1.133 creates one Remote Machine settings resource independently of the active profile service. | Blocked pending an isolated runtime. A shared Remote Machine override would also affect excluded workspaces, so runtime isolation requires a separate VS Code Server data root or WSL distribution before the ceiling can be enabled. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance, and moved machine-scoped Pylance launch controls to the FDAI profile. | Current change in `.vscode/fdai.code-profile`, `.vscode/settings.json`, `scripts/automation/configure-vscode-profile.py`, and focused profile/workspace tests: 9 passed. | Record the FDAI Pylance process argument and centralized validation receipt. |
| 2026-08-13 | deferred | Removed the ineffective Pylance machine settings, rejected duplicate profile JSON keys, and added a contract that prevents their return. | A clean Remote WSL process command lacked the configured heap argument; focused profile and workspace tests: 11 passed. | Use a separately rooted VS Code Server or WSL distribution, then prove the heap argument from the restarted process command. |
| 2026-08-13 | implemented | Added a dedicated local PostgreSQL cluster for destructive validation and taught the detached validation queue to load only its generated DSN. | Current change; Compose config passed, focused queue and local-env tests passed (68 tests), and the isolated migration upgrade/downgrade checks passed (2 tests). | No remaining implementation work for local validation database isolation. |
| 2026-08-13 | in-progress | Replaced the live Console test's retired backend path with an independent Operator Service using production adapters and test-only bearer verification, then moved the isolated stack to IPv6 loopback so readiness failures remain bounded. | Current change in `console/playwright.live.config.ts`, `console/tests/live-e2e/operator_service.py`, and `console/tests/live-e2e/console-routes.spec.ts`; focused Overview check: 1 passed in 5.1 seconds. | Run all 50 registered routes, then complete at least 10 assurance rounds and 10 critique/hardening rounds until only Low-or-lower findings remain. |
| 2026-08-13 | in-progress | Made the capability catalog distinguish an optional missing projection from an unexpected failure and constrained the live exception to `404 /capabilities`. | Current change in `console/src/routes/capabilities.tsx`, `console/src/routes/capabilities.test.ts`, and `console/tests/live-e2e/console-routes.spec.ts`; focused unit tests: 7 passed; focused authenticated live check: 1 passed. | Repair the remaining failing routes, then complete the open assurance and critique/hardening rounds. |
| 2026-08-13 | validated | Bound the Live observation consumer group through the Operator environment and composition, isolated the E2E launcher with a UUID-scoped group, and proved the authenticated local event path from canonical ingress to the existing Live DOM. | Current change in the Operator environment, composition, launcher, and focused regressions; 41 tests passed. Controlled Browser Entra evidence rendered the event and all four accepted stages. | Record equivalent evidence from a deployed revision. Browser Notifications API and closed-browser push delivery remain outside this evidence. |
| 2026-08-13 | in-progress | Bound ontology assurance artifacts to exact source, configuration, workspace, authentication, request, and projection provenance before they can become governed evidence. | Current change in `console/tests/live-e2e/ontology-query-assurance*.ts`; focused Vitest: 25 passed; Console typecheck passed. | Obtain the exact centralized validation receipt, then run one authenticated probe before the seeded bilingual 100-case cohort. |

### Remaining work

- [ ] Establish an FDAI-only Remote WSL server data root or WSL distribution, then record a restarted Pylance process command containing `--max-old-space-size=2048` without changing the excluded workspace.
- [ ] Record passing evidence for all 50 registered Console routes, then complete at least 10 assurance rounds and 10 critique/hardening rounds with no unresolved finding above Low severity.
- [ ] Record a deployed-revision event that reaches an authenticated Live DOM through a replica-specific `FDAI_LIVE_STAGE_CONSUMER_GROUP_ID`; track browser Notifications API and closed-browser push delivery separately if those capabilities enter scope.

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
| Design mocks | `http://127.0.0.1:5373` | `Design Mocks: Static Site` launch, `design mocks: serve (5373)` task, or Live Server |
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

The process launcher sets `FDAI_EXECUTION_VENUE=local` independently from `RUNTIME_ENV`. Local
service state uses the Docker PostgreSQL instance on `127.0.0.1:5432` with the owning role for Core,
Operator, Document Ingestion API, Document Processing Worker, and Isolated Executor. Local event
transport uses Docker Redpanda on `127.0.0.1:19092`. A deployed Azure process sets
`FDAI_EXECUTION_VENUE=deployed` and uses its service-owned Azure Database for PostgreSQL DSN and
Event Hubs Kafka endpoint. Venue selection never changes evidence authority, promotion state,
human identity, or executor authority.

Opening the trusted workspace runs only lightweight hook installation, safe background Git sync,
and the optional development VPN check. `console: prepare local state` is explicit and runs through
`console: prepare full stack` or a direct task invocation. It starts runtime PostgreSQL on port
`5432`, an isolated validation PostgreSQL cluster on port `5433`, Redpanda, and ClamAV. It advances
the frozen legacy Alembic lineage and adopts and upgrades all five service-owned
migration branches under a single-instance limit. The same preparation refreshes read-only Azure
Resource Graph inventory and materializes sanitized model and runtime Settings projections from
prepared authoritative inputs without copying tenant identifiers, resource endpoints, or
credentials. An unavailable or unauthorized provider leaves inventory explicitly unavailable
instead of substituting fixture data.
The ignored local runtime environment records the validation cluster as
`FDAI_VALIDATION_DATABASE_URL`. The detached central validation queue maps only that value to
`FDAI_DATABASE_URL` for selected integration tests. It never supplies the active runtime DSN to
destructive migration tests. A separate volume and PostgreSQL cluster are required because database
roles created and removed by Alembic are cluster-global even when test tables use another database.
The same migration creates the principal-scoped `conversation_image` repository in local and
deployed PostgreSQL. Command Deck history therefore restores sent images through the same
authenticated Operator API route in both profiles; neither profile stores inline base64 in turn
metadata or browser transcript caches.
The compound completes `console: prepare full stack` before starting its children, so migration,
both backend environments, and Entra synchronization run once. The Operator environment derives
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
existing `aw.pantheon.objects` transport. A startup probe confirms the response consumer before traffic is accepted. The client reuses a joining consumer across retries and allows a 20-second initial Event Hubs group join.
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
previous generations retained. These gitignored diagnostics survive a task terminal closing; they
don't replace the structured `warnings.jsonl` warning and error record. The core terminal keeps its
machine-readable JSON stream, while the core file renders those records as `LEVEL: logger: message`
lines to match the Operator API log. The local Operator API uses the same structured logger and honors
`FDAI_LOG_LEVEL` with an `INFO` default. Its Uvicorn access log is disabled, and `aiokafka`, `httpx`,
and `weasyprint` records below `WARNING` are suppressed while FDAI lifecycle and decision records
remain at `INFO`. The Event Hubs adapter also suppresses aiokafka's context-free per-socket
authentication success messages and emits one `event_bus_consumer_started` record per logical
consumer with its topic, consumer group, client id, and authentication mechanism. Dependency
warnings and errors remain visible. Short-lived readiness consumers cancel and drain fetch I/O
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

VS Code excludes dependencies, caches, generated reports, local state, secrets, Terraform state,
scratch output, and `.improve/` from Explorer, search, and file watching. This reduces editor load,
keeps local artifacts out of workspace search, and prevents duplicate Problems entries from
worktree copies. These are discovery preferences: excluded paths remain explicitly accessible and
do not change evidence, identity, authority, or runtime adapters. Source, tests, and owning design
docs remain searchable. Terraform indexing skips verified non-Terraform directory names and
preserves every directory containing a tracked `.tf` file.

Pylance analysis covers the five service source roots, shared packages, independently packaged SDK
and benchmark sources, and repository maintenance scripts. Background workspace indexing is
disabled; open files still receive IntelliSense and diagnostics, and focused tests remain available
through the test runner. Pylance does not follow symlinked folders and records warning-level
language-server messages. Disabled library-source type inference bounds analysis work without
`light` mode. A profile-local Node.js heap ceiling is not claimed: Remote WSL machine settings are
shared by the server instance and a clean process-command check did not contain the attempted heap
argument. Configured workspace analysis, open-file diagnostics,
IntelliSense, and navigation therefore remain available. The validation worktree and linked local
artifacts cannot duplicate the workspace analysis set or add information-level log churn. The Chat
context-usage indicator remains enabled so a developer can move long work to the recorded session
handover before the prompt reaches its limit. Copilot
summarizes agent conversation history at 160000 tokens and disables next edit suggestions in this
workspace; Chat, inline completions, context usage, and session records remain available.

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
VPN opens Azure VPN Client and reports a Problems-panel error from the failed startup task; the
developer still completes Entra sign-in and MFA. Workstations without local dev-access state
receive no prompt or network change.

### Console data in local development

The canonical local Operator API uses `FDAI_OPERATOR_API_LOCAL_ENTRA=1` and shares route-owned runtime helpers with deployment. The browser obtains the API token
and the API verifies its JWT and App Roles exactly as deployment does. The server's Azure CLI token
is confined to Azure adapters such as Resource Graph, Microsoft Graph, model discovery, and Event
Hubs. `FDAI_OPERATOR_API_LOCAL_AZURE_CLI=1` with `VITE_LOCAL_AZURE_CLI_AUTH=1` is an explicit
CLI-principal debug alternative with a fixed role ceiling.

Local Kubernetes workload evidence is opt-in and server-owned. Set
`FDAI_LOCAL_KUBECONFIG`, `FDAI_LOCAL_KUBERNETES_CONTEXT`, and
`FDAI_LOCAL_KUBERNETES_CLUSTER_NAME` together to bind one fixed read-only `kubectl` query. The
cluster name must match the Azure inventory result before Deployment or Pod evidence can complete
an AKS answer. With all three values absent, workload coverage remains explicitly unavailable; a
partial binding fails startup instead of using the implicit current context.

Local and deployed inventory projections use the same two query modes. `scope=<view-id>` selects
a deterministic named architecture view. The mutually exclusive rooted mode uses
`root=<resource-id>`, `depth=1..8`, and `limit=1..1000` to return one bidirectional neighborhood;
an unknown root returns `404`, and a cap sets `truncated=true`. The local Azure CLI provider applies
the same bounds to its authoritative cached snapshot that the deployed PostgreSQL provider applies
inside the active snapshot plus real-time overlay. Neither profile widens a rooted request to the
complete inventory. The deployed provider reads that effective graph in one repeatable-read,
read-only transaction, and both profiles expand same-depth frontier resources round-robin in a
deterministic order. Named-view requests keep the original three-argument provider call contract;
only rooted requests require the extended keywords. Relationship-filter count and text length are
bounded before provider dispatch. The read route rejects malformed resources, unknown or dangling
relationships, duplicate resource ids, invalid truncation metadata, and oversized provider output.
Both profiles preserve observed operational state, including nested AKS `powerState.code`, instead
of replacing it with provisioning state. Local cache envelope v13 records a strict redacted receipt
for the Azure CLI/ARG commands that produced the snapshot. Older envelopes refresh before they can
expose provider execution detail. A Command Deck inventory turn applies IQL to that snapshot; it
doesn't claim that the provider commands ran again for the question.
Rooted output uses the requested resource cap and matching edge cap; named views keep the existing
5,000-resource and 40,000-link response ceilings.
Both profiles expose the same truncation reason vocabulary: resource, adjacent-edge,
internal-edge, or source cap. The read route rejects unknown reasons and a reason attached to a
non-truncated payload.

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
observation use a different rule because each bounded process-local SSE hub is non-replay:
`FDAI_LIVE_STAGE_CONSUMER_GROUP_ID` must be distinct for every independently running Operator process
or replica so each hub consumes the complete `aw.pipeline.stages` stream. Its default preserves
single-process compatibility only. The isolated E2E launcher always replaces an inherited value with
a UUID-scoped group and never joins the group used by the browser-serving Operator.

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
`aw.pipeline.stages` transport that carries control-loop progress. The Operator API distinguishes
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

### Azure-backed integrations

| Subsystem | Status | Gap |
|-----------|--------|-----|
| Azure Resource Graph inventory | Production reads the promoted PostgreSQL snapshot plus Huginn's real-time delta overlay | Full-stack local maps every registered Azure ARM type through read-only `AzureCliInventory`, uses bounded `az graph query` properties for relationships and VM power state without a separate `az vm list --show-details`, and stores a `.fdai/cache/inventory` snapshot isolated by subscription and Azure CLI profile fingerprint; synthetic opt-out is rejected |
| Azure Monitor Logs KQL | Production and local adapters share `AzureLogAnalyticsQueryProvider` | Requires server-owned `FDAI_MONITOR_WORKSPACE_ID`; explicit `query_log` fails closed when unavailable |
| Managed Identity token (`WorkloadIdentity`) | Deployed adapter exists | interactive local publishes to the deployed executor; fixture tests may use a local issuer |
| Governed execution backend | Provider-neutral Protocol, profile registry, durable PostgreSQL ledger, bubblewrap/VM adapters, and Azure Container Apps Job adapter exist | profiles are disabled by default; local interactive has no executor binding, and live Azure Job evidence remains required before promotion |
| Browser evidence | Provider-neutral contracts, optional Playwright adapter, PostgreSQL artifacts, and GET-only inspection exist | unbound by default; interactive local has no executor identity and renders unavailable until an isolated restricted-egress browser runtime and exact origin policies are configured |
| Key Vault secret provider (`SecretProvider`) | deployment injects Key Vault references | interactive adapters use environment references; fixture values remain test-only |
| GitOps PR publisher | Real GitHub adapter exists | interactive execution uses the configured adapter; recording publishers are test-only |
The local inventory cache promotes only scans that reach the final fence and writes them by atomic
replace. Operator API startup loads the persistent cache and schedules a stale or missing refresh without blocking readiness; shutdown cancels and drains that task. A fresh cache returns immediately across restarts. A fresh-required query waits only when warmup is still running. An expired or Huginn-invalidated cache returns immediately as `stale` with `cache.status=refreshing`, then a background Azure CLI scan atomically replaces it. When a provisioned `aw.inventory.raw` topic is configured through
`FDAI_INVENTORY_RAW_TOPIC`, accepted write/delete events invalidate the local cache after durable
projection. A stack without that auxiliary-topic binding converges through TTL refresh.
Inventory projection changes that add resource types or relationships increment the cache envelope
schema revision so an older complete snapshot is refreshed instead of being presented with stale
semantics. Schema revision 10 invalidates every earlier snapshot, including revisions that predate
normalized Azure service state and catalog-driven resource-type and Azure `kind` disambiguation.
The first database-status or shared-ARM-type query therefore cannot replay an older `unknown` or
misclassified state. A missing explicit subscription disables persistent cache reuse rather than risking a
snapshot from another active Azure CLI subscription. The cache envelope also binds the resource
limit, rejects malformed
or materially future-dated snapshots, and bounds each local refresh to 240 seconds. Cache-file or
marker I/O failure preserves the last complete in-memory graph. Marker write failure falls back to
TTL convergence; marker metadata read failure is treated as stale and schedules refresh rather than
trusting uncertain cache state. Persistent reads accept only user-private regular files and enforce
the 5 MB limit on an already-open descriptor. Writes repair the cache directory to mode `0700`,
create mode-`0600` files, cap serialized bytes before replace, and fsync the directory. Both live
and cached graphs reject duplicate resources or links, dangling/self links, non-finite or out-of-
world geometry, invalid roots or parent cycles, future timestamps, invalid envelopes, and counts
beyond the configured limit.
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

At `terraform apply` time the resolver behaves like this:

```mermaid
flowchart LR
    START([terraform apply]) --> WHOAMI["az account show<br/>+ resolve deployer principal"]
    WHOAMI --> AUDIT[Bootstrap audit entry:<br/>deployer_object_id, sub, region]
    AUDIT --> REG[read rule-catalog/llm-registry.yaml]
    REG --> CAT["query Azure catalog:<br/>Foundry / AOAI SKUs available<br/>in var.region"]
    CAT --> RBAC{deployer has<br/>Cognitive Services Contributor<br/>on target subscription?}
    RBAC -->|no| SKIP1[emit warning:<br/>skip LLM provisioning<br/>mark T2 capability = HIL-only]
    RBAC -->|yes| MATCH{"preferred family available<br/>AND deployer sub has quota?"}
    MATCH -->|no for capability| SKIP2["mark this capability HIL-only<br/>continue with remaining"]
    MATCH -->|yes| DEPLOY["provision deployment<br/>cap_tpm from registry"]
    DEPLOY --> INV{"mixed-model invariant:<br/>primary.publisher != secondary.publisher?"}
    INV -->|violated| ABORT["abort with clear error<br/>(fork must expand preferences)"]
    INV -->|ok| WRITE[emit resolved-models.json file or inline JSON]
    SKIP1 --> WRITE
    SKIP2 --> WRITE
    WRITE --> ROLE[role-assign executor MI:<br/>Cognitive Services OpenAI User]
    ROLE --> DONE([done])
```

**Deployer permission gates** (checked by the resolver before touching the catalog):

| Check | Failure mode | Follow-up |
|-------|--------------|-----------|
| `az account show` returns a signed-in principal | abort - deployer must run `az login` | one-line diagnostic |
| Principal has `Cognitive Services Contributor` (or `Owner`) on the target subscription | skip LLM provisioning, mark all `t2.*` and `t1.judge` capabilities as `hil-only`, emit warning | fork can grant the role and re-run |
| Region exposes at least one family from each capability's preferences | mark just the affected capability `hil-only`, warn | fork can expand preferences in `llm-registry.yaml` and re-run |
| Deployer's subscription has quota for the requested `capacity_tpm` | reduce to the largest available capacity ≥ 20% of requested; refuse below that | fork requests quota increase |
| Mixed-model invariant (`t2.reasoner.primary.publisher != t2.reasoner.secondary.publisher`) after resolution | **abort** - do NOT partially deploy a T2 tier that would fail the quality gate | fork adjusts preferences |

The resolver artifact contains the deployer's `object_id`, subscription, region, resolved
capability map, and reasons. Identical registry + catalog + permission + quota inputs produce
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
