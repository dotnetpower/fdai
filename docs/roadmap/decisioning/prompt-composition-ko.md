---
title: 진화하는 시스템 프롬프트
translation_of: prompt-composition.md
translation_source_sha: 2383cf87a23b94ffb5eed904177e0c40807a0a2b
translation_revised: 2026-08-11
---

# 진화하는 시스템 프롬프트

T2 계층과 quality 게이트는 하드코딩된 단일 문자열이 아니라 **조립 가능한
catalog-as-code 프롬프트**를 소비합니다. 이 문서는 설계의 원본입니다. 레이어가 어떻게
조립되고, 각 아티팩트가 어디에 살며, 조립 루트가 어떤 경계를 배선하고, 모델이
우리가 보낸 것을 실제로 읽었는지 어떻게 측정하는지를 다룹니다.
[llm-strategy-ko.md](../architecture/llm-strategy-ko.md#t2---reasoning-tier-quality-gate-required)의
LLM 계약과
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)의
trust 라우팅을 확장합니다.

> **범위.** 업스트림은 범용 · Azure-first입니다. 웹 검색은 검토된 Azure Responses
> 어댑터를 통해 배포별로 명시적 선택합니다. 고객별 오버라이드는 포크 전용이며 코어는
> 기본 비활성 가짜를 배포합니다
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
>
> **상태.** Wave 1, 2, 2.5-A, 2.5-B 단계 1, 2.5-B 단계 2a, 2.5-B 단계
> 2b, 3 단계 A, 3 단계 B 저장소, 3 단계 B 파이프라인 구획 1, 3 단계 B
> 파이프라인 구획 2, 3 단계 C-1, 3 단계 C-2, 3 단계 D-1, 3 단계 D-2a,
> 3 단계 D-2b-i, 3 단계 D-2b-ii-alpha, 3 단계 D-2b-ii-beta, 3 단계
> D-2b-ii-gamma-1, 3 단계 D-2b-ii-gamma-2, 4 alpha, 4 beta-1, 4
> beta-2, 4.5 alpha, 4.5 beta, 4.5 gamma, 4.5 delta-1, 4.5 delta-2a,
> 4.5 delta-2b, 5 alpha와 Azure Responses 프로바이더 구획이 랜딩되었습니다 - evolving-system-prompt
> 설계가 이제 T2에 대해 **완전히 실제 운영**: 운영자 기억 종단 간,
> recognition-probe 챕터, `AzureOpenAICrossCheckModel` 내부의 per-event
> 재조립, 비평자 + Judge + 오케스트레이터 트라이앵글 (타입 + 평가기 +
> Azure 어댑터 + `max_rounds = 1` 오케스트레이터 + composition-root
> 바인딩), `DebateRouter` 순수 정책, 교차 검증 disagreement 시 토론을
> 실행하고 resolved `PROCEED`를 `ELIGIBLE`로 flip하는 `QualityGate`
> 에스컬레이션 경로, 그리고 `core/web_search/` 경계 (기본 비활성
> `NoOpWebSearchProvider` + 도메인 허용 목록 + injection-marker
> sanitizer + `trusted="false"` 스니펫 묶음). 작성기 체인은 Base
> + 작업 스킬 묶음 + 선택적 도구 매니페스트 + 선택적 Operator Memory +
> 선택적 레이어별 canary 토큰. 데이터 클래스 대체 경로 기본값은
> 제거되었습니다. `system_prompt`는 `AzureOpenAICrossCheckModelConfig`의
> 필수 필드이며 이제 작성기가 wire되지 않은 경우의
> startup-safety 대체 경로 역할을 합니다. Wave 3 단계 B **파이프라인
> 구획 3** (fork-first second-approval 채널), Wave 5 **T2 통합**
> (코어 T2 도구 매니페스트로 스니펫 threading)은 문서화되어 있지만 아직
> 구현되지 않았습니다. 모든 wave는 shadow 게이트를 통과해야만
> 승격됩니다. [롤아웃 waves](#rollout-waves) 참조.

## 한눈에 보는 설계

프롬프트는 코드 안의 리터럴이 아니라 **데이터**입니다. 조립 루트가 부팅 시
`rule-catalog/prompts/`에서 로드하고, 기능으로 인덱싱한 뒤, 해석된 본문을
Azure OpenAI 어댑터에 넘깁니다. 런타임 레이어(rule-catalog 인용,
운영자 기억 항목, 도구 출력, web 스니펫, 토론 대화 기록)는 모두
`trusted="false"` XML 태그로 감싸져 모델이 이를 데이터로 취급하도록 합니다.
**결정론적 검증기가 유일한 실행 권한**로 남습니다 - 추가된 역할, 툴,
레이어는 모두 그 검증기를 위한 재료를 생산할 뿐, 우회로가 아닙니다.

## 역할 x 계층 매트릭스

프롬프트는 두 축을 가집니다. **레이어**는 조립된 프롬프트를 구성하는 콘텐츠 타입이며,
**역할**은 어떤 base / 묶음 / 도구 집합이 적용될지 결정합니다. 카탈로그는 검토자,
제안자, 비평자, Judge, 평가 기준 base 프롬프트를 모두 배포합니다.

| 계층 \\ 역할 | 제안자 | 비평자 | Judge |
|--------------|----------|--------|-------|
| Base (역할 스켈레톤) | `base/t2-proposer.v1.yaml` | `base/t2-critic.v1.yaml` | `base/t2-judge.v1.yaml` |
| 작업 스킬 묶음 | `packs/<capability>.proposer.vN.yaml` | `packs/<capability>.critic.vN.yaml` | (보통 제안자 묶음과 공유) |
| 도구 매니페스트 | 도구 + 선택적 `web.search` | 도구(읽기 전용) | 없음 (Judge는 툴 호출 금지) |
| 도메인 맥락 (RAG) | 룰 / 과거 인시던트 인용 | 동일 | 동일 |
| Web Snippets | 제안자가 가져온 경우 | 읽기 전용 | 읽기 전용 |
| Operator Memory | 범위 제한 | 범위 제한 | 범위 제한 |
| 토론 대화 기록 | (첫 턴엔 비어 있음) | 제안자 출력 | 제안자 + 비평자 출력 |

2-model 검토자가 기본 T2 경로입니다. 제안자 / 비평자 / Judge 토론은 설정된
disagreement에서만 라우터를 통해 실행됩니다.

네 번째 역할인 **평가 기준** 판정자는 Base 레이어(`base/t2-rubric.vN.yaml`)와 도메인
맥락 레이어를 재사용합니다; 제안자의 추론을 고정 기준으로 채점하며 툴을 호출할 수
없습니다. 권위가 아니라 빼기 전용 환각 필터입니다 -
[hallucination-rubric-gate-ko.md](hallucination-rubric-gate-ko.md) 참조.

## 레이어 카탈로그

각 레이어는 고정된 역할과 고정된 저장 티어를 가집니다.

- **Base** - 짧고 불변인 역할 스켈레톤 (출력 계약, verifier-as-authority 리마인드,
  JSON-only 출력 규칙). Wave 1 목표: <= 128 토큰.
- **작업 스킬 묶음** - capability-scoped 지시 (예: RCA grounding, 액션 제안,
  novelty 분류). 각 묶음은 기능이 참조할 수 있는 rule-catalog 항목을 인용합니다.
- **도구 매니페스트** - 이 역할이 호출할 수 있는 툴의 부분집합. base 프롬프트 밖에서
  선언하는 이유는 base를 짧고 캐시 친화적으로 유지하기 위함입니다.
- **도메인 맥락 (RAG)** - 이벤트별로 선택된 룰 발췌와 과거 인시던트 참조.
  프롬프트 옆에 영구 저장하지 않고, 감사에는 인용된 id와 vector-hit 점수만 기록.
- **Web Snippets** - [웹 검색 정책](#web-search-policy) 하에서만 가져옵니다.
  `<web_snippet trusted="false" url="..." hash="...">...</web_snippet>`로 wrap.
- **Operator Memory** - 운영자 피드백(HIL 거부, 재정의 사유,
  ChatOps 선호 설정, PR 리뷰)에서 나온 범위 제한, HIL-승인된 노트.
  절대 global 아님. [Operator 기억 파이프라인](#operator-memory-pipeline) 참조.
- **토론 대화 기록** - 이전 역할들의 출력이 다음 역할에게 읽기 전용 컨텍스트로 전달.

## 저장

### Catalog-as-code (git 추적)

```text
rule-catalog/
  prompts/
    schema/
      prompt.schema.json          # 모든 아티팩트가 검증되는 JSON Schema
    base/
      t2-cross-check.v1.yaml      # Wave 1 (배포됨)
      t2-proposer.v1.yaml         # Wave 3 (배포됨, shadow)
      t2-critic.v1.yaml           # 배포됨, shadow
      t2-judge.v1.yaml            # 배포됨, shadow
      t2-rubric.v1.yaml           # 루브릭 환각 필터 (배포됨, shadow)
    packs/                        # Wave 2+
    tools/                        # Wave 2.5+
```

### 런타임 데이터 (Postgres, 해시 주소 블롭)

  다음은 목표 영속성 모델입니다. `operator_memory`는 배포됐고 전용
  `agent_transcript`와 `web_evidence` 테이블은 아직 계획 단계입니다. Operator API는 현재
  정제된 web 근거를 영속 대화 턴에 첨부합니다.

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

Global 범위의 운영자 기억은 쓰기 시점에 거부됩니다 - 이 설계가 상속하는
[Human 재정의](../../../.github/instructions/architecture.instructions.md#human-override)
정책 기준으로 너무 넓기 때문입니다.

## 프로바이더 protocols (DI 경계)

코어는 프로토콜 뒤에 남고, Azure 어댑터가 경계당 한 구현을 제공합니다. 이 설계의
현재 및 계획된 경계는 다음과 같습니다:

| 경계 | 종류 | Wave | 역할 |
|------|------|------|------|
| `PromptRegistry` | sync | 1 (배포됨) | 프롬프트 YAML 로드 / 인덱스 |
| `PromptComposer` | 비동기 | 2 | 이벤트별 역할 x 계층 조립 |
| `ToolRegistry` | sync | 2.5 | 도구 YAML 매니페스트 로드 |
| `ToolExecutor` | 비동기 | 2.5 | 모델이 발행한 도구 호출 디스패치 |
| `ProgrammaticPipelineRunner` | 비동기 | 범위가 제한된 파이프라인 | 검토된 도구 루프를 isolated venue에서 실행 |
| `OperatorMemoryStore` | 비동기 | 3 | scope-bounded 노트 읽기 / 덧붙이기 |
| `WebSearchProvider` | 비동기 | 5 | 허용 목록 뒤 아웃바운드 HTTP |
| `EvidenceStore` | 비동기 | 5 (계획됨) | hash-addressed 웹 스냅샷 저장 |
| `AgentTranscriptStore` | 비동기 | 4.5 (계획됨) | 추가 전용 토론 행 |
| `DebateOrchestrator` | 비동기 | 4.5 | 제안자 -> 비평자 -> Judge 루프 |

I/O-bound 경계는
[coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md#safety)
가 선언한 프로바이더 프로토콜의 async-by-default 규칙을 따릅니다.

## 도구 use 서브시스템

툴은 룰 카탈로그를 미러링한 catalog-as-code입니다. 각 YAML이 설명, 호출 스키마,
기능 게이트, 허용 목록, 출력 래퍼를 선언합니다.

- **기능과 예산**: `llm-registry`가 짧은 제안자/비평자 허용 목록을 선택하고, 각 도구의
  `cost_budget_usd_per_call`이 이벤트별 상한에 반영됩니다.
- **신뢰할 수 없는 출력**: `<tool_result trusted="false" ...>`는 검증기와 정책 re-check용 데이터로
  남습니다. Judge는 도구를 받지 않으므로 두 번째 제안자로 붕괴하지 않습니다.
- **Programmatic 루프**: 검토된 읽기/필터/집계 Python은 다이제스트, 샌드박스, 실행 기능,
  바이트/호출 한도, 증적 검사를 거쳐 생성된 클라이언트로 범위가 제한된 subset을 호출합니다. 프로바이더
  자격 증명, 재귀 권한, 변경 권한은 받지 않습니다.
  [프로그래밍 방식 도구 파이프라인](../interfaces/programmatic-tool-pipelines-ko.md)을 참조하세요.

### 검토된 런타임 스킬

런타임 스킬은 이미 등록된 도구 사용법을 에이전트에게 알려주는 portable Markdown instruction입니다. 저장소 coding-agent 스킬과 별개이며 도구, 신원, 역할, 실행 권한을 부여하지 않습니다. FDAI Console은 `설치됨`, `활성화됨`, `로드 적격`을 load-readiness 상태로 표시하고 권한 승격은 해당 없음으로 표시합니다.
기능 선언은 결정론적 운영자 요청 경로를 별도로 표시하며 변경 선언은 스킬 충족 여부나 카탈로그 존재로 승격을 추론하지 않고 측정된 ActionType 승격 근거로 연결합니다.

- **3단계:** 범위가 제한된 인덱스에는 메타데이터만 포함됩니다. `load_skill`은 완전한 `SKILL.md` 하나를, `read_skill_reference`는 support 산출물 하나를 반환합니다. `list_skills`, `describe_skill`도 읽기 담당 연산이며 수명 주기를 변경하지 않습니다.
- **Signed 산출물 매니페스트:** YAML front matter는 신원, 버전, 출처 이력, 본문 다이제스트, 필수 도구, allowed 에이전트, 내용 기반 주소를 가진 참조를 포함합니다. Unsafe 경로, undeclared/부분 파일, symlink-shaped 메타데이터, 다이제스트 mismatch, 예산 초과분은 실패 시 차단합니다.
- **충족 여부와 재생:** 매 부하는 활성화된 상태, 도구 가용성, 에이전트 허용 목록, stored 바이트, 발행기 서명, 참조 다이제스트를 다시 확인합니다. 프롬프트 재생은 연산,
  스킬 이름/버전, 본문/raw 다이제스트, 참조 다이제스트, 선택된/rejected 상태, 사유를 기록합니다.
- **Progressive 프롬프트:** 인덱스는 선택 본문 및 참조보다 먼저 들어갑니다. 본문은 검증 후에만 trusted 검토된 instruction이며 참조는 신뢰할 수 없는 데이터로 남습니다. 기존 reference-free
  single-file 스킬은 같은 파서와 effective 내용을 변경 없이 사용합니다. 명시적 multi-skill 조립은 [통제된 스킬 Bundles](governed-skill-bundles-ko.md)가 소유합니다.
- **측정 벤치마크:** 고정 16-skill 카탈로그의 네트워크 인시던트, 비용 spike, 배포 실패 시나리오에서 full 변환 결과 8194 estimated 토큰이 완전한 본문 하나 선택 시 1544-1546으로 줄어 81.1-81.2% 감소했습니다.
- **Dynamic 코드 없음:** 런타임 스킬은 binary 설치, 환경 시크릿 주입, 프로바이더 부하,
  도구 카탈로그 및 risk 게이트 bypass를 할 수 없습니다.
- **Audited 제안 workshop:** `SkillWorkshop`은 에이전트 초안을 validate하고 inert
  내용 기반 주소를 가진 데이터로 저장합니다. Injected human authorizer가 사유와 함께 approve 또는
  거부해야 하며 제안자는 self-review할 수 없습니다. 모든 전이는 Markdown 본문을
  포함하지 않고 추가 전용 감사 싱크로 전송됩니다. PostgreSQL 영속성은 재시작 후에도
  유지되며 검토 및 구체화에 expected-state compare-and-swap을 적용합니다. 승격은
  다이제스트 및 발행기 trust 검증을 다시 실행한 뒤 활성 프롬프트 변경 없이 approved
  산출물을 비활성화된 상태로 install합니다.
- **승인된 출처 새로 고침:** 등록된 GitHub 출처는 ETag 상태로 변경할 수 없는 커밋을 해석하고
  declared 파일만 가져와 exact 바이트를 격리 구역에 저장합니다. 통과한 내용은 비활성화된
  후보가 됩니다. Approver installation은 disabled-first를 유지하고 Owner 철회는
  출처 이력을 삭제하지 않고 출처와 영속 산출물을 비활성화합니다.
  [스킬 소스 관리](../interfaces/skill-source-management-ko.md)를 참조하세요.

### Operator-memory 검토 및 compaction

Operator-memory 저장소는 활성, 만료된, 대체된 항목을 범위, 출처 이벤트/참조, 작성자,
서로 다른 승인자, TTL-derived 만료, supersession 포인터와 함께 범위가 제한된 검토 변환 결과로
제공합니다. Settings > Operator 기억 콘솔 화면은 GET-only입니다. 변경은 계속 approved HIL
또는 ChatOps 작업 흐름으로 진입합니다.

`MemoryCompactionService`는 범위 및 category가 같고 출처 이력 참조를 가진 활성 unique 출처
항목 2개 이상에서만 더 짧은 항목을 제안할 수 있습니다. 후보 텍스트는 주입 screening을
통과하고 서로 다른 authorized 검토자가 approve하기 전까지 inert합니다. PostgreSQL 승격은
compacted 항목 덧붙이기, 출처 id/참조 보존, original supersession을 atomic하게 수행합니다. Rollback은
본문을 삭제하지 않고 original 출처 항목을 복원하며 compacted 항목을 inactive로 만듭니다.
Compaction은 역할, 도구, 액션, 실행 권한을 부여하지 않습니다.

## 웹 검색 정책

웹 검색은 최후의 수단 툴입니다. 배포별 명시적 선택이며 절대 grounding 출처가
아닙니다.

- **기본 off**: 업스트림은 no-op `WebSearchProvider`를 배포합니다.
  `FDAI_WEB_SEARCH_ENABLED=true`와 curated 도메인 허용 목록을 설정하면 Azure
  Responses 어댑터가 활성화됩니다. 프로덕션은 Operator API managed 신원을
  재사용하며 대화 표면에 검색 API 키를 추가하지 않습니다.
- **언제 실행 가능**: T2 케이스, novelty 점수가 임계값 초과, 기능의
  도구 허용 목록이 `web.search`를 포함, 이벤트당 조회 / 비용 예산이 소진되지
  않음. 이 결정은 산문이 아니라 순수 · 결정론적
  [`decide_web_search`](../../../services/core-control-plane/src/fdai/core/web_search/policy.py) 정책
  (`WebSearchPolicyConfig` + `WebSearchSignals` -> `SEARCH` / `SKIP`)이며,
  `escalation_ladder`를 미러링합니다. deny-first 게이트(비활성화된 -> 프로바이더
  없음 -> 기능 허용 목록 미포함 -> reasoning-tier 아님 -> 조회 예산
  -> 비용 예산 -> grounding-gap 필요 -> novelty 임계값)를 평가하고 건너뜀
  사유를 감사 로그에 기록하므로, "언제 웹 검색이 실행되는가"는 문단이
  아니라 테스트로 답합니다.
- **도메인 허용 목록**: 기본 출처만 사용합니다(벤더 docs, RFC, NVD, CVE 레지스트리). 허용 목록 도메인은 DNS 하위 도메인을 포함하지만 라벨 경계 검사는 suffix-confusion 호스트를 차단합니다. 블로그, 포럼 및 소셜 미디어는 지원되지 않습니다.
- **스니펫 처리**: HTML strip. prompt-유사 패턴(`ignore previous`, `system:` 등)
  탐지 및 플래그. inject 전에 `<web_snippet trusted="false">...</web_snippet>`
  로 wrap.
- **Grounding 출처가 아님**: `cited_rule_ids`는 여전히 rule-catalog 항목으로
  해석되어야 합니다. 유용한 웹 발견은 rule-catalog 발견 루프로 흘러가며,
  현재 이벤트의 grounding 요구를 만족시키지 않습니다.
- **재생 결정성**: 결과는 `web_evidence`에 `(content_hash, url, fetched_at)`
  로 저장. 감사 엔트리는 해시를 참조. 재생은 저장된 스냅샷을 읽으며 다시 fetch
  하지 않으므로 과거 실행이 재현 가능하게 유지됩니다.
- **통제된 Azure Responses 어댑터**: Azure-first 구현은 managed `web_search`를 `WebSearchProvider`
  뒤에 감쌉니다. Direct Responses는 매 요청에 `allowed_domains`를 보내고, 선택적 Foundry
  prompt-agent 경로는 정확한 배포 허용 목록을 사용하며 런타임 표류를 거부합니다. 두 경로
  모두 `web_search_call`을 검증하고 off-allowlist 인용을 거부하며 정제된 근거 스냅샷을 영속
  대화 턴에 저장합니다. 제한된 운영자 조회만 FDAI 밖으로 나가며
  화면 스냅샷과 대화 이력은 검색 호출에 전송되지 않습니다. 프로바이더 실패는 `tool_blocked`, `provider_unauthorized`, `provider_rate_limited` 같은 제한된 사유 코드로 변환하며 raw 응답 본문은 대화에 포함하지 않습니다. 조직 전체 차단 및 권한 확인 실패는 모델 장애 조치를 중단하고 transient 실패만 다음 배포를 시도합니다.
- **지연 기반 모델 풀**: 검색 후보는 `resolved-models.json`의
  전용 `t1.web_search` 레지스트리 기능에서 가져와 `web_search_candidates`로
  serialize합니다. Narrator 후보는 대체 경로로 사용하지 않습니다. 시작은 후보별
  managed-tool 검색을 실제로 한 번 보내고 실패 후보를 serving 전에 제외합니다. 이후
  주기적 모델 지식만 쓴 탐색은 검색 비용 없이 지연 시간을 갱신합니다. 검색 호출은 rolling p50이
  가장 낮은 후보를 선택하고 오류 시 다음 후보로 장애 조치합니다. 선택 배포,
  p50/p95 이력, 실제 검색 지연 시간을 출처 이력으로 반환합니다. 탐색은 웹 검색을
  호출하지 않으므로 주기적 상태 측정에는 검색 툴 비용이 발생하지 않습니다.
- **외부 데이터 경계**: Azure `web_search`는 Grounding with Bing을 사용합니다.
  이 전송에는 Microsoft 데이터 Protection Addendum가 적용되지 않으며 데이터가
  배포의 compliance 및 geography 경계 밖으로 나갈 수 있습니다. 따라서
  명시적으로 활성화하고 도메인을 허용 목록으로 제한합니다. GUID, Azure 리소스
  ID, 이메일 주소, 비공개 IP 주소가 포함된 질의는 전송 전에 차단합니다.

## 토론 오케스트레이터 (제안자 / 비평자 / Judge)

토론은 라우터가 요청할 때만 실행됩니다 - 보통 high-severity, high novelty,
또는 명시적인 operator-memory 지침. 기본 T2 경로는 여전히
[llm-strategy-ko.md](../architecture/llm-strategy-ko.md)에 문서화된 2-model 교차 검증입니다.

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
`debate.max_cost_usd`. 초과 시 HIL로 abort. 비평자는 제안자와 다른 발행기
모델이어야 합니다 (mixed-model distinctness 규칙 확장,
[llm-strategy-ko.md](../architecture/llm-strategy-ko.md#t2---reasoning-tier-quality-gate-required)).
Judge는 더 작고 저렴한 모델이어도 됩니다.

비평자의 역할은 "다른 의견"이 아니라, 7개 안전조건(stop-condition, 롤백, blast-radius,
예행 실행, 잠금, 멱등성, audit-log)에 대한 체크리스트 + 인용 validity + 운영자 기억
와의 모순 여부입니다.

## Operator 기억 파이프라인

Operator 피드백은 두 단계 게이트를 거쳐 기억이 됩니다:

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

- **범위는 resource-group 이하여야 합니다.** 더 넓은 범위는 재정의가 아닌
  룰 변경이며, 카탈로그 파이프라인을 통과해야 합니다.
- **주입 시 sanitize + wrap**: 기억 본문은
  `<operator_note author="..." scope="..." trusted="false">...</operator_note>`
  태그 안으로 들어가며, base 프롬프트는 해당 태그 안의 지시를 따르는 것을
  금지합니다.
- **발견 신호**: 같은 룰에 대한 장기 재정의 또는 유사한 기억 행의 다수는
  rule-catalog 발견 루프에 개정 번호 / retirement 후보로 흘러갑니다.

> Working-context 선택은 [컨텍스트 선택 정책](context-selection-policy-ko.md)이 별도로 소유합니다:
> 불변 `deterministic-tiered-v1@1.0.0`, 필수 검증, shadow 근거, 재생 및 롤백.

## 인식 측정

긴 프롬프트는 조용히 지시를 흘립니다. "모델이 우리가 보낸 것을 실제로 읽었는가"를
1급 KPI로 다루며, 프롬프트를 강제 적용으로 승격하기 전에 게이트합니다.

- **하드 토큰 예산** - 작성기가 조립된 프롬프트당 토큰을 추정. 초과 시 HIL로
  abort하고 `prompt.token_budget.exceeded_rate`를 증가. 우선순위가 낮은 레이어
  (가장 오래된 운영자 기억부터)는 감사에 보이는 이유와 함께 명시적으로 폐기.
- **Canary 토큰** - 작성기가 태그된 레이어 마커
  (`<layer id="pack.rca.v3">...</layer>`)를 삽입. 역할들은 어느 레이어를
  인식했는지 보고. 인식되지 않은 고우선순위 레이어는 결함으로 surfacing.
- **Adherence 비율** - JSON 스키마 위반, 필수 필드 누락, citation-rule-id
  validity를 매 프롬프트 버전 bump마다 고정 시나리오 세트에서 측정.
- **Position 민감도** - 통제된 고정본이 동일한 지시를 base vs. 묶음
  vs. 끝에 배치하고 adherence를 비교. 특정 위치의 지속적 dip은 base 재작성
  신호.
- **Mixed-model agreement 비율** - 기존 quality-gate disagreement 비율을
  프롬프트 버전별로 추적하여 리그레션을 즉시 노출.
- **토론 economics** - 토론 오케스트레이터 랜딩 후
  `debate.rounds.p95`, `debate.cost_usd.p95`, `debate.timeout_to_hil_rate`,
  `critic.reversal_rate`를 추적.

승격 게이트 (초기값, 기능별로 튜닝): `adherence >= 0.95`,
`citation_f1 >= 0.9`, `web.grounding_leak == 0`, `토론.timeout_to_hil_rate
<= 5%`, `비평자.reversal_rate in [1%, 15%]`.

## 안전 불변식 (확장)

[coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md#safety)
의 8개 불변식에 이 설계 랜딩과 함께 6개가 추가됩니다:

1. 웹 검색 출력은 **절대** `cited_rule_id`가 아님.
2. 도구 결과와 web 스니펫은 **항상** `trusted="false"` XML로 wrap.
3. 토론 루프는 하드 `max_rounds`, `max_wall_seconds`, `max_cost_usd`
   상한을 가지며, 초과 시 HIL로 abort.
4. 비평자와 제안자의 발행기는 **달라야** 하며, 같은 발행기 쌍은 단일
   voter로 붕괴함.
5. Judge는 툴을 호출**해서는 안 됨**. Judgment와 세대는 분리.
6. Web 근거는 해시 주소 변경할 수 없는이며, 재생은 스냅샷을 읽고 다시 fetch
   하지 않음.

## 롤아웃 waves

모든 wave는 shadow first로 랜딩. 승격은 이전 wave의 승격 게이트가 유지되어야 함.

| Wave | Deliverable | 배포됨 |
|------|-------------|--------|
| 1 | Base 프롬프트 카탈로그 외부화 + `PromptRegistry` + 조립 배선 | yes |
| 2 | `PromptComposer` 비동기 프로토콜 + `DefaultPromptComposer` (Base + 작업 묶음) + `ComposedPrompt` / `LayerRef` 인식 프리미티브 + `AzureOpenAICrossCheckModelConfig`의 `system_prompt` 필수 전환 | yes |
| 2.5-A | `DefaultPromptComposer`의 shadow-vs-enforce 필터 + 배포된 shadow 모드 작업 묶음 + `tool.schema.json` + `FileSystemToolRegistry` | yes |
| 2.5-B 단계 1 | 작성기가 선택적 도구 매니페스트 레이어 발행 + 배포된 shadow 모드 도구 YAML (`rule.query` / `state.query` / `audit.query`) + `trusted="false"` 래퍼 강제 | yes |
| 2.5-B 단계 2a | 비동기 `ToolExecutor` + `ToolProvider` 경계 + 스키마 검증, shadow 가드, 래퍼 강제, 5개의 타입이 지정된 실패 시 차단 에러 (`UnknownToolError`, `ShadowToolBlockedError`, `ToolArgumentValidationError`, `MissingProviderError`, `ProviderCallError`)를 가진 `DefaultToolExecutor` | yes |
| 2.5-B 단계 2b | `AzureOpenAICrossCheckModel`이 강제 적용 모드 도구에 대해 `tools=[...]`를 발행하고, 범위가 제한된 multi-turn 루프로 모델 발행 `tool_calls`를 실행기로 라우팅하며, 알 수 없는 함수명 / 잘못된 arguments / half-wired 설정을 실패 시 차단으로 거부 | yes |
| 3 단계 A | `core/operator_memory/` 타입 + 비동기 `OperatorMemoryStore` 프로토콜 + `InMemoryOperatorMemoryStore` + `wrap_operator_note` / `detect_injection_markers` sanitizer + 쓰기 시점 정책 강제(범위 <= resource-group, 서로 다른 승인자, 추가 전용 대체, 선택적 TTL, 주입 마커 거부) | yes |
| 3 단계 B 저장소 | `PostgresOperatorMemoryStore` + alembic 이행 `20260706_0006_operator_memory` (추가 전용 테이블, Python 정책을 미러링한 검사 제약, `(scope_kind, scope_ref)` scope-lookup 인덱스, `InMemoryOperatorMemoryStore`와 TTL + 대체 시맨틱 동등성, `FDAI_DATABASE_URL` unset 시 스킵되는 통합 테스트) | yes |
| 3 단계 B 파이프라인 구획 1 | `HilResponse(decision=REJECT, reason=...)` + 별개의 `second_approver`를 주입된 `OperatorMemoryStore`를 통해 저장된 `OperatorMemoryEntry`로 변환하는 `HilRejectMaterializer` 코어 모듈; 5개의 pipeline-level 오류 코드 (`wrong_decision`, `empty_reason`, `missing_first_approver`, `missing_second_approver`, `same_principal`)가 저장소 접근 전에 fail-fast, store-side 정책 오류(중복 id, 주입 표시)는 그대로 표면 | yes |
| 3 단계 B 파이프라인 구획 2 | Composition-root wire: `_build_operator_memory_store()`가 `FDAI_OPERATOR_MEMORY_DSN`으로 Postgres를 선택하거나 기본값으로 in-memory 가짜를 사용하고, `_finalize_llm_bindings`가 저장소를 `DefaultPromptComposer`에 인계하므로 operator-memory 레이어가 데이터베이스 없이도 종단 간으로 도달 가능 (포크가 `HilRejectMaterializer`로 덧붙이기한 항목이 즉시 작성기에 보임) | yes |
| 3 단계 B 파이프라인 구획 3 | 실제로 materializer를 invoke하는 second-approval 채널 (Teams Adaptive 카드 / git PR / fork-authored CLI). 승인 채널은 배포마다 다르므로 fork-first 유지; 업스트림은 `HilRejectMaterializer` 경계와 operator-memory 저장소만 배포하고 특정 UI는 배포하지 않음 | 계획됨 |
| 3 단계 C-1 | `DefaultPromptComposer`가 선택적 `operator_memory_store` + `scope`를 받고 operator-memory 레이어를 발행. 각 항목은 `wrap_operator_note`로 wrap. 계층 해석은 resource-group note를 리소스 note 앞에 배치 | yes |
| 3 단계 C-2 | `AzureOpenAICrossCheckModel`이 시작 시 한 번이 아니라 per-event로 작성기를 호출 (포크가 제공하는 선택적 `ScopeResolver`가 후보에서 `OperatorScope`를 도출)하므로 운영자 기억이 실제로 모델에 도달 | yes |
| 3 단계 D-1 | Recognition-probe 프리미티브 (`RequiredField`, `ExpectedResponse`, `CitationScores`, `RecognitionResult`) + 순수 평가기 함수 (`evaluate_adherence`, `evaluate_canary_echoes`, `evaluate_citations`, `score_recognition`) - `core/measurement/prompt_probe.py` | yes |
| 3 단계 D-2a | `CanaryGenerator` 프로토콜 + `SecretsCanaryGenerator` / `DeterministicCanaryGenerator` + `ComposedPrompt.canary_tokens` 필드 + 작성기 레이어별 head-marker 주입 (`canary_generator=` 파라미터 명시적 선택. 기본값은 빈 대응이므로 프로덕션 동작 무변화) | yes |
| 3 단계 D-2b-i | `RecognitionKpiSummary` 데이터 클래스 + `summarize_recognition` 집계 (adherence 통과 비율, per-code violation counts, per-layer canary echo 비율 - measured denominator 사용, 스코어된 샘플만 대상으로 하는 인용 F1 mean) | yes |
| 3 단계 D-2b-ii-alpha | `RecognitionScenario` / `RecognitionSample` / `RecognitionRunReport` + `ScenarioResponder` 프로토콜 + `score_batch` (순수) + `run_scenarios` (작성기 + 응답자 오케스트레이션. 작성기 canary가 자동으로 스코어링에 승격) | yes |
| 3 단계 D-2b-ii-beta | `rule-catalog/prompts/scenarios/` scaffold + `scenario.schema.json` + `load_scenarios(catalog_root)` 파일시스템 로더 (aggregate-error 표면, 파일명 `<id>.v<version>.yaml`, 빈 카탈로그 합법) | yes |
| 3 단계 D-2b-ii-gamma-1 | `emit_kpi_rows(report)` target-neutral KPI 행 emitter + `KpiRow` / `RowUnit` 타입 + 안정된 메트릭 이름 상수 (`prompt.recognition.*`) | yes |
| 3 단계 D-2b-ii-gamma-2 | recognition 메트릭 이름에 wire된 CLI 실행기 + 대시보드 패널 | 계획됨 |
| 4 alpha | 비평자 역할 스캐폴딩: `CriticStance` / `CriticSeverity` / `CriticObjection` / `CriticOutput` / `CriticVerdict` 타입 + `CriticModel` 프로토콜 + `evaluate_critic_output()` 순수 평가기 + `rule-catalog/prompts/base/t2-critic.v1.yaml` (`default_mode: shadow`, `applies_to: [t2.critic]`). QualityGate에 실제 운영 wire 없음; Wave 4.5가 토론 오케스트레이터를 랜딩할 때까지 dormant | yes |
| 4 beta-1 | `AzureOpenAICriticModel` httpx 어댑터가 Azure OpenAI ``채팅/completions`` 구조화된 JSON 출력을 통해 `CriticModel` 프로토콜을 구현; strict 실패 시 차단 파서 (알 수 없음 stance / 심각도 / 누락 필드 / non-string 인용 / blank description 모두 raise). 아직 조립 루트에 wire되지 않음 - 배포된 카탈로그 시드는 `default_mode: shadow` 유지 | yes |
| 4 beta-2 | `rule-catalog/llm-registry.yaml`에 `t2.critic` 기능을 추가 (`invocation: on_disagreement`, Anthropic-first 선호 설정으로 제안자와 발행기 구분). `LlmBindings`가 선택적 `critic_model` 필드를 갖고, `bind_azure_llm_bindings`가 기능 해석 + `critic_system_prompt` 공급 모두 만족될 때 `AzureOpenAICriticModel`을 바인딩. 시작 로그에 `critic_prompt_composed` 구조화 엔트리 추가 | yes |
| 4.5 alpha | Judge 역할 스캐폴딩: `JudgeDecision` / `JudgeOutput` / `JudgeVerdict` 타입 + `JudgeModel` 프로토콜 + `evaluate_judge_output()` 순수 평가기 + `rule-catalog/prompts/base/t2-judge.v1.yaml` (`default_mode: shadow`, `applies_to: [t1.judge]`). 토론 오케스트레이터 설계에 따라 Judge는 smaller / cheaper 모델 유지 | yes |
| 4.5 beta | `AzureOpenAIJudgeModel` httpx 어댑터가 `JudgeModel` 프로토콜을 구현; 비평자 어댑터와 동일한 형태의 strict 실패 시 차단 파서 | yes |
| 4.5 gamma | `DebateOrchestrator` 코어 모듈이 `max_rounds = 1`로 제안자 / 비평자 / Judge를 orchestration; 모든 어댑터 예외에 실패 시 차단 (`error_class`가 보존된 `DebateVerdict.ABORT` 반환), 감사 로그용 토론 대화 기록을 `DebateOutcome`에 보존, 비평자가 이미 ABORT하면 Judge를 short-circuit (token-cost 보호) | yes |
| 4.5 delta-1 | Composition-root wire: `LlmBindings`가 선택적 `judge_model`과 `debate_orchestrator` 필드를 갖게 됨. `bind_azure_llm_bindings(judge_system_prompt=)`가 `t1.judge` 기능 해석 + 프롬프트 공급 시 `AzureOpenAIJudgeModel` 바인딩. `critic_model` AND `judge_model` 둘 다 바인딩되면 `DebateOrchestrator(max_rounds=1)` 자동 생성; `__post_init__`이 일관성 없는 수동 생성 거부. `__main__`이 shipped 시드에서 `t2.judge` 프롬프트 조립을 `LookupError`-graceful 성능 저하로 처리 | yes |
| 4.5 delta-2a | `core/quality_gate/debate_router.py`의 `DebateRouter` 순수 정책 모듈: `DebateRoutingDecision` + `DebateRouterConfig` (`enabled` 킬스위치, `on_cross_check_disagreement` 축, `always_for_action_types` / `never_for_action_types` 허용/거부 리스트) + `decide_debate_route()` 실패 시 차단 술어. 오케스트레이터 미이용 시 건너뜀 short-circuit; 킬스위치가 허용 목록 지배; denylist가 허용 목록 이김 | yes |
| 4.5 delta-2b | `QualityGate`가 선택적 `debate_orchestrator` + `debate_router_config` 수용. 교차 검증 disagreement 시 `decide_debate_route()` 호출; `DEBATE`면 기본 교차 검증 모델을 재호출하는 no-directive `retry_proposer`와 함께 오케스트레이터 실행. `DebateOutcome.PROCEED`가 disagreement를 `ELIGIBLE`로 flip (다른 soft issue가 없는 한); `ABORT`는 `DISAGREE` 유지. Half-wiring (두 파라미터 중 하나만) 은 construction 시점에 raise | yes |
| 5 alpha | `core/web_search/`의 웹 검색 경계: `WebSearchQuery` / `WebSnippet` / `WebSearchResult` 타입, `WebSearchProvider` 비동기 프로토콜, `NoOpWebSearchProvider` 기본 비활성 가짜 (모든 쿼리에서 zero snippets + `reasons=("no_op_provider",)` 반환), 그리고 off-allowlist 도메인과 주입 표시를 거부한 후 `<web_snippet trusted="false" ...>...</web_snippet>` 묶음을 생성하는 sanitizer 헬퍼 (`validate_snippet_domain`, `detect_snippet_injection_markers`, `wrap_web_snippet`) | yes |
| 5 beta-A | Azure Responses 프로바이더 + latency-routed 모델 풀 + Operator API 채팅 명시적 선택 배선 | yes |
| 5 beta-B | 정책에 따라 정제된 스니펫을 도구 매니페스트에 threading하는 코어 T2 조립 wire | 계획됨 |

## Wave 1 - 무엇이 배포되었나

Wave 1은 런타임 행동을 바꾸지 않은 채 경계를 도입합니다.

- `rule-catalog/prompts/schema/prompt.schema.json` - 프롬프트 아티팩트용 JSON
  스키마.
- `rule-catalog/prompts/base/t2-cross-check.v1.yaml` - 추출된 T2 base 프롬프트.
- `services/core-control-plane/src/fdai/core/prompts/` - `PromptRegistry` 프로토콜,
  `FileSystemPromptRegistry` 구현, aggregate-error 검증.
- `bind_azure_llm_bindings`가 선택적 `system_prompt`를 받아 모든 교차 검증
  구성에 스레딩.
- `runtime.configuration._finalize_llm_bindings`가 `FileSystemPromptRegistry`를 통해 base
  프롬프트를 로드하여 전달.

## Wave 2 - 무엇이 배포되었나

Wave 2는 프롬프트 조립을 정식 작성기로 승격하며 경계를 완성합니다.

- `services/core-control-plane/src/fdai/core/prompts/composer.py` - `PromptComposer` 비동기 프로토콜
  + `DefaultPromptComposer` (Base + 작업 스킬 묶음 조립).
- `services/core-control-plane/src/fdai/core/prompts/testing.py` - 포크 테스트가 카탈로그를 건드리지
  않고 캔닝된 프롬프트를 주입할 수 있게 하는 `StaticPromptComposer` 가짜.
- `PromptRegistry.get_packs(capability_id)` - 특정 기능에 바인딩된 모든
  task-pack 아티팩트를 반환하며, id당 최고 버전만 유지.
- `ComposedPrompt` + `LayerRef` 타입이 정렬된 레이어 매니페스트와 레이어별
  토큰 추정치를 기록하여 향후 recognition-probe 측정을 위한 기반 제공.
- `AzureOpenAICrossCheckModelConfig.system_prompt`는 이제 필수 필드입니다.
  데이터 클래스 기본값은 제거되었습니다. 빈 프롬프트는 생성 시 거부됩니다.
- `bind_azure_llm_bindings(..., system_prompt=)`가 필수이며 두 T2
  reasoner 구성으로 모두 전달되어 mixed-model 교차 검증이 동일한 지시
  컨텍스트를 보게 됩니다.
- `runtime.configuration._finalize_llm_bindings`가 `DefaultPromptComposer`를 생성하고
  `compose(capability_id="t2.reasoner.primary")`를 대기한 뒤 어댑터를
  배선하기 전에 조립된 계층 매니페스트를 로깅.

## Wave 2.5-A - 무엇이 배포되었나

Wave 2.5-A는 shadow 모드 필터와 tool-catalog 스캐폴딩을 추가합니다.
도구 매니페스트 주입과 실행기는 Wave 2.5-B에서 랜딩합니다.

- `DefaultPromptComposer(include_shadow_packs=False)`가 프로덕션 기본값.
  `default_mode: shadow`로 저작된 묶음은 git에 있지만 승격되기 전까지 라이브
  프롬프트에 영향을 주지 않습니다. 평가 실행은 `include_shadow_packs=True`로
  명시적 선택.
- `rule-catalog/prompts/packs/t2-cross-check-output-contract.v1.yaml` -
  경계를 종단 간으로 증명하는 shipped shadow 모드 작업 묶음. Wave 3의
  recognition 탐색이 도움을 확인하면 첫 `enforce` 묶음으로 승격 예정.
- `rule-catalog/prompts/tools/schema/tool.schema.json` - 도구 아티팩트용
  JSON 스키마. 모든 도구 설명은 레지스트리가 파일을 받아들이기 전에 이를
  통과해야 합니다.
- `rule-catalog/prompts/tools/README.md` - prompts 서브시스템 README를
  미러링한 디렉토리 계약.
- `services/core-control-plane/src/fdai/core/tools/` (이전 `core/prompts/tool_registry.py`에서
  이관) - `ToolArtifact`, `CapabilityGate`, `ToolRegistry` 프로토콜,
  aggregate-error 검증을 가진 `FileSystemToolRegistry`. 빈 카탈로그가 에러
  없이 로드되므로 포크는 첫 도구를 저작하기 전에 경계를 채택할 수 있습니다.
  `output_wrapper`의 `trusted="false"` 불변식은 inject 시점이 아니라 부하
  시점에 강제됩니다.

## Wave 2.5-B 단계 1 - 무엇이 배포되었나

Wave 2.5-B 단계 1은 아직 어떤 호출도 디스패치하지 않은 채 도구 설명을
작성기에 스레딩합니다. 단계 2가 실행기와 OpenAI function-calling
파라미터를 배선합니다.

- `DefaultPromptComposer(tool_registry=...)`가 선택적 `ToolRegistry`를
  받습니다. 제공되고 shadow 필터 이후 최소 하나의 도구가 조건을 충족한하면,
  작성기가 조립된 프롬프트 끝에 synthetic `tool-manifest` 레이어를
  발행합니다. 없거나 비어 있으면 매니페스트 레이어가 추가되지 않습니다.
  모델은 "no 도구" 표현을 절대 보지 않습니다.
- `include_shadow_tools=False`가 프로덕션 기본값. ``true``로 설정하면
  평가 실행에서 `include_shadow_packs=True`와 같은 방식으로 미러링됩니다.
- `rule-catalog/prompts/tools/catalog/`에 세 개의 shadow 모드 도구 YAML이
  배포됩니다: `rule.query.v1.yaml`, `state.query.v1.yaml`,
  `audit.query.v1.yaml`. 각각 레지스트리가 강제하는 `trusted="false"` 출력
  래퍼를 가집니다.
- 프롬프트 레지스트리는 이제 `prompts/` 아래의 형제 subsystem을 건너뜀합니다
  (현재는 `tools/`만). 따라서 `FileSystemPromptRegistry`가 도구 YAML을
  malformed 프롬프트 조각으로 오해할 수 없습니다.

## Wave 2.5-B 단계 2a - 무엇이 배포되었나

Wave 2.5-B 단계 2a는 Azure OpenAI 어댑터를 아직 건드리지 않은 채로 도구
콜을 종단 간으로 전달할 수 있게 하는 실행기 경계를 도입합니다.
단계 2b가 모델 발행 `tool_calls`를 이 실행기로 스레딩합니다.

- `services/core-control-plane/src/fdai/core/tools/executor.py` - `ToolExecutor` 비동기 프로토콜
  + `DefaultToolExecutor` 업스트림 구현 + 포크가 도구 그룹별로 구현하는
  `ToolProvider` 경계. 모든 실패는 `ToolExecutorError`의 다섯 개
  타입이 지정된 서브클래스 (`UnknownToolError`, `ShadowToolBlockedError`,
  `ToolArgumentValidationError`, `MissingProviderError`,
  `ProviderCallError`) 중 하나로 surfacing되어, 호출자가 부분 결과를
  삼키지 않고 HIL로 라우팅할 수 있습니다.
- `services/core-control-plane/src/fdai/core/tools/testing.py` - `InMemoryToolProvider`
  (도구 id + 정렬된 arguments 튜플로 keying된 canned 응답, 호출
  기록 저장) 및 `NoOpToolProvider` (모든 호출 거부. 포크가 프로바이더
  배선 없이 도구를 승격했을 때의 업스트림 기본값).
- 전달 시점 실패 시 차단 보장:
  1. 알 수 없는 도구 id -> `UnknownToolError`,
  2. `default_mode: shadow`이며 `allow_shadow_dispatch=False` ->
     `ShadowToolBlockedError` (작성기의 매니페스트 레이어 필터
     뒤편의 belt-and-braces 방어),
  3. 아티팩트의 `input_schema` (`additionalProperties=False` 포함)를
     위반한 arguments -> `ToolArgumentValidationError`,
  4. 아티팩트가 declare한 `provider` 이름이 조립 시점에
     배선되지 않음 -> `MissingProviderError`,
  5. 프로바이더가 raise -> `ProviderCallError` (원본 예외는
     `__cause__`에 보존).
- `ToolResult`는 `wrapped_text` (다음 턴에 주입 준비 완료), `raw`
  (감사 쓰기 담당용), `cost_usd`, `latency_ms`를 기록하여 Wave 4.5의
  토론 오케스트레이터가 이벤트별 예산을 강제할 수 있게 합니다.
- `core.prompts`와 `core.tools` 간 순환 가져오기는 `TYPE_CHECKING`
  가드로 해소됩니다: `core.prompts.composer`는 런타임 도구
  레지스트리를 duck typing으로 사용하므로 모듈 로드 시 `core.tools`
  가져오기가 필요하지 않습니다.

## Wave 2.5-B 단계 2b - 무엇이 배포되었나

Wave 2.5-B 단계 2b는 실행기를 Azure OpenAI 교차 검증 어댑터로
스레딩하여 모델 발행 도구 콜이 실제로 프로바이더 round-trip에 도달하게
합니다. 배포된 도구 세 개는 모두 `default_mode: shadow`이므로 업스트림
기본 상태에서는 어댑터가 도구를 하나도 advertising 하지 않습니다.
프로덕션 동작은 포크가 실제 프로바이더를 등록하고 도구를 승격하기 전까지
동일하게 유지됩니다.

- `AzureOpenAICrossCheckModel.__init__`이 선택적 `tool_registry` +
  `tool_executor`를 받습니다 (둘 다 또는 둘 다 없음. half-wired 설정은
  fail-fast). 어댑터는 생성 시점에 모든 강제 적용 모드 도구를 스냅샷하고
  OpenAI 호환 `tools=[...]` 배열을 한 번 빌드합니다. `propose()` 실행
  중에 매니페스트가 표류할 수 없습니다.
- `AzureOpenAICrossCheckModelConfig.max_tool_iterations` (기본 3)이 도구
  전달 루프를 바운드합니다. 0으로 설정하면 실행기가 주입되어도
  도구 콜을 완전히 비활성화합니다. 양수 값을 설정하고 도달하면 더
  많은 토큰을 소모하지 않고 `RuntimeError`로 HIL에 abort합니다.
- `rule.query` 같은 도구 id는 lossless dot-to-underscore 인코딩으로
  OpenAI 함수명이 됩니다. 역 조회는 생성 시점에 레지스트리 스냅샷에서
  구축된 맵을 사용하므로, 공격자가 underscored 형태를 추측하여 대체
  id를 밀어넣을 수 없습니다 (`delete_everything`은 맵에 없음 -> 거부).
- Multi-turn 루프는 assistant `tool_calls` 턴과 콜당 하나의
  `role: "tool"` 메시지를 보존하여 모델이 다음 라운드에 완전한
  컨텍스트를 갖게 합니다.
- 어댑터 경계에서의 실패 시 차단 보장:
  1. 알 수 없는 함수명 -> `RuntimeError` (실행기가 실행되기 전),
  2. 실행기 배선 없이 tool_calls -> `RuntimeError`,
  3. non-JSON arguments -> `RuntimeError`,
  4. `max_tool_iterations` 도달 -> `RuntimeError`,
  5. 실행기 실패는 그대로 전파되어 호출자가 다섯 개의
     `ToolExecutorError` 서브클래스를 구분할 수 있게 합니다.
- `bind_azure_llm_bindings`가 선택적 `tool_registry` + `tool_executor`를
  받아 세 개의 교차 검증 생성 사이트(hil-only 기본, 기본
  reasoner, 보조 reasoner)에 모두 스레딩하므로 mixed-model
  교차 검증이 동일한 도구 매니페스트를 봅니다.
- `runtime.configuration._finalize_llm_bindings`가 azure 모드에서
  `FileSystemToolRegistry` + `DefaultToolExecutor(providers={})`를
  빌드합니다. 업스트림은 의도적으로 빈 providers 맵으로 ship합니다:
  배포된 모든 도구가 shadow이므로 어댑터가 도구를 advertising하지 않고
  어떤 전달도 실행되지 않습니다. 포크가 자체 providers dict을
  제공하여 함수 calling을 활성화합니다.

## Wave 3 단계 A - 무엇이 배포되었나

Wave 3 단계 A는 HIL 파이프라인과 작성기가 안정된 표면 위에 구축될
수 있도록 operator-memory 경계를 도입합니다. Postgres 저장소, HIL 2차
승인 워크플로우, 작성기 통합은 Wave 3의 후속 단계에서 랜딩합니다.

- `services/core-control-plane/src/fdai/core/operator_memory/types.py` - `OperatorMemoryEntry`
  고정된 데이터 클래스 + 세 개의 enum: `ScopeKind` (값은 `resource-group`과
  `resource`로 제한. 더 넓은 범위는 거부되는데, 룰을 org 전역에서
  비활성화하는 것은 재정의가 아니라 룰 폐기이기 때문), `MemorySource`,
  `MemoryCategory`.
- `services/core-control-plane/src/fdai/core/operator_memory/store.py` - `OperatorMemoryStore`
  비동기 프로토콜 + `InMemoryOperatorMemoryStore` 업스트림 기본값. 모든
  쓰기는 동일한 정책 검증기를 실행하므로, 호출자가 저장소를 직접
  건드려서 Human 재정의 계약을 우회할 수 없습니다. 정책 코드는
  `OperatorMemoryPolicyError.code`로 노출되어 구조화된 텔레메트리를
  가능하게 합니다 (`empty_body`, `empty_scope_ref`, `scope_too_wide`,
  `missing_author`, `missing_approver`, `self_approval`, `invalid_ttl`,
  `duplicate_id`, `already_superseded`).
- `services/core-control-plane/src/fdai/core/operator_memory/sanitizer.py` -
  `detect_injection_markers`가 본문을 큐레이션된 prompt-injection 패턴
  목록에 대해 검사 (대소문자 무관. "ignore previous", "system:",
  role-hijack 토큰). `wrap_operator_note`가 accepted 본문을
  `<operator_note trusted="false" 작성자="..." scope_kind="..."
  scope_ref="..." category="...">...</operator_note>` 안에 렌더링하며,
  모든 속성과 내용 위치는 XML-escape되므로 항목이 closing tag를
  위조하거나 새 속성을 밀어넣을 수 없습니다.
- 추가 전용 시맨틱: 저장소는 저장된 항목을 절대 mutate하지 않습니다.
  replacement는 자체 행을 가지고, `supersede(entry_id, superseded_by)`가
  포인터를 threading합니다. Double 대체는 `already_superseded`
  정책 코드로 거부됩니다.
- 장기 보존 항목(`ttl_seconds=None`)는 Human 재정의 정책에 따라
  허용됩니다. TTL 값은 제공되는 경우 양수여야 합니다.
- 쓰기 경로가 작성기 레이어보다 먼저 주입 방어를 강제하므로,
  악의적인 본문은 저장소에 도달조차 하지 못합니다. 리뷰어가 승인
  시점에 수정하거나 항목이 폐기됩니다.

## Wave 3 단계 B 저장소 - 무엇이 배포되었나

Wave 3 단계 B는 `OperatorMemoryStore`의 영속 Postgres 백엔드를
랜딩하여, scope-narrowed 운영자 note가 프로세스 재시작을 견디고
작성기가 모든 T2 이벤트마다 조회할 수 있게 합니다. 단계 B의 나머지
절반(HIL 거부로부터 `OperatorMemoryEntry` 행을 materialize하는 HIL
2차 승인 **파이프라인**)은 별도 후속 작업이며 롤아웃 표에서 아직
`계획됨`입니다.

- `alembic/versions/20260706_0006_operator_memory.py` - 단일 테이블
  `operator_memory`, Python 정책과 미러링된 검사 제약:
  `scope_kind IN ('resource-group', 'resource')`,
  `btrim(body) <> ''`, `btrim(scope_ref) <> ''`,
  `category IN (...)`, `ttl_seconds IS NULL OR ttl_seconds > 0`,
  `lower(btrim(author)) <> lower(btrim(approved_by))`. Python-side
  검증기를 우회하는 호출자도 리뷰되지 않은 또는 self-approved
  항목을 랜딩할 수 없습니다.
- `superseded_by`는 self-referential FK. 추가 전용 불변식은
  `UPDATE ... SET body = ...`를 절대 issue하지 않음으로써 강제됩니다.
  유일한 갱신은 `FOR UPDATE`-locked 트랜잭션 내부의 `superseded_by`
  뿐이며, 저장소는 포인터를 덮어쓰는 대신 `already_superseded`를
  반환합니다.
- `services/core-control-plane/src/fdai/delivery/persistence/postgres_operator_memory.py` -
  `PostgresOperatorMemoryStore`가 in-memory 가짜와 동일한 비동기
  `OperatorMemoryStore` 프로토콜을 realize합니다. DSN +
  `statement_timeout_ms` 계약은 `PostgresStateStore`와 동일하므로 두
  어댑터를 같은 구성 표면에서 wire할 수 있습니다.
- `append()`가 커넥션 열기 **전에** 공유 `_reject_policy_violations`를
  호출 - 정책 오류는 in-memory 저장소와 동일한 코드
  (`empty_body`, `self_approval`, `invalid_ttl`, ...)의
  `OperatorMemoryPolicyError`로 표면. `id`의 PRIMARY-KEY 충돌은
  `duplicate_id` 코드로 번역되어 작성기가 백엔드 전반에서 단일 오류
  taxonomy를 보게 됩니다.
- `list_active_for_scope()`가 대체된과 만료된 행을 단일 SQL
  쿼리에서 필터링 -
  `NOW() - created_at < make_interval(secs => ttl_seconds)`,
  `_is_expired` 헬퍼의 시맨틱과 일치. 작성기는 post-filter할 필요가
  없습니다.
- `_row_to_entry()`가 naive `datetime` 값을 UTC로 coerce하고 ISO-8601
  / UUID 문자열 컬럼을 방어적으로 파싱하여 JSON 내보내기/가져오기 왕복이
  올바른 Python 타입에 landing.
- 통합 테스트(`services/core-control-plane/tests/persistence/test_postgres_operator_memory.py`)는
  pgvector + state-store 어댑터와 동일한 `FDAI_DATABASE_URL`
  unset 시 건너뜀 패턴을 따르며, 라이브 Postgres에서 덧붙이기 + 목록 +
  대체 + 만료 + duplicate-id + unknown-id-lookup을 커버합니다.
  Offline 유닛 테스트는 구성 검증, coerce 헬퍼, cross-backend 정책
  오류 동등성을 exercise하므로 파일이 데이터베이스 없이도 커버리지를
  유지합니다.

## Wave 3 단계 B 파이프라인 구획 1 - 무엇이 배포되었나

Wave 3 단계 B 파이프라인 구획 1은 HIL 거부 이유를 두 번째 별개
운영자가 승인한 후 저장된 `OperatorMemoryEntry`로 변환하는 순수
도메인 모듈을 랜딩합니다. 실제로 이를 invoke하는 HTTP / ChatOps
콜백은 후속 구획에 있습니다. 이 단계는 "brain" - Teams Adaptive
카드 버튼, 조정기 poll, fork-authored CLI 어느 것에서
트리거되든 동일 클래스가 2차 승인 로직을 처리합니다.

- `services/core-control-plane/src/fdai/core/operator_memory/hil_pipeline.py` -
  `HilRejectMaterializer(*, store, entry_id_fn=uuid4, now_fn=None)`가
  단일 비동기 메서드 `materialize(*, hil_response, second_approver,
  자료)`를 노출합니다. 결정론적 훅 (`entry_id_fn`, `now_fn`)이
  전역을 monkey-patch하지 않고도 테스트에서 id와 시각을 pin할
  수 있게 합니다.
- `HilRejectMaterial(scope_kind, scope_ref, category, source_ref,
  ttl_seconds=None, 메타데이터=...)`가 작업 흐름이 공급하는 컨텍스트
  (ChatOps 명령, HTTP 엔드포인트, 조정기 poll)를 운반합니다.
  `source_ref`는 관례적으로 `hil.reject:<approval_id>`이며 감사자가
  항목을 정확한 HIL 실행으로 역추적할 수 있게 합니다.
- `HilMaterializationError`의 5개 fail-fast 오류 코드가 저장소 접근
  전에 short-circuit: `wrong_decision` (거부 아님),
  `empty_reason` (기억할 만한 콘텐츠 없음),
  `missing_first_approver` (`HilResponse.approver_id` 없음),
  `missing_second_approver` (검토자 없음),
  `same_principal` (`strip().lower()` 정규화 후 rejecter가
  self-approve 시도). 마지막은 저장소의 `self_approval` 코드와
  의도적으로 구분되므로 UI가 "이 단계에서는 self-approve할 수
  없음"과 "저장소의 더 깊은 정책이 다른 이유로 거부"를 구별할 수
  있습니다.
- Store-side 정책 오류는 그대로 흐릅니다. Sanitizer가 이유에서
  prompt-injection 표시를 감지하거나 호출자의 `entry_id_fn`이
  중복 id를 반환하면, 저장소의 `OperatorMemoryPolicyError`
  (코드 `injection_marker_detected`, `duplicate_id` 등)가 호출자에게
  보이는 것 - materializer는 이를 절대 삼키거나 re-code하지
  않습니다.
- `core/`-safe 유지: 모듈은 `fdai.core.operator_memory`와
  `fdai.shared.providers.hil_channel` (프로토콜 패키지)에서만
  가져오기하므로 `scripts/quality/architecture/check-core-imports.sh`가 계속 통과합니다.
  `delivery.*` 가져오기 없음.

## Wave 3 단계 B 파이프라인 구획 2 - 무엇이 배포되었나

Wave 3 단계 B 파이프라인 구획 2는 `OperatorMemoryStore`를 조립
루트에 wire하여 operator-memory 레이어가 실제로 런타임에서 종단 간으로
도달 가능하도록 합니다. 구획 1이 `HilRejectMaterializer`를 배포했고
구획 3가 특정 second-approval 채널을 배포할 것입니다. 이 구획은
연결 조직 - 한 경로가 덧붙이기한 항목이 다음 이벤트에서 즉시 작성기에
보이게 만듭니다.

- `services/core-control-plane/src/fdai/runtime/providers.py`의 `_build_operator_memory_store()`가
  기존 `_build_audit_store()` 패턴을 미러링: `FDAI_OPERATOR_MEMORY_DSN`
  (컨테이너의 Key Vault 시크릿 참조로 채워짐)이 설정되면 wire가
  `PostgresOperatorMemoryStore`를 반환하고, 그렇지 않으면 결정론적
  `InMemoryOperatorMemoryStore` 가짜가 사용되어 작성기의
  operator-memory 레이어가 데이터베이스 없이도 종단 간으로 완전히
  wire됩니다. 포크가 `HilRejectMaterializer`로 항목을 시드하면 다음
  `compose()` 호출에서 추가 배관 없이 레이어가 materialize되는 것을
  봅니다.
- `_finalize_llm_bindings()`가 이제 저장소를 생성하여
  `DefaultPromptComposer(registry=..., operator_memory_store=...)`에
  인계합니다. 시작 `prompt_composed` 구조화 로그가 구체적인
  클래스 이름을 담은 `operator_memory_store` 필드를 얻으므로
  배포가 로그를 grep하여 프로세스가 연결한 백엔드를 검증할 수
  있습니다.
- 백엔드 선택은 defense-in-depth: 빈 문자열 DSN은 "unset"으로 취급
  (`if dsn:`가 `""`에 대해 falsy)되므로 mis-quoted env var가 broken
  Postgres 어댑터를 instantiate하는 대신 in-memory 가짜로 대체 경로
  합니다. 테스트가 이 동작을 회귀 방지로 pin합니다.
- `services/core-control-plane/tests/test_main_helpers.py`의 세 개 offline 테스트가 각 env-var
  상태에 대해 헬퍼가 올바른 백엔드를 wire함을 증명합니다. 경계의
  작성기 측은 이미 `services/core-control-plane/tests/core/prompts/test_composer.py`가 커버하므로
  종단 간 wire는 조립으로 증명됩니다.

## Wave 3 단계 C-1 - 무엇이 배포되었나

Wave 3 단계 C-1은 전달 어댑터를 아직 건드리지 않은 채 운영자
기억을 작성기에 스레딩합니다. 단계 C-2가 조립을 per-event 요청
경로로 이동시켜 실제로 note가 런타임에 모델에 도달하도록 합니다.

- `PromptLayer.OPERATOR_MEMORY` - 작성기의 기억 레이어가 사용하는
  새로운 synthetic 계층 값. 프롬프트 아티팩트의 JSON 스키마는 이 값을
  의도적으로 나열하지 않습니다: operator-memory 콘텐츠는 저장소에서
  materialize되는 데이터 레이어이지 YAML 조각으로 저작되지 않습니다.
- `OperatorScope(resource_group_ref, resource_ref=None)` - 작성기가
  해석하는 튜플. ``None`` 범위는 "이번 호출엔 운영자 기억 없음"을
  의미합니다. 프로덕션 per-event 전달은 정규화된 이벤트 페이로드에서
  가져온 실제 범위를 제공합니다.
- `DefaultPromptComposer(operator_memory_store=..., scope=...)`가 저장소를
  두 번 조회 (항상 RG 레벨, 범위가 리소스 참조를 가진 경우 리소스
  레벨도) 하고, resource-group note를 먼저 리소스 note를 나중에
  concatenate하여 가장 구체적인 지침이 사용자 턴에 가장 가까이
  위치하게 합니다.
- 조회된 각 항목은 `wrap_operator_note`로 wrap되어 `trusted="false"`
  불변식을 보존합니다. 대체된 / 만료된 항목은 저장소의
  `list_active_for_scope`가 필터링합니다. 작성기는 수명 주기 상태를
  재검사하지 않습니다.
- `StaticPromptComposer` (테스트 가짜)가 모든 호출에서 `(capability_id,
  범위)` 쌍을 추적하므로 테스트가 조립된 프롬프트를 검사하지 않고도
  조립 컨텍스트를 assert할 수 있습니다.
- 작성기는 세 가지 명시적 경우에 **기억 레이어를 발행하지 않습니다**:
  1. `operator_memory_store`가 주입되지 않음,
  2. 호출 시점에 `scope`가 `None` (시작 조립 경로),
  3. 저장소가 해석된 범위에 대해 활성 항목을 0개 반환.

## Wave 3 단계 C-2 - 무엇이 배포되었나

Wave 3 단계 C-2는 프롬프트 조립을 startup-only에서 per-event로 이동시켜
운영자 기억 엔트리(포크가 제공하는 해석기 통해)와 canary 토큰이
모든 모델 호출에서 회전하도록 합니다. 이 변경은 가산입니다:
작성기를 전달하지 않는 조립 루트는 이전처럼 정적
`config.system_prompt`를 계속 전송합니다.

- `AzureOpenAICrossCheckModel.__init__`이 세 개의 선택적 키워드 인자를
  갖게 됩니다: `prompt_composer`(`PromptComposer` 인스턴스),
  `capability_id`(작성기에서 찾을 역할 키),
  `scope_resolver`(`Callable[[QualityCandidate], OperatorScope | None]`).
- 생성 시점에 cross-consistency 강제: `prompt_composer`와
  `capability_id`는 함께 제공되어야 하며, `capability_id`는 비어있지
  않아야 하고, `scope_resolver`는 작성기 없이 나타날 수 없음(먹일
  대상이 없는 해석기는 배선 버그).
- `_resolve_system_prompt(candidate)`가 모든 `propose()` 턴에서 먼저
  호출됩니다. 작성기가 wire되어 있으면
  `await composer.compose(capability_id=..., scope=resolver(candidate))`로
  재조립하고, 그렇지 않으면 `config.system_prompt` 스냅샷을 반환합니다.
- **작성기 실패는 `RuntimeError`를 raise합니다** (메시지에 기능
  id 포함). 이는 기존 quality-gate 에러 경로를 통해 실행을 HIL로
  라우팅합니다. 어댑터는 절대 대체 경로 텍스트로 조용히 degrade하지
  않습니다 - 그러면 루프가 의존하는 운영자 기억나 fresh canary
  토큰 없이 stale 프롬프트를 배송하게 됩니다.
- `bind_azure_llm_bindings`가 대응하는 `prompt_composer` +
  `scope_resolver` 매개변수를 갖고, 두 T2 reasoner를 각자의
  role-specific 기능 id (`t2.reasoner.primary` /
  `t2.reasoner.secondary`)로 생성합니다. 교차 검증 정족수가 역할별로
  일관된 instruction 맥락을 보게 되며 단일 공유 프롬프트가 아닙니다.
- `runtime.configuration._finalize_llm_bindings`가 이제 업스트림 작성기를
  `scope_resolver=None`으로 전달합니다. `QualityCandidate.target_resource_ref`를
  `OperatorScope`로 매핑하는 ARM-id 파서는 포크의 조립 루트에
  있습니다. 업스트림 저장소는 CSP-neutral을 유지합니다.
- 시작 `composer.compose(capability_id="t2.reasoner.primary")` 호출은
  유지됩니다: 프로세스 시작 시 카탈로그 + 스키마를 검증하고
  observability용 `prompt_composed` 구조화 로그를 발행합니다. 실제 운영
  이벤트에 대해 모델이 보는 `system_text`는 더 이상 이것이 아니어도
  마찬가지입니다.

## Wave 3 단계 D-1 - 무엇이 배포되었나

Wave 3 단계 D-1은 recognition-probe KPI의 순수 평가기 부분을
랜딩합니다. 단계 D-2가 작성기에게 레이어별 canary 토큰 삽입을
가르치고, 숫자를 시나리오 실행기를 통해 대시보드에 배선합니다.

- `services/core-control-plane/src/fdai/core/measurement/prompt_probe.py` - 네 개의 타입이 지정된
  입력/출력 데이터 클래스 (`RequiredField`, `ExpectedResponse`,
  `CitationScores`, `RecognitionResult`)와 네 개의 순수 평가기:
  `evaluate_adherence` (JSON 유효성 + 필드별 존재/타입/비-empty를
  구조화된 위반 코드로), `evaluate_canary_echoes` (raw 응답에 대한
  대소문자를 구분하는 부분 문자열 매칭. 소문자로 echo된 응답은 recognition
  으로 인정되지 않음), `evaluate_citations` (인용된 룰 id 집합에
  대한 정밀도 / 재현율 / F1. 중복과 빈 문자열은 무시),
  `score_recognition` 집계.
- 구조화된 위반 코드: `not-a-json-object`, `missing-field:X`,
  `wrong-type:X`, `empty-field:X`로 KPI 대시보드가 free 텍스트 정규식
  없이 bucketing 가능.
- Non-JSON 응답은 필드별 실패로 팬-아웃하지 않고 정확히 하나의
  `not-a-json-object` 집계 위반만 보고 (같은 defect의 double
  counting은 KPI를 오염).
- `_extract_cited_ids`는 응답을 관대하게 읽습니다: 필드 누락,
  잘못된 타입, non-string 멤버는 모두 인용 zero 재현율로
  표면될 뿐 raise되지 않음. Recognition 탐색은 절대 hard
  실패 소스로 변하지 않습니다.

## Wave 3 단계 D-2a - 무엇이 배포되었나

Wave 3 단계 D-2a는 조립된 각 레이어의 헤드에 canary 토큰을 배치하여
recognition 탐색의 canary-echo 평가기가 스코어링할 실제 표시를
갖게 합니다. 단계 D-2b가 그 토큰과 D-1 평가기를 소비하는 시나리오
실행기를 추가하여 대시보드 rows를 발행합니다.

- `CanaryGenerator` 프로토콜이 평가기 옆
  `core/measurement/prompt_probe.py`에 위치합니다.
  `SecretsCanaryGenerator`는 프로덕션 unpredictability를 위해
  :mod:`secrets`를 사용. `DeterministicCanaryGenerator`는 테스트와
  재생 실행을 위해 미리 시드된 ``{layer_id: 토큰}`` 대응을 받음.
- `ComposedPrompt.canary_tokens: Mapping[str, str]`가
  ``layer_id -> 주입된 토큰`` 쌍을 기록. 기본값은 빈 대응이므로
  generator 없는 작성기는 Wave 3 단계 C-1과 동일한 출력 형태를
  생성.
- `DefaultPromptComposer(canary_generator=...)`가 새 명시적 선택.
  주입 시 작성기는 모든 레이어 본문 (base, 작업 packs, 도구
  매니페스트, 운영자 기억) 앞에 ``[canary:<layer_id>=<TOKEN>]\n``를
  prepend하고, 각 `LayerRef.token_estimate`를 새로 고침하여
  매니페스트가 모델이 실제로 보는 것을 반영하게 함.
- 프로덕션 동작은 변경 없음: `runtime.configuration._finalize_llm_bindings`가
  canary generator를 넘기지 않으므로 현재 wire 프롬프트는 pre-D-2a
  형태와 동일하게 유지됩니다.
- Canary 주입 후의 토큰 추정치 업데이트가 recognition-probe KPI의
  첫 구체적 입력입니다. Post-canary 토큰 예산이 상한을 넘는
  레이어는 D-2b의 ``프롬프트.token_budget.exceeded_rate`` 시그널 후보.

## Wave 3 단계 D-2b-i - 무엇이 배포되었나

Wave 3 단계 D-2b-i는 배치의 per-sample `RecognitionResult` 값을
발행 가능한 하나의 요약으로 변환하는 KPI 집계를 랜딩합니다.
단계 D-2b-ii가 시나리오 고정본 형식, 실행기 CLI, 실제 대시보드 행
emission을 추가합니다.

- `RecognitionKpiSummary` 고정된 데이터 클래스가 설계 doc이 요구하는
  네 KPI를 담습니다: `adherence_pass_rate`, per-code
  `adherence_violation_counts`, `per_layer_canary_echo_rate`,
  `mean_citation_f1`.
- `summarize_recognition(results)`가 순수 집계 함수. 격리
  테스트 가능하며 결과가 어떻게 생성되었는지에 무관 - shadow 모드
  실행기, 오프라인 고정본 재생, CI 배치 모두 동일한 형태를 소비.
- **레이어별 측정된 분모**: 레이어의 echo 비율은 실제로 그 레이어를
  측정한 샘플 수(그 id가 `canary_echoes`에 존재)로 계산되며 배치
  크기가 아닙니다. 기능의 절반만 exercise한 실행이 모든 echo
  비율을 조용히 반으로 낮추지 못합니다.
- **인용 mean이 스코어되지 않은 샘플 제외**: 호출자가
  `expected_cited_rule_ids`를 넘기지 않은 샘플은
  `result.citations is None`이며 `mean_citation_f1`에서 제외됩니다.
  스코어된 샘플만 기여하므로 인용 커버리지가 non-scored 실행에
  의해 희석되지 않음.
- **빈 배치는 중립, 0이 아님**: 빈 결과 리스트는
  `mean_citation_f1 is None`인 요약을 반환하므로 대시보드 emitter가
  오해의 소지가 있는 0.0을 발행하는 대신 인용 행을 건너뜀.
- **측정 안 된 레이어는 나타나지 않음**: 지도는 "측정됨, 절대 echo
  안 됨"(비율 0.0)과 "전혀 측정 안 됨"(키 부재)을 명확히 구분하므로,
  `< 50% echo` alerting 룰이 아무도 안 본 레이어에 대해 fire할 수
  없습니다.

## Wave 3 단계 D-2b-ii-alpha - 무엇이 배포되었나

Wave 3 단계 D-2b-ii-alpha는 배치 스코어링과 라이브 시나리오 실행을 위한
런타임 API를 전달합니다. Catalog-as-code YAML 형식, CLI, 대시보드
emission은 ``beta`` / ``gamma`` 서브 스텝에서 랜딩합니다.

- `services/core-control-plane/src/fdai/core/measurement/prompt_probe_runner.py` -
  `RecognitionSample` (composed 프롬프트 + 응답 + 예상),
  `RecognitionRunReport` (per-sample 결과 + KPI 요약을 한 번들에),
  `RecognitionScenario` (조립 가능한 spec: 기능 id + 선택적
  범위 + 예상 계약), `ScenarioResponder` 비동기 프로토콜 (포크가
  실제 모델을 wire. 테스트는 canned 응답자 제공).
- `score_batch(samples)`가 사전 조립된 배치를 리포트로 변환하는 순수
  집계. `sample.expected.canary_tokens`가 미설정이고 작성기가
  `composed_prompt.canary_tokens`에 canary를 각인한 경우, 스코어러가
  작성기 토큰을 **자동 승격**합니다 - 시나리오 저자가 canary 지도를
  중복 정의하지 않으며, 두 형태 간의 표류가 구조적으로 불가능.
- 명시적 `expected.canary_tokens` 값은 auto-promotion을 재정의하여
  회귀 고정본이 작성기가 변경되어도 원본 실행의 토큰을 pin할
  수 있게 함.
- `run_scenarios(composer, responder, scenarios)`가 라이브 러너
  엔트리포인트. 시나리오별로 `capability_id` + `scope`로 조립하고,
  응답자를 대기한 뒤 `score_batch`로 위임. 범위는 그대로
  스레딩되므로 범위 바운드 operator-memory 레이어가 실제로
  recognition 실행에서 도달 가능.
- I/O 프로바이더와 YAML 고정본은 아직 배포되지 않음 - 업스트림은
  런타임 경계를 순수하게 유지하여 포크 테스트가 Azure 의존성 없이
  어떤 작성기와 응답자로도 driver할 수 있게 합니다.

## Wave 3 단계 D-2b-ii-beta - 무엇이 배포되었나

Wave 3 단계 D-2b-ii-beta는 recognition-probe 표면의 catalog-as-code
절반을 랜딩합니다: 포크가 라이브 작성기 / 응답자와 독립적으로
저작 가능한 on-disk 시나리오 형식.

- `rule-catalog/prompts/scenarios/schema/scenario.schema.json` -
  모든 시나리오 YAML이 검증되는 JSON 스키마. `capability_id`가
  필수. `scope`는 선택적 (있으면 `resource_group_ref` 필수,
  `resource_ref` 선택적), `expected.required_fields`는 알려진
  `expected_type`(`string` / `object` / `array`)을 가진 필드가 최소
  하나 필요.
- `rule-catalog/prompts/scenarios/README.md` - prompts + 도구
  서브시스템 README를 미러링한 디렉토리 계약.
- `services/core-control-plane/src/fdai/core/measurement/prompt_probe_loader.py` -
  prompts와 도구 레지스트리와 동일한 aggregate-error 표면을 가진
  `load_scenarios(catalog_root) -> tuple[RecognitionScenario, ...]`.
  빈 카탈로그가 legal이므로 포크는 첫 시나리오를 저작하기 전에 경계를
  채택 가능.
- `FileSystemPromptRegistry`가 이제 `tools/`와 `scenarios/` 두 peer
  서브시스템을 모두 건너뜀하므로 시나리오 YAML이 실수로 프롬프트 스키마
  검증기를 trip할 수 없음.

## Wave 3 단계 D-2b-ii-gamma-1 - 무엇이 배포되었나

Wave 3 단계 D-2b-ii-gamma-1은 `RecognitionRunReport`를 target-neutral
메트릭 행 리스트로 변환하는 순수 KPI 행 emitter를 랜딩합니다. 단계
gamma-2가 CLI를 wire하여 이 rows를 소비합니다.

- `services/core-control-plane/src/fdai/core/measurement/prompt_probe_emit.py` -
  `KpiRow(metric, value, unit, dimensions)` + `RowUnit` enum
  (`ratio`, `count`) + 5개 메트릭 이름 상수
  (`prompt.recognition.sample_count`,
  `prompt.recognition.adherence.pass_rate`,
  `prompt.recognition.adherence.violation_count`,
  `prompt.recognition.canary_echo_rate`,
  `prompt.recognition.citation_f1.mean`).
- `emit_kpi_rows(report, *, dimensions=None)`이 호출자가 제공한 base
  dimension (예: `{"capability": "t2.reasoner.primary"}`)을 모든 발행
  행에 병합하므로 per-capability 실행이 싱크에서 구별 가능한 행을
  publish.
- 테스트로 baked in된 emission 규칙:
  - **빈 배치**도 여전히 `sample_count = 0` 발행 - 항상 샘플 개수를
    publish하는 대시보드 시리즈가 조용히 사라지지 않음;
  - **Adherence 통과 비율**는 `sample_count > 0`일 때만 발행
    (misleading `0/0` 회피);
  - **위반 개수**는 코드별 행 하나씩. `code`로 dimension되며
    알파벳 순으로 정렬되어 안정된 대시보드 순서를 생산자;
  - **레이어별 echo 비율**는 layer_id별 행 하나씩. 집계의
    measured denominator 사용 → 배치의 절반만 측정된 레이어가
    조용히 dilute되지 않음;
  - **인용 F1**은 적어도 하나의 샘플이 스코어되었을 때만 발행
    (`mean_citation_f1 is not None`) - 인용 스코어링 opt-out
    배치가 misleading `0.0`을 publish하지 않음.
- 메트릭 별 라벨 (`code`, `layer_id`)이 메트릭 계열 간 절대 leak되지
  않음 - 각 행의 dimension 집합은 자신의 메트릭에만 범위됨.

## Wave 3 단계 D-2b-ii-gamma-2 - 무엇이 배포되었나

Wave 3 단계 D-2b-ii-gamma-2는 smoke-runnable CLI와 응답자 헬퍼로
recognition-probe 챕터를 마무리합니다. Recognition 메트릭 이름을
명명하는 대시보드 패널은 후속 문서 편집에서 P0 KPI 대시보드와 함께
랜딩합니다. 이 단계는 런타임에 집중합니다.

- `services/core-control-plane/src/fdai/core/measurement/prompt_probe_testing.py` -
  `AbstainResponder`는 매 호출마다 canned `hil.escalate` JSON 액션을
  반환하므로 업스트림 CLI가 실제 운영 모델 없이 smoke-run 가능하며,
  `RecordingResponder`는 큐에서 canned 답변을 pop하면서
  `(capability_id, composed_system_text)` 쌍을 assertion용으로
  기록합니다.
- `AbstainResponder`는 construction 시점에 JSON 본문을 **한 번만**
  직렬화하므로 모든 `respond` 호출은 byte-identical 텍스트를 반환합니다.
  시간에 따라 응답을 비교하는 shadow 실행이 허위 variation을 보지
  않습니다.
- `services/core-control-plane/src/fdai/core/measurement/prompt_probe_cli.py` -
  `run_from_catalog(catalog_root, responder)`가
  `FileSystemPromptRegistry` + `DefaultPromptComposer`를 wire하고
  `load_scenarios(catalog_root)`를 호출한 후 `run_scenarios`에
  위임합니다. `main()`은 ``python -m
  fdai.코어.측정.prompt_probe_cli`` 뒤의 sync 항목 지점.
- CLI exit 코드는 기존 `runners_cli.py` 계약과 일치: ``0`` = 실행 완료
  (빈 카탈로그도 legal 결과, `sample_count = 0` 행 출력),
  ``2`` = 카탈로그 루트 없음, ``3`` = stderr에 스택 추적을 남기는
  unexpected exception.
- 출력 형태: stdout에 라인당 JSON 객체 하나씩, 키 정렬됨.
  `jq`/`awk`/observability 파이프라인이 추가 파싱 없이 바로 ingest 가능.
- CLI는 절대 Azure 엔드포인트를 건드리지 않음. 포크가 실제 운영 조립
  루트에서 `run_from_catalog`를 가져오기하고 실제 `ScenarioResponder`
  (Wave 2.5-B에서 만든 Azure OpenAI 어댑터를 wire하는)를 전달합니다.

## Wave 4 alpha - 무엇이 배포되었나

Wave 4 alpha는 비평자 역할의 타입이 지정된 형태와 shadow-mode 프롬프트 시드를
랜딩합니다 - 실제 운영 배선 없는 비평자의 "brain". Wave 4 beta가 Azure
어댑터를 배포하고 Wave 4.5가 제안자 / 비평자 / Judge 루프를
orchestration합니다. 이 alpha 단계는 의도적으로 dormant이므로 타입 +
평가기가 현재 T2 흐름에 위험 없이 fork-authored 탐색과 미래
오케스트레이터 코드에서 소비 가능합니다.

- `services/core-control-plane/src/fdai/core/quality_gate/critic.py` -
  `CriticStance` (`agree` / `challenge` / `abstain`),
  `CriticSeverity` (`low` / `medium` / `high`),
  `CriticObjection` (blank 인용 또는 description을 거부하는
  `__post_init__`가 있는 고정된 데이터 클래스),
  `CriticOutput` (stance + objections + citations + `QualityCandidate`와
  동일한 "no 모델 self-report" 계약을 따르는 선택적 확신도
  signals),
  `CriticVerdict` (`endorse` / `retry` / `abort` / `abstain`),
  그리고 `CriticModel` 프로토콜.
- `evaluate_critic_output(output, *, known_rule_ids)`가 하나의
  `CriticOutput`을 하나의 판정으로 reduce합니다. 테스트로 baked-in된
  규칙:
  - `ABSTAIN` stance는 `ABSTAIN` 판정으로 short-circuit (이의
    검사 없음);
  - `AGREE` + 어떤 HIGH-severity 이의이라도 있으면 `ABORT` -
    self-contradiction은 절대 honor하지 않음;
  - 그 외 `AGREE`는 `ENDORSE` (AGREE와 함께 있는 LOW-severity nit도
    여전히 endorsement);
  - 빈 이의 리스트를 가진 `CHALLENGE`는 `ABSTAIN` (증거 없는
    도전자는 defect);
  - 알 수 없음 룰 id를 인용하는 이의가 있는 `CHALLENGE`는
    `ABSTAIN` (ungrounded 이의는 감사 이력을 깨뜨림);
  - 어떤 HIGH-severity 이의이라도 있는 `CHALLENGE`는 `ABORT`;
  - 그 외 `CHALLENGE`는 `RETRY`.
- `rule-catalog/prompts/base/t2-critic.v1.yaml` - `layer: critic`,
  `applies_to: [t2.critic]`, `default_mode: shadow`. 본문이 평가기가
  강제하는 구조화된 JSON 계약(stance + 근거에 기반한 objections +
  citations)을 서술하므로 실제 운영 비평자가 parseable 출력을 발행합니다.
  `t2.critic` 기능은 아직 `llm-registry.yaml`에 없음; 시드는
  Wave 4 beta가 기능을 추가하고 어댑터를 wire할 때까지 dormant.
- 비평자는 이 alpha에서 `QualityGate`에 wire되지 않음. 결정론적
  검증기가 여전히 유일한 실행 권한; 비평자는 (wire되면)
  오케스트레이터가 감사 이력과 Wave 4.5 제안자 재시도로 threading하는
  이의를 표면합니다.
- `core/`-safe 유지: 모듈은 `fdai.core.quality_gate.gate`와
  stdlib에서만 가져오기; `delivery.*` 또는 LLM SDK 없음.
  `scripts/quality/architecture/check-core-imports.sh`가 74 files로 계속 통과합니다.

## Wave 4 beta-1 - 무엇이 배포되었나

Wave 4 beta-1은 Azure OpenAI를 상대로 실제 비평자 호출을 하는 Azure
어댑터를 랜딩합니다. 의도적으로 아직 조립 루트에 **wire하지
않음** - 배포된 `rule-catalog/prompts/base/t2-critic.v1.yaml` 시드는
`default_mode: shadow` 유지이므로 실행 중인 배포는 동작 변화를 보지
않습니다. Wave 4 beta-2가 `llm-registry.yaml`에 `t2.critic` 기능
엔트리를 추가하고 어댑터를 조립 루트로 threading합니다.

- `services/core-control-plane/src/fdai/delivery/azure/llm/critic.py` -
  `AzureOpenAICriticModelConfig` (엔드포인트, 배포, **필수**
  `system_prompt`, api_version, temperature, max_tokens,
  timeout_seconds) + `AzureOpenAICriticModel`의 단일 비동기
  `critique(candidate, proposer_output)` 메서드가
  `response_format={"type": "json_object"}`로
  `/openai/deployments/{deployment}/chat/completions`에 게시합니다.
- 구성 검증은 교차 검증 어댑터의 fail-fast 계약을 미러링:
  non-https 엔드포인트, 빈 배포, 빈 system_prompt, zero /
  out-of-range temperature, zero max_tokens, zero 시간 초과 모두
  생성 시점에 `ValueError`를 raise합니다.
- User-turn 묶음에 후보와 제안자 출력이 정본
  `(sort_keys=True)` JSON 모양으로 들어가 있어 재생과 감사가
  결정론적입니다.
- 응답 파서가 안전성 표면입니다. 모든 실패는 descriptive 메시지와
  함께 `RuntimeError`를 raise하므로 미래의 토론 오케스트레이터가
  malformed 비평을 조용히 수용하는 대신 HIL로 라우팅합니다:
  - non-string / 빈 `content`;
  - 유효한 JSON이 아닌 `content`;
  - non-object로 decode되는 `content`;
  - 누락 또는 non-string `stance`;
  - `CriticStance` enum 밖의 `stance`;
  - non-array `objections`;
  - objections 리스트의 non-object 항목;
  - 이의의 누락 / non-string `severity`;
  - `CriticSeverity` enum 밖의 `severity`;
  - non-string `cited_rule_id` / `description`;
  - non-string / non-null `alt_action_type` (빈 문자열은 `None`으로
    정규화되어 다운스트림 코드가 단일 "no alternate" 표현을 갖도록);
  - non-string / blank 인용 항목.
- `CriticObjection.__post_init__`가 두 번째 방어선 - 파서가 whitespace-
  only description을 놓쳐도 데이터 클래스가 객체가 어댑터를 escape하기
  전에 `ValueError`를 raise합니다.
- `services/core-control-plane/tests/delivery/azure/llm/test_critic.py`가 6개 구성 검증 경로 +
  4개 성공 파싱 + 10개 실패 시 차단 파싱 + HTTP 상태 전파를
  커버합니다. `httpx.MockTransport`를 사용하므로 실제 운영 네트워크 불필요.
- `delivery/azure/llm/__init__.py`에서 교차 검증 어댑터와 함께
  등록됨; beta-2가 랜딩될 때 조립 루트가 가져오기할 준비 완료.

## Wave 4 beta-2 - 무엇이 배포되었나

Wave 4 beta-2는 비평자 어댑터를 명시적 선택 바인딩으로 조립 루트에
wire합니다. 레지스트리에 `t2.critic` 기능을 추가하지 않는 포크는
pre-Wave-4 형태 유지; 기능을 해석하는 포크는
`LlmBindings.critic_model`이 Wave 4.5 토론 오케스트레이터를 위한 실제 운영
`AzureOpenAICriticModel`에 바인딩됩니다.

- `rule-catalog/llm-registry.yaml`에 `t2.critic` 엔트리 추가:
  `invocation: on_disagreement`와 Anthropic-first 선호 설정으로 비평자
  발행기가 OpenAI-first 제안자와 구분되도록 (토론 설계 준수).
- `composition.LlmBindings`가 선택적 `critic_model` 필드
  (`CriticModel | None`)를 갖게 되어 Critic-off / Critic-on 경로에서
  경계 표면이 uniform.
- `bind_azure_llm_bindings`가 선택적 `critic_system_prompt` 파라미터
  추가. 기능 해석과 프롬프트 공급 두 조건 모두 만족될 때만
  비평자 바인딩 - 부분 포크 구성 (기능 있지만 프롬프트 없음, 또는
  반대)이 절대 half-wired 어댑터를 landing하지 못함.
- `runtime.configuration._finalize_llm_bindings`가
  `composer.compose(capability_id="t2.critic")`으로 비평자 system
  프롬프트를 조립. 카탈로그에 비평자 base 프롬프트가 없어 compose가
  `LookupError`를 raise하면 wire가 `critic_model=None`으로 조용히
  degrade하고 `critic_prompt_missing` 구조화 로그를 발행하여
  배포가 이유를 grep 가능. 성공 시 기존 `prompt_composed`
  엔트리와 함께 `critic_prompt_composed` 발행.
- `services/core-control-plane/tests/test_composition_llm.py`의 세 테스트가 three-way 매트릭스 pin:
  (기능 + 프롬프트) → 바인딩, (기능만) → None, (프롬프트만,
  기능 없음) → None.

## Wave 4.5 alpha - 무엇이 배포되었나

Wave 4.5 alpha는 Judge 역할의 타입이 지정된 형태와 shadow-mode 프롬프트
시드를 랜딩합니다 - 비평자 Wave 4 alpha 구획을 미러링. Judge는
의도적으로 smaller 모델 (`t2.*`가 아닌 `t1.judge`에 바인딩) - 토론
오케스트레이터 설계 준수; 계층 하락이 제안자 / 비평자 쌍이 비쌀 때도
Judge의 per-event 비용을 한계.

- `services/core-control-plane/src/fdai/core/quality_gate/judge.py` -
  `JudgeDecision` (`accept` / `revise_and_retry` /
  `escalate_hil`), `JudgeOutput` (blank justification을 거부하는
  `__post_init__`을 가진 고정된 데이터 클래스),
  `JudgeVerdict` (`proceed` / `retry` / `escalate`), 그리고
  `JudgeModel` 프로토콜.
- `evaluate_judge_output(output, *, known_rule_ids)`가 하나의
  `JudgeOutput`을 하나의 판정으로 reduce합니다. 규칙:
  - `ACCEPT`와 known 인용만 -> `PROCEED`;
  - `ACCEPT`와 알 수 없음 인용 -> `ESCALATE`
    (ungrounded acceptance는 honor 안 함);
  - `REVISE_AND_RETRY` + non-blank `retry_directive` + known
    인용만 -> `RETRY`;
  - `REVISE_AND_RETRY`와 누락된 / blank directive ->
    `ESCALATE` (제안자가 뭘 바꿀지 모름);
  - `ESCALATE_HIL` -> `ESCALATE`.
- `rule-catalog/prompts/base/t2-judge.v1.yaml` - `layer: judge`,
  `applies_to: [t1.judge]`, `default_mode: shadow`. 본문이
  평가기가 강제하는 JSON 계약을 서술하므로 실제 운영 Judge가
  parseable 출력 발행. `t1.judge` 기능은 이미
  `llm-registry.yaml`에 있으므로 레지스트리 변경 불필요.
- `core/`-safe 유지: `fdai.core.quality_gate.gate` +
  `fdai.core.quality_gate.critic` (둘 다 peer 모듈) + stdlib
  에서만 가져오기.

## Wave 4.5 beta - 무엇이 배포되었나

Wave 4.5 beta는 Azure Judge 어댑터를 랜딩; Wave 4 beta-1 형태를
미러링.

- `services/core-control-plane/src/fdai/delivery/azure/llm/judge.py` -
  `AzureOpenAIJudgeModelConfig` (엔드포인트, 배포,
  **필수** `system_prompt`, api_version, temperature,
  max_tokens, timeout_seconds) + `AzureOpenAIJudgeModel`의 단일
  비동기 `judge(candidate, proposer_output, critic_output)` 메서드가
  `response_format={"type": "json_object"}`로 `chat/completions`
  에 게시.
- User-turn 묶음에 후보 + 제안자 출력 + 비평자의
  stance / objections / citations가 정본 `(sort_keys=True)`
  JSON 모양으로 들어가 재생과 감사가 결정론적.
- Strict 실패 시 차단 파서: non-JSON 내용, non-object 페이로드,
  누락 / non-string / enum-invalid `decision`, non-string
  `justification`, non-string / non-null `retry_directive`,
  non-array `citations`, non-string 인용 항목 - 모두
  `RuntimeError` raise. `JudgeOutput.__post_init__`이 blank
  justification을 두 번째 방어선으로 catch.
- `services/core-control-plane/tests/delivery/azure/llm/test_judge.py`의 20개 테스트가
  `httpx.MockTransport`로 6개 구성 검증 + 4개 성공 파싱 + 10개
  실패 시 차단 파싱 커버.
- 아직 조립 루트에 wire되지 않음; Wave 4.5 gamma가
  오케스트레이터를 만들고 Wave 4.5 delta가 실제 운영 `QualityGate`로 전체
  threading.

## Wave 4.5 gamma - 무엇이 배포되었나

Wave 4.5 gamma는 `DebateOrchestrator` 코어 모듈을 랜딩: 하나의
클래스 + 하나의 구성 + 하나의 `DebateOutcome` 기록이 제안자
후보 주변에서 비평자와 Judge를 조율. 이것이 `core/`에서 Wave 4.5
챕터를 닫음; Wave 4.5 delta가 오케스트레이터를 실제 운영 `QualityGate`에
wire.

- `services/core-control-plane/src/fdai/core/quality_gate/debate.py` -
  `DebateOrchestrator(*, critic, judge, config=None)`;
  `DebateOrchestratorConfig(max_rounds=1)`이 Wave 4.5에서
  `[0, 1]` 밖의 값을 거부하는 strict `__post_init__`을 가짐 (나중에
  올리려면 명시적 reviewable 편집);
  `ProposerRetry` 타입 별칭 for 호출자가 공급하는 제안자 재시도
  콜백 (`Callable`로 유지되어 `delivery.*` 가져오기가 `core/`에
  누출 안 됨);
  `DebateVerdict` (`proceed` / `abort`)와
  `DebateOutcome` (판정 + 사유 + 최종 제안자 출력 + 전체
  대화 기록 필드 + rounds counter + `error_class`).
- 하나의 `async run(...)` 메서드가 전체 루프 드라이브:
  1. 비평자 턴 1 -> ABORT 또는 ABSTAIN이면 **Judge 호출을 소비하지
     않고** `DebateVerdict.ABORT`로 short-circuit (token-cost 가드가
     테스트 스위트에 baked-in);
  2. Judge 턴 1 -> `PROCEED` 즉시 반환; `ESCALATE` abort;
     `RETRY` 두 번째 라운드 실행;
  3. 재시도 -> `retry_proposer(candidate, directive)` invoke
     (`max_rounds >= 1`일 때 필수 파라미터; 누락 시 호출 시점에
     `ValueError` raise하여 포크 구성 버그가 fail-fast);
  4. 비평자 턴 2 -> ABORT / ABSTAIN 모두 abort;
  5. Judge 턴 2 -> `PROCEED`는 `rounds=2`로 반환; 나머지는 모두
     abort (라운드 2의 `RETRY`는 `max_rounds` 초과이므로 refused).
- 모든 어댑터 예외에 **실패 시 차단**. `except Exception` 브랜치가
  두 라운드 모두에서 비평자 / Judge / 제안자 실패를 catch하여
  `error_class`가 보존된 `DebateVerdict.ABORT` 생산. 지금까지 누적된
  토론 대화 기록 (비평자 출력, Judge 출력, previous-round
  verdicts)가 `DebateOutcome`에 threading되어 감사 로그가 토론이
  얼마나 진행됐는지 정확히 표시 가능.
- `services/core-control-plane/tests/quality_gate/test_debate.py`의 14개 테스트가 커버: 구성
  검증 (2), retry-argument-required (1), Round-1 happy 경로 +
  비평자 ABORT short-circuit + 비평자 ABSTAIN short-circuit + Judge
  escalate (4), 재시도 라운드 + max_rounds=0 거절 + 재시도 비평자
  ABORT + Judge re-retry 거절 (4), `error_class`가 보존된 세 오류
  경로.

## Wave 4.5 delta-1 - 무엇이 배포되었나

Wave 4.5 delta-1은 Judge 어댑터를 조립 루트에 wire하고 두 역할
모델 모두 바인딩되면 `DebateOrchestrator`를 자동 생성합니다. Container가
이제 사용 준비된 토론 경계를 노출; delta-2가 두 모델 교차 검증
정족수 대신 어떤 실제 운영 이벤트를 그것으로 흐르게 할지 선택할 예정.

- `composition.LlmBindings`가 선택적 두 필드 추가:
  `judge_model: JudgeModel | None`과
  `debate_orchestrator: DebateOrchestrator | None`. 데이터 클래스
  `__post_init__`이 일관성 없는 수동 생성 (두 역할 모델 모두 바인딩
  안 됐는데 오케스트레이터만 있음)을 거부하여 포크 구성 버그가 첫
  이벤트에서 오케스트레이터 내부 깊숙히 발견되지 않고 빌드 시점에
  잡힘.
- `bind_azure_llm_bindings`가 Wave 4 beta-2 `critic_system_prompt`
  형태와 매칭되는 `judge_system_prompt` 파라미터 추가. `t1.judge`
  기능 해석 AND 프롬프트 공급 시 Judge 바인딩.
  `critic_model` AND `judge_model` 둘 다 바인딩되면 기본
  `DebateOrchestrator(critic, judge, DebateOrchestratorConfig(max_rounds=1))`
  자동 생성.
- `runtime.configuration._finalize_llm_bindings`가
  `composer.compose(capability_id="t1.judge")`로 Judge system 프롬프트를
  조립하되 `LookupError`-graceful 성능 저하 (비평자 경로 미러링):
  성공 시 `judge_prompt_composed`, 카탈로그에 Judge base 프롬프트가 없으면
  `judge_prompt_missing` 발행.
- `services/core-control-plane/tests/test_composition_llm.py`의 다섯 테스트가 four-way 매트릭스와
  수동 생성 거절 pin: (a) 두 기능 + 두 프롬프트 -> 오케스트레이터
  생성; (b) 판정자 상한만 -> 오케스트레이터 None; (c) 비평자 상한만 ->
  오케스트레이터 None; (d) 두 상한 있지만 판정자 프롬프트 없음 -> 오케스트레이터
  None; (e) `LlmBindings(...debate_orchestrator=orch, critic_model=None...)`
  생성 시점에 raise.
- 실제 운영 T2 경로에 아직 동작 변화 없음. 바인딩된 오케스트레이터는
  `LlmBindings.debate_orchestrator`에 앉아서 Wave 4.5 delta-2 호출자
  (라우터 또는 QualityGate의 strategy pattern)가 어떤 이벤트를 그것을
  통과하게 할지 결정하기를 기다림.

## Wave 4.5 delta-2a - 무엇이 배포되었나

Wave 4.5 delta-2a는 Wave 4.5 delta-2b가 실제 운영 `QualityGate`에 wire할
**순수 라우팅 정책**을 랜딩합니다. 술어 + 구성을 먼저 배포 (`QualityGate`
변경 없음, 실제 운영 wire 없음)하면 포크가 shadow 탐색으로 라우팅 매트릭스를
exercise 가능하고, 어떤 이벤트가 실제로 토론을 통과하기 전에 승격
게이트가 신호를 수집할 수 있음.

- `services/core-control-plane/src/fdai/core/quality_gate/debate_router.py` -
  `DebateRoute` (`debate` / `skip`) enum,
  `DebateRoutingDecision` (경로 + 사유 + 스냅샷된
  ``action_type`` + 메타데이터) 고정된 데이터 클래스,
  `DebateRouterConfig` (`enabled` 킬스위치,
  `on_cross_check_disagreement` 축,
  `always_for_action_types` / `never_for_action_types` 허용 /
  거부 리스트)와 겹치는 허용 / 거부 집합을 거부하는
  `__post_init__`, 그리고 순수 `decide_debate_route(...)` 술어.
- 테스트에 baked-in된 6-rule precedence:
  1. `orchestrator_available=False` -> 건너뜀 with 사유
     `orchestrator_unavailable` (실패 시 차단 - 허용 목록 포함
     모든 다른 축 지배);
  2. `config.enabled=False` -> 건너뜀 with 사유 `disabled`
     (킬스위치 - 허용 목록 지배);
  3. 후보 `action_type` in `never_for_action_types` -> 건너뜀
     with 사유 `never_list` (denylist가 허용 목록 이김; 포크의
     가드레일이 다른 포크의 명시적 선택 리스트에 조용히 오버라이드되지
     않도록);
  4. 후보 `action_type` in `always_for_action_types` ->
     토론 with 사유 `always_list`;
  5. 교차 검증 disagreed AND
     `on_cross_check_disagreement=True` -> 토론 with 사유
     `cross_check_disagreement` (기본 트리거);
  6. 그 외 -> 건너뜀 with 사유 `default_skip`.
- `core/`-safe 유지: `fdai.core.quality_gate.gate`와 stdlib
  에서만 가져오기; `delivery.*` 또는 LLM SDK 없음.
  `scripts/quality/architecture/check-core-imports.sh`가 계속 통과.
- `services/core-control-plane/tests/quality_gate/test_debate_router.py`의 11개 테스트가 모든
  precedence 룰 + 구성의 overlap 검증기 + `action_type`
  스냅샷 (미래의 ActionType 이름 변경이 과거 감사 항목을 절대
  깨지 않음) 커버.

## Wave 4.5 delta-2b - 무엇이 배포되었나

Wave 4.5 delta-2b는 실제 운영 wire를 랜딩합니다: `QualityGate.evaluate()`가
이제 교차 검증 disagreement 시 토론 오케스트레이터를 참조합니다.
Wire는 완전히 명시적 선택 - 토론 파라미터를 전달하지 않으면 생성자가
historical 형태를 유지하므로 모든 기존 `QualityGate` 호출자가 동작
동일.

- `QualityGate.__init__`이 매칭되는 두 선택적 파라미터 추가 -
  `debate_orchestrator`와 `debate_router_config`. 둘 중 하나만
  전달하면 construction 시점에 `ValueError("...MUST be provided
  together...")` raise, 포크 배선 버그가 첫 disagreement에서 조용히
  터지지 않고 fail-fast.
- `evaluate()`가 정족수 루프 동안 기본 교차 검증 모델의 전체
  `(action_type, params)` 출력을 캡처하여 오케스트레이터가 제안자의
  제안을 비평자에게 넘길 수 있게 함.
- `cross_check_below_quorum` 시, 두 토론 경계가 모두 wire되면
  게이트가 `decide_debate_route(cross_check_disagreed=true,
  orchestrator_available=true, ...)` 호출하여 라우터의
  `route + reason`을 `debate_route:{value}:{reason}`으로 감사 이력에
  덧붙이기.
- `DebateRoute.DEBATE`에서 게이트가
  `오케스트레이터.실행(후보, proposer_output, known_rule_ids,
  retry_proposer=self._debate_retry_proposer)`를 대기; 결과는
  `debate_outcome:{verdict}:{reason}`로 로그.
- `_debate_retry_proposer(candidate, directive)`는 기본 교차 검증
  모델을 동일한 후보로 재호출하는 no-directive 콜백.
  `CrossCheckModel` 프로토콜이 directive를 받지 않으므로 재시도는
  "특정 변경을 향해 steer"가 아닌 "제안자에게 동일한 조건에서 한 번
  더 기회"로 동작. Directive는 감사용 토론 대화 기록에 남음.
- 결과 로직:
  - `PROCEED`가 **disagreement를 flip** - 다른 soft issue (검증기
    abstain, 누락된 / ungrounded 인용, low 확신도)가 없는
    한 게이트가 `ELIGIBLE` 반환;
  - `ABORT`가 **disagreement 유지** - 게이트가 `DISAGREE` 반환하고
    오케스트레이터의 사유가 감사 이력에 threading;
  - `PROCEED` + 다른 soft issue -> **`ABSTAIN`로 degrade** - 토론은
    하나의 축; 다른 모든 검사가 여전히 적용.
- Deferred 가져오기 (`from fdai.코어.quality_gate.토론
  가져오기 DebateVerdict`, `from
  fdai.코어.quality_gate.debate_router 가져오기 DebateRoute,
  decide_debate_route`)가 `evaluate()` 내부에 위치하여 module-level
  cycle을 break (`debate`와 `debate_router` 둘 다 `gate`에서
  `QualityCandidate`를 가져오기).
- `services/core-control-plane/tests/core/quality_gate/test_gate.py`의 7개 테스트가 커버:
  half-wiring 거절 (2), `PROCEED` -> `ELIGIBLE` (1),
  비평자 HIGH-severity에서 `ABORT`가 `DISAGREE` 유지 (1), 라우터
  killswitch가 오케스트레이터 호출 방지 (1), `PROCEED` + low-confidence가
  `ABSTAIN`으로 degrade (1), Judge `ESCALATE_HIL`이 `DISAGREE` 유지
  (1). 기존 17개 QualityGate 테스트는 변경 없이 통과 - wire가 진정
  가산.

## Wave 5 alpha - 무엇이 배포되었나

Wave 5 alpha는 웹 검색을 위한 업스트림 **경계**을 랜딩합니다: 타입,
프로토콜, 기본 비활성 가짜, sanitizer 방어. 이후 검토된 Azure Responses
어댑터와 Operator API 채팅 배선이 배포됐고 코어 T2 프롬프트 조립은
아직 이 경계에서 멈춥니다.

- `services/core-control-plane/src/fdai/core/web_search/types.py` -
  `WebSearchQuery` (`__post_init__`가 blank 텍스트, zero max_results,
  zero budget_ms를 거부하는 고정된 데이터 클래스; 호출자가 공급하는
  `allowed_domains` 튜플 + `metadata`),
  `WebSnippet` (`url` / `domain` / `title` / `text` /
  `content_hash` / `fetched_at`를 가진 불변 기록; blank url /
  도메인 / content_hash는 construction 시 거부),
  `WebSearchResult` (originating 조회, retrieved 스니펫,
  audit-friendly `reasons` 튜플을 운반하는 고정된 묶음 -
  운영자가 검색이 왜 degrade했는지 볼 수 있게).
- `services/core-control-plane/src/fdai/core/web_search/provider.py` -
  하나의 비동기 `search(query) -> WebSearchResult` 메서드를 가진
  `WebSearchProvider` `@runtime_checkable` 프로토콜 (API 키 같은
  비밀은 어댑터 생성자에 유지, 프로토콜 표면 밖에), 그리고
  `NoOpWebSearchProvider` - 모든 쿼리에서 `snippets=()` +
  `reasons=("no_op_provider",)`을 반환하는 배포된 deny-by-default
  가짜.
- `services/core-control-plane/src/fdai/core/web_search/sanitizer.py` -
  구조화된 코드 (`off_allowlist`, `empty_allowlist`,
  `injection_markers_detected`)를 가진 `WebSnippetPolicyError`,
  operator-memory 표시 리스트를 재사용하는
  `detect_snippet_injection_markers()` (기억에서 차단된 어떤
  패턴이든 스니펫에서도 차단), off-allowlist 스니펫 AND 빈
  허용 목록을 거부하는 `validate_snippet_domain()` (빈 허용 목록은
  스니펫에 정당한 소스가 없음을 의미), 그리고 XML-escape된 본문과
  속성으로
  `<web_snippet trusted="false" url="..." domain="..." content_hash="...">...</web_snippet>`
  묶음을 생성하는 `wrap_web_snippet()` (스니펫이 closing tag를
  forge할 수 없도록).
- `core/`-safe 유지: stdlib과 `fdai.core.operator_memory.sanitizer`
  (공유 표시 리스트용)에서만 가져오기. LLM SDK 없음, `delivery.*`
  없음. `scripts/quality/architecture/check-core-imports.sh` 계속 통과.
- `services/core-control-plane/tests/core/web_search/test_web_search.py`의 19개 테스트가 모든
  생성자 불변식 (4 + 3), NoOp 프로바이더 동작 + 프로토콜
  runtime-check (2), 도메인 허용 목록 강제 (3), 주입 탐지 (2),
  `wrap_web_snippet` (5 - 본문 + url XML-escape, off-allowlist
  거부, 주입 표시 거부 포함) 커버.

## 관련 문서

| 목적 | 시작 지점 |
|------|-----------|
| Tier 경계와 quality 게이트 | [llm-strategy-ko.md](../architecture/llm-strategy-ko.md) |
| Trust 라우팅과 컨트롤 루프 | [../../.github/instructions/architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) |
| 이 설계가 확장하는 Human 재정의 정책 | [../../.github/instructions/architecture.instructions.md#human-override](../../../.github/instructions/architecture.instructions.md#human-override) |
| 안전 불변식과 코딩 컨벤션 | [../../.github/instructions/coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md) |
| Prompt-injection 위협 모델 | [security-and-identity-ko.md](../architecture/security-and-identity-ko.md) |
| Rule 카탈로그와 출처 이력 규칙 | [rule-catalog-collection-ko.md](../rules-and-detection/rule-catalog-collection-ko.md) |
