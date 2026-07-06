---
title: 오퍼레이터 콘솔 (Conversational)
translation_of: operator-console.md
translation_source_sha: 67df825e17b460f4784960abe417215e077bcac7
translation_revised: 2026-07-06
---

# 오퍼레이터 콘솔 (Conversational)

사람 오퍼레이터가 대화형 인터페이스로 AIOpsPilot 에게 **역으로 말할 수 있는**
방식 — CLI REPL 이 먼저, Teams / Slack 챗이 다음, 웹 챗이 마지막. 이 문서는
**대화형 surface** 를 권위적으로 정의한다: 계층 아키텍처, tool 카탈로그, LLM
tier 모델, 세션 지속성, tool 별 RBAC, 안전 invariant, 단계별 rollout.

Push 방향 (시스템 → 사람) 알림은
[channels-and-notifications.md](channels-and-notifications-ko.md) 에 있고,
읽기 전용 콘솔 SPA 는
[project-structure.md § console/](project-structure-ko.md#console-static-web-app)
에 있음. 이 문서는 **pull 방향** 을 다룬다 — 오퍼레이터가 묻고, 시뮬레이션
하고, 승인. 알림 문서가 이미 어댑터를 제공하는 모든 채널에 걸쳐. Push 와
pull 은 같은 채널 credential 과 같은 audit 계약을 공유하지만 서로 다른
통합 surface 이다.

> 고객-무관: 아래의 모든 채널 id, LLM deployment 이름, 리소스 id, 그룹
> 이름은 placeholder. Fork 는 config 로 실제 값을 공급
> ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).

## 1. Framing - 무엇인가 (그리고 무엇이 아닌가)

오퍼레이터 콘솔은 **자율 SRE agent 가 아니다**. AIOpsPilot 의 판단 authority
는 이미 있는 곳에 그대로 남는다 — deterministic engine (T0), quality gate (T2
verifier), risk gate, shipped Rego policy. 콘솔은 그 판단을 오퍼레이터가
검사하고, 변경을 시뮬레이션하고, 시스템이 이미 큐잉한 것을 승인하는
**대화형 surface** 이다.

세 property 가 직접 따라온다:

- **LLM 은 translator 이지 judge 가 아님.** 자연어 in, tool call out; tool
  결과 in, 자연어 out. LLM 은 execution eligibility 를 절대 부여하지 않음 —
  오직 verifier 만
  ([architecture.instructions.md § Design Principles](../../.github/instructions/architecture.instructions.md#design-principles)).
- **Tool 은 pipeline stage 를 노출하고, primitive data source 가 아님.**
  LLM 이 진단으로 조합해야 하는 `query_log()` + `query_metric()` +
  `read_config()` 대신, 콘솔은 `describe_event()`, `explain_verdict()`,
  `simulate_change()` 를 노출. 시스템이 이미 reasoning 을 완료했음;
  오퍼레이터는 결과에 대해 묻는다.
- **성장은 카탈로그 성장이지, 모델 memory 성장이 아님.** 반복되는
  investigation 패턴은 discovery loop 를 통해 새 룰 후보가 됨
  ([architecture.instructions.md § Rule Catalog](../../.github/instructions/architecture.instructions.md#rule-catalog)) —
  불투명한 LLM 세션 memory 가 아님. 대화 간에 persist 되는 모든 상태는
  `audit_log` + `operator_memory` 에 살며, 감사가능 / export 가능 / CSP-중립.

### 1.1 Azure SRE Agent 와의 비교

Azure SRE Agent
([sre.azure.com/docs/overview](https://sre.azure.com/docs/overview)) 는
업계가 인식하는 카테고리를 정의하기 때문에 참조로서 유용하다. 우리 콘솔은
같은 오퍼레이터 경험을 다른 판단 모델로 겨냥한다.

| 축 | Azure SRE Agent | AIOpsPilot Operator Console |
|------|-----------------|-----------------------------|
| Primary judge | LLM agent (with tool) | Deterministic engine + verifier |
| LLM 역할 | Primary reasoner | Translator + T2 fallback (~5-10% turn) |
| 성장 | LLM 이 팀 패턴 학습 | Rule catalog + `operator_memory` 축적 |
| Tool 확장 | MCP connector (외부 protocol) | Rule catalog + ActionType + 옵션 MCP (Week 2+) |
| Trust 시그널 | LLM self-confidence | Rule severity + shadow → enforce metric + verifier pass |
| 세션 지속성 | Model-side memory | Append-only audit log + `operator_memory` |
| Multi-signal RCA | LLM 이 log / metric / trace 상관관계 | 시스템이 ingest 에서 이미 상관관계 완료; 오퍼레이터는 *"왜 X 로 결정했어?"* 를 물음 |

추상적으로 어느 접근이 "더 좋다" 는 없다; 서로 다른 제품이다. 오퍼레이터
콘솔은 AIOpsPilot 의 `deterministic-first` 원칙과 rule-catalog collection
계약에 fit 하는 것.

### 1.2 공유 glossary 에 추가된 어휘

다음 토큰들이
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md)
의 공유 어휘에 추가되며 참조하는 모든 문서에서 일관되게 사용된다:

- **operator-console** - 여기 문서화된 계층 surface.
- **narrator** - 오퍼레이터 콘솔의 LLM tier (translator 역할; judge 절대
  아님). T2 quality-gate 역할과는 별개 — 그건 제안된 액션에 대한 도메인
  reasoner.
- **operator-conversation** - 오퍼레이터와 콘솔 사이의 bounded exchange
  하나 (멀티-turn, RBAC-scoped, 감사됨).
- **console-tool** - narrator 가 호출 가능한 노출된 pipeline stage 또는
  카탈로그 view 하나.

## 2. 3-layer 아키텍처

```mermaid
flowchart TD
  subgraph L3["Layer 3 — Channel (thin adapter)"]
    CLI["CLI REPL"]
    TEAMS_PULL["Teams (pull)"]
    SLACK_PULL["Slack (pull)"]
    WEB["Web chat (Console SPA)"]
  end
  subgraph L2["Layer 2 — Conversation Coordinator"]
    NARR["Narrator (LLM)\nt1.judge default\nt2.reasoner escalation"]
    INTENT["Intent classify\n(read | simulate | approve | breakglass)"]
    RBAC["RBAC gate\n(per-tool role floor)"]
    VERIF["Verifier re-check\n(no auto-execute)"]
    SESS["Session state\n(audit-log-backed)"]
  end
  subgraph L1["Layer 1 — Existing deterministic core (unchanged)"]
    CL["ControlLoop"]
    RULES["RuleIndex / T0Engine"]
    QG["QualityGate"]
    EXEC["ShadowExecutor / RiskGate"]
    INV["Inventory / StateStore"]
  end
  CLI --> INTENT
  TEAMS_PULL --> INTENT
  SLACK_PULL --> INTENT
  WEB --> INTENT
  INTENT --> RBAC --> NARR --> VERIF --> SESS
  NARR -.tool call.-> CL
  NARR -.tool call.-> RULES
  NARR -.tool call.-> QG
  NARR -.tool call.-> EXEC
  NARR -.tool call.-> INV
```

- **Layer 3 (Channel)** 은 얇다. 각 채널 adapter 는 wire 포맷 (stdin /
  Teams Activity / Slack event / WebSocket frame) 의 한 turn 을
  `ConversationTurn` 으로, 그리고 반대 방향으로 변환. 판단은 여기 없음.
- **Layer 2 (Coordinator)** 는 intent classification, RBAC gating, tool
  dispatch, verifier re-check, 세션 bookkeeping 을 소유. Narrator 는 DI
  seam (`ConversationalModel` Protocol - §5 참조) 이므로 fork 가 어떤 LLM
  provider 든 바인딩 가능; upstream 기본은 Azure OpenAI.
- **Layer 1 (Core)** 은 이미 shipping 중인 deterministic core 그대로.
  콘솔은 새 판단 경로, 새 지속성 저장소, 새 execution vector 를 추가하지
  않는다. 콘솔 tool call 은 기존 pipeline 이 이미 만드는 법을 아는 call
  로 resolve.

### 2.1 모듈 맵

- [`src/aiopspilot/core/conversation/`](../../src/aiopspilot/core/conversation/)
  - `coordinator.py` - `ConversationCoordinator` (Layer 2 orchestrator).
  - `tools.py` - `ConsoleTool` Protocol + per-tool 구현체가 Layer 1
    모듈에만 delegate.
  - `narrator.py` - `ConversationalModel` Protocol + tier-select 로직
    (t1.judge default, t2.reasoner.primary escalation).
  - `session.py` - `ConversationSession` dataclass; 상태는 append-only
    audit log 로부터 project 됨.
- [`src/aiopspilot/delivery/channels/`](../../src/aiopspilot/delivery/channels/)
  - `cli_repl.py` - Day-1 채널 adapter (stdin/stdout).
  - `teams_bot.py` - pull-방향 Teams adapter (Bot Framework messaging).
  - `slack_bot.py` - pull-방향 Slack adapter (Socket Mode).
  - `web_chat.py` - read-console API 가 노출하는 WebSocket adapter.
- [`tools/chat.py`](../../tools/chat.py) - CLI 엔트리 포인트.

CSP-중립 규칙은 그대로 유지: `core/conversation/` 은 **오직** Protocol 만
import. 모든 Azure SDK / httpx / Bot Framework 호출은 `delivery/` 아래
거주.

## 3. Tool 카탈로그

Tool 은 **pipeline-stage view** 이다. 각각 안정된 이름, 인자에 대한 JSON
Schema (등록 시 함수 시그니처로부터 생성), RBAC 하한, 문서화된 실패
surface 를 가진다. 새 tool 은 additive; 룰이나 정책을 절대 override 하지
않음.

### 3.1 Day-1 tool 집합 (read-only + explain)

| Tool | 목적 | RBAC 하한 | Delegates to |
|------|---------|-----------|--------------|
| `describe_event(payload)` | 하나의 이벤트를 `EventIngest → TrustRouter → T0Engine` 로 in-memory 실행 (PR 없음, audit write 없음); 결과 routing 결정 + 후보 룰 id 반환. | Reader | `EventIngest`, `TrustRouter`, `T0Engine` |
| `explain_verdict(event_id)` | 이미 처리된 이벤트의 audit trail 을 읽어; tier, decision, citing 룰 id, verifier 리포트, mode 반환. | Reader | `StateStore.query_audit()` |
| `explore_catalog(query)` | Shipped rule 카탈로그 / action-type 카탈로그 / ontology 어휘를 id, keyword, 또는 resource_type 으로 검색. | Reader | 로딩된 카탈로그 (I/O 없음) |
| `query_audit(filters)` | 구조화된 audit query: event id, actor, decision, mode, 시간 window 별. Paginate. | Reader | `StateStore.query_audit()` |
| `query_inventory(resource_type, filter)` | ARG-backed inventory query, CSP-중립 어휘 in, CSP-중립 record out. Paginate. | Reader | `Inventory.list(...)` |

### 3.2 Week-1 추가 (write / approve / runbook)

| Tool | 목적 | RBAC 하한 | 참고 |
|------|---------|-----------|-------|
| `simulate_change(scenario)` | End-to-end `ControlLoop.process()` 를 **shadow** mode 로; publish 없이 executor outcome + 생성된 PR intent 반환. | Contributor | Shadow-only; 여전히 audit entry 를 남김 → 오퍼레이터가 `query_audit` 로 찾을 수 있음. |
| `approve_hil(approval_id, decision, justification)` | 큐잉된 HIL item 하나 해결. Verifier + `no_self_approval` invariant 재확인. | Approver | Approver 그룹; [security-and-identity.md](security-and-identity-ko.md) 의 PR gate enforcement 와 동일 principal. |
| `list_hil()` | 호출자의 role 에 visible 한 현재 큐잉된 HIL item 반환. | Approver | Reader-visible 은 non-approver 에게 intent 를 leak; Approver-scoped 유지. |
| `run_runbook(name, params, dry_run)` | `docs/runbooks/` 아래 하나의 runbook 실행. `dry_run=true` 는 Contributor 요구; `dry_run=false` 는 Owner 요구. | Contributor / Owner | 구체 runbook adapter (예: `db_dr_drill_cli`) 는 이미 shipping; 이 tool 은 이름으로 route. |
| `activate_break_glass(reason, expiry)` | 현재 세션을 BreakGlass 로 명시적 promote. Time-boxed, role gate 와 별개, 항상 audit + Owner 에게 페이지. | 인증된 아무 사용자 | Session-scoped 만; 세션 종료 또는 `expiry` 만료시 revoke. 영구 grant 없음. |

### 3.3 Month-1 추가 (관찰 depth)

| Tool | 목적 | RBAC 하한 | 의존 |
|------|---------|-----------|-------------|
| `query_log(query, window)` | Log Analytics KQL query. | Reader | 신규 `AzureMonitorAdapter` |
| `query_metric(namespace, metric, window, aggregation)` | Azure Monitor metrics API. | Reader | 신규 `AzureMonitorAdapter` |
| `query_deployments(window)` | Git + ARM deployment-history join. | Reader | 신규 `DeploymentHistoryAdapter` |
| `correlate_incident(incident_id)` | 하나의 incident id 에 대해 ingest event + audit + inventory + log + metric 을 multi-signal correlate. | Reader | 위 셋 + `event_ingest` |

Month-1 추가는 콘솔을 Azure SRE Agent 의 "Autonomous Incident Response"
서사에 가깝게 만드는 양보 — 하지만 여전히 **이미 correlate 된** 결과를
surface; correlator 는 Layer 1 에 살고, narrator 안에 살지 않는다.

### 3.4 Tool discovery 계약

각 tool 은 다음을 선언:

- `name` - CLI-friendly snake_case verb (`describe-*` / `explore-*`
  접두사 taxonomy 없음; verb 자체가 카테고리).
- `description` - 한 문장, 영어, 마케팅 언어 없음.
- `parameters` - 타이핑된 `TypedDict` / dataclass 로부터 생성된 JSON
  Schema; 유효성 검증은 경계에서 강제 (유효하지 않은 인자 → HTTP-400
  모양 error, partial call 절대 아님).
- `rbac_floor` - tool 을 호출 MAY 하는 가장 낮은 role.
- `side_effect_class` - `read` / `simulate` / `approve` / `execute` /
  `breakglass`. Audit entry 가 이 class 를 carry 하므로 downstream
  analytics 가 저렴하게 slice.
- `failure_modes` - tool 의 docstring 에 문서화된 타입화된 error surface.

관리용 `list_tools()` call 은 스키마를 반환; narrator 는 LLM function-
calling 계약을 통해 같은 스키마를 받음.

## 4. Narrator - LLM tier 모델

Narrator 는 콘솔의 LLM layer. DI seam (`ConversationalModel` Protocol; §5.1
참조) 이므로 fork 가 provider swap. Upstream 은 deployed
`oai-aiopspilot-dev-krc` account 에 Azure OpenAI 를 바인딩.

### 4.1 세 tier (trust router 를 반영)

| Tier | 모델 | 처리 | 기본? |
|------|-------|---------|----------|
| **Chat T0** | 없음 (regex / keyword intent) | Direct-hit tool call: `list_hil`, `explain_verdict <id>`, `explore_catalog <keyword>`. | Yes (T0 intent 가 configured threshold 이상 신뢰도로 매치하면 LLM 미호출) |
| **Chat T1** | `t1.judge` (mini reasoner) | 표준 turn: 자연어 ↔ tool_call, 대부분의 read-only investigation, one-hop follow-up. | **Yes (mini always active)** |
| **Chat T2** | `t2.reasoner.primary` (frontier) | Escalation 만 (§4.2 참조). | No (escalation trigger 로 opt-in) |

### 4.2 Escalation trigger (T1 → T2)

Coordinator 는 다음 중 하나라도 발생하면 Chat T2 로 escalate:

- Narrator 의 T1 응답이 `finish_reason=abstain` 또는 aggregated 신뢰도
  (verifier-derived, model-self-reported 아님) 가 configured threshold 아래.
- Verifier 가 제안된 tool_call 시퀀스를 reject (§7 참조).
- 요청된 tool 이 `simulate_change`, `approve_hil`, `run_runbook`, 또는
  `activate_break_glass` **이고** turn 이 인자 resolve 를 위해 1 tool hop
  이상 요구.
- 현재 세션의 multi-turn hop 수가 configured limit (기본 5) 초과 —
  intent 가 novel 이라는 시그널.
- 사용자가 명시적으로 더 깊은 분석 요청 (자연어 marker 패턴,
  configurable).

Escalation 은 **세션 당 one-way**: 세션이 T2 로 escalate 하면 같은 turn 의
연장은 T2 에 머무르지만 다음 turn 은 다시 T1 에서 시작. Audit entry 는
`tier`, `escalation_trigger`, 그리고 escalate 를 트리거한 T1 output 을
기록.

### 4.3 Narrator 가 하면 안 되는 것

- **Execution eligibility 를 주장.** 오직 verifier 만 (§7).
- **RBAC gate 를 우회.** Coordinator 는 narrator 를 호출하기 **전에** 하한을
  적용하므로, 모델에 넘겨진 tool 스키마는 호출 가능한 tool 만 포함.
- **Audit log 를 직접 읽음.** Narrator 는 tool 결과가 제공하는 것만 봄;
  audit store 는 Protocol seam 뒤에.
- **Coordinator 가 tool call 로 취급할 자연어 "명령" 을 emit.** 모델의
  function-calling 응답으로부터 구조화된 `tool_calls` 만 count. Prose 는
  prose; 실행되지 않음.

### 4.4 Cost 와 rate limit

D12 에 따라: mini (t1.judge) 는 항상 켜져 있고 오퍼레이터 budget 가정은
이것이 normal-cost surface 라는 것. Upstream 기본에는 **사용자당 rate limit
없음** 그리고 **turn 당 token cap 없음**; fork 는 config 를 통해 추가 MAY.
매 LLM 호출은 tier, model deployment id, prompt/completion token count 를
audit log 에 기록하므로 fork 는 콘솔을 추가로 계측하지 않고도 cost 리포트
를 post-hoc 로 빌드 가능.

## 5. DI seam

모든 seam 은 Protocol; composition root 가 구체 구현을 wire. `core/` 는
Protocol 만 import
([coding-conventions.instructions.md § Provider Protocols](../../.github/instructions/coding-conventions.instructions.md#safety)).

### 5.1 `ConversationalModel`

```python
class ConversationalModel(Protocol):
    async def turn(
        self,
        *,
        system_prompt: str,
        messages: Sequence[ChatMessage],
        tools_schema: Sequence[ToolSchema],
        tier: ChatTier,
    ) -> ConversationalResponse: ...
```

- `system_prompt` 는 coordinator 생성 시 narrator base prompt
  (`rule-catalog/prompts/narrator/base.vN.yaml`), RBAC-scoped tool 목록,
  그리고 calling principal 에 적용되는 operator-memory scope 로부터 한 번
  composition.
- `messages` 는 OpenAI 스타일 role/content shape 의 현재 세션 transcript.
  이전 tool_call 결과는 role `tool` 로 inline.
- `tools_schema` 는 coordinator 가 이미 RBAC 로 필터링한 JSON-Schema tool
  set.
- `tier` 는 `Chat T1` 또는 `Chat T2` 이며 adapter 내부의 모델 selection 을
  드라이브 (fork-specific).
- `ConversationalResponse` 는 `text`, 옵션 `tool_calls`, `finish_reason`,
  `confidence_signals`, audit-friendly metadata (`prompt_tokens`,
  `completion_tokens`, `model_deployment_id`) 를 carry.

Upstream 기본은
[`src/aiopspilot/delivery/azure/llm/conversational.py`](../../src/aiopspilot/delivery/azure/llm/conversational.py)
아래의 `AzureOpenAIConversationalModel` (Day 1 추가). Function-calling 계약
으로 Azure OpenAI chat completion 호출; model deployment 는
`resolved-models.json` 에서 선택 (tier T1 은 `t1.judge`, tier T2 는
`t2.reasoner.primary`).

### 5.2 `ConsoleTool`

```python
class ConsoleTool(Protocol):
    name: str
    description: str
    parameters: type[TypedDict]
    rbac_floor: Role
    side_effect_class: SideEffectClass

    async def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,
        session: ConversationSession,
    ) -> ToolResult: ...
```

- `call()` 은 **이미 validate 된** arguments mapping 을 받음 (validation 은
  coordinator 경계에서 `parameters` 스키마에 대해).
- `principal` 은 Layer-2 authenticated principal; `session` 은 이전 turn
  에 대한 read access 제공.
- `ToolResult` 는 `data` (serialisable), `preview` (narrator 가 요약하도록
  받는 짧은 human-readable string), 그리고 옵션 `evidence_refs` (audit id,
  PR url, ARG resource id — narrator 가 verbatim cite MUST) 를 가진
  타입화된 dataclass.

### 5.3 `ChannelAdapter`

```python
class ChannelAdapter(Protocol):
    channel_kind: ChannelKind
    async def receive(self) -> AsyncIterator[InboundTurn]: ...
    async def send(self, response: OutboundResponse) -> None: ...
```

- Wire 당 하나의 adapter (CLI, Teams Bot Framework, Slack Socket Mode,
  WebSocket).
- Push-방향 adapter
  ([channels-and-notifications.md](channels-and-notifications-ko.md)) 는
  pull adapter 와 **병합 안 됨**; config 를 통해서만 credential 공유. 이는
  `send-only` 와 `receive-plus-send` blast-radius 를 별개로 유지.

## 6. 세션 모델 + memory

`ConversationSession` 은 bounded 이고 in-memory 로는 stateless — 모든
상태는 세션 로드 시 **audit log 로부터 project** 되므로, coordinator 가
어느 node 에서든 crash 하고 recover 가능.

### 6.1 세션 필드

```python
@dataclass(frozen=True)
class ConversationSession:
    session_id: str                # UUID; first turn 시 생성
    principal_id: str              # Entra OID 또는 CLI principal id
    channel_id: str                # 채널 adapter 의 채널 식별자
    started_at: datetime
    break_glass: BreakGlassGrant | None  # 세션이 activate 했다면 (§7.3)
    turns: tuple[Turn, ...]        # audit log 로부터 project
```

- `Turn` = `{turn_id, role, content, tool_calls?, tool_results?, tier,
  audit_entry_id}`.
- `turns` 는 `query_audit(session_id=...)` 를 페이지하며 lazy 로드.

### 6.2 지속성 규칙

- **Day 1**: 매 turn (inbound + outbound + tool_call + tool_result + tier
  + escalation_trigger) 은 `action_kind=console.turn` 로 하나의 append-only
  audit entry 를 write. 신규 Postgres 테이블 없음.
- **Week 1**: `operator_memory` (parallel session 이
  [`src/aiopspilot/core/operator_memory/`](../../src/aiopspilot/core/operator_memory/)
  아래 이미 scaffolded) 가 **out-of-band 오퍼레이터 선호도** 의 store 가
  됨: "이 environment 는 항상 tag X 사용", "이 패턴은 발화 전 investigation
  을 위해 격리", "resource Y 는 legacy 예외". 콘솔은 Protocol seam 을 통해
  read-write; narrator memory 로는 절대 되지 않음.
- **Month 1+**: 세션들에 걸쳐 감지된 반복 investigation 패턴이
  discovery-loop 시그널이 됨 (§9). 여전히 narrator memory 아님 - 카탈로그의
  rule 후보가 결과 아티팩트.

### 6.3 의도적으로 저장하지 않는 것

- Narrator 의 raw generation trace, per-token log, 또는 오퍼레이터 prompt
  의 embedding 벡터. Audit entry 는 tool call 과 narrator 가 반환한
  *요약* 을 포함; 모델의 내부 chain 은 지속되지 않음.
- 채널 경계에서 redact 된 secret. Redactor 는 채널 adapter 에 살음
  ([channels-and-notifications.md § 8 - redaction](channels-and-notifications-ko.md#8-redaction) 과 동일 정책).

## 7. 안전 invariant (chat 은 이를 약화시키지 않음)

[coding-conventions.instructions.md § Safety](../../.github/instructions/coding-conventions.instructions.md#safety)
의 4 autonomy invariant 는 변경 없이 적용. Chat 은 그 위에 자체적으로 3개를
추가.

### 7.1 기존 4 invariant

매 write-class tool call (`simulate_change` in enforce mode - 오늘 허용
안 됨 -, `approve_hil`, `run_runbook --live`) 은 다음을 carry MUST:

1. **Stop-condition** - 기저 ActionType 이 이미 하나를 선언; 콘솔은 추가
   하거나 제거하지 않음.
2. **Rollback path** - ActionType 의 `rollback_contract` 재사용.
3. **Blast-radius limit** - ActionType 의 `blast_radius` 블록 재사용;
   오퍼레이터는 자연어로 이를 widen 할 수 없음.
4. **Audit entry** - tool 이 실제로 dispatch 하기 전에 coordinator 가
   write.

### 7.2 Chat 특화 3 invariant

5. **매 write-class tool call 에서 verifier re-check.** Narrator 가 write-
   class tool 을 겨냥하는 `tool_calls` frame 을 emit 한 후, coordinator 는
   tool 인자에 대해 T0Engine + policy-as-code check 를 재실행. Abstain /
   deny 시, tool call 은 drop 되고 turn 은 HIL 로 fall through (§7.4 참조).
   이것이 "LLM 은 execution eligibility 를 절대 부여하지 않는다" 뒤의
   mechanical guarantee.
6. **Chat-scoped no self-approval.** `approve_hil` 은 caller 의 Entra
   `oid` 가 큐잉된 item 에 recorded 된 requester 와 매치하면 caller 가
   Owner 를 holding 하고 있어도 refuse. PR gate
   ([security-and-identity.md](security-and-identity-ko.md)) 와 동일한
   invariant; chat 은 refuse 시 audit reason 에 invariant 이름을 추가.
7. **BreakGlass 는 time-boxed 이고 명시적이어야 함.**
   `activate_break_glass` 는 `(reason, expiry ≤ 4h)` 요구하고 configured
   Owner 모두에게 push-방향 Slack/Teams adapter
   ([channels-and-notifications.md](channels-and-notifications-ko.md)) 로
   페이지. Silent elevation 없음.

### 7.3 BreakGlass grant 형태

```python
@dataclass(frozen=True)
class BreakGlassGrant:
    activated_at: datetime
    expires_at: datetime           # <= activated_at + 4h
    reason: str                    # >= 20 자, secret 패턴 없음
    pager_receipt: str             # push 알림의 id
```

Break-glass 는 **세션-scoped**; 세션 종료가 이를 revoke. Fork 는 config 로
4h 상한을 낮출 MAY 하지만 올릴 MUST NOT.

### 7.4 LLM 이 write 를 제안할 때 HIL fall-through

Narrator 는 오퍼레이터가 "그냥 fix 해" 라고 말할 때
`run_runbook(dry_run=false)` 또는 `approve_hil` 을 위한 `tool_call` 을
emit MAY. Verifier re-check (invariant 5) 시:

- Verifier pass AND RBAC 충족 → tool call 진행.
- Verifier abstain 또는 RBAC 하한 미달 → coordinator 는 기존 HIL 큐에
  review item 을 file 하는 `enqueue_hil(...)` call 로 substitute 하고
  오퍼레이터에게 "HIL item id X 를 file 했어" 반환.
- 어떠한 상황에서도 dispatch 전 audit entry 없이 write 는 발생하지 않음.

## 8. 채널 통합 (push vs pull)

채널 추상화 ([channels-and-notifications.md](channels-and-notifications-ko.md))
는 이미 push (시스템 → 사람) 을 처리. 이 문서는 pull 방향 (사람 → 시스템)
을 push adapter 와 credential 및 채널 routing config 를 공유하는 **별개
adapter 집합** 으로 추가. 분리가 중요한 이유: trust posture 가 다름 - push
adapter 는 send-only credential; pull adapter 는 사용자 입력을 받을 수 있는
Bot Framework 세션 / Socket Mode 소켓을 유지.

| 채널 | Push (기존) | Pull (이 문서) | 공유 config |
|---------|-----------------|-----------------|---------------|
| Teams | `TeamsHilAdapter` (Incoming Webhook 또는 Bot Framework send 로 Adaptive Card) | `TeamsBotChannel` (Bot Framework receive + reply) | Tenant, 채널 id, app registration |
| Slack | `SlackWebhookChannel` (Incoming Webhook 로 Block Kit) | `SlackBotChannel` (Socket Mode receive + `chat.postMessage` reply) | Workspace, 채널 id, app credential |
| Email | send-only | (계획 없음; 비동기, 인터랙티브에 부적합) | n/a |
| Webhook | send-only | (계획 없음; 호출자가 인터랙티브 protocol 을 자체 소유해야) | n/a |
| Pager (PagerDuty) | send-only | (계획 없음) | n/a |
| SMS | send-only | (계획 없음) | n/a |
| Web chat | n/a | `WebChatChannel` (read-console 상 WebSocket) | Console SPA config |
| CLI | n/a | `CliReplChannel` (stdin/stdout) | local az login |

### 8.1 동일한 채널 routing config

Fork 는
[`config/notifications-matrix.yaml`](../../config/notifications-matrix.yaml)
에 채널을 한 번 등록하고 **양쪽** push 및 pull routing 을 그로부터 파생.
이는 [channels-and-notifications.md § 1](channels-and-notifications-ko.md#1-design-principles)
의 "one abstraction, many adapters" 규칙을 보존.

## 9. 성장 모델 (catalog + operator memory)

콘솔은 시간이 지남에 따라 세 가지 결정론적 mechanism 으로 나아진다.
모델-측 학습은 그 중 하나가 **아니다**.

### 9.1 Day 1

Day-1 콘솔은 답변 가능:

- "`example-rg` 의 `network.nsg` 에 어떤 룰이 적용되지?"
  → `query_inventory` + `explore_catalog`.
- "왜 event `<id>` 가 HIL 로 route 됐어?" → `explain_verdict`.
- "지난 24시간 `object-storage.public-access.deny` 의 모든 audit entry 를
  보여줘." → `query_audit`.
- "public access enabled 로 storage account 를 create 하면 loop 이 뭘
  할까?" → `describe_event`.

Write 없음, runbook 없음, approval 없음 - 오리엔테이션만.

### 9.2 Week 1

`simulate_change`, `approve_hil`, `run_runbook --dry-run`, Teams / Slack
pull adapter 추가. 콘솔은 이제:

- End-to-end 변경을 shadow 로 preview.
- PR flow 가 사용하는 것과 동일한 identity gate 로 큐잉된 HIL item 해결.
- 어느 채널에서든 shipped runbook ([docs/runbooks/](../runbooks/)) 을
  트리거.

### 9.3 Month 1

관찰 depth tool (§3.3) 과 discovery-loop hook 추가:

- 같은 tool-argument shape 이 rolling window 에서 구별되는 principal 을
  가로질러 N 번 나타날 때 coordinator 는 `console.recurrent_query` 시그널
  을 discovery-loop 입력 스트림에 publish (N 은 configured; 기본 5 / 주).
- Rule-candidate generator ([rule-governance.md](rule-governance-ko.md))
  가 여느 시그널처럼 그것을 받음; 결과 룰은 동일한 promotion pipeline 을
  통해 shadow-first 로 ship.

결과는 chat 의 common investigation 패턴이 카탈로그의 first-class 룰이 됨 -
**콘솔은 카탈로그를 성장시키지, 자신을 성장시키지 않는다**.

## 10. 단계별 rollout

각 phase 는 측정 가능하고 shadow-first 로 gate,
[phase-0-instrumentation.md](phases/phase-0-instrumentation-ko.md) 의 phase
규율에 매치.

### Day 1 (이 세션)

- `AzureCliWorkloadIdentity` (로컬 az login 을 위한 identity adapter).
- `ConversationalModel` Protocol + `AzureOpenAIConversationalModel`
  adapter.
- `ConversationCoordinator` + 5 Day-1 tool (§3.1).
- `CliReplChannel` + `tools/chat.py` 엔트리 포인트.
- Coordinator 는 매 turn 을 기존 audit log 에 write.
- **Exit gate**: Reader-role 오퍼레이터가 deployed `rg-aiopspilot-dev-krc`
  환경에 대해 CLI REPL 로부터 모든 Day-1 tool 시나리오를 완수 가능;
  unit test 는 RBAC gating, escalation trigger, verifier re-check
  invariant 를 커버.

### Week 1

- `simulate_change`, `approve_hil`, `list_hil`, `run_runbook`,
  `activate_break_glass` (§3.2).
- `TeamsBotChannel` 과 `SlackBotChannel` (pull adapter).
- Read-API approval callback endpoint (POST
  `/hil/{approval_id}/decision`, HMAC verified).
- Composition-root `default_workload_identity_from_env()` 가
  `ManagedIdentityWorkloadIdentity` (production Container Apps),
  `AzureCliWorkloadIdentity` (로컬 dev), `LocalWorkloadIdentity` (테스트)
  사이에서 pick.
- **Exit gate**: Teams 에서 Approver 가 deployed 환경에 대해 완전한 "detect
  → chat inspect → approve → shadow PR opens" 사이클을 완수 가능; audit
  log 는 매 turn, verdict, PR 링크를 carry.

### Month 1

- Month-1 관찰 tool (§3.3).
- 콘솔로부터 `operator_memory` read/write (Week 1 이 스키마를 landing;
  Month 1 이 이를 scope-bounded seam 으로 narrator 에게 노출).
- Discovery-loop hook (§9.3).
- Console SPA 상의 Web chat 채널.
- **Exit gate**: recurrent-query 시그널이 생성한 최소 하나의 룰 후보가
  shadow evaluation 을 완료했고 review 됨; Month-1 관찰 tool 은
  [`tests/delivery/azure/`](../../tests/delivery/azure/) 아래 실제 Azure
  Monitor / Log Analytics fixture 에 대해 unit + integration test 를 가짐.

## 11. Testability

- **Coordinator** - property test: "verifier re-check 는 매 write-class
  tool call 에서 실행", "RBAC 하한은 narrator 가 tool 스키마를 보기 전에
  강제됨", "audit entry 는 매 tool dispatch 를 선행", "escalation 은 tier
  와 trigger 를 기록".
- **Narrator adapter** - Azure OpenAI endpoint 용 `httpx.MockTransport` 를
  사용한 contract test; 결정론적 응답; tier selection 왕복 검증.
- **Tool** - 각 tool 은 `side_effect_class == read | simulate` 일 때 절대
  mutate 하지 않음을 보이는 shadow-mode test; `write` / `approve` test 는
  verifier re-check gate 를 보임.
- **Channel** - CLI REPL: golden transcript. Teams / Slack: Bot Framework
  / Socket Mode frame 용 MockTransport-equivalent 를 사용한 adapter test.
- **RBAC 매트릭스** - §3.1-§3.3 의 하한이 적용됨을 증명하는 모든 (Role ×
  Tool) 셀에 대한 table-driven test.
- **Break-glass** - `activate_break_glass` 가 `expiry > 4h` 를 refuse,
  세션 종료가 grant 를 revoke, Owner 알림이 발화됨을 증명하는 test.
- **결정론성** - 같은 CLI transcript 를 fake `ConversationalModel` 로 두
  번 실행하면 byte-identical audit trail 을 생성 (고정된 timestamp 와
  idempotency key 하에서).

## 12. 실패 모드

- **Narrator unavailable** - Chat T0 direct-hit 로 fall through; turn 이
  T0 패턴에 매치되지 않으면, canned "reasoning layer 가 일시적으로
  unavailable; 다음은 direct query surface" 로 응답하고 tool 목록 노출.
- **Write-class tool 에 verifier abstain** - `enqueue_hil(...)` 로
  substitute (§7.4 참조), HIL id 반환, audit reason `verifier_abstained`.
- **채널 adapter disconnect** - coordinator 는 audit trail 을 넘어서
  in-flight turn state 를 지속하지 않음; reconnect 는 session_id 로 세션
  재개.
- **Break-glass expiry mid-turn** - coordinator 는 elevated capability 를
  요구하는 다음 tool_call 을 refuse, "grant 만료됨, justification 과 함께
  `activate_break_glass` 재사용" 반환.
- **Tool 구현 raise** - tool 의 타입화된 error surface (§3.4) 가
  `ToolResult(status=error)` 로 wrap; narrator 는 exception traceback 이
  아닌 구조화된 error 를 봄.

## 13. 데이터 + wire 계약

### 13.1 Audit entry - `console.turn` action_kind

```json
{
  "action_kind": "console.turn",
  "session_id": "…",
  "turn_id": "…",
  "principal": {"kind": "user|cli|bot", "id": "…", "role": "Reader|…"},
  "channel": "cli|teams|slack|web",
  "direction": "inbound|outbound|tool_call|tool_result",
  "tier": "T0|T1|T2",
  "escalation_trigger": "…",
  "tool_name": "…",
  "arguments": {…},
  "result_preview": "…",
  "evidence_refs": ["…"],
  "verifier_verdict": "pass|abstain|deny|n/a",
  "model_deployment_id": "…",
  "prompt_tokens": 0,
  "completion_tokens": 0,
  "started_at": "…",
  "finished_at": "…"
}
```

### 13.2 CLI REPL wire 계약

- stdin: 한 줄에 하나의 오퍼레이터 발화.
- stdout: `--json` flag 설정 시 JSON-Lines; 그렇지 않으면 formatted text.
- stderr: coordinator log 라인 (구조화됨; 별개 stream 이므로 formatted
  view 는 clean 유지).
- Exit code: clean 세션 종료 시 `0`; 유효하지 않은 config 시 `2`; 복구
  불가능한 채널 error 시 `3`.

### 13.3 Read-API approval callback (Week 1)

- `POST /hil/{approval_id}/decision`
- Body: `{"decision": "approve|reject|defer", "justification": "…"}`
- Header: `X-AIOpsPilot-Signature: sha256=<hex>`,
  `X-AIOpsPilot-Timestamp: <RFC3339>`.
- Response: `200 {"queued": true, "audit_entry_id": "…"}`.

이것은 현재 read-API test 가 강제하는 "read API 는 3 GET route only"
invariant 에 대한 유일한 예외; invariant test 는 Week 1 landing 시
문서화된 allow-listed POST 를 얻음.

## 14. MCP - future work (Week 2+)

Upstream 콘솔은 Day 1 에 MCP server 를 ship 하지 **않음**. In-process tool
set 이 안정되고 RBAC 매트릭스가 exercised 되면, Week-2+ 추가는 동일한
tool 카탈로그 (`list_tools` / `call_tool`) 및 오퍼레이터 콘솔 read
리소스 (rule catalog, action types, runbook index) 를 MCP 리소스로
publish 하는 `src/aiopspilot/delivery/mcp/server.py` 의 MCP server
surface.

MCP layer 는 **additive**: 같은 coordinator 가 MCP-sourced tool call 을
CLI/Teams-sourced 것과 정확히 동일하게 처리, RBAC gate 는 identical 유지.
Fork 는 자기 재량으로 MCP server 를 external agent (Claude Code, Copilot
Chat, Azure SRE Agent 자체) 에게 expose MAY; upstream surface 는 wire
계약을 문서화하고 server process 를 ship 하지만 이를 publicly 하게
opening 하지 않음.

## 15. Open decisions (tracked)

- **OD-C1** - narrator prompt 카탈로그 이름: `rule-catalog/prompts/narrator/`
  vs `rule-catalog/prompts/console/`. Prompt composition 문서
  ([prompt-composition.md](prompt-composition-ko.md)) 의 Wave-N 을 blocking.
- **OD-C2** - operator_memory 스키마. Parallel session 이 소유;
  콘솔이 write 시작하기 전 Week 1 이 sign off.
- **OD-C3** - BreakGlass grant 를 위한 "self-approval" 정의 -
  active break-glass grant 가 no-self-approval invariant 를 더 강한 form
  (paired-approver only) 으로 reduce 하는지 여부. Owner: security-and-
  identity 문서 저자.
- **OD-C4** - CLI REPL history 파일 위치 및 retention. 기본 제안:
  `~/.aiopspilot/console-history.jsonl`, 10 MiB 로 cap, write 전 redact.
  Day 1 구현 blocking.

## 16. 관련 문서

- [architecture.instructions.md](../../.github/instructions/architecture.instructions.md) -
  trust routing, verifier authority.
- [channels-and-notifications.md](channels-and-notifications-ko.md) - 이
  문서의 pull 측이 확장하는 push-방향 채널 매트릭스.
- [user-rbac-and-identity.md](user-rbac-and-identity-ko.md) - tool 매트릭스
  (§3) 가 참조하는 RBAC role 집합.
- [security-and-identity.md](security-and-identity-ko.md) - no-self-
  approval, execution identity, 안전 invariant.
- [prompt-composition.md](prompt-composition-ko.md) - narrator prompt
  layering, tool-schema 노출, Month 1 이 소비 MAY 하는 debate
  orchestrator (Wave 4.5).
- [rule-governance.md](rule-governance-ko.md) - Month-1 콘솔이 feed 하는
  discovery loop.
- [project-structure.md § console/](project-structure-ko.md#console-static-web-app) -
  Month-1 web-chat 채널이 확장하는 read-only 콘솔 SPA.
