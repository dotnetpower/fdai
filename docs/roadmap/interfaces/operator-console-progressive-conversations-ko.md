---
title: 오퍼레이터 콘솔 점진적 대화
translation_of: operator-console-progressive-conversations.md
translation_source_sha: b729c4a2c4f350c9637ce343bc20f1b38afac1db
translation_revised: 2026-08-14
---
# 오퍼레이터 콘솔 점진적 대화

이 문서는 점진적으로 진행되는 오퍼레이터 콘솔 대화의 채널 중립적인 가지 수명 주기, 순서가 있는
집약, 검증된 개정판, 범위가 제한된 진행 상황 계약을 소유합니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| Web 점진적 스트림 집약 | 구현됨 | [`backend-stream.ts`](../../../console/src/deck/backend-stream.ts), [`backend-stream-fallback.test.ts`](../../../console/src/deck/backend-stream-fallback.test.ts), [`backend-stream-v1-contract.test.ts`](../../../console/src/deck/backend-stream-v1-contract.test.ts) | 집중 테스트는 순서가 있는 프레임, 재생 거부, 가지 수명 주기, 확정된 개정판, 부분 턴을 다룹니다. 이 행은 Teams 또는 Slack 런타임 검증을 주장하지 않습니다. |
| 채널 중립적 최종 집약 | 구현됨 | [`conversation_channel.py`](../../../services/core-control-plane/src/fdai/shared/providers/conversation_channel.py), [`test_rich_contract.py`](../../../services/core-control-plane/tests/delivery/channels/test_rich_contract.py) | 집중 계약 테스트 36개가 통과했습니다. Teams와 Slack은 영속 재생 전체에서 동일한 정본 답변, 제한, 근거 참조, `execution_authority=false`, 단조 증가하는 최종 확정 갱신을 보존합니다. 운영 A3 게시자나 통제된 채널 런타임 증적을 주장하지 않습니다. |
| 드로어 표현 및 새 대화 정체성 | 진행 중 | [`use-command-deck-sessions.ts`](../../../console/src/deck/use-command-deck-sessions.ts), [`console-routes.spec.ts`](../../../console/tests/live-e2e/console-routes.spec.ts) | Console은 저장된 드로어 표시 여부와 독립적으로 새 세션을 만들며, 라이브 테스트는 이제 새 대화에서 요청을 격리합니다. 인증된 런타임 증적 통과가 아직 필요합니다. |
| 통제된 4단계 온톨로지 증적 | 진행 중 | [`console-routes.spec.ts`](../../../console/tests/live-e2e/console-routes.spec.ts) | 요청부터 Console까지 이어지는 검증이 있으며 번역된 요약 순서에 의존하지 않고 요청에 결속된 증적의 disclosure 조상을 펼칩니다. `검증됨`을 뒷받침하는 새 보존 통과 산출물은 없습니다. |
| 이중 언어 무작위 릴리스 게이트 | 진행 중 | [`ontology-query-assurance-readiness.ts`](../../../console/tests/live-e2e/ontology-query-assurance-readiness.ts), [`ontology-query-assurance.test.ts`](../../../console/tests/live-e2e/ontology-query-assurance.test.ts) | 집중 보증 테스트 41개가 통과했습니다. 전체 집단은 영어와 한국어 모두에서 근거가 완전한 answered 턴이 없으면 `production_ready=true`를 보고할 수 없으며 실제 운영 spec은 운영 준비 판정을 단언합니다. 새 100-case 통과 산출물은 여전히 필요합니다. |
| 의미 명확화 표현 | 구현됨 | [`verification-presentation.ts`](../../../console/src/deck/verification-presentation.ts), [`verification-presentation.test.ts`](../../../console/src/deck/verification-presentation.test.ts) | `semantic_clarification_required`를 `Context required`로 표시하며 Console 집중 테스트 13개가 통과했습니다. 분류는 제어 평면이 실제로 방출하는 이유 코드만 다룹니다. 인증되고 보존된 증적은 열린 항목으로 남아 있습니다. |
| 검증된 의미 답변 표현 | 검증됨 | [`semantic_turn_processor.py`](../../../services/core-control-plane/src/fdai_core_service/semantic_turn_processor.py), [`semantic_turn_presentation.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/semantic_turn_presentation.py), [`semantic_turn_runtime.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/semantic_turn_runtime.py), [`semantic-answer-presentation.spec.ts`](../../../console/tests/live-e2e/semantic-answer-presentation.spec.ts), `.fdai/live-validation/semantic-answer-presentation-244d003ef77bd37dc0041f0b6a29634cdbaacb91-post-validation/` | 범위가 제한된 인증 Web/한국어 경로는 명시적 workspace patch digest와 함께 중앙 검증된 source revision `244d003ef`에서 검증됐습니다. 최초 턴과 재생성 턴은 관찰된 5단계, 동일한 인시던트 및 기술 출력 digest, 읽기 전용 근거 수집, primary JSON 미노출, `execution_authority=false`를 유지했습니다. 이 상태는 Teams, Slack, 4단계 온톨로지 실행기 또는 이중 언어 100-case 집단을 주장하지 않습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
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

### 남은 작업

- [ ] 인증된 요청부터 Console까지 이어지는 4단계 온톨로지 통과 증적을 새 저장소 경로에
  보존합니다.
- [ ] 2026-08-11 기준선을 교체하지 않고, 두 언어 모두에서 근거가 완전한 answered 턴이 있는
  seed `0x0fda1`의 영어/한국어 100-case 무작위 보증 통과 산출물을 보존합니다.
- [ ] 채널 전체 런타임 검증을 주장하기 전에 통제된 Teams 및 Slack 집약 증적을 기록합니다.
- [x] 정확한 machine payload와 최종 검증 증적은 접힌 기술 상세에 보존하면서 primary semantic
  답변의 fenced machine JSON을 지역화되고 결정론적인 운영자 대상 내용으로 교체합니다.
- [x] `Preparing answer`가 `done` 전에 관찰된 수락, 계획, 근거, 검증 및 표현 작업을 반영하도록
  단조 증가하는 의미 수명 주기 프레임을 내보내고 재생합니다.
- [x] 완료된 의미 표현 및 재생성 경로의 통제된 인증 Browser 산출물을 보존한 뒤 한국어 동등
  실행을 수행하고 보존합니다.

## 의미 최종 표현 계획

현재 의미 경로는 조회 실행과 검증을 입증하지만 운영자 대상 표현 전에 멈춥니다. Core는 검증된
출력을 fenced JSON으로 직렬화하고, Operator는 `done` 이벤트 하나를 재생하며, 최종 payload에
`answer_plan`, `presentation_artifact`, `trajectory_detail`이 없으므로 Console은 설계대로 해당
정본 텍스트를 fallback으로 표시합니다. 기존 `Preparing answer` 컴포넌트는 일시적인 브라우저
상태입니다. `inFlight`가 true인 동안에만 표시할 수 있고 의미 단계 이벤트를 받지 못하므로 완료된
재생에서는 어떤 작업이 수행됐는지 설명할 수 없습니다.

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
