---
title: 에이전트 판테온 구현 계획
translation_of: agent-pantheon-implementation.md
translation_source_sha: ed7925abdae04b0e800aab5bd87913ca7ad4f47b
translation_revised: 2026-08-13
---

# 에이전트 판테온 구현 계획

[agent-pantheon.md](agent-pantheon-ko.md) 에서 정의한 15개 에이전트 판테온을
착지시키기 위한 웨이브 계획. 각 웨이브는 스코프된 산출물 세트, exit 게이트,
이전 웨이브 의존성을 가진다; 웨이브는 자기 게이트 가 통과할 때까지 병합 되지
않는다. 이 문서는 조정 기록이다 - 개별 PR 은 여전히 자기 exit 게이트 와
[coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md#safety)
의 안전 불변식 로 측정된다.

> **범위:** 계획은 고객-무관이다. 아래의 모든 모듈 경로와 토픽 은 범용;
> 포크 는 [project-structure.md](../architecture/project-structure-ko.md) 의 경계 을 통해
> 바인딩을 설정하지만 판테온 자체는 편집하지 않는다
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
>
> **구현 초점:** Azure only. Kafka wire 는 Event Hubs `:9093`, ChatOps 는
> Teams Adaptive 카드; ChatOps admin 채널과 전달 어댑터 는
> [app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)
> 의 배치를 따른다.

아래 섹션은 롤아웃 순서와 수락 의도를 보존합니다. 공유 구성 요소는
`services/core-control-plane/src/fdai/agents/_framework/`에 있습니다. Huginn은 정규화된
계획 및 관찰된 변경을 `object.change`로 게시하고, Muninn은 실행 권한을 추가하지 않은 채
변경할 수 없는 내용 주소 기반 리비전을 보존합니다. 인과 Event는 같은 변경 근거를 포함하고,
Forseti의 범위가 제한된 평가는 권한을 유지하거나 낮출 수만 있습니다. 그래프 최신성에
권위 있는 근거가 생길 때까지 계획된 변경은 사람 검토 상태로 유지됩니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| W0-W1 문서, 온톨로지 및 프레임워크 기반 | implemented | [`test_framework_layout.py`](../../../services/core-control-plane/tests/agents/test_framework_layout.py), [`test_pantheon_doc_parity.py`](../../../services/core-control-plane/tests/agents/test_pantheon_doc_parity.py), [`test_topics.py`](../../../services/core-control-plane/tests/agents/test_topics.py) | 고정 레지스트리, 패키지 경계, 문서 일치 및 타입이 지정된 토픽 기반을 실행하고 검사할 수 있습니다. |
| W2-W6 거버넌스, 파이프라인, 인터페이스, 전문 에이전트, 인계 및 보안 메커니즘 | implemented | [`test_runtime_chain.py`](../../../services/core-control-plane/tests/agents/test_runtime_chain.py), [`test_thor_durable.py`](../../../services/core-control-plane/tests/agents/test_thor_durable.py), [`test_conversational_port.py`](../../../services/core-control-plane/tests/agents/test_conversational_port.py) | 범위가 제한된 메커니즘을 집중 합성 검사로 실행하지만 실제 운영 검증을 입증하지는 않습니다. |
| W7 에이전트 간 shadow 작업 흐름 메커니즘 | implemented | [`test_wave7_workflows.py`](../../../services/core-control-plane/tests/agents/test_wave7_workflows.py) | 작업 흐름에 실행 가능한 합성 shadow 추적이 있으며, enforce 작업 흐름을 기본값으로 사용하는 근거는 이 문서에 없습니다. |
| W8 KPI, 승격 및 성능 저하 메커니즘 | implemented | [`test_wave8_kpi_degradation.py`](../../../services/core-control-plane/tests/agents/test_wave8_kpi_degradation.py) | KPI 보고는 측정값과 사용 불가능한 근거를 구분하고, 근거가 없으면 승격을 차단하며, 주입된 성능 저하 훈련이 고정 판테온을 다룹니다. |
| 실제 운영 KPI 검증 및 실제 enforce 승격 | not-started | [목표와 메트릭](../architecture/goals-and-metrics-ko.md) | 이 계획에는 보존된 실제 shadow 표본 집합, 운영 승격 증적, 독립적인 검토 또는 실제 판테온 enforce 승격 근거가 없습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-13 | in-progress | W0-W8 전체 완료 주장을 독립적으로 근거를 확인할 수 있는 구현 영역으로 교체했습니다. | 현재 변경 | 검증 완료 또는 enforce 운영을 주장하기 전에 실제 근거를 수집하고 별도 검토를 거친 승격을 완료합니다. |

### 남은 작업

- [ ] 하나의 고정된 런타임, 카탈로그, ActionType, 작업 흐름 및 시나리오 집합 리비전에서 보존된 실제 shadow 코호트를 대상으로 선언된 KPI 수집기를 실행합니다.
- [ ] 승격 후보마다 표본 수와 신뢰 구간을 포함한 권위 있는 결과, 재발, 롤백 및 정책 이탈 0건 근거를 보존합니다.
- [ ] 판테온 enforce 운영을 사용하거나 보고하기 전에 독립적인 승격 검토를 완료하고 권위 있는 승격 집합 증적을 기록합니다.

## 1. 이 문서가 존재하는 이유

판테온 문서 ([agent-pantheon.md](agent-pantheon-ko.md)) 는 15개 에이전트 계약을
정의한다. 이를 코드베이스와 룰 카탈로그에 착지시키려면 아래가 필요:

- **문서**: 3개 로드맵 문서가 상세 섹션을 획득 (per-agent 작업,
  workflows, 성능 저하).
- **온톨로지**: 새 `Agent` 객체 타입 + 5개 지원 객체 타입
  (`Conversation`, `Turn`, `UserPreference`, `SecurityEvent`, `Issue`) 이
  `rule-catalog/vocabulary/object-types/` 아래 기존 카탈로그에 합류.
- **타입이 지정된 기능**: 중재, 인계, 알림, rule-candidate 게시는 소유자 에이전트의 schema-checked 객체 토픽을 사용합니다.
  이 동작은 카탈로그 ActionType이 아니며 `governance.*`는 `pr_native` catalog-as-code 변경에만 사용합니다.
- **Python 코어**: `services/core-control-plane/src/fdai/agents/` 아래 15개 flat 전문가 모듈과
  `_framework/` 아래 공유 base, 레지스트리, 토픽, 버스, 런타임, two-port 구성 요소.
- **테스트**: 레지스트리 무결성, single-writer 토픽 강제, ActionType 역할
  바인딩, pantheon 서브그래프 온톨로지 조회.
- **Wave W0-W8**: 증분 per-agent 동작 + cross-agent 워크플로우, 전체에 걸쳐
  shadow-mode 게이팅.

아래 웨이브들은 이 작업을 순차화하여 각 웨이브가 측정 가능한 exit 기준으로
게이트된 동작 서브셋을 제공한다.

## 2. 가이드 불변식 (어느 웨이브에서도 위반 금지)

- **Docs-first, docs-after.** 모든 웨이브는 코드 / 카탈로그 변경과 같은 PR
  에 doc 업데이트를 착지시킨다. 문서는 절대 표류 하지 않는다.
- **Shadow before 강제 적용.** 모든 새 에이전트 동작은 judge-only 로 배포.
  강제 적용 승격은 per-behavior 이며 별도 검토.
- **Single-writer topics.** 소유자 에이전트 만 `object.<type>` 에 publish. 스키마
  레지스트리 가 병합 시점에 강제.
- **판사는 실행기 가 아니다.** Forseti 는 판정 를 발행; Thor 는
  전달. 어떤 웨이브도 이 역할을 collapse 하지 않는다.
- **Hard-dependency 존중.** Saga 와 Vidar 는 변경 의 필수 의존성;
  둘 중 하나가 저하되면 변경 은 shadow 로 강등.
- **LLM 은 Bragi (translator), Forseti (T2 abstain), Norns (off-path 배치)
  에서만.** 다른 모든 에이전트는 hot-path 에서 LLM-free 유지.
- **포크 경계.** Pantheon 세트 / 역할 바인딩은 upstream-locked; 포크 는
  설정만 하고 pantheon 을 확장하지 않는다.

## 3. 웨이브 개요

9개 웨이브. 각 웨이브는 하나의 exit 게이트 와 범위가 제한된 범위 를 가진다. 게이트 는
측정 가능; 웨이브는 산문으로 닫히지 않는다.

| Wave | 산출물 세트 | Exit 게이트 |
|------|-------------|-----------|
| **W0** | Docs 기반: workflows doc, pantheon §4 상세, 온톨로지 YAML 추가 | translation-pair CI + 스키마 lint green; 새 객체 타입 이 `/ontology/graph` (dev) 로 해석됨 |
| **W1** | Python 스캐폴딩: `agents/` 패키지, base 등급, 15 stub, 토픽 레지스트리, two-port 골격 | 레지스트리 + topic-owner 강제 테스트로 `pytest services/core-control-plane/tests/agents/` 통과 |
| **W2** | 거버넌스 staff: Saga (감사 + issue), Mimir (룰 담당자), Muninn (기억 / RAG), Norns (learner) shadow 로 완전 배선 | 종단간 감사 이력: 합성 이벤트가 walk-through, Saga 가 `AuditEntry` 를 쓰기, 재생 가 재구성, Norns 가 pattern 포착 |
| **W3** | Sensing + judgment + risk: Huginn, Heimdall, Forseti, Var, Vidar, Thor 가 타입이 지정된 포트 로 연결; verdict-to-execute-to-audit 루프 shadow 로 실제 운영 | 100개 합성 이벤트가 유입 -> 판정 -> HIL 또는 auto -> execute (shadow) -> 감사 로 정책 위반 zero 로 흐름 |
| **W4** | Bragi + Odin: 라우팅, per-user 맥락, 중재 이 있는 conversational 포트 | 오퍼레이터 NL 조회 하나가 라우팅 -> 기본 + contributors -> aggregated 응답 로 walk-through; Odin 이 합성 domain_conflict 를 arbitrate |
| **W5** | 도메인 specialists: Njord, Freyr, Loki 가 Forseti 에 참고용 바인딩 | 비용 / 용량 / chaos advice 가 합성 판정 에 첨부; Loki 실험이 blast-radius 존중하며 shadow 로 실행 |
| **W6** | 인계 + security 에스컬레이션: Issue dedup, 지문 인덱스, admin-channel 알림 | (a) 합성 unhandled 요청 가 정확히 1개 GitHub issue + repeat 시 comment 생성; (b) RBAC-insufficient 제안 이 정확히 1개 admin 카드 + repeat 시 dedup 생성 |
| **W7** | Cross-agent workflows: [agent-workflows.md](agent-workflows-ko.md)의 13개 작업 흐름이 한 번에 하나씩 shadow로 동작 | 각 작업 흐름은 executable shadow 추적 참조를 가지며 어떤 작업 흐름도 강제 적용을 기본값으로 사용하지 않음 |
| **W8** | 승격 gates + 측정: per-agent KPI 수집기, promotion_gate 배선, 성능 저하 훈련 | (a) 각 에이전트가 선언된 KPI 를 리포트; (b) 각 성능 저하 정책 가 주입 실패로 검증; (c) 임의 단일 워크플로우가 게이트 통과 후 별도 PR 로 강제 적용 모드 승격 가능 |

## 4. Wave 0 - Docs 기반

**범위**

- **`docs/roadmap/agents/agent-workflows.md` (+ ko)** - 순서 diagram 과 exit
  criteria 가 있는 13개 cross-agent 워크플로우. 워크플로우 인벤토리는 이
  문서 §5 참고.
- **`docs/roadmap/agents/agent-pantheon.md` §4 상세** - 15개 에이전트 각각이
  네 개의 서브섹션 (Recurring / Event / Meta / Cross-agent 작업) + KPI
  테이블 + 성능 저하 정책 문단을 얻음. 현재 §4 의 간결한 테이블은
  인덱스가 되고, 상세는 inline 으로.
- **`rule-catalog/vocabulary/object-types/` 온톨로지 추가**:
  - `agent.yaml` (pantheon 객체 타입, `question_domains`,
    `owns_code_paths`, `llm_bindings`, `rate_limits` 포함)
  - `conversation.yaml`, `turn.yaml`, `user-preference.yaml`
  - `security-event.yaml`, `issue.yaml`
  - `rule-candidate.yaml`, `handoff-escalation.yaml`
- **타입이 지정된 기능 정합성** - `HandoffEscalation`, `Issue`, `SecurityEvent`, `ArbitrationRequest`,
  `ArbitrationDecision`, `RuleCandidate`는 single-writer 토픽 소유권을 유지합니다.
  레지스트리 테스트는 shipped ActionType으로 해석되지 않는 `AgentSpec.executes` 또는 `AgentSpec.initiates` 값을 거부합니다.

**Exit 게이트**

- 3개 CI translation 게이트 모두 green (`scripts/quality/localization/check-translations.sh`).
- 온톨로지 YAML lint 통과 (기존 `scripts/catalog/validate-catalog-full.py` 가 오늘
  이를 커버).
- `docs/roadmap/README.md` (+`-ko.md`) 가 새 workflows 문서 참조;
  renumbering 은 pantheon-doc PR 에서 이미 완료.

**의존성**

- 판테온 문서 병합 필요 (이전 PR 에서 이미 착지).

**Anti-scope (W0)**

- Python 코드 없음.
- 기존 에이전트 동작 변경 없음 (아직 하나도 없음).

## 5. Wave 1 - Python 스캐폴딩

**범위**

- `services/core-control-plane/src/fdai/agents/` 패키지:
  - `_framework/base.py` - 추상 `Agent` 클래스: 필드 (`name`, `layer`, `owns`,
    `executes`, `subscribes`, `publishes`, `question_domains`,
    `owns_code_paths`, `llm_bindings`, `rate_limits`), 메서드
    (`on_typed_message`, `on_conversation_turn`, `health`), 강제된
    single-writer publish 보조 로직.
  - `_framework/registry.py` - pantheon 명세를 로드하고 레지스트리를
    빌드, `get(name)`, `all()`, `owner_of(topic)`,
    `owner_of(object_type)` 노출.
  - `_framework/topics.py` - 타입이 지정된 토픽 계약: naming (`object.<type>`), 파티션
    키 전략 (변경 은 per-resource, judgment/감사 는
    per-correlation), 멱등성, back-pressure 기본값.
  - `_framework/bus.py`와 `_framework/bus_bridge.py` -
    `producer_principal == owner_agent`를 강제하는 in-memory 계약과 EventBus 브리지.
  - Flat 전문가 모듈 (`odin.py`, `thor.py`, ...) - 고정 pantheon
    에이전트마다 하나의 구현.
- `services/core-control-plane/src/fdai/agents/__init__.py` 가 레지스트리 항목 지점 를 내보내기.

**테스트 (`services/core-control-plane/tests/agents/`)**

- `test_framework_layout.py`, `test_registry.py`, `test_topics.py`가 패키지
  형태, 고정 15-agent 레지스트리, single-writer 소유권, partition-key 동작을 검증.
- `test_ontology_alignment.py`가 온톨로지와 ActionType이 pantheon 명세와
  일치하는지 검증합니다. `test_action_intent_parity.py`는 클라이언트 측 자연어 라우터를
  허용하지 않아 action-intent 라우팅을 서버가 소유한으로 유지합니다.

**Exit 게이트**

- `pytest services/core-control-plane/tests/agents/` green.
- `scripts/quality/architecture/check-core-imports.sh` 여전히 green (`agents/` 외부에 새
  cross-layer 가져오기 없음).
- 새 패키지에 `mypy` (또는 repo 의 현재 타입-체크 bar) clean.

**의존성**

- W0 완료 (레지스트리 가 로드하려면 에이전트 객체 타입 YAML 이 존재해야 함).

**Anti-scope**

- `pass` 이상의 핸들러 본문 없음.
- 새 HTTP 또는 Kafka 클라이언트 없음 (기존 어댑터 계약 재사용).
- Conversational 포트 아직 없음 (W4 에서 착지).

## 6. Wave 2 - 거버넌스 staff

거버넌스 에이전트가 가장 먼저 오는 이유: Saga 는 누구든 실행하기 전에
기록해야 하고; Mimir 는 Forseti 가 판단하기 전에 룰 참조를 해석해야 하고;
Muninn 은 Forseti 가 사유 하기 전에 맥락 를 서브해야 하고; Norns 는
발견 루프 를 닫는다.

**범위**

- **Saga (`services/core-control-plane/src/fdai/agents/saga.py`)** - 모든 terminal-state 토픽 을 구독한
  `append_audit` 핸들러 구현. 기존 감사 저장소 에 저장
  ([security-and-identity.md](../architecture/security-and-identity-ko.md) 참고).
  `escalate_to_github_issue` 실행기 구현: 지문 계산, Muninn 을
  통한 dedup 인덱스 읽기, GitHub App 어댑터 를 통한 issue 생성 또는
  comment 덧붙이기 (실제 네트워크는 포크 로 미룸; 테스트에서 in-memory
  어댑터 사용). 과거 audit-entry 를 chronological 순서 로 소비하며
  republish 없이 재생 구현.
- **Mimir (`services/core-control-plane/src/fdai/agents/mimir.py`)** - `object.rule-candidate` 구독.
  기존 룰 카탈로그 저장소 에 대한 sync 작업으로 `promote_rule` 과
  `revoke_rule` 구현. 최신성 monitor 추가 (recurring): 룰 별 발화
  카운트를 audit-log 에서 읽기, 비활성 임계값에서 `RuleStalenessSignal`
  발행. Mimir는 `RuleGenerationBuildRequest`와 `RuleGenerationBuildResult`도 소유합니다.
  주입된 영속 빌더가 exact 요청을 처리하고 Mimir는 범위가 제한된 권한 없는 결과만
  발행합니다. Exact Heimdall 검증은 변환 결과로 저장되며 활성화를 직접 호출할 수 없습니다.
- **Muninn (`services/core-control-plane/src/fdai/agents/muninn.py`)** - 다른 에이전트를 위한 상태 /
  맥락 저장소 읽기 담당. 기존 상태 저장소 프로바이더 로 backed
  ([project-structure.md](../architecture/project-structure-ko.md#customization-via-dependency-injection)).
  Bitemporal 스냅샷 교대 과 캐시 제거 구현. Saga 가 사용하는
  Issue 지문 인덱스 소유.
- **Norns (`services/core-control-plane/src/fdai/agents/norns.py`)** - 두 항목 지점: 배치 (기존
  스케줄러 를 통한 hourly cron) 과 스트림 (`object.audit-entry` 구독).
  Pattern 추출 을 T1 clustering 우선으로 구현; T2 LLM 요약 훅
  은 W7 에 남겨둠. `RuleCandidate` 와 `close_issue` 액션 발행. Publish 전에
  내부 Urd (과거 근거), Verdandi (현재 계약), Skuld (미래 안전성) 관점의 `3/3`
  합의를 요구합니다. 이들은 에이전트 또는 principal이 아닙니다. Norns는 하나의
  집계 합의 결과만 내보내고 불일치는 범위가 제한된 보류 기록으로 보관합니다. 비공개 `norns_deployment_learning.py` 보조 로직은 범위가 제한된 scenario-gap 및 preflight-blocker 집계만 소유합니다. 모든 후보 생성과 publish는 계속 Norns가 기존 합의 경계를 통해 수행합니다. Caller-supplied preflight 관측은 서로 다른 범위 다이제스트 전반의 같은 수동 차단 요인을 inert `preflight-toggle-gap` 후보 하나로 집계할 수 있으며 Norns 자체는 토글을 만들지 않습니다.

**테스트**

- `test_wave2_governance.py`가 Saga 감사/issue 동작, Mimir 룰 거버넌스,
  Muninn 상태, Norns 후보 흐름을 검증.
- `test_candidate_guard.py`, `test_norns_coverage.py`, `test_norns_preflight.py`가 inert 후보
  안전성과 범위가 제한된 learning 동작을 검증.
- `test_norns_consensus.py`가 Norns single-writer 경계에서 unanimous publish와
  disagreement 보류 동작을 검증합니다.
- `test_runtime.py`가 Mimir 빌드 요청/결과와 Heimdall 검증 체인, 위조 producer, 누락된
  handler 및 활성화 없음 경계를 검증합니다.

**Exit 게이트**

- 종단간 합성 추적: 합성 이벤트 -> Saga 기록 -> Norns 포착 ->
  RuleCandidate 제안 -> Mimir 승격 -> audit-log 가 전체 체인 을 표시.

**의존성**

- W1 완료.

**Anti-scope**

- 실제 GitHub App 호출 없음 (in-memory 어댑터 만; 실제 통합은
  fork-configured 경계 뒤에).
- Norns 에 LLM 없음 (이번 웨이브는 T1 clustering 만).

## 7. Wave 3 - Sensing, judgment, 실행 루프

**범위**

- **Huginn (`services/core-control-plane/src/fdai/agents/huginn.py`)** - 실시간 리소스 및 변경 발견
  유입을 소유합니다. 구독 범위의 Azure 쓰기/삭제 이벤트는 managed 신원
  Event Grid 전달을 통해 raw Event 허브로 들어오고, 런타임 정규화기가 정본
  Event로 다시 publish합니다. Huginn은 dedup 후 주입된 영속 인벤토리 projector를
  호출하고 `object.event`를 publish합니다. Change-bearing IaC, release, provider-activity
  이벤트는 `object.change`도 publish하고 Muninn은 맥락 및 재생을 위해 변경할 수 없는 개정 번호를
  저장합니다. 6시간 인벤토리 sync 작업은 full ARG/ARM
  조정 경로로 유지됩니다.
- **Heimdall (`services/core-control-plane/src/fdai/agents/heimdall.py`)** - 발견 최신성/커버리지
  assurance와 anomaly detector
  (statistical 임계값, T0/T1 을 통한 adaptive 기준선), 표류
  detector (Muninn 스냅샷 비교를 통한 declared vs actual 상태),
  예측 (statistical 시계열; ARIMA 또는 exponential smoothing).
  `Anomaly`, `Drift`, `Forecast` 발행. `SecurityEvent` 구독은 W6 로
  예약. 주입된 범위가 제한된 읽기 전용 operational 근거 훅은 판단 또는 실행 권한을
  부여하지 않고 권위 있는 anomaly를 enrich할 수 있습니다. Stale/degraded 인벤토리는 fail
  closed하며 Heimdall은 조정 작업을 시작하지 않습니다. 주입된 Rule 세대 검증기는 정확한
  준비 상태 스냅샷만 읽고 `RetrievalValidation`을 발행하며 증적을 연결하거나 세대를
  활성화하지 않습니다.
- **Forseti (`services/core-control-plane/src/fdai/agents/forseti.py`)** - `object.anomaly`,
  `object.drift`, `object.event` 구독. 3-tier trust 라우터 를 로컬 구현:
  Mimir 를 통한 T0 룰 일치; Muninn 을 통한 T1 유사도; T2 는 W7
  까지 `abstain` 반환하는 stub 유지. Verdict 는 결정론 `risk-classification.yaml`
  테이블 + ActionType 상한 에서 계산된 `risk_verdict` 를 포함.
  `auto | hil | deny` 로 `Verdict` 발행. `domain_conflict: true` 시
  `arbitrate` 신호 발행 (Odin 은 W4 에서 착지).
- **Thor (`services/core-control-plane/src/fdai/agents/thor.py`)** - `object.verdict` 와
  `object.rollback` 을 구독합니다.
  전달: `auto` -> 기존 실행기 프로바이더 에 대해 shadow execute;
  `hil` -> `object.hil-request` publish (Var 도 여기서 착지); `deny` ->
  Saga 를 위한 폐기 기록 publish. `resource_id` 파티션 에서
  per-resource mutex 강제. 실패 시 롤백 트리거.
- **Var (`services/core-control-plane/src/fdai/agents/var.py`)** - `object.hil-request` 구독. 기존
  ChatOps 어댑터 를 통해 present (W3 에서는 stub, W5 에서 real
  어댑터). 시간 초과 / expire tracking. `object.hil-response` publish.
- **Vidar (`services/core-control-plane/src/fdai/agents/vidar.py`)** - Thor 실패 신호 을 구독합니다.
  ActionType `rollback_contract` 로 선택한 주입형 롤백 실행기 를
  호출하고 프로바이더 증적 를 `object.rollback` 으로 publish 합니다.
  Thor 는 증적 가 도착할 때까지 실패한 ActionRun 과 리소스 잠금 을
  유지합니다. 실행기 누락, 프로바이더 오류 또는 빈 증적 는 성공으로
  기록하지 않고 `rollback_failed` 로 종료합니다.

강제 적용 모드 런타임 을 구성할 때는 명시적 Thor 실행기, 영속 ActionRun
저장소, StateStore-backed Saga 감사 체인, 롤백 실행기 레지스트리 가 모두
필요합니다. 하나라도 없으면 시작 이 차단됩니다. Shadow 모드 는 in-memory
기본값 를 유지하며 privileged 실행기 를 호출하지 않습니다.

**테스트**

- `test_wave3_pipeline.py`가 shadow 판정, 전달, 승인, 롤백
  경로를 검증.
- `test_runtime_chain.py`와 `test_thor_durable.py`가 종단 간 라우팅,
  영속 ActionRun, 리소스 잠금, 재시작 복구를 검증.

**Exit 게이트**

- 종단간 shadow 루프: 100개 합성 이벤트, per-resource mutex 관찰, 정책
  escape zero, Saga 감사 이력 완료.

**의존성**

- W2 완료.

**Anti-scope**

- 실제 ChatOps 카드 없음 (Var 는 테스트에서 in-memory 승인).
- Forseti 에 LLM 없음 (T2 는 stub abstain 유지).
- Cross-vertical 중재 없음 (Odin 은 W4 에서 착지).

## 8. Wave 4 - Bragi + Odin

**범위**

- **Bragi (`services/core-control-plane/src/fdai/agents/bragi.py`)** - conversational 포트 항목
  지점. 기존 operator-console 어댑터
  ([operator-console.md](../interfaces/operator-console-ko.md)) 재사용. 구현:
  - 의도 분류: `Agent.question_domains` 대비 T0 키워드 일치;
    Muninn 의 맥락 인덱스 를 통한 T1 임베딩 유사도; 대체 경로
    으로 T2 LLM classifier (포크 구성 에서 연결).
  - 승자 선택 채점 (판테온 문서 §6.3).
  - Multi-agent 집계: 기본 + contributors 에 타입이 지정된 조회
    보냄, 응답을 집계, NL 응답 로 렌더링.
  - 대화 상태: 세션, 턴, per-user partitioning, 보존.
- **Odin (`services/core-control-plane/src/fdai/agents/odin.py`)** - Forseti 가 발행한
  `object.arbitration-request` 구독. 룰 카탈로그에서 fork-configured
  priority 정책 (기본값: SLO > 비용 > 아키텍처) 읽기.
  `object.arbitration-response` publish. Recurring: 선언된 우선순위에서
  실제 결과가 벗어날 때 정책 가중치 를 조정하는 portfolio-outcome
  monitor (여전히 결정론 - 정책 갱신 제안 은 `RuleCandidate` 로
  Mimir 를 통과).

**테스트**

- `test_wave4_interface.py`와 `test_conversational_port.py`가 라우팅,
  세션 격리, 기여자 집계, 읽기 전용 질문 경로를 검증.
- `test_arbitration.py`가 결정론적 충돌 해석과 Forseti/Odin
  왕복을 검증.

**Exit 게이트**

- 오퍼레이터가 합성 Heimdall change-index 에 "누가 예시 리소스의
  공개 네트워크를 변경했어"라고 질문; Bragi 가 페이로드 에 `primary`,
  `contributors`, `trace_ref` 를 포함한 Heimdall + Saga + Muninn 의
  aggregated 응답 반환.

**의존성**

- W3 완료.

**Anti-scope**

- 프로덕션급 LLM 비용 tracking 없음 (LLM strategy 문서에 있으며 별도로
  착지).
- 아직 proactive briefing 없음 (recurring 대화 seeding 은 W7 의
  "Judgment coherence 감사" 워크플로우와 함께 착지).

## 9. Wave 5 - 도메인 specialists

**범위**

- **Njord (`services/core-control-plane/src/fdai/agents/njord.py`)** - 정본 `object.event`에서 범위가 제한된 비용 샘플을
  consume합니다(Azure 비용 관리 어댑터; 테스트에서 in-memory). spend 가
  예측 에서 임계값 만큼 편차 시 `CostAnomaly` 발행. cost-impact
  귀속 을 위한 Forseti 판정 참고용 훅 제공.
- **Freyr (`services/core-control-plane/src/fdai/agents/freyr.py`)** - 정본 `object.event`에서 범위가 제한된 사용률 샘플을 consume.
  `CapacityForecast`, `SizingRecommendation` 발행. Forseti 판정
  참고용 훅.
- **Loki (`services/core-control-plane/src/fdai/agents/loki.py`)** - 정본 `object.event`에서 범위가 제한된 예약 트리거를 consume. 모든 실험은
  `blast_radius` 가 범위가 제한된 되고 `default_mode: shadow` 인 `ActionRun`
  으로 propose. Loki 는 절대 실험을 auto-execute 하지 않는다:
  ActionType 은 판테온 §7.6 별 Forseti + Var 를 통과.

**테스트**

- `test_wave5_specialists.py`가 Njord 비용 advice, Freyr forecasting,
  Loki blast-radius 적용을 검증.

**Exit 게이트**

- 모든 도메인 전문가 가 shadow 의 최소 하나의 워크플로우 판정 에
  참고용 annotation 을 첨부; Loki 가 `blast_radius` 존중하며
  shadow-mode chaos 실험 완료.

**의존성**

- W4 완료 (cost-vs-SRE 충돌에 중재 필요).

**Anti-scope**

- 실제 Azure 비용 관리 pull 없음 (포크 경계 뒤에 어댑터).
- Adversarial 시나리오 생성 없음 (W7 워크플로우).

## 10. Wave 6 - 인계 + security 에스컬레이션

**범위**

- 완전한 `escalate_to_github_issue` 경로: 포크 경계 뒤의 실제 GitHub
  App 어댑터; Saga 지문 dedup; repeat 시 comment 덧붙이기; Mimir
  가 매칭 룰 을 승격하고 24시간 regression-clean 후 auto-close.
- 완전한 `notify_admin_privilege_violation` 경로: Heimdall 이
  `object.security-event` 구독; 판테온 §9.2 별 심각도 분류; §9.4 별
  경보 dedup 과 rate-limit; admin ChatOps 채널 어댑터.

**테스트**

- `test_wave6_handoff_security.py`가 issue deduplication, repeat comment,
  종결, 심각도, admin 알림 동작을 검증.
- `test_rate_limiter.py`가 범위가 제한된 알림과 에스컬레이션 비율을 검증.

**Exit 게이트**

- (a) 인계: 1개 issue, repeat 시 1개 comment, 승격 후 1개 auto-close.
  (b) Security: `high` 에 1개 카드, dedup 관찰, rate-limit 관찰.

**의존성**

- W2 (Saga), W3 (Heimdall + Forseti), W5 (Loki 필수 아니지만 W6 은 전체
  파이프라인이 서 있어야 함).

**Anti-scope**

- Permission-upgrade HIL 흐름 없음 (판테온 §9.5 언급; 별도 PR).

## 11. Wave 7 - Shadow 로 cross-agent workflows

롤아웃 순서, 작업 흐름별 shadow 게이트, 의존성 및 anti-scope는
[에이전트 작업 흐름 Shadow 롤아웃](agent-workflow-rollout-ko.md)이 소유합니다. 각 작업 흐름은
독립적으로 검토하며 이 wave에서는 어떤 작업 흐름도 강제 적용으로 승격하지 않습니다.

## 12. Wave 8 - 승격 gates, KPIs, 성능 저하 drills

**범위**

- **KPI collectors** - 각 에이전트는 pantheon 문서 §4 상세에서 선언한 KPI를
  기존 측정 파이프라인
  ([goals-and-metrics.md](../architecture/goals-and-metrics-ko.md))에 보고합니다.
  결과 근거가 없으면 `value: null`과 `not_measured` 같은 근거 상태를
  기록합니다. Fabricated zero를 만들지 않으며 measured 샘플이 도착할 때까지
  승격은 실패 시 차단합니다.
- **승격 gates** - 각 ActionType 의 `promotion_gate` 블록이 판테온
  KPI 테이블에 매칭되는 기계가 읽는 exit criteria 획득. 표준
  형태:

  ```yaml
  promotion_gate:
    shadow_days_min: 14
    kpi_thresholds:
      - 메트릭: 에이전트.forseti.verdict_accuracy
        min: 0.95
      - 메트릭: 에이전트.forseti.t2_escalation_rate
        max: 0.10
    regression_scenarios: [scenario-set-forseti-baseline]
  ```

- **성능 저하 drills** - 에이전트당 합성 실패 주입, 선언된
  성능 저하 정책 활성화 검증:
  - Saga down -> 새 변경 거부
  - Vidar down -> 새 변경 shadow 로 강등
  - Forseti down -> 큐 증가, 경보 발화
  - Var down -> 시간 초과 확장 + admin 경보
  - 나머지는 판테온 §11 별 (anti-pattern 은 이미 doc 에 codified; 테스트
    파일이 활성화)

**테스트**

- `test_wave8_kpi_degradation.py`가 KPI emission, 승격 검사, 고정
  pantheon의 injected 성능 저하 동작을 검증.

**Exit 게이트**

- 15개 에이전트 모두 KPI 를 측정 파이프라인으로 발행.
- 모든 성능 저하 훈련 통과.
- 게이트를 통과한 하나의 작업 흐름은 권위 있는 promoted 집합에 포함되어 shared
  수명 주기가 published로 해석될 수 있습니다. 업스트림 기본값은 shadow로
  유지되며 배포 권한에는 별도 검토된 승격이 필요합니다.

**의존성**

- W7 완료.

**Anti-scope**

- Multi-cloud 없음 (Azure only;
  [구현 Focus](../../../.github/copilot-instructions.md#implementation-focus-must)
  참고).

## 13. Cross-wave 관심사

### 13.1 문서는 항상 같은 PR 에 업데이트

모든 웨이브가 doc delta 를 코드와 나란히 착지. 검토자 는 문서가 stale
한 채로 남는 병합 를 블록. 구체적으로:

- W0 은 workflows 문서와 판테온 §4 상세 착지.
- W1 - W6 은 에이전트가 online 됨에 따라 판테온 §5 (에이전트 카탈로그) 행을
  업데이트 (`llm_bindings`, `rate_limits` 기본값 반영).
- W7 은 workflows 문서 항목 를 실제 shadow 추적 참조 로 업데이트.
- W8 은 판테온 §4 KPI 블록을 실제 기준선 숫자로 업데이트.

### 13.2 Bilingual 쌍 규율

모든 doc 변경은 같은 PR 에서 `foo.md` + `foo-ko.md` 를 touch 하고 ko 파일의
`translation_source_sha` 를 업데이트
([language.instructions.md](../../../.github/instructions/language.instructions.md#user-facing-doc-translations-ko)).

### 13.3 모든 웨이브에서 포크 경계

웨이브는 절대 customer 구성을 업스트림 코드로 pull 하지 않는다. 웨이브가
실제 통합 (GitHub App, ChatOps, Azure 비용 관리) 이 필요할 때, 코드는
기존 프로바이더 프로토콜 뒤에 가고 in-memory 어댑터 가 테스트를 위해 같은
PR 에서 ship
([project-structure.md](../architecture/project-structure-ko.md#customization-via-dependency-injection)).

### 13.4 웨이브에 대한 롤백

각 웨이브 PR 은 self-revertable: PR 을 revert 하면 데이터 마이그레이션
없이 이전 동작 복구 (새 파이프라인 단계 의 feature 플래그 는 기본값 off;
기존 테스트는 플래그 off 로 계속 통과해야 함).

### 13.5 Composition-root 배선 (라이브 프로세스)

웨이브 W1 - W8 은 에이전트 동작을 구현하고 테스트로 검증하지만,
에이전트들은 프로세스가 실제 이벤트 버스에 그들을 배선한 뒤에야 서로
통신한다. 그 경계 은 `services/core-control-plane/src/fdai/agents/_framework/runtime.py`
(`PantheonRuntime`)이며 `services/core-control-plane/src/fdai/runtime/bootstrap.py`에서 조립됩니다.
Headless `services/core-control-plane/src/fdai/__main__.py`는 이 초기화에 위임합니다:

- `PantheonRuntime.build(provider, raw_event_topic)` 은 15 개 에이전트를
  전부 인스턴스화하고, 발행(publish)하는 각 에이전트를 주입된 `EventBus`
  프로바이더 위의 단일 `EventBusBridge` 에 연결 하며, 각 에이전트가 선언한
  `AgentSpec.subscribes` 토픽을 브리지 구독으로 등록한다. 따라서
  `object.<type>` 로의 발행은 모든 구독자에게 즉시 동시 확산 되고, 각자
  자기 Kafka 소비자 그룹(`fdai-pantheon.<agent>`)을 쓴다.
- 원시 유입 이벤트(P1 컨트롤 루프가 소비하는 것과 동일한
  `kafka.topic_events`)는 Event Collector 인 Huginn 으로 라우팅되어
  정규화된 뒤 `object.event` 로 재발행된다. 판테온은 별도 소비자 그룹
  을 쓰므로 P1 파이프라인의 레코드를 가로채지 않고 그 옆에서 병렬 shadow
  로 동작한다.
- `PantheonRuntime.run()` 이 영속 컨슈머다: 실제 브로커에서는 영원히
  블록(구독마다 태스크 하나)하며, `__main__` 이 이를 P1 컨슈머 옆의
  **blast-radius 격리된** 백그라운드 태스크로 실행한다. 컨슈머들은
  `return_exceptions=True` 로 gather 되고, 죽은 컨슈머는 카운트·로깅 후
  삼켜져 형제 컨슈머는 계속 돈다; 판테온 전체 실패는
  `pantheon_runtime_failed` 로 로깅되지만 P1 wait 세트를 절대 취소하지
  않는다(shadow 오버레이는 주 파이프라인의 의존성이 아니다). 종료 시
  차례로 취소된다.

이 런타임은 **기본 활성화되고 기본 shadow**입니다. `FDAI_START_PANTHEON=0`
(`false`, `no`, `off`도 동일)이 런타임을 비활성화합니다.
`FDAI_START_CONSUMER`가 필요하며 소비자 버스가 없으면 초기화가
`pantheon_requested_without_consumer`를 로깅하고 배선을 건너뜁니다.

shadow 는 **가정이 아니라 강제된다**: `PantheonRuntime.build` 가 Thor 를
shadow 모드로 강제(`enforce=False`, 기본)하므로 판테온 Thor 는
judge-and-log 만 하고 P1 루프와 이중 실행하지 않는다. 강제 적용 로의 승격은
명시적이고 별도 리뷰되는 명시적 선택(`FDAI_PANTHEON_ENFORCE` /
`build(enforce=True)`)이며 절대 기본이 아니다. 에이전트는
`services/core-control-plane/src/fdai/agents/_framework/adapters.py` 의 in-memory 감사 / issue / admin 어댑터를
쓴다; 포크 는 `build(saga=...)` 로 영속(StateStore 기반) `Saga` 를
주입하고 나머지 어댑터도 영속 백엔드로 교체한다(§13.3 참조).

구성 가능 + 관측 가능 경계:

- `build(consumer_group_prefix=...)` 로 환경별 소비자 그룹 격리(기본
  `fdai-pantheon`).
- **부분 판테온.** `build(disabled_agents=...)` /
  `FDAI_PANTHEON_DISABLED_AGENTS` 로 포크 가 부분집합을 구동할 수 있다
  (agent-pantheon.md 10): 비활성화된 에이전트는 연결 도 구독 도 되지 않는다.
  알 수 없는 이름과 hard-dependency 에이전트(Saga / Vidar)는 거부됩니다.
  감사 / 롤백 비활성화는 변경 안전 불변식을 깨뜨립니다. Huginn
  비활성화는 유입 를 idle 시킨다(경고).
- **cross-vertical 중재 (라이브 루프).** 이벤트가 상충하는 `domain_advice`
  (`{domain: recommendation}`)를 실으면 Forseti -
  `object.arbitration-request` 의 단일 라이터 - 가 충돌을 제기하고,
  헌법 hard 제약이 부적격 선택지를 제거한 뒤 Odin이 남은 soft-objective 충돌을 결정적 우선순위(`복원력 > security > change_safety > 비용 >
  용량`, fork 오버라이드 가능)로 해결해 `객체.arbitration-decision`
  을 발행하며, Forseti 가 이를 기록한다. Forseti 는 *별개* 도메인 신호로
  도착한 조언도 누적한다 - 같은 리소스에 대한 Njord `object.cost-anomaly`
  (`scale_down`)와 Freyr `object.capacity-forecast`(`scale_up`) - 이라
  실제 도메인 간 충돌이 인라인 힌트 없이도 중재 을 트리거한다.
  런타임이 이미 양쪽을 구독하므로 루프는 끝에서 끝까지 닫혀 있다.
- **Conversational 포트 (실제 운영, deterministic-first).** 15개 응답자 모두 서버가 소유한 프롬프트,
  범위가 제한된 읽기 도구, principal 범위로 한정된 세션, 범위가 제한된 기여자, 타입이 지정된 액션 re-entry, digest-only
  A2A 귀속을 사용합니다. T1은 한계 `EmbeddingModel`의 다국어 charter vector를 캐시하고
  cosine/margin 임계값 뒤에서 T0 abstention/동점만 임베딩합니다. 명시적 이름, 읽기 의도, 액션
  요청, one-domain T0는 zero-call이며 richer 답변도 결정론적 owned-state 응답을 바꾸지 않습니다.
- **자가치유 컨슈머.** 죽은 컨슈머는 지수 백오프
  (`max_consumer_restarts`, `restart_backoff_base`,
  `restart_backoff_max`)로 재시작하고, 상한 초과 시에만 포기(카운트+로깅)
  하며 형제를 끌어내리지 않습니다. 최종 에이전트/토픽 상태는 false 하트비트를
  억제하고 Saga/Vidar 최종 또는 상태 실패는 sticky shadow를 강제합니다.
  재시작은 committed 오프셋에서 재개되고 범위가 제한된 `stop()`은 hang하지 않습니다.
- `EventBusBridge` 는 `BridgeMetrics`(delivered / handler_errors /
  handler_retries / dead_lettered / dead_letter_errors / consumers_crashed /
  consumers_restarted / empty_partition_keys / published / publish_errors /
  missing_correlation_id / missing_idempotency_key /
  producer_principal_mismatch / ordered_poison_halts / schema_violations)를
  `snapshot()` 으로 노출하고, `PantheonRuntime.health()` 가 Heimdall
  프로브와 KPI 수집기 용으로 이를 표면화한다. `health()` 는 per-agent
  `agent_health`, `consumer_states`, `unavailable_agents`, continuity 지도를 담아
  활성 실행, 최종 구독, effective 적용을 표시합니다.
- **Pub/sub 하드닝 (버스 계약).** 브리지 와 `InMemoryBus` 테스트 더블은
  하나의 계약을 공유해 테스트가 프로덕션과 조용히 어긋나지 못하게 한다:
  - **파티션 키 단일 출처.** 두 버스 모두 `topics.partition_key_for`
    (변경 -> `resource_id`, judgment/감사 -> `correlation_id`)를
    사용한다; 브리지 가 별도 사본을 두지 않는다.
  - **묶음 스탬프 + 강제.** 모든 publish 는 `producer_principal` 과
    `schema_version`(`ENVELOPE_SCHEMA_VERSION`, 호출자 재정의 우선)을
    찍고, 누락된 `correlation_id`(모든 토픽) / `idempotency_key`(변경
    토픽) - 와이어 계약(6.1)의 필수 필드 - 를 차단 없이 카운트한다.
  - **빈 변경 키 실패 시 차단.** 파티션 키가 빈 값으로 해석되는
    변경 토픽 publish 는 거부된다(`fail_closed_on_empty_mutation_key`,
    기본 on) - 파티션을 round-robin 하며 per-resource mutex 를 잃는
    미직렬화 변경 이 방출되지 않도록.
  - **컨슈머측 single-writer 검증.** 전달 전 브리지 는
    `producer_principal == owner_of_topic` 를 검증한다; impostor 레코드는
    구독자에게 건네지 않고 dead-letter 된다(`verify_producer_principal`,
    기본 on). "publish 측만" 갭을 닫는다.
  - **범위가 제한된 핸들러 재시도 + 타임아웃.** `_deliver` 는 일시적 핸들러
    실패를 `handler_max_retries`(기본 0)회 백오프로 재시도하고, 각 시도를
    `handler_timeout`(기본 없음)으로 한계 해 stuck 핸들러가 컨슈머를
    wedge 하지 못하게 한다; 최종 실패는 DLQ 로 라우팅된다.
  - **순서 토픽 poison halt.** `halt_ordered_topic_on_poison` 시 dead-letter
    된 변경 레코드가 해당 컨슈머를 halt 시켜 같은 리소스의 나중 변경
    이 앞지르지 못하게 한다(순서 보존); 형제는 계속 돈다. 기본 off
    (DLQ-and-continue).
  - **오퍼레이터 DLQ redrive.** `EventBusBridge.redrive(topic, handler)` 는
    수정 후 `<topic>.dlq` 를 재처리하고, 각 레코드를 언랩하며 여전히
    실패하는 것은 재-park 한다 - 상시 루프가 아닌 의도적 admin 액션.
  - **Publish 측 검증기 경계.** `payload_validator` 가 publish 경계에서
    malformed 레코드를 선택적으로 거부(실패 시 차단)해 `ContractValidator`
    경계 을 버스와 결합 없이 연결한다.
  - **구독 가드.** 두 버스 모두 미등록 `object.*` 토픽 구독(조용한
    dead 경계)에 경고하고, 중복 `(topic, agent, handler)` 등록(이중 전달)을
    건너뛴다.
  - **테스트 더블 패리티.** `InMemoryBus` 는 이제 동일 묶음 을 주입하고,
    동일 파티션 키를 계산하며, raising 구독자를 격리(`dead_letters` 에 캡처,
    DLQ 미러)하고, stuck 핸들러를 `handler_timeout` 으로 한계 한다.
- **강제 적용 는 영속 감사 을 요구한다.** 주입된 `Saga` 없이
  `build(enforce=True)` 하면 `pantheon_enforce_without_durable_saga` 를
  로깅한다: 추가 전용 감사 은 모든 자율 액션의 hard 불변식 이므로,
  in-memory(재시작 시 유실) 감사 체인 위에서 강제 적용 하는 것을 크게
  경고한다.
- **영속 ActionRun (포크 경계).** `build(thor_state_store=...)` 이
  진행 중인 ActionRun 을 `ActionRunStore` 프로토콜 로 영속화한다
  (`StateStoreActionRunStore` 가 `StateStore` 위에서 백업); `PantheonRuntime.run()`
  이 시작 시 이를 rehydrate 하므로 강제 적용 모드 재시작이 진행 중 변경
  추적이나 per-resource 락을 잃지 않는다. 최종 상태는 삭제되어
  진행 중인 작업만 복원된다. 업스트림 기본은 in-memory(shadow); 포크 는
  영속 `Saga` 와 함께 영속 저장소 를 주입한다. Forseti는 모든 Verdict에
  액션 멱등성 키를 보존하고 Thor는 각 수명 주기 이벤트 키와 구분해 저장합니다.
  런타임은 `StateStoreOpenActionEvidenceProvider`를 통해 이 활성 인덱스를 읽습니다.
  Indexed 행이 없거나 malformed이면 충돌로 처리하므로 불완전한 영속성이
  자율성을 높일 수 없습니다.
- **shadow 관측.** 전용 관찰기 소비자 그룹 이 판테온이 내릴 결정
  (판정 risk 분포 + ActionRun 최종 상태)을 `shadow_decisions` 로
  집계하고 `health()` 가 표면화한다 - "shadow before 강제 적용" 에 필요한
  측정 가능한 기준선. 별도 그룹 이라 실제 구독자의 레코드를 가로채지
  않는다.
- **divergence 측정.** `ShadowDivergenceLedger` 가 판테온의 shadow 판정 와
  권위 있는 P1 결정을 `correlation_id` 로 조인해 agreement 비율 와
  방향성 있는 `authoritative->pantheon` divergence breakdown 을 보고한다 -
  shadow 능력을 강제 적용 로 올리는 실제 승격 게이트. 이 원장 는
  core-agnostic(순수 결정 문자열, `core` 미가져오기)이다: 판테온 관찰기 가
  shadow 쪽을, P1 소비자(`_authoritative_decision`)가 권위 있는 쪽을
  먹이며, `ControlLoop` 을 건들지 않고 조립 루트 에서 조인된다.
  매칭은 증분적이고 LRU-bounded 다.
- **하트비트.** `run(heartbeat_interval=...)` /
  `FDAI_PANTHEON_HEARTBEAT_SECONDS` 가 companion 태스크를 띄워 고정 주기로
  `pantheon_heartbeat`(`health()` 스냅샷)를 로깅한다 - Heimdall 의
  per-minute agent-health 프로브의 최소 형태.
- DLQ 쓰기는 격리된다(`_safe_dead_letter`): DLQ 경로의 브로커 hiccup 은
  카운트되지 컨슈머를 죽이지 않는다.
- Huginn 의 dedup 메모리는 범위가 제한된(LRU, `dedup_capacity`)라 장수 프로세스
  가 leak 하지 않는다; 안정 키 없는 원시 유입 이벤트는 DLQ 폭주 대신
  경고(`pantheon_ingress_unkeyed_event`)와 함께 폐기 된다(P1 루프가 같은
  레코드를 여전히 처리하므로).

에이전트의 `bus` 경계 은 `PantheonBus` 프로토콜(`services/core-control-plane/src/fdai/agents/_framework/bus.py`)로
타입되며, in-memory `InMemoryBus`(테스트)와 Kafka 기반
`EventBusBridge`(프로덕션) 둘 다 이를 만족한다; base 클래스의
`Agent.bind_bus` 로 조립 루트 가 모든 에이전트를 균일하게 연결 한다.

**실제 브로커 전제조건:** 에이전트가 발행/구독하는 `object.<type>`
토픽은 pantheon 런타임을 명시적으로 비활성화하지 않을 때 Event Hubs에 존재해야 합니다.
그 허브 프로비저닝은 infra 관심사(`infra/modules/event-bus/`)이며 플래그
자체의 범위 밖이다.

### 13.6 LLM 호출 표면 (웨이브 전반)

웨이브 전체의 모델 바인딩, 품질 게이트, 숙의 및 측정 상세는
[판테온 지원 부록](README-ko.md#웨이브-전반의-llm-호출-표면)에서 관리합니다.

## 14. 타임라인 형태 (commitment 아님)

[타임라인 형태](README-ko.md#타임라인-형태-commitment-아님)를 참조하세요.

## 15. 범위 밖

[범위 밖](README-ko.md#범위-밖)을 참조하세요.

## Next 단계

| 학습 주제 | 읽기 |
|----------|------|
| 판테온 설계 (역할, 온톨로지, 계약) | [agent-pantheon.md](agent-pantheon-ko.md) |
| W7 에서 착지하는 13개 워크플로우 | [agent-workflows.md](agent-workflows-ko.md) (W0) |
| W0 이 참조하는 ActionType 스키마 | [action-ontology.md](../decisioning/action-ontology-ko.md) |
| W8 이 참조하는 KPI 측정 파이프라인 | [goals-and-metrics.md](../architecture/goals-and-metrics-ko.md) |
| W2, W5, W6 이 참조하는 포크 경계 | [project-structure.md](../architecture/project-structure-ko.md#customization-via-dependency-injection), [downstream-fork-guide.md](../fork-and-sequencing/downstream-fork-guide-ko.md) |
| 기존 standard-set 웨이브 계획 (스타일 참고용) | [implementation-plan.md](../fork-and-sequencing/implementation-plan-ko.md) |
