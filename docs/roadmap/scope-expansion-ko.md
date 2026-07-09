---
title: 스코프 개선 및 구조적 갭
translation_of: scope-expansion.md
translation_source_sha: 4df3bcc4eb3b00c5b469d27b9393eb90cee4e5f1
translation_revised: 2026-07-09
---
# 스코프 개선 및 구조적 갭

FDAI는 자율 클라우드 운영 컨트롤 플레인으로 자리잡고 있지만
([copilot-instructions.md](../../.github/copilot-instructions.md)),
초기 vertical - Change Safety, Resilience, Cost Governance -는
FDAI 배포가 성장해 나갈 운영 duty 중 일부만 cover 한다.
이 문서는 P2/P3 axis 확장을 위한 **스코프 결정**을 못박아,
이후의 모든 구조적 변경이 명시된 design intent 를 기준으로
landing 하도록 한다.

Reference: 로드맵 레벨의 duty 목록은
[goals-and-metrics.md](goals-and-metrics-ko.md) (KPI 1-4 + guard
metric); layered runtime shape 은
[app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md);
CSP-neutral wire contract 는
[csp-neutrality.md](csp-neutrality-ko.md); trust-router / risk-gate /
control loop 은
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md).

## 1. In-scope axes (유지 + 확장)

| Axis | Position | Rationale |
|------|----------|-----------|
| **Change Safety** | vertical 유지. Foundational. | Deterministic-first ⇢ policy-gate ⇢ shadow → enforce 는 현재 가장 강력한 story. |
| **Resilience (DR/Chaos)** | vertical 유지. Chaos Studio adapter shipped. | Prod-exclusion invariant + `chaos:opt-out` 태그는 industry 에서 드문 safety floor 제공. |
| **Cost Governance (FinOps)** | vertical 유지. | 확립된 FinOps guardrail 패턴에 align. |
| **Incident lifecycle** | **새 first-class object.** § 3.1 참조. | Postmortem, RCA depth, on-call handoff 를 block. 이것 없이는 그것들 ship 불가. |
| **Telemetry ingestion** | **Layer-0 seam 확장 5 → 8.** § 3.2 참조. | Metric / log / trace consumer 부재; anomaly + predictive + RCA 가 이 없이는 capped. |
| **Workload SLO / error budget** | **새 subsystem.** § 3.3 참조. | 컨트롤 플레인 SLO 는 존재 ([deployment.md § 157](deployment.md)); incident 우선순위를 rank 하는 workload-facing SLI/SLO/burn-rate 추상화는 부재. 두 identity 를 혼동하지 않도록 컨트롤 플레인 SLO 와 분리 유지. |
| **Runbook orchestration** | **새 primitive layer.** § 3.4 참조. | 현재 ActionType 은 leaf; runbook 은 rollback branch 를 갖는 ActionType 위의 DAG. |
| **On-call schedule** | **새 provider.** § 3.5 참조. | 오늘의 HIL 라우팅은 role-based; schedule-based 아님. Break-glass pager 는 존재하지만 누가 shift 중인지 모름. |
| **Postmortem draft** | **새 core module.** § 3.6 참조. | Incident + audit trail 로 feed. LLM-optional (template-based default). |
| **Full T1/T2 wiring into ControlLoop** | **T1 + T2 wired (shadow-only); T2 실행 pending.** § 3.7 참조. | `ControlLoop.__init__` 은 optional `t1_engine` + `t2_engine` 을 accept; loop 은 `T0.abstain -> T1.reuse-log -> T2.propose + quality-gate` 를 실행하며 각 verdict 를 실행 없이 audit. eligible 한 T2 candidate 에서 `Action` 을 빌드해 risk-gate 로 route 하는 것이 남음. |

## 2. 명시적으로 deferred 된 axes (이 확장에 포함되지 않음)

| Axis | Position | Rationale |
|------|----------|-----------|
| Multi-cloud (AWS / GCP) | 이후 phase 로 deferred. | 구현 focus 는 Azure 유지; wire-contract seam (§ 3.2) 이 AWS adapter 를 additive 로 유지. |
| Predictive capacity / autoscaling | Deferred. | Telemetry ingestion (§ 3.2) 이 stub 이 아니라 real 이어야 depend 가능. § 3.2 먼저 ship 후 이것을 이후 phase 에서. |
| Status page / stakeholder broadcast | Deferred. | Incident object (§ 3.1) 이 전제 조건; broadcast 는 delivery-layer adapter 이고 독립적으로 land. |
| PagerDuty / OpsGenie 통합 | Deferred. | `OnCallSchedule` provider (§ 3.5) 가 seam 정의; specific vendor adapter 는 upstream 이 아닌 fork model 에 land. |
| DORA metric ingestion (change-failure-rate, deploy-frequency) | Deferred. | MTTR + lead time 은 이미 [goals-and-metrics.md](goals-and-metrics-ko.md) 에 존재; 부재한 두 piece 는 P2 스코프 밖의 git-history reader 가 필요. |

## 3. 구조적 변경 (design contract)

아래 모든 subsystem 은
[architecture.instructions.md § Safety Invariants](../../.github/instructions/architecture.instructions.md#safety-invariants)
의 standing invariant 를 honor MUST: 모든 자율 액션은 stop-condition,
rollback path, blast-radius limit, audit entry 를 carry; 새 capability
는 shadow mode 로 먼저 ship.

### 3.1 Incident 를 first-class object 로

**Problem.** 오늘의 이벤트 correlation 은 `event_ingest` 내에서
`incident_id` 문자열을 produce 하지만, `Incident` dataclass 도, state
machine 도, lifecycle hook 도 없다. 결과적으로:

- 하나의 correlated group 에 대한 여러 finding 이 하나의 entity 의
  형제가 아니라 - key 를 공유하는 이벤트일 뿐;
- postmortem, on-call handoff, after-action review 를 걸 장소가 없음;
- incident 별 audit query 는 incident-indexed lookup 이 아니라 full-scan
  filter 요구.

**Design.**

- **Schema**: `shared/contracts/incident/schema.json` (JSON Schema
  2020-12) + `shared/contracts/models.py` 의 pydantic `Incident` 모델.
  Field: `incident_id` (correlation key 로부터 deterministic), `state`,
  `severity`, `opened_at`, `mitigated_at`, `resolved_at`, `closed_at`,
  `correlation_keys`, `member_event_ids`, `related_finding_ids`,
  `related_action_ids`, `assignee_oid` (Entra OID; no-self-approval
  유지를 위해 submitter 와 distinct), `mitigation_summary`,
  `postmortem_ref`.
- **State machine**: `open → triaging → mitigated → resolved → closed`
  + reopen path `resolved → triaging`. 불법 transition 은
  `IncidentTransitionError`. Transition 은
  `(incident_id, target_state, actor_oid)` 로 idempotent.
- **Persistence**: `StateStore` 를
  `append_incident_transition(entry: Mapping)` 로 확장; concrete
  Postgres adapter 는 transition 을 동일한 audit stream 으로 hash-chain
  (see [security-and-identity.md § Auditability](security-and-identity-ko.md)),
  append-only 보장을 어느 것도 bypass 하지 않음.
- **Ownership**: `core/incident/` (신규 패키지). Vertical 은 candidate
  transition 을 emit; incident 모듈만이
  `append_incident_transition` 을 호출할 수 있는 유일한 writer.

**Storm 처리.** 하나의 근본 결함이 다수의 상관 incident 로 fan-out 될 때,
모든 remediation 을 한꺼번에 발화하면 blast radius 가 배가되고 공유
의존성에서 race 가 나며 운영자를 파묻어 버린다. `core/incident/storm.py`
(`StormCoordinator`) 는 인간 지휘관의 판단을 증류한 결정론적이고 I/O 없는
incident-command 플래너다:

- **Storm 감지** 는 sliding window 안의 signal 을 세고, threshold 이상의
  count 는 storm 이다.
- **우선순위 시퀀싱** 은 remediation 을 severity(SEV1 우선), 그다음 blast
  radius, 그다음 stable id 순으로 정렬해 계획을 재현 가능하게 한다.
- **동시성 캡** 은 정렬된 계획을 capped wave 로 나눈다; storm 중에는 캡이
  더 조여진다(기본 1 = 엄격한 직렬) 그래서 fan-out 이 병렬로 실행되지 않는다.
- **동적 HIL** 은 `StormPolicy` 를 반환하며, storm 이 활성인 동안 승인 기준을
  올려(설정된 severity 이상에서 상향) 고영향 액션이 storm 중 자동 실행되지
  않게 한다.

이 coordinator 는 advisory 다 - risk gate 와 executor 가 그
`StormPolicy` 와 정렬된 계획을 소비한다; 스스로 실행하거나 lock 을 잡거나
model 을 호출하지 않으므로 `core/` import 규칙 아래 머문다.

### 3.2 Telemetry ingestion seam (Layer-0 확장)

**Problem.** [csp-neutrality.md](csp-neutrality-ko.md) 는 다섯 개의
wire-level contract 를 선언 (event bus, state store, secret, workload
identity, inventory). OpenTelemetry 는 컨트롤 플레인 트레이스를 emit
하지만 외부 metric, log, trace 를 consume 하는 것이 없다. 이는
`observability-and-detection.md` design 을 correlation only 로 cap -
anomaly, forecast, RCA 는 real telemetry 위에 ground 할 수 없음.

**Design.**

- **`shared/providers/` 아래 세 개의 새로운 async Protocol**:
  - `MetricProvider.query(query: MetricQuery) -> AsyncIterator[MetricPoint]`
    (Prometheus PromQL, Azure Monitor Logs, 또는 CloudWatch 로 backed;
    upstream 은 local no-op + 문서화된 shape ship).
  - `LogQueryProvider.query(query: LogQuery) -> AsyncIterator[LogRecord]`
    (Log Analytics KQL, Loki LogQL 등으로 backed).
  - `TraceQueryProvider.query(query: TraceQuery) -> AsyncIterator[Span]`
    (App Insights, Tempo, Jaeger 로 backed).
- Wire contract 수가 **5 → 8** 로 증가; [csp-neutrality.md](csp-neutrality-ko.md)
  는 seam 을 introduce 하는 동일 PR 에서 update.
- **Default upstream binding**: 빈 iterator 를 반환하는 local no-op
  provider. Real adapter (Azure Monitor, Log Analytics) 는 이어지는
  work item 에서 `delivery/azure/` 로 land; seam 만으로도 anomaly /
  forecast / RCA subsystem 이 안정된 interface 에 대해 author 되기에
  충분.
- **데이터가 흐르는 곳**: provider 는 structured record 를 produce 하고
  이것이 internal bus 상의 `Event` 객체가 되므로, trust-router 와
  risk-gate 가 무엇이 자율적으로 실행되는지에 대한 유일한 authority
  로 유지.

### 3.3 Workload SLO subsystem

**Problem.** [deployment.md § Observability, SLOs, and Alerting](deployment-ko.md)
는 **컨트롤 플레인** SLO 를 정의 (FDAI 자기 자신의 latency, success
rate, console availability). 부재한 나머지 절반은 **workload-facing
SLO** - user-facing incident 우선순위를 rank 하고 error-budget burn
동안 risky change 를 gate 하는 SLI/SLO/error-budget layer.

**Design.**

- **Schema**: `shared/contracts/slo/schema.json` -  `SLI` (query +
  threshold + kind={availability, latency, correctness, freshness}),
  `SLO` (objective ratio + window), `ErrorBudget` (derived),
  `BurnRate` (short + long window).
- **Module**: `core/slo/` 와 `SloRegistry` (`rule-catalog/slo/` 로부터
  YAML SLO load) 그리고 `BurnRateEvaluator` (Google SRE Chapter 5 의
  multi-window multi-burn-rate alerting).
- **컨트롤 루프로 wire back**: burn-rate breach 는
  `Event(event_type="slo.error_budget_burn")` 을 emit 하여 동일한
  trust-router → risk-gate → executor path 를 hit. Side channel 없음.
- **SLO subsystem 이 하지 않는 것**: [goals-and-metrics.md](goals-and-metrics-ko.md)
  를 replace 하지 않는다. 그 파일은 **FDAI 자신의 performance** 를
  측정; SLO subsystem 은 **FDAI 가 운영하는 workload** 를 측정.
  명확히 분리된 identity 로 coexist.

### 3.4 Runbook DAG orchestrator

**Problem.** 온톨로지의 `ActionType` 은 `stop_condition`,
`rollback_contract`, `blast_radius` 를 가진 leaf action. 실제 SRE
runbook 은 여러 ActionType 을 chain (예: `db.failover` → `app.restart`
→ `healthcheck` → on-fail `db.rollback`). 오늘은 composition primitive
없음.

**Design.**

- **Schema**: `shared/contracts/runbook/schema.json` - `RunbookStep`
  entry 의 ordered sequence, 각각 name 으로 ActionType 을 point,
  optional `on_failure` branch step id 포함.
- **Runner**: `core/runbook/runner.py` 와 `RunbookRunner.run(runbook,
  context)` 가 `RunbookResult` (per-step outcome + terminal state)
  반환. Runner 는 **모든 step 에서** 4 대 safety invariant 를 honor -
  terminal 뿐만 아니라 - 실패 step 의 rollback branch 자체가 runner
  short-circuit 전에 audit.
- **최소 viable 스코프**: linear sequence + single `on_failure` branch
  (real DAG 는 두 caller 가 필요할 때까지 deferred). "failover →
  restart → healthcheck → rollback" encode 하기에 충분.
- **Docs**: [action-ontology.md](action-ontology-ko.md) vocabulary
  재사용; 새 sibling doc `docs/roadmap/runbook.md`.

### 3.5 On-call schedule provider

**Problem.** `HilChannel` 은 Teams 채널로 approval 을 route; RBAC 은
role 로 approver 를 pick. 어느 쪽도 **누가 지금 shift 중인지** 모름.
새벽 3시에 "동일한" approver bucket 은 자고 있는 20명.

**Design.**

- **Protocol**: `shared/providers/oncall_schedule.py` 의
  `OnCallSchedule.current(rotation: str) -> OnCallShift`, `OnCallShift(rotation, primary_oid, secondary_oid, until)`
  반환.
- **Default upstream 구현**: config 로부터 shift 의 JSON list 를
  reading 하는 `StaticOnCallSchedule`. Fork model 은 PagerDuty /
  OpsGenie adapter 를 wire.
- **Integration**: `HilChannel.dispatch(...)` 는 optional
  `on_call_shift` 를 accept; coordinator layer 가 dispatch 전에
  `OnCallSchedule` 을 consult 하여 페이지 받는 party 가 role bucket 이
  아닌 shift-holder.
- **Fail-closed**: schedule provider 가 error 하면, HIL 요청은 전체
  role bucket 으로 fallback (기존 behavior) - request 를 drop 하지 않음.

### 3.6 Postmortem draft generator

**Problem.** SRE 문화는 모든 significant incident 후에 written PIR /
postmortem 을 demand. FDAI 는 raw material (audit log, finding,
action) 을 가지고 있지만 synthesizer 가 없다.

**Design.**

- **Module**: `core/postmortem/` 와 `Incident` id + optional
  `PostmortemLlm` binding 을 taking 하고 `PostmortemDraft` (structured
  markdown: summary, timeline, impact, root cause, contributing
  factors, actions taken, follow-up) 를 반환하는 `PostmortemGenerator`.
- **LLM 부재 시 fail-closed**: `PostmortemLlm` 이 bind 되지 않으면,
  generator 는 audit timeline 만으로 **template-based** draft 반환 -
  fabrication 없음, "TODO" 로 marked 된 missing section 없음; 각
  section 은 실제 audit data 로 채워지거나 명시적인 "no evidence
  recorded" line.
- **Output persistence**: draft 는 remediation PR 을 ship 하는 동일한
  PR-native delivery flow 로 `rule-catalog/postmortems/<incident-id>.md`
  아래의 git-managed location 에 write, review / approval 이 기존
  gate 재사용. [action-ontology.md](action-ontology-ko.md) 의
  `pr_native` execution path 를 의도적으로 재사용.
- **Knowledge extraction (재사용 lesson)**:
  `core/postmortem/learning.py` (`PostmortemKnowledgeExtractor`) 가
  *resolved* incident 와 그 audit timeline 을 inert `PostmortemLearning`
  candidate 로 mining 한다 - 조직이 원래 엔지니어 머릿속에만 두는 "이
  패턴이 발생했을 때 이 action 이 해결했다" 는 지식이다. 결정론적이며
  **fail-closed**: audit trail 에 기록된 root cause *와* 최소 하나의
  성공적으로 실행된(enforce-mode, success-outcome) action 이 있을 때만
  learning 을 emit 하고, 그렇지 않으면 **abstain** - lesson 을 절대
  fabricate 하지 않는다. learning 은 특정 resource id 로부터 일반화한다
  (correlation-key *prefix* 로 anchor 하므로 `resource:vm-a` 는
  `vm-a` 가 아니라 재사용 가능한 anchor `resource` 를 기여), discovery
  loop 이 반복 패턴을 dedup 할 수 있도록 결정론적 `signature` 를
  carry 하며, 다른 rule candidate 와 동일한 `CandidateGuard` 를 통과하도록
  grounded `provenance` 를 ship 한다. 출력은 action 도 catalog edit 도
  아닌 지식이다: memory / discovery loop
  ([rule-catalog-collection.md](rule-catalog-collection-ko.md)) 에
  feed 되고 catalog 에 영향을 주기 전 표준 quality gate 를 통과해야 한다.

### 3.7 T1 / T2 tier 를 `ControlLoop` 로 wire

**Status.** T1 과 T2 모두 loop 에 wired; T2 실행이 남은 단계.
`ControlLoop.__init__` 은 optional `t1_engine`(`T1Tier`) 과
`t2_engine`(`T2Tier`) - 둘 다 Protocol-typed - 을 accept. `process` 는
`T0.abstain -> T1.reuse-log -> T2.propose + quality-gate` 를 실행하며,
각 tier hop 은 자체 audit entry 를 write 하여 decision 이 reconstructable.
두 tier 는 이 wiring 에서 **shadow-only**: T1 similarity hit 은
`T1_REUSE_LOGGED` 로, T2 verdict 는
`T2_PROPOSED_LOGGED` / `T2_ESCALATED` / `T2_DENIED` / `T2_ABSTAINED` 로
기록되지만 둘 다 실행하지 않음 - authoritative decision 은 `abstain` 으로
유지되고 아무것도 build/route 되지 않음. T2 output 은 eligible 이 되기
전에 `QualityGate`(mixed-model cross-check + verifier + grounding)를
통과함.

**Remaining design (T2 실행).**

- eligible 한 `QualityCandidate`(`T2Outcome.PROPOSED`)에서 `Action` 을
  빌드해 risk-gate + executor 로 route - shadow-only T2 log 를 gated
  action 으로 바꾸는 한 단계이며, T1 reuse 가 아직 필요로 하는 동일한
  P2 단계.
- gate `ELIGIBLE` verdict 만 risk-gate 에 도달; `ESCALATE` / `DENIED` /
  `ABSTAIN` 은 절대 auto-execute 되지 않음. execution eligibility 는
  결정론적 gate 가 부여하며, model 은 절대 부여하지 않음.

**Scenario replay.** [tests/scenarios/v2026.07/](../../tests/scenarios/v2026.07/)
의 frozen 시나리오는 shipped 룰이 매핑되는 곳마다
[tests/scenarios/enrichment/v2026.07/](../../tests/scenarios/enrichment/v2026.07/)
overlay 로 T0 에서 enrich 됨 - 예:
`finops.stop-idle-dev-vm-off-hours.003` 은 `compute.vm.idle-detected` 발화,
`dr.replica-lag-degraded.001` 은 `postgresql-server.high-availability` 발화
(risk-gate 경유 HIL).
overlay 가 아직 없는 시나리오는 `xfail` 유지:
`dr.chaos-experiment-novel.003`(T2 필요),
`dr.backup-vault-restore-rehearsal.002` /
`change.drift-manual-portal-edit.003`(shipped 룰 author 필요).

### 3.8 Vertical registry (new-domain 온보딩 seam)

**Problem.** FDAI 는 세 vertical (Resilience, Change Safety, Cost
Governance)을 ship 하지만, "조직 대체"는 그 집합이 **`core/` 편집 없이**
security posture, compliance, patch management 로 커져야 함을 의미한다. 오늘은
셋이 직접 composed 되며, fork 가 네 번째를 onboard 할 선언된 seam 이 없다.

**Design.**

- **Module**: `core/verticals/registry.py` 의 `VerticalRegistry` 가 inert
  `VerticalDescriptor` (`vertical_id`, `display_name`, `category`,
  `rule_source_ids`, `enabled`, `default_mode`)를 보유한다. fork 가
  composition root 에서 descriptor 를 등록하고, control loop 은 셋을
  hard-code 하는 대신 registry 를 enumerate 한다.
- **Validating, plugin loader 아님.** 등록은 misconfigured onboarding 을
  즉시 reject 한다: 중복이거나 non-ASCII 인 `vertical_id`, rule source 를
  명명하지 않은 **enabled** vertical (아무것도 감지하지 않는 도메인), 또는
  enforce mode 로 직접 onboard 하려는 descriptor. `register_all` 은 첫 실패에서
  abort 하므로 부분 batch 가 half-register 될 수 없다.
- **구성상 shadow-first.** `default_mode` 는 `Mode.SHADOW` 로 default 되고
  onboarding 시 shadow 로 유지되어야 한다 - enforce 로의 promotion 은 별도
  reviewed change 이므로, onboarding 이 절대 autonomous action 을 silently
  enable 할 수 없다. Enumeration (`all`, `enabled`)은 id-sorted 이고 결정론적이다.

## 4. Rollout 순서 및 safety mode

위 모든 subsystem 은 **shadow mode** 로 먼저 ship
([architecture.instructions.md § Safety Invariants](../../.github/instructions/architecture.instructions.md#safety-invariants)).
Enforce 로의 promotion 은 module 의 `promotion_gate` 가 선언하는
shadow accuracy 로 gated 된 별도 change (rule / ActionType promotion
계약을 mirror).

Rollout 순서는 strict prerequisite chain 을 pick:

1. **§ 3.1 Incident** 와 **§ 3.2 Telemetry** 는 독립적 - 둘 다 동일
   phase 에서 ship, 순서 무관.
2. **§ 3.7 T1/T2 wiring** - T1 은 이미 shipped; T2 는 `t2_reasoning` tier 라이브러리 구축이 선행.
3. **§ 3.3 SLO** 는 § 3.2 depend (real burn-rate 는 metric ingestion
   필요).
4. **§ 3.6 Postmortem** 은 § 3.1 depend.
5. **§ 3.5 On-call** 은 독립적.
6. **§ 3.4 Runbook** 은 독립적 - 기존 ActionType 을 compose.

## 5. 이 문서가 아닌 것

- Phase plan 아님. Phase 는 [docs/roadmap/phases/](phases/) 아래 존재
  하며 이러한 subsystem 을 maintainer 의 schedule 에 따라 slot.
- Customer-facing spec 아님. FDAI 는 customer-agnostic 유지; § 3.2 의
  wire contract 는 fork model
  ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md))
  intact 유지.
- 완전한 운영 coverage claim 아님. § 2 의 deferred axis 는 phase 가
  명시적으로 집을 때까지 의도적으로 out of scope 유지.

## 6. SRE Agent duty coverage

SRE agent 가 커버하리라 기대되는 baseline 의무를, 그것을 구현하는 FDAI
서브시스템에 대해 정직하게 매핑합니다. `Covered` 는 `core/` 서브시스템과 그
규칙/테스트가 존재함을 뜻하고; `Partial` 은 서브시스템은 있으나 선언된 의존성이
아직 deferred 임을 뜻하며; `Deferred` 는 seam 만 설계됨(§ 2 / § 3), 배선 안 됨을
뜻합니다.

| SRE 의무 | 상태 | 위치 |
|----------|------|------|
| Incident 감지 / triage / lifecycle | Covered | `core/incident/` (§ 3.1), `core/event_ingest/` |
| Root-cause analysis | Covered | `core/rca/`, [observability-and-detection.md](observability-and-detection-ko.md) |
| 자동 완화(risk-gated) | Covered | `core/risk_gate/`, `core/executor/`, [risk-classification.md](risk-classification-ko.md) |
| Postmortem | Covered | `core/postmortem/` (§ 3.6) |
| Anomaly / forecast / correlation | Covered | `core/detection/`, [observability-and-detection.md](observability-and-detection-ko.md) |
| Capacity planning | Covered | `core/capacity/` |
| Runbook orchestration | Covered | `core/runbook/` (§ 3.4) |
| Change safety / pre-deploy feasibility | Covered | `core/deploy_preflight/`, [deployment-preflight.md](deployment-preflight-ko.md) |
| Posture 리뷰 / 아키텍처 Q&A | Covered | `core/assurance_twin/`, [assurance-twin.md](assurance-twin-ko.md) |
| **Dev-to-ops 핸드오프 (정책 + RBAC 리뷰)** | Covered | [operational-readiness.md](operational-readiness-ko.md) (ORR) |
| **Identity / RBAC 최소권한 posture** | Covered | 워크로드 RBAC 규칙 팩(`*.role-assignment.*`) + `remediate.right-size-role` |
| SLO / error budget | Partial | `core/slo/`: `MetricBurnRateSource` 가 § 3.2 metric seam 을 burn-rate evaluator 에 브리지하고 `SloBurnRunner.run_once` 가 `slo.error_budget_burn` 이벤트를 발행(데이터 누락 시 fail-closed); real vendor `MetricProvider` adapter + infra cron 트리거만 남음 |
| Monitoring / alerting (외부 signal ingestion) | Partial | `core/detection/` correlation 은 ship; § 3.2 metric seam 은 SLO burn-rate 에, log / trace seam 은 RCA telemetry grounding(`TelemetryEvidenceGatherer`)에 소비됨; real vendor adapter 만 남음 |
| On-call 스케줄 / paging | Partial | § 3.5 `OnCallSchedule` seam + core `OnCallResolver`(fail-safe fallback)가 HIL parking + audit 에 배선됨(누가 당번이었는지 기록); PagerDuty / OpsGenie vendor adapter 와 card DM-targeting 은 fork 에 land (§ 2) |
| Status page / stakeholder broadcast | Deferred | § 2 (Incident object 이 전제) |
| DORA change-failure-rate / deploy-frequency | Deferred | § 2 (git-history reader 필요) |

두 `Partial` 행은 이제 하나의 남은 전제 - composition root 에 바인드된 real vendor
`MetricProvider` adapter - 를 공유합니다. § 3.2 Protocol, 그 in-memory 바인딩,
그것을 consume 하는 `core/slo/` 브리지, 그리고 breach 이벤트를 발행하는
`SloBurnRunner` 가 모두 존재합니다; 구체 backend 와 `run_once` 를 호출하는 out-of-band
cron 트리거만 남았고, 둘 다 `core/` 재작성 없이 additive 로 land 합니다(fork
adapter + infra job). `Deferred` 행은 컨트롤 루프의 gap 이 아니라 설계상 seam 입니다.

