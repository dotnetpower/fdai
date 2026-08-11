---
title: Operator Console - Data and Wire Contracts
translation_of: operator-console-wire-contracts.md
translation_source_sha: 58a807dfcbe683e35b3ccdf06cf55ae84840b0f0
translation_revised: 2026-08-11
---

# Operator Console - Data and Wire Contracts

> [operator-console-ko.md](operator-console-ko.md) section 13 (13.1-13.3, 13.6-13.9)에서 분리한 focused 소유자 문서입니다.

## 13. 데이터 + wire 계약

### 13.1 감사 항목 - `console.turn` action_kind

```json
{
 "action_kind": "console.turn",
 "session_id": "...",
 "turn_id": "...",
 "principal": {"kind": "user|cli|bot", "id": "...", "role": "Reader|..."},
 "channel": "cli|teams|slack|web",
 "direction": "inbound|outbound|tool_call|tool_result",
 "tier": "T0|T1|T2",
 "escalation_trigger": "...",
 "tool_name": "...",
 "arguments": {...},
 "result_preview": "...",
 "evidence_refs": ["..."],
 "verifier_verdict": "pass|abstain|deny|n/a",
 "model_deployment_id": "...",
 "prompt_tokens": 0,
 "completion_tokens": 0,
 "started_at": "...",
 "finished_at": "..."
}
```

### 13.2 CLI REPL wire 계약

- stdin: 한 줄에 하나의 오퍼레이터 발화.
- stdout: `--json` 플래그 설정 시 JSON-Lines; 그렇지 않으면 formatted 텍스트.
- stderr: 조정기 로그 라인 (구조화됨; 별개 스트림 이므로 formatted
 화면은 clean 유지).
- Exit 코드: clean 세션 종료 시 `0`; 유효하지 않은 구성 시 `2`; 복구
 불가능한 채널 오류 시 `3`.

### 13.3 Operator API 승인 콜백 (주 1)

- `POST /hil/{approval_id}/decision`
- 본문: `{"decision": "approve|reject|defer", "justification": "..."}`
- 헤더: `X-FDAI-Signature: sha256=<hex>`,
 `X-FDAI-Timestamp: <RFC3339>`.
- 서명 재료: `HMAC-SHA256(secret, timestamp . approval_id . body)`.
 세 부분은 literal `.` separator 로 결합. URL 경로 `approval_id` 를
 다이제스트 에 연결 하면, 캡처된 유효 메시지를 다른 pending item 으로 재생
 (URL swap) 할 수 없음. bot은 URL 에 넣은 `approval_id` 를 서명 재료에도
 반드시 동일하게 포함해야 함.
- 응답: `200 {"queued": true, "audit_entry_id": "..."}`.

이 경로는 Operator API의 GET 전용 변환 결과 표면에 문서화된 write-route
예외입니다. Invariant 테스트는 이 콜백을 명시적으로 allow-list합니다. 이는
[app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)
의 "콘솔 never executes" 규칙을 깨지 **않음**: 이 엔드포인트는 기존 HIL
큐에 *승인 결정을 기록* (시그널) 할 뿐이며, 별도 실행기 principal이
나중에 그것을 실행. API 프로세스는 실행기 Managed Identity를 절대
보유하지 않고 변경 표면을 직접 호출하지 않음; 승인과 실행은
별개 principal 유지.

### 13.6 의미 기반 작업 초안 및 타입이 지정된 확인

모든 자연어 턴은 `POST /chat` 또는 `POST /chat/stream`을 사용합니다.
구성된 mini 서술기는 서버가 제공한 기능 매니페스트에서 답변, 읽기
도구, agent 소유자, 공개 웹 조회, 명확화 또는 쓰기 초안을 선택한
strict JSON-schema `TurnPlan`을 반환합니다. 브라우저는 액션 의도를
분류하지 않으며 자연어를 쓰기 엔드포인트에 직접 보내지 않습니다.

- **초안**: `action_draft` 또는 `incident_draft`는 허용 목록에 있는
 `action_type`, 범위가 제한된 타입이 지정된 arguments, 대화 `session_id`, request-scoped
 멱등성 키를 반환합니다. 초안을 만드는 동안 event를 발행하거나
 인시던트를 생성하지 않습니다. 브라우저는 확인 및 취소 control을 표시합니다.
- **타입이 지정된 확인**: `POST /chat/action/confirm`은
 `{"action_type": str, "arguments": 객체, "session_id": str?,
 "idempotency_key": str}`만 받습니다. 서버는 proposal 하나를 발행하기 전에
 ActionType 허용 목록, 인자 한계치, 인증된 principal 및 RBAC를 다시
 확인합니다. 알 수 없는 필드 및 허용 목록에 없는 액션은 차단됩니다.
- **호환 엔드포인트**: `POST /chat/action`, 본문 `{"프롬프트": str, "session_id": str?,
 "idempotency_key": str?}`. `OperatorApiConfig.console_action` 이
 `ConsoleActionSubmitter`
 (`services/operator-service/src/fdai_operator_service/`)를 wire할 때만
 등록됩니다. 이 raw-prompt 경로는 호환 API 클라이언트를 위해 남아 있으며 브라우저
 Command Deck은 사용하지 않습니다. 오퍼레이터 제공 값은
 한계된다(프롬프트 <= 4000, 질문 <= 2000, 리소스 id / 세션 id /
 멱등성 키 <= 200자) - 하나의 큰 값이 파이프라인/감사 을 bloat 하지
 못하게. 클라이언트 `idempotency_key` 는 proposal 의 dedup 키가 되어(initiator 로
 이름 공간 되므로 한 운영자 가 다른 운영자 의 키를 재사용해 그의 액션 을
 suppress 할 수 없다), 재시도/중복 제출이 두 번째 액션 을 큐에 추가 하지 않고
 Huginn 에서 collapse 된다; Thor 는 상관관계 단위로 추가 멱등이므로
 at-least-once 재전달이 double-execute 되지 않는다.
- **서버 파생 RBAC**. 오퍼레이터 역할은 검증된 bearer 토큰(`Principal.roles`)
 에서 오며, 클라이언트 JSON이 아니다. 제출은 `author-draft-pr` 기능
 (기여자 이상)를 요구; 읽기 담당은 아무것도 발행되기 전에
 `403 {"submitted": false, "reason": "rbac_capability"}` 로 거부. Forseti가
 downstream에서 initiator principal을 재확인(거부 + `SecurityEvent`) -
 defense in depth.
- **두 진입 게이트는 역할 순위가 아니라 기능으로 일치한다**. 대화형 진입
 게이트(`Bragi.submit_action_proposal`)는 세션의 Entra 역할을 **동일한** 정본
 기능 매트릭스(`fdai.core.rbac.roles`)로 매핑하고 마찬가지로
 `author-draft-pr` 를 요구하므로, HTTP와 대화형 표면이 절대 어긋나지 않는다.
 특히 `BreakGlass` 는 하드 격리(Owner의 superset 아님)이고 `author-draft-pr` 를
 갖지 않으므로, 어느 표면에서도 일반 액션을 제출할 수 없다.
- **거부는 관측 가능하다**. 파이프라인 진입 전의 모든 거부(`invalid_principal` /
 `rbac_capability` / `deny_override_forbidden`)는 로깅되고 선택적으로 주입된
 `RefusalObserver`(`ConsoleActionSubmitter.refusal_observer`)에 전달되어, 한
 actor에 대한 반복 거부 - 요청이 파이프라인에 들어가지 않아 Forseti가 못 보는
 권한 프로빙 신호 - 를 탐지 가능하게 한다(감사 / 메트릭 / security event). seam이
 없으면 구조화 로그 라인만 방출된다.
- **이전 방식 translation**. 호환 엔드포인트의
 `fdai.agents.bragi.translate_action_intent`는 먼저 정확한 ActionType
 id 또는 load된 ActionType 카탈로그의 모호하지 않은 전체 접미사를 매칭합니다.
 예를 들어 `flush cache`는 `ops.flush-cache`로 매핑됩니다. 그다음 보수적인
 built-in verb 대체 경로를 사용합니다. 모호하거나 매핑되지 않은 명령은 추측하지
 않고 `200 {"submitted": false, "reason": "unmapped_action_intent"}`를
 반환합니다. 이 함수는 pantheon 내부 경로와 공유하는 단일 진실원으로 유지됩니다.
- **Deny-override 차단 (시나리오 B)**. `prior_outcome_lookup` seam이 wire되면,
 submitter는 publish 전에 이 정확한 `(initiator, resource, action_type)` 에
 대한 파이프라인의 마지막 최종 결론을 확인한다. 직전 **거부**(안전하지
 않다고 판정됨)는 권위 있는하다: 반복 콘솔 요청으로 이를 lift할 수 없어
 submitter는 `403 {"submitted": false, "reason": "deny_override_forbidden"}`
 로 거부하고 아무것도 publish하지 않는다 - 거부는 오직 통제된 rule / 정책
 / 재정의 변경으로만 lift되며, 반복 요청으로는 절대 안 된다. 직전 **no-op**
 (대상이 이미 충족되어 액션이 불필요했던 경우)은 재요청을 막지 **않는다**:
 조건은 drift하므로 요청은 파이프라인에 재진입해 새로 judged된다. 이 규칙은
 하나의 순수 함수(`fdai.core.console_request.evaluate_operator_rerequest`)에
 산다. seam이 없으면 모든 요청은 fresh로 취급된다(deny-override 확인 없음).
- **응답**(제출됨): `200 {"submitted": true, "correlation_id": ...,
 "action_type": ..., "resource_id": ...}`. 오퍼레이터는 `correlation_id`
 (Trace 패널 / 감사)로 진행을 추적; 파이프라인 결과(auto shadow-exec,
 HIL 대기, 거부)는 비동기.
- **조사 인시던트**. 명시적 `tool.run-investigation <kind> <resource>` 명령 자체를
 확인으로 간주하여 세션, 대상, 리소스 kind에 대한 결정론적 인시던트를 만들거나
 재사용합니다. Proposal은 인시던트 ID를 상관관계로 사용하고 타입이 지정된 매개변수에
 `incident_id`를 전달합니다. 일반 질문과 발견 작업은 인시던트를 만들지 않습니다.
- **실제 운영 단계 턴**. 제출 성공 후 web deck은 인증된 correlation-filtered `/live/stream`
 읽기 담당을 열고 하나의 transcript 턴을 Huginn ingest, Forseti 경로/verify/gate, Thor
 execute, Saga 감사 순서로 갱신합니다. 감사가 최종이며 시간 초과 또는 스트림 실패 시
 영속 Trace 상관관계가 복구 출처로 남습니다.
- **이것은 13.3 승인 콜백과 나란한 두 번째 문서화된 쓰기 경로**;
 둘 다 시그널을 기록할 뿐 실행기 Managed Identity를 갖지 않는다.

### 13.7 Python VM 작업 workbench

작업 흐름 빌더 는
[`python_tasks.py`](../../../services/operator-service/src/fdai_operator_service/) 의 여섯
변경 경로 와 읽기 전용 `GET /python-tasks/capabilities` 경로 를 사용하는
multi-file Python 작업 workbench 를 포함합니다.
Operator 는 출처 file 을 편집하고 entrypoint 를 선택하며 모듈 및 host
기능 를 선언한 뒤 validate, 변경할 수 없는 산출물 단계, 인벤토리 Resource 대상
shadow 계획 을 수행할 수 있습니다.

기능 응답 는 선택적 연산 별 가용성을 따로 보고합니다. Console 은 경로 가
없으면 workbench 를 열지 않으며 어댑터, submitter 또는 예약 저장소 가 연결되지 않은
연산 을 비활성화합니다. 따라서 사용 불가 경로 가 범용 `404` 로 실패하는 실행 가능한
control 처럼 표시되지 않습니다.

Workbench 는 콘솔 신원 경계 를 유지합니다.

- **Validate** 는 pure AST 및 매니페스트 검증 입니다.
- **Generate editable 초안** 는 운영자 의도, 대상 기능, 허용 목록에 있는
 모듈 로 injected `PythonTaskAuthor` 를 호출합니다. 초안 는 요청 control 이
 활성화 되기 전에 계속 validate 및 단계 되어야 합니다.
- **단계 산출물** 는 VM 이 아니라 내용 기반 주소를 가진 산출물 저장소 에 씁니다.
- **테스트 shadow 계획** 은 `PlanningVmTaskRunner` 를 사용합니다. Operator API 에는 실행
 Command 를 만들 수 있는 Managed Identity가 없습니다.
- **요청 통제된 실행** 은 타입이 지정된 `ActionProposal` 을 publish 합니다. Console
 프로세스 에서 `VmTaskRunner` 를 호출하거나 file 을 copy 하거나 Python 을 실행하지
 않습니다.
- **생성 예약** 은 선택한 카탈로그 작업 흐름, 산출물, 인벤토리 대상 의
 strict cron 연결 을 저장합니다. 이후 스케줄러 tick 이 타입이 지정된 event 를
 publish 합니다.

Background 작업, busy 입력, skill의 Operator API 조립 보조 로직은 `routes/`에 두며 결과 패널은 검증 issue, 산출물 참조, planned file 및 바이트 개수,
대상 기능 또는 submitted 상관관계 id 를 표시합니다. Control loop 가
proposal 을 수락한 후 런타임 상태 는 Processes 및 감사 표면 에 이어집니다.

### 13.8 채팅 답변의 그라운딩된 코드

Command Deck 의 최종 답변에 fenced 코드 블록 이 있으면 Operator API 는 이를 크기가
제한된 `GroundedCodeArtifact` 로 추출합니다. 산출물 는 코드, language, SHA-256
참조, static 검증 결과를 포함합니다. Python 블록 은 가져오기 하거나
실행하지 않고 parse 및 compile 합니다. 다른 언어는 검증되었다고 표시하지 않고
`not_checked` 로 표시합니다. Fenced `chart` 블록은 rich-answer chart component가 렌더링하는
표현 data이므로 `GroundedCodeArtifact` 추출에서 제외하며 **코드 근거** 아래에 두 번째로
표시하지 않습니다.

Console 은 기본적으로 코드 를 **코드 근거** 아래에 접어서 표시합니다. Disclosure
를 펼치면 그라운딩된 정확한 내용, 산출물 참조, 구문 검증 통과
여부를 볼 수 있습니다. 최종 산출물 는 완료되지 않은 스트리밍 토큰 이 아니라
검증된 최종 답변에서 생성됩니다. Tab 은 transcript 와 함께 산출물 를
`sessionStorage` 에 보존할 수 있으며, 방어적 파서 는 malformed 또는 oversized
항목 를 제거합니다.

이 표시 계약은 실행 권한을 부여하지 않습니다.

- **런타임 쓰기 없음**: chat 경로 는 생성된 코드 를 FDAI 출처 tree, 설치된
 package, 컨테이너 파일 시스템 또는 활성 Git 체크아웃 에 쓰지 않습니다.
- **Chat 실행 없음**: Operator API 에서는 static parsing 만 수행합니다. 생성된
 모듈 을 가져오기 하거나 subprocess 를 시작하거나 virtual 환경 를 만들거나
 `VmTaskRunner` 를 호출하지 않습니다.
- **통제된 실행 분리**: 코드 실행이 필요한 운영자 는 `PythonTask` 를 만들고
 단계 한 후 section 13.7 flow 를 통해 타입이 지정된 `ActionProposal` 을 publish 합니다.
 Risk gate, 승인 상한, 실행기 신원, 감사 경로 가 계속 권위입니다.
- **Temporary 저장소 는 샌드박스 자체가 아님**: 실행기 는 writable file 을 위해
 `/tmp/fdai-code/<run-id>` 와 같은 per-run 디렉터리 를 사용할 수 있습니다. 실제
 격리 은 separate principal, 읽기 전용 런타임 파일 시스템, 경로 및 symlink 검사,
 리소스 한도, 네트워크 정책, 정리 에서 나옵니다. 경로 convention 만으로는
 security 경계 가 되지 않습니다.

### 13.9 온톨로지 레지스트리 변환 결과

`GET /ontology/graph`는 웹 콘솔의 Objects, Links 및 Actions 보기를 위한 읽기 전용
레지스트리 변환 결과입니다. 네 번째 **온톨로지 맵** 보기는 `rule-catalog`와
`PANTHEON_SPECS`에서 생성된 버전형 카탈로그 산출물을 로드합니다. 이 맵은 런타임 근거가
아닌 참조 변환 결과이며 `/inventory/graph`를 호출하거나 아키텍처에 연결하지 않습니다.

저장 위치 질문은 요청한 경로를 누락된 화면 필드로 취급하지 않고 결정적 카탈로그 계약을
사용합니다. 기본 ObjectType과 LinkType 정의는 `rule-catalog/vocabulary/object-types/` 및
`rule-catalog/vocabulary/link-types/`에서, ActionType 정의는 `rule-catalog/action-types/`에서
가져옵니다. Downstream 조립은 검증된 추가 루트를 주입할 수 있습니다. Operator API는 시작할
때 합성된 정의를 변경할 수 없는 in-memory 카탈로그로 로드하고 `/ontology/graph`가 그 카탈로그를
읽기 전용 변환 결과로 제공합니다. 운영 온톨로지 instance는 PostgreSQL의
`ontology_resource`와 `ontology_link`에 저장됩니다. ObjectType과 LinkType 메타데이터도 FK 검증용
참조로 PostgreSQL에 동기화될 수 있지만, 해당 행은 정의의 authoring 출처 또는 출처 of
truth가 아닙니다. SPA는 별도 복사본을 저장하지 않습니다. JSON 및 SSE chat은 서술기를 호출하지
않고 동일한 계약 답변을 반환합니다.

- **Objects**: ObjectType 과 LinkType edge 를 선택된 하나의 결정적 one-hop
 neighborhood 로 렌더링합니다. Inspector 는 기록된 속성 와 들어오는 및
 나가는 relationship 을 표시합니다.
- **Links**: LinkType 을 선택하면 기록된 모든 `from_type -> to_type` 엔드포인트 pair,
 cardinality, causal, transitive, temporal 플래그 를 표시합니다. 콘솔은 카탈로그에
 없는 relationship 의미 규칙 를 추론하지 않습니다.
- **Actions**: 응답은 로드된 ActionType 카탈로그를 완전한 safety-contract 기록 로
 포함합니다. 카탈로그 뷰는 category, 트리거, 실행 경로, 롤백 계약,
 기본값 모드, precondition, stop 조건, blast-radius 선언, tier 상한,
 승격 gate 를 표시합니다.
- **온톨로지 맵**: 생성된 그래프는 ObjectType, ResourceType, 활성 Rule, ActionType,
 작업 흐름, Pantheon Agent, SignalType 및 Property를 하나의 결정론적 토폴로지로 결합합니다.
 노드 크기는 연결 수, 노드 색상은 온톨로지 종류를 나타내고 가중 링크는 안정적인
 토폴로지 커뮤니티를 형성합니다. 오퍼레이터는 검색, 선택, 드래그, 이동, 확대 및 축소,
 맞춤, 관계 종류 필터링 및 전체 화면을 사용할 수 있습니다. 노드를 선택하면 1단계 관계가
 강조되고 읽기 전용 검사기에 세부 정보가 표시됩니다. 생성기는 같은 그래프에서 목업과
 콘솔 페이로드를 출력하므로 카탈로그가 바뀔 때 두 화면이 함께 변경됩니다.

ActionType 변환 결과 은 additive 입니다. 이전 배포 에서는
`action_type_count`와 `action_types`가 없거나 0일 수 있지만 ObjectType과 LinkType 탐색은
계속 동작합니다. ActionType은 선택된 ObjectType의 1단계 그래프에는 넣지 않지만, 생성된
온톨로지 맵에는 Rule, 작업 흐름 및 Agent 링크가 있는 카탈로그 노드로 포함됩니다. 네 보기는
모두 읽기 전용이며 액션 또는 승인 호출을 실행하지 않습니다.
