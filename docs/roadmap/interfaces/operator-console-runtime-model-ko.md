---
title: Operator Console - Narrator, DI Seams, and Session Model
translation_of: operator-console-runtime-model.md
translation_source_sha: 56fbc2ca1e4ba379156e1f7256741fab12a2033b
translation_revised: 2026-08-11
---

# Operator Console - Narrator, DI Seams, and 세션 모델

> [operator-console-ko.md](operator-console-ko.md) section 1.2 및 4-6에서 분리한 focused 소유자 문서입니다.

## 런타임 설정 경계

Settings는 콘솔을 실행 표면으로 바꾸지 않고 제한된 런타임 정책을 관리할 수 있습니다.
읽기 담당은 가용성, 환경 상한, 저장된 재정의 및 effective 값의 정제된 변환 결과를
확인할 수 있습니다. Owner는 optimistic 개정 번호 검사를 통해 허용 목록된 정책 필드만
업데이트할 수 있습니다. 수락된 각 업데이트는 새 상태와 감사 항목을 원자적으로 기록합니다.

Settings 경로는 실행기 신원을 받지 않으며 cloud 리소스를 변경하지 않습니다. Dynamic
구성을 지원하는 런타임 소비자는 동작을 적용하기 전에 동일한 영속 정책을
읽습니다. 환경 및 infrastructure 값은 상한으로 유지됩니다. 저장된 선호 설정은
사용할 수 없는 기능을 활성화하거나, ActionType 또는 작업 흐름을 승격하거나, risk 및
승인 검사를 약화하거나, test-only 어댑터를 선택할 수 없습니다. 시크릿, 엔드포인트, 테넌트
식별자 및 managed 신원 식별자는 구성된 또는 사용 불가 상태로만 표시합니다.

초기 허용 목록은 제한된 조사, 인벤토리 최신성, analyzer 예산, 인시던트 auto-open
정책, 사례 이력 보존 및 로깅 상세를 포함합니다. 인시던트 정책은 활성화,
최소 심각도, repeat 임계값, repeat 구간을 노출하며 Heimdall이 프로세스 시작에
생성되므로 네 필드 모두 재시작이 필요합니다. 각 필드는 타입, 최소와 최대, 재시작
요구사항 및 사용 불가 사유를 선언합니다. 콘솔은 현재, proposed 및 effective 값,
개정 번호, 마지막 행위자와 갱신 시간, 검증 conflict를 표시합니다. Stale 개정 번호는 conflict를
반환하며 운영자가 재시도 전에 최신 상태를 검토하도록 합니다.

## 4. Narrator - LLM tier 모델

Narrator는 콘솔의 LLM translator 계층입니다. Core/CLI는 `Narrator` 프로토콜을 사용하고,
web progressive-answer 세대는 Operator API의 별도 백엔드 경계를 사용합니다. Azure 연결은
특정 account 이름에 고정되지 않고 `resolved-models.json`과 환경 조립에서 선택됩니다.

### 4.1 세 tier (trust 라우터를 반영)

| Tier | 모델 | 처리 | 기본? |
|------|-------|---------|----------|
| **Chat T0** | 없음 (정규식 / 키워드 의도) | Direct-hit 도구 호출: `list_hil`, `explain_verdict <id>`, `explore_catalog <keyword>`. | Yes (T0 의도가 구성된 임계값 이상 신뢰도로 매치하면 LLM 미호출) |
| **Chat T1** | `t1.judge` (mini reasoner) | 표준 턴: 자연어 ↔ tool_call, 대부분의 읽기 전용 조사, one-hop 후속 조치. | **Yes (mini always 활성)** |
| **Chat T2** | `t2.reasoner.primary` (frontier) | 에스컬레이션만 (§4.2 참조). | No (에스컬레이션 트리거로 명시적 선택) |

**Deterministic-first는 여전히 유효.** Chat T0 (정규식 / 키워드 의도, LLM
없음)이 매 턴 에서 먼저 시도되며 반복 오퍼레이터 verb (`list_hil`,
`explain_verdict <id>`, `explore_catalog <keyword>`)의 대부분을 처리할
것으로 예상. 설계 목표는 Chat T0가 턴의 다수를 해석 하고 Chat T2가
작은 소수 (~5-10% of turns, event-측 tier 분할을 반영)로 유지되는 것 -
하지만 이는 **측정된 기준선에 대해 검증할 목표** 이지 보장이 아니다.
콘솔은 per-tier 턴 개수를 telemetry 표면
([goals-and-metrics.md](../architecture/goals-and-metrics-ko.md))에 발행 하므로 분할은
측정되며 주장되지 않음. `t1.judge`가 "always 활성" 라는 것은 non-T0
턴의 대체 경로 이라는 뜻이지, 확신의 T0 의도가 매치할 때 LLM이 돌아간다
는 뜻이 아니다.

공개 웹 의도도 같은 tier 형태를 사용합니다. T0는 high-confidence explicit-search 및 local-scope
pattern을 유지합니다. 대상 턴이 `none`으로 남으면 Azure Responses 후보가 전용 system 프롬프트와
strict JSON 스키마를 사용해 경로, 분류 확신도, 사유 코드 및 범위가 제한된 English search
조회를 반환합니다. Alternative 발견은 목표, 비교 대상 및 2-8개 기능도 반환하며,
조정기가 해당 기능에서 실제 조회를 다시 구성합니다. 현재 화면 스냅샷 또는 이력은
받지 않습니다. Alternative 수집은 direct product 페이지만 수락하며 medium search 맥락으로 filtering 전
서로 다른 product를 최소 3개 요청합니다. Self 참조, 범용 homepage, conceptual guidance, editorial 또는
blog 페이지, documentation 인덱스 및 중복 product 신원은 근거가 Bragi에 도달하기 전에 제거합니다.
잘못된, low-confidence 또는 사용 불가 출력은 `none`을 유지하며
로컬 또는 sensitive-data denial을 재정의할 수 없습니다. Alternative가 아닌 목표에서는 라우팅에
영향을 주지 않는 model-generated 대상 또는 기능 필드를 폐기하지만, malformed 필수 필드는
계속 실패 시 차단합니다. 후보의 제한된 출력 예산을 분류에도 적용하므로 reasoning 토큰이
valid 구조화된 결정을 truncate하지 않습니다. 이 classifier 프롬프트는 Bragi answer-generation 프롬프트와
분리됩니다.

공개 수집은 `narrator_candidates`를 빌리지 않습니다. 해석기는 `t1.web_search`를
`web_search_candidates`로 선택하고 시작은 Operator API가 트래픽을 serve하기 전에 후보별 실제
managed-tool 요청을 한 번 전송합니다. 실패 후보는 제외합니다. 남은 후보가 없으면 Settings는
활성화된 선호 설정을 보존하지만 제한된 사유와 함께 `available=false`를 보고하고 관리를 비활성화합니다.
Settings는 정제된 프로바이더, Foundry project 구성 여부, 에이전트 이름, 모델 배포,
프로비저닝 상태 및 실제 도구 준비 상태도 표시합니다. Project 엔드포인트, Azure 리소스 ID,
테넌트 신원 또는 자격 증명은 노출하지 않습니다.

### 4.1.1 프로세스 간 에이전트 introspection

Core 런타임만 Pantheon을 소유합니다. 분리된 Operator API는 두 번째 에이전트 런타임을 내장하지 않고
`aw.pantheon.objects`에 multiplex한 범위가 제한된 logical 서비스 토픽 두 개로 Bragi에 접근합니다.
Server-echo 탐색으로 응답 소비자를 확인하고 재시도 중 같은 joining 소비자를 재사용하며 최초
Event Hubs 그룹 결합을 최대 20초 허용합니다. 요청은 silent 잘림 없이 최대 2,000자 질문과 process-secret salted
SHA-256 user/세션 참조를 전달합니다. 응답은 답변 16 KiB, 전체 결과 64 KiB, 대기 20초,
pending 요청 256개로 제한합니다. 고정 에이전트 이름과 정확한 대상 소유권을 검증하고 전체 정규화된
결과에서 민감한 값을 검사하며, 고정 대상 `AgentSpec`과 일치하는 charter 해시 및 도구 매니페스트만
유지합니다. Full-charter 해시는 역할 필드, 도구 용도/사실 범위 및 다국어 라우팅 예시를
포함하며 정확한 versioned 정책 귀속이 없는 answered 턴은 실패 시 차단합니다. 사실은 프로세스 경계를 넘기 전에 범위가 제한된 JSON으로 round-trip합니다. Conflicting request-id
재생 거부, 5분 캐시 만료, late/unmatched 응답 무시를 적용합니다. 실패는 attention 상태로 Bragi에 인계하며 선택한
에이전트가 근거를 제공했다고 주장하지 않습니다. 서비스 토픽은 액션, judgment, 승인 또는
실행기 권한을 부여하지 않습니다. 최종 서술은 charter 메타데이터를 출처 이력로만 사용하고
Bragi 신원을 유지하며 static 에이전트 spec을 런타임 근거로 표시하지 않고 내용 기반 주소를 가진
agent-state 참조를 direct 또는 tool-routed 정규화된 사실에서 생성합니다.

### 4.2 에스컬레이션 트리거 (T1 -> T2)

조정기는 다음 중 하나라도 발생하면 Chat T2로 escalate:

- Narrator의 T1 응답이 `finish_reason=abstain` 또는 aggregated 신뢰도가
 구성된 임계값 아래. **신뢰도는 도출되며 model-self-reported가
 아님:** write-class 턴은 검증기 결과 (§7.2); 읽기 전용 턴 (검증기
 미실행)은 Chat-T0 intent-match 점수, 모든 제안 `tool_call`이
 `argument_schema`에 대해 validate 됐는지, 도구가 `status=ok` 반환했는지
 로 구성. 모든 도구 호출이 validate + 성공한 읽기 전용 턴은 고-신뢰도
 이며 신뢰도만으로 절대 escalate 안 함.
- 검증기가 제안된 tool_call 시퀀스를 거부 (§7 참조).
- 요청된 도구가 `simulate_change`, `approve_hil`, `run_runbook`, 또는
 `activate_break_glass` **이고** 턴이 인자 해석을 위해 1 도구 홉
 이상 요구.
- 현재 세션의 multi-turn 홉 수가 구성된 한도 (기본 5) 초과 -
 의도가 novel 이라는 시그널.
- 사용자가 명시적으로 더 깊은 분석 요청 (자연어 표시 패턴,
 configurable).

에스컬레이션은 **세션 당 one-way**: 세션이 T2로 escalate 하면 같은 턴의
연장은 T2에 머무르지만 다음 턴은 다시 T1 에서 시작. 감사 항목은
`tier`, `escalation_trigger`, 그리고 escalate를 트리거한 T1 출력을
기록.

### 4.3 Narrator가 하면 안 되는 것

- **실행 충족 여부를 주장.** 오직 검증기만 (§7).
- **RBAC gate를 우회.** 조정기는 서술기를 호출하기 **전에** 하한을
 적용하므로, 모델에 넘겨진 도구 스키마는 호출 가능한 도구만 포함.
- **감사 로그를 직접 읽음.** Narrator는 도구 결과가 제공하는 것만 봄;
 감사 저장소는 프로토콜 경계 뒤에.
- **조정기가 도구 호출로 취급할 자연어 "명령"을 발행.** 모델의
 function-calling 응답으로부터 구조화된 `tool_calls`만 개수. 산문은
 산문; 실행되지 않음.
- **tool-인자 내용을 명령으로 취급.** 오퍼레이터-공급 인자 값 (하나의
 `restart_reason`, 자유-텍스트 필터)은 T2 이벤트 페이로드와 똑같이
 신뢰할 수 없는 입력이자 prompt-injection 표면
 ([아키텍처.instructions.md § LLM Quality Gate](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2)).
 그것들은 (a) 조정기 경계에서 schema-validate 되고, (b) trusted 텍스트
 로 system 프롬프트에 절대 concat 안 되며, (c) write-class 도구는 검증기
 (§7.2)가 재확인 - 인자 텍스트가 담을 수 있는 어떤 명령이 아닌 검증기
 가 권위. 민감정보 제거 (action-ontology §5.2)은 시크릿을 strip; injection 방어
 가 아니다 - 검증기 재확인이 방어.

### 4.4 비용과 비율 한도

D12에 따라: mini (t1.judge)는 항상 켜져 있고 오퍼레이터 예산 가정은
이것이 normal-cost 표면 라는 것. Upstream 기본은 **넘치지만-유한한**
턴 당 토큰 예산과 세션 당 홉 상한 (구성 키
`console.max_completion_tokens_per_turn`, 기본 4096, 그리고
`console.max_tool_hops_per_turn`, 기본 8)을 ship - 비용 거버넌스 vertical
이 지출을 단속하는 제품이 자신의 콘솔을 무계 LLM 표면으로 ship 할 수
없음. 기본에 사용자당 *비율* 한도는 없음; 포크는 구성으로 추가 MAY.
측정된 각 LLM 호출은 tier, 모델 배포 id, 워크로드 범위,
프롬프트/완료 토큰 개수를 metering 스트림에 기록합니다.

**제공되는 사용량 뷰.** T1과 T2 어댑터는 프로바이더가 측정한 `usage`를
`MeteringSink`로 기록합니다. 서술기도 같은 스트림을 사용하며 명시적인
`operator_chat` 범위를 기록하고, 나머지 호출은 `control_plane`을 사용합니다.
`LlmCostPanel`은 호환 경로 `GET /kpi/llm-cost`를 유지하지만 공개 변환 결과에는
토큰 사용량만 포함합니다. 범위, 모델, 모드, 대화(`correlation_id`),
일, 월별 합계와 함께 각 행에 모델 및 기능이 있는 최신 호출 원장을
상한 내에서 반환합니다. 콘솔은 이를 읽기 전용 **LLM 사용량** 패널로 렌더링합니다.

리전, 통화, 협상 요율 차이로 설정 기반 추정치와 프로바이더 청구서가 달라질 수
있으므로 Operator API와 콘솔에는 파생 비용을 노출하지 않습니다. 배포는 내부 예산
gate에서 설정된 가격표를 계속 사용할 수 있습니다. 헤드리스 코어와 Operator API는
별도 프로세스이므로 운영은 영속 Postgres `llm_invocation` 저장소를
사용합니다. 단일 프로세스 개발 하네스는 서술기 호출과 패널이 하나의
`InMemoryMeteringSink`를 공유합니다.

패널은 측정된 호출 기록에서 계산한 nullable `latest_occurred_at`도
반환합니다. LLM 사용량 화면은 이 시각을 Deck 스냅샷의 `capturedAt`으로
사용하며 오래된 metering 최신성을 브라우저 시간으로 대체하지 않습니다. 빈
metering 출처는 `null`을 반환합니다. 발행은 최선 노력이므로 계량 실패는
로그로 남고 결정 또는 chat 경로를 중단하지 않습니다.

### 4.5 Routed 턴 기한

Routed web 서술기는 턴 하나에 합계 wall-clock 기한을 적용합니다. 기본값은
30초이며 배포는 `FDAI_NARRATOR_TURN_TIMEOUT_SECONDS`를 1-300초 범위에서 설정할 수
있습니다. 각 후보는 남은 기한을 남은 후보 수로 나눈 예산만 받으므로
느린 배포 하나가 다른 후보의 장애 조치 예산까지 소비할 수 없습니다.
첫 streamed 토큰 전 시간 초과는 장애 조치할 수 있습니다. 토큰이 표시된 뒤 시간 초과가
발생하면 스트림을 중단하며 다른 모델의 텍스트를 결합하지 않습니다.

## 5. DI 경계

모든 경계는 프로토콜; 조립 루트가 구체 구현을 wire. `core/`는
프로토콜만 가져오기
([coding-conventions.instructions.md § 프로바이더 Protocols](../../../.github/instructions/coding-conventions.instructions.md#safety)).

### 5.1 `Narrator`와 web 세대 백엔드

```python
class Narrator(Protocol):
 def translate(
  self,
  *,
  utterance: str,
  tools: Sequence[ToolSchema],
  principal_role: str,
 ) -> str | None: ...
```

- Core 서술기는 RBAC로 보이는 도구 스키마만 받아 정본 verb 줄 또는 abstention을
 반환합니다. 조정기 정규식과 도구 RBAC가 계속 권위입니다.
- `AzureOpenAINarratorModel`의 strict translator 프롬프트는 현재 어댑터 코드가 소유합니다.
- Web `/chat` 및 `/chat/stream`은 AnswerPlan, 근거 해석, progressive 검증을
 위한 별도 비동기 백엔드를 사용하며 이 sync 프로토콜을 multi-turn 세대 API로 가장하지 않습니다.
- 긴 읽기 전용 조사는 검증된 최종 답변 전에 누적 `activity` 행과 범위가 제한된 Bragi
 `milestone` 메시지를 보냅니다. 활동 행은 고정된 id로 갱신되고 서술기 이력에서 제외되며
 완료된 요약은 tab reload 이후에도 유지됩니다.

Upstream 기본은
[`services/operator-service/src/fdai_operator_service/`](../../../services/operator-service/src/fdai_operator_service/)
아래의 `AzureOpenAINarratorModel`입니다. Azure OpenAI chat 완료를 strict one-line
translator로 호출하며 엔드포인트와 배포는 조립에서 resolved 모델 연결로 받습니다.

### 5.2 `ConsoleTool`

```python
class ConsoleTool(Protocol):
 name: str
 description: str
 rbac_floor: Role
 side_effect_class: SideEffectClass

 def call(
  self,
  *,
  arguments: Mapping[str, Any],
  principal: Principal,
 ) -> ToolResult: ...
```

- 현재 코어 이름은 `SystemConsoleTool`이며 `call()`은 조정기가 파싱하고 검증한 arguments와
 인증된 principal을 받습니다. 세션 이력이 필요한 web 도구는 Operator API의 별도 비동기
 프로바이더 경로를 사용합니다.
- `ToolResult`는 `data` (serialisable), `preview` (서술기가 요약하도록
 받는 짧은 사람이 읽는 문자열), 그리고 옵션 `evidence_refs` (감사 id,
 PR url, ARG 리소스 id - 서술기가 verbatim cite MUST)를 가진
 타입화된 데이터 클래스.

### 5.3 `ConversationChannelAdapter`

```python
class ConversationChannelAdapter(Protocol):
 channel_kind: ConversationChannelKind
 def receive(self) -> AsyncIterator[InboundTurn]: ...
 async def send(
  self, response: OutboundResponse
 ) -> ChannelDeliveryReceipt | None: ...
```

- 벤더 wire당 하나의 어댑터가 있습니다. Teams는 Bot Framework 활동, Slack은 signed
 HTTP 이벤트 API, web은 인증된 Operator API JSON/SSE를 사용합니다. CLI는 shared Operator API를
 호출하며 별도 벤더 어댑터가 아닙니다.
- `InboundTurn`은 조정기가 보기 전에 범위가 제한된 채널, 메시지, sender, 스레드, 텍스트 필드를
 검증합니다. `ConversationChannelGateway`는 해결되지 않은 sender를 차단하고 도구 실행 전에 중복
 메시지 id를 제거합니다.
- Push-방향 어댑터
 ([channels-and-notifications.md](channels-and-notifications-ko.md))는
 pull 어댑터와 **병합 안 됨**; 구성을 통해서만 자격 증명 공유. 이는
 `send-only`와 `receive-plus-send` blast-radius를 별개로 유지.

### 5.4 대화 작업 진행

Web, Slack, Teams는 하나의 순서가 있는 작업 진행 변환 결과를 사용합니다. 변환 결과는 제한된
서술기 이정표와 고정된 활동 갱신을 포함하며 채널은 표현만 변경합니다. 이정표는
앞선 활동 그룹을 닫고 관측된 사실과 다음 제한 작업을 설명합니다. 숨겨진 reasoning을 노출하거나
도구, 승인 또는 실행 권한을 부여하지 않습니다.

서버는 프롬프트 wording이 아니라 실제 작업을 기준으로 필요한 최소 표현을 선택합니다.

| 표현 | 선택 기준 | 채널 동작 |
|--------------|-----------|-----------|
| None | 활동, 인계, background 작업 없음 | 답변만 렌더링합니다. |
| 간결한 | 실패, 재시도, 인계가 없는 최종 읽기 활동 하나 | 간결한 세션 헤더와 관찰된 단계를 계속 표시하고 linked 출처 표시를 해당 단계에 통합하며 raw 출력과 시각만 접습니다. |
| 타임라인 | 여러 활동, 인계, 실패, 재시도, 코드 또는 파일 변경, non-read 권한 중 하나 이상 | 이정표와 활동 그룹을 causal 순서로 배치합니다. |
| Detached | 실행 정책이 영속 background 작업을 선택 | 영속 작업 요약을 렌더링하고 이후 진행 상황 또는 완료를 originating 스레드에 전달합니다. |

Web은 현재 활동 그룹과 completed 활동 그룹의 shell을 계속 표시합니다. 이정표 또는 최종 프레임은 앞선 그룹을 settled 상태로
바꾸되 관찰된 단계를 제거하지 않습니다. Raw 출력과 시각은 접힌 상태로 유지하며 운영자는 작업을 재생하지 않고 다시 펼칠 수 있습니다. Slack과
Teams는 확인 응답을 받은 메시지 하나를 cumulative 스냅샷으로 수정합니다. 갱신은 개정 번호와
활동 개수 기준으로 단조 증가하고 민감정보가 제거된 근거를 보존하며 정본 답변으로 끝납니다. 프로바이더
한도 때문에 이전 상세를 생략할 수 있지만 작업 순서를 바꾸거나 잘림 표시를 제거하거나
accountable 행위자를 대체할 수 없습니다. 재시작 또는 전달 재시도는 저장된 변경할 수 없는 스냅샷을
사용하며 도구를 다시 실행하지 않습니다.

## 6. 세션 모델 + 기억

`ConversationSession`은 principal 범위 `ConversationHistoryStore`의 범위가 제한된
working 변환 결과이다. 운영에서는 PostgreSQL `conversation`과
`conversation_turn` 행이 기억 of 기록이고, 브라우저 및 프로세스 내 세션은
폐기 가능한 캐시만 보유하므로 조정기는 raw 텍스트를 감사 로그에서 재생하지
않고 어느 노드에서든 recover할 수 있다.

### 6.1 세션 필드

```python
@dataclass(frozen=True)
class ConversationSession:
 session_id: str
 principal: Principal
 channel_id: str    # 채널 adapter 의 채널 식별자
 started_at: datetime
 turns: list[Turn]    # core/CLI의 bounded working projection
```

- `Turn` = `{turn_id, 역할, 내용, tool_calls?, tool_results?, tier,
 audit_entry_id}`.
- 운영 web 이력의 기억 of 기록은 principal 범위로 한정된 `ConversationHistoryStore`이며,
 코어 세션 객체는 disposable working 변환 결과입니다.

### 6.2 지속성 규칙

- **대화 원장**: 인바운드와 최종 assistant 턴은 고정된 요청 멱등성
 키와 함께 `conversation_turn`에 덧붙이기된다. 감사와 범용 온톨로지
 변환 결과에는 raw 대화 본문 대신 id, 해시, 라우팅 메타데이터, 근거
 참조만 남긴다.
- **사용자 맥락**: `UserPreferenceStore`는 로케일, verbosity, timezone,
 learner consent를 저장한다. `UserMemoryStore`는 source-turn 출처 이력과
 선택적 만료가 있는 명시적으로 확인된 사실만 수락한다. `operator_memory`는
 승인된 리소스 범위 운영 지식을 위한 별도 저장소로 유지한다.
- **Optimistic 동시성**: 선호 설정 및 정책 쓰기는 현재 개정 번호를 요구하고
 생성할 때만 `0`을 사용합니다. Policy 및 briefing-subscription 삭제도 현재 개정 번호를
 요구하므로 stale Settings tab은 `409`를 받습니다.
- **Learner consent**: learner-facing 턴 변환 결과는 기본적으로 메타데이터만
 제공한다. Raw 턴 본문은 같은 principal이 `share_with_learner: true`를
 명시적으로 설정한 경우에만 제공한다.
- **Post-turn 검토**: 두 대화 턴이 저장된 뒤 chat 경로는 범위가 제한된 묶음을 non-blocking 큐에
 제출합니다. Bragi가 `object.turn`에 발행하고 Norns가 응답 지연 시간 밖에서 결정론적 충족 여부와 선택적
 mixed-family 검토를 수행합니다. 읽기 담당이 볼 수 있는 `post-turn-reviews` 패널은 GET-only이며 제안 본문나
 승인 control 없이 영속 상태, 근거 참조, 제안 상태와 집계 acceptance를 제공합니다. Materialized operator-memory 제안은 retained 항목에 대한 restrictive foreign 키를 가지며 대화 reuse도 exact 항목이 활성 상태이고 여전히 해당 제안을 인용하는지 다시 확인합니다.
- **보존 및 변환 결과 정리**: 스케줄러는 90일이 지난 비활성 대화와 오래된
 briefing 실행을 삭제하고 명시된 만료 시각에 기억 사실을 삭제한다. 각
 PostgreSQL 출처 삭제는 해당 온톨로지 객체 id를 같은 트랜잭션에서
 큐한다. Leased 워커가 제한된 exponential 재시도로 metadata-only
 변환 결과를 삭제하므로 일시적인 온톨로지 실패가 영구 복사본을 조용히
 남기지 않는다.
- **변환 결과 일관성 경계**: 선호 설정, 기억, 정책 및 briefing 구독
 쓰기는 출처 기록과 같은 트랜잭션에서 출처 참조를 큐합니다.
 스케줄러는 임차 기간과 제한된 exponential 재시도를 사용해 upsert를 재생합니다.
 5회 실패한 작업은 무기한 재시도하지 않고 운영자 diagnostics용 dead-letter로
 이동합니다. 온톨로지 변환 결과는 출처 기록에서 재구성할 수 있습니다.
- **선제적 동작**: 허용 목록된 `ConversationPolicy` 기록만 고정 서술기 프롬프트
 fragment로 compile한다. Opening briefing과 scheduled briefing은 결정적
 `BriefingSpec`을 공유하며, 영속 구독은 IANA timezone을 사용하고
 근거에 기반한 `BriefingRun`을 소유 principal별로 저장한다.
- **Web 대화 탐색**: Console SPA는 대화 목록과 **새 대화** control을
 표시. 목록은 분리된 transcript 캐시를 가리키는 principal 범위로 한정된
 `localStorage` 인덱스이므로 스레드 전환, tab reload 또는 브라우저 재실행 시 완료된
 턴을 복원하면서 agent-scoped 대화와 일반 대화를 섞지 않음. Persistent 브라우저
 저장소가 차단된 환경에서는 `sessionStorage`로 대체 경로합니다.
 Operator는 로드된 transcript를 검색하고 일치하는 턴 사이를 이동할
 수 있음. 기본 대화는 비식별 user 해시와 정규화된 URL 경로 이름별로
 분리. query-only 필터 변경은 같은 경로 이름 세션을 재사용하고, 다른
 메뉴 또는 분석 상세 URL은 자체 transcript를 시작하거나 복원. 기본
 서술기는 **Bragi**이며 회신 헤더와 대화 행 모두 범용
 Deck 라벨 대신 Bragi 에이전트 icon을 사용. **캐시 지우기**와 **캐시된
 대화 제거**는 브라우저 copy만 삭제하며 영속 서버 이력은 삭제하지
 않습니다. 에이전트 카드에서 `Ask <agent>`를 선택하면 클릭할 때마다 새 user-scoped
 대화를 만들고 첫 턴 전에 해당 에이전트를 대상으로 저장합니다. 이전 에이전트 transcript를
 복원하거나 이어 쓰지 않으며, 이전 대화는 이력에서 계속 선택할 수 있습니다.
 Incident-bound 대화는 명시적으로 재개할 수 있도록 고정된 인시던트 신원을 유지합니다.
 이 브라우저 인덱스는 탐색 상태일 뿐이다. 각 user-scoped 대화 키는 고정된 서버
 대화 id로도 사용됩니다. 캐시 miss 시 Command Deck은 principal 범위 턴을 서버에서
 다시 로드하고 browser-local 저장소에 mirror한다. 인증된 시작에서는 서버 소유 대화
 메타데이터를 최대 1,000건까지 브라우저 인덱스에 병합하며 transcript 본문은 선택할 때만 로드합니다. 이전 random id를 사용하는 이전 방식 대화도
 계속 선택할 수 있고, 열 때 첫 운영자 턴에서 제목을 복원합니다.
 Floating Deck은 경로 탐색과 실제 운영 화면 re-render 중에도 유지된다.
 Full-workspace에서 활동 Bar 그룹을 선택하면 Deck을 닫고 해당 그룹의 첫 visible
 하위 페이지를 열며, 그 외에는 명시적인 닫기 액션 또는 `Escape`로 닫는다. L3 응답 언어는 현재 턴을 따름: 콘솔 display
 로케일이 영어여도 한국어 프롬프트에는 한국어로 답변. 그 외에는 운영자가
 설정한 로케일이 응답 언어를 제어. Localized 산문을 반환하기 전에 서술기는
 자신이 작성한 surrounding 산문만 교정하여 malformed 또는 nonsensical word, 우발적
 character 순서, duplicated fragment 및 우발적 언어 혼합을 제거합니다. Quoted
 근거 값, 식별자, 코드 및 도구 출력은 교정, 정규화, 번역 또는 재작성하지 않습니다.
 근거 검증 전에 terminal-answer 무결성은 Unicode replacement character,
 unpaired surrogate 코드 지점, 허용되지 않은 C0/C1 control 및 bidirectional 재정의 또는
 isolate control을 차단합니다. 경로는 malformed 텍스트를 저장하지 않고 localized 검증되지 않은
 답변을 반환합니다. Newline, tab 및 script-shaping zero-width 결합기는 계속 허용합니다.
 검증은 trim한 답변을 Unicode NFC 형식으로 비교하므로 동일한 한국어의 정본
 equivalent 표현이 false correction 개정 번호를 만들지 않습니다. 반환하는 정본 근거
 텍스트는 재작성하지 않습니다.
 Model-generated 한국어 답변은 최종 근거 검증 전에 범위가 제한된 post-generation
 검토를 한 번 받습니다. 경로는 exact 스냅샷 값, 식별자, URL 및 코드를 ordered
 자리 표시자로 마스킹합니다. 검토자는 초안을 pass하거나 narrator-authored 산문을 rewrite하거나
 복구할 수 없는 초안을 거부할 수 있습니다. 모든 자리 표시자가 원래 순서로 정확히 한 번씩
 나타나는 경우에만 rewrite를 수락하고 원래 근거를 byte-for-byte로 복원합니다. 명시적
 거절은 localized 검증되지 않은 답변이 됩니다. 검토자 장애, 잘못된 JSON, 자리 표시자
 mismatch, English 출력 및 결정론적 근거 fast 경로는 두 번째 모델 의존성을 추가하지
 않고 기존 factual 검증기를 계속 사용합니다. JSON과 SSE는 범위가 제한된 `answer_quality` 메타데이터를
 노출하고, SSE는 변경된 visible 초안을 기존 `revision` 프레임으로 교체합니다.
 탐색 목록은 대화를 **현재 화면**, **다른 화면**, **에이전트**로 그룹화.
 각 경로 이름은 제거할 수 없는 기본 화면 대화 하나를 소유. **새 대화**는 현재
 경로 이름에 대한 빈 임시 스레드를 만들고, 첫 운영자 턴을 보낸 뒤에만 해당
 프롬프트를 정규화한 제목으로 인덱스에 등록. 첫 턴 전에 닫거나 다른 화면으로
 이동하면 빈 스레드를 폐기. 화면 스레드의 출처 경로 이름과 라벨은 생성 후
 변경하지 않음. **다른 화면**의 스레드를 선택하면 transcript를 복원하기 전에
 해당 출처로 이동하므로 이전 턴이 다른 화면 근거와 결합되지 않음.
 에이전트 대화는 별도 그룹과 명시적 에이전트 범위를 유지.
- **운영 기억**: `operator_memory`는 승인된 리소스 범위 예외와 런북
 힌트를 저장한다. 서로 다른 승인자를 요구하며 personal 서술기 기억으로
 사용하지 않는다.
- **월 1+**: 세션들에 걸쳐 감지된 반복 조사 패턴이
 discovery-loop 시그널이 됨 (§9). 여전히 서술기 기억 아님 - 카탈로그의
 rule 후보가 결과 아티팩트.

### 6.3 의도적으로 저장하지 않는 것

- Narrator의 raw 세대 trace, per-token 로그, 또는 오퍼레이터 프롬프트
 의 임베딩 벡터. 감사 항목은 도구 호출과 서술기가 반환한
 *요약*을 포함; 모델의 내부 체인은 지속되지 않음.
- 채널 경계에서 redact 된 시크릿. Redactor는 채널 어댑터에 살음
 ([channels-and-notifications.md § 8 - 민감정보 제거](channels-and-notifications-ko.md#8-redaction)과 동일 정책).

### 6.4 Working 맥락 조립 (턴 수 제한 없음)

세션 transcript는 **기억 of 기록**다. 모든 턴은 보존 정책이
제거할 때까지 `ConversationHistoryStore`에 지속되므로 세션은 일어난 일을 기억한다.
특정 턴에 서술기가 받는 것은 별개의 **경계가 있는** 변환 결과 -
*working 맥락* - 로, 매 턴 토큰 예산 하에 재조립되므로 긴 세션이
프롬프트를 폭발시키지 않는다. Memory(무손실, 세션 길이에 대해 `O(L)`)와
프롬프트(경계, 상수 상한)는 의도적으로 구분된다.

JSON 및 SSE chat 경로는 후속 조치 planning 전에 인증된 `(principal_id, conversation_id)`
쌍으로 영속 저장소에서 이력을 해석합니다. 저장소가 구성된 경우 클라이언트가 제공한 이력은
사용하지 않습니다. 해석기는 턴 수 제한 없이 전체 transcript를 읽고, 이력이 기본
160,000-byte 예산 안에 있으면 모든 문자를 그대로 유지합니다. 예산을 넘으면 오래된 조각을 최대
두 번의 범위가 제한된 시도로 압축하면서 최신 20개 턴은 원문 그대로 유지합니다. 읽기 시간 초과,
compaction 시간 초과, 프로바이더 오류 또는 과도한 compaction 동시 확산이 발생하면 동일 principal 범위에서
최신 20개 턴을 다시 읽습니다. 해당 읽기도 실패하면 권한 확인 경계를 넘을 수 있는 브라우저
copy를 수락하는 대신 빈 이력을 사용합니다.

Content-policy 결정은 프로바이더 장애가 아니라 타입이 지정된 non-retryable 결과로 처리합니다. 차단된
history-compaction 조각은 범위가 제한된 depth 및 탐색 예산 안에서 분할하여 원인 턴만 모델
맥락에서 제외하며 영속 transcript 행은 변경하지 않습니다. 프롬프트에는 내용이 없는 omission
표시를 넣고 운영자 및 assistant 턴 메타데이터에는 `history_mode`, omitted 개수 및 정책 단계를
남깁니다. 차단된 내용에서 파생된 다이제스트는 프로바이더, 브라우저, 로그 또는 영속 메타데이터에 전달하지
않습니다. 최종 서술기 입력 블록은 하나의 30초 복구 기한 안에서 policy-safe compacted
이력으로 한 번, 빈 이력으로 한 번만 재시도합니다. 출력 블록은 재시도하거나 다른 모델로
라우팅하지 않습니다. 복구할 수 없는 블록은 한 번의 멱등적 재시도로 body-free SYSTEM 증적을
기록하고 assistant 턴은 기록하지 않습니다.

조립은 순수
[`compose_working_context`](../../../services/core-control-plane/src/fdai/core/working_context/composer.py)
정책이다. **턴 수**를 절대 제한하지 않는다; 대신 *토큰*을 제한하며,
[`ContextBudget`](../../../services/core-control-plane/src/fdai/core/working_context/types.py)에서 뽑은
네 개 tier에 걸쳐:

- **Pinned** - 상시 오퍼레이터 제약과 미해결 결정; 항상 포함되고, 이들만
 으로 예산을 초과하면 실패 시 차단 (`WorkingContextError`) - 절대 조용히
 버리지 않음.
- **타입이 지정된 사실** - 타입이 지정된 파이프라인에서 변환 결과 된 결정론적 no-LLM
 문맥(감사 항목, T0 판정)과 HIL 승인된 운영자 기억(선호 설정,
 재정의 note, forbidden 액션, 런북 힌트 - `operator_memory_to_entries`
 경유); `trusted` ground truth로 주입되며 절대 요약되지 않음.
 Forbidden-action 노트는 `pinned`이므로 예산 압박이 안전 제약을 절대 떨구지
 않는다. 이것이 상시 오퍼레이터 지식이 프롬프트에 닿는 방식이다 - 불투명한
 서술기 기억이 아니라 감사가능하고 범위 태깅된 trusted 레이어로 (section 1).
- **Verbatim recent** - 가장 최근 턴을 원문 그대로, 이력 예산의 일정
 비율까지 채움(턴 수가 아니라 토큰 기준).
- **관련성 수집** - 현재 발화와의 유사도로 끌어온 오래된 턴
 (`t1.embedding` + pgvector). verbatim 윈도우 밖의 턴도 관련되면 다시
 등장.
- **Hierarchical 요약** - 나머지 전부를 rolling 요약으로 접음(수준 1
 이 턴을, 수준 2가 level-1 요약을 접음)므로 요약 tier는 세션 길이 `L`에
 대해 `O(log L)`로 성장. 순수
 [`plan_summarization`](../../../services/core-control-plane/src/fdai/core/working_context/planner.py)
 정책이 어떤 턴을 어느 수준으로 접을지 결정하고 - 전체 `fold_factor` 청크만,
 따라서 턴이 혼자 접혔다가 재접히는 일이 없음 -
 [`SummarizationOrchestrator`](../../../services/core-control-plane/src/fdai/core/working_context/orchestrator.py)
 가 그 계획을 `TranscriptSummarizer` 경계에 대해 구동하여, 계획된 각 접기를
 안정된 순서로 핫 패스 밖에서 수행한다.

상위 우선순위 tier의 미사용 예산은 다음 tier로 spill 되므로, 짧은 세션은
요약으로 padding 하지 않고 verbatim 턴으로 채워진다. 두 I/O 경계 -
[`TranscriptSummarizer`](../../../services/core-control-plane/src/fdai/core/working_context/summarizer.py)
(mini 모델 접기, `t1.judge`)과 `TranscriptRetriever` (pgvector) - 은
결정론적 no-LLM 가짜를 업스트림에 제공하는 DI 프로토콜이다. 모든 조립은
턴 감사에 `context_manifest`(verbatim id, 요약 해시, retrieved id,
dropped id, tier별 토큰)를 기록하므로 어떤 프롬프트든 기억 of 기록에서
재구성 가능하다.

종단 간 [`assemble_turn_context`](../../../services/core-control-plane/src/fdai/core/conversation/context_bridge.py)는
세션 verbatim, 운영자 기억, 수집, 요약을 하나의 범위가 제한된 맥락으로 묶습니다.
Retriever가 없으면 `session_to_working_context`와 운영자 기억을 사용합니다.

변경되지 않은 `deterministic-tiered-v1@1.0.0` 기본값은 필수 `ContextSelectionPolicy`
검증기를 통과합니다. 범위가 제한된 후보는 요청 지연 시간 밖에 머물며 GET-only 비교
화면에는 수명 주기 control이 없습니다. [컨텍스트 선택 정책](../decisioning/context-selection-policy-ko.md)을 참고하세요.

**에이전트도 동일 메커니즘.** 에이전트 conversational 포트 (agent-to-agent
introspection)는 correlation-scoped transcript 위에서 같은 composer를
사용한다. 타입이 지정된 파이프라인 이벤트는 trusted `typed-fact` 항목으로 흘러들어,
no-LLM 결정론 히스토리와 LLM 대화를 하나의 타임라인에 유지하되 trust 경계를
넘지 않는다 - 외부/모델 생성 내용은 `trusted="false"`로 남아 data로
wrapping 되며, 이는 T2 quality gate가 이벤트 페이로드를 다루는 방식과 동일.
