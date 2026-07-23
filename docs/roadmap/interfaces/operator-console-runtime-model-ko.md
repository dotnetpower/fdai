---
title: Operator Console - Narrator, DI Seams, and Session Model
translation_of: operator-console-runtime-model.md
translation_source_sha: a768986796a378e40da913f0c2431a521a3e193c
translation_revised: 2026-07-23
---

# Operator Console - Narrator, DI Seams, and Session Model

> [operator-console-ko.md](operator-console-ko.md) section 4-6에서 분리한 focused owner 문서입니다.

## 4. Narrator - LLM tier 모델

Narrator는 콘솔의 LLM translator layer입니다. Core/CLI는 `Narrator` Protocol을 사용하고,
web progressive-answer generation은 read API의 별도 backend seam을 사용합니다. Azure binding은
특정 account 이름에 고정되지 않고 `resolved-models.json`과 environment composition에서 선택됩니다.

### 4.1 세 tier (trust router를 반영)

| Tier | 모델 | 처리 | 기본? |
|------|-------|---------|----------|
| **Chat T0** | 없음 (regex / keyword intent) | Direct-hit tool call: `list_hil`, `explain_verdict <id>`, `explore_catalog <keyword>`. | Yes (T0 intent가 configured threshold 이상 신뢰도로 매치하면 LLM 미호출) |
| **Chat T1** | `t1.judge` (mini reasoner) | 표준 turn: 자연어 ↔ tool_call, 대부분의 read-only investigation, one-hop follow-up. | **Yes (mini always active)** |
| **Chat T2** | `t2.reasoner.primary` (frontier) | Escalation만 (§4.2 참조). | No (escalation trigger로 opt-in) |

**Deterministic-first는 여전히 유효.** Chat T0 (regex / keyword intent, LLM
없음)이 매 turn 에서 먼저 시도되며 반복 오퍼레이터 verb (`list_hil`,
`explain_verdict <id>`, `explore_catalog <keyword>`)의 대부분을 처리할
것으로 예상. 설계 목표는 Chat T0가 turn의 다수를 resolve 하고 Chat T2가
작은 소수 (~5-10% of turns, event-측 tier 분할을 반영)로 유지되는 것 -
하지만 이는 **측정된 baseline에 대해 검증할 목표** 이지 보장이 아니다.
콘솔은 per-tier turn count를 telemetry surface
([goals-and-metrics.md](../architecture/goals-and-metrics-ko.md))에 emit 하므로 분할은
측정되며 주장되지 않음. `t1.judge`가 "always active" 라는 것은 non-T0
turn의 fallback 이라는 뜻이지, 확신의 T0 intent가 매치할 때 LLM이 돌아간다
는 뜻이 아니다.

Public-web intent도 같은 tier shape를 사용합니다. T0는 high-confidence explicit-search 및 local-scope
pattern을 유지합니다. 대상 turn이 `none`으로 남으면 Azure Responses candidate가 전용 system prompt와
strict JSON schema를 사용해 route, classification confidence, reason code 및 bounded English search
query를 반환합니다. Alternative discovery는 goal, comparison subject 및 2-8개 capability도 반환하며,
coordinator가 해당 capability에서 실제 query를 다시 구성합니다. Current screen snapshot 또는 history는
받지 않습니다. Alternative retrieval은 direct product page만 수락하며 medium search context로 filtering 전
서로 다른 product를 최소 3개 요청합니다. Self reference, generic homepage, conceptual guidance, editorial 또는
blog page, documentation index 및 duplicate product identity는 evidence가 Bragi에 도달하기 전에 제거합니다.
Invalid, low-confidence 또는 unavailable output은 `none`을 유지하며
local 또는 sensitive-data denial을 override할 수 없습니다. 이 classifier prompt는 Bragi answer-generation
prompt와 분리됩니다.

### 4.2 Escalation trigger (T1 -> T2)

Coordinator는 다음 중 하나라도 발생하면 Chat T2로 escalate:

- Narrator의 T1 응답이 `finish_reason=abstain` 또는 aggregated 신뢰도가
  configured threshold 아래. **신뢰도는 도출되며 model-self-reported가
  아님:** write-class turn은 verifier 결과 (§7.2); read-only turn (verifier
  미실행)은 Chat-T0 intent-match score, 모든 제안 `tool_call`이
  `argument_schema`에 대해 validate 됐는지, tool이 `status=ok` 반환했는지
  로 구성. 모든 tool call이 validate + 성공한 read-only turn은 고-신뢰도
  이며 신뢰도만으로 절대 escalate 안 함.
- Verifier가 제안된 tool_call 시퀀스를 reject (§7 참조).
- 요청된 tool이 `simulate_change`, `approve_hil`, `run_runbook`, 또는
  `activate_break_glass` **이고** turn이 인자 resolve를 위해 1 tool hop
  이상 요구.
- 현재 세션의 multi-turn hop 수가 configured limit (기본 5) 초과 -
  intent가 novel 이라는 시그널.
- 사용자가 명시적으로 더 깊은 분석 요청 (자연어 marker 패턴,
  configurable).

Escalation은 **세션 당 one-way**: 세션이 T2로 escalate 하면 같은 turn의
연장은 T2에 머무르지만 다음 turn은 다시 T1 에서 시작. Audit entry는
`tier`, `escalation_trigger`, 그리고 escalate를 트리거한 T1 output을
기록.

### 4.3 Narrator가 하면 안 되는 것

- **Execution eligibility를 주장.** 오직 verifier만 (§7).
- **RBAC gate를 우회.** Coordinator는 narrator를 호출하기 **전에** 하한을
  적용하므로, 모델에 넘겨진 tool 스키마는 호출 가능한 tool만 포함.
- **Audit log를 직접 읽음.** Narrator는 tool 결과가 제공하는 것만 봄;
  audit store는 Protocol seam 뒤에.
- **Coordinator가 tool call로 취급할 자연어 "명령"을 emit.** 모델의
  function-calling 응답으로부터 구조화된 `tool_calls`만 count. Prose는
  prose; 실행되지 않음.
- **tool-인자 내용을 명령으로 취급.** 오퍼레이터-공급 인자 값 (하나의
  `restart_reason`, 자유-텍스트 filter)은 T2 event payload와 똑같이
  신뢰할 수 없는 입력이자 prompt-injection surface
  ([architecture.instructions.md § LLM Quality Gate](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2)).
  그것들은 (a) coordinator 경계에서 schema-validate 되고, (b) trusted text
  로 system prompt에 절대 concat 안 되며, (c) write-class tool은 verifier
  (§7.2)가 재확인 - 인자 텍스트가 담을 수 있는 어떤 명령이 아닌 verifier
  가 권위. Redaction (action-ontology §5.2)은 secret을 strip; injection 방어
  가 아니다 - verifier 재확인이 방어.

### 4.4 Cost와 rate limit

D12에 따라: mini (t1.judge)는 항상 켜져 있고 오퍼레이터 budget 가정은
이것이 normal-cost surface 라는 것. Upstream 기본은 **넘치지만-유한한**
turn 당 token budget과 session 당 hop cap (config 키
`console.max_completion_tokens_per_turn`, 기본 4096, 그리고
`console.max_tool_hops_per_turn`, 기본 8)을 ship - Cost Governance vertical
이 지출을 단속하는 제품이 자신의 콘솔을 무계 LLM surface로 ship 할 수
없음. 기본에 사용자당 *rate* limit은 없음; fork는 config로 추가 MAY.
측정된 각 LLM 호출은 tier, model deployment id, workload scope,
prompt/completion token count를 metering stream에 기록합니다.

**제공되는 사용량 뷰.** T1과 T2 어댑터는 provider가 측정한 `usage`를
`MeteringSink`로 기록합니다. narrator도 같은 스트림을 사용하며 명시적인
`operator_chat` scope를 기록하고, 나머지 호출은 `control_plane`을 사용합니다.
`LlmCostPanel`은 호환 경로 `GET /kpi/llm-cost`를 유지하지만 공개 projection에는
토큰 사용량만 포함합니다. scope, model, mode, conversation(`correlation_id`),
일, 월별 합계와 함께 각 행에 model 및 capability가 있는 최신 호출 원장을
상한 내에서 반환합니다. 콘솔은 이를 read-only **LLM 사용량** 패널로 렌더링합니다.

리전, 통화, 협상 요율 차이로 설정 기반 추정치와 provider invoice가 달라질 수
있으므로 read API와 콘솔에는 파생 비용을 노출하지 않습니다. 배포는 내부 budget
gate에서 설정된 가격표를 계속 사용할 수 있습니다. 헤드리스 코어와 read API는
별도 프로세스이므로 production은 durable Postgres `llm_invocation` store를
사용합니다. 단일 프로세스 개발 하네스는 narrator 호출과 패널이 하나의
`InMemoryMeteringSink`를 공유합니다.

패널은 측정된 invocation record에서 계산한 nullable `latest_occurred_at`도
반환합니다. LLM 사용량 화면은 이 timestamp를 Deck snapshot의 `capturedAt`으로
사용하며 오래된 metering freshness를 browser time으로 대체하지 않습니다. 빈
metering source는 `null`을 반환합니다. emit은 best-effort이므로 계량 실패는
로그로 남고 decision 또는 chat 경로를 중단하지 않습니다.

## 5. DI seam

모든 seam은 Protocol; composition root가 구체 구현을 wire. `core/`는
Protocol만 import
([coding-conventions.instructions.md § Provider Protocols](../../../.github/instructions/coding-conventions.instructions.md#safety)).

### 5.1 `Narrator`와 web generation backend

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

- Core narrator는 RBAC로 보이는 tool schema만 받아 canonical verb line 또는 abstention을
  반환합니다. Coordinator regex와 tool RBAC가 계속 권위입니다.
- `AzureOpenAINarratorModel`의 strict translator prompt는 현재 adapter code가 소유합니다.
- Web `/chat` 및 `/chat/stream`은 AnswerPlan, evidence resolution, progressive verification을
  위한 별도 async backend를 사용하며 이 sync Protocol을 multi-turn generation API로 가장하지 않습니다.
- 긴 read-only investigation은 verified terminal answer 전에 누적 `activity` row와 bounded Bragi
  `milestone` message를 보냅니다. Activity row는 stable id로 update되고 narrator history에서 제외되며
  완료된 summary는 tab reload 이후에도 유지됩니다.

Upstream 기본은
[`src/fdai/delivery/azure/llm/narrator.py`](../../../src/fdai/delivery/azure/llm/narrator.py)
아래의 `AzureOpenAINarratorModel`입니다. Azure OpenAI chat completion을 strict one-line
translator로 호출하며 endpoint와 deployment는 composition에서 resolved model binding으로 받습니다.

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

- 현재 core 이름은 `SystemConsoleTool`이며 `call()`은 coordinator가 파싱하고 검증한 arguments와
  authenticated principal을 받습니다. Session history가 필요한 web tool은 read API의 별도 async
  provider path를 사용합니다.
- `ToolResult`는 `data` (serialisable), `preview` (narrator가 요약하도록
  받는 짧은 human-readable string), 그리고 옵션 `evidence_refs` (audit id,
  PR url, ARG resource id - narrator가 verbatim cite MUST)를 가진
  타입화된 dataclass.

### 5.3 `ConversationChannelAdapter`

```python
class ConversationChannelAdapter(Protocol):
    channel_kind: ConversationChannelKind
    def receive(self) -> AsyncIterator[InboundTurn]: ...
    async def send(
        self, response: OutboundResponse
    ) -> ChannelDeliveryReceipt | None: ...
```

- Vendor wire당 하나의 adapter가 있습니다. Teams는 Bot Framework activity, Slack은 signed
  HTTP Events API, web은 authenticated read API JSON/SSE를 사용합니다. CLI는 shared read API를
  호출하며 별도 vendor adapter가 아닙니다.
- `InboundTurn`은 coordinator가 보기 전에 bounded channel, message, sender, thread, text field를
  검증합니다. `ConversationChannelGateway`는 unresolved sender를 차단하고 tool 실행 전에 duplicate
  message id를 제거합니다.
- Push-방향 adapter
  ([channels-and-notifications.md](channels-and-notifications-ko.md))는
  pull adapter와 **병합 안 됨**; config를 통해서만 credential 공유. 이는
  `send-only`와 `receive-plus-send` blast-radius를 별개로 유지.

## 6. 세션 모델 + memory

`ConversationSession`은 principal 범위 `ConversationHistoryStore`의 bounded
working projection이다. Production에서는 PostgreSQL `conversation`과
`conversation_turn` row가 memory of record이고, browser 및 in-process session은
폐기 가능한 cache만 보유하므로 coordinator는 raw text를 audit log에서 replay하지
않고 어느 node에서든 recover할 수 있다.

### 6.1 세션 필드

```python
@dataclass(frozen=True)
class ConversationSession:
    session_id: str
    principal: Principal
    channel_id: str                # 채널 adapter 의 채널 식별자
    started_at: datetime
    turns: list[Turn]              # core/CLI의 bounded working projection
```

- `Turn` = `{turn_id, role, content, tool_calls?, tool_results?, tier,
  audit_entry_id}`.
- Production web history의 memory of record는 principal-scoped `ConversationHistoryStore`이며,
  core session object는 disposable working projection입니다.

### 6.2 지속성 규칙

- **대화 원장**: inbound와 terminal assistant turn은 stable request idempotency
  key와 함께 `conversation_turn`에 append된다. Audit와 generic ontology
  projection에는 raw 대화 본문 대신 id, hash, routing metadata, evidence
  reference만 남긴다.
- **사용자 context**: `UserPreferenceStore`는 locale, verbosity, timezone,
  learner consent를 저장한다. `UserMemoryStore`는 source-turn provenance와
  선택적 expiry가 있는 명시적으로 확인된 fact만 수락한다. `operator_memory`는
  승인된 resource 범위 운영 지식을 위한 별도 store로 유지한다.
- **Optimistic concurrency**: preference 및 policy write는 현재 revision을 요구하고
  생성할 때만 `0`을 사용합니다. Policy 및 briefing-subscription delete도 현재 revision을
  요구하므로 stale Settings tab은 `409`를 받습니다.
- **Learner consent**: learner-facing turn projection은 기본적으로 metadata만
  제공한다. Raw turn body는 같은 principal이 `share_with_learner: true`를
  명시적으로 설정한 경우에만 제공한다.
- **Post-turn review**: 두 conversation turn이 저장된 뒤 chat route는 bounded envelope를 non-blocking queue에
  제출합니다. Bragi가 `object.turn`에 발행하고 Norns가 response latency 밖에서 결정론적 eligibility와 선택적
  mixed-family review를 수행합니다. Reader가 볼 수 있는 `post-turn-reviews` panel은 GET-only이며 proposal body나
  approval control 없이 durable status, evidence reference, proposal state와 aggregate acceptance를 제공합니다.
- **보존 및 projection 정리**: 스케줄러는 90일이 지난 비활성 대화와 오래된
  briefing run을 삭제하고 명시된 expiry 시각에 memory fact를 삭제한다. 각
  PostgreSQL source 삭제는 해당 ontology object id를 같은 transaction에서
  queue한다. Leased worker가 제한된 exponential retry로 metadata-only
  projection을 삭제하므로 일시적인 ontology 실패가 영구 복사본을 조용히
  남기지 않는다.
- **Projection 일관성 경계**: preference, memory, policy 및 briefing subscription
  write는 source record와 같은 transaction에서 source reference를 queue합니다.
  Scheduler는 lease와 제한된 exponential retry를 사용해 upsert를 replay합니다.
  5회 실패한 job은 무기한 retry하지 않고 operator diagnostics용 dead-letter로
  이동합니다. Ontology projection은 source record에서 재구성할 수 있습니다.
- **선제적 동작**: allowlist된 `ConversationPolicy` record만 고정 narrator prompt
  fragment로 compile한다. Opening briefing과 scheduled briefing은 결정적
  `BriefingSpec`을 공유하며, durable subscription은 IANA timezone을 사용하고
  grounded `BriefingRun`을 소유 principal별로 저장한다.
- **Web 대화 탐색**: Console SPA는 대화 목록과 **새 대화** control을
  표시. 목록은 분리된 transcript cache를 가리키는 tab-scoped
  `sessionStorage` index이므로 thread 전환 또는 tab reload 시 완료된
  turn을 복원하면서 agent-scoped 대화와 일반 대화를 섞지 않음.
  Operator는 로드된 transcript를 검색하고 일치하는 turn 사이를 이동할
  수 있음. 기본 대화는 비식별 user hash와 정규화된 URL pathname별로
  분리. query-only filter 변경은 같은 pathname 세션을 재사용하고, 다른
  메뉴 또는 분석 detail URL은 자체 transcript를 시작하거나 복원. 기본
  narrator는 **Bragi**이며 reply header와 conversation row 모두 generic
  Deck label 대신 Bragi agent icon을 사용. **캐시 지우기**와 **캐시된
  대화 제거**는 browser copy만 삭제하며 durable server history는 삭제하지
  않는다. 이 browser index는 탐색 상태일 뿐이다. Cache miss 시 Command Deck은
  principal 범위 turn을 server에서 다시 로드하고 `sessionStorage`에 mirror한다.
  Floating Deck은 route 탐색과 live 화면 re-render 중에도 유지된다.
  Full-workspace에서 Activity Bar group을 선택하면 Deck을 닫고 해당 group의 첫 visible
  하위 page를 열며, 그 외에는 명시적인 닫기 action 또는 `Escape`로 닫는다. L3 응답 언어는 현재 turn을 따름: console display
  locale이 영어여도 한국어 prompt에는 한국어로 답변. 그 외에는 operator가
  설정한 locale이 응답 언어를 제어. Localized prose를 반환하기 전에 narrator는
  자신이 작성한 surrounding prose만 교정하여 malformed 또는 nonsensical word, 우발적
  character sequence, duplicated fragment 및 우발적 language mixing을 제거합니다. Quoted
  evidence value, identifier, code 및 tool output은 교정, 정규화, 번역 또는 재작성하지 않습니다.
  Evidence verification 전에 terminal-answer integrity는 Unicode replacement character,
  unpaired surrogate code point, 허용되지 않은 C0/C1 control 및 bidirectional override 또는
  isolate control을 차단합니다. Route는 malformed text를 저장하지 않고 localized unverified
  answer를 반환합니다. Newline, tab 및 script-shaping zero-width joiner는 계속 허용합니다.
  Verification은 trim한 answer를 Unicode NFC 형식으로 비교하므로 동일한 한국어의 canonical
  equivalent 표현이 false correction revision을 만들지 않습니다. 반환하는 canonical evidence
  text는 재작성하지 않습니다.
  Model-generated 한국어 answer는 terminal evidence verification 전에 bounded post-generation
  review를 한 번 받습니다. Route는 exact snapshot value, identifier, URL 및 code를 ordered
  placeholder로 mask합니다. Reviewer는 draft를 pass하거나 narrator-authored prose를 rewrite하거나
  복구할 수 없는 draft를 reject할 수 있습니다. 모든 placeholder가 원래 순서로 정확히 한 번씩
  나타나는 경우에만 rewrite를 수락하고 원래 evidence를 byte-for-byte로 restore합니다. Explicit
  rejection은 localized unverified answer가 됩니다. Reviewer outage, invalid JSON, placeholder
  mismatch, English output 및 deterministic evidence fast path는 두 번째 model dependency를 추가하지
  않고 기존 factual verifier를 계속 사용합니다. JSON과 SSE는 bounded `answer_quality` metadata를
  노출하고, SSE는 변경된 visible draft를 기존 `revision` frame으로 교체합니다.
  탐색 목록은 대화를 **현재 화면**, **다른 화면**, **에이전트**로 그룹화.
  각 pathname은 제거할 수 없는 기본 화면 대화 하나를 소유. **새 대화**는 현재
  pathname에 대한 빈 임시 thread를 만들고, 첫 operator turn을 보낸 뒤에만 해당
  prompt를 정규화한 제목으로 index에 등록. 첫 turn 전에 닫거나 다른 화면으로
  이동하면 빈 thread를 폐기. 화면 thread의 origin pathname과 label은 생성 후
  변경하지 않음. **다른 화면**의 thread를 선택하면 transcript를 복원하기 전에
  해당 origin으로 이동하므로 이전 turn이 다른 화면 evidence와 결합되지 않음.
  Agent 대화는 별도 그룹과 명시적 agent scope를 유지.
- **운영 memory**: `operator_memory`는 승인된 resource 범위 예외와 runbook
  hint를 저장한다. Distinct approver를 요구하며 personal narrator memory로
  사용하지 않는다.
- **Month 1+**: 세션들에 걸쳐 감지된 반복 investigation 패턴이
  discovery-loop 시그널이 됨 (§9). 여전히 narrator memory 아님 - 카탈로그의
  rule 후보가 결과 아티팩트.

### 6.3 의도적으로 저장하지 않는 것

- Narrator의 raw generation trace, per-token log, 또는 오퍼레이터 prompt
  의 embedding 벡터. Audit entry는 tool call과 narrator가 반환한
  *요약*을 포함; 모델의 내부 chain은 지속되지 않음.
- 채널 경계에서 redact 된 secret. Redactor는 채널 adapter에 살음
  ([channels-and-notifications.md § 8 - redaction](channels-and-notifications-ko.md#8-redaction)과 동일 정책).

### 6.4 Working context 조립 (턴 수 제한 없음)

세션 transcript는 **memory of record**다. 모든 turn은 retention policy가
제거할 때까지 `ConversationHistoryStore`에 지속되므로 세션은 일어난 일을 기억한다.
특정 턴에 narrator가 받는 것은 별개의 **경계가 있는** projection -
*working context* - 로, 매 턴 토큰 예산 하에 재조립되므로 긴 세션이
프롬프트를 폭발시키지 않는다. Memory(무손실, 세션 길이에 대해 `O(L)`)와
prompt(경계, 상수 상한)는 의도적으로 구분된다.

조립은 순수
[`compose_working_context`](../../../src/fdai/core/working_context/composer.py)
정책이다. **턴 수**를 절대 제한하지 않는다; 대신 *토큰*을 제한하며,
[`ContextBudget`](../../../src/fdai/core/working_context/types.py)에서 뽑은
네 개 tier에 걸쳐:

- **Pinned** - 상시 오퍼레이터 제약과 미해결 결정; 항상 포함되고, 이들만
  으로 예산을 초과하면 fail-closed (`WorkingContextError`) - 절대 조용히
  버리지 않음.
- **Typed facts** - typed 파이프라인에서 projection 된 결정론적 no-LLM
  문맥(audit entry, T0 verdict)과 HIL 승인된 operator memory(preference,
  override note, forbidden action, runbook hint - `operator_memory_to_entries`
  경유); `trusted` ground truth로 주입되며 절대 요약되지 않음.
  Forbidden-action 노트는 `pinned`이므로 예산 압박이 안전 제약을 절대 떨구지
  않는다. 이것이 상시 오퍼레이터 지식이 프롬프트에 닿는 방식이다 - 불투명한
  narrator memory가 아니라 감사가능하고 scope 태깅된 trusted 레이어로 (section 1).
- **Verbatim recent** - 가장 최근 턴을 원문 그대로, history 예산의 일정
  비율까지 채움(턴 수가 아니라 토큰 기준).
- **Relevance retrieval** - 현재 발화와의 유사도로 끌어온 오래된 턴
  (`t1.embedding` + pgvector). verbatim 윈도우 밖의 턴도 관련되면 다시
  등장.
- **Hierarchical summary** - 나머지 전부를 rolling summary로 접음(level 1
  이 턴을, level 2가 level-1 요약을 접음)므로 요약 tier는 세션 길이 `L`에
  대해 `O(log L)`로 성장. 순수
  [`plan_summarization`](../../../src/fdai/core/working_context/planner.py)
  정책이 어떤 턴을 어느 level로 접을지 결정하고 - 전체 `fold_factor` 청크만,
  따라서 턴이 혼자 접혔다가 재접히는 일이 없음 -
  [`SummarizationOrchestrator`](../../../src/fdai/core/working_context/orchestrator.py)
  가 그 계획을 `TranscriptSummarizer` seam에 대해 구동하여, 계획된 각 fold를
  안정된 순서로 핫 패스 밖에서 수행한다.

상위 우선순위 tier의 미사용 예산은 다음 tier로 spill 되므로, 짧은 세션은
요약으로 padding 하지 않고 verbatim 턴으로 채워진다. 두 I/O seam -
[`TranscriptSummarizer`](../../../src/fdai/core/working_context/summarizer.py)
(mini 모델 folding, `t1.judge`)과 `TranscriptRetriever` (pgvector) - 은
결정론적 no-LLM fake를 업스트림에 제공하는 DI Protocol이다. 모든 조립은
턴 audit에 `context_manifest`(verbatim id, summary hash, retrieved id,
dropped id, tier별 토큰)를 기록하므로 어떤 프롬프트든 memory of record에서
재구성 가능하다.

End-to-end [`assemble_turn_context`](../../../src/fdai/core/conversation/context_bridge.py)는
session verbatim, operator memory, retrieval, summary를 하나의 bounded context로 묶습니다.
Retriever가 없으면 `session_to_working_context`와 operator memory를 사용합니다.

변경되지 않은 `deterministic-tiered-v1@1.0.0` 기본값은 필수 `ContextSelectionPolicy`
validator를 통과합니다. Bounded candidate는 request latency 밖에 머물며 GET-only comparison
view에는 lifecycle control이 없습니다. [컨텍스트 선택 정책](../decisioning/context-selection-policy-ko.md)을 참고하세요.

**에이전트도 동일 메커니즘.** 에이전트 conversational port (agent-to-agent
introspection)는 correlation-scoped transcript 위에서 같은 composer를
사용한다. Typed 파이프라인 이벤트는 trusted `typed-fact` entry로 흘러들어,
no-LLM 결정론 히스토리와 LLM 대화를 하나의 타임라인에 유지하되 trust 경계를
넘지 않는다 - 외부/모델 생성 내용은 `trusted="false"`로 남아 data로
wrapping 되며, 이는 T2 quality gate가 이벤트 payload를 다루는 방식과 동일.
