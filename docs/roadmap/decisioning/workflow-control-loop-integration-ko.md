---
title: Workflow Control-Loop Integration
translation_of: workflow-control-loop-integration.md
translation_source_sha: 4b5f34b4df9c22d370e598d25855775aff927e71
translation_revised: 2026-08-11
---

# 작업 흐름 Control-Loop 통합

> [process-automation-ko.md](process-automation-ko.md) 섹션 4에서 분리한 focused 소유자 문서입니다.

## 4. 컨트롤 루프 통합

컴파일된 워크플로는 side 채널 에서 실행되지 않는다.
[`WorkflowCompiler`](../../../services/core-control-plane/src/fdai/core/workflow/compiler.py) 는 `Workflow` 를
[`Runbook`](../../../services/core-control-plane/src/fdai/core/runbook/models.py) 으로 바꾸고, 기존
[`RunbookRunner`](../../../services/core-control-plane/src/fdai/core/runbook/runner.py) 가 스텝을 걷는다. 각
스텝은 주입된 `StepExecutor` 를 통해 전달 되며, 이는 타입이 지정된 파이프라인에
재진입한다: `ActionType` -> risk-gate -> 실행기 -> 감사. 스텝 간 direct RPC 도,
risk-gate 우회도 없다. 이는 행동 요청은 타입이 지정된 파이프라인에 재진입한다는 pantheon
규칙과 일치한다
([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)).

상태를 변경하는 각 액션 단계는 `ActionType` 호출이므로 7개 안전조건이 적용됩니다.
근거 및 컨트롤 단계는 변경 권한이 없고 전용 타입이 지정된 계약을 사용합니다. 실행기는
재구성을 위한 집계 `runbook.terminal` 감사 행을 추가합니다.

### 4.1 거버넌스가 적용되는 그림자 및 강제 적용 오케스트레이터

[`WorkflowOrchestrator`](../../../services/core-control-plane/src/fdai/core/workflow/orchestrator.py) 가 첫
라이브 소비자다. 승인을 계획하고 ([6.1절](#61-승인자-할당approver-assignment)),
`(workflow, target_resource_id, trigger_ts)` 에서 멱등적 `Process` id 를
파생하고, 워크플로를 컴파일한 뒤
[`ShadowWorkflowStepExecutor`](../../../services/core-control-plane/src/fdai/core/workflow/orchestrator.py) 로
걷는다 - 이 `StepExecutor` 는 발행기 도, direct-API 실행기 도, 리소스 잠금
도 없어서 **구조적으로 변경 이 불가능**하다. 각 스텝은 (해결된 승인자 할당과
함께) judge-and-log 되어 `SUCCESS` 로 보고되고, 실행은 `workflow.process-plan`
감사 행 하나, 스텝마다 `workflow.step` 행 하나, 러너의 `runbook.terminal` 을
발행 합니다. 실행은 전용 `ProcessRuntimeStore` 에도 기록됩니다. 여기에는 현재
스냅샷 하나와 추가 전용 전이 저널 이 있습니다. PostgreSQL 어댑터 는
optimistic 개정 번호 을 검사하면서 스냅샷 갱신과 타입이 지정된 `ProcessEvent` 덧붙이기 를
한 트랜잭션 에서 처리합니다. In-memory 저장소 는 테스트와 로컬 개발에 같은
계약 를 구현합니다. 명시적 강제 적용 실행은 `WorkflowActionDispatcher`를 사용합니다.
각 액션 단계는 멱등적 `operator_request`를 타입이 지정된 유입으로 다시 게시하므로
ActionType 승격, risk, HIL, Thor 실행을 계속 통과합니다. 명시적인 긍정 `attempt`는
`1`이 기본값이며 제안 멱등성 키와 모든 단계 전이 id를 범위하므로 서로 다른
시도가 deduplicate되지 않습니다. 디스패처가 없거나
프로세스는 `action.dispatched`를 기록한 뒤 주입된 `WorkflowOutcomeVerifier`가 권위 있는 효과
증적을 검증할 때까지 기다립니다. Command 맥락만으로 성공을 주장할 수 없습니다. 이후
단계가 실패하면 저널에 기록된 independently 검증된 applied 단계를 역순으로 보상합니다.
보상 의도는 타입이 지정된 전달 전에 커밋되고, 검증된 보상 증적만 프로세스를
`compensated`로 닫습니다. 디스패처, 검증기, 증적이 없거나 가드가 실패하면 프로세스는
보류 또는 실패 시 차단됩니다. ARB 같은 control-only 작업 흐름은 리소스
변경 권한 없이 실제 승인 및 결정 전이를 저장할 수 있습니다.
Approval 요청은 attempt-scoped입니다. 거부는 완전한 정족수 시도를 닫고 거부 또는 시간 초과
뒤 재시도는 fresh Var 자리를 만들며 시도 1 durable-key 호환성을 유지합니다.

이벤트 진입점은
[`WorkflowTriggerCoordinator`](../../../services/core-control-plane/src/fdai/core/workflow/coordinator.py) 다:
`event-ingest` 를 통과한 Event 는 `event_type` 으로
[`WorkflowTriggerIndex`](../../../services/core-control-plane/src/fdai/core/workflow/trigger_index.py) 에 매칭되고,
매칭된 모든 작업 흐름 는 그림자 로 실행된다 (이름 순서, 리소스 + 타임스탬프는
Event 에서). 어떤 작업 흐름 도 매칭하지 않는 이벤트는 아무것도 시작하지 않는다.

코디네이터는 [`ControlLoop`](../../../services/core-control-plane/src/fdai/core/control_loop/orchestrator.py) 에 **기본 활성,
fail-safe side-consumer** 로 배선된다. 카탈로그가 작업 흐름 를 실으면 엔트리 포인트가
(로드된 작업 흐름 카탈로그, RBAC
그룹 매핑, 알림 매트릭스 로) 조립하고 모든 ingested 이벤트가 매칭된
작업 흐름 를 발화시킨다. 감사 행 만 추가한다 - 라우팅, risk 결정, return 경로를
절대 바꾸지 않으며, 코디네이터 실패는 로깅되고 swallow 된다.
`FDAI_WORKFLOW_SHADOW=0|false|no|off`는 명시적 maintenance 비활성화이며, 미설정은
non-mutating 관측을 활성 상태로 유지한다.

### 4.2 가드 평가 (경계)

스텝의 `guard_rule_ref` 는 스텝의 결정론적 "언제"다 - policy-as-code 술어이지,
모델 텍스트가 아니다. 오케스트레이터는
[`WorkflowGuardEvaluator`](../../../services/core-control-plane/src/fdai/core/workflow/orchestrator.py) 경계 을
노출한다 (비동기, 결정론적, side-effect 없음). 업스트림 기본값은 평가기 를 **주입
하지 않는다**: 가드 는 룰 카탈로그에 대해 load-validate 되지만 런타임엔
`guard_evaluated: false` 로 기록되어 업스트림 은 동작상 중립을 유지한다. 포크 (또는
향후 강제 적용 경로)가 이 경계 을 통해 구체 OPA-backed 평가기 를 바인딩한다.
평가기 가 바인딩되고 스텝의 가드 가 false 를 반환하면, 그림자 실행은
`guard_passed: false` 를 기록하고 그 스텝을 judged no-op 로 취급한다 (사유
`guard_blocked_shadow_noop`) - 실행은 계속되고 아무것도 mutate 하지 않는다. 모든
`workflow.step` 감사 행 는 `guard_rule_ref` / `guard_evaluated` /
`guard_passed` 를 담아 리뷰어가 어느 가드 가 어느 스텝을 게이트 했는지 정확히 본다.

### 4.3 런타임 저널 과 온톨로지 변환 결과

런타임 스냅샷 은 "이 프로세스 가 지금 어디에 있는가?"에 답하고, 추가 전용
저널 은 "어떻게 여기까지 왔는가?"에 답합니다. 타입이 지정된 이벤트 는 생성, 단계
수명 주기, wait/승인/결정 상태, 병렬 가지 결과, 보상, 시간 초과,
최종 결과를 다룹니다. Approval 단계 은 서로 다른 승인 principal 수를 세고,
`no_self_approval` 이 켜져 있으면 요청자 를 제외하며, 정족수 을 충족할 때까지
waiting 상태를 유지합니다. Applied 단계가 없는 wait 및 승인 시간 초과는 프로세스를
`timed_out`으로 끝내지만 applied 단계 이후에는 forward 전달을 중단하고 보상에
진입합니다. 병렬 가지는 동시에 실행되고 상위 스냅샷 개정 번호를 두고 경쟁하지 않는
하위 이벤트를 기록하지만 실패는 새 가지 전달을 freeze하고 applied 증적을 결합한 뒤
reverse-dependency 보상을 시작합니다.
Approval 시간 초과는 개정 번호 CAS에서 이긴 뒤에만 프로세스를 종료합니다. 기한 만료는 late
동시 승인보다 우선합니다. 실행기는 같은 시도를 다시 읽고 최신 개정 번호로 시간 초과
CAS를 재시도합니다. 만료 전에 완성된 정족수는 delayed 재개에서도 유효합니다. 최종 승인
상태는 단조롭게 유지되며 프로바이더 reread는 권위 있는 상태 커밋 뒤 중단된 HIL 자리 종결을
복구합니다.

온톨로지 그래프 는 정본 가 아니라 읽기 모델 입니다. 각 이벤트 가 커밋 된
후 `ProcessOntologyProjector` 가 현재 `Process` 객체 와 `targets` 링크 를
materialize 합니다. 작업 흐름 전용 projector 는 도메인 객체 와 링크 를 추가할 수
있습니다. 예를 들어 architecture-review projector 는 같은 스냅샷 과 이벤트 에서
검토 사례, 검사, 근거, principal, 승인, 결정 을 materialize 합니다.

변환 결과 전달 는 영속 재시도 발신함 를 사용합니다.

- PostgreSQL 런타임 어댑터 는 `process_event` 와 그
 `process_projection_outbox` 작업 을 같은 트랜잭션 에 삽입 합니다.
- Immediate projector 는 best effort 입니다. 변환 결과 실패는 프로세스 상관관계 id 와
 함께 로그 하지만 커밋 된 런타임 결과를 바꾸거나 가리지 않습니다.
- `ProcessProjectionWorker.run_once()` 는 `FOR UPDATE SKIP LOCKED` 로 범위가 제한된 배치 를
 임차 기간 하고, 멱등적 변환 결과 을 재시도하며, 실패한 작업 은 설정된 지연 후
 release 합니다. 새 변환 결과 성공 시에도 due 배치 하나를 배출 합니다.
- 워커 는 always-on polling daemon 이 아니라 one-shot 이벤트/작업 기본 요소 입니다.
 Container Apps 작업 또는 시작 훅 이 `retry_pending()` 을 호출해 적체 를
 복구할 수 있습니다.

이 분리 덕분에 온톨로지 저장소 가 잠시 사용 불가 해도 런타임 처리는 계속되고,
모든 변환 결과 의도 는 복구를 위해 보존됩니다.

### 4.4 수동 그림자 또는 강제 적용 명령

프로덕션 신호 을 기다리지 않고 카탈로그 작업 흐름 를 시작하려면 기여자 권한이
필요한 선택적 `POST /workflows/run` 명령을 사용할 수 있습니다. 이 경로 는 카탈로그
작업 흐름 이름, 대상 리소스 id, RFC 3339 트리거 시각, 범위가 제한된
parameter-substitution 맥락 및 `mode`를 받습니다. 기여자는 그림자를 실행할 수
있습니다. 강제 적용에는 Owner와 배포 `FDAI_WORKFLOW_ENFORCE_ALLOWLIST` 항목이
필요합니다. 액션 단계는 일반 타입이 지정된 파이프라인으로 다시 게시되며 작업 흐름이 실행기를
직접 호출하지 않습니다.

로컬 dev 조립 은 명령과 Processes 읽기 경로 를 동일한
`ProcessRuntimeStore` 에 연결합니다. 다음 CLI 래퍼 로 실행해 볼 수 있습니다.

```bash
FDAI_OPERATOR_API_LOCAL_AZURE_CLI=1 uv run uvicorn \
 'fdai.delivery.operator_api.dev.local:app' --factory --port 8000

uv run python scripts/automation/run-workflow.py architecture-review \
 --target fdai-control-plane

uv run python scripts/automation/run-workflow.py \
 --resume-process-id <process-id-from-start-response>

uv run python scripts/automation/run-workflow.py \
 --cancel-process-id <process-id-from-start-response>

uv run python scripts/automation/run-workflow.py \
 --retry-process-id <process-id-from-start-response>
```

응답에는 프로세스 id 와 스냅샷, 저널, 콘솔 경로 링크가 포함됩니다.
`POST /workflows/{process_id}/resume`과 CLI `--resume-process-id` 모드는 본문을 보내지
않습니다. 서버는 프로세스 저널에서 original 대상, 트리거, 모드, 상관관계,
audit-safe 매개변수 맥락을 다시 읽고 현재 역할과 강제 적용 허용 목록을 다시 확인합니다.
`POST /workflows/{process_id}/cancel`과 CLI `--cancel-process-id`도 본문을 보내지 않습니다.
Pending 또는 waiting safe 경계만 수락하고 강제 적용 프로세스에는 Owner를 요구하며 pending
승인 자리를 닫습니다. Outstanding 액션 결과를 조정한 뒤 취소 또는
보상을 진행합니다. Running 프로세스는 in-flight 디스패처가 idle이라고 가정하지 않고 타입이 지정된
충돌을 반환합니다. `POST /workflows/{process_id}/retry`와 CLI `--retry-process-id`는 effect-free
실패한 시도 또는 최종 승인 시간 초과만 수락하고 현재 강제 적용 권한을 다시 검사하며
서버가 소유한 시도 상한을 적용합니다. 모호한 전달 실패는 복구 작업으로 유지합니다.
운영 조립은
`WorkflowExecutionConfig`를 주입해 명시적 선택 합니다.
설정하지 않으면 명령 경로가 등록되지 않습니다. SPA는 이 엔드포인트를 호출하지 않습니다. CLI와
ChatOps가 명령 채널이고 콘솔은 읽기 전용 상태 표면으로 유지됩니다.

### 4.5 통제된 Python 작업 및 cron 예약

작업 흐름 는 온톨로지 에서 선택한 compute Resource 에 생성된 Python 산출물 를
실행하기 위해 `tool.run-python-on-vm` 을 참조할 수 있습니다. `PythonTask` 는
변경할 수 없는 매니페스트 와 내용 해시 를 저장합니다. `VmTaskRun` 은 계획 또는 실행
증적 하나를 저장합니다. `executes_task` 및 `runs_on` 링크 로 프로세스 저널 또는
이벤트 버스 에 출처 코드 를 넣지 않고 산출물 와 대상 을 traverse 할 수 있습니다.

Authoring 경로는 여섯 연산 을 분리합니다.

1. `POST /python-tasks/generate` 는 injected `PythonTaskAuthor` 에게 선택된 대상
 기능 및 허용 목록에 있는 모듈 에 근거에 기반한 된 editable JSON 출처 번들 을
 요청합니다. Returned 초안 는 static 검증 을 거치며 auto-stage 되지 않습니다.
2. `POST /python-tasks/validate` 는 코드를 실행하지 않고 AST 를 parse 및 compile
 합니다. 탐색, embedded 시크릿 표시, dynamic `eval` / `exec`, 선언하지 않은
 외부 모듈, 선언하지 않은 호스트 기능, 64 KiB 를 초과한 inline 산출물 를
 차단합니다. 더 큰 번들 은 Run Command 본문 를 늘리는 대신 future
 managed-identity object-storage staging 어댑터 가 필요합니다.
3. `POST /python-tasks/stage` 는 valid 내용 기반 주소를 가진 산출물 를 변경할 수 없는 하게
 저장합니다. 같은 `task_id@version` 을 다른 내용 로 다시 쓰는 것은 차단됩니다.
4. `POST /python-tasks/test` 는 활성 인벤토리 에서 대상 을 해석 하고 그림자
 계획 을 반환합니다. Operator API 는 실행기 신원 가 없고 파일 copy 또는 코드
 실행이 불가능한 `PlanningVmTaskRunner` 를 바인딩합니다.
5. `POST /python-tasks/request-run` 은 산출물 참조, 대상 Resource 참조,
 사유 만 `ActionProposal` 로 publish 합니다. 일반 컨트롤 루프 는 제안 을
 정본 Event 로 normalize 하고 referenced ActionType 에 따라 트리거 및 인자 를
 validate 하며 활성 인벤토리 에서 신뢰할 수 있는 대상 속성 를 로드한 뒤 unified
 risk 게이트 를 적용합니다. Owner HIL 상한 과 `ToolCallShadowExecutor` 가 실제 운영 작업 를
 제어합니다.
6. `POST /python-tasks/schedule` 은 staged 산출물, 인벤토리 대상, 카탈로그
 작업 흐름, strict cron 표현식 을 persistent 스케줄러 에 바인딩합니다. Future
 타입이 지정된 이벤트 를 기록할 뿐 VM 에 접속하지 않습니다.

Headless 코어 는 `FDAI_VM_TASK_ENABLED=1` 일 때 `VmPythonToolExecutor` 를
바인딩합니다. 그림자 전달 는 `dry_run=true` 로 실행기 를 호출합니다. 강제 적용
전달 는 `FDAI_VM_TASK_ENFORCE=1` 도 필요합니다. Azure 어댑터 는 활성
인벤토리 에서 프로바이더 ARM 참조 를 해석 하고, 실행기 Managed Identity 로
Managed Run Command 리소스 를 생성하며, base64-encoded 파일 을 단계 합니다.
Cached 산출물 를 포함한 모든 호출 에서 VM 의 모든 SHA-256 다이제스트 를 다시
검사하고 GPU 및 필수 모듈 을 확인한 뒤, 미리 생성된 `fdai-task` user 로
entrypoint 를 실행합니다. Run Command 는 root-owned
launcher 를 호출해 transient systemd 단위 을 생성합니다. 출처 는 읽기 전용 이고,
출력 은 per-run 디렉터리 로 제한되며 네트워크/프로세스/device 접근 는 declared
기능 를 따릅니다. 권한 에스컬레이션 은 비활성화된 이고 호스트 자격 증명 경로 는
inaccessible 합니다. 패키지 는 설치하지 않습니다. Run Command 리소스 를 삭제하면
in-flight 실행 이 취소됩니다. 내용 기반 주소를 가진 산출물 는 변경할 수 없는 캐시 로
남습니다. 상태 polling 실패 또는 로컬 coroutine 취소 이 발생해도 최종
결과 를 보고하기 전에 원격 Run Command 삭제를 시도합니다.
Reusable [`vm-task-host`](../../../infra/modules/vm-task-host) Terraform 모듈 은
VM cloud-init 프로파일 을 생성합니다. 별도
[`vm-task-rbac`](../../../infra/modules/vm-task-rbac) 모듈 은 대상 VM 범위 에
VM 읽기 및 Managed Run Command 읽기/쓰기/삭제 만 부여합니다. 어느 모듈 도 VM 을
생성하거나 시작하지 않습니다. 다운스트림 조립 은 Python, driver, CUDA,
approved 모듈 이 이미 포함된 승인 GPU VM 이미지 에 호스트 프로파일 을 전달하고 VM 생성
후 RBAC 을 바인딩합니다.
호스트 모듈 의 `inventory_tags` 출력 은 `fdai:vm-task-ready=true` 및 declared
`fdai:capabilities` 목록 를 설정합니다. 대상 해석기 는 명시적 명시적 선택 이 없는
활성 인벤토리 VM 을 차단하고 VM SKU (`NC`, `ND`, `NV` 계열) 로 GPU 기능 를
교차 확인합니다.

Schedule-triggered 작업 흐름 는 strict five-field cron 표현식 을 사용합니다.
스케줄러 는 간격 작업 와 함께 cron 을 저장하고 matching minute 마다 최대 한
번 발행 하며 카탈로그 작업 흐름 참조 를 작업 와 함께 저장합니다. Single-action
scheduled 작업 흐름 에서는 `scheduled_task_from_workflow()` 가 타입이 지정된
`action_proposal` 도 materialize 합니다. Due 시 스케줄러 는 이를 `operator_request`
로 publish 하며 immediate 요청 와 같은 raw 형식을 사용합니다. `EventIngest` 는 두
형식을 normalize 하고 `ActionBuilder` 는 ActionType 스키마 가 허용하는 인자 만
보존합니다. 컨트롤 루프 는 제안 을 신뢰하는 대신 활성 인벤토리 에서 대상
환경 를 로드하고 완전한 액션 및 정책 맥락 를 Owner 승인 용으로
보류 한 뒤 승인된 요청 를 declared 도구 실행기 로 전달 합니다. 선택적
Pantheon 런타임 은 같은 토픽 을 그림자 로 관찰하며 두 번째 실행 권한 가
아닙니다. 연결 은 업스트림 YAML 에 환경 값 를 넣지 않고 대상 및
산출물 하나를 제공합니다.

Scheduled 작업은 `interval`, `one-shot`, `cron`, `event-exit` 네 종류 중 하나를 선언합니다.
One-shot 작업은 `start_at` 이후 한 번 실행됩니다. Cron 작업은 검증된 IANA 표준 시간대에서 strict
5-field 표현식을 평가하며 UTC occurrence id를 유지합니다. Event-exit 작업은
`SchedulerService.observe_event()`가 구성된 정규화된 이벤트 타입을 받을 때까지 간격으로
반복하고 영속 저장소가 exit 시간을 기록하고 작업을 비활성화합니다. Kind-qualified 결정론적
occurrence id가 재시도, 재시작, cross-kind 중복 게시를 방지합니다.

모든 작업은 영속 `ScheduledRunIsolationProfile`도 가집니다. 기본값 프로파일은 주변 도구를
모두 거부하고 세션 소요 시간 및 맥락 크기를 제한합니다. 명시적 선택 프로파일은 allowed 도구를 모두
명시하고 합계 도구 호출을 상한하며 서버가 소유한 명령 샌드박스 프로파일을 참조할 수 있습니다.
`ScheduledRunIsolationGuard`는 다운스트림 실행 경계에서 맥락, 경과 시간, 도구 id,
이전 호출 개수를 다시 검사합니다. 모든 synthetic 이벤트 및 액션 제안이 변경할 수 없는 프로파일을
포함하며 scheduled 실행은 creating 운영자의 더 넓은 세션, 자격 증명, workspace, 도구
권한을 상속하지 않습니다.

모든 due 게시는 이벤트 버스 호출 전에 영속 `schedule_dispatch_run` 원장에
기록됩니다. 예약 멱등성 키를 사용하는 atomic 점유는
`claimed -> published|failed` 상태로 이동합니다. `published` 행은
`scheduled_task.last_run` 갱신 전에 기록되므로 브로커 게시와 task-state 갱신 사이에서
프로세스가 실패해도 같은 이벤트를 다시 publish하지 않습니다. `failed` 행은 재시도를 위해 다시
점유할 수 있습니다. 스케줄러 작업은 구성된 임차 기간보다 오래된 `claimed` 행을 `lost`로
조정하며 `lost` 행도 다시 점유할 수 있습니다. 시도 counter와 task-scoped 이력은
PostgreSQL에서 프로세스 재시작 이후에도 유지됩니다.

`published`는 synthetic 이벤트가 이벤트 버스에 도달했다는 뜻만 가집니다. 다운스트림 컨트롤 루프
또는 요청된 액션이 성공했다는 뜻은 아닙니다. 이후 결과는 기존 이벤트, 프로세스, 액션,
감사 기록에 유지됩니다.

`ScheduleRunHistoryService`는 원장을 읽기 전용 task-scoped 이력으로 project합니다. 시도를
newest first로 정렬하고 상태 필터와 범위가 제한된 한도를 지원하며 `(scheduled_for, run_id)`에서
만든 opaque 커서를 사용하므로 새 실행이 도착해도 페이지 경계가 안정적입니다. 변환 결과는
상태, 시도, 시각, 오류 종류만 노출합니다. 재시도, 취소, execute 메서드가 없습니다.
Reader-role `GET /scheduler-runs` 패널은 `task_id`, 선택적 상태, 범위가 제한된 한도, opaque
커서 매개변수를 받습니다. 운영은 PostgreSQL 원장과 이를 구성하며 콘솔의
`/processes/scheduler-runs` 중첩된 화면은 작업 및 상태 필터를 URL에 보존하고 액션 버튼
또는 실행기 신원 없이 cursor-paginated 근거를 렌더링합니다. 응답은 `source`와
`durable`도 포함합니다. 운영은 `postgres`와 `true`, 로컬 in-memory 실행 장치는
`synthetic-dev`와 `false`를 보고합니다. Console은 경로 이름이나 static copy에서 내구성을
추론하지 않고 이 필드를 렌더링하며 [Reviewable 자동화 Blueprints](automation-blueprints-ko.md)가 repeated-work suggestion을 소유합니다.

로컬 Operator API 도 in-memory 작업, 인벤토리, 감사, HIL 어댑터 와 함께 동일한
권위 있는 ControlLoop 를 사용합니다. 따라서 작업 흐름 빌더 실행 요청 는 Owner
승인 게이트 까지 도달하고 경로, 게이트, 최종 감사 프레임 을 `/live/stream` 으로
발행 합니다. Dev 실행 장치 는 parked 액션 을 auto-approve 하지 않습니다.

### 4.6 통제된 명령 및 셸 산출물

생성된 Python 작업 는 더 이상 `process` 기능 를 받지 않습니다. Static
검증 은 출처 에서 하위 프로세스 생성이 보이지 않는 경우에도 이 기능 를
차단합니다. 이 실패 시 차단 기본값 는 타입이 지정된 명령 브로커 가 준비되기 전에 생성된
Python 이 작업 호스트 `PATH` 의 임의 binary 를 호출하지 못하게 합니다.

Command 기반은 의도, 해석, 실행 을 분리합니다.

- **타입이 지정된 카탈로그**: `CommandCatalog` 는 등록된 `command_id`, 타입이 지정된 요청 인자,
 서버가 소유한 trusted 값 를 받아 고정된 `CommandPlan` 을 생성합니다. 요청 는
 executable, raw argv, 환경, 자격 증명 프로파일, 네트워크 프로파일, working 디렉터리,
 구독 또는 project 를 선택할 수 없습니다.
- **실행기 경계**: `CommandRunner` 는 해석 된 계획 만 받습니다. 업스트림 기본값 는
 예행 실행 을 실제 no-op 으로 유지하는 `RecordingCommandRunner` 입니다. 명시적 선택
 `BubblewrapCommandRunner` 는 `local_read` 계획 만 실행합니다. Opaque 참조 를 비공개
 workspace 루트 아래에서 해석하고 해당 workspace 및 구성된 런타임 을 읽기 전용
 mount하며 네트워크 를 unshare하고 기능 를 폐기합니다. 비공개 tmpfs 만 노출하고
 새 프로세스 그룹, 시간 초과, stdout/stderr 바이트 상한 을 적용합니다. Workspace-write,
 cloud, credentialed 계획 은 프로세스 생성 전에 거부합니다.
- **샌드박스 프로파일 게이트**: `SandboxProfileCatalog`은 각 명령 id에 정확히 하나의 서버가 소유한
 격리 프로파일을 부여합니다. 프로파일이 없는 명령은 차단됩니다. 프로파일은 백엔드,
 allowed 실행 등급 및 네트워크 프로파일, workspace 접근, 자격 증명 정책, 시간 초과,
 출력 상한을 고정합니다. `ProfiledCommandRunner`는 구체적인 실행기 직전에 최종
 `CommandPlan`을 검증하고 requested 한도를 프로파일 상한으로 낮춥니다. Bubblewrap 프로파일은
 구조적으로 읽기 전용, offline, credential-free이며 이를 넓히려는 프로파일은 등록에서
 차단됩니다.
- **Cross-adapter 샌드박스 적용**: VM 작업, 외부 도구, binary 문서 converter는 구체적인
 어댑터 경계에서 같은 default-deny pattern을 사용합니다. `ProfiledVmTaskRunner`는 작업
 기능, 입력 개수와 바이트, 시간 초과를 제한하며 프로파일은 `process` 기능을 허용하지
 않습니다. `McpServerCatalog.build_routes(...)`는 활성화된 ActionType마다 `ToolSandboxCatalog`을
 요구하고 `ProfiledToolExecutor`는 호출 전에 모드, 인자 개수와 바이트, 도구 참조
 크기를 다시 검사합니다. Binary knowledge 인제스트는 `DocumentConverterSandboxCatalog`과
 결합된 injected `DocumentConverter`만 받습니다. 프로파일은 converter id, 접미사, 입력/출력
 바이트 상한을 소유하고 요청은 호스트 경로나 executable 대신 relative 출처 이력과 내용
 바이트만 노출합니다. 프로파일이 없거나 위반되면 실패 시 차단합니다.
- **셸 산출물**: `ShellTaskSpec` 은 내용 기반 주소를 가진 credential-free Bash 번들 을
 저장합니다. Structural 검증 은 루프, pipe, heredoc 같은 로컬 construct 를
 허용하면서 cloud CLI, privilege-escalation 도구, protected 호스트 경로, 메타데이터 엔드포인트,
 embedded 시크릿 표시, `eval`, `exec`, `source`, xtrace, offline 이 아닌 네트워크
 프로파일 을 차단합니다.
- **No-exec 구문 검사**: `BashSyntaxChecker` 는 출처 를 stdin 으로 전달하고 pinned
 absolute Bash 경로 를 `--noprofile --norc -n` 으로 호출합니다. Minimal 환경,
 시간 초과, stderr 상한 으로 구문 검사 를 제한합니다. `-n` 은 명령 를 parse 하지만
 실행하지 않습니다. Future 실제 운영 실행기 전에는 ShellCheck 도 계속 필요합니다.
- **비공개 workspace patch**: `CodePatchSet` 은 내용 기반 주소를 가진 `workspace_ref` 만
 대상으로 하며 base 개정 번호, repository-relative 경로 당 연산 하나, 예상
 before 해시, after-content 해시 를 포함합니다. 검증 은 탐색, 중복
 연산, 런타임/생성된 파일, binary 텍스트, oversized 변경 를 차단합니다. 업스트림
 프로바이더 는 활성 런타임 체크아웃 에 patch 를 적용하지 않습니다.
 `GitCodeWorkspaceProvider` 는 hardlink 없이 committed 개정 번호 을 clone하고 출처 을
 제거하며 source-checkout WIP 를 보존합니다. 검증된 patch 마다 새 copy-on-write
 workspace 를 materialize합니다. 적용 경계 에서 stale 해시, symlink 탐색,
 protected 경로 를 다시 검사합니다.

업스트림 명령 카탈로그 는 처음에 `local.git.status`, scoped `local.git.diff`, targeted
`local.python.pytest`, targeted `local.python.ruff`, Azure 읽기 연산
`azure.resource.list` 만 노출합니다. 로컬 명령 는 비공개 workspace 참조 를
요구합니다. Azure 명령 의 구독 및 자격 증명 프로파일 은 모델 인자 가
아니라 trusted 조립 값 에서 옵니다. 이 카탈로그 에 cloud 변경, raw REST,
재귀 object-store 연산 또는 arbitrary 명령 항목 는 없습니다. 명시적 선택
`AzureCliCommandRunner` 는 이 읽기 명령 하나를 지원합니다. 호출 마다 비공개
`AZURE_CONFIG_DIR` 을 만들고 구성된 user-assigned Managed Identity 로 login하며
dynamic 확장 설치를 끄고 활성 구독 을 다시 확인합니다. Azure CLI 호출
전에 exact argv 형태 도 검증합니다. 예행 실행 은 login 하지 않습니다. 어댑터 는
조립 에 사용할 수 있지만 업스트림 앱 은 연결 하지 않습니다.

이 계약은 기존 실행 경로 를 재사용합니다. 로컬 검사 및 읽기 전용 결과
산출물 는 `tool_call`, cloud 기반 변경 은 `direct_api`, fixed operating
procedure 는 `run_runbook` 을 사용합니다. 범용 `shell_exec` 경로 와 모델이 작성한
privileged `bash -c` 명령 는 지원하지 않습니다. 셸 산출물 자체는 아직 실행하지
않습니다. `BashSyntaxChecker` 는 parse만 수행하고 `BubblewrapCommandRunner` 는
catalog-resolved argv 를 실행합니다. Future shell-artifact 컴파일러 는 완전한 스크립트
실행 전에 ShellCheck 를 추가하고 모든 외부 연산 을 명령 id 로 변환하며
감사 증적 를 생성해야 합니다.
