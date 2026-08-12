---
title: Operator Console Module Map and Boundaries
translation_of: operator-console-module-map.md
translation_source_sha: 48771d037f66c61f9bbe4851d6ab9757447a9353
translation_revised: 2026-08-12
---
# Operator Console 모듈 지도 and Boundaries

이 문서는 Operator Console 대화 모듈, 경로, 채널 및 프로바이더 경계를 매핑합니다.
Main 콘솔 계약을 확장하지 않고 출처 소유권을 찾을 수 있게 유지합니다.

## 실행 가능한 기준선

[`operator-console-module-inventory.json`](operator-console-module-inventory.json)은 현재 Operator API
패키지 책임, 경로 계열 분류, 후보 대상 및 가져오기 표면 상태를 기록합니다. 이 인벤토리는
file-count 목표가 아닌 설명 기준이지만, executable 완전성 게이트는 현재 모든 모듈 디렉터리와
경로 모듈을 분류된 상태로 유지하도록 요구합니다.
후보 대상은 패키지 힌트입니다. 새 프로세스, 신원, 전송 계층 또는 데이터 소유자의 게이트는 [서비스 승격과 데이터 소유권](../architecture/service-graduation-and-ownership-ko.md)입니다.
[`test_operator_api_layout.py`](../../../services/operator-service/tests/)는 현재 모든
패키지와 경로 모듈이 분류된 상태인지 확인하고, exact 기본 메서드, 경로, route-name 집합 및 대표 HTTP
묶음을 고정합니다. 의도적인 기본 경로 추가는 같은 변경에서 검토된 기준선을 갱신합니다.

### Dependency-direction 게이트

`check-operator-api-boundaries.py`는 애플리케이션 코드를 로드하지 않고 가져오기를 파싱합니다. 정리된
core-to-delivery, runtime-to-Operator API, ingestion-to-Operator API, shared
delivery-to-application, application-to-provider-adapter 및 route-to-provider-adapter 방향은 enforced
검사로 유지합니다. 기존 route-to-core 정책 가져오기와 반대
방향의 Operator API 서비스 가져오기는 report-only debt로 유지하므로 이후 이행 issue가 이를 줄이는
동안 관련 없는 작업을 차단하지 않습니다.

게이트는 운영 factory, 개발 factory 및 런타임 초기화의 unique 내부 가져오기도
측정합니다. 검토된 한도 이상인 조립 루트는
`.check-operator-api-boundaries.allowlist`에 exact 경로, 최대 가져오기 개수 및 바로 앞의
justification comment가 필요합니다. 검토된 최대를 넘기려면 새 검토가 필요합니다. Justification
누락, 검토되지 않은 high-fanout 루트 또는 stale exception은 검사를 실패시킵니다. Report-only 룰은
`.check-operator-api-boundaries.debt`를 집계 non-growth 예산으로 사용합니다. Debt는 파일 변경 없이
줄어들 수 있지만 증가는 CI를 실패시킵니다. 좁은 패키지 또는 touched-file 검사에는 하나 이상의
`--path <repository-relative-path>` 인자를 사용합니다. Stale detection도 동일한 선택 범위로
제한되며 CI와 pre-push는 항상 full 검사를 실행합니다.

Enforced 발견 사항은 의존성을 neutral 계약 또는 프로바이더 경계로 이동하고 검토된 조립
루트에서 구현을 연결하여 해결합니다. Reverse 서비스 가져오기를 위해 허용 목록 항목을 추가하지
않습니다. Report-only 발견 사항은 이행 인벤토리이며 owning 패키지가 정리된 후에만 강제 적용 대상으로
전환합니다.

`check-boundary-docstrings.py`는 exact 검토된 패키지 모듈에서 비어 있지 않은 Responsibility,
경계, 권한 and 상태, 의존성, 배포 섹션을 검사합니다. 범위는 보고
모드로 시작하고 검토 후에만 강제 적용으로 이동합니다. Justified exclusion은 누락된, 범위 밖
또는 불필요한 상태가 되면 실패합니다. 이 structural AST 검사는 의미 truth를 증명하지 않습니다.

### 첫 reversible 계열 이행

Issue 70은 다섯 개의 `routes/audit*.py` 모듈을 첫 이행 계열로 선택합니다. Executable
인벤토리는 이미 이 모듈을 하나의 read-projection 계열로 분류합니다. 각 모듈은 계열 외부에 한두
개의 direct Python 소비자, 한 개에서 세 개의 내부 FDAI 가져오기 및 측정된 90-day 구간에 한두 번의 변경이
있습니다. 이 계열은 읽기 전용이며 승인, 실행, CORS 또는 lifespan 행동을 소유하지 않으므로
채팅, 작업 흐름 또는 조사보다 behavioral 표면이 작습니다.

구현 소유자는 `fdai.delivery.operator_api.projections.audit`로 이동하며 파일 이름과 공개
symbol은 변경하지 않습니다. App-side 감사 조회 use와 운영 패널 조립은 새 패키지 파사드를
가져옵니다. 개발 조립은 shared 운영 패널 빌더를 통해 같은 파사드에 도달합니다.
기존의 모든 `routes.audit_*` 모듈은 명시적 per-module 호환성 심으로 유지합니다. 메서드,
경로, 경로 이름, 권한 확인, 응답 페이로드, 출처 이력 및 데이터베이스 소유권은 변경하지 않습니다.

Rollback에서도 두 가져오기 표면을 안정적으로 유지합니다. 구현 파일을 `routes/` 아래에
복원하고 새 `projections.audit` 모듈 각각을 복원된 경로 모듈의 forwarding 심으로 변경하며
조립 가져오기는 패키지 파사드에 유지합니다. 이 절차는 API 또는 wire 롤백 없이 physical
소유권을 되돌리고 broad 와일드카드 파사드를 만들지 않습니다.

### 대화 턴 애플리케이션 경계

Issue 71은 JSON 및 SSE 채팅 경로가 공유하는 process-local application-service 경계로
`fdai.delivery.operator_api.application.conversation_turn`을 도입합니다. Authentication과 범위가 제한된
전송 계층 파싱 이후 각 경로는 변경할 수 없는 `ConversationTurnInput`을 만들고 하나의 타입이 지정된 수명 주기를
시작합니다. 기존 근거, 계획 수립, 서술, 검증, 이력, busy-input, 진행 상황 및 취소
구현은 프로세스 내로 유지되고 해당 수명 주기를 통해 완료됩니다. 네트워크 홉 또는 별도 배포
서비스는 추가하지 않습니다.

입력은 server-derived principal, 대화, 요청, 상관관계, 프롬프트, 로케일, target-agent,
evidence-reference, history-count 및 transport-mode 값만 포함합니다. 프로바이더 범위, 자격 증명,
승인, 역할, 실행기 신원 또는 변경 가능한 맥락 필드는 없습니다. 변경할 수 없는 결과는 최종
상태, 검증된 답변, 검증 요약, 근거 참조, 표현 산출물, 위임 메타데이터 및
명시적 실패 상세를 기록합니다. 고정된 wire 스냅샷은 필드 추가 없이 기존 JSON 페이로드 또는 SSE
최종 프레임으로 round-trip합니다.

서비스는 non-authoritative이며 호출 사이에 상태를 유지하지 않습니다. Approval, 실행, 승격,
프로바이더 범위 선택을 수행할 수 없고 Thor 신원을 받을 수 없습니다. HTTP 상태 대응, SSE
순서/개정 번호, 헤더, 경로 이름, 권한 확인 및 취소 전송 계층은 경로가 계속 소유합니다.
Bragi는 표현 translator로 유지되고 authority-bearing 에이전트 작업은 타입이 지정된 pub/sub을 계속 사용합니다.

### 대화 의도 그래프 변환 결과 경계

Shared ontology-query SDK는 exact-plan `IntentGraph` 및 `IntentGraphEvidence` 기록을 소유합니다.
명시적 변환 결과 함수는 내부 프레임/계획 다이제스트를 제거하고 정본 목표 인자를 parse하며
범위가 제한된 Console v2 그래프 및 v1 근거 형태만 발행합니다. Console 파서는 그래프와 목표 증적
수준 모두에서 최종 취소를 수락하여 valid 최종 갱신을 폐기하지 않고
`request_cancelled`를 보존합니다. 변환 결과는 8개를 초과하는 목표, 잘못된 display 목표 id, deep/oversized
인자, excess 의존성 및 12개를 초과하는 근거 참조를 거부합니다. 프로바이더 본문을 copy하지
않고 실행 권한을 부여하지 않습니다.

Core는 principal-manifest-verified 조회 계획에서 이 기록을 만듭니다. Operator는 영속 의미
변환 결과를 기존 `done` 프레임으로 변환하고 운영 SSE는 Console 파서를 변경하지 않은 채 그래프,
근거, 검증 counter 및 결정론적 답변을 전달합니다.

독립 Operator/Core 브리지에는 이제 의미 턴과 최종 변환 결과를 위한 가산 버전 1.2 wire
형태가 있습니다. Operator는 authentication, 영속 발신함 acceptance, principal 범위로 한정된 재생 및 SSE
순서를 계속 담당합니다. Core는 exact release/principal 매니페스트 선택, 검증된 계획 실행 및 근거
증적 생성을 계속 담당합니다. 이 계약은 서비스 구현의 direct 가져오기 또는 의미 페이로드의
older peer downgrade를 허용하지 않습니다.

Core 의미 런타임은 이제 계획 수립, dependency-wave 실행 및 이 변환 결과를 하나의 비동기 서버
결과로 구성합니다. 모든 accepted 턴은 답변, 명확화, 보류, 지원하지 않는, 액션 초안 또는
취소로 종료됩니다. Synchronous 호환성 조정기는 exact 정본 명령을 기본값으로
사용하며 명시적 temporary 호출자가 `legacy` 모드를 선택하지 않으면 natural-language 정규식, 키워드
서술 또는 canonical-string 읽기 계획 수립을 적용하지 않습니다.

독립 Operator 패키지는 `adapters/` 아래에 구체적인 Event Hubs Kafka 어댑터를 소유합니다. 운영
조립은 초기화, 요청 토픽 및 변환 결과 토픽이 all-or-none 검증을 통과한 경우에만 두
포트에 하나의 어댑터를 구성합니다. 생산자는 멱등적이고 소비자는 수동 커밋을 사용합니다.
Valid 대응은 의미 브리지가 처리한 뒤에만 커밋하고 malformed 또는 oversized JSON은 형제
DLQ에 쓴 다음 커밋합니다. 어댑터는 managed-identity 자격 증명을 소유하고 애플리케이션 수명 주기에서
이를 닫습니다. 명시적으로 주입된 발행기/출처 쌍은 테스트 및 다운스트림 재정의 경계로 유지됩니다.
의미 Kafka와 dev-only 로컬 서술기는 상호 배타적입니다. 같은 process 경계가
`GET /chat/health`를 소유하며 bridge worker 준비 상태를 직접 투영하고 영속 conversation projection을
요구하지 않습니다.

### 대화 단정 애플리케이션 경계

SD-01 단정 구획은 `fdai.delivery.operator_api.application.conversation.claims` 아래에서
결정론적 answer-claim 검증을 소유합니다. 추출, 근거 수집, matching,
매니페스트 construction 및 frozen-corpus evaluation은 프로세스 안에서 실행되며 request-local 상태만
유지합니다. 경로 어댑터는 authentication, HTTP 상태 대응, JSON 묶음, SSE 순서,
취소 및 최종 렌더링을 계속 소유합니다.

소유된 최종 검증기는 명시적 단정 패키지 파사드를 가져옵니다. 기존
`routes.chat_claim*` 모듈의 repository-wide 소비자는 내부 구현 또는 테스트 가져오기였고
같은 구획에서 이동했으므로 점유 호환성 심은 남기지 않습니다. Rollback은 구현
모듈과 파사드를 `routes/` 아래에 복원한 다음 단정 패키지 파사드가 복원된 소유자를 가리키게 합니다.
이 과정에서 JSON 또는 SSE wire 계약은 변경하지 않습니다.

### 대화 검증 애플리케이션 경계

SD-01 검증 구획은 `fdai.delivery.operator_api.application.conversation.verification`
아래에서 최종 답변 검증을 소유합니다. 이 패키지는 정본 결과, text-integrity
검사, 결정론적 점유/근거 coordination, 범위가 제한된 인시던트/agent-activity 렌더링,
도구/operational 검증 핸들러를 포함합니다. Request-local이며 HTTP 상태 대응, JSON
묶음, SSE 순서, authentication, 취소 및 최종 프레임 assembly는 경로에 유지합니다.

내부 경로와 테스트 소비자는 명시적 패키지 파사드를 가져옵니다. 기능 카탈로그는 해당
owned 패키지를 직접 사용하므로 `routes/` 아래에 검증 호환성 모듈이 남지 않습니다.
Rollback은 이동한 모듈을 `routes/` 아래에 복원하고 패키지 파사드가 복원된 소유자를 가리키게 합니다.
JSON, SSE, authentication 또는 conversation-history 행동은 변경하지 않습니다.

### 대화 표현 변환 결과 경계

SD-01 표현 구획은
`fdai.delivery.operator_api.projections.conversation.presentation` 아래에서 value-free 배치
선택과 검증된 근거 산출물 compilation을 소유합니다. 이 패키지에는 표현 계약,
형태 프로파일, 범위가 제한된 플래너, 결정론적 인벤토리 및 subscription-health 산출물 컴파일러가
포함됩니다. 읽기 전용이며 request-local입니다.

JSON 및 SSE 경로는 명시적 표현 파사드를 가져오기하며 authentication, HTTP 상태 대응,
JSON 묶음, SSE 순서와 개정 번호, 취소, 최종 assembly 및 대화 이력을
계속 소유합니다. 기존 `routes.chat_presentation*` 모듈은 내부 가져오기 경로였으므로 호환성
심을 남기지 않습니다. 이 이동은 정본 텍스트 대체 경로, 산출물 스키마, localized 라벨,
근거 참조, 바이트 한계 및 플래너 성능 저하를 정확히 보존합니다. Rollback은 경로
구현 모듈을 복원하고 wire 계약을 변경하지 않은 채 표현 파사드가 복원된
소유자를 가리키게 합니다.

### 대화 인벤토리 애플리케이션 및 변환 결과 경계

SD-01 인벤토리 구획은 타입이 지정된 조회, 결정론적 compilation, 후속 조치 범위,
catalog-backed 언어/리소스 의미, 온톨로지 함수, 의미 수집 및 provider-read
coordination을 `fdai.delivery.operator_api.application.conversation.capabilities.inventory`
아래에서 소유합니다. 이 기능은 읽기 전용이고 request-local입니다. HTTP, SSE,
authentication, 취소, 이력 또는 인벤토리 쓰기는 소유하지 않습니다.

Sanitization, 현재/활동 결과 변환 결과, scheduled-shutdown 변환 결과 및 결정론적
답변 렌더링은 `fdai.delivery.operator_api.projections.conversation.inventory` 아래에 있습니다.
경로와 최종 검증은 책임에 따라 명시적 애플리케이션 또는 변환 결과 파사드를 가져옵니다.
기존 `routes.chat_inventory*` 소비자는 모두 내부 구현 또는 테스트 코드였으므로
호환성 심을 남기지 않습니다. JSON, SSE 순서/개정 번호, 권한 확인, 프로바이더 범위 및
대화 이력 행동은 변경되지 않습니다.

Rollback은 인벤토리 구현 모듈을 `routes/` 아래에 복원하고 두 인벤토리 패키지
파사드가 복원된 소유자를 가리키게 합니다. Wire 계약과 권위 있는 인벤토리 프로바이더는
변경하지 않습니다.

### 대화 백엔드 애플리케이션 및 어댑터 경계

SD-01 백엔드 구획은 `fdai.delivery.operator_api.application.conversation.backend` 아래에서
프로바이더 중립적인 계약과 request-local 지연 시간 라우팅을 소유합니다. 애플리케이션 패키지는 injected
백엔드 중 하나를 선택하고 범위가 제한된 장애 조치와 멀티모달 전달을 보존하며 자격 증명이 없는 엔드포인트
메타데이터만 노출합니다. Azure 또는 OpenAI 구현은 가져오기하지 않습니다.

구체적인 Azure workload-identity 및 OpenAI-compatible HTTP 구현, shared 응답 검증,
metering 전송 계층, resolved-model 로딩 및 시작 construction은
`fdai.delivery.operator_api.adapters.conversation` 아래에 있습니다. JSON 및 SSE 경로는 authentication,
HTTP 상태 대응, 순서와 개정 번호, 취소, 최종 전달 및 대화 이력을 계속
소유합니다. 기존 `routes.chat_backend_*` 모듈의 저장소 소비자는 모두 내부 구현 또는
테스트 가져오기였으므로 호환성 심을 남기지 않습니다.

Rollback은 다섯 백엔드 모듈을 `routes/` 아래에 복원한 다음 애플리케이션 및 어댑터 파사드가 복원된
소유자를 가리키게 합니다. Auth, 프로바이더 범위, JSON 또는 SSE는 변경하지 않습니다.

### 대화 근거 애플리케이션 경계

SD-01 근거 구획은
`fdai.delivery.operator_api.application.conversation.evidence` 아래에서 읽기 전용 operational
근거 해석, 출처 이력 변환 결과, 범위가 제한된 가지 수명 주기 및 authority-preserving 결과
병합을 소유합니다. Operational 조회는 authorized 서버 읽기 모델을 계속 읽으며 정확한
`matched`, `summary`, `ambiguous`, `none`, `unavailable` 결과를 유지합니다. 근거가 없거나
충돌하거나 선택되지 않은 경우 지원하지 않는 답변으로 넘어가지 않고 명시적으로 유지합니다.

독립 가지는 계속 동시하게 완료되며 정본 명세 순서로 반환됩니다. 병합은 기존
도구, operational, 에이전트 및 공개 웹 권한 precedence를 유지합니다. JSON 및 SSE 경로는
authentication, 요청 파싱, HTTP 상태 대응, 프레임 순서와 개정 번호, 취소,
최종 assembly 및 대화 이력을 계속 소유합니다. 기존 `routes.chat_evidence*` 소비자는
모두 내부 출처 또는 테스트 가져오기였고 이 구획에서 이동했으므로 호환성 심은 남기지
않습니다. Rollback은 다섯 경로 구현을 복원하고 JSON, SSE, authentication, 근거
권한 또는 이력을 변경하지 않은 채 근거 파사드가 복원된 소유자를 가리키게 합니다.

### 대화 진행 상황 메트릭 변환 결과 경계

SD-01 스트리밍 메트릭 구획은
`fdai.delivery.operator_api.projections.conversation.stream_metrics` 아래에서 큐에 수락된
진행 상황의 pure reduction을 소유합니다. First-progress 지연 시간, 최종 가지 결과와 소요 시간,
출력 잘림의 집계만 기록합니다. 프롬프트, 답변, 가지 id, 채널 id, principal id 또는
리소스 식별자는 보관하지 않습니다.

SSE 경로는 프레임 순서, 큐 admission, 취소 및 전송 계층 전달을 계속 소유합니다.
기존 `routes.chat_stream_metrics` 모듈에는 외부 호환성 소비자가 없었으므로 심을
남기지 않습니다. Rollback은 집약기를 `routes/` 아래에 복원하고 메트릭 이름, SSE 프레임 또는
취소 행동을 변경하지 않은 채 스트림 경로 가져오기를 되돌립니다.

### 대화 최종 변환 결과 경계

SD-01 최종 구획은 `fdai.delivery.operator_api.projections.conversation.terminal` 아래에서 pure
verification-frame assembly, 최종 페이로드 compilation, 측정된 LLM 사용량 렌더링, 영속 인벤토리
결과 맥락 및 source-failure 재생 맥락을 소유합니다. 이 패키지는 최종 응답에 사용되는
범위가 제한된 공개 intent-graph 및 conversation-policy 요약도 소유합니다. 이 경계는 읽기 전용이며
request-local입니다.

JSON 및 SSE 경로는 계속 authentication, 요청 파싱, HTTP 상태 대응, 프레임 순서와 개정 번호,
취소, 최종 전달 및 대화 이력을 소유합니다. 이전 경로 모듈 4개의 모든 저장소
소비자는 명시적 최종 파사드로 이동했고 패키지는 `fdai.delivery.operator_api.routes` 모듈을 가져오기하지
않으므로 호환성 심이 남지 않습니다. Rollback은 경로 구현 4개를 복원하고 최종 파사드를
redirect하며 두 wire 계약은 변경하지 않습니다.

### 대화 post-generation 애플리케이션 경계

SD-01 post-generation 구획은
`fdai.delivery.operator_api.application.conversation.post_generation` 아래에서 streamed 턴
완료를 소유합니다. 답변 세대 이후 이 패키지는 기존 순서대로 범위가 제한된 quality 검토,
결정론적 검증, 최종 페이로드 검증, principal 범위 assistant-turn 영속성 및
off-path post-turn 검토를 조정합니다. Pure 페이로드 compilation은
`projections.conversation.terminal`에 위임하고 영속 이력은 injected 저장기를 통해서만 씁니다.

SSE 경로는 권한 확인, 요청 파싱, 하트비트 framing, 연결 및 busy-input 취소,
요청 순서와 개정 번호, trajectory 변환 결과 및 최종 전송 계층 전달을 계속 소유합니다. 이
패키지는 `fdai.delivery.operator_api.routes` 모듈을 가져오기하지 않습니다. 기존
`routes.chat_stream_post_generation` 경로는 내부이었으므로 호환성 심을 남기지 않습니다.
Rollback은 해당 경로 모듈을 복원하고 stream-route 가져오기를 변경하며 프레임 순서, JSON 또는 SSE
최종 페이로드, 검증, 이력 및 post-turn 검토 행동은 변경하지 않습니다.

### 대화 요청 preparation 애플리케이션 경계

SD-01 request-preparation 슬라이스는
`fdai.delivery.operator_api.application.conversation.request_preparation` 아래에서 content-policy
검증과 재생, 사용자 선호 설정, document-reference 해석, complete-history 조립,
검증된 이전 맥락, 리소스와 최신성 맥락, 후속 조치 범위, 답변 계획 수립,
target-agent 파생을 소유합니다. 이 패키지는 server-authenticated, byte-bounded JSON 객체 하나를
받고 타입이 지정된 prepared 요청 또는 재생 결과를 반환합니다. Process-local이고 권한이
없으며 `operator_api.routes` 모듈을 가져오기하지 않습니다.

`routes/chat_stream_request.py`는 `authorize(request)`, Content-Length preflight, raw 본문 읽기,
바이트 제한, JSON-object 파싱, Starlette `HTTPException` 대응 및 SSE 어댑터 호출을 유지합니다.
JSON 채팅은 기존 전송 계층 순서를 유지하면서 같은 preparation 계약과 보조 로직을 가져옵니다.
기존 route-owned 이력 모듈은 전체 이동했고 문서, 재생, resource-context, 신원 보조 로직은
혼합 경로 모듈에서 분리했습니다. 모든 소비자가 내부 출처 또는 테스트 가져오기였으므로
호환성 심은 남기지 않았습니다.

문서 해석기 실패는 JSON과 SSE 모두 애플리케이션 경계에서 하나의 고정된 사용 불가
상세로 변환됩니다. Exception chaining은 내부 진단을 보존하지만 프로바이더 URL, 토큰 및 오류
텍스트는 HTTP 경계를 넘지 않습니다.

Rollback은 이력과 preparation 보조 로직을 `routes/` 아래에 복원하고 `chat_stream_setup.py`를
복원한 뒤 JSON과 SSE 가져오기를 되돌립니다. Authentication, 상태 코드, 본문 한계,
content-policy 재생, 이력, 문서 접근, 답변 계획 및 두 wire 계약은 변경하지 않습니다.

### 대화 수명 주기 애플리케이션 경계

SD-01 수명 주기 구획은 shadow answer-planning 작업 coordination을
`application.conversation.planning`으로, Korean 서술기 검토를
`application.conversation.post_generation.quality`로, 입력 content-policy 복구를
`application.conversation.request_preparation.content_policy`로, request-local steer 및 활성
서술기 중단 coordination을 `application.conversation.busy_input`으로 이동합니다. 이 모듈들은
범위가 제한된 process-local 상태만 유지하며 `operator_api.routes` 모듈을 가져오기하지 않습니다.

`BusyInputCoordinator`는 active-turn 등록과 중재를 담당하는 코어 권한으로 유지됩니다.
애플리케이션 보조 로직은 safe-boundary와 cancel-event 계약만 사용하며 대화 취소를 Thor,
ActionType 또는 managed-resource 상태에 연결하지 않습니다. JSON 및 SSE 경로는 authentication, HTTP/SSE
상태 대응, 프레임 순서와 개정 번호, 연결 취소, 이력 전송 계층 및 최종 전달을
계속 소유합니다.

이전 경로 모듈 소비자는 모두 내부 출처 또는 테스트 코드였으므로 호환성 심은 남기지
않습니다. Rollback은 네 경로 구현을 복원하고 내부 가져오기를 되돌리며 계획 수립 한계,
quality 검증, 정책 복구, steering, 중단, JSON 또는 SSE 행동은 변경하지 않습니다.

### 대화 최종 support 변환 결과 경계

SD-01 최종 support 구획은 범위가 제한된 trajectory-detail 재생, 결정론적 current-screen T0
답변, 명시적 선택 민감정보가 제거된 model-call 추적, 검증된 resource-follow-up 응답 맥락을
`fdai.delivery.operator_api.projections.conversation` 아래에서 소유합니다. 이 변환 결과는 읽기 전용이고
request-local입니다. `operator_api.routes` 모듈을 가져오기하지 않고 영속 쓰기, 모델 호출 또는 프로바이더
호출을 수행하지 않습니다.

요청 리소스 파싱 및 후속 조치 contextualization은
`application.conversation.request_preparation.resource_context`에 유지됩니다. Azure 및 OpenAI-compatible
어댑터는 이미 수행된 모델 요청과 응답을 추적 변환 결과에 기록하고 프로바이더 호출은 계속
어댑터가 소유합니다. JSON 및 SSE 경로는 authentication, 본문 파싱, 상태 대응, 프레임 순서와
개정 번호, 취소, 최종 전달, 대화 이력을 유지합니다. 이전 경로 소비자는 모두
내부이므로 호환성 심은 남기지 않습니다. Rollback은 네 경로 구현을 복원하고
내부 소비자를 redirect하며 wire 계약은 변경하지 않습니다.

### 대화 영속성 및 문서 근거 경계

SD-01 영속성 구획은 principal 범위 대화 기록 쓰기, 내용이 없는 정책 증적, 재생
메타데이터 및 conversation-image 수명 주기를
`fdai.delivery.operator_api.persistence.conversation` 아래에서 소유합니다. 명시적 파사드는 고정된
운영자/assistant 멱등성 키, ordered 턴 할당 및 범위가 제한된 온톨로지 변환 결과를
보존합니다. Assistant 변환 결과 시간 초과 또는 실패는 영속 답변 쓰기 이후 logged 성능 저하로
유지되며 저장된 답변 또는 최종 응답을 변경하지 않습니다.

검증된 이미지는 기존 pending 생성, exact-attempt 보상 및 영속 finalization 순서를
유지합니다. Turn 메타데이터에는 이미지 id, display 이름 및 검증된 매체 타입만 포함됩니다. 이미지 바이트는
principal과 대화 범위 이미지 저장소에 유지됩니다. Pure 통제된 문서 맥락 및
검증 병합은 `projections.conversation.document_evidence`에 있으며 exact 인용 값과
중복 참조 제거 시 고정된 first-occurrence 순서를 보존합니다.

JSON 및 SSE 경로는 authentication, 요청 파싱, HTTP 상태 대응, 프레임 순서와 개정 번호,
취소 및 전송 계층 전달을 유지합니다. 이전 route-module 소비자는 모두 내부 출처 또는
테스트 코드였으므로 호환성 심은 남기지 않습니다. Rollback은 세 구현을 `routes/` 아래에
복원하고 내부 가져오기를 되돌리며 대화 기록 신원, 이미지 만료, 문서 참조, JSON 또는 SSE 행동은
변경하지 않습니다.

### 대화 기능 애플리케이션 경계

SD-01 기능 구획은 범위가 제한된 Pantheon 위임, runtime-skill 공개,
configuration-baseline 읽기, 공개 웹 근거 해석, request-time 기능 가시성 및 strict
토폴로지 의도를 `fdai.delivery.operator_api.application.conversation` 아래에서 소유합니다. 에이전트
위임은 기존 런타임 및 브리지 계약을 사용하는 읽기 전용 어댑터로 유지됩니다. 액션 제안과
인계 구체화를 비활성화하며 Pantheon의 judgment, 승인, 실행, 복구 또는 감사 권한을
Operator API로 옮기지 않습니다.

프로바이더 중립적인 웹 검색 해석기는 결정론적 및 의미 의도 precedence, sanitization, 범위가 제한된
시간 초과, 가용성, 진행 상황 및 실패 시 차단 프로바이더 오류를
`application.conversation.capabilities.web_search` 아래에서 소유합니다. Azure 후보 construction과
환경 로딩은 `adapters.conversation.web_search`에 둡니다. 호출자 텍스트는 프로바이더 범위, allowed
도메인, 엔드포인트, 배포 또는 자격 증명을 제공하지 않습니다. 구성 표류는 정확한 server-pinned
문서 경로를 action-context 문구보다 먼저 유지하고, 토폴로지 의도는 계속 exact 서버가 소유한
선택자를 요구합니다.

JSON 및 SSE 경로는 authentication, 요청 파싱, HTTP 상태 대응, 프레임 순서와 개정 번호,
취소, 최종 전달 및 대화 이력을 유지합니다. 이전 경로 모듈 6개의 소비자는
모두 내부 출처 또는 테스트 가져오기였으므로 호환성 심을 남기지 않습니다. Rollback은 해당
구현을 `routes/` 아래에 복원하고 내부 가져오기를 되돌리며 권한 분류, 프로바이더
범위, 의도 precedence 또는 wire 계약은 변경하지 않습니다.

### 최종 대화 경로 종결

커밋 `e141ab07e`은 여섯 파일의 structural 인벤토리를 확립하고 compiled user 정책,
assurance 정책 및 one-shot 응답 완료를 명시적 애플리케이션 소유자 뒤로 이동했습니다. Pure
최종 요약과 페이로드 값은 `projections.conversation.terminal`에 유지하며 대화
애플리케이션, 변환 결과 및 영속성 패키지는 경로 모듈을 가져오기하지 않습니다.

JSON 및 streamed 턴 수명 주기는 이제 `application/conversation/turn_execution` 아래에 있습니다.
타입이 지정된 서비스는 Starlette, 프로바이더 어댑터 또는 경로 모듈을 가져오기하지 않고 요청 preparation,
계획 수립, 근거, 세대와 스트림 수집, busy 입력, 검증, 응답 완료,
영속성, metering 및 user-context 변환 결과를 조정합니다. `chat.py`는 authentication, 범위가 제한된
JSON 파싱, 애플리케이션 error-to-status 대응, `JSONResponse` 전달, 경로 연결 및 검토된
호환성 가져오기를 유지합니다.

`chat_stream.py`는 이제 authentication과 범위가 제한된 요청 전송 계층 위임, 스트림 시작 전
애플리케이션 error-to-status 대응, `StreamingResponse` construction, SSE 인코딩, 하트비트 바이트,
순서와 개정 번호 필드, 비동기 iterator 정리를 통한 connection-close 취소만 유지합니다.
애플리케이션 이벤트가 정본 답변 `revision`을 소유하고 경로는 wire-frame 순서용 별도 단조 증가
`seq`를 추가하며 개정 번호를 변경하지 않고 보존합니다. `chat_registration.py`는 등록,
`chat_stream_protocol.py`는 SSE 프로토콜,
`chat_stream_request.py`는 요청 전송 계층을 소유합니다. Chat 계열은 SSE 프레임 순서, 재생,
중단, 취소, 이력 및 최종 페이로드를 보존하면서 structural transport-only 상태가
되었습니다.

### 변경 계보 변환 결과 경계

SD-06 Operator 변환 결과는 `fdai.delivery.operator_api.projections.change_lineage` 아래에서
정본 변경할 수 없는 변경 계보의 범위가 제한된 요약 및 상세 화면을 소유합니다. 읽기 전용이고
request-local이며 후보 전용 learning과 실행/승격 권한 0을 보존하고 프로바이더 I/O나
영속성을 수행하지 않습니다.

### 변경할 수 없는 앱 조립

Issue 72는 `OperatorApiConfig(**kwargs)`를 범위가 제한된 호환성 생성자로 유지하고 경로를 등록하기
전에 `split()`으로 변환 결과합니다. `OperatorApiValues`에는 inert environment-derived 값만 포함됩니다.
`OperatorApiRuntimeBindings`는 process-local 의존성을 스트림, 변환 결과, 수명 주기, read-view,
대화, governed-route 및 fixed-HTTP 기록으로 그룹화합니다. 각 등록 함수는 이전 방식
집계 대신 자신이 소유한 기능 기록만 받습니다.

모든 기록은 고정된입니다. 대응 입력은 읽기 전용 화면으로 복사되며, 의도적으로 공유하는 프로바이더는
소비자 전체에서 같은 객체를 참조해야 합니다. `OperatorApiComposition.validate()`는 경로를 추가하거나
수명 주기 콜백을 시작하기 전에 shared 참조와 필수 cross-group 쌍을 검사합니다. 기록에는 raw
프로바이더 자격 증명 또는 Thor 실행기 신원이 없습니다. 운영과 interactive 로컬 조립은
계속 같은 이전 방식 생성자를 만들고 동일한 분리 및 검증 경계로 진입하므로 synthetic
운영 대체 경로이나 venue-specific 경로 모델을 추가하지 않습니다.

경로 메서드, 경로, 이름, 등록 순서, 권한 확인, CORS, 응답 페이로드 및 가용성 기본값은
변경하지 않습니다. Rollback은 변경할 수 없는 기록 정의와 검증을 `app/config.py`로 다시 옮기고
`app/composition.py`를 제거하며 이전 방식 생성자, `split()` 대응, 공개 `main` 파사드 및 등록
서명을 그대로 유지합니다. 이 절차는 wire 또는 호출자 이행 없이 physical 소유권을 되돌립니다.

| 패키지 | 현재 책임 | 이행 규칙 |
|---------|-----------|----------------|
| 루트 | 공개 파사드 및 foundational 계약 | 분류된 replacement가 준비될 때까지 유지합니다. |
| `adapters/` | 독립적으로 소유한 Kafka 실시간 단계 소비자를 포함하는 HTTP 경로 밖의 구체적인 Operator API 프로바이더 구현 | 프로바이더 I/O를 애플리케이션 계약 뒤에 유지하고 단계 레코드는 검증과 전달 뒤에만 커밋합니다. |
| `adapters/conversation/` | Azure 및 OpenAI-compatible 서술기 전송 계층과 웹 검색 시작 construction | 명시적 모듈로 가져오기하고 자격 증명, 엔드포인트, 배포 선택 및 전송 계층은 애플리케이션과 경로 밖에 유지합니다. |
| `app/` | Shared ASGI assembly, middleware, 등록 및 lifespan | HTTP 조립 경계로 유지합니다. |
| `application/` | 타입이 지정된 process-local, non-authoritative 애플리케이션 coordination | Service-graduation 근거가 프로세스 경계를 정당화할 때까지 유지합니다. |
| `application/conversation/` | HTTP 전송 계층 밖의 process-local 대화 계획 수립, 서버 정책 해석, one-shot JSON 실행, 응답 완료, 기능 가시성, strict 의도 분류, busy-input steering, 중단 및 기능 | Service-graduation 근거가 준비될 때까지 프로세스 안에 유지하고 HTTP 및 SSE 전송 계층 책임은 경로에 둡니다. |
| `application/conversation/turn_execution/` | 타입이 지정된, Starlette-free JSON 및 streamed 턴 요청 preparation, 계획 수립, 근거, 세대, 검증, 영속성, metering 및 완료 coordination | 명시적 파사드로 가져오기하고 authentication, 본문 파싱, 상태 대응, JSON/SSE 인코딩, 하트비트, 순서, 개정 번호 및 응답 전달은 경로에 유지합니다. |
| `application/conversation/capabilities/` | 도메인별 타입이 지정된 process-local 에이전트 위임, runtime-skill, configuration-drift, 웹 검색 및 read-model 기능 | Non-authoritative 기능 소유자로 유지하고 injected 읽기 전용 런타임과 프로바이더 계약을 사용합니다. |
| `application/conversation/capabilities/inventory/` | 타입이 지정된 인벤토리 조회, 결정론적 compilation, 의미 grounding 및 provider-read coordination | 명시적 패키지 파사드로 가져오기하고 JSON, SSE, authentication 및 이력은 경로에 유지합니다. |
| `application/conversation/backend/` | 프로바이더 중립적인 백엔드 계약 및 request-local 지연 시간 라우팅 | 명시적 파사드로 가져오기하고 프로바이더 구현은 어댑터에 유지합니다. |
| `application/conversation/claims/` | 결정론적 answer-claim 추출 및 범위가 제한된 근거 검증 | 명시적 패키지 파사드로 가져오기하고 JSON, SSE 및 authentication은 경로에 유지합니다. |
| `application/conversation/verification/` | 결정론적 최종 답변 검증 및 범위가 제한된 근거 렌더링 | 명시적 패키지 파사드로 가져오기하고 wire 행동과 authentication은 경로에 유지합니다. |
| `application/conversation/evidence/` | Operational 근거 해석, 출처 이력, 가지 수명 주기 및 authority-preserving 병합 | 명시적 패키지 파사드로 가져오기하고 JSON, SSE, authentication, 취소 및 이력은 경로에 유지합니다. |
| `application/conversation/post_generation/` | Quality 검토, 검증, 이력 영속성 coordination, 최종 페이로드 검증 및 post-turn 검토 | 명시적 패키지 파사드로 가져오기하고 권한 확인, 요청 파싱, 하트비트 framing, 순서, 취소 및 SSE 전달은 경로에 유지합니다. |
| `application/conversation/request_preparation/` | 내용 정책과 재생, 선호 설정, 문서 참조, 이력, 이전 맥락, 리소스와 최신성 맥락, 후속 조치 범위, 답변 계획 및 target-agent 파생 | 명시적 패키지 파사드로 가져오기하고 권한 확인, 범위가 제한된 본문 파싱, HTTP 대응, SSE 순서 및 전송 계층 전달은 경로에 유지합니다. |
| `dev/` | Interactive 로컬 및 test-only 프로바이더 조립 | 운영 가져오기에서 사용할 수 없게 유지합니다. |
| `dev/fixtures/` | Synthetic pytest-only 고정본 | 운영 조립 밖에 유지합니다. |
| `persistence/` | Operator API read-model 및 conversation-state 영속성 구현 | 소유된 저장소 계약 뒤에 유지합니다. |
| `persistence/conversation/` | principal 범위 대화 기록, 정책 증적, 재생 메타데이터 및 conversation-image 수명 주기 영속성 | 명시적 파사드로 가져오기하고 HTTP, SSE, authentication, 상태 대응 및 전송 계층은 경로에 유지합니다. |
| `projections/` | HTTP 경로 밖의 읽기 전용 변환 결과 소유권 | Migrated 계열의 소유자로 유지합니다. |
| `projections/audit/` | 감사 조회 및 자율성/FinOps 측정 변환 결과 | 독립적인 Operator 서비스가 범위가 제한된 `GET /kpi/llm-cost`를 포함한 동등한 PostgreSQL 읽기 모델을 소유합니다. Pricing, 실행기 권한 및 Core 구현 가져오기는 해당 서비스 밖에 유지합니다. |
| `projections/change_lineage/` | 범위가 제한된 정본 Change-lineage 요약 및 상세 화면 | 명시적 파사드로 가져오기하고 HTTP, 프로바이더 I/O, 영속성, 실행 및 승격은 패키지 밖에 유지합니다. |
| `projections/conversation/` | 화면 데이터, exact 문서 근거, 모델 추적, trajectory 상세, 리소스 응답 맥락 및 큐에 수락된 진행 상황 메트릭 reduction을 포함하는 request-local 대화 읽기 변환 결과 | Service-graduation 근거가 준비될 때까지 프로세스 안에 유지합니다. |
| `projections/conversation/presentation/` | Value-free 배치 선택 및 검증된 근거 산출물 compilation | 명시적 파사드로 가져오기하고 JSON 및 SSE 행동은 경로에 유지합니다. |
| `projections/conversation/inventory/` | 인벤토리 근거 sanitization, 결과 변환 결과 및 결정론적 렌더링 | 명시적 파사드로 가져오기하고 조회 compilation과 프로바이더 coordination은 애플리케이션 패키지에 유지합니다. |
| `projections/conversation/terminal/` | 최종 페이로드, LLM 사용량, resource-result 및 source-failure 변환 결과 | 명시적 파사드로 가져오기하고 JSON, SSE, authentication, 취소 및 이력은 경로에 유지합니다. |
| `production/` | 운영 프로바이더 construction 및 연결 | Wire 행동을 변경하지 않고 fanout을 점진적으로 줄입니다. |
| `routes/` | HTTP/SSE 전송 계층, 경로 등록, 도메인 요청 어댑터 및 분류된 호환성 파사드 | 전송 계층 및 검토된 파사드 경계로 유지하고 대화 수명 주기 orchestration은 타입이 지정된 애플리케이션 파사드 뒤에 둡니다. |
| `streaming/` | `/live/stream`을 위한 읽기 전용 범위 제한 SSE 전달과 실패 시 차단하는 Core 단계 프레임 검증 | 인증과 HTTP 응답 소유권은 경로에 유지하고 연결 유지 신호에서 런타임 준비 상태를 추론하지 않습니다. |

`fdai.delivery.operator_api.main`은 공개 앱 파사드입니다. `read_model`은 검토된 replacement가 준비될
때까지 공개 전달 계약으로 유지합니다. `fdai.delivery.auth`는 framework-neutral bearer 및 Entra
검증을 소유하고 `operator_api.auth`와 `operator_api.entra_verifier`는 호환성 파사드로만
유지됩니다.
`main` 파사드의 `busy_input_runtime` re-export는 새 런타임 소유권 점유가 아닌 transitional 공개
경계입니다.
현재 포크 및 reporting guide가 직접 가져오기하므로 `routes.panels`와 `routes.reporting`은 transitional
공개 확장 경계로 유지합니다. 그 외 개별 `routes.*` 모듈은 내부 구현 경로이며,
분류된 호환성 필요가 있을 때만 모듈별 forwarding 심을 사용합니다.
Runtime-owned agent-state 기록 및 event-bus 게시는 `fdai.delivery.agent_activity`에 있으므로
headless 런타임은 Operator API 스트리밍 구현을 가져오기하지 않습니다. 프로비저닝의
`streaming.provision_stream` 호환성은 별도로 분류합니다. Issue 71은 기준선에 기록된 채팅 wire
debt를 해소합니다. 버전 1 의미 프레임에는 서버가 소유한 요청 id와 정수 순서가 필요하고,
known HTTP 실패는 범위가 제한된 상태와 사유를 유지하며, 생산자는 브라우저의 256 KiB 한도를 넘는
프레임을 거부합니다.

이 이동 동안 PostgreSQL과 Alembic은 shared 이행 권한으로 유지됩니다. 모듈 또는 경로 이행은
두 번째 스키마 소유자를 만들지 않습니다. Service-owned 스키마 및 이행 레인에는 별도 검토된 경계가
필요합니다.

## Core 및 전달 지도

- [`services/core-control-plane/src/fdai/core/conversation/`](../../../services/core-control-plane/src/fdai/core/conversation)
  - `coordinator.py`는 계층 2 `ConversationCoordinator` orchestration을 소유합니다.
  - `tool_arguments.py`는 pure canonical-verb 인자 파싱을 소유하며 도구 권한을 부여하지 않습니다.
  - `read_plan.py`는 bounded-plan 검증, serial 읽기 실행, 결과 집계 및
    identity-scoped high-signal 충돌 detection을 소유합니다.
  - `contextual_translation.py`는 현재/이전 턴 텍스트의 scalar 인자 출처 이력을 소유합니다.
  - `grounded_answer_validation.py`는 서술과 변경할 수 없는 도구 권한 사이의 conservative
    canonical-ID, numeric, 시각, 최신성 및 exact-reference 검사를 소유합니다.
  - `tools.py`는 `SystemConsoleTool`과 계층 1 모듈에 delegate하는 구현을 정의합니다.
  - `narrator.py`는 synchronous 의도, contextual, proposal-only read-plan, zero-execution
    명확화 및 presentation-only grounded-answer 프로토콜을 정의합니다.
  - `session.py`는 disposable 코어/CLI `ConversationSession` 변환 결과를 제공합니다. 운영
    대화 기록은 principal 범위로 한정된 `ConversationHistoryStore`가 소유합니다.
- [`cli/`](../../../cli)
  - `src/repl.ts`는 shared `POST /chat` 조정기용 IME-safe stdin/stdout 채널입니다.
  - `src/cockpit.ts`는 self-describing 화면 스냅샷을 같은 조정기에 publish하는 실제 운영 SSE
    표현입니다.
- [`services/core-control-plane/src/fdai/core/conversation/channel_gateway.py`](../../../services/core-control-plane/src/fdai/core/conversation/channel_gateway.py)는
  발신자를 인증하고 메시지 멱등성 키를 점유하며 조정기를 호출합니다. 영속 전달이
  구성되면 프로바이더 전송 전에 완전한 응답을 저장합니다.
- [`services/operator-service/src/fdai_operator_service//`](../../../services/operator-service/src/fdai_operator_service/)
  - `teams.py`는 bearer-token 검증 이후 Bot Framework 활동을 normalize하고 injected 회신
    발행기를 사용합니다. Payload-supplied 회신 URL을 신뢰하지 않습니다.
  - `slack.py`는 timestamped 서명을 검증하고 재생 또는 bot-authored 이벤트를 차단하며 메시지를
    normalize하고 injected 회신 발행기를 사용합니다.
  - Slack, Teams 및 web 첨부 계약은
    [대화 첨부](conversation-attachments-ko.md)를 통해 수렴합니다. Dedicated WebSocket
    어댑터는 선택적입니다.
- [`current_time.py`](../../../services/operator-service/src/fdai_operator_service/)는 injected
  aware 시계와 principal IANA 표준 시간대에서 current-time 질문을 해석합니다.

## Operator API 경로 소유권

- `application/conversation/backend/`는 프로바이더 중립적인 백엔드 계약, prompt-policy 오류, 범위가 제한된
  지연 시간 라우팅, 장애 조치 및 멀티모달 전달을 소유합니다. 프로바이더 I/O, HTTP, SSE, authentication 또는
  영속 상태는 소유하지 않습니다.
- `adapters/conversation/`은 Azure workload-identity 및 OpenAI-compatible 프로바이더 호출, 응답 검증,
  metering 전송 계층, resolved-model 로딩 및 백엔드 construction을 소유합니다. 경로 권한 확인, JSON
  또는 SSE 전달, 대화 이력은 소유하지 않습니다.
- `application/conversation/claims/`는 결정론적 점유 추출, 근거 matching 및 근거
  매니페스트를 소유합니다. HTTP, SSE, authentication 또는 영속 상태는 소유하지 않습니다.
- `application/conversation/verification/`은 최종 답변 무결성, 결정론적 근거
  검증 및 범위가 제한된 검증 산문을 소유합니다. HTTP, SSE, authentication, 취소
  또는 영속 상태는 소유하지 않습니다.
- `application/conversation/capabilities/inventory/`는 타입이 지정된 인벤토리 조회, compilation,
  의미 grounding 및 provider-read coordination을 소유합니다. HTTP, SSE, authentication,
  이력, 렌더링 또는 인벤토리 쓰기는 소유하지 않습니다.
- `application/conversation/evidence/`는 읽기 전용 operational 근거 해석, 출처 이력,
  정본 가지 정렬 및 authority-preserving 병합을 소유합니다. HTTP, SSE, authentication,
  취소, 이력 또는 영속 상태는 소유하지 않습니다.
- `application/conversation/post_generation/`은 ordered quality 검토, 검증, 최종
  검증, 이력 영속성 coordination 및 post-turn 검토를 소유합니다. HTTP,
  authentication, 요청 파싱, 하트비트 framing, SSE 순서, 연결 취소 또는
  전송 계층 전달은 소유하지 않습니다.
- `application/conversation/request_preparation/`은 content-policy 검증과 재생,
  선호 설정, 문서 참조, 이력 조립, 검증된 이전 맥락, 리소스와 최신성 맥락,
  후속 조치 범위, 답변 계획 수립 및 target-agent 파생을 소유합니다. 요청, HTTP 상태 대응,
  권한 확인, SSE 순서, 취소 또는 전송 계층 전달은 소유하지 않습니다.
- `application/conversation/planning.py`는 범위가 제한된 shadow 계획 수립 작업 시작, 메타데이터 및 배출을
  소유합니다. `application/conversation/busy_input.py`는 safe-boundary steering과 활성 서술기
  중단만 소유합니다. 두 모듈 모두 연결 취소, 코어 busy-input 권한,
  액션 상태 또는 영속 상태를 소유하지 않습니다.
- `application/conversation/capabilities/`는 액션, prior-context, current-time, 출처,
  준비 상태, 지식, metering, 로그, 네트워크, subscription-health, T2 복구, 행동 및
  read-model 보조 로직을 소유합니다. `application/conversation/`은 턴/intent-graph 계획 수립, 프롬프트
  assembly, 공개 웹 의도 및 vision 검증을 소유합니다. 두 패키지 모두 `routes`를 가져오기하지
  않습니다.
- `projections/conversation/presentation/`은 value-free 표현 계획, 검증된 근거 산출물
  compilation, 한계 및 localized 라벨을 소유합니다. HTTP, SSE, authentication, 취소,
  최종 전달 또는 영속 상태는 소유하지 않습니다.
- `projections/conversation/inventory/`는 인벤토리 근거 sanitization, 결과 변환 결과 및
  결정론적 렌더링을 소유합니다. 프로바이더 선택, 조회 compilation, HTTP, SSE,
  authentication, 이력 또는 영속 상태는 소유하지 않습니다.
- `projections/conversation/terminal/`은 최종 verification-frame 및 페이로드 assembly, 측정된 LLM
  사용량 렌더링, 영속 결과 맥락 및 범위가 제한된 공개 최종 요약을 소유합니다. HTTP, SSE
  순서, authentication, 취소, 이력 또는 영속 상태는 소유하지 않습니다.
- `projections/conversation/stream_metrics.py`는 큐에 수락된 집계 진행 상황 reduction을
  소유합니다. 프레임 순서, 큐 admission, 취소, 전송 계층 또는 영속 상태는
  소유하지 않습니다.
- `projections/conversation/`은 incident-dossier와 RCA 렌더링, 범위가 제한된 execution-output
  변환 결과, provider-receipt 변환 결과, tool-progress reduction, current-screen T0 렌더링,
  민감정보가 제거된 모델 추적, trajectory-detail 재생 및 resource-follow-up 응답 변환 결과를 소유합니다.
  이동된 내부 보조 로직에는 호환성 심이 없습니다.
- `routes/chat_stream_request.py`는 권한 확인, Content-Length와 raw-body 한계, JSON-object
  파싱, 애플리케이션 오류의 HTTP 대응 및 SSE preparation 어댑터를 소유합니다.
- `application/conversation/turn_execution/`은 타입이 지정된 의존성과 결과를 통해 one-shot JSON
  요청 preparation, 계획 수립, 근거, 세대, 검증, 영속성, metering 및 최종
  완료를 소유합니다. Starlette, 경로 또는 provider-adapter 모듈을 가져오기하지 않습니다.
- 다섯 파일의 `chat*.py` structural 인벤토리에는 `chat.py`, `chat_registration.py`,
  `chat_stream.py`, `chat_stream_protocol.py` 및 `chat_stream_request.py`가 포함됩니다. `chat.py`는 이제
  JSON HTTP 전송 계층과 호환성 연결만 소유합니다. `chat_stream.py`는 SSE 전송 계층만 소유하고
  애플리케이션 개정 번호를 전송 계층 순서가 있는 프레임으로 매핑합니다. 나머지 세 파일은 각각
  등록, SSE 프로토콜 및 request-transport 소유자로 유지됩니다.
- `application/conversation/capabilities/knowledge_context.py`는 상태 쓰기 없이 exact prior-turn
  런북, 출처 최신성, consented
  기억 및 materialized learning을 읽습니다.
- `application/conversation/vision_prompt.py`는 검증된 이미지를 변환 결과합니다.
- `routes/`는 JSON/SSE 묶음, authentication, HTTP/SSE 상태 대응, 프레임 순서,
  연결 취소, 경로 등록과 그래프, data-source, 준비 상태 변환 결과의 HTTP
  핸들러를 유지합니다.
- `read_investigation_responder.py`는 등록된 Heimdall 읽기 의도를 타입이 지정된 근거에서 렌더링합니다.
  근거가 없으면 명시적 사용 불가 답변을 반환합니다. `read_investigation_catalog.py`는 카탈로그
  ID, 소유권 또는 계획 연결 표류 시 시작을 차단합니다.
- `routes/rule_catalog.py`는 읽기 전용 활성/발견 Rule 참조 변환 결과를 제공합니다.
  카탈로그와 일치하는 활성 세대에서만 의미 순위를 사용하고, 그 외에는 명시적인
  degraded 상태와 함께 lexical 결과를 반환합니다. Reader-gated `POST /rules/search`는 exact
  `catalog.search_rules` 온톨로지 함수를 invoke하고 evaluation 또는 실행 권한 없이
  수집 및 함수 증적을 반환합니다. 세대 발행은 API 시작 밖에 유지합니다.

영어 및 한국어 표현 리터럴은 NFC UTF-8을 사용합니다. Escaped Hangul은 정확한 근거 설명이 있는
code-point 행동에만 허용됩니다. 이 표현은 머신 값, 근거 권한, 로케일 선택 또는
typed-pipeline 결정을 변경하지 않습니다.

스케줄러 Runs, 자동화 Blueprints, Scheduled Continuations,
[관리형 trajectory 데이터셋](governed-trajectory-datasets-ko.md),
[실행 백엔드 상태](execution-backends-ko.md)는 읽기 전용 메타데이터를 제공합니다. 이 화면에는 활성화,
제출, 재시도, 취소, 정리, execute 또는 승인 컨트롤이 없습니다. 자격 증명 및 Thor 신원을
제외하고 명령을 SPA 밖에 유지합니다.

[`tools/chat.py`](../../../tools/chat.py)는 코어 조정기용 headless JSONL 개발 실행 장치이며 별도
정책 구현이 아닙니다.

## 경계 불변식

`core/conversation/`은 프로토콜만 가져옵니다. Azure SDK, HTTP, Bot Framework 및 프로바이더 호출은
`delivery/` 아래에 있습니다. 대화 표현은 실행 권한이 되지 않습니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| Console framing, 도구, RBAC 및 안전성 | [Operator Console](operator-console-ko.md) |
| 런타임 모델 및 DI 경계 | [Operator Console 런타임 모델](operator-console-runtime-model-ko.md) |
| 영속 채널 전달 | [영속 대화 전달](durable-conversation-delivery-ko.md) |
