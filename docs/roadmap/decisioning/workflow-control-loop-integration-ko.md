---
title: Workflow Control-Loop Integration
translation_of: workflow-control-loop-integration.md
translation_source_sha: 7eee02d07bcf34b604f17dd9941996fbbdcd00b0
translation_revised: 2026-08-02
---

# Workflow Control-Loop Integration

> [process-automation-ko.md](process-automation-ko.md) section 4에서 분리한 focused owner 문서입니다.

## 4. 컨트롤 루프 통합

컴파일된 워크플로는 side channel 에서 실행되지 않는다.
[`WorkflowCompiler`](../../../src/fdai/core/workflow/compiler.py) 는 `Workflow` 를
[`Runbook`](../../../src/fdai/core/runbook/models.py) 으로 바꾸고, 기존
[`RunbookRunner`](../../../src/fdai/core/runbook/runner.py) 가 스텝을 걷는다. 각
스텝은 주입된 `StepExecutor` 를 통해 dispatch 되며, 이는 typed 파이프라인에
재진입한다: `ActionType` -> risk-gate -> executor -> audit. 스텝 간 direct RPC 도,
risk-gate 우회도 없다. 이는 행동 요청은 typed 파이프라인에 재진입한다는 pantheon
규칙과 일치한다
([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)).

상태를 변경하는 각 action step은 `ActionType` 호출이므로 7개 안전조건이 적용됩니다.
Evidence 및 control step은 mutation authority가 없고 전용 typed contract를 사용합니다. Runner는
재구성을 위한 aggregate `runbook.terminal` audit row를 추가합니다.

### 4.1 거버넌스가 적용되는 shadow 및 enforce 오케스트레이터

[`WorkflowOrchestrator`](../../../src/fdai/core/workflow/orchestrator.py) 가 첫
라이브 소비자다. 승인을 계획하고 ([6.1절](#61-승인자-할당approver-assignment)),
`(workflow, target_resource_id, trigger_ts)` 에서 idempotent `Process` id 를
파생하고, 워크플로를 컴파일한 뒤
[`ShadowWorkflowStepExecutor`](../../../src/fdai/core/workflow/orchestrator.py) 로
걷는다 - 이 `StepExecutor` 는 publisher 도, direct-API executor 도, resource lock
도 없어서 **구조적으로 mutation 이 불가능**하다. 각 스텝은 (해결된 승인자 할당과
함께) judge-and-log 되어 `SUCCESS` 로 보고되고, 실행은 `workflow.process-plan`
audit row 하나, 스텝마다 `workflow.step` row 하나, 러너의 `runbook.terminal` 을
emit 합니다. 실행은 전용 `ProcessRuntimeStore` 에도 기록됩니다. 여기에는 현재
snapshot 하나와 append-only transition journal 이 있습니다. PostgreSQL adapter 는
optimistic revision 을 검사하면서 snapshot 갱신과 typed `ProcessEvent` append 를
한 transaction 에서 처리합니다. In-memory storage 는 테스트와 로컬 개발에 같은
contract 를 구현합니다. 명시적 enforce 실행은 `WorkflowActionDispatcher`를 사용합니다.
각 action step은 idempotent `operator_request`를 typed ingress로 다시 게시하므로
ActionType promotion, risk, HIL, Thor execution을 계속 통과합니다. Dispatcher가 없거나
guard가 실패하면 Process는 fail-closed됩니다. ARB 같은 control-only workflow는 resource
mutation authority 없이 실제 approval 및 decision transition을 저장할 수 있습니다.

이벤트 진입점은
[`WorkflowTriggerCoordinator`](../../../src/fdai/core/workflow/coordinator.py) 다:
`event-ingest` 를 통과한 Event 는 `event_type` 으로
[`WorkflowTriggerIndex`](../../../src/fdai/core/workflow/trigger_index.py) 에 매칭되고,
매칭된 모든 Workflow 는 shadow 로 실행된다 (name 순서, 리소스 + 타임스탬프는
Event 에서). 어떤 Workflow 도 매칭하지 않는 이벤트는 아무것도 시작하지 않는다.

코디네이터는 [`ControlLoop`](../../../src/fdai/core/control_loop/orchestrator.py) 에 **opt-in,
fail-safe side-consumer** 로 배선된다: `FDAI_WORKFLOW_SHADOW` 가 truthy 이고
카탈로그가 Workflow 를 실으면, 엔트리 포인트가 (로드된 Workflow 카탈로그, RBAC
그룹 매핑, notification matrix 로) 조립하고 모든 ingested 이벤트가 매칭된
Workflow 를 발화시킨다. audit row 만 추가한다 - routing, risk 결정, return 경로를
절대 바꾸지 않으며, 코디네이터 실패는 로깅되고 swallow 된다. upstream 기본은
off 이므로, 배포가 opt-in 하지 않는 한 컨트롤 루프는 이전과 똑같이 동작한다.

### 4.2 Guard 평가 (seam)

스텝의 `guard_rule_ref` 는 스텝의 결정론적 "언제"다 - policy-as-code 술어이지,
모델 텍스트가 아니다. 오케스트레이터는
[`WorkflowGuardEvaluator`](../../../src/fdai/core/workflow/orchestrator.py) seam 을
노출한다 (async, 결정론적, side-effect 없음). upstream 기본값은 evaluator 를 **주입
하지 않는다**: guard 는 rule 카탈로그에 대해 load-validate 되지만 런타임엔
`guard_evaluated: false` 로 기록되어 upstream 은 동작상 중립을 유지한다. fork (또는
향후 enforce 경로)가 이 seam 을 통해 구체 OPA-backed evaluator 를 바인딩한다.
evaluator 가 바인딩되고 스텝의 guard 가 false 를 반환하면, shadow 실행은
`guard_passed: false` 를 기록하고 그 스텝을 judged no-op 로 취급한다 (reason
`guard_blocked_shadow_noop`) - 실행은 계속되고 아무것도 mutate 하지 않는다. 모든
`workflow.step` audit row 는 `guard_rule_ref` / `guard_evaluated` /
`guard_passed` 를 담아 리뷰어가 어느 guard 가 어느 스텝을 gate 했는지 정확히 본다.

### 4.3 런타임 journal 과 온톨로지 projection

런타임 snapshot 은 "이 Process 가 지금 어디에 있는가?"에 답하고, append-only
journal 은 "어떻게 여기까지 왔는가?"에 답합니다. Typed event 는 생성, step
lifecycle, wait/approval/decision 상태, parallel branch 결과, compensation, timeout,
terminal 결과를 다룹니다. Approval step 은 서로 다른 승인 principal 수를 세고,
`no_self_approval` 이 켜져 있으면 requester 를 제외하며, quorum 을 충족할 때까지
waiting 상태를 유지합니다. Wait 및 approval timeout 은 Process 를 `timed_out` 으로
종료합니다. Parallel branch 는 동시에 실행되고 parent snapshot revision 을 두고
경쟁하지 않는 child event 를 기록합니다.

Ontology graph 는 source of truth 가 아니라 read model 입니다. 각 event 가 commit 된
후 `ProcessOntologyProjector` 가 현재 `Process` object 와 `targets` link 를
materialize 합니다. Workflow 전용 projector 는 domain object 와 link 를 추가할 수
있습니다. 예를 들어 architecture-review projector 는 같은 snapshot 과 event 에서
review case, check, evidence, principal, approval, decision 을 materialize 합니다.

Projection delivery 는 durable retry outbox 를 사용합니다.

- PostgreSQL runtime adapter 는 `process_event` 와 그
  `process_projection_outbox` job 을 같은 transaction 에 insert 합니다.
- Immediate projector 는 best effort 입니다. Projection 실패는 Process correlation id 와
  함께 log 하지만 commit 된 runtime 결과를 바꾸거나 가리지 않습니다.
- `ProcessProjectionWorker.run_once()` 는 `FOR UPDATE SKIP LOCKED` 로 bounded batch 를
  lease 하고, idempotent projection 을 재시도하며, 실패한 job 은 설정된 지연 후
  release 합니다. 새 projection 성공 시에도 due batch 하나를 drain 합니다.
- Worker 는 always-on polling daemon 이 아니라 one-shot event/job primitive 입니다.
  Container Apps Job 또는 startup hook 이 `retry_pending()` 을 호출해 backlog 를
  복구할 수 있습니다.

이 분리 덕분에 ontology store 가 잠시 unavailable 해도 runtime 처리는 계속되고,
모든 projection intent 는 복구를 위해 보존됩니다.

### 4.4 수동 shadow 또는 enforce 명령

프로덕션 signal 을 기다리지 않고 카탈로그 Workflow 를 시작하거나 재개하려면
Contributor 권한이 필요한 선택적 `POST /workflows/run` 명령을 사용할 수 있습니다.
이 route 는 catalog workflow 이름, target resource id, RFC 3339 trigger timestamp,
bounded string context 및 `mode`를 받습니다. Contributor는 shadow를 실행할 수 있습니다.
Enforce에는 Owner와 deployment `FDAI_WORKFLOW_ENFORCE_ALLOWLIST` entry가 필요합니다.
Action step은 일반 typed pipeline으로 다시 게시되며 workflow가 executor를 직접 호출하지
않습니다.

로컬 dev composition 은 명령과 Processes read route 를 동일한
`ProcessRuntimeStore` 에 연결합니다. 다음 CLI wrapper 로 실행해 볼 수 있습니다.

```bash
FDAI_OPERATOR_API_LOCAL_AZURE_CLI=1 uv run uvicorn \
  'fdai.delivery.operator_api.dev.local:app' --factory --port 8000

uv run python scripts/automation/run-workflow.py architecture-review \
  --target fdai-control-plane
```

응답에는 Process id 와 snapshot, journal, console route 링크가 포함됩니다. 같은
`trigger_ts` 와 target 을 다시 사용하면 safe-to-retry (idempotent) Process 를
재개합니다. 따라서 중복 실행을 만들지 않고 wait, approval, decision context 를
전달할 수 있습니다. Production composition 은 `WorkflowExecutionConfig` 를 주입해
opt-in 합니다. 설정하지 않으면 command route 가 등록되지 않습니다. SPA 는 이
endpoint 를 호출하지 않습니다. CLI 와 ChatOps 가 command channel 이고 console 은
read-only 상태 표면으로 유지됩니다.

### 4.5 Governed Python task 및 cron schedule

Workflow 는 ontology 에서 선택한 compute Resource 에 generated Python artifact 를
실행하기 위해 `tool.run-python-on-vm` 을 참조할 수 있습니다. `PythonTask` 는
immutable manifest 와 content hash 를 저장합니다. `VmTaskRun` 은 plan 또는 execution
receipt 하나를 저장합니다. `executes_task` 및 `runs_on` link 로 Process journal 또는
event bus 에 source code 를 넣지 않고 artifact 와 target 을 traverse 할 수 있습니다.

Authoring 경로는 여섯 operation 을 분리합니다.

1. `POST /python-tasks/generate` 는 injected `PythonTaskAuthor` 에게 selected target
  capability 및 allowlisted module 에 grounded 된 editable JSON source bundle 을
  요청합니다. Returned draft 는 static validation 을 거치며 auto-stage 되지 않습니다.
2. `POST /python-tasks/validate` 는 코드를 실행하지 않고 AST 를 parse 및 compile
  합니다. Traversal, embedded secret marker, dynamic `eval` / `exec`, 선언하지 않은
  external module, 선언하지 않은 host capability, 64 KiB 를 초과한 inline artifact 를
  차단합니다. 더 큰 bundle 은 Run Command body 를 늘리는 대신 future
  managed-identity object-storage staging adapter 가 필요합니다.
3. `POST /python-tasks/stage` 는 valid content-addressed artifact 를 immutable 하게
  저장합니다. 같은 `task_id@version` 을 다른 content 로 다시 쓰는 것은 차단됩니다.
4. `POST /python-tasks/test` 는 active inventory 에서 target 을 resolve 하고 shadow
  plan 을 반환합니다. Operator API 는 executor identity 가 없고 file copy 또는 code
  실행이 불가능한 `PlanningVmTaskRunner` 를 바인딩합니다.
5. `POST /python-tasks/request-run` 은 artifact reference, target Resource reference,
  reason 만 `ActionProposal` 로 publish 합니다. 일반 control loop 는 proposal 을
  canonical Event 로 normalize 하고 referenced ActionType 에 따라 trigger 및 argument 를
  validate 하며 active inventory 에서 신뢰할 수 있는 target property 를 로드한 뒤 unified
  risk gate 를 적용합니다. Owner HIL ceiling 과 `ToolCallShadowExecutor` 가 live work 를
  제어합니다.
6. `POST /python-tasks/schedule` 은 staged artifact, inventory target, catalog
  Workflow, strict cron expression 을 persistent scheduler 에 바인딩합니다. Future
  typed event 를 기록할 뿐 VM 에 접속하지 않습니다.

Headless core 는 `FDAI_VM_TASK_ENABLED=1` 일 때 `VmPythonToolExecutor` 를
바인딩합니다. Shadow dispatch 는 `dry_run=true` 로 runner 를 호출합니다. Enforce
dispatch 는 `FDAI_VM_TASK_ENFORCE=1` 도 필요합니다. Azure adapter 는 active
inventory 에서 provider ARM reference 를 resolve 하고, executor Managed Identity 로
Managed Run Command resource 를 생성하며, base64-encoded file 을 stage 합니다.
Cached artifact 를 포함한 모든 invocation 에서 VM 의 모든 SHA-256 digest 를 다시
검사하고 GPU 및 required module 을 확인한 뒤, 미리 생성된 `fdai-task` user 로
entrypoint 를 실행합니다. Run Command 는 root-owned
launcher 를 호출해 transient systemd unit 을 생성합니다. Source 는 read-only 이고,
output 은 per-run directory 로 제한되며 network/process/device access 는 declared
capability 를 따릅니다. Privilege escalation 은 disabled 이고 host credential path 는
inaccessible 합니다. Package 는 설치하지 않습니다. Run Command resource 를 삭제하면
in-flight run 이 취소됩니다. Content-addressed artifact 는 immutable cache 로
남습니다. Status polling 실패 또는 local coroutine cancellation 이 발생해도 terminal
result 를 보고하기 전에 remote Run Command 삭제를 시도합니다.
Reusable [`vm-task-host`](../../../infra/modules/vm-task-host) Terraform module 은
VM cloud-init profile 을 생성합니다. 별도
[`vm-task-rbac`](../../../infra/modules/vm-task-rbac) module 은 target VM scope 에
VM read 및 Managed Run Command read/write/delete 만 부여합니다. 어느 module 도 VM 을
생성하거나 시작하지 않습니다. Downstream composition 은 Python, driver, CUDA,
approved module 이 이미 포함된 승인 GPU VM image 에 host profile 을 전달하고 VM 생성
후 RBAC 을 바인딩합니다.
Host module 의 `inventory_tags` output 은 `fdai:vm-task-ready=true` 및 declared
`fdai:capabilities` list 를 설정합니다. Target resolver 는 explicit opt-in 이 없는
active inventory VM 을 차단하고 VM SKU (`NC`, `ND`, `NV` family) 로 GPU capability 를
교차 확인합니다.

Schedule-triggered Workflow 는 strict five-field cron expression 을 사용합니다.
Scheduler 는 interval task 와 함께 cron 을 저장하고 matching minute 마다 최대 한
번 emit 하며 catalog Workflow reference 를 task 와 함께 저장합니다. Single-action
scheduled Workflow 에서는 `scheduled_task_from_workflow()` 가 typed
`action_proposal` 도 materialize 합니다. Due 시 scheduler 는 이를 `operator_request`
로 publish 하며 immediate request 와 같은 raw 형식을 사용합니다. `EventIngest` 는 두
형식을 normalize 하고 `ActionBuilder` 는 ActionType schema 가 허용하는 argument 만
보존합니다. Control loop 는 proposal 을 신뢰하는 대신 active inventory 에서 target
environment 를 로드하고 complete Action 및 policy context 를 Owner approval 용으로
park 한 뒤 승인된 request 를 declared tool executor 로 dispatch 합니다. Optional
Pantheon runtime 은 같은 topic 을 shadow 로 관찰하며 두 번째 execution authority 가
아닙니다. Binding 은 upstream YAML 에 environment value 를 넣지 않고 target 및
artifact 하나를 제공합니다.

Scheduled task는 `interval`, `one-shot`, `cron`, `event-exit` 네 kind 중 하나를 선언합니다.
One-shot task는 `start_at` 이후 한 번 실행됩니다. Cron task는 validated IANA timezone에서 strict
5-field expression을 평가하며 UTC occurrence id를 유지합니다. Event-exit task는
`SchedulerService.observe_event()`가 configured normalized event type을 받을 때까지 interval로
반복하고 durable store가 exit time을 기록하고 task를 disable합니다. Kind-qualified deterministic
occurrence id가 retry, restart, cross-kind duplicate publication을 방지합니다.

모든 task는 durable `ScheduledRunIsolationProfile`도 가집니다. Default profile은 ambient tool을
모두 deny하고 session duration 및 context size를 제한합니다. Opt-in profile은 allowed tool을 모두
명시하고 total tool call을 cap하며 server-owned command sandbox profile을 참조할 수 있습니다.
`ScheduledRunIsolationGuard`는 downstream execution boundary에서 context, elapsed time, tool id,
prior call count를 다시 검사합니다. 모든 synthetic event 및 action proposal이 immutable profile을
포함하며 scheduled run은 creating operator의 더 넓은 session, credential, workspace, tool
authority를 상속하지 않습니다.

모든 due publication은 event bus 호출 전에 durable `schedule_dispatch_run` ledger에
기록됩니다. Schedule idempotency key를 사용하는 atomic claim은
`claimed -> published|failed` 상태로 이동합니다. `published` row는
`scheduled_task.last_run` 갱신 전에 기록되므로 broker publication과 task-state update 사이에서
process가 실패해도 같은 event를 다시 publish하지 않습니다. `failed` row는 retry를 위해 다시
claim할 수 있습니다. Scheduler job은 구성된 lease보다 오래된 `claimed` row를 `lost`로
reconcile하며 `lost` row도 다시 claim할 수 있습니다. Attempt counter와 task-scoped history는
PostgreSQL에서 process restart 이후에도 유지됩니다.

`published`는 synthetic event가 event bus에 도달했다는 뜻만 가집니다. Downstream control loop
또는 요청된 action이 성공했다는 뜻은 아닙니다. 이후 outcome은 기존 event, process, action,
audit record에 유지됩니다.

`ScheduleRunHistoryService`는 ledger를 read-only task-scoped history로 project합니다. Attempt를
newest first로 정렬하고 status filter와 bounded limit을 지원하며 `(scheduled_for, run_id)`에서
만든 opaque cursor를 사용하므로 새 run이 도착해도 page boundary가 안정적입니다. Projection은
status, attempt, timestamp, error kind만 노출합니다. Retry, cancel, execute method가 없습니다.
Reader-role `GET /scheduler-runs` panel은 `task_id`, optional status, bounded limit, opaque
cursor parameter를 받습니다. Production은 PostgreSQL ledger와 이를 구성하며 console의
`/processes/scheduler-runs` nested view는 task 및 status filter를 URL에 보존하고 action button
또는 executor identity 없이 cursor-paginated 근거를 렌더링합니다. Response는 `source`와
`durable`도 포함합니다. Production은 `postgres`와 `true`, local in-memory harness는
`synthetic-dev`와 `false`를 보고합니다. Console은 route 이름이나 static copy에서 durability를
추론하지 않고 이 필드를 렌더링하며 [Reviewable Automation Blueprints](automation-blueprints-ko.md)가 repeated-work suggestion을 소유합니다.

Local Operator API 도 in-memory task, inventory, audit, HIL adapter 와 함께 동일한
authoritative ControlLoop 를 사용합니다. 따라서 Workflow Builder run request 는 Owner
approval gate 까지 도달하고 route, gate, terminal audit frame 을 `/live/stream` 으로
emit 합니다. Dev harness 는 parked action 을 auto-approve 하지 않습니다.

### 4.6 Governed command 및 shell artifact

Generated Python task 는 더 이상 `process` capability 를 받지 않습니다. Static
validation 은 source 에서 child process 생성이 보이지 않는 경우에도 이 capability 를
차단합니다. 이 fail-closed default 는 typed command broker 가 준비되기 전에 generated
Python 이 task host `PATH` 의 임의 binary 를 호출하지 못하게 합니다.

Command 기반은 intent, resolution, execution 을 분리합니다.

- **Typed catalog**: `CommandCatalog` 는 등록된 `command_id`, typed request argument,
  server-owned trusted value 를 받아 frozen `CommandPlan` 을 생성합니다. Request 는
  executable, raw argv, environment, credential profile, network profile, working directory,
  subscription 또는 project 를 선택할 수 없습니다.
- **Runner seam**: `CommandRunner` 는 resolve 된 plan 만 받습니다. Upstream default 는
  dry-run 을 실제 no-op 으로 유지하는 `RecordingCommandRunner` 입니다. Opt-in
  `BubblewrapCommandRunner` 는 `local_read` plan 만 실행합니다. Opaque ref 를 private
  workspace root 아래에서 resolve하고 해당 workspace 및 configured runtime 을 read-only
  mount하며 network 를 unshare하고 capability 를 drop합니다. Private tmpfs 만 노출하고
  새 process group, timeout, stdout/stderr byte cap 을 적용합니다. Workspace-write,
  cloud, credentialed plan 은 process 생성 전에 거부합니다.
- **Sandbox profile gate**: `SandboxProfileCatalog`은 각 command id에 정확히 하나의 server-owned
  isolation profile을 부여합니다. Profile이 없는 command는 차단됩니다. Profile은 backend,
  allowed execution class 및 network profile, workspace access, credential policy, timeout,
  output ceiling을 고정합니다. `ProfiledCommandRunner`는 concrete runner 직전에 최종
  `CommandPlan`을 검증하고 requested limit을 profile ceiling으로 낮춥니다. Bubblewrap profile은
  구조적으로 read-only, offline, credential-free이며 이를 넓히려는 profile은 registration에서
  차단됩니다.
- **Cross-adapter sandbox 적용**: VM task, external tool, binary document converter는 concrete
  adapter boundary에서 같은 default-deny pattern을 사용합니다. `ProfiledVmTaskRunner`는 task
  capability, input count와 byte, timeout을 제한하며 profile은 `process` capability를 허용하지
  않습니다. `McpServerCatalog.build_routes(...)`는 enabled ActionType마다 `ToolSandboxCatalog`을
  요구하고 `ProfiledToolExecutor`는 invocation 전에 mode, argument count와 byte, tool reference
  size를 다시 검사합니다. Binary knowledge ingestion은 `DocumentConverterSandboxCatalog`과
  결합된 injected `DocumentConverter`만 받습니다. Profile은 converter id, suffix, input/output
  byte ceiling을 소유하고 request는 host path나 executable 대신 relative provenance와 content
  byte만 노출합니다. Profile이 없거나 위반되면 fail closed합니다.
- **Shell artifact**: `ShellTaskSpec` 은 content-addressed credential-free Bash bundle 을
  저장합니다. Structural validation 은 loop, pipe, heredoc 같은 local construct 를
  허용하면서 cloud CLI, privilege-escalation tool, protected host path, metadata endpoint,
  embedded secret marker, `eval`, `exec`, `source`, xtrace, offline 이 아닌 network
  profile 을 차단합니다.
- **No-exec syntax check**: `BashSyntaxChecker` 는 source 를 stdin 으로 전달하고 pinned
  absolute Bash path 를 `--noprofile --norc -n` 으로 호출합니다. Minimal environment,
  timeout, stderr cap 으로 syntax check 를 제한합니다. `-n` 은 command 를 parse 하지만
  실행하지 않습니다. Future live runner 전에는 ShellCheck 도 계속 필요합니다.
- **Private workspace patch**: `CodePatchSet` 은 content-addressed `workspace_ref` 만
  대상으로 하며 base revision, repository-relative path 당 operation 하나, expected
  before hash, after-content hash 를 포함합니다. Validation 은 traversal, duplicate
  operation, runtime/generated file, binary text, oversized change 를 차단합니다. Upstream
  provider 는 active runtime checkout 에 patch 를 적용하지 않습니다.
  `GitCodeWorkspaceProvider` 는 hardlink 없이 committed revision 을 clone하고 origin 을
  제거하며 source-checkout WIP 를 보존합니다. Validated patch 마다 새 copy-on-write
  workspace 를 materialize합니다. Apply boundary 에서 stale hash, symlink traversal,
  protected path 를 다시 검사합니다.

Upstream command catalog 는 처음에 `local.git.status`, scoped `local.git.diff`, targeted
`local.python.pytest`, targeted `local.python.ruff`, Azure read operation
`azure.resource.list` 만 노출합니다. Local command 는 private workspace reference 를
요구합니다. Azure command 의 subscription 및 credential profile 은 모델 argument 가
아니라 trusted composition value 에서 옵니다. 이 catalog 에 cloud mutation, raw REST,
recursive object-store operation 또는 arbitrary command entry 는 없습니다. Opt-in
`AzureCliCommandRunner` 는 이 read command 하나를 지원합니다. Invocation 마다 private
`AZURE_CONFIG_DIR` 을 만들고 configured user-assigned Managed Identity 로 login하며
dynamic extension 설치를 끄고 active subscription 을 다시 확인합니다. Azure CLI 호출
전에 exact argv shape 도 검증합니다. Dry-run 은 login 하지 않습니다. Adapter 는
composition 에 사용할 수 있지만 upstream app 은 bind 하지 않습니다.

이 계약은 기존 execution path 를 재사용합니다. Local check 및 read-only result
artifact 는 `tool_call`, cloud substrate mutation 은 `direct_api`, fixed operating
procedure 는 `run_runbook` 을 사용합니다. Generic `shell_exec` path 와 모델이 작성한
privileged `bash -c` command 는 지원하지 않습니다. Shell artifact 자체는 아직 실행하지
않습니다. `BashSyntaxChecker` 는 parse만 수행하고 `BubblewrapCommandRunner` 는
catalog-resolved argv 를 실행합니다. Future shell-artifact compiler 는 complete script
실행 전에 ShellCheck 를 추가하고 모든 external operation 을 command id 로 변환하며
audit receipt 를 생성해야 합니다.
