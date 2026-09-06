---
title: 오퍼레이터 콘솔 점진적 대화
translation_of: operator-console-progressive-conversations.md
translation_source_sha: aa7bec5262e2a1ce5ea289f8432c6d0a9e7d1475
translation_revised: 2026-09-06
---
# 오퍼레이터 콘솔 점진적 대화

이 문서는 점진적으로 진행되는 오퍼레이터 콘솔 대화의 채널 중립적인 가지 수명 주기, 순서가 있는
집약, 검증된 개정판, 범위가 제한된 진행 상황 계약을 소유합니다.

Command Deck의 화면 대화는 경로 범위 `ViewSnapshot`을 받습니다. 등록된 모든 패널은 로딩, 오류,
화면 전환 상태에서 대체 정보로 화면 식별자와 목적을 제공합니다. 검증된 표시 근거가 있는 경로는
이 대체 정보를 범위가 제한된 사실과 레코드로 교체할 수 있습니다.
각 특화 스냅샷은 목적과 함께 공통 카탈로그에서 구성한 용어집을 선언하므로 브라우저가 용어를
추론하지 않아도 경로 맥락을 자체 설명할 수 있습니다.
타입 기반 인시던트 바인딩이 자동 조사 프롬프트를 소유하면 Deck은 활성 패널의 사실, 레코드,
용어집, 제목을 해당 제출에서 제외합니다. 현재 화면 맥락이 인시던트 근거로 나타나지 않도록
최소한의 로캘, 경로, principal 메타데이터와 서버에서 검증한 정확한 인시던트 바인딩만 유지합니다.

대화 복원은 기존 대화 행과 사용자 범위의 의미 요청 및 결과 기록을 함께 읽습니다.
캐시가 답변 없는 사용자 질문으로 끝나면 불완전하므로 서버 조회를 생략하지 않습니다.
저장된 최종 결과는 같은 검증된 표현 경로로 표시하며 질문을 다시 보내거나 모델을 호출하거나
이력을 다시 쓰지 않습니다. 복원 중 새 입력이나 세션 전환이 발생하면 화면을 덮어쓰지 않습니다.

검증된 자문 최종 응답은 완성된 원문을 즉시 표시합니다. 서버가 검토를 마친 뒤 인위적인 타자
효과를 다시 재생하지 않습니다. 일반 스트리밍 조각은 기존 표시 속도와 순서를 유지하며 잘못된
자문 메타데이터는 이 빠른 경로를 선택할 수 없습니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 적응형 답변 출처와 재실행 표현 | implemented | `adaptive-answer.test.ts` 33개, `turn-history.test.ts` 및 `command-deck.session.test.ts` 20개, Console 타입 검사와 빌드 통과 | 일반 지식에는 전체 답변의 조회 증적을 부여하지 않습니다. 목표별 근거와 별도 초안 설명은 스트림 및 복원 후에도 유지하며, 잘못된 스트림은 미검증 텍스트를 지웁니다. 브라우저 런타임 검증은 별도입니다. |
| 일반 대화 예시 질문 즉시 전송 | 구현됨 | `general-conversation-intro.tsx`, `command-deck-view.tsx`, `conversation-entry.spec.ts` | 양 언어의 예시 버튼 세 개는 클릭하거나 키보드로 실행하면 표시된 질문을 선택한 맥락에 맞는 일반 전송 경로로 보냅니다. 툴팁은 즉시 전송 동작을 안내합니다. 실제 모델 호출 없이 합성 응답으로 예시 질문 검사 6개와 기존 진입점 검사 2개를 통과했습니다. |
| Web 점진적 스트림 집약 | 구현됨 | [`backend-stream.ts`](../../../console/src/deck/backend-stream.ts), [`backend-stream-fallback.test.ts`](../../../console/src/deck/backend-stream-fallback.test.ts), [`backend-stream-v1-contract.test.ts`](../../../console/src/deck/backend-stream-v1-contract.test.ts) | 집중 테스트는 순서가 있는 프레임, 재생 거부, 가지 수명 주기, 확정된 개정판, 부분 턴을 다룹니다. 이 행은 Teams 또는 Slack 런타임 검증을 주장하지 않습니다. |
| 직접 응답 수명 주기 억제 | 구현됨 | [`semantic_turn_runtime.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/semantic_turn_runtime.py), [`command-deck-view.tsx`](../../../console/src/deck/command-deck-view.tsx), [`retrieval-trace.tsx`](../../../console/src/deck/retrieval-trace.tsx), [`use-command-deck-submit.ts`](../../../console/src/deck/use-command-deck-submit.ts), 집중 Operator 및 Console 검사 | Operator는 스트림을 열 때 운영자 텍스트를 검사하거나 최종 처리 결과를 예측하지 않습니다. 모델이 선택한 타입 기반 직접 응답은 `done`만 보냅니다. Console은 제출 직후 영속 기록에 남지 않는 간결한 대기 행을 표시하고, 관측된 진행 프레임이 온 뒤에만 상세 준비 추적으로 확장하며, 직접 최종 응답이 오면 두 상태를 모두 제거합니다. 브라우저는 표현의 크기 전환과 최종 응답 전용 텍스트 공개만 보간하며 수명 주기 내용을 만들지 않습니다. |
| 계약으로 검증된 시작 질문 | 구현됨 | `intro-suggestions.ts`, 이중 언어 Console 카탈로그, `semantic_operational_summary_planning.py`, 질문 은행 산출물, 집중 Core, Console 및 질문 은행 검사 | 비어 있는 Deck에는 검토된 Resource 상태, Resource Health, Service Health 질문 5개만 표시합니다. 수락되고 모호하지 않은 타입 기반 함수 intent는 두 번째 모델 호출 없이 결정론적으로 검증된 프레임을 재사용할 수 있습니다. 구현되지 않은 화면 요약, tier 구성, 승인, 실패 원인, 기회 질문은 준비된 예시로 표시하지 않습니다. |
| 인시던트 바인딩 맥락 격리 | 구현됨 | `command-deck.tsx`, `use-command-deck-events.ts`, 집중 Console 검사 및 인증된 Browser Entra 요청 확인 | 자동 인시던트 조사는 Dashboard 사실이나 레코드 없이 정확한 인시던트 바인딩을 제출합니다. 검증된 답변은 `query.incident_evidence`를 읽습니다. 경로 메타데이터는 표현 맥락으로만 남고 답변 근거가 되지 않습니다. |
| 일반 대화와 현재 화면 대화 분리 | 구현됨 | `conversation-context.ts`, `general-conversation-intro.tsx`, `command-deck.tsx`, `navigation-shell.tsx`, `conversation-entry.spec.ts`, 집중 Deck 검사 | 좌측 메뉴는 현재 탭의 일반 대화를 열거나 이어가고 하단과 키보드 진입점은 현재 화면의 별도 대화를 선택합니다. 일반 질문에는 명시적으로 추가한 화면만 포함합니다. 초안, 저장한 맥락, 배치 설정은 각각 유지합니다. 작업 초안의 로그인 검토 힌트와 별도 실행기 권한도 유지합니다. |
| Operator 대화 SSE 종료 | 구현됨 | [`shutdown.py`](../../../services/operator-service/src/fdai_operator_service/streaming/shutdown.py), [`factory.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/factory.py), [`test_stream_shutdown.py`](../../../services/operator-service/tests/test_stream_shutdown.py) | 애플리케이션 종료와 호출자 취소는 모두 진행 중인 source 읽기를 취소하고 기다린 뒤 스트림을 닫습니다. 유휴 source는 정상 종료를 막거나 분리된 읽기 task를 남길 수 없습니다. |
| 채널 중립적 최종 집약 | 구현됨 | [`conversation_channel.py`](../../../services/core-control-plane/src/fdai/shared/providers/conversation_channel.py), [`test_rich_contract.py`](../../../services/core-control-plane/tests/delivery/channels/test_rich_contract.py) | 집중 계약 테스트 36개가 통과했습니다. Teams와 Slack은 영속 재생 전체에서 동일한 정본 답변, 제한, 근거 참조, `execution_authority=false`, 단조 증가하는 최종 확정 갱신을 보존합니다. 운영 A3 게시자나 통제된 채널 런타임 증적을 주장하지 않습니다. |
| 드로어 표현 및 새 대화 정체성 | 진행 중 | [`use-command-deck-sessions.ts`](../../../console/src/deck/use-command-deck-sessions.ts), [`console-routes.spec.ts`](../../../console/tests/live-e2e/console-routes.spec.ts) | Console은 저장된 드로어 표시 여부와 독립적으로 새 세션을 만들며, 라이브 테스트는 이제 새 대화에서 요청을 격리합니다. 인증된 런타임 증적 통과가 아직 필요합니다. |
| 선제적 담당 업무 인수인계 대화 | 구현됨 | `handover_runtime.py`; `handover_binding.py`; `console/src/handover-*`; Command Deck 세션 및 문서 업로드 경로; 집중 Operator 및 Console 검사 | 실제 최종 책임자 매핑은 피로도 한도가 적용된 에이전트 대화 하나를 열 수 있습니다. 서버는 주체, 목표, 세션, 에이전트를 검증하고 영속적으로 연결하며 인시던트 또는 승인 작업 중 초대를 억제합니다. 승인된 근거가 이후 사용할 수 없게 되면 목표를 stale로 표시합니다. 배포 증적은 남아 있습니다. |
| 통제된 4단계 온톨로지 증적 | 진행 중 | [`console-routes.spec.ts`](../../../console/tests/live-e2e/console-routes.spec.ts) | 외부 Browser Entra 실행기는 정확한 Operator API 원본을 요구하고, 성공 경로에서 모호하지 않은 조회 가능 유형 요청을 사용하며, 요청 및 변환 결과에 결속된 증적을 펼치고, 산출물을 출처, 작업 영역 패치, 실행 구성 digest에 결속합니다. `answered`가 아닌 증적을 받으면 답변 전용 UI 단언 전에 중단합니다. `검증됨`을 뒷받침하는 새 보존 통과 산출물은 없습니다. |
| 이중 언어 무작위 릴리스 게이트 | 진행 중 | [`ontology-query-assurance-readiness.ts`](../../../console/tests/live-e2e/ontology-query-assurance-readiness.ts), [`ontology-query-assurance.test.ts`](../../../console/tests/live-e2e/ontology-query-assurance.test.ts) | 집중 보증 테스트 49개가 통과했습니다. 통제되는 모든 실행은 범위가 제한된 실행 식별자를 요구하고 질문 범위의 안정된 backend session id를 파생하므로 checkpoint 재개는 정체성을 보존하지만 새 실행은 다른 실행의 영속 semantic projection을 재사용할 수 없습니다. 전체 집단은 영어와 한국어 모두에서 근거가 완전한 answered 턴이 없으면 `production_ready=true`를 보고할 수 없습니다. 새 100-case 통과 산출물은 여전히 필요합니다. |
| 의미 명확화 표현 | 구현됨 | [`verification-presentation.ts`](../../../console/src/deck/verification-presentation.ts), [`grounded-reply.tsx`](../../../console/src/deck/grounded-reply.tsx), 집중 Console 검사 | `semantic_clarification_required`를 `Context required`로 표시하면서 범위가 제한된 서버 작성 질문을 기본 답변으로 보존합니다. 질문이 잘못되었거나 없으면 지역화된 대체 문구를 사용합니다. 분류는 제어 평면이 실제로 방출하는 이유 코드만 다룹니다. 인증되고 보존된 증적은 열린 항목으로 남아 있습니다. |
| 타입 기반 근거 보류 표현 | 구현됨 | [`backend-stream.ts`](../../../console/src/deck/backend-stream.ts), [`grounded-reply.tsx`](../../../console/src/deck/grounded-reply.tsx), 집중 스트림 및 Console 검사, Core 부분 인과 표현 검사 | `semantic_evidence_held`와 `semantic_evidence_incomplete`는 온톨로지 조회 검증에 비어 있지 않은 완료 근거가 있고 같은 요청의 보류 증적이 일치하는 사유, 계획, 실행, 권한 없음 digest와 `authoritative_evidence_unavailable`을 보고할 때만 범위가 제한된 정본 최종 답변을 보존합니다. 검증 사유가 증적 검증 전에 타입 기반 보류 주장을 식별하므로 누락되거나 다른 요청에 속하거나 불일치하는 증적은 거부를 우회할 수 없습니다. 정본 최종 본문이 없거나 공백뿐이면 대기 중인 token을 내보내기 전에 거부하고, 단조 증가하는 미검증 revision과 token pump generation 무효화로 이미 표시된 초안과 로컬 burst token을 철회한 뒤 지역화 대체 문구를 표시합니다. |
| 의미 모델 투명성 | 구현됨 | `semantic_planning.py`, `semantic_planning_cascade.py`, Azure 의미 계획 어댑터, `semantic_turn_processor.py`, `semantic_turn_presentation.py`, 집중 Core 및 Operator 검사 | 완료된 모든 의미 판단, 프레임, 계획 모델 호출은 표현을 위해 범위가 제한된 실측 모델, 처리 시간 및 토큰 metadata를 보존합니다. 요청과 응답 본문은 요청에서 명시적으로 활성화한 경우에만 projection하며 결정론적으로 민감정보를 제거하고 범위를 제한합니다. 이 정보는 계획 근거나 실행 권한이 되지 않습니다. |
| 실시간 의미 조회 진행 상황 | 구현됨 | `SemanticQueryProgress`, `query_execution.py`, Core semantic consumer, Operator semantic bridge, 집중 progress 검사 25개 통과 | Core는 검증된 실제 조회 노드의 시작 및 최종 관측만 별도 best-effort topic으로 발행합니다. Operator는 실제 내부 조회를 렌더링하고 권위 있는 최종 receipt가 도착하면 일시적인 진행 상태를 폐기합니다. 진행 정보는 범위가 제한되고 읽기 전용이며 `execution_authority=false`로 고정됩니다. 인증된 Command Deck 증적은 열린 상태입니다. |
| 현재 화면 컨텍스트 게시 | 구현됨 | [`context.tsx`](../../../console/src/deck/context.tsx), [`app.tsx`](../../../console/src/app.tsx), [`view-contract.test.ts`](../../../console/src/routes/view-contract.test.ts), 집중 Console 컨텍스트 및 경로 검사, 데스크톱 브라우저 검사 | 등록된 모든 패널은 로딩, 사용 불가, 오류, 경로 전환 상태에서 자신을 식별합니다. 특화 게시기는 이전 경로의 스냅샷을 넘기지 않고 대체 정보를 범위가 제한된 표시 사실과 공통 카탈로그 용어집으로 교체할 수 있습니다. |
| 검증된 의미 답변 표현 | 검증됨 | [`semantic_turn_processor.py`](../../../services/core-control-plane/src/fdai_core_service/semantic_turn_processor.py), [`semantic_turn_presentation.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/semantic_turn_presentation.py), [`semantic_turn_runtime.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/semantic_turn_runtime.py), [`semantic-answer-presentation.spec.ts`](../../../console/tests/live-e2e/semantic-answer-presentation.spec.ts), `.fdai/live-validation/semantic-answer-presentation-244d003ef77bd37dc0041f0b6a29634cdbaacb91-post-validation/` | 범위가 제한된 인증 Web/한국어 경로는 명시적 workspace patch digest와 함께 중앙 검증된 source revision `244d003ef`에서 검증됐습니다. 최초 턴과 재생성 턴은 관찰된 5단계, 동일한 인시던트 및 기술 출력 digest, 읽기 전용 근거 수집, primary JSON 미노출, `execution_authority=false`를 유지했습니다. 이 상태는 Teams, Slack, 4단계 온톨로지 실행기 또는 이중 언어 100-case 집단을 주장하지 않습니다. |
| 결정론적 교차 채널 표현 계획 | 구현됨 | `semantic_presentation_semantics.py`, `semantic_turn_processor.py`, `presentation_rows.py`, `presentation_planner.py`, `presentation_artifact_v2.py`, `presentation.py`, Console artifact 및 module registry, 집중 semantic presentation 검사 137개, Console deck 검사 693개, chart browser 검사 4개 통과 | Core는 검증된 종단 행에서 renderer-neutral semantics를 파생합니다. Operator는 시각화 10개 중 하나를 선택하기 전에 shape별 역할과 행 불변식을 다시 검증합니다. Web과 channel artifact 경계는 동일한 bounded schema를 적용합니다. Legacy와 v2 경로는 읽기 쉬운 행과 exact 기술 값을 보존합니다. 모델은 차트 컴포넌트를 선택할 수 없습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-09-06 | implemented | 기존 이력 경로로 사용자 범위의 의미 처리 최종 결과를 복원하고, 답변 없는 질문으로 끝나는 캐시를 모델 재호출 없이 보완했습니다. | `current change`; 집중 Python 검사 162개, Console 검사 81개 및 양 언어 복원 브라우저 검사 2개 통과. 보고된 대화의 저장 결과를 읽기 전용으로 복원해 744자 답변을 반환했고 인증된 세션 브라우저에서 실제 표시를 확인했습니다. | 최종 답변 복원을 수정했습니다. 관측된 작성, 검토, 보강 및 재검증 지연 51.4초는 별도의 최적화 대상입니다. |
| 2026-09-06 | implemented | 기존 회귀 테스트를 직접 응답과 자문 응답의 내부 경로 배지 숨김 및 명시적인 담당 관계 미확인 계약에 맞췄습니다. | `current change`; 표현 및 자문 검사 44개, 외부 공급자 없는 의미 요청 왕복 검사 15개 통과. 통합된 메인 코드에서 합성 대화 진입점 브라우저 검사 10개도 모두 통과했습니다. | 실제 모델 품질, 로컬 기동 및 정확한 커밋의 CI는 별도 근거입니다. |
| 2026-09-06 | implemented | 적응형 출처의 펼침 영역과 복원된 일반 대화의 맥락을 강화했습니다. 이전 로컬 색인에 맥락 모드가 없으면 제목이나 생성 경로가 아니라 명시적인 일반 대화 식별자에서 복원하며, 재개한 요청에 대시보드 사실을 자동으로 추가하지 않습니다. | `current change`; 집중 Console 검사 209개, 타입 검사와 빌드, 격리된 대화 진입점 E2E 시나리오 10개 모두 통과. 두 언어에서 데스크톱을 먼저 검증한 뒤 1440/993/390 화면, 키보드 펼침, 저장 이력 복원 및 화면 맥락 없는 후속 전송을 확인했습니다. | 브라우저 근거는 격리된 합성 검증이며 실제 Browser Entra 또는 모델 검증 증적이 아닙니다. |
| 2026-09-06 | implemented | 통제된 확인 필드를 대체하지 않고 변환 결과 1.6의 조언 응답 표현, 번역된 목표별 근거, 선택한 에이전트 신원 및 재실행 후에도 유지되는 초안 설명을 추가했습니다. | `current change`; 적응형 답변 33개, 세션과 이력 20개, Console 타입 검사와 프로덕션 빌드 통과 | 연결 비평 근거를 완료하고 별도로 승인된 브라우저 런타임 근거를 보존합니다. |
| 2026-09-06 | 구현됨 | 런타임 라우팅이나 어휘 검사기를 변경하지 않고 구조화된 대화 키 복원을 의미 판정이 아닌 검토된 경계로 등록했습니다. | `current change`, `chat-semantic-routing-baseline.json`, 의미 라우팅 검사 10개 통과, 세션 및 탐색 검사 33개 통과, Console 타입 검사 | 게시된 정확한 커밋의 CI 증적은 이 집중 검사와 별개입니다. |
| 2026-09-06 | 구현됨 | 일반 대화 예시 버튼이 초안만 채우는 대신 일반 전송 경로로 바로 질문을 보내도록 변경하고 양 언어 툴팁에 전송 안내를 추가했습니다. | `current change`, `conversation-entry.spec.ts`: 8개 통과, 집중 채팅 및 카탈로그 검사: 48개 통과, Console 타입 검사 | 실제 모델 호출이나 리소스 실행 검증은 요청되지 않았으며 수행하지 않았습니다. |
| 2026-09-06 | 구현됨 | 일반 대화 시작 화면과 명시적 화면 추가 기능을 완성했습니다. 다시 열 때 별도 초안을 보존하고 일반 이력은 화면을 이동하지 않으며 두 전송 경로는 선택한 스냅샷을 사용합니다. 답변 재생성도 화면 없는 요청을 그대로 유지합니다. | `current change`, `conversation-context.test.ts`, `conversation-navigation.test.ts`, `command-deck.session.test.ts`, `conversation-entry.spec.ts`, 집중 단위 검사와 합성 브라우저 검사 | 이 UI 검증에서는 모델 답변이나 리소스 실행을 호출하지 않았습니다. |
| 2026-09-06 | 구현됨 | 일반 Deck과 현재 화면 Deck 진입을 분리하고 경로 스냅샷이 일반 제출에 들어가지 않게 했으며 작업 초안에 로그인 계정과 서버 재검증 경계를 표시했습니다. | `current change`, 집중 Deck, 탐색, 근거 기반 답변, 카탈로그 및 타입 검사 | 두 진입 모드의 인증된 Browser 증적을 보존하기 전에는 배포 검증을 주장하지 않습니다. |
| 2026-09-06 | 구현됨 | 정확한 인시던트 바인딩과 최소한의 요청 메타데이터를 유지하면서 자동 인시던트 바인딩 조사 요청에서 활성 패널 스냅샷을 제외했습니다. | `current change`, `command-deck.tsx`, `use-command-deck-events.ts`, 집중 Console 검사 38개 통과, 인증된 Browser Entra 요청 확인에서 검증된 인시던트 근거 반환 | 이 범위가 제한된 맥락 격리 변경에 남은 작업이 없습니다. |
| 2026-09-05 | 구현됨 | 선제적 웹 담당 업무 인수인계 대화, 리비전 기반 목표 제어, 매핑된 에이전트 후속 라우팅, 관리되는 문서 근거 연결을 추가했습니다. | `current change`; 집중 Operator 및 Console 테스트, Console typecheck, Console build. | 인증된 배포 증적을 보존하고 서버 소유 인시던트 및 승인 작업 중 억제를 추가합니다. |
| 2026-09-05 | 구현됨 | 인수인계 대상 선택을 브라우저 작성 프롬프트 라우팅에서 서버가 검증한 주체, 목표, 세션 바인딩으로 이동하고 근거 검토 전에 권위 있는 문서 승인을 요구했습니다. | `current change`; 집중 Operator, Console, migration inventory 테스트가 통과했습니다. | 인증된 배포 증적을 보존하고 서버 소유 인시던트 및 승인 작업 중 억제를 추가합니다. |
| 2026-09-05 | 구현됨 | 안전한 인시던트 및 승인 작업 중 억제와 접근 시점 문서 근거 노후화 전파를 추가했습니다. | `current change`; 집중 Operator 테스트가 통과했습니다. | 인증된 배포 증적을 보존합니다. |
| 2026-09-05 | 구현됨 | 공통 카탈로그 용어집과 카탈로그 기반 경로 레이블을 게시하여 지식 개요 및 커넥터 스냅샷이 자체 설명 화면 계약을 다시 충족하도록 수정했습니다. | `current change`, `console/src/routes/knowledge-sources.tsx`, 집중 Console 카탈로그 및 화면 계약 검사 47개 통과, 분리된 Console 타입 검사 및 운영 빌드 통과 | 이 범위가 제한된 계약 수정에 남은 구현 작업은 없습니다. |
| 2026-09-03 | 구현됨 | 평가되지 않은 시작 예시를 이중 언어 함수 기반 질문 5개로 교체하고, 신뢰도가 높은 타입 기반 프레임 재사용을 추가하고, 적극적인 T2 복구를 기본적으로 비활성화하고, 완료된 프레임 및 계획 호출을 모델 지연 시간 근거에 포함했습니다. | `current change`, 집중 의미 계획, Azure 어댑터, 런타임 설정, Console 시작 화면, 질문 은행 검사 | 시작 질문 집합 또는 지연 시간 개선을 `검증됨`으로 올리기 전에 인증된 이중 언어 런타임 증적을 새로 보존합니다. |
| 2026-08-31 | 구현됨 | 완료된 측정, 이름이 표시된 미해결 가설, 정확한 공백, `execution_authority=false`가 표시되도록 Console에서 타입 기반 부분 근거 보류 답변을 보존했습니다. 보존에는 정본 최종 본문, 비어 있지 않은 근거, 같은 요청의 일치하는 검증 및 의미 증적이 필요합니다. 증적이 없거나 잘못됐거나 최종 답변이 없거나 공백뿐이면 활성 token pump generation을 무효화하고 내보내기 전에 대기 및 누적 초안을 지운 뒤 단조 증가하는 철회 revision을 보냅니다. | `current change`, 집중 grounded-reply 및 스트림 검사 52개와 Console typecheck 통과 | 정확한 커밋 리비전에서 인증된 데스크톱 및 모바일 타입 기반 보류 증적 하나를 보존합니다. |
| 2026-08-29 | implemented | 강화 라운드 10에서 Console 근거 및 스트림 관점 25개를 검토하고 label에서 파생한 검색 단계 key를 고정된 의미 id로 교체했습니다. SSE 진행 label은 활성 행을 다시 마운트하거나 애니메이션 및 포커스 상태를 초기화하지 않고 갱신됩니다. | `current change`; 집중 retrieval-trace 테스트 및 Console typecheck. | 실제 진행 스트림의 관리되는 시각적 근거를 보존합니다. |
| 2026-08-27 | 구현됨 | 패널에서 파생한 대체 화면 스냅샷과 경로 전환 격리를 추가하여 특화 게시기 실행 전이나 게시기가 없는 경우에도 Command Deck이 등록된 모든 화면을 인식하도록 했습니다. | `current change`, `console/src/app.tsx`, `console/src/deck/context.tsx`, 집중 Console 검사 58개 통과, 예측 학습, 브라우저 근거, 구성 기준선 데스크톱 검사 | 이 범위가 제한된 동작을 `validated`로 승격하기 전에 인증된 배포 근거를 보존합니다. |
| 2026-08-26 | 구현됨 | 최종 결과의 권위를 바꾸지 않고 실시간 의미 조회 노드 진행 상황을 추가했습니다. Executor는 실제 노드 시작과 receipt 완료를 관측하고, Core는 범위가 제한되고 권한이 없는 별도 record를 발행하며, Operator는 `done` 전에 안정된 조회 activity를 스트리밍합니다. 느리거나 실패한 progress 발행은 범위 안에서 끝나며 조회 실행을 바꿀 수 없습니다. Reconnect 및 최종 완료는 기존 영속 receipt를 계속 권위로 사용합니다. | `current change`, 공유 계약 및 schema, Core executor 및 consumer, Operator relay 및 Kafka adapter, 집중 progress 검사 25개 통과, Ruff, formatting 및 strict mypy 통과 | 인증된 Command Deck 실행에서 정확한 AKS 현재 상태 ObjectSet 및 Function 단계가 검증된 최종 답변 전에 running에서 completed로 바뀌는 것을 보존합니다. |
| 2026-08-26 | 구현됨 | 실측 의미 판단 투명성을 타입이 지정된 직접 응답에서 일반 답변, 명확화, 보류 및 지원하지 않음 결과까지 확장했습니다. Core는 범위가 제한되고 권한이 없는 관측을 계획 전체에서 보존하고 processor extension은 이를 조회 근거와 병합하며 Operator는 검증을 바꾸지 않고 최종 event에 포함합니다. 요청과 응답 본문은 명시적으로 활성화한 경우에만 포함합니다. | `current change`, 집중 계획, processor 및 Operator 검사 544개와 strict mypy, Ruff 통과, 인증된 일반 Resource 턴에서 모델 호출 1건, 실측 토큰 5,398개, 범위가 제한되고 민감정보가 제거된 요청 및 응답 내용, 변경되지 않은 권한 없는 근거 상태 표시 | 이 범위가 제한된 투명성 결함에 남은 구현 작업은 없습니다. |
| 2026-08-26 | implemented | 여러 단계를 관측한 조사는 답변이 끝난 뒤에도 펼친 상태로 유지합니다. 기존에는 무엇을 관측했든 조사가 접혔고, 의미 경로는 모든 계획 단계를 최종 시점에만 내보내기 때문에 검증된 조사의 단계별 근거가 답변 뒤에 나타나면서 이미 닫혀 있었습니다. 단일 읽기는 답변이 이미 말하는 내용에 더할 것이 없으므로 그대로 접힙니다. | `current change`, [`investigation-timeline.tsx`](../../../console/src/deck/investigation-timeline.tsx), 집중 타임라인·궤적 표현·작업공간 시각 검사 47개 통과, 인증된 Console 턴이 실행된 조회 노드 2개의 범위·증적·소요 시간을 추가 클릭 없이 렌더함 | 의미 경로는 Core가 여전히 최종 projection 하나만 발행하므로 실행 중 단계별 진행 표시는 미해결로 남습니다. |
| 2026-08-26 | 구현됨 | 모든 의미 명확화를 일반 context 질문으로 교체하는 대신 `semantic_clarification_required`에 포함된 범위가 제한된 서버 작성 질문을 보존했습니다. 잘못된 질문과 다른 검증되지 않은 이유는 기존 지역화 대체 문구를 유지하고 machine reason은 변경하지 않습니다. | `current change`, `grounded-reply.tsx`, 집중 Console 검사 12개 통과 | 수정된 exact-target 질문의 인증 증적을 보존합니다. 이 표현 결함에 남은 추가 구현 작업은 없습니다. |
| 2026-08-26 | 구현됨 | 완료된 출처 세부 정보를 검사 가능하게 만들고 검증되지 않은 대화를 대화형으로 바꿨습니다. `SCREEN` 및 `RECORDS` 배지는 범위가 제한된 60px 라벨을 유지하고, 레코드 출처는 행 수와 브라우저에 표시된 첫 행의 스칼라 값 최대 4개를 보여 주며, 타입이 지정된 검증 실패 이유는 지역화된 명확화 질문으로 표시합니다. 정본 최종 답변과 이유는 대화, 보증 및 실행 기록 경로에 변경 없이 남습니다. | `current change`, 집중 Console 검사 30건과 카탈로그 동등성 검사가 통과했습니다. 인증된 데스크톱 및 390px Browser 검사에서 온전한 배지, 대표 값, 한국어 근거 원본 및 범위 질문, 행·패널·문서 오버플로 0을 확인했습니다. | 이 범위가 제한된 출처 세부 정보 및 명확화 작업에 남은 구현 작업은 없습니다. |
| 2026-08-26 | 구현됨 | 공유된 38px 출처 종류 열 때문에 `PROVENANCE`가 배지 밖에 표시되고 출처 제목을 침범하던 준비 출처 행을 교정했습니다. 이제 Command Deck은 말줄임표가 적용된 64px 범위의 종류 열을 소유하며 보조 기술에는 정확한 출처 종류를 보존합니다. | `current change`, 집중 출처 슬롯 시각 계약, Console 타입 검사, 프로덕션 빌드 및 진입 번들 검사가 통과했습니다. 인증된 데스크톱 및 390px Browser 검사에서 배지와 텍스트의 겹침, 행 오버플로 및 문서 오버플로가 모두 0임을 측정했습니다. | 이 출처 행 회귀에 남은 작업은 없습니다. |
| 2026-08-26 | 구현됨 | 순서가 있는 이벤트나 근거 계약을 바꾸지 않고 브라우저 전용 답변 전환을 부드럽게 했습니다. 관측된 준비 추적은 간결한 대기 높이에서 440ms 동안 확장되고, 토큰 프레임이 없는 정본 최종 답변은 최대 60프레임 동안 화면 프레임마다 범위가 제한된 조각 하나를 공개합니다. 숨겨졌거나 포커스가 없는 탭은 계속 동기적으로 완료되며 모션 감소 설정에서는 즉시 전환합니다. | `current change`, `console/src/deck/stream-paint.ts`, `console/src/deck/use-command-deck-submit.ts`, `console/src/styles.css`, 집중 Console 검사 36건 통과. 인증된 세션에서 기존 70px에서 260px로 이동하는 준비 단계 점프를 재현했고, 숨겨진 탭이 최종 답변을 바꾸지 않은 채 표현 애니메이션을 일시 중지함을 확인했습니다. | 더 넓은 통제된 Browser 보증 산출물에 포커스가 있는 인증된 활성 탭 관찰을 보존합니다. |
| 2026-08-26 | 구현됨 | 직접 응답 정리 source 계약을 공유 typed source helper와 맞췄습니다. 테스트는 계속 일시적 조사 활동 제거를 요구하며 더 이상 폐기된 inline 문자열 비교에 의존하지 않습니다. | `current change`, 집중 Command Deck 이벤트 검사 11개 통과 | 이 회귀 정정에 남은 구현 작업은 없습니다. |
| 2026-08-26 | 구현됨 | 제출과 첫 backend 프레임 사이에 Bragi의 compact 대기 상태를 즉시 표시하도록 추가했습니다. 이 행은 브라우저에만 존재하고 추론한 단계나 근거 주장을 포함하지 않으며, 관측된 진행 상황이 온 뒤에만 기존 상세 trace로 확장되고 최종 답변으로 교체됩니다. 직접 인사는 완료 후 대기, 근거 검색 또는 조사 행을 남기지 않습니다. | `current change`, 집중 Console 시각, 스트림 및 presenter 검사 69개 통과, typecheck 통과, 인증된 Browser 관찰에서 6.6초가 걸린 일반 최종 응답 전에 compact 행을 확인했고 직접 인사 완료 후 대기, 근거 검색, 조사 행이 모두 0개임을 확인했습니다. | 통제된 browser 보증 산출물에 이 상호 작용을 보존합니다. 추가 수명 주기 프레임이나 backend 의도 분류기는 필요하지 않습니다. |
| 2026-08-25 | 구현됨 | Operator의 직접 응답 텍스트 분류기와 모든 추측성 수락 및 계획 이벤트를 제거했습니다. Bridge는 이제 Core 변환 결과를 기다리고 모델이 선택한 직접 응답에는 `done`만 보내며, 검증된 답변 최종 결과에서만 질의 진행 상황을 파생합니다. 따라서 relay가 두 번째 의도 소유자가 되지 않습니다. | `current change`, 집중 직접 응답, 답변, 지연 최종 결과, 재생 및 질의 실행 스트림 검사 8개 통과 | 현재 source 스택을 다시 시작하고 인증된 직접 및 답변 스트림 근거를 보존합니다. |
| 2026-08-25 | 구현됨 | 직접 응답 수명 주기 억제를 인사에서 타입이 지정된 `self_introduction` 의도로 확장했습니다. Operator는 Core와 동일한 공유 전체 발화 분류기를 사용하고, 신원 중심 답변 계획과 실행 권한이 없는 증적을 검증하며, 최종 응답 전에 조사 프레임을 보내지 않습니다. | `current change`, 집중 Operator 표현 및 수명 주기 검사 3개와 Console 엄격 증적 구문 분석 검사 53개 통과 | 로컬 스택을 다시 시작하고 운영자 턴과 직접 답변만 표시되는 인증된 자기소개를 보존합니다. |
| 2026-08-25 | 구현됨 | 정확한 인사에 일시적으로 표시되던 조사 화면을 제거했습니다. Operator가 이미 수락 및 계획 프레임을 보낸 뒤에는 최종 응답 정리가 너무 늦었으며, Console도 `inFlight`만으로 `Preparing answer`를 표시했습니다. 이제 Operator는 공유 정확한 인사 분류 결과에 따라 해당 프레임을 억제하고, Console은 관측된 진행 상황이 있어야 준비 추적을 표시합니다. | `current change`, 집중 Operator 직접 및 일반 수명 주기 검사 3개와 Console 스트림 및 시각 검사 58개 통과 | 로컬 스택을 다시 시작하고 운영자 턴과 직접 답변만 표시되는 인증된 인사를 보존합니다. |
| 2026-08-21 | 구현됨 | v1 브라우저 stream 회귀 검사를 기존 fail-closed binding 계약과 일치시켰습니다. 요청 ID가 일치하지 않거나 sequence가 없으면 거부된 payload를 폐기하고 sequence-gap partial 답변 대신 공유 unavailable 응답을 렌더합니다. | `current change`; `backend-stream-v1-contract.test.ts`; workflow 작성 정정과 함께 집중 Console 계약 검사 31개 통과. | 이 회귀 정정에 남은 작업은 없습니다. |
| 2026-08-13 | 진행 중 | 구현 장부를 도입했으며 이전 출처는 복원하지 않았습니다. 저장된 열린 상태와 새 대화 상태에서 라이브 증적 준비를 안정화했습니다. | 현재 변경의 [`console-routes.spec.ts`](../../../console/tests/live-e2e/console-routes.spec.ts)와 이 문서 쌍, Console 타입 검사 및 대상 Playwright 검색이 통과했습니다. | 인증된 4단계 증적을 확보한 뒤, 런타임 보증을 승격하기 전에 seed가 지정된 이중 언어 보증 산출물을 보존해야 합니다. |
| 2026-08-13 | 구현됨 | 범위가 제한된 의미 명확화를 지원되지 않는 주장이 아니라 필요한 맥락으로 분류했습니다. | `current change`, [`verification-presentation.ts`](../../../console/src/deck/verification-presentation.ts), [`verification-presentation.test.ts`](../../../console/src/deck/verification-presentation.test.ts), 통과한 Console 집중 테스트 12개 | 런타임 검증을 주장하기 전에 아래에 이미 나열된 인증된 4단계 증적을 확보해야 합니다. |
| 2026-08-14 | 구현됨 | 맥락 분류를 제어 평면이 실제로 방출하는 이유 코드로 제한하고, 추측성 리터럴 2개를 실제 방출되는 `operational_case_context_missing`으로 대체했습니다. | `current change`, [`verification-presentation.ts`](../../../console/src/deck/verification-presentation.ts), [`verification-presentation.test.ts`](../../../console/src/deck/verification-presentation.test.ts), 통과한 Console 집중 테스트 13개 | 의미 질의 매니페스트가 인시던트 역량을 노출하지 않아 Console 인시던트 조사 프롬프트는 여전히 명확화로 귀결됩니다. 이 역량 공백은 별도의 설계 검토가 필요합니다. |
| 2026-08-14 | 진행 중 | 인증된 인시던트 턴이 근거에 결속된 증적을 반환했지만 점진적 서버 프레임 없이 fenced JSON을 기본 답변으로 노출한 것을 확인하고 검증된 의미 최종 표현 공백을 기록했습니다. | 구현 범위 표의 현재 출처와 인증된 Browser 관찰, 이 문서 변경에서는 런타임 산출물을 보존하지 않았고 제품 코드도 변경하지 않았습니다. | 아래 의미 표현 작업 패키지를 완료하고 종료 근거를 보존합니다. |
| 2026-08-14 | 구현됨 | 변경할 수 없는 의미 machine 출력과 지역화된 정본 답변을 분리하고, 재생 가능한 관찰 수명 주기 프레임을 추가하고, 증적에 결속된 인시던트 표현과 답변 계획을 compile하고, 정확한 출력을 접힌 실행 상세에 보존하고, 재생과 재생성에서 검증된 인시던트 정체성을 유지했습니다. | 구현 범위 표의 현재 출처와 집중 검사, 보존하지 않은 인증된 Browser Entra 관찰에서 서버가 관찰한 계획 단계의 `Preparing answer`, 검증된 감사 기록 3건, 명시된 인과 및 근거 제한, 읽기 전용 근거 수집 다음 단계, 접힌 exact JSON, 재생성 뒤 동일한 검증 결과를 확인했습니다. | 채널 전체 런타임 검증을 주장하기 전에 통제된 인증 산출물을 보존하고, 한국어 동등 실행을 수행하고, Teams 및 Slack 집약 증적을 기록합니다. |
| 2026-08-14 | 구현됨 | 정본 top-level locale을 전달하고, 재생성 history를 원래 질문 경계로 제한하고, 검증된 의미 요청 신원을 한 번 재생하고, 해당 신원을 Operator 멱등성에 결속하고, 반복되는 Azure throttling 또는 schema-invalid 후보를 범위 안에서 재시도하도록 했습니다. | `current change`, Console stream, normalizer, session 및 event 집중 검사 128개와 Azure 의미 계획 adapter 검사 5개가 통과했고 Console 타입 검사와 작업 범위 Ruff가 통과했습니다. 보존된 인증 한국어 Browser working-tree 실행은 두 턴 모두 `request_identity_replayed=true`이고 Core 계획 수명 주기 5단계가 정확히 한 번인 상태로 통과했습니다. | 이 변경을 커밋하고 중앙 검증한 뒤 exact-source 인증 Browser 산출물을 보존합니다. Teams 및 Slack 집약 증적은 열린 상태로 유지합니다. |
| 2026-08-14 | 구현됨 | Submit 시점에 원래 view snapshot을 deep clone해 route refresh가 검증된 요청 재생에 결속된 내용을 변경하지 못하게 했습니다. | `current change`, Console session 집중 검사 16개와 Console 타입 검사가 통과했고 request snapshot mutation 회귀에서 중첩된 fact 및 record 값이 보존됐습니다. | Provider capacity가 오염시키지 않는 첫 턴을 허용할 때 post-validation 인증 Browser 산출물을 보존합니다. |
| 2026-08-14 | 검증됨 | 구현 커밋의 중앙 검증 뒤 인증된 한국어 의미 표현 및 재생성 산출물을 보존했습니다. | Source revision `7f2b740b1` 및 `244d003ef`에 중앙 receipt가 있습니다. 보존된 post-validation 산출물은 `passed=true`, 보호된 요청 2개, 진행 단계 5개, 표현 slot 3개, 일치하는 요청·바인딩·기술 출력 digest, 읽기 전용 권한, Core 계획 수명 주기 5단계 1회를 기록합니다. | Teams 및 Slack 집약 receipt, 별도 4단계 receipt, 이중 언어 100-case 집단은 열린 상태로 유지합니다. |
| 2026-08-14 | 구현됨 | 채널 중립적 최종 집약기에 명시적인 Teams 및 Slack 동등성 검사를 추가했습니다. | `current change`, [`test_rich_contract.py`](../../../services/core-control-plane/tests/delivery/channels/test_rich_contract.py)의 집중 검사 36개가 통과했고 두 채널 종류에서 정본 내용, 제한, 근거 참조, 실행 권한 없음, 최종 확정 갱신을 보존했습니다. | 통제된 Teams 및 Slack 런타임 증적을 보존하기 전에 운영 A3 게시자를 구현하고 실행합니다. |
| 2026-08-14 | 진행 중 | answered 턴이 0건인 100-case 집단을 운영 준비 상태로 분류하던 무작위 보증 오탐을 해소했습니다. | `current change`, [`ontology-query-assurance.test.ts`](../../../console/tests/live-e2e/ontology-query-assurance.test.ts)의 집중 검사 40개가 통과했으며 답변 0건과 불완전한 근거를 거부하는 사례를 포함합니다. | 릴리스 준비 상태를 변경하기 전에 근거에 결속된 answered 턴이 1건 이상인 새 인증 100-case 산출물을 보존합니다. |
| 2026-08-14 | 진행 중 | 한 언어에만 답변이 있는 집합을 이중 언어 운영 준비 상태로 인정하지 않도록 무작위 릴리스 게이트를 강화했습니다. | `current change`, [`ontology-query-assurance.test.ts`](../../../console/tests/live-e2e/ontology-query-assurance.test.ts)의 집중 검사 41개가 통과했으며 언어 누락 거부 사례를 포함합니다. | 릴리스 준비 상태를 변경하기 전에 두 언어 모두에서 근거가 완전한 answered 턴이 있는 새 인증 100-case 산출물을 보존합니다. |
| 2026-08-14 | 구현됨 | 점진적 재렌더링 중 번역된 중첩 요약을 클릭하는 대신 최종 의미 요청에 4단계 증적 disclosure를 결속했습니다. | `current change`, focused Playwright 검색이 통과했습니다. 전체 Console 타입 검사는 이 변경 밖의 동시 incident 경로 working-tree 오류로 계속 차단됐습니다. | 선택자 수정을 커밋하고 중앙 검증한 뒤 인증된 4단계 통과 산출물을 보존합니다. |
| 2026-08-14 | 구현됨 | 4단계 실행기를 최종 요청과 변환 결과의 정체성 모두에 결속하고, 애플리케이션이 reader를 닫은 뒤 transport EOF를 기다리는 대신 처음 완결된 `done` 프레임에서 복제된 SSE 근거 수집을 멈추도록 강화했습니다. | `current change`, 정확한 Playwright 검색과 focused esbuild compile이 통과했습니다. 인증 probe는 최종 수집까지 진행됐지만 런타임 재기동과 의미 planner 사용 불가 때문에 통과 산출물을 보존하지 않았습니다. | 현재 로컬 Core와 Operator 프로세스가 범위가 제한된 요청 동안 준비 상태를 유지한 뒤 안정된 인증 4단계 산출물을 보존합니다. |
| 2026-08-14 | 구현됨 | 최종 의미 증적이 `answered`가 아니면 답변 전용 UI 단언이 보류 원인을 가리기 전에 4단계 실행기를 즉시 중단하도록 했습니다. | `current change`, [`console-routes.spec.ts`](../../../console/tests/live-e2e/console-routes.spec.ts), 정확한 Playwright 검색과 focused esbuild compile이 통과했습니다. 진단은 처리 결과, 사용 불가 이유, 요청 식별자, 변환 결과 식별자, 의미 경로를 포함합니다. | 안정된 출처에서 인증된 4단계 경로를 다시 실행하고, 통과했으며 출처가 결속된 산출물만 보존합니다. |
| 2026-08-14 | 진행 중 | 안정된 출처에서 인증된 4단계 경로를 다시 실행하고, typed hold가 답변 전용 단언 전에 중단되는 것을 확인했습니다. | 중앙 검증된 source revision `48b5d12bd6d2610a09acd756447e5108384cecd6`과 안정된 workspace patch digest `sha256:e509b6af05032a4875084e0978b2914c37bf2000a7ffafcfa58a8a0e50fd34d6`, 실행기는 `disposition=held`와 `unavailable_reason=semantic_planner_unavailable`을 보고했습니다. Core plan 후보는 HTTP 429 응답 뒤 범위가 제한된 재시도를 소진했습니다. 실패 산출물은 보존하지 않았습니다. | 의미 계획 모델 용량을 복구한 뒤 두 계약을 완화하지 않고 4단계 경로와 이중 언어 답변 coverage 14칸 게이트를 다시 실행합니다. |
| 2026-08-14 | 구현됨 | 명시적 Operator API 원본이 없으면 외부 4단계 근거 실행이 즉시 실패하게 하고, 성공 경로 질문을 전체 조회 가능 유형 집합으로 좁히며, 산출물에 출처, 작업 영역 패치, 정본 실행 구성의 출처 정보를 포함했습니다. | `current change`, [`console-routes.spec.ts`](../../../console/tests/live-e2e/console-routes.spec.ts), 정확한 Playwright 검색, 집중 보증 및 출처 검사 52개, Console 타입 검사가 통과했습니다. | 중앙 검증을 확보한 뒤 인증된 통과 산출물을 보존해야 범위 상태를 `검증됨`으로 변경할 수 있습니다. |
| 2026-08-15 | 구현됨 | 표현 산출물이 답변 내용을 제거하지 못하게 했습니다. 일반 검증 조회 산출물은 출력 노드 개수만 보이는 대신 반환된 행과 노드별 결과를 투영하며, 산출물이 개요 요약 외에 아무것도 담지 않으면 답변은 Markdown을 그대로 유지합니다. | `current change`, [`presentation-artifact.ts`](../../../console/src/deck/presentation-artifact.ts) 및 [`grounded-reply.tsx`](../../../console/src/deck/grounded-reply.tsx), focused Console deck 검사 76개, Console 타입 검사, Operator bridge 검사 48개 통과 | 인증된 로컬 Console에서 렌더링 결과를 확인합니다. |
| 2026-08-15 | 구현됨 | 무작위 보증의 각 실행과 질문을 고유한 backend session identity에 결속해 새 실행이 이전 실행의 영속 projection을 소비하지 못하게 하고 checkpoint 재개에서는 같은 정체성을 유지했습니다. | `current change`, [`ontology-query-assurance.ts`](../../../console/tests/live-e2e/ontology-query-assurance.ts), [`ontology-query-assurance.spec.ts`](../../../console/tests/live-e2e/ontology-query-assurance.spec.ts), [`ontology-query-assurance.test.ts`](../../../console/tests/live-e2e/ontology-query-assurance.test.ts), 집중 보증 테스트 49개와 Console 타입 검사 통과, 정확한 실제 운영 Playwright 테스트 검색 완료 | 새 exact-source 14-cell 산출물을 보존한 뒤 seed가 지정된 이중 언어 100-case 집단을 실행하고 보존합니다. |
| 2026-08-15 | 구현됨 | 자동 인시던트 프롬프트를 시스템이 답할 수 있는 범위에 맞추고 브리핑의 관사 일치 오류를 고쳤습니다. 프롬프트는 원인을 요구했지만 인시던트 답변은 인과 분석을 사용 불가로 고정하고 있어 모든 자동 조사가 답할 수 없는 질문을 던졌습니다. 이제 근거로 확인되는 사실, 빠진 근거, 다음 안전한 읽기 전용 조치를 묻습니다. 브리핑은 severity가 unknown일 때 `a unknown`으로 렌더링되었습니다. | `current change`, focused Console 인시던트 주의 및 카탈로그 검사 8개 통과, 카탈로그 parity 16쌍 검증, Console 타입 검사 통과 | 인증된 로컬 Console에서 재작성된 자동 프롬프트를 확인합니다. |
| 2026-08-15 | 구현됨 | 앞선 보증 장부 문구가 구현 파일보다 먼저 `6bb17dffe9f2`에 반영되어 있던 근거 경계를 정정했습니다. 실행 범위 session identity 구현은 이 이력 정정과 함께 반영됩니다. | `current change`, 위에 인용된 온톨로지 보증 경로 3개, 집중 보증 테스트 49개와 Console 타입 검사 통과, 정확한 실제 운영 Playwright 테스트 검색 완료 | 새 exact-source 14-cell 산출물을 보존한 뒤 seed가 지정된 이중 언어 100-case 집단을 실행하고 보존합니다. |
| 2026-08-16 | 구현됨 | Source가 유휴 상태일 때도 Operator 대화 SSE가 애플리케이션 종료를 관측하게 하고, 호출자 취소 시 source를 닫기 전에 내부 wait task 둘을 모두 취소하고 기다리도록 강화했습니다. 따라서 클라이언트 연결 해제 뒤 분리된 `anext` task가 `aclose`와 경합하지 않습니다. | `current change`, `shutdown.py`, `factory.py`, `test_stream_shutdown.py`, focused 스트림, 대화 family 및 표현 검사 25개 통과, Ruff 및 strict mypy 통과 | 대화 스트림 종료 정리에 남은 구현 작업은 없습니다. |
| 2026-08-17 | implemented | 인시던트 후보 선택기가 답변이 충족할 수 없는 프롬프트를 제출하던 동작을 중단했습니다. 후보를 선택하면 주의 배지와 동일한 인시던트 고정 대화가 열리는데도 근본 원인을 요구했고, 그 답변은 항상 인과 분석이 구현되지 않았다고 보고합니다. 이제 두 진입점 모두 근거로 확인되는 사실, 누락된 근거, 다음 안전한 읽기 전용 조치를 요청합니다. | `current change`; `messages.{en,ko}.json`; focused 테스트가 두 프롬프트 키를 두 로케일에서 고정합니다. Console i18n과 grounded-reply 검사 17건과 typecheck가 통과했고, 원인 표현을 되돌리면 해당 테스트가 실패합니다. | 인시던트 프롬프트 계약에 남은 작업은 없습니다. |
| 2026-08-17 | implemented | 카탈로그와 두 진입점이 근거 범위가 정해진 프롬프트를 채택한 뒤에도 폐기된 근본 원인 질문을 기대하던 인시던트 후보 회귀 테스트를 교정했습니다. | `current change`; `incident-candidates.test.ts`; 후보 선택 집중 테스트 4건이 통과했습니다. | 이 회귀 교정에 남은 작업은 없습니다. |
| 2026-08-17 | implemented | 기록된 활동 타임라인이 생기기 전에 제공되던 블록 3개를 그대로 고정하고 있던 인증된 인시던트 표현 게이트를 바로잡았습니다. 이제 동일한 종료 응답이 담고 있는 상관 근거에서 기대 블록을 도출하므로, 타임라인이 사라지면 실패하고 행을 반환하지 않은 인시던트 읽기는 그대로 통과합니다. | `current change`; `console/tests/live-e2e/semantic-answer-presentation.spec.ts`; 오늘 관측한 라이브 Console 답변은 `overview`, `records`, `limitations`, `findings`를 렌더링합니다. Console typecheck가 통과했습니다. | 인증된 외부 스택에서 게이트를 실행합니다. |
| 2026-08-18 | implemented | 검증된 목록 답변을 한눈에 읽을 수 있게 했습니다. 완전한 범주형 결과는 제한된 막대 분포를 그리고, 잘린 결과는 검증된 전체 중 몇 건을 표시했고 나머지가 어디에 있는지 밝히며, 이름 있는 읽기 쉬운 필드가 불투명한 식별자보다 앞에 오고, 요약 격자는 항목 수에 맞춰져 값 하나 옆에 빈 칸을 남기지 않습니다. 불완전하거나 상한에 걸린 결과는 차트를 그리지 않으므로 부분 집계가 전체처럼 읽히지 않습니다. | `current change`, [Issue #184](https://github.com/dotnetpower/fdai/issues/184), `semantic_turn_presentation.py`, `console/src/deck/structured-reply.css`, focused Operator 검사 394개 통과(차트 회귀 2건 신규), Console typecheck와 Ruff 및 strict mypy 통과 | 차트와 행 상한 안내에 대한 통제된 request-to-Console 및 이중 언어 무작위 근거를 보존합니다. |
| 2026-08-18 | implemented | 의미 turn이 관측한 단계를 주소 지정 가능한 step으로 발행했습니다. Console은 이미 `activity` 이벤트로 관측 과정 타임라인을 그리지만 의미 turn은 `status`와 `verification`만 발행해 턴 내내 한 줄이 고정돼 있었습니다. 이제 관측된 각 단계가 제한된 step을 함께 발행하고, 대기 step은 종단 projection이 생길 때까지 running으로 보고되며 disposition과 무관하게 종단 이벤트 전에 정리됩니다. 관측하지 않은 시각은 합성하지 않으며 replay 이벤트 id는 그대로입니다. | `current change`, [Issue #187](https://github.com/dotnetpower/fdai/issues/187), `semantic_turn_runtime.py`, focused Operator 검사 394개 통과(수명 주기, held, 지연 종단, 재개 회귀 갱신), Ruff 및 strict mypy 통과, 실제 turn이 running 대기 step과 완료 step 5개로 타임라인 표시 | Core는 여전히 종단 projection 하나만 발행하므로 계획 하위 단계는 스트림이 관측하지 못합니다. |
| 2026-08-18 | implemented | 근거 step에 명령 상세를 부여했습니다. Console은 이미 step별 도구 배지, 읽기 전용 라벨, 복사 가능한 명령 블록, 접히는 출력을 렌더링하지만 의미 step이 실행 기록을 담지 않아 모든 step이 라벨뿐이었습니다. 이제 근거 step이 동일한 종단 projection이 이미 담고 있는 검증된 쿼리와 행 수를 함께 전달하며, 실행한 것이 없는 step은 기록을 담지 않고, goal이 둘 이상인 plan은 하나를 실행된 쿼리로 지목하지 않고 명령을 보고하지 않습니다. | `current change`, [Issue #188](https://github.com/dotnetpower/fdai/issues/188), `semantic_turn_runtime.py`, focused Operator 검사 396개 통과(실행 기록 회귀 2건 신규), Ruff 및 strict mypy 통과, 실제 turn이 ObjectSet 정의와 `returned_rows`/`total_rows`를 JSON 코드 블록으로 표시 | step은 아직 소요 시간을 보고하지 않으므로 실행 기록에 관측 구간이 없습니다. |
| 2026-08-19 | 진행 중 | 비평 후 결정론적 교차 채널 표현 설계를 승인했습니다. 수정안은 v1 재생을 그대로 유지하고 v2를 추가하며 근거 분석과 배치 계획을 분리하고 모델이나 브라우저의 서술 추측이 컴포넌트를 선택하지 못하게 합니다. | `current change`, 이 소유 문서 쌍 | 범위 상태를 바꾸기 전에 분석기, 플래너, v2 컴파일러, 호환성 검사 및 교차 채널 동등성 테스트를 구현합니다. |
| 2026-08-19 | 구현됨 | 순수 근거 형태 분석기, 결정론적 결정 행렬, 검증된 frame 메타데이터 변환 결과 및 추가적인 v2 컴파일러를 구현했습니다. 알 수 없는 타입 맥락, 누락값, 혼합 단위, 불명확한 분모, 낮은 항목 수, 잘림 및 불완전한 검증은 0을 만들지 않고 exact 레코드, 제한 사항 또는 정본 텍스트로 대체됩니다. | `current change`, [이슈 #234](https://github.com/dotnetpower/fdai/issues/234), 집중 planner, compiler 및 producer/Console 계약 검사 33개와 Ruff, formatting, strict mypy 통과 | 순수 Teams, Slack 및 주입형 사용자 지정 기능 렌더러를 구현하고 검증합니다. |
| 2026-08-20 | 구현됨 | Legacy와 v2 경로가 읽기 쉬운 행 projection 하나를 재사용하고 실제 두 단계 Resource property shape를 처리하도록 확장했습니다. Artifact는 불투명한 identity와 기술 세부의 변경하지 않은 근거 행을 보존하면서 이름, 타입, 위치를 앞세우며 중첩 tag와 provider payload는 표시 열이 되지 않습니다. | `current change`, [이슈 #241](https://github.com/dotnetpower/fdai/issues/241), focused v2 compiler, planner 및 의미 bridge 검사 94개 통과, Ruff, formatting, strict mypy 통과 | Operator 재시작 뒤 인증된 desktop, constrained-desktop, mobile 근거를 보존합니다. |
| 2026-08-20 | 구현됨 | 인증된 검토에서 뒤에 표시되는 `id`와 `object_type` 열이 유용한 계층을 계속 평평하게 만드는 것을 확인한 뒤 앞선 읽기 쉬운 행 정책을 교정했습니다. 이제 읽기 쉬운 표는 해당 열 없이 운영자용 사실을 표시하고 identity만 있는 결과는 대체 표시를 유지하며 변경하지 않은 exact 행은 기술 세부에서 계속 확인할 수 있습니다. | `current change`, `presentation_rows.py`, focused Operator 표현 검사 82개와 Command Deck 시각 검사 19개, Console typecheck 및 운영 build 통과 | 이 source로 Operator API를 재시작한 뒤 인증된 desktop, constrained-desktop, mobile 근거를 보존합니다. |
| 2026-08-21 | 구현됨 | 결정론적 표현 계획을 넓은 블록 선택에서 온톨로지에 근거한 시각화 선택 10개로 확장했습니다. 엄격한 v2 artifact는 추가적인 hint 또는 타입이 지정된 scatter와 heatmap 블록을 전달합니다. Console은 공유 차트 primitive를 렌더링하고 Slack과 Teams는 exact 사실로 축약합니다. 종류에 맞지 않는 hint는 fail closed하며 이전 v2 artifact는 새 필드를 합성하지 않고 round-trip합니다. | `current change`, planner 및 compiler 검사 67개, Console artifact 및 registry 검사 28개, 채널 renderer 검사 5개, Console typecheck 통과 | 이 기능을 `검증됨`으로 올리기 전에 인증된 Web 및 통제된 Slack/Teams 런타임 증적을 보존합니다. |
| 2026-08-22 | 구현됨 | Renderer-neutral semantic metadata를 Core 종단 producer에 연결하고 전체 선택 경계를 강화했습니다. 명시적 비교 역할은 generic temporal 필드보다 우선합니다. Semantic field-role map은 shape별 exact 집합을 따릅니다. Ranking, part-to-whole, cumulative, matrix variant는 행 수준 증명을 요구합니다. 중복 matrix 좌표와 감소하는 cumulative 값은 의미를 만들지 않고 대체 경로로 이동합니다. | `current change`, 집중 Core projector/wiring 및 Operator planner/compiler 검사 90개, Console parser/registry/primitive 검사 45개, 채널 축약 검사 13개, Ruff 및 Console typecheck 통과 | 이 기능을 `검증됨`으로 올리기 전에 인증된 Web 및 통제된 Slack/Teams 런타임 증적을 보존합니다. |
| 2026-08-22 | 구현됨 | 48개가 넘는 check로 독립적인 적대적 검토 3회를 완료하고 확인된 Medium 이상 잔여가 없을 때까지 집중 hardening을 반복했습니다. 수락한 수정은 상한을 넘는 근거 참조와 exact cell을 fail closed하고, 의미 label과 공유 RFC 3339 순서를 요구하며, chart 값, tone, role, 참조, table, text bound, slot, envelope type, item schema, v1 integer, control character에 대해 Web과 Slack/Teams 계약을 일치시킵니다. 범위가 제한된 읽기 쉬운 6-column table, 유효한 음수 comparison/scatter 도메인, sparse heatmap placeholder는 다시 검토하고 유지했습니다. | `current change`, 집중 semantic presentation 검사 137개, Console deck 검사 693개, desktop/mobile chart Playwright 검사 4개, Ruff, strict mypy, Console typecheck 및 production build 통과 | Low 표시 tradeoff만 남습니다. Sparse heatmap 공백은 명시적인 `-`를 사용하며 일부 안전한 chart fallback은 generic reason을 사용합니다. Exact 기술 행은 계속 확인할 수 있습니다. `검증됨`으로 올리려면 통제된 Web 및 Slack/Teams 런타임 증적이 여전히 필요합니다. |

### 남은 작업

- [ ] 인증된 Command Deck 증적에서 정확한 AKS 현재 상태 ObjectSet 및 Function activity가
  권위 있는 최종 답변 전에 running 및 completed로 바뀌는 것을 보존합니다.
- [ ] 인증된 요청부터 Console까지 이어지는 4단계 온톨로지 통과 증적을 새 저장소 경로에
  보존합니다.
- [ ] 2026-08-11 기준선을 교체하지 않고, 두 언어 모두에서 근거가 완전한 answered 턴이 있는
  seed `0x0fda1`의 영어/한국어 100-case 무작위 보증 통과 산출물을 보존합니다.
- [ ] 채널 전체 런타임 검증을 주장하기 전에 통제된 Teams 및 Slack 집약 증적을 기록합니다.
- [x] 독립적인 시각화 비평을 20개 이상 완료하고 확인된 Medium 이상 잔여가 없을 때까지 집중
  hardening을 반복합니다. 현재 근거는 check 48개, 집중 Python 검사 137개, Console deck 검사
  693개, desktop/mobile browser 검사 4개입니다.
- [x] v1 재생, 차트 대체 경로, 잘못되거나 증적에 결속되지 않은 산출물 거부를 포함하는
  결정론적 근거 형태 분석기와 v2 플래너 결정 행렬을 구현하고 집중 테스트합니다.
- [x] 정확한 machine payload와 최종 검증 증적은 접힌 기술 상세에 보존하면서 primary semantic
  답변의 fenced machine JSON을 지역화되고 결정론적인 운영자 대상 내용으로 교체합니다.
- [x] 상세 `Preparing answer` 내용이 `done` 전에 관찰된 수락, 계획, 근거, 검증 및 표현 작업을
  반영하도록 단조 증가하는 의미 수명 주기 프레임을 내보내고 재생합니다. 첫 프레임 전에는 영속
  기록에 남지 않는 compact 대기 행만 표시하며, 타입이 지정된 정확한 직접 응답은 수명 주기 프레임을
  생략하고 완료 후 진행 행을 남기지 않습니다.
- [x] 완료된 의미 표현 및 재생성 경로의 통제된 인증 Browser 산출물을 보존한 뒤 한국어 동등
  실행을 수행하고 보존합니다.

## Command Deck 작업 영역 수명 주기

좌측 메뉴는 기본적으로 전체 작업 영역에 일반 대화를 엽니다. 빈 화면에는 "무엇을 도와드릴까요?",
입력창 하나, 클릭하거나 키보드로 실행하면 질문을 바로 보내는 작은 예시 버튼 세 개를 표시합니다.
툴팁은 전송할 질문과 즉시 전송 동작을 안내합니다. 예시 질문도 선택한 맥락을 반영하는 일반 전송
경로를 사용하며 첨부와 중복 전송 검사를 그대로 거칩니다.
하단 버튼과 `Ctrl+K` 또는 `/`는 현재 화면의 별도 대화를 우측 패널에 엽니다.
각 진입점은 배치 선택을 따로 기억합니다. 일반 대화는 현재 화면의 근거를 자동으로 포함하지 않습니다.
"현재 화면 추가"를 선택하면 스냅샷을 저장하고 제거 가능한 "참고 화면" 칩으로 표시합니다.
화면을 제거하면 이후 질문에만 적용되며 이미 보낸 메시지는 유지합니다.

일반 대화를 다시 열면 현재 탭의 일반 대화와 작성 중인 입력을 복원합니다. "새 대화"는 사용자별
일반 대화 키를 새로 만들며, 이력 선택은 명시적으로 수행하고 에이전트와 인시던트의 연결은 유지합니다.
두 진입점을 오갈 때 초안, 이력, 선택한 화면 맥락을 각각 보존합니다. 다른 메뉴로 이동해도 열린
플로팅 대화의 참고 화면은 바뀌지 않습니다. 일반 대화 이력을 선택해도 생성 당시 화면으로 이동하지
않습니다. 질문을 보내면 입력창은 대화 하단으로 이동합니다. 헤더는 대화와 참고 맥락을 구분하며
검색과 이력을 간결하게 표시합니다. 화면 맥락은 힌트일 뿐이며 근거, 권한, 실행 검증은 서버가 담당합니다.

대화 이력은 운영자의 질문이 아니라 구조화된 대화 식별자와 메타데이터에서 진입 모드를 복원합니다.
사용자 및 경로 정규화와 네임스페이스 해석은 의미 라우팅 기준 목록의 검토된 `retain` 경계입니다.
질문은 표시 제목에만 사용합니다. 실행을 요청하는 문구나 네임스페이스 문자열이 있어도 에이전트,
인시던트 연결 또는 대화 모드를 선택하지 않습니다.

## 의미 최종 표현 계획

`advisory_response`는 소셜 `direct_response` 및 검증된 운영 `answered`와 구분하여 변환 결과
`1.6.0`으로 전달합니다. Console은 전체 답변의 증적을 만들지 않고 정본 답변과 목표별 일반 지식,
검증된 예시, 사용 불가 표시를 렌더링합니다. 선택적 예시 실패가 설명을 원본 실패 답변으로 대체하지
않습니다. 검토된 설명은 기존 `action_draft`에도 첨부할 수 있으며 정본 초안과 전달된 확인 필드는
유지합니다. 스트림, JSON, 로컬 캐시, 영속 복원은 동일한 적응형 메타데이터를 보존합니다.
설명 문구에서 새로운 확인 권한이나 실행 권한을 추론하지 않습니다.
제한 사유는 원시 진단 코드를 주요 레이블로 표시하는 대신 번역된 펼침 영역에 넣습니다.
이전 로컬 색인에 명시적인 모드 필드가 없어도 복원된 일반 대화는 일반 맥락을 유지하며,
제목이나 생성 경로만으로 화면 근거를 추가하지 않습니다.

타입이 지정된 `direct_response`는 검증된 조회 답변과 구분합니다. 하나의 닫힌 답변 의도,
의미 판단 모델이 작성하고 범위와 언어가 제한된 텍스트, `execution_authority=false`를 전달하지만 조회 계획, 근거 참조, 검증 배지,
표현 산출물 또는 실행 궤적은 포함하지 않습니다. Web, Teams 및 Slack은 운영 주장이 없는 동일한
검증된 최종 응답을 보존합니다. Core는 성공한 직접 응답을 고정 인사 또는 자기소개 템플릿으로
대체하지 않습니다.

구조화된 산출물에 개요 이외의 콘텐츠가 있으면 Console은 정본 검증 자연어 답변을 먼저 표시하고
그 아래에 표, 차트, 타임라인 또는 다른 컴포넌트를 표시합니다. 클라이언트는 요약을 다시 만들거나
재해석하지 않습니다. 따라서 검증, 범위, 잘림 및 한계 설명은 다른 채널에서 사용하는 정본 답변과
동일하게 유지됩니다.

### 증적에 결속된 답변 권한

Core는 서버가 소유한 함수 레지스트리가 실행 증적을 발행할 때 답변 권한을 할당합니다.
증적은 권한과 근거 참조를 하나의 변경할 수 없는 목표 결과에 함께 보관합니다. 출처 등급은
다음과 같이 구분합니다.

- `server_subscription_health`: 구독 Service Health 및 Resource Health 읽기
- `server_inventory_graph`: 보안이 적용된 인벤토리 및 현재 상태 그래프 읽기
- `server_metering`: 측정된 LLM 사용량 읽기
- `server_ontology_manifest`: 정확한 principal 범위 온톨로지 매니페스트 읽기

Operator는 완료된 목표 증적의 참조가 터미널 의미 근거를 정확히 포함할 때만
`verification.authority`를 도출합니다. 모델, 프롬프트, 클라이언트 컨텍스트, 의미 답변 및 기술
표현 메타데이터의 권한 텍스트는 무시합니다. 권한이 없으면
`semantic_evidence_authority_missing`과 함께 `unverified`가 됩니다. 권한이 여러 개면
`semantic_evidence_authority_conflict`와 함께 `unverified`가 되고 턴을 보류합니다. 의도 그래프
근거 v2는 권한을 가산 방식으로 전달합니다. v1 재생은 계속 읽을 수 있지만 검증된 권한을
입증할 수 없습니다.

현재 의미 경로는 조회 실행과 검증을 입증하지만 운영자 대상 표현 전에 멈춥니다. Core는 검증된
출력을 fenced JSON으로 직렬화하고, Operator는 `done` 이벤트 하나를 재생하며, 최종 payload에
`answer_plan`, `presentation_artifact`, `trajectory_detail`이 없으므로 Console은 설계대로 해당
정본 텍스트를 fallback으로 표시합니다. 기존 `Preparing answer` 컴포넌트는 일시적인 브라우저
상태입니다. Compact 행은 관측되지 않은 단계를 이름 붙이지 않고 제출과 첫 server 프레임 사이를
채웁니다. 상세 trace는 관측된 진행 프레임 뒤에만 표시되므로 완료된 replay에서 수행 작업을 설명하는
근거는 계속 server 수명 주기 event에 의존합니다. 해당 프레임이 도착하면 브라우저는 전체 패널을 한
번에 삽입하지 않고 간결한 행의 높이에서 상세 추적을 확장합니다. 토큰 프레임이 없는 최종 응답은
정확한 정본 텍스트를 최대 60개의 화면 프레임에 걸쳐 공개합니다. 백그라운드 탭은 동기적으로
완료되며 모션 감소 설정에서는 두 전환을 모두 생략합니다.

Machine 결과는 계속 권위 있고 재생 가능하지만 primary 사람 답변은 아닙니다. 다음 다섯 작업
패키지로 수정합니다.

| 작업 패키지 | 필요한 변경 | 종료 근거 |
|-------------|-------------|-----------|
| Machine과 표현 분리 | 정확한 의미 출력과 digest는 타입이 지정된 기술 데이터로 유지합니다. 검증된 서버 소유 slot에서 지역화된 정본 Markdown 답변을 compile합니다. 모델에 값이나 근거 참조를 다시 쓰게 하지 않습니다. | 계약 테스트는 사람 답변에 불변 결과에 있는 값만 포함됨을 입증하고, 기술 상세는 exact machine payload와 증적을 round-trip합니다. |
| 정직한 진행 상황 | accepted, planning, evidence execution, verification, presentation 단계에 추가적이고 단조 증가하는 수명 주기 프레임을 내보냅니다. Core가 단계를 게시하기 전에는 Operator가 로컬에서 관찰한 수락 또는 대기 상태만 보고할 수 있습니다. 작업을 다시 실행하지 않고 reconnect 재생이 가능하도록 충분한 순서 상태를 보존합니다. | 스트림 테스트는 순서가 있는 status 프레임이 `done`보다 먼저 오고, reconnect가 단계를 중복하지 않으며, 취소가 최종 상태로 유지되고, 관찰하지 않은 단계를 만들지 않음을 입증합니다. |
| 인시던트 서술 | 검증된 사실, 인과 상태, 근거 공백 및 다음 안전 단계를 구분해 렌더링합니다. 인과 계약이 없으면 root cause를 사용할 수 없다고 표시합니다. 누락된 impact 또는 citation 근거는 계속 명시합니다. 기본 다음 단계는 근거 수집이며, 운영자가 초안 생성을 명시적으로 요청한 경우에만 action draft를 표시합니다. | 영어/한국어 fixture는 `rca.hypothesis` 기록에서 원인을 추론하지 않고 모든 공백을 표시하며 `execution_authority=false`가 바뀌지 않음을 입증합니다. |
| Console 및 채널 집약 | `presentation_artifact` v1을 통해 검증된 요약, 제한, 근거 링크 및 선택적 표 block을 렌더링합니다. Raw JSON과 digest는 접힌 기술 상세에 둡니다. Web, Teams, Slack은 같은 정본 내용을 사용하고 지원하지 않는 artifact는 raw JSON이 아닌 읽기 쉬운 Markdown으로 fallback합니다. | Console parser와 renderer 테스트는 알 수 없거나 증적에 결속되지 않은 block을 거부합니다. 채널 테스트는 vendor 한계를 적용하면서 같은 사실, 제한 및 권한을 보존합니다. |
| 인증된 보증 | Focused 계약 테스트가 통과한 뒤 새로운 바인딩된 인시던트 턴, 영속 재생, reconnect 및 한국어 동등 질문을 실행합니다. | 통제된 Browser 산출물은 최종 완료 전에 `Preparing answer`가 표시되고, primary fenced JSON이 없는 읽기 쉬운 검증 답변, 접힌 기술 상세, 명시적 근거 공백, 만들어 내지 않은 원인 및 재생 뒤 동일한 답변을 보여 줍니다. |

현재 관찰된 인시던트 형태에서 계약에 맞는 최종 답변은 상관관계가 있는 감사 기록 3건이
검증됐고 인과 분석은 사용할 수 없으며 impact와 grounded citation 근거가 누락됐고 변경을
제안하기 전에 누락된 근거 유형을 수집하는 것이 다음 안전 단계임을 설명하는 것이 좋습니다.
정확한 식별자, 시각, 기록 및 digest는 대화를 이끄는 대신 기술 근거로 확인할 수 있게 유지합니다.

## 여러 원본을 사용하는 응답 표시

Service Health 응답은 결정론적으로 계산한 `yes`, `no`, `partial`, `unknown` 결론을 먼저
표시합니다. 이벤트 타임라인보다 먼저 구성된 구독 범위, 고유 이벤트 수, 고유 영향 리소스 수,
관측 시각, 완전성, 원본 제한 사항을 보여 줍니다. 이벤트 식별자와 근거 식별자를 구분하므로
하나의 이벤트가 여러 영향 행으로 확장되어도 한 번만 계산합니다. 불완전한 근거는 검증된 숫자
0으로 바뀌지 않습니다.

혼합 리소스 상태 응답은 상태별 결론과 전원 상태, Resource Health 섹션을 분리해 표시합니다.
스키마 v2 검증 개체는 정렬된 `source_verifications`를 사용합니다. 각 항목은 정확한 권한,
근거 참조, 완전성, 제한 사항을 보존하며 합성된 결합 권한을 만들지 않습니다. 단일 원본 응답은
기존 전송 형태를 유지합니다.

판단 보류 응답은 확인할 수 없는 내용, 확인된 범위, 정확한 제한 사항, 다음 안전 읽기 단계를
먼저 보여 줍니다. 내부 쿼리 실행 과정은 기술 세부 정보에 유지합니다.

## 결정론적 교차 채널 표현 설계

의미 표현 플래너는 검증된 의도와 타입이 지정된 근거 형태 분석만 받습니다. 분석 결과는 항목 수,
필드 역할, 숫자 단위, 분모 검증, 시각 순서, 누락값, 잘림, 제한 사항 및 근거 참조를 기록합니다.
Markdown을 읽어 차트를 추론하지 않으며 모델은 컴포넌트 이름이나 필드 역할을 바꿀 수 없습니다.
플래너는 블록 결정을 반환하고 컴파일러는 변경할 수 없는 근거의 정확한 값을 버전이 있는 산출물에
복사합니다.

스키마 v1 및 v2 산출물은 재생 호환성을 위해 기존 `stack` 배치를 유지합니다. 스키마 v3은
검증된 타입 출력에만 서버가 선택한 `operational_brief`와 `markdown_document` 배치를
추가합니다. 각 v3 산출물은 현지화된 레이블, 정확한 섹션 수, 허용 목록 입력 범주 및 렌더링에
영향을 주는 전체 내용을 SHA-256 조립 다이제스트에 결속합니다. 원본 시스템 프롬프트 또는
운영자 메모리 내용은 포함하지 않습니다. Console은 답변 문장을 분류하지 않고 서버 결정을
렌더링하며 잘못되거나 변경된 산출물은 정본 Markdown으로 대체합니다.

### 결정 표

| 근거와 의도 | 선택 블록 | 필수 검사 | 안전한 대체 경로 |
|-------------|-----------|-----------|------------------|
| 스칼라 KPI 또는 짧은 상태 2-8개 | `summary` | 고유한 레이블과 정확한 값 | `list` |
| 정확한 식별자, 이질적인 열, 행 비교, 감사 행 또는 정밀도가 중요한 값 | `table` | 닫힌 열 집합과 범위가 제한된 행 | `list` |
| 소수의 이질적인 레코드 또는 레이블/값 레코드 | `list` | 범위가 제한된 레코드와 행 간 비교 불필요 | `table` |
| 관찰값, 기준선, 임계값 및 상태 | `threshold_table` | 호환 단위와 명시적 임계값 방향 | `table`과 `callout` |
| 범주형 또는 순위 값 2-12개 | `bar` | 단일 단위, 완전한 값, 잘림 없음 | `table` |
| 구성비 또는 커버리지 | `coverage` | 검증된 0이 아닌 분모와 완전한 분자 의미 | `table`과 `callout` |
| 단일 메트릭의 정렬된 관찰값 3개 이상 | `time_series` | RFC 3339 시각, 엄격한 정렬, 단일 메트릭, 단일 단위, 누락값 없음 | `table` |
| 기준선/현재/목표 또는 이전/이후 | `comparison` | 명시적 역할, 호환 단위, 완전한 비교값 | `table` |
| 인시던트 이벤트, 관찰 활동 또는 인계 | `timeline` | 정렬된 시각 또는 명시적으로 검증된 순서 | `table` 또는 `list` |
| 제한, 사용 불가 상태, 부분 근거 또는 승인 경계 | `callout` | 정확한 사유와 추론한 0 없음 | 정본 텍스트 |
| 인용, 출처, 증적 또는 정확한 출처 참조 | `evidence` | 최종 검증 증적에 속하는 참조 | 정본 텍스트 |

차트가 빠른 파악에 유리하지만 정확한 값도 중요하면 같은 근거 참조를 사용하는 접힌 표 블록을
뒤에 둡니다. 단위 불일치, 누락값, 불명확한 분모, 낮은 항목 수, 잘림 또는 불완전한 검증은 차트
선택을 차단합니다. `unavailable`은 그대로 유지하며 0으로 바꾸지 않습니다.

### 온톨로지 기반 시각화 선택

온톨로지는 차트 라이브러리 이름이 아니라 의미 역할과 관계를 설명합니다. Core 종단 producer는
검증된 operation, output shape, exact 행에서 닫힌 `semantic_shape` 하나와 범위가 제한된 필드
역할 바인딩을 파생합니다. 관계가 입증되지 않으면 metadata를 생략합니다. 결정론적 planner가 이
의미를 시각화 hint로 변환합니다. 모델은 이후 검증할 타입이 지정된 intent를 제안할 수 있지만
컴포넌트 이름을 방출하거나 필드 역할 또는 대체 경로를 바꿀 수 없습니다.

| 검증된 의미 형태 | 시각화 hint | Artifact 블록 | Exact 대체 경로 |
|------------------|-------------|---------------|-----------------|
| 단일 메트릭의 정렬된 관찰값 | `line` | `time_series` | Exact 표 |
| 정렬된 크기 또는 누적 변화 | `area` | `time_series` | Exact 표, 값은 단조 비감소해야 함 |
| 비교 가능한 범주형 값 | `bar` | `bar` | Exact 표 |
| 순위가 있는 범주형 값 | `bar_list` | `bar` | Exact 표, 양수이며 고유하고 정렬된 rank 필요 |
| 검증된 하나의 전체를 구성하는 부분 | `donut` | `bar` | Exact 표, 양의 total 하나와 일치하는 part 합계 필요 |
| 검증된 분자와 분모 | `category_bar` | `coverage` | Exact 표와 유효하지 않을 때 제한 안내 |
| 기준선, 현재, 목표, 이전 또는 이후 역할 | `comparison_bar` | `comparison` | Exact 표 |
| 정렬된 이벤트 또는 활동 | `tracker` | `timeline` | Exact 표 또는 목록 |
| 결속된 숫자 축 2개 | `scatter` | `scatter` | Exact 표 |
| 범주 차원 2개와 숫자 값 1개 | `heatmap` | `heatmap` | Exact 표, 좌표는 고유해야 함 |

검증된 의미가 크기나 누적을 입증하지 않으면 planner는 `area` 대신 `line`을 선택합니다. 레코드가
하나의 전체를 구성하는 부분임을 입증하지 않으면 `donut` 대신 `bar`를 선택합니다. 상관관계 형태는
scatter plot을 허용하지만 상관관계를 인과관계로 승격하지 않습니다.

Operator는 `presentation_semantics`를 renderer 권한이 아니라 검증할 주장으로 취급합니다.
Correlation에는 `label/x/y`만, matrix에는 `row/column/value`만 허용하며 나머지 shape 8개는
field-role map을 허용하지 않습니다. 잘못된 역할, 중복 binding, 누락된 증명 필드 또는 실패한 행
불변식은 exact 표를 유지하고 더 안전한 generic 시각화 또는 차트 없음으로 이동합니다.

### 버전 및 실패 계약

`presentation_artifact` v1은 바이트 단위 재생 호환성을 유지합니다. 버전 2는 타입이 지정된
`time_series`, `comparison`, `timeline`, `scatter`, `heatmap` 블록과 명시적인 차트 설명, 단위,
추가적인 시각화 hint를 제공합니다. v2 소비자는 정확한 키, 종류별 hint 허용 목록, 종류별 상한,
정렬된 시각, 유한한 값, 호환 단위, 고유한 슬롯 및 증적에 결속된 근거 참조를 검증합니다. 이전
v2 artifact에 hint가 없으면 기존 wire 형태와 결정론적 renderer 기본값을 유지합니다. 알 수 없는
버전, 블록, 필드, hint 또는 참조가 있으면 artifact 전체를 거부하고 읽을 수 있는 정본 텍스트를
렌더링합니다. 원시 JSON을 기본 답변으로 렌더링하지 않습니다.

각 차트 블록은 의미 설명과 인접한 정확한 값 표를 제공합니다. 블록 자체가 접근 가능한 표라면
표를 추가하지 않아도 됩니다. Web은 전체 모듈을 표시할 수 있습니다. Teams와 Slack은 기능
렌더러를 통해 같은 검증된 산출물을 축약합니다. 사용자 지정 채널은 플래너나 코어에 벤더 분기를
추가하지 않고 같은 렌더러 프로토콜을 주입합니다.

## 가지 계약

결정론적인 범위 및 권한 라우팅을 마치면 조정기는 조건을 충족한 독립 읽기 가지를 동시에
시작할 수 있습니다. 가지는 변경할 수 없는 근거 수집 작업이지, 중첩된 서술 세션이나 에이전트
직접 호출이 아닙니다. 대화의 정체성은 서술 번역자가 계속 지킵니다. 책임을 지는 도구나 에이전트가
가지 근거를 소유하고, 확정된 답변 구간은 결정론적 검증이 소유합니다.

| 필드 | 계약 |
|-------|----------|
| `branch_id` | 요청 안에서 고정되며 요청 식별자와 정본 가지 종류에서 파생됩니다. |
| `branch_kind` | `tool`, `operational`, `agent`, `public_web`처럼 허용 목록에 있는 읽기 출처 하나입니다. |
| `parent_branch_id` | 선택적인 의존성 참조이며, 독립적인 최상위 가지는 `null`을 씁니다. |
| `status` | `pending`, `running`을 거친 뒤 `completed`, `unavailable`, `failed`, `timed_out`, `cancelled` 중 하나로 단조 증가합니다. |
| `summary` | 범위가 제한되고 민감 정보가 가려진 진행 또는 최종 요약입니다. 근거로서의 권한은 없습니다. |
| `started_at`, `completed_at`, `duration_ms` | 선택적으로 관찰된 시각이며, 종료가 시작보다 앞설 수 없습니다. |
| `evidence_refs` | 가지가 최종 상태에 이르렀을 때만 내보내는, 범위가 제한된 정본 참조입니다. |

서버는 요청의 `seq` 순서대로 가지 수명 주기 프레임을 내보냅니다. 완료 순서는 달라질 수 있지만
결합 단계는 변경할 수 없는 결과를 정본 가지 종류 순서로 합칩니다. 거부된 신뢰할 수 없는
입력은 스택 추적 없이 `unavailable`이 됩니다. 예기치 못한 예외는 경고 근거와 함께 `failed`로
남습니다. 성공한 형제 가지는 계속 쓸 수 있습니다. 권위 간 충돌이 생기면 양쪽 근거를 모두
보존하고 답변을 미검증으로 표시합니다. 동시에 돌아가는 가지는 공유 맥락에 쓰지 않습니다.

첫 번째 묶음은 조건을 충족한 도구, 운영, 명시적으로 선택된 에이전트, 읽기 조사 에이전트,
결정론적 공개 웹 읽기에 범위가 제한된 작업 그룹 하나를 씁니다. 앞선 권한 판단 결과에 따라 수행
여부가 갈리는 작업은 범위가 제한된 후속 묶음에서 실행합니다. JSON과 SSE는 같은 병합 보조
로직을 씁니다.

## 확정된 개정판

초안 `token` 프레임은 잠정적인 서술로 남습니다. `confirmed` 프레임은 결정론적 검증기를
통과한 근거로 그려낸 완성된 구간만 담습니다. 여기에는 단조 증가하는 구간 번호, 답변 개정 번호,
근거 참조, 그리고 나중에 검증된 수정을 넣을 교체 구간이 포함됩니다. 확정된 구간은 아직
돌아가는 가지를 인용하지 않습니다. 최종 `done` 프레임이 정본이며, 대화 이력에 저장되는 유일한
답변입니다. 중단된 스트림은 부분 상태로 남고, 초안 텍스트는 확정 내용이 되지 않습니다. Semantic
POST 스트림은 요청 기한까지 영속 변환 결과를 기다립니다. 결과가 없으면 빈 성공 스트림이 아니라
영속 typed hold로 종료합니다.

웹 집약기는 화면에 그리기 전에 가지 종류, 단조 증가 상태, 시각, 근거 참조, 텍스트 한계를
검증합니다. 각 가지는 번호가 매겨진 조사 단계와 펼쳐볼 수 있는 제한된 근거로 그려냅니다.
관찰된 명령과 출력 상세는 기본적으로 접혀 있습니다. 대기 중인 토큰 그리기와 수정 개정판이
모두 빠져나간 뒤에야 확정 내용을 적용합니다.

토큰 프레임과 확정 프레임은 현재 정본 개정 번호와 일치해야 합니다. 밀려난 개정판이거나 예고되지
않은 개정판의 프레임은 순서 자리만 소비할 뿐, 텍스트를 덧붙이거나 정본 내용을 교체하거나
확정 콜백을 호출하거나 확정 지표를 올릴 수 없습니다. 확정 개정 번호는 엄격히 증가합니다.
`seq`가 빠지면 나중에 `done`이 도착해도 해당 턴은 부분 상태가 됩니다.

드로어 표시 여부는 표현 상태이며 대화 정체성과 독립적으로 유지됩니다. 열린 드로어 상태가
저장되어 있어도 이전 턴을 새 요청으로 재생하지 않습니다. 새 대화를 시작하면 운영자가 드로어를
닫았다가 다시 열 필요 없이 빈 정본 이력과 새로운 요청 및 멱등성 식별자를 만듭니다.

## 채널별 집약

웹, Teams, Slack은 같은 순서 기반 이벤트 집약을 씁니다.

- **웹**은 진행 중인 답변 옆에 간단한 가지 요약을 유지합니다. 상세 내용과 민감 정보가 가려진 정본
  명령/출력 근거는 펼칠 때까지 접혀 있습니다.
- **Teams와 Slack**은 원래 스레드에 응답 하나를 게시하고 단조 증가하는 편집을 적용합니다. 마지막
  편집에는 정본 검증 답변과 범위가 제한된 접힌 가지 요약이 들어갑니다.
- **기능 대체 경로**는 벤더가 편집을 지원하지 않을 때 완성된 최종 응답 하나를 보냅니다. 미리
  계산된 조각을 스트리밍이라고 설명하지 않으며 답변의 권한도 바꾸지 않습니다.

## 취소, 한계치, 재생

스트림 종료, 운영자의 중단, 요청 기한은 모든 하위 가지를 취소하고 종료를 기다립니다.
선택적인 진행 상황 관찰기가 실패해도 취소가 그대로 유효하며, 관찰기 오류는 가지를 실패로
바꾸지 않고 로그로만 남깁니다.

가지별 기한, 큐 용량, 가지 개수, 이벤트 크기, 활동 개수, 텍스트 바이트, 벤더 페이로드는 모두
제한된 상태를 유지합니다. 명령과 출력 근거에는 `redacted=true`가 필요합니다. 요약은 자격 증명,
테넌트 식별자, 고객 리소스 식별자, 정제되지 않은 웹 콘텐츠를 노출하지 않습니다. 영속 재생은
이미 끝난 읽기를 다시 실행하거나 프로바이더 메시지를 중복해서 보내지 않고 정본 최종 답변과
개정판 상태만 저장합니다.

intent 그래프 목표 인자는 계약의 양쪽에서 노드 128개와 중첩 6단계로 제한됩니다. 6단계는
object-set membership 술어에 필요한 깊이입니다. arguments, definition, predicates, 술어 하나,
그 values 배열, 값 하나 순서입니다. 이보다 얕은 한계치는 membership으로 걸러내는 계획의 답변을
모두 조용히 보류시켰습니다.

## 지표

진행 상황 지표는 집계 개수와 지연 시간만 보관합니다. 첫 진행 상황과 첫 확정 내용까지의 시간,
가지 종류, 결과, 소요 시간, 수정, 잘림, 최종 완료, 재생, 큐 포화, 순서 누락, 억제된
재시도, 모호한 채널 갱신을 기록합니다. 프롬프트, 답변, 가지 식별자, 채널 식별자, principal
식별자, 리소스 식별자는 보관하지 않습니다.

실패했거나 시간을 초과한 읽기는 턴 안에서 다시 시도하지 않습니다. 지표는 범위가 제한된 스트림
큐가 이벤트를 받아들인 뒤에만 기록합니다. 취소만 담긴 수명 주기 프레임은 첫 근거 진행이
아닙니다. 멱등적인 최종 재생은 근거 수집, 서술, 턴 종료 후 검토를 건너뛰면서도 관찰된 첫
확정까지의 지연 시간과 재생 횟수를 기록합니다. 서버는 빠진 클라이언트 프레임을 관찰할 수
없으므로 브라우저가 순서 누락과 부분 종료를 집계합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 근거 권한, 재생, 스트림 복구 | [콘솔 근거와 복원력](console-evidence-and-resilience-ko.md) |
| 화면 간 근거 권한 | [오퍼레이터 콘솔 화면 스냅샷](operator-console-view-snapshot-ko.md) |
| 대화 모듈 소유권 | [오퍼레이터 콘솔 모듈 지도](operator-console-module-map-ko.md) |
