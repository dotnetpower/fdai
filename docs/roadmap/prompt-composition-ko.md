---
title: 진화하는 시스템 프롬프트
translation_of: prompt-composition.md
translation_source_sha: 485fe954a4208891c35918c9117f62586837579a
translation_revised: 2026-07-06
---

# 진화하는 시스템 프롬프트

T2 tier와 quality gate는 하드코딩된 단일 문자열이 아니라 **조립 가능한
catalog-as-code 프롬프트**를 소비합니다. 이 문서는 설계의 원본입니다. 레이어가 어떻게
조립되고, 각 아티팩트가 어디에 살며, composition root가 어떤 seam을 배선하고, 모델이
우리가 보낸 것을 실제로 읽었는지 어떻게 측정하는지를 다룹니다.
[llm-strategy-ko.md](llm-strategy-ko.md#t2---reasoning-tier-quality-gate-required)의
LLM 계약과
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md)의
trust routing을 확장합니다.

> **범위.** 업스트림은 범용 · Azure-first입니다. 웹 검색과 고객별 오버라이드는
> fork 전용 바인딩으로만 들어옵니다. 코어 저장소는 기본 비활성 fake를 배포하므로
> 포크는 명시적으로 opt-in해야 합니다
> ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).
>
> **상태.** Wave 1, 2, 2.5-A, 2.5-B step 1, 2.5-B step 2a, 2.5-B step
> 2b, 3 step A, 3 step B store, 3 step B pipeline slice 1, 3 step B
> pipeline slice 2, 3 step C-1, 3 step C-2, 3 step D-1, 3 step D-2a,
> 3 step D-2b-i, 3 step D-2b-ii-alpha, 3 step D-2b-ii-beta, 3 step
> D-2b-ii-gamma-1, 3 step D-2b-ii-gamma-2, 4 alpha, 4 beta-1, 4
> beta-2, 4.5 alpha, 4.5 beta, 4.5 gamma가 랜딩되었습니다 - operator
> memory가 end-to-end로 완전히 wire되고, recognition-probe 챕터가
> 완성되고, `AzureOpenAICrossCheckModel`이 event마다 재조립하고,
> Critic + Judge + `DebateOrchestrator` 트라이앵글이 shipped seam으로
> 존재하고 (타입 + evaluator + Azure 어댑터 + `max_rounds = 1`
> orchestrator), composition root가 `t2.critic` capability resolve 시
> Critic 어댑터를 바인딩합니다. Composer 체인은 Base + Task Skill Pack
> + 선택적 Tool Manifest + 선택적 Operator Memory + 선택적 레이어별
> canary token. dataclass fallback 기본값은 제거되었습니다.
> `system_prompt`는 `AzureOpenAICrossCheckModelConfig`의 required
> 필드이며 이제 composer가 wire되지 않은 경우의 startup-safety fallback
> 역할을 합니다. Wave 3 step B **파이프라인 slice 3** (fork-first
> second-approval 채널), Wave 4.5 **delta** (`t2.critic`과 `t1.judge`가
> 모두 resolve될 때 `DebateOrchestrator`를 live `QualityGate`에 wire),
> Wave 5 (fork 전용 웹 검색)은 여기 문서화되어 있지만 아직 구현되지
> 않았습니다. 모든 wave는 shadow gate를 통과해야만 승격됩니다.
> [Rollout waves](#rollout-waves) 참조.

## 한눈에 보는 설계

프롬프트는 코드 안의 리터럴이 아니라 **데이터**입니다. Composition root가 부팅 시
`rule-catalog/prompts/`에서 로드하고, capability로 인덱싱한 뒤, 해석된 body를
Azure OpenAI 어댑터에 넘깁니다. 런타임 레이어(rule-catalog citation,
operator memory 항목, tool output, web snippet, debate transcript)는 모두
`trusted="false"` XML 태그로 감싸져 모델이 이를 데이터로 취급하도록 합니다.
**결정론적 verifier가 유일한 실행 authority**로 남습니다 - 추가된 역할, 툴,
레이어는 모두 그 verifier를 위한 재료를 생산할 뿐, 우회로가 아닙니다.

## Role x layer 매트릭스

프롬프트는 두 축을 가집니다. **레이어**는 조립된 프롬프트를 구성하는 콘텐츠 타입이며,
**역할**은 어떤 base / pack / tool 집합이 적용될지 결정합니다. Wave 1은 reviewer
역할만 배포하며, 나머지는 미래 wave가 안정된 seam에 슬롯인할 수 있도록 선언만 되어
있습니다.

| Layer \\ Role | Proposer | Critic | Judge |
|--------------|----------|--------|-------|
| Base (역할 스켈레톤) | `base/t2-proposer.vN.yaml` | `base/t2-critic.vN.yaml` | `base/t2-judge.vN.yaml` |
| Task Skill Pack | `packs/<capability>.proposer.vN.yaml` | `packs/<capability>.critic.vN.yaml` | (보통 proposer pack과 공유) |
| Tool Manifest | tools + 선택적 `web.search` | tools(읽기 전용) | 없음 (Judge는 툴 호출 금지) |
| Domain Context (RAG) | rule / 과거 인시던트 인용 | 동일 | 동일 |
| Web Snippets | Proposer가 가져온 경우 | 읽기 전용 | 읽기 전용 |
| Operator Memory | scope 제한 | scope 제한 | scope 제한 |
| Debate Transcript | (첫 턴엔 비어 있음) | Proposer 출력 | Proposer + Critic 출력 |

현재 reviewer 역할은 2-model cross-check로 동작합니다(Wave 2는 이를 유지). Wave 4
가 Critic을 추가하고, Wave 4.5가 Proposer / Critic / Judge orchestrator로 승격합니다.
매트릭스가 이미 각 셀을 예약해 두어 이 추가가 리팩터를 요구하지 않습니다.

## 레이어 카탈로그

각 레이어는 고정된 역할과 고정된 저장 티어를 가집니다.

- **Base** - 짧고 불변인 역할 스켈레톤 (출력 계약, verifier-as-authority 리마인드,
  JSON-only 출력 규칙). Wave 1 목표: <= 128 토큰.
- **Task Skill Pack** - capability-scoped 지시 (예: RCA grounding, 액션 제안,
  novelty 분류). 각 pack은 capability가 참조할 수 있는 rule-catalog 항목을 인용합니다.
- **Tool Manifest** - 이 역할이 호출할 수 있는 툴의 부분집합. base 프롬프트 밖에서
  선언하는 이유는 base를 짧고 캐시 친화적으로 유지하기 위함입니다.
- **Domain Context (RAG)** - 이벤트별로 선택된 rule 발췌와 과거 인시던트 참조.
  프롬프트 옆에 영구 저장하지 않고, audit에는 인용된 id와 vector-hit 점수만 기록.
- **Web Snippets** - [Web search policy](#web-search-policy) 하에서만 가져옵니다.
  `<web_snippet trusted="false" url="..." hash="...">...</web_snippet>`로 wrap.
- **Operator Memory** - operator 피드백(HIL reject, override 사유,
  ChatOps preference, PR 리뷰)에서 나온 scope 제한, HIL-승인된 노트.
  절대 global 아님. [Operator memory pipeline](#operator-memory-pipeline) 참조.
- **Debate Transcript** - 이전 역할들의 출력이 다음 역할에게 읽기 전용 컨텍스트로 전달.

## 저장

### Catalog-as-code (git 추적)

```text
rule-catalog/
  prompts/
    schema/
      prompt.schema.json          # 모든 아티팩트가 검증되는 JSON Schema
    base/
      t2-cross-check.v1.yaml      # Wave 1 (배포됨)
      t2-proposer.vN.yaml         # Wave 3 (계획됨)
      t2-critic.vN.yaml           # Wave 4 (계획됨)
      t2-judge.vN.yaml            # Wave 4.5 (계획됨)
    packs/                        # Wave 2+
    tools/                        # Wave 2.5+
    roles/                        # Wave 3+
```

### 런타임 데이터 (Postgres, hash 주소 blob)

기존 state / audit 스키마 옆에 두 개의 새 테이블이 랜딩합니다. Append-only이며 hash로
주소되므로, replay가 외부 콘텐츠를 다시 fetch 하지 않습니다.

```sql
CREATE TABLE operator_memory (
  id            uuid PRIMARY KEY,
  scope_kind    text NOT NULL,     -- 'resource-group' | 'resource' | 'vertical'
  scope_ref     text NOT NULL,
  category      text NOT NULL,
  body          text NOT NULL,     -- 주입 시 <operator_note>로 wrap
  source_event  text NOT NULL,     -- 'hil.reject' | 'override.create' | ...
  source_ref    text NOT NULL,     -- audit id / PR url / message id
  author        text NOT NULL,
  approved_by   text NOT NULL,     -- self-approval 금지
  created_at    timestamptz NOT NULL,
  superseded_by uuid,
  ttl           interval
);

CREATE TABLE agent_transcript (
  id             uuid PRIMARY KEY,
  event_id       text NOT NULL,
  round          smallint NOT NULL,
  role           text NOT NULL,    -- 'proposer' | 'critic' | 'judge'
  model_id       text NOT NULL,
  prompt_hash    text NOT NULL,
  layer_manifest jsonb NOT NULL,   -- 정렬된 layer ref + version + token 수
  tool_calls     jsonb NOT NULL,
  response_hash  text NOT NULL,
  cost_usd       numeric NOT NULL,
  latency_ms     integer NOT NULL,
  created_at     timestamptz NOT NULL
);

CREATE TABLE web_evidence (
  content_hash    text PRIMARY KEY,
  url             text NOT NULL,
  fetched_at      timestamptz NOT NULL,
  intent          text NOT NULL,
  sanitized_text  text NOT NULL,
  injection_flags jsonb NOT NULL
);
```

Global scope의 operator memory는 write 시점에 거부됩니다 - 이 설계가 상속하는
[Human Override](../../.github/instructions/architecture.instructions.md#human-override)
정책 기준으로 너무 넓기 때문입니다.

## Provider protocols (DI seam)

코어는 Protocol 뒤에 남고, Azure 어댑터가 seam당 한 구현을 제공합니다. 이 설계가
도입하는 새 seam:

| Seam | 종류 | Wave | 역할 |
|------|------|------|------|
| `PromptRegistry` | sync | 1 (배포됨) | 프롬프트 YAML 로드 / 인덱스 |
| `PromptComposer` | async | 2 | 이벤트별 Role x Layer 조립 |
| `ToolRegistry` | sync | 2.5 | Tool YAML manifest 로드 |
| `ToolExecutor` | async | 2.5 | 모델이 발행한 tool call 디스패치 |
| `OperatorMemoryStore` | async | 3 | scope-bounded 노트 읽기 / append |
| `WebSearchProvider` | async | 5 | allowlist 뒤 outbound HTTP |
| `EvidenceStore` | async | 5 | hash-addressed 웹 스냅샷 저장 |
| `AgentTranscriptStore` | async | 4.5 | append-only debate 행 |
| `DebateOrchestrator` | async | 4.5 | Proposer -> Critic -> Judge 루프 |

I/O-bound seam은
[coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md#safety)
가 선언한 provider protocol의 async-by-default 규칙을 따릅니다.

## Tool use 서브시스템

툴은 rule catalog를 미러링한 catalog-as-code입니다. 각 YAML이 설명, 호출 스키마,
capability gate, allowlist, output wrapper를 선언합니다.

- **Capability별 allowlist**: capability의 `llm-registry` 엔트리가 Proposer /
  Critic이 호출할 수 있는 툴을 이름 짓습니다. tool manifest를 짧게 유지하여
  "lost in the middle" 실패 모드가 새어들지 않게 합니다.
- **Untrusted 출력**: 모든 tool 결과는 wrap되며
  (`<tool_result trusted="false" tool="..." ...>...</tool_result>`) 데이터로 취급.
  verifier와 policy 재검사가 authoritative로 남습니다.
- **Budget**: 각 툴은 `cost_budget_usd_per_call`을 선언하고, composer가 이벤트별
  상한을 강제. 초과 시 HIL로 abort.
- **Judge는 툴을 쥐지 않음**: judgment는 직무 분리입니다. 툴을 호출하는 Judge는
  두 번째 Proposer로 붕괴합니다.

## Web search 정책

Web search는 최후의 수단 툴입니다. fork별 opt-in이며 절대 grounding source가
아닙니다.

- **기본 off**: 업스트림은 no-op `WebSearchProvider`를 배포. fork가 API key와
  curated 도메인 allowlist를 제공하여 활성화합니다.
- **언제 실행 가능**: T2 케이스, novelty score가 threshold 초과, capability의
  tool allowlist가 `web.search`를 포함, 이벤트당 query / cost budget이 소진되지
  않음.
- **도메인 allowlist**: primary source만 (vendor docs, RFC, NVD, CVE 레지스트리).
  블로그, 포럼, 소셜 미디어는 금지.
- **Snippet 처리**: HTML strip. prompt-유사 패턴(`ignore previous`, `system:` 등)
  탐지 및 플래그. inject 전에 `<web_snippet trusted="false">...</web_snippet>`
  로 wrap.
- **Grounding source가 아님**: `cited_rule_ids`는 여전히 rule-catalog 항목으로
  해석되어야 합니다. 유용한 웹 발견은 rule-catalog discovery loop로 흘러가며,
  현재 이벤트의 grounding 요구를 만족시키지 않습니다.
- **Replay 결정성**: 결과는 `web_evidence`에 `(content_hash, url, fetched_at)`
  로 저장. audit 엔트리는 hash를 참조. Replay는 저장된 스냅샷을 읽으며 다시 fetch
  하지 않으므로 과거 실행이 재현 가능하게 유지됩니다.

## Debate orchestrator (Proposer / Critic / Judge)

Debate는 router가 요청할 때만 실행됩니다 - 보통 high-severity, high novelty,
또는 명시적인 operator-memory 지침. 기본 T2 경로는 여전히
[llm-strategy-ko.md](llm-strategy-ko.md)에 문서화된 2-model cross-check입니다.

```text
Proposer  -- candidate + citation + confidence
   |
   v
Critic    -- objection: [{severity, cited_rule_id, alt_action?}]
   |
   v
Judge     -- decision in {accept, revise_and_retry (<=1), escalate_hil}
   |
   +--> accept       -> 결정론적 verifier -> risk gate
   +--> revise       -> Proposer 1회 재시도 (total round <= 2)
   +--> escalate_hil -> 종료
```

이벤트당 하드 리밋: `debate.max_rounds <= 2`, `debate.max_wall_seconds`,
`debate.max_cost_usd`. 초과 시 HIL로 abort. Critic은 Proposer와 다른 publisher
모델이어야 합니다 (mixed-model distinctness 규칙 확장,
[llm-strategy-ko.md](llm-strategy-ko.md#t2---reasoning-tier-quality-gate-required)).
Judge는 더 작고 저렴한 모델이어도 됩니다.

Critic의 역할은 "다른 의견"이 아니라, 네 개의 안전 불변식(stop-condition, 롤백,
blast-radius, audit-log)에 대한 체크리스트 + citation validity + operator memory
와의 모순 여부입니다.

## Operator memory 파이프라인

Operator 피드백은 두 단계 gate를 거쳐 memory가 됩니다:

```text
HIL reject / approve reason -----\\
Override create / modify event  --+--> operator-memory 후보
ChatOps preference message      --|         |
PR review comment on rem PR     --/         v
                                     HIL 2차 승인 (self-approval 금지)
                                             |
                                             v
                                  operator_memory 행 (append-only)
```

- **Scope는 resource-group 이하여야 합니다.** 더 넓은 scope는 override가 아닌
  rule 변경이며, catalog pipeline을 통과해야 합니다.
- **주입 시 sanitize + wrap**: memory body는
  `<operator_note author="..." scope="..." trusted="false">...</operator_note>`
  태그 안으로 들어가며, base 프롬프트는 해당 태그 안의 지시를 따르는 것을
  금지합니다.
- **Discovery 신호**: 같은 rule에 대한 장기 override 또는 유사한 memory 행의 다수는
  rule-catalog discovery loop에 revision / retirement 후보로 흘러갑니다.

## 인식 측정

긴 프롬프트는 조용히 지시를 흘립니다. "모델이 우리가 보낸 것을 실제로 읽었는가"를
1급 KPI로 다루며, 프롬프트를 enforce로 승격하기 전에 gate합니다.

- **하드 토큰 예산** - composer가 조립된 프롬프트당 토큰을 추정. 초과 시 HIL로
  abort하고 `prompt.token_budget.exceeded_rate`를 증가. 우선순위가 낮은 레이어
  (가장 오래된 operator memory부터)는 감사에 보이는 이유와 함께 명시적으로 drop.
- **Canary 토큰** - composer가 태그된 레이어 마커
  (`<layer id="pack.rca.v3">...</layer>`)를 삽입. 역할들은 어느 레이어를
  인식했는지 보고. 인식되지 않은 고우선순위 레이어는 결함으로 surfacing.
- **Adherence rate** - JSON 스키마 위반, 필수 필드 누락, citation-rule-id
  validity를 매 프롬프트 버전 bump마다 고정 시나리오 세트에서 측정.
- **Position sensitivity** - 통제된 fixture가 동일한 지시를 base vs. pack
  vs. 끝에 배치하고 adherence를 비교. 특정 위치의 지속적 dip은 base 재작성
  신호.
- **Mixed-model agreement rate** - 기존 quality-gate disagreement rate를
  프롬프트 버전별로 추적하여 리그레션을 즉시 노출.
- **Debate economics** - debate orchestrator 랜딩 후
  `debate.rounds.p95`, `debate.cost_usd.p95`, `debate.timeout_to_hil_rate`,
  `critic.reversal_rate`를 추적.

승격 gate (초기값, capability별로 튜닝): `adherence >= 0.95`,
`citation_f1 >= 0.9`, `web.grounding_leak == 0`, `debate.timeout_to_hil_rate
<= 5%`, `critic.reversal_rate in [1%, 15%]`.

## 안전 불변식 (확장)

[coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md#safety)
의 8개 불변식에 이 설계 랜딩과 함께 6개가 추가됩니다:

1. Web-search 출력은 **절대** `cited_rule_id`가 아님.
2. Tool 결과와 web snippet은 **항상** `trusted="false"` XML로 wrap.
3. Debate 루프는 하드 `max_rounds`, `max_wall_seconds`, `max_cost_usd`
   상한을 가지며, 초과 시 HIL로 abort.
4. Critic과 Proposer의 publisher는 **달라야** 하며, 같은 publisher 쌍은 단일
   voter로 붕괴함.
5. Judge는 툴을 호출**해서는 안 됨**. Judgment와 generation은 분리.
6. Web evidence는 hash 주소 immutable이며, replay는 스냅샷을 읽고 다시 fetch
   하지 않음.

## Rollout waves

모든 wave는 shadow first로 랜딩. 승격은 이전 wave의 승격 gate가 유지되어야 함.

| Wave | Deliverable | 배포됨 |
|------|-------------|--------|
| 1 | Base 프롬프트 catalog 외부화 + `PromptRegistry` + composition 배선 | yes |
| 2 | `PromptComposer` async Protocol + `DefaultPromptComposer` (Base + Task Pack) + `ComposedPrompt` / `LayerRef` 인식 프리미티브 + `AzureOpenAICrossCheckModelConfig`의 `system_prompt` required 전환 | yes |
| 2.5-A | `DefaultPromptComposer`의 shadow-vs-enforce 필터 + 배포된 shadow 모드 task pack + `tool.schema.json` + `FileSystemToolRegistry` | yes |
| 2.5-B step 1 | Composer가 선택적 Tool Manifest 레이어 emit + 배포된 shadow 모드 tool YAML (`rule.query` / `state.query` / `audit.query`) + `trusted="false"` 래퍼 강제 | yes |
| 2.5-B step 2a | Async `ToolExecutor` + `ToolProvider` seam + 스키마 검증, shadow guard, 래퍼 강제, 5개의 typed fail-closed 에러 (`UnknownToolError`, `ShadowToolBlockedError`, `ToolArgumentValidationError`, `MissingProviderError`, `ProviderCallError`)를 가진 `DefaultToolExecutor` | yes |
| 2.5-B step 2b | `AzureOpenAICrossCheckModel`이 enforce 모드 tool에 대해 `tools=[...]`를 emit하고, bounded multi-turn 루프로 모델 발행 `tool_calls`를 executor로 라우팅하며, 알 수 없는 함수명 / 잘못된 arguments / half-wired 설정을 fail-closed로 거부 | yes |
| 3 step A | `core/operator_memory/` 타입 + async `OperatorMemoryStore` Protocol + `InMemoryOperatorMemoryStore` + `wrap_operator_note` / `detect_injection_markers` sanitizer + write 시점 정책 강제(scope <= resource-group, 서로 다른 approver, append-only supersede, 선택적 TTL, injection 마커 거부) | yes |
| 3 step B store | `PostgresOperatorMemoryStore` + alembic migration `20260706_0006_operator_memory` (append-only 테이블, Python 정책을 미러링한 CHECK 제약, `(scope_kind, scope_ref)` scope-lookup 인덱스, `InMemoryOperatorMemoryStore`와 TTL + supersede 시맨틱 parity, `AIOPSPILOT_DATABASE_URL` unset 시 스킵되는 integration test) | yes |
| 3 step B pipeline slice 1 | `HilResponse(decision=REJECT, reason=...)` + 별개의 `second_approver`를 주입된 `OperatorMemoryStore`를 통해 저장된 `OperatorMemoryEntry`로 변환하는 `HilRejectMaterializer` core 모듈; 5개의 pipeline-level 오류 코드 (`wrong_decision`, `empty_reason`, `missing_first_approver`, `missing_second_approver`, `same_principal`)가 store 접근 전에 fail-fast, store-side 정책 오류(duplicate id, injection marker)는 그대로 surface | yes |
| 3 step B pipeline slice 2 | Composition-root wire: `_build_operator_memory_store()`가 `AIOPSPILOT_OPERATOR_MEMORY_DSN`으로 Postgres를 선택하거나 기본값으로 in-memory fake를 사용하고, `_finalize_llm_bindings`가 store를 `DefaultPromptComposer`에 handoff하므로 operator-memory 레이어가 database 없이도 end-to-end로 도달 가능 (fork가 `HilRejectMaterializer`로 append한 entry가 즉시 composer에 보임) | yes |
| 3 step B pipeline slice 3 | 실제로 materializer를 invoke하는 second-approval 채널 (Teams Adaptive Card / git PR / fork-authored CLI). 승인 채널은 deployment마다 다르므로 fork-first 유지; upstream은 `HilRejectMaterializer` seam과 operator-memory store만 배포하고 특정 UI는 배포하지 않음 | 계획됨 |
| 3 step C-1 | `DefaultPromptComposer`가 선택적 `operator_memory_store` + `scope`를 받고 operator-memory 레이어를 emit. 각 entry는 `wrap_operator_note`로 wrap. 계층 해석은 resource-group note를 resource note 앞에 배치 | yes |
| 3 step C-2 | `AzureOpenAICrossCheckModel`이 startup 시 한 번이 아니라 per-event로 composer를 호출 (fork가 제공하는 선택적 `ScopeResolver`가 candidate에서 `OperatorScope`를 도출)하므로 operator memory가 실제로 모델에 도달 | yes |
| 3 step D-1 | Recognition-probe 프리미티브 (`RequiredField`, `ExpectedResponse`, `CitationScores`, `RecognitionResult`) + 순수 evaluator 함수 (`evaluate_adherence`, `evaluate_canary_echoes`, `evaluate_citations`, `score_recognition`) - `core/measurement/prompt_probe.py` | yes |
| 3 step D-2a | `CanaryGenerator` Protocol + `SecretsCanaryGenerator` / `DeterministicCanaryGenerator` + `ComposedPrompt.canary_tokens` 필드 + composer 레이어별 head-marker 주입 (`canary_generator=` 파라미터 opt-in. 기본값은 빈 mapping이므로 프로덕션 동작 무변화) | yes |
| 3 step D-2b-i | `RecognitionKpiSummary` dataclass + `summarize_recognition` aggregate (adherence pass rate, per-code violation counts, per-layer canary echo rate - measured denominator 사용, 스코어된 샘플만 대상으로 하는 citation F1 mean) | yes |
| 3 step D-2b-ii-alpha | `RecognitionScenario` / `RecognitionSample` / `RecognitionRunReport` + `ScenarioResponder` Protocol + `score_batch` (순수) + `run_scenarios` (composer + responder 오케스트레이션. composer canary가 자동으로 스코어링에 승격) | yes |
| 3 step D-2b-ii-beta | `rule-catalog/prompts/scenarios/` scaffold + `scenario.schema.json` + `load_scenarios(catalog_root)` 파일시스템 로더 (aggregate-error surface, 파일명 `<id>.v<version>.yaml`, 빈 catalog 합법) | yes |
| 3 step D-2b-ii-gamma-1 | `emit_kpi_rows(report)` target-neutral KPI row emitter + `KpiRow` / `RowUnit` 타입 + 안정된 metric 이름 상수 (`prompt.recognition.*`) | yes |
| 3 step D-2b-ii-gamma-2 | recognition metric 이름에 wire된 CLI runner + 대시보드 panel | 계획됨 |
| 4 alpha | Critic role 스캐폴딩: `CriticStance` / `CriticSeverity` / `CriticObjection` / `CriticOutput` / `CriticVerdict` 타입 + `CriticModel` Protocol + `evaluate_critic_output()` 순수 evaluator + `rule-catalog/prompts/base/t2-critic.v1.yaml` (`default_mode: shadow`, `applies_to: [t2.critic]`). QualityGate에 live wire 없음; Wave 4.5가 debate orchestrator를 랜딩할 때까지 dormant | yes |
| 4 beta-1 | `AzureOpenAICriticModel` httpx 어댑터가 Azure OpenAI ``chat/completions`` structured JSON output을 통해 `CriticModel` Protocol을 구현; strict fail-closed 파서 (unknown stance / severity / 누락 필드 / non-string citation / blank description 모두 raise). 아직 composition root에 wire되지 않음 - 배포된 catalog seed는 `default_mode: shadow` 유지 | yes |
| 4 beta-2 | `rule-catalog/llm-registry.yaml`에 `t2.critic` capability를 추가 (`invocation: on_disagreement`, Anthropic-first preference로 Proposer와 publisher 구분). `LlmBindings`가 선택적 `critic_model` 필드를 갖고, `bind_azure_llm_bindings`가 capability resolve + `critic_system_prompt` 공급 모두 만족될 때 `AzureOpenAICriticModel`을 바인딩. Startup 로그에 `critic_prompt_composed` 구조화 엔트리 추가 | yes |
| 4.5 alpha | Judge role 스캐폴딩: `JudgeDecision` / `JudgeOutput` / `JudgeVerdict` 타입 + `JudgeModel` Protocol + `evaluate_judge_output()` 순수 evaluator + `rule-catalog/prompts/base/t2-judge.v1.yaml` (`default_mode: shadow`, `applies_to: [t1.judge]`). Debate orchestrator 설계에 따라 Judge는 smaller / cheaper 모델 유지 | yes |
| 4.5 beta | `AzureOpenAIJudgeModel` httpx 어댑터가 `JudgeModel` Protocol을 구현; Critic 어댑터와 동일한 shape의 strict fail-closed 파서 | yes |
| 4.5 gamma | `DebateOrchestrator` core 모듈이 `max_rounds = 1`로 Proposer / Critic / Judge를 orchestration; 모든 어댑터 예외에 fail-closed (`error_class`가 보존된 `DebateVerdict.ABORT` 반환), audit log용 debate transcript를 `DebateOutcome`에 보존, Critic이 이미 ABORT하면 Judge를 short-circuit (token-cost 보호) | yes |
| 5 | Fork별 web search opt-in (업스트림은 no-op provider. enforce에는 injection detection 필요) | 계획됨 |

## Wave 1 - 무엇이 배포되었나

Wave 1은 런타임 행동을 바꾸지 않은 채 seam을 도입합니다.

- `rule-catalog/prompts/schema/prompt.schema.json` - 프롬프트 아티팩트용 JSON
  Schema.
- `rule-catalog/prompts/base/t2-cross-check.v1.yaml` - 추출된 T2 base 프롬프트.
- `src/aiopspilot/core/prompts/` - `PromptRegistry` Protocol,
  `FileSystemPromptRegistry` 구현, aggregate-error 검증.
- `bind_azure_llm_bindings`가 선택적 `system_prompt`를 받아 모든 cross-check
  config에 스레딩.
- `__main__._finalize_llm_bindings`가 `FileSystemPromptRegistry`를 통해 base
  프롬프트를 로드하여 전달.

## Wave 2 - 무엇이 배포되었나

Wave 2는 프롬프트 조립을 정식 composer로 승격하며 seam을 완성합니다.

- `src/aiopspilot/core/prompts/composer.py` - `PromptComposer` async Protocol
  + `DefaultPromptComposer` (Base + Task Skill Pack 조립).
- `src/aiopspilot/core/prompts/testing.py` - fork 테스트가 catalog를 건드리지
  않고 캔닝된 프롬프트를 주입할 수 있게 하는 `StaticPromptComposer` fake.
- `PromptRegistry.get_packs(capability_id)` - 특정 capability에 바인딩된 모든
  task-pack 아티팩트를 반환하며, id당 최고 버전만 유지.
- `ComposedPrompt` + `LayerRef` 타입이 정렬된 레이어 매니페스트와 레이어별
  토큰 추정치를 기록하여 향후 recognition-probe 측정을 위한 기반 제공.
- `AzureOpenAICrossCheckModelConfig.system_prompt`는 이제 필수 필드입니다.
  dataclass 기본값은 제거되었습니다. 빈 프롬프트는 생성 시 거부됩니다.
- `bind_azure_llm_bindings(..., system_prompt=)`가 required이며 두 T2
  reasoner config로 모두 전달되어 mixed-model cross-check가 동일한 지시
  컨텍스트를 보게 됩니다.
- `__main__._finalize_llm_bindings`가 `DefaultPromptComposer`를 생성하고
  `compose(capability_id="t2.reasoner.primary")`를 await한 뒤 어댑터를
  배선하기 전에 조립된 layer manifest를 로깅.

## Wave 2.5-A - 무엇이 배포되었나

Wave 2.5-A는 shadow 모드 필터와 tool-catalog 스캐폴딩을 추가합니다.
Tool 매니페스트 주입과 executor는 Wave 2.5-B에서 랜딩합니다.

- `DefaultPromptComposer(include_shadow_packs=False)`가 프로덕션 기본값.
  `default_mode: shadow`로 저작된 pack은 git에 있지만 승격되기 전까지 라이브
  프롬프트에 영향을 주지 않습니다. 평가 실행은 `include_shadow_packs=True`로
  opt-in.
- `rule-catalog/prompts/packs/t2-cross-check-output-contract.v1.yaml` -
  seam을 end-to-end로 증명하는 shipped shadow 모드 task pack. Wave 3의
  recognition probe가 도움을 확인하면 첫 `enforce` pack으로 승격 예정.
- `rule-catalog/prompts/tools/schema/tool.schema.json` - tool 아티팩트용
  JSON Schema. 모든 tool 설명은 registry가 파일을 받아들이기 전에 이를
  통과해야 합니다.
- `rule-catalog/prompts/tools/README.md` - prompts 서브시스템 README를
  미러링한 디렉토리 계약.
- `src/aiopspilot/core/tools/` (이전 `core/prompts/tool_registry.py`에서
  이관) - `ToolArtifact`, `CapabilityGate`, `ToolRegistry` Protocol,
  aggregate-error 검증을 가진 `FileSystemToolRegistry`. 빈 catalog가 에러
  없이 로드되므로 fork는 첫 tool을 저작하기 전에 seam을 채택할 수 있습니다.
  `output_wrapper`의 `trusted="false"` 불변식은 inject 시점이 아니라 load
  시점에 강제됩니다.

## Wave 2.5-B step 1 - 무엇이 배포되었나

Wave 2.5-B step 1은 아직 어떤 호출도 디스패치하지 않은 채 tool 설명을
composer에 스레딩합니다. Step 2가 executor와 OpenAI function-calling
파라미터를 wiring합니다.

- `DefaultPromptComposer(tool_registry=...)`가 선택적 `ToolRegistry`를
  받습니다. 제공되고 shadow 필터 이후 최소 하나의 tool이 eligible하면,
  composer가 조립된 프롬프트 끝에 synthetic `tool-manifest` 레이어를
  emit합니다. 없거나 비어 있으면 매니페스트 레이어가 추가되지 않습니다.
  모델은 "no tools" 표현을 절대 보지 않습니다.
- `include_shadow_tools=False`가 프로덕션 기본값. ``True``로 설정하면
  평가 실행에서 `include_shadow_packs=True`와 같은 방식으로 미러링됩니다.
- `rule-catalog/prompts/tools/catalog/`에 세 개의 shadow 모드 tool YAML이
  배포됩니다: `rule.query.v1.yaml`, `state.query.v1.yaml`,
  `audit.query.v1.yaml`. 각각 registry가 강제하는 `trusted="false"` output
  wrapper를 가집니다.
- 프롬프트 registry는 이제 `prompts/` 아래의 sibling subsystem을 skip합니다
  (현재는 `tools/`만). 따라서 `FileSystemPromptRegistry`가 tool YAML을
  malformed prompt fragment로 오해할 수 없습니다.

## Wave 2.5-B step 2a - 무엇이 배포되었나

Wave 2.5-B step 2a는 Azure OpenAI 어댑터를 아직 건드리지 않은 채로 tool
콜을 end-to-end로 dispatch할 수 있게 하는 executor seam을 도입합니다.
Step 2b가 모델 발행 `tool_calls`를 이 executor로 스레딩합니다.

- `src/aiopspilot/core/tools/executor.py` - `ToolExecutor` async Protocol
  + `DefaultToolExecutor` upstream 구현 + fork가 tool 그룹별로 구현하는
  `ToolProvider` seam. 모든 실패는 `ToolExecutorError`의 다섯 개
  typed 서브클래스 (`UnknownToolError`, `ShadowToolBlockedError`,
  `ToolArgumentValidationError`, `MissingProviderError`,
  `ProviderCallError`) 중 하나로 surfacing되어, 호출자가 부분 결과를
  삼키지 않고 HIL로 라우팅할 수 있습니다.
- `src/aiopspilot/core/tools/testing.py` - `InMemoryToolProvider`
  (tool id + 정렬된 arguments 튜플로 keying된 canned response, 호출
  기록 저장) 및 `NoOpToolProvider` (모든 호출 거부. fork가 provider
  wiring 없이 tool을 승격했을 때의 upstream 기본값).
- Dispatch 시점 fail-closed 보장:
  1. 알 수 없는 tool id -> `UnknownToolError`,
  2. `default_mode: shadow`이며 `allow_shadow_dispatch=False` ->
     `ShadowToolBlockedError` (composer의 manifest 레이어 필터
     뒤편의 belt-and-braces 방어),
  3. 아티팩트의 `input_schema` (`additionalProperties=False` 포함)를
     위반한 arguments -> `ToolArgumentValidationError`,
  4. 아티팩트가 declare한 `provider` 이름이 composition 시점에
     wiring되지 않음 -> `MissingProviderError`,
  5. provider가 raise -> `ProviderCallError` (원본 예외는
     `__cause__`에 보존).
- `ToolResult`는 `wrapped_text` (다음 턴에 주입 준비 완료), `raw`
  (감사 writer용), `cost_usd`, `latency_ms`를 기록하여 Wave 4.5의
  debate orchestrator가 이벤트별 예산을 강제할 수 있게 합니다.
- `core.prompts`와 `core.tools` 간 순환 import는 `TYPE_CHECKING`
  guard로 해소됩니다: `core.prompts.composer`는 런타임 tool
  registry를 duck typing으로 사용하므로 모듈 로드 시 `core.tools`
  import가 필요하지 않습니다.

## Wave 2.5-B step 2b - 무엇이 배포되었나

Wave 2.5-B step 2b는 executor를 Azure OpenAI cross-check 어댑터로
스레딩하여 모델 발행 tool 콜이 실제로 provider round-trip에 도달하게
합니다. 배포된 tool 세 개는 모두 `default_mode: shadow`이므로 upstream
기본 상태에서는 어댑터가 tools을 하나도 advertising 하지 않습니다.
프로덕션 동작은 fork가 실제 provider를 등록하고 tool을 승격하기 전까지
동일하게 유지됩니다.

- `AzureOpenAICrossCheckModel.__init__`이 선택적 `tool_registry` +
  `tool_executor`를 받습니다 (둘 다 또는 둘 다 없음. half-wired 설정은
  fail-fast). 어댑터는 생성 시점에 모든 enforce 모드 tool을 스냅샷하고
  OpenAI 호환 `tools=[...]` 배열을 한 번 빌드합니다. `propose()` 실행
  중에 manifest가 drift할 수 없습니다.
- `AzureOpenAICrossCheckModelConfig.max_tool_iterations` (기본 3)이 tool
  dispatch 루프를 바운드합니다. 0으로 설정하면 executor가 주입되어도
  tool 콜을 완전히 비활성화합니다. 양수 값을 설정하고 도달하면 더
  많은 토큰을 소모하지 않고 `RuntimeError`로 HIL에 abort합니다.
- `rule.query` 같은 tool id는 lossless dot-to-underscore 인코딩으로
  OpenAI 함수명이 됩니다. 역 lookup은 생성 시점에 registry 스냅샷에서
  구축된 맵을 사용하므로, 공격자가 underscored 형태를 추측하여 대체
  id를 밀어넣을 수 없습니다 (`delete_everything`은 맵에 없음 -> 거부).
- Multi-turn 루프는 assistant `tool_calls` 턴과 콜당 하나의
  `role: "tool"` 메시지를 보존하여 모델이 다음 라운드에 완전한
  컨텍스트를 갖게 합니다.
- 어댑터 boundary에서의 fail-closed 보장:
  1. 알 수 없는 함수명 -> `RuntimeError` (executor가 실행되기 전),
  2. executor wiring 없이 tool_calls -> `RuntimeError`,
  3. non-JSON arguments -> `RuntimeError`,
  4. `max_tool_iterations` 도달 -> `RuntimeError`,
  5. executor 실패는 그대로 전파되어 caller가 다섯 개의
     `ToolExecutorError` 서브클래스를 구분할 수 있게 합니다.
- `bind_azure_llm_bindings`가 선택적 `tool_registry` + `tool_executor`를
  받아 세 개의 cross-check 생성 사이트(hil-only primary, primary
  reasoner, secondary reasoner)에 모두 스레딩하므로 mixed-model
  cross-check가 동일한 tool manifest를 봅니다.
- `__main__._finalize_llm_bindings`가 azure 모드에서
  `FileSystemToolRegistry` + `DefaultToolExecutor(providers={})`를
  빌드합니다. Upstream은 의도적으로 빈 providers 맵으로 ship합니다:
  배포된 모든 tool이 shadow이므로 어댑터가 tools을 advertising하지 않고
  어떤 dispatch도 실행되지 않습니다. Fork가 자체 providers dict을
  제공하여 function calling을 활성화합니다.

## Wave 3 step A - 무엇이 배포되었나

Wave 3 step A는 HIL 파이프라인과 composer가 안정된 표면 위에 구축될
수 있도록 operator-memory seam을 도입합니다. Postgres store, HIL 2차
승인 워크플로우, composer 통합은 Wave 3의 후속 step에서 랜딩합니다.

- `src/aiopspilot/core/operator_memory/types.py` - `OperatorMemoryEntry`
  frozen dataclass + 세 개의 enum: `ScopeKind` (값은 `resource-group`과
  `resource`로 제한. 더 넓은 scope는 거부되는데, rule을 org 전역에서
  비활성화하는 것은 override가 아니라 rule 폐기이기 때문), `MemorySource`,
  `MemoryCategory`.
- `src/aiopspilot/core/operator_memory/store.py` - `OperatorMemoryStore`
  async Protocol + `InMemoryOperatorMemoryStore` upstream 기본값. 모든
  write는 동일한 정책 validator를 실행하므로, 호출자가 store를 직접
  건드려서 Human Override 계약을 우회할 수 없습니다. 정책 코드는
  `OperatorMemoryPolicyError.code`로 노출되어 구조화된 텔레메트리를
  가능하게 합니다 (`empty_body`, `empty_scope_ref`, `scope_too_wide`,
  `missing_author`, `missing_approver`, `self_approval`, `invalid_ttl`,
  `duplicate_id`, `already_superseded`).
- `src/aiopspilot/core/operator_memory/sanitizer.py` -
  `detect_injection_markers`가 body를 큐레이션된 prompt-injection 패턴
  목록에 대해 검사 (대소문자 무관. "ignore previous", "system:",
  role-hijack 토큰). `wrap_operator_note`가 accepted body를
  `<operator_note trusted="false" author="..." scope_kind="..."
  scope_ref="..." category="...">...</operator_note>` 안에 렌더링하며,
  모든 attribute와 content 위치는 XML-escape되므로 entry가 closing tag를
  위조하거나 새 attribute를 밀어넣을 수 없습니다.
- Append-only 시맨틱: store는 저장된 entry를 절대 mutate하지 않습니다.
  replacement는 자체 row를 가지고, `supersede(entry_id, superseded_by)`가
  pointer를 threading합니다. Double supersede는 `already_superseded`
  정책 코드로 거부됩니다.
- 장기 보존 entry(`ttl_seconds=None`)는 Human Override 정책에 따라
  허용됩니다. TTL 값은 제공되는 경우 양수여야 합니다.
- Write 경로가 composer 레이어보다 먼저 injection 방어를 강제하므로,
  악의적인 body는 storage에 도달조차 하지 못합니다. 리뷰어가 approval
  시점에 수정하거나 entry가 폐기됩니다.

## Wave 3 step B store - 무엇이 배포되었나

Wave 3 step B는 `OperatorMemoryStore`의 영속 Postgres 백엔드를
랜딩하여, scope-narrowed operator note가 프로세스 재시작을 견디고
composer가 모든 T2 event마다 조회할 수 있게 합니다. Step B의 나머지
절반(HIL reject로부터 `OperatorMemoryEntry` 행을 materialize하는 HIL
2차 승인 **파이프라인**)은 별도 후속 작업이며 rollout 표에서 아직
`계획됨`입니다.

- `alembic/versions/20260706_0006_operator_memory.py` - 단일 테이블
  `operator_memory`, Python 정책과 미러링된 CHECK 제약:
  `scope_kind IN ('resource-group', 'resource')`,
  `btrim(body) <> ''`, `btrim(scope_ref) <> ''`,
  `category IN (…)`, `ttl_seconds IS NULL OR ttl_seconds > 0`,
  `lower(btrim(author)) <> lower(btrim(approved_by))`. Python-side
  validator를 우회하는 caller도 리뷰되지 않은 또는 self-approved
  entry를 랜딩할 수 없습니다.
- `superseded_by`는 self-referential FK. Append-only invariant는
  `UPDATE ... SET body = ...`를 절대 issue하지 않음으로써 강제됩니다.
  유일한 UPDATE는 `FOR UPDATE`-locked 트랜잭션 내부의 `superseded_by`
  뿐이며, store는 pointer를 덮어쓰는 대신 `already_superseded`를
  반환합니다.
- `src/aiopspilot/delivery/persistence/postgres_operator_memory.py` -
  `PostgresOperatorMemoryStore`가 in-memory fake와 동일한 async
  `OperatorMemoryStore` Protocol을 realize합니다. DSN +
  `statement_timeout_ms` 계약은 `PostgresStateStore`와 동일하므로 두
  adapter를 같은 config 표면에서 wire할 수 있습니다.
- `append()`가 커넥션 열기 **전에** 공유 `_reject_policy_violations`를
  호출 - 정책 오류는 in-memory store와 동일한 코드
  (`empty_body`, `self_approval`, `invalid_ttl`, ...)의
  `OperatorMemoryPolicyError`로 surface. `id`의 PRIMARY-KEY collision은
  `duplicate_id` 코드로 번역되어 composer가 백엔드 전반에서 단일 오류
  taxonomy를 보게 됩니다.
- `list_active_for_scope()`가 superseded와 expired 행을 단일 SQL
  쿼리에서 필터링 -
  `NOW() - created_at < make_interval(secs => ttl_seconds)`,
  `_is_expired` 헬퍼의 시맨틱과 일치. Composer는 post-filter할 필요가
  없습니다.
- `_row_to_entry()`가 naive `datetime` 값을 UTC로 coerce하고 ISO-8601
  / UUID 문자열 컬럼을 방어적으로 파싱하여 JSON export/import 왕복이
  올바른 Python 타입에 landing.
- 통합 테스트(`tests/persistence/test_postgres_operator_memory.py`)는
  pgvector + state-store adapter와 동일한 `AIOPSPILOT_DATABASE_URL`
  unset 시 skip 패턴을 따르며, 라이브 Postgres에서 append + list +
  supersede + expiry + duplicate-id + unknown-id-lookup을 커버합니다.
  Offline 유닛 테스트는 config 검증, coerce 헬퍼, cross-backend 정책
  오류 parity를 exercise하므로 파일이 database 없이도 coverage를
  유지합니다.

## Wave 3 step B pipeline slice 1 - 무엇이 배포되었나

Wave 3 step B 파이프라인 slice 1은 HIL reject 이유를 두 번째 별개
operator가 승인한 후 저장된 `OperatorMemoryEntry`로 변환하는 순수
도메인 모듈을 랜딩합니다. 실제로 이를 invoke하는 HTTP / ChatOps
콜백은 후속 slice에 있습니다. 이 step은 "brain" - Teams Adaptive
Card 버튼, reconciler poll, fork-authored CLI 어느 것에서
트리거되든 동일 클래스가 2차 승인 로직을 처리합니다.

- `src/aiopspilot/core/operator_memory/hil_pipeline.py` -
  `HilRejectMaterializer(*, store, entry_id_fn=uuid4, now_fn=None)`가
  단일 async 메서드 `materialize(*, hil_response, second_approver,
  material)`를 노출합니다. 결정론적 훅 (`entry_id_fn`, `now_fn`)이
  전역을 monkey-patch하지 않고도 테스트에서 id와 timestamp를 pin할
  수 있게 합니다.
- `HilRejectMaterial(scope_kind, scope_ref, category, source_ref,
  ttl_seconds=None, metadata=...)`가 workflow가 공급하는 컨텍스트
  (ChatOps 명령, HTTP endpoint, reconciler poll)를 운반합니다.
  `source_ref`는 관례적으로 `hil.reject:<approval_id>`이며 감사자가
  entry를 정확한 HIL run으로 역추적할 수 있게 합니다.
- `HilMaterializationError`의 5개 fail-fast 오류 코드가 store 접근
  전에 short-circuit: `wrong_decision` (REJECT 아님),
  `empty_reason` (기억할 만한 콘텐츠 없음),
  `missing_first_approver` (`HilResponse.approver_id` 없음),
  `missing_second_approver` (reviewer 없음),
  `same_principal` (`strip().lower()` 정규화 후 rejecter가
  self-approve 시도). 마지막은 store의 `self_approval` 코드와
  의도적으로 구분되므로 UI가 "이 단계에서는 self-approve할 수
  없음"과 "store의 더 깊은 정책이 다른 이유로 거부"를 구별할 수
  있습니다.
- Store-side 정책 오류는 그대로 흐릅니다. Sanitizer가 이유에서
  prompt-injection marker를 감지하거나 caller의 `entry_id_fn`이
  duplicate id를 반환하면, store의 `OperatorMemoryPolicyError`
  (코드 `injection_marker_detected`, `duplicate_id` 등)가 caller에게
  보이는 것 - materializer는 이를 절대 삼키거나 re-code하지
  않습니다.
- `core/`-safe 유지: 모듈은 `aiopspilot.core.operator_memory`와
  `aiopspilot.shared.providers.hil_channel` (Protocol 패키지)에서만
  import하므로 `scripts/check-core-imports.sh`가 계속 통과합니다.
  `delivery.*` import 없음.

## Wave 3 step B pipeline slice 2 - 무엇이 배포되었나

Wave 3 step B 파이프라인 slice 2는 `OperatorMemoryStore`를 composition
root에 wire하여 operator-memory 레이어가 실제로 런타임에서 end-to-end로
도달 가능하도록 합니다. Slice 1이 `HilRejectMaterializer`를 배포했고
slice 3가 특정 second-approval 채널을 배포할 것입니다. 이 slice는
연결 조직 - 한 경로가 append한 entry가 다음 event에서 즉시 composer에
보이게 만듭니다.

- `src/aiopspilot/__main__.py`의 `_build_operator_memory_store()`가
  기존 `_build_audit_store()` 패턴을 미러링: `AIOPSPILOT_OPERATOR_MEMORY_DSN`
  (컨테이너의 Key Vault secret ref로 채워짐)이 설정되면 wire가
  `PostgresOperatorMemoryStore`를 반환하고, 그렇지 않으면 결정론적
  `InMemoryOperatorMemoryStore` fake가 사용되어 composer의
  operator-memory 레이어가 database 없이도 end-to-end로 완전히
  wire됩니다. Fork가 `HilRejectMaterializer`로 entry를 seed하면 다음
  `compose()` 호출에서 추가 배관 없이 레이어가 materialize되는 것을
  봅니다.
- `_finalize_llm_bindings()`가 이제 store를 생성하여
  `DefaultPromptComposer(registry=..., operator_memory_store=...)`에
  handoff합니다. Startup `prompt_composed` 구조화 로그가 concrete
  클래스 이름을 담은 `operator_memory_store` 필드를 얻으므로
  deployment가 로그를 grep하여 프로세스가 bind한 backend를 검증할 수
  있습니다.
- Backend 선택은 defense-in-depth: 빈 문자열 DSN은 "unset"으로 취급
  (`if dsn:`가 `""`에 대해 falsy)되므로 mis-quoted env var가 broken
  Postgres adapter를 instantiate하는 대신 in-memory fake로 fallback
  합니다. 테스트가 이 동작을 regression 방지로 pin합니다.
- `tests/test_main_helpers.py`의 세 개 offline 테스트가 각 env-var
  상태에 대해 헬퍼가 올바른 backend를 wire함을 증명합니다. Seam의
  composer 측은 이미 `tests/core/prompts/test_composer.py`가 커버하므로
  end-to-end wire는 composition으로 증명됩니다.

## Wave 3 step C-1 - 무엇이 배포되었나

Wave 3 step C-1은 delivery 어댑터를 아직 건드리지 않은 채 operator
memory를 composer에 스레딩합니다. Step C-2가 조립을 per-event 요청
경로로 이동시켜 실제로 note가 런타임에 모델에 도달하도록 합니다.

- `PromptLayer.OPERATOR_MEMORY` - composer의 memory 레이어가 사용하는
  새로운 synthetic layer 값. 프롬프트 아티팩트의 JSON Schema는 이 값을
  의도적으로 나열하지 않습니다: operator-memory 콘텐츠는 store에서
  materialize되는 데이터 레이어이지 YAML fragment로 저작되지 않습니다.
- `OperatorScope(resource_group_ref, resource_ref=None)` - composer가
  해석하는 튜플. ``None`` scope는 "이번 호출엔 operator memory 없음"을
  의미합니다. 프로덕션 per-event dispatch는 정규화된 event 페이로드에서
  가져온 실제 scope를 제공합니다.
- `DefaultPromptComposer(operator_memory_store=..., scope=...)`가 store를
  두 번 조회 (항상 RG 레벨, scope가 resource ref를 가진 경우 resource
  레벨도) 하고, resource-group note를 먼저 resource note를 나중에
  concatenate하여 가장 구체적인 지침이 사용자 턴에 가장 가까이
  위치하게 합니다.
- 조회된 각 entry는 `wrap_operator_note`로 wrap되어 `trusted="false"`
  invariant를 보존합니다. Superseded / expired entry는 store의
  `list_active_for_scope`가 필터링합니다. composer는 lifecycle 상태를
  재검사하지 않습니다.
- `StaticPromptComposer` (test fake)가 모든 호출에서 `(capability_id,
  scope)` 쌍을 추적하므로 테스트가 조립된 프롬프트를 검사하지 않고도
  composition 컨텍스트를 assert할 수 있습니다.
- Composer는 세 가지 명시적 경우에 **memory 레이어를 emit하지 않습니다**:
  1. `operator_memory_store`가 주입되지 않음,
  2. 호출 시점에 `scope`가 `None` (startup composition 경로),
  3. store가 해석된 scope에 대해 active entry를 0개 반환.

## Wave 3 step C-2 - 무엇이 배포되었나

Wave 3 step C-2는 프롬프트 조립을 startup-only에서 per-event로 이동시켜
operator memory 엔트리(fork가 제공하는 resolver 통해)와 canary 토큰이
모든 모델 호출에서 회전하도록 합니다. 이 변경은 additive입니다:
composer를 전달하지 않는 composition root는 이전처럼 정적
`config.system_prompt`를 계속 전송합니다.

- `AzureOpenAICrossCheckModel.__init__`이 세 개의 선택적 키워드 인자를
  갖게 됩니다: `prompt_composer`(`PromptComposer` 인스턴스),
  `capability_id`(composer에서 찾을 role 키),
  `scope_resolver`(`Callable[[QualityCandidate], OperatorScope | None]`).
- 생성 시점에 cross-consistency 강제: `prompt_composer`와
  `capability_id`는 함께 제공되어야 하며, `capability_id`는 비어있지
  않아야 하고, `scope_resolver`는 composer 없이 나타날 수 없음(먹일
  대상이 없는 resolver는 wiring 버그).
- `_resolve_system_prompt(candidate)`가 모든 `propose()` 턴에서 먼저
  호출됩니다. Composer가 wire되어 있으면
  `await composer.compose(capability_id=..., scope=resolver(candidate))`로
  재조립하고, 그렇지 않으면 `config.system_prompt` 스냅샷을 반환합니다.
- **Composer 실패는 `RuntimeError`를 raise합니다** (메시지에 capability
  id 포함). 이는 기존 quality-gate 에러 경로를 통해 실행을 HIL로
  라우팅합니다. Adapter는 절대 fallback 텍스트로 조용히 degrade하지
  않습니다 - 그러면 loop가 의존하는 operator memory나 fresh canary
  token 없이 stale prompt를 배송하게 됩니다.
- `bind_azure_llm_bindings`가 대응하는 `prompt_composer` +
  `scope_resolver` 매개변수를 갖고, 두 T2 reasoner를 각자의
  role-specific capability id (`t2.reasoner.primary` /
  `t2.reasoner.secondary`)로 생성합니다. Cross-check 정족수가 role별로
  일관된 instruction context를 보게 되며 단일 공유 프롬프트가 아닙니다.
- `__main__._finalize_llm_bindings`가 이제 upstream composer를
  `scope_resolver=None`으로 전달합니다. `QualityCandidate.target_resource_ref`를
  `OperatorScope`로 매핑하는 ARM-id 파서는 fork의 composition root에
  있습니다. Upstream 저장소는 CSP-neutral을 유지합니다.
- Startup `composer.compose(capability_id="t2.reasoner.primary")` 호출은
  유지됩니다: 프로세스 시작 시 catalog + schema를 검증하고
  observability용 `prompt_composed` 구조화 로그를 emit합니다. Live
  event에 대해 모델이 보는 `system_text`는 더 이상 이것이 아니어도
  마찬가지입니다.

## Wave 3 step D-1 - 무엇이 배포되었나

Wave 3 step D-1은 recognition-probe KPI의 순수 evaluator 부분을
랜딩합니다. Step D-2가 composer에게 레이어별 canary 토큰 삽입을
가르치고, 숫자를 시나리오 runner를 통해 대시보드에 wiring합니다.

- `src/aiopspilot/core/measurement/prompt_probe.py` - 네 개의 typed
  입력/출력 dataclass (`RequiredField`, `ExpectedResponse`,
  `CitationScores`, `RecognitionResult`)와 네 개의 순수 evaluator:
  `evaluate_adherence` (JSON 유효성 + 필드별 존재/타입/비-empty를
  구조화된 위반 코드로), `evaluate_canary_echoes` (raw 응답에 대한
  case-sensitive 부분 문자열 매칭. 소문자로 echo된 응답은 recognition
  으로 인정되지 않음), `evaluate_citations` (인용된 rule id 집합에
  대한 precision / recall / F1. 중복과 빈 문자열은 무시),
  `score_recognition` aggregate.
- 구조화된 위반 코드: `not-a-json-object`, `missing-field:X`,
  `wrong-type:X`, `empty-field:X`로 KPI 대시보드가 free text 정규식
  없이 bucketing 가능.
- Non-JSON 응답은 필드별 실패로 팬-아웃하지 않고 정확히 하나의
  `not-a-json-object` aggregate 위반만 보고 (같은 defect의 double
  counting은 KPI를 오염).
- `_extract_cited_ids`는 응답을 관대하게 읽습니다: 필드 누락,
  잘못된 타입, non-string 멤버는 모두 citation zero recall로
  surface될 뿐 raise되지 않음. Recognition probe는 절대 hard
  failure 소스로 변하지 않습니다.

## Wave 3 step D-2a - 무엇이 배포되었나

Wave 3 step D-2a는 조립된 각 레이어의 head에 canary 토큰을 배치하여
recognition probe의 canary-echo evaluator가 스코어링할 실제 marker를
갖게 합니다. Step D-2b가 그 토큰과 D-1 evaluator를 소비하는 시나리오
runner를 추가하여 대시보드 rows를 발행합니다.

- `CanaryGenerator` Protocol이 evaluator 옆
  `core/measurement/prompt_probe.py`에 위치합니다.
  `SecretsCanaryGenerator`는 프로덕션 unpredictability를 위해
  :mod:`secrets`를 사용. `DeterministicCanaryGenerator`는 test와
  replay run을 위해 미리 시드된 ``{layer_id: token}`` mapping을 받음.
- `ComposedPrompt.canary_tokens: Mapping[str, str]`가
  ``layer_id -> 주입된 token`` 쌍을 기록. 기본값은 빈 mapping이므로
  generator 없는 composer는 Wave 3 step C-1과 동일한 출력 shape을
  생성.
- `DefaultPromptComposer(canary_generator=...)`가 새 opt-in.
  주입 시 composer는 모든 레이어 body (base, task packs, tool
  manifest, operator memory) 앞에 ``[canary:<layer_id>=<TOKEN>]\n``를
  prepend하고, 각 `LayerRef.token_estimate`를 refresh하여
  manifest가 모델이 실제로 보는 것을 반영하게 함.
- 프로덕션 동작은 변경 없음: `__main__._finalize_llm_bindings`가
  canary generator를 넘기지 않으므로 현재 wire prompt는 pre-D-2a
  shape과 동일하게 유지됩니다.
- Canary 주입 후의 token estimate 업데이트가 recognition-probe KPI의
  첫 구체적 입력입니다. Post-canary token budget이 ceiling을 넘는
  레이어는 D-2b의 ``prompt.token_budget.exceeded_rate`` 시그널 후보.

## Wave 3 step D-2b-i - 무엇이 배포되었나

Wave 3 step D-2b-i는 배치의 per-sample `RecognitionResult` 값을
발행 가능한 하나의 요약으로 변환하는 KPI aggregate를 랜딩합니다.
Step D-2b-ii가 시나리오 fixture 형식, runner CLI, 실제 대시보드 row
emission을 추가합니다.

- `RecognitionKpiSummary` frozen dataclass가 설계 doc이 요구하는
  네 KPI를 담습니다: `adherence_pass_rate`, per-code
  `adherence_violation_counts`, `per_layer_canary_echo_rate`,
  `mean_citation_f1`.
- `summarize_recognition(results)`가 순수 aggregate 함수. 격리
  테스트 가능하며 결과가 어떻게 생성되었는지에 무관 - shadow 모드
  runner, 오프라인 fixture replay, CI 배치 모두 동일한 shape을 소비.
- **레이어별 측정된 분모**: 레이어의 echo rate는 실제로 그 레이어를
  측정한 샘플 수(그 id가 `canary_echoes`에 존재)로 계산되며 배치
  크기가 아닙니다. Capability의 절반만 exercise한 run이 모든 echo
  rate를 조용히 반으로 낮추지 못합니다.
- **Citation mean이 스코어되지 않은 샘플 제외**: 호출자가
  `expected_cited_rule_ids`를 넘기지 않은 샘플은
  `result.citations is None`이며 `mean_citation_f1`에서 제외됩니다.
  스코어된 샘플만 기여하므로 citation coverage가 non-scored run에
  의해 희석되지 않음.
- **빈 배치는 중립, 0이 아님**: 빈 결과 리스트는
  `mean_citation_f1 is None`인 요약을 반환하므로 대시보드 emitter가
  오해의 소지가 있는 0.0을 발행하는 대신 citation row를 skip.
- **측정 안 된 레이어는 나타나지 않음**: map은 "측정됨, 절대 echo
  안 됨"(rate 0.0)과 "전혀 측정 안 됨"(key 부재)을 명확히 구분하므로,
  `< 50% echo` alerting rule이 아무도 안 본 레이어에 대해 fire할 수
  없습니다.

## Wave 3 step D-2b-ii-alpha - 무엇이 배포되었나

Wave 3 step D-2b-ii-alpha는 배치 스코어링과 라이브 시나리오 실행을 위한
런타임 API를 전달합니다. Catalog-as-code YAML 형식, CLI, 대시보드
emission은 ``beta`` / ``gamma`` 서브 스텝에서 랜딩합니다.

- `src/aiopspilot/core/measurement/prompt_probe_runner.py` -
  `RecognitionSample` (composed prompt + response + expected),
  `RecognitionRunReport` (per-sample 결과 + KPI 요약을 한 번들에),
  `RecognitionScenario` (조립 가능한 spec: capability id + 선택적
  scope + expected 계약), `ScenarioResponder` async Protocol (fork가
  실제 모델을 wire. 테스트는 canned responder 제공).
- `score_batch(samples)`가 사전 조립된 배치를 리포트로 변환하는 순수
  aggregate. `sample.expected.canary_tokens`가 미설정이고 composer가
  `composed_prompt.canary_tokens`에 canary를 stamp한 경우, 스코어러가
  composer 토큰을 **자동 승격**합니다 - 시나리오 저자가 canary map을
  중복 정의하지 않으며, 두 shape 간의 drift가 구조적으로 불가능.
- 명시적 `expected.canary_tokens` 값은 auto-promotion을 override하여
  regression fixture가 composer가 변경되어도 원본 run의 토큰을 pin할
  수 있게 함.
- `run_scenarios(composer, responder, scenarios)`가 라이브 러너
  엔트리포인트. 시나리오별로 `capability_id` + `scope`로 조립하고,
  responder를 await한 뒤 `score_batch`로 위임. Scope는 그대로
  스레딩되므로 scope 바운드 operator-memory 레이어가 실제로
  recognition run에서 도달 가능.
- I/O provider와 YAML fixture는 아직 배포되지 않음 - upstream은
  런타임 seam을 순수하게 유지하여 fork 테스트가 Azure 의존성 없이
  어떤 composer와 responder로도 driver할 수 있게 합니다.

## Wave 3 step D-2b-ii-beta - 무엇이 배포되었나

Wave 3 step D-2b-ii-beta는 recognition-probe surface의 catalog-as-code
절반을 랜딩합니다: fork가 라이브 composer / responder와 독립적으로
저작 가능한 on-disk 시나리오 형식.

- `rule-catalog/prompts/scenarios/schema/scenario.schema.json` -
  모든 시나리오 YAML이 검증되는 JSON Schema. `capability_id`가
  required. `scope`는 선택적 (있으면 `resource_group_ref` 필수,
  `resource_ref` 선택적), `expected.required_fields`는 알려진
  `expected_type`(`string` / `object` / `array`)을 가진 field가 최소
  하나 필요.
- `rule-catalog/prompts/scenarios/README.md` - prompts + tools
  서브시스템 README를 미러링한 디렉토리 계약.
- `src/aiopspilot/core/measurement/prompt_probe_loader.py` -
  prompts와 tools registry와 동일한 aggregate-error surface를 가진
  `load_scenarios(catalog_root) -> tuple[RecognitionScenario, ...]`.
  빈 catalog가 legal이므로 fork는 첫 시나리오를 저작하기 전에 seam을
  채택 가능.
- `FileSystemPromptRegistry`가 이제 `tools/`와 `scenarios/` 두 peer
  서브시스템을 모두 skip하므로 시나리오 YAML이 실수로 prompt schema
  validator를 trip할 수 없음.

## Wave 3 step D-2b-ii-gamma-1 - 무엇이 배포되었나

Wave 3 step D-2b-ii-gamma-1은 `RecognitionRunReport`를 target-neutral
metric row 리스트로 변환하는 순수 KPI row emitter를 랜딩합니다. Step
gamma-2가 CLI를 wire하여 이 rows를 소비합니다.

- `src/aiopspilot/core/measurement/prompt_probe_emit.py` -
  `KpiRow(metric, value, unit, dimensions)` + `RowUnit` enum
  (`ratio`, `count`) + 5개 metric 이름 상수
  (`prompt.recognition.sample_count`,
  `prompt.recognition.adherence.pass_rate`,
  `prompt.recognition.adherence.violation_count`,
  `prompt.recognition.canary_echo_rate`,
  `prompt.recognition.citation_f1.mean`).
- `emit_kpi_rows(report, *, dimensions=None)`이 caller가 제공한 base
  dimension (예: `{"capability": "t2.reasoner.primary"}`)을 모든 emit
  row에 merge하므로 per-capability run이 sink에서 구별 가능한 row를
  publish.
- 테스트로 baked in된 emission 규칙:
  - **빈 배치**도 여전히 `sample_count = 0` emit - 항상 sample count를
    publish하는 대시보드 시리즈가 조용히 사라지지 않음;
  - **Adherence pass rate**는 `sample_count > 0`일 때만 emit
    (misleading `0/0` 회피);
  - **위반 count**는 code별 row 하나씩. `code`로 dimension되며
    알파벳 순으로 정렬되어 안정된 대시보드 순서를 producer;
  - **레이어별 echo rate**는 layer_id별 row 하나씩. aggregate의
    measured denominator 사용 → 배치의 절반만 측정된 레이어가
    조용히 dilute되지 않음;
  - **Citation F1**은 적어도 하나의 샘플이 스코어되었을 때만 emit
    (`mean_citation_f1 is not None`) - citation 스코어링 opt-out
    배치가 misleading `0.0`을 publish하지 않음.
- Metric 별 label (`code`, `layer_id`)이 metric family 간 절대 leak되지
  않음 - 각 row의 dimension set은 자신의 metric에만 scope됨.

## Wave 3 step D-2b-ii-gamma-2 - 무엇이 배포되었나

Wave 3 step D-2b-ii-gamma-2는 smoke-runnable CLI와 responder 헬퍼로
recognition-probe 챕터를 마무리합니다. Recognition metric 이름을
명명하는 대시보드 panel은 후속 문서 편집에서 P0 KPI dashboard와 함께
랜딩합니다. 이 step은 런타임에 집중합니다.

- `src/aiopspilot/core/measurement/prompt_probe_testing.py` -
  `AbstainResponder`는 매 호출마다 canned `hil.escalate` JSON action을
  반환하므로 upstream CLI가 live model 없이 smoke-run 가능하며,
  `RecordingResponder`는 queue에서 canned answer를 pop하면서
  `(capability_id, composed_system_text)` pair를 assertion용으로
  기록합니다.
- `AbstainResponder`는 construction 시점에 JSON body를 **한 번만**
  직렬화하므로 모든 `respond` 호출은 byte-identical text를 반환합니다.
  시간에 따라 응답을 비교하는 shadow run이 허위 variation을 보지
  않습니다.
- `src/aiopspilot/core/measurement/prompt_probe_cli.py` -
  `run_from_catalog(catalog_root, responder)`가
  `FileSystemPromptRegistry` + `DefaultPromptComposer`를 wire하고
  `load_scenarios(catalog_root)`를 호출한 후 `run_scenarios`에
  위임합니다. `main()`은 ``python -m
  aiopspilot.core.measurement.prompt_probe_cli`` 뒤의 sync entry point.
- CLI exit code는 기존 `runners_cli.py` 계약과 일치: ``0`` = run 완료
  (empty catalog도 legal outcome, `sample_count = 0` row 출력),
  ``2`` = catalog root 없음, ``3`` = stderr에 traceback을 남기는
  unexpected exception.
- 출력 shape: stdout에 라인당 JSON object 하나씩, key 정렬됨.
  `jq`/`awk`/observability pipeline이 추가 파싱 없이 바로 ingest 가능.
- CLI는 절대 Azure endpoint를 건드리지 않음. Fork가 live composition
  root에서 `run_from_catalog`를 import하고 실제 `ScenarioResponder`
  (Wave 2.5-B에서 만든 Azure OpenAI adapter를 wire하는)를 전달합니다.

## Wave 4 alpha - 무엇이 배포되었나

Wave 4 alpha는 Critic 역할의 typed shape와 shadow-mode 프롬프트 seed를
랜딩합니다 - live wiring 없는 Critic의 "brain". Wave 4 beta가 Azure
어댑터를 배포하고 Wave 4.5가 Proposer / Critic / Judge 루프를
orchestration합니다. 이 alpha step은 의도적으로 dormant이므로 타입 +
evaluator가 현재 T2 흐름에 위험 없이 fork-authored probe와 미래
orchestrator 코드에서 소비 가능합니다.

- `src/aiopspilot/core/quality_gate/critic.py` -
  `CriticStance` (`agree` / `challenge` / `abstain`),
  `CriticSeverity` (`low` / `medium` / `high`),
  `CriticObjection` (blank citation 또는 description을 거부하는
  `__post_init__`가 있는 frozen dataclass),
  `CriticOutput` (stance + objections + citations + `QualityCandidate`와
  동일한 "no model self-report" 계약을 따르는 선택적 confidence
  signals),
  `CriticVerdict` (`endorse` / `retry` / `abort` / `abstain`),
  그리고 `CriticModel` Protocol.
- `evaluate_critic_output(output, *, known_rule_ids)`가 하나의
  `CriticOutput`을 하나의 verdict로 reduce합니다. 테스트로 baked-in된
  규칙:
  - `ABSTAIN` stance는 `ABSTAIN` verdict로 short-circuit (objection
    검사 없음);
  - `AGREE` + 어떤 HIGH-severity objection이라도 있으면 `ABORT` -
    self-contradiction은 절대 honor하지 않음;
  - 그 외 `AGREE`는 `ENDORSE` (AGREE와 함께 있는 LOW-severity nit도
    여전히 endorsement);
  - 빈 objection 리스트를 가진 `CHALLENGE`는 `ABSTAIN` (증거 없는
    challenge는 defect);
  - unknown rule id를 인용하는 objection이 있는 `CHALLENGE`는
    `ABSTAIN` (ungrounded objection은 audit trail을 깨뜨림);
  - 어떤 HIGH-severity objection이라도 있는 `CHALLENGE`는 `ABORT`;
  - 그 외 `CHALLENGE`는 `RETRY`.
- `rule-catalog/prompts/base/t2-critic.v1.yaml` - `layer: critic`,
  `applies_to: [t2.critic]`, `default_mode: shadow`. Body가 evaluator가
  강제하는 structured JSON 계약(stance + grounded objections +
  citations)을 서술하므로 live Critic이 parseable output을 emit합니다.
  `t2.critic` capability는 아직 `llm-registry.yaml`에 없음; seed는
  Wave 4 beta가 capability를 추가하고 어댑터를 wire할 때까지 dormant.
- Critic은 이 alpha에서 `QualityGate`에 wire되지 않음. 결정론적
  verifier가 여전히 유일한 실행 authority; Critic은 (wire되면)
  orchestrator가 audit trail과 Wave 4.5 Proposer retry로 threading하는
  objection을 surface합니다.
- `core/`-safe 유지: 모듈은 `aiopspilot.core.quality_gate.gate`와
  stdlib에서만 import; `delivery.*` 또는 LLM SDK 없음.
  `scripts/check-core-imports.sh`가 74 files로 계속 통과합니다.

## Wave 4 beta-1 - 무엇이 배포되었나

Wave 4 beta-1은 Azure OpenAI를 상대로 실제 Critic 호출을 하는 Azure
어댑터를 랜딩합니다. 의도적으로 아직 composition root에 **wire하지
않음** - 배포된 `rule-catalog/prompts/base/t2-critic.v1.yaml` seed는
`default_mode: shadow` 유지이므로 실행 중인 배포는 동작 변화를 보지
않습니다. Wave 4 beta-2가 `llm-registry.yaml`에 `t2.critic` capability
엔트리를 추가하고 어댑터를 composition root로 threading합니다.

- `src/aiopspilot/delivery/azure/llm/critic.py` -
  `AzureOpenAICriticModelConfig` (endpoint, deployment, **required**
  `system_prompt`, api_version, temperature, max_tokens,
  timeout_seconds) + `AzureOpenAICriticModel`의 단일 async
  `critique(candidate, proposer_output)` 메서드가
  `response_format={"type": "json_object"}`로
  `/openai/deployments/{deployment}/chat/completions`에 POST합니다.
- Config 검증은 cross-check 어댑터의 fail-fast 계약을 미러링:
  non-https endpoint, empty deployment, empty system_prompt, zero /
  out-of-range temperature, zero max_tokens, zero timeout 모두
  생성 시점에 `ValueError`를 raise합니다.
- User-turn envelope에 candidate와 Proposer output이 canonical
  `(sort_keys=True)` JSON 모양으로 들어가 있어 replay와 audit가
  결정론적입니다.
- 응답 파서가 safety surface입니다. 모든 실패는 descriptive 메시지와
  함께 `RuntimeError`를 raise하므로 미래의 debate orchestrator가
  malformed critique를 조용히 accept하는 대신 HIL로 라우팅합니다:
  - non-string / empty `content`;
  - 유효한 JSON이 아닌 `content`;
  - non-object로 decode되는 `content`;
  - 누락 또는 non-string `stance`;
  - `CriticStance` enum 밖의 `stance`;
  - non-array `objections`;
  - objections 리스트의 non-object entry;
  - objection의 누락 / non-string `severity`;
  - `CriticSeverity` enum 밖의 `severity`;
  - non-string `cited_rule_id` / `description`;
  - non-string / non-null `alt_action_type` (빈 문자열은 `None`으로
    정규화되어 downstream 코드가 단일 "no alternate" 표현을 갖도록);
  - non-string / blank citation entry.
- `CriticObjection.__post_init__`가 두 번째 방어선 - 파서가 whitespace-
  only description을 놓쳐도 dataclass가 객체가 어댑터를 escape하기
  전에 `ValueError`를 raise합니다.
- `tests/delivery/azure/llm/test_critic.py`가 6개 config 검증 경로 +
  4개 성공 파싱 + 10개 fail-closed 파싱 + HTTP status 전파를
  커버합니다. `httpx.MockTransport`를 사용하므로 live network 불필요.
- `delivery/azure/llm/__init__.py`에서 cross-check 어댑터와 함께
  등록됨; beta-2가 랜딩될 때 composition root가 import할 준비 완료.

## Wave 4 beta-2 - 무엇이 배포되었나

Wave 4 beta-2는 Critic 어댑터를 opt-in 바인딩으로 composition root에
wire합니다. Registry에 `t2.critic` capability를 추가하지 않는 fork는
pre-Wave-4 shape 유지; capability를 resolve하는 fork는
`LlmBindings.critic_model`이 Wave 4.5 debate orchestrator를 위한 live
`AzureOpenAICriticModel`에 바인딩됩니다.

- `rule-catalog/llm-registry.yaml`에 `t2.critic` 엔트리 추가:
  `invocation: on_disagreement`와 Anthropic-first preference로 Critic
  publisher가 OpenAI-first Proposer와 구분되도록 (debate 설계 준수).
- `composition.LlmBindings`가 선택적 `critic_model` 필드
  (`CriticModel | None`)를 갖게 되어 Critic-off / Critic-on 경로에서
  seam surface가 uniform.
- `bind_azure_llm_bindings`가 선택적 `critic_system_prompt` 파라미터
  추가. Capability resolve와 prompt 공급 두 조건 모두 만족될 때만
  Critic 바인딩 - 부분 fork 구성 (capability 있지만 prompt 없음, 또는
  반대)이 절대 half-wired 어댑터를 landing하지 못함.
- `__main__._finalize_llm_bindings`가
  `composer.compose(capability_id="t2.critic")`으로 Critic system
  prompt를 조립. Catalog에 critic base prompt가 없어 compose가
  `LookupError`를 raise하면 wire가 `critic_model=None`으로 조용히
  degrade하고 `critic_prompt_missing` 구조화 로그를 emit하여
  deployment가 이유를 grep 가능. 성공 시 기존 `prompt_composed`
  엔트리와 함께 `critic_prompt_composed` emit.
- `tests/test_composition_llm.py`의 세 테스트가 three-way 매트릭스 pin:
  (capability + prompt) → 바인딩, (capability만) → None, (prompt만,
  capability 없음) → None.

## Wave 4.5 alpha - 무엇이 배포되었나

Wave 4.5 alpha는 Judge 역할의 typed shape와 shadow-mode 프롬프트
seed를 랜딩합니다 - Critic Wave 4 alpha slice를 미러링. Judge는
의도적으로 smaller 모델 (`t2.*`가 아닌 `t1.judge`에 바인딩) - debate
orchestrator 설계 준수; tier 하락이 Proposer / Critic 쌍이 비쌀 때도
Judge의 per-event 비용을 bound.

- `src/aiopspilot/core/quality_gate/judge.py` -
  `JudgeDecision` (`accept` / `revise_and_retry` /
  `escalate_hil`), `JudgeOutput` (blank justification을 거부하는
  `__post_init__`을 가진 frozen dataclass),
  `JudgeVerdict` (`proceed` / `retry` / `escalate`), 그리고
  `JudgeModel` Protocol.
- `evaluate_judge_output(output, *, known_rule_ids)`가 하나의
  `JudgeOutput`을 하나의 verdict로 reduce합니다. 규칙:
  - `ACCEPT`와 known citation만 -> `PROCEED`;
  - `ACCEPT`와 unknown citation -> `ESCALATE`
    (ungrounded acceptance는 honor 안 함);
  - `REVISE_AND_RETRY` + non-blank `retry_directive` + known
    citation만 -> `RETRY`;
  - `REVISE_AND_RETRY`와 missing / blank directive ->
    `ESCALATE` (Proposer가 뭘 바꿀지 모름);
  - `ESCALATE_HIL` -> `ESCALATE`.
- `rule-catalog/prompts/base/t2-judge.v1.yaml` - `layer: judge`,
  `applies_to: [t1.judge]`, `default_mode: shadow`. Body가
  evaluator가 강제하는 JSON 계약을 서술하므로 live Judge가
  parseable output emit. `t1.judge` capability는 이미
  `llm-registry.yaml`에 있으므로 registry 변경 불필요.
- `core/`-safe 유지: `aiopspilot.core.quality_gate.gate` +
  `aiopspilot.core.quality_gate.critic` (둘 다 peer 모듈) + stdlib
  에서만 import.

## Wave 4.5 beta - 무엇이 배포되었나

Wave 4.5 beta는 Azure Judge 어댑터를 랜딩; Wave 4 beta-1 shape을
미러링.

- `src/aiopspilot/delivery/azure/llm/judge.py` -
  `AzureOpenAIJudgeModelConfig` (endpoint, deployment,
  **required** `system_prompt`, api_version, temperature,
  max_tokens, timeout_seconds) + `AzureOpenAIJudgeModel`의 단일
  async `judge(candidate, proposer_output, critic_output)` 메서드가
  `response_format={"type": "json_object"}`로 `chat/completions`
  에 POST.
- User-turn envelope에 candidate + Proposer output + Critic의
  stance / objections / citations가 canonical `(sort_keys=True)`
  JSON 모양으로 들어가 replay와 audit가 결정론적.
- Strict fail-closed 파서: non-JSON content, non-object payload,
  누락 / non-string / enum-invalid `decision`, non-string
  `justification`, non-string / non-null `retry_directive`,
  non-array `citations`, non-string citation entry - 모두
  `RuntimeError` raise. `JudgeOutput.__post_init__`이 blank
  justification을 두 번째 방어선으로 catch.
- `tests/delivery/azure/llm/test_judge.py`의 20개 테스트가
  `httpx.MockTransport`로 6개 config 검증 + 4개 성공 파싱 + 10개
  fail-closed 파싱 커버.
- 아직 composition root에 wire되지 않음; Wave 4.5 gamma가
  orchestrator를 만들고 Wave 4.5 delta가 live `QualityGate`로 전체
  threading.

## Wave 4.5 gamma - 무엇이 배포되었나

Wave 4.5 gamma는 `DebateOrchestrator` core 모듈을 랜딩: 하나의
클래스 + 하나의 config + 하나의 `DebateOutcome` record가 Proposer
candidate 주변에서 Critic과 Judge를 조율. 이것이 `core/`에서 Wave 4.5
챕터를 닫음; Wave 4.5 delta가 orchestrator를 live `QualityGate`에
wire.

- `src/aiopspilot/core/quality_gate/debate.py` -
  `DebateOrchestrator(*, critic, judge, config=None)`;
  `DebateOrchestratorConfig(max_rounds=1)`이 Wave 4.5에서
  `[0, 1]` 밖의 값을 거부하는 strict `__post_init__`을 가짐 (나중에
  올리려면 명시적 reviewable edit);
  `ProposerRetry` 타입 alias for caller가 공급하는 Proposer retry
  콜백 (`Callable`로 유지되어 `delivery.*` import가 `core/`에
  누출 안 됨);
  `DebateVerdict` (`proceed` / `abort`)와
  `DebateOutcome` (verdict + reason + final proposer output + 전체
  transcript 필드 + rounds counter + `error_class`).
- 하나의 `async run(...)` 메서드가 전체 루프 드라이브:
  1. Critic turn 1 -> ABORT 또는 ABSTAIN이면 **Judge 호출을 소비하지
     않고** `DebateVerdict.ABORT`로 short-circuit (token-cost 가드가
     테스트 스위트에 baked-in);
  2. Judge turn 1 -> `PROCEED` 즉시 반환; `ESCALATE` abort;
     `RETRY` 두 번째 라운드 실행;
  3. Retry -> `retry_proposer(candidate, directive)` invoke
     (`max_rounds >= 1`일 때 필수 파라미터; 누락 시 호출 시점에
     `ValueError` raise하여 fork 구성 버그가 fail-fast);
  4. Critic turn 2 -> ABORT / ABSTAIN 모두 abort;
  5. Judge turn 2 -> `PROCEED`는 `rounds=2`로 반환; 나머지는 모두
     abort (round 2의 `RETRY`는 `max_rounds` 초과이므로 refused).
- 모든 어댑터 예외에 **fail-closed**. `except Exception` 브랜치가
  두 라운드 모두에서 Critic / Judge / Proposer 실패를 catch하여
  `error_class`가 보존된 `DebateVerdict.ABORT` 생산. 지금까지 누적된
  debate transcript (Critic output, Judge output, previous-round
  verdicts)가 `DebateOutcome`에 threading되어 audit log가 debate가
  얼마나 진행됐는지 정확히 표시 가능.
- `tests/quality_gate/test_debate.py`의 14개 테스트가 커버: config
  검증 (2), retry-argument-required (1), Round-1 happy path +
  Critic ABORT short-circuit + Critic ABSTAIN short-circuit + Judge
  escalate (4), retry round + max_rounds=0 refusal + retry Critic
  ABORT + Judge re-retry refusal (4), `error_class`가 보존된 세 error
  path.

## 관련 문서

| 목적 | 시작 지점 |
|------|-----------|
| Tier 경계와 quality gate | [llm-strategy-ko.md](llm-strategy-ko.md) |
| Trust routing과 컨트롤 루프 | [../../.github/instructions/architecture.instructions.md](../../.github/instructions/architecture.instructions.md) |
| 이 설계가 확장하는 Human override 정책 | [../../.github/instructions/architecture.instructions.md#human-override](../../.github/instructions/architecture.instructions.md#human-override) |
| 안전 불변식과 코딩 컨벤션 | [../../.github/instructions/coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md) |
| Prompt-injection 위협 모델 | [security-and-identity-ko.md](security-and-identity-ko.md) |
| Rule catalog와 provenance 규칙 | [rule-catalog-collection-ko.md](rule-catalog-collection-ko.md) |
