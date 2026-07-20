---
title: 스코프 개선 및 구조적 갭
translation_of: scope-expansion.md
translation_source_sha: c8e95685444b8d45d679d10b8284df997ba2d306
translation_revised: 2026-07-21
---
# 스코프 개선 및 구조적 갭

FDAI는 자율 클라우드 운영 컨트롤 플레인으로 자리잡고 있지만
([copilot-instructions.md](../../../.github/copilot-instructions.md)),
초기 vertical - Change Safety, Resilience, Cost Governance -는
FDAI 배포가 성장해 나갈 운영 duty 중 일부만 cover 한다.
이 문서는 P2/P3 axis 확장을 위한 **스코프 결정**을 못박아,
이후의 모든 구조적 변경이 명시된 design intent 를 기준으로
landing 하도록 한다.

Reference: 로드맵 레벨의 duty 목록은
[goals-and-metrics.md](../architecture/goals-and-metrics-ko.md) (KPI 1-4 + guard
metric); layered runtime shape 은
[app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md);
CSP-neutral wire contract 는
[csp-neutrality.md](../architecture/csp-neutrality-ko.md); trust-router / risk-gate /
control loop 은
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md).

> **구현 상태 (2026-07-21).** §3에서 제안한 Incident, 8개 telemetry wire contract, workload
> SLO, runbook, on-call, postmortem, vertical registry는 배포됐습니다. §3의 `Problem` 문단은
> 채택 당시 historical gap을 보존합니다. T2 candidate의 Action build와 unified risk/HIL routing도
> 배포됐고, risk-eligible T2 action을 executor로 넘기는 최종 단계만 남았습니다.

## 1. In-scope axes (유지 + 확장)

| Axis | Position | Rationale |
|------|----------|-----------|
| **Change Safety** | vertical 유지. Foundational. | Deterministic-first ⇢ policy-gate ⇢ shadow → enforce 는 현재 가장 강력한 story. |
| **Resilience (DR/Chaos)** | vertical 유지. Chaos Studio adapter shipped. | Prod-exclusion invariant + `chaos:opt-out` 태그는 industry 에서 드문 safety floor 제공. |
| **Cost Governance (FinOps)** | vertical 유지. | 확립된 FinOps guardrail 패턴에 align. |
| **Incident lifecycle** | **배포됨.** § 3.1 참조. | Durable lifecycle, proposal, notification, SLA, storm coordination 제공. |
| **Telemetry ingestion** | **Layer-0 seam 8개 및 Azure adapter 배포됨.** § 3.2 참조. | Metric/log/trace가 SLO, detection, RCA를 grounding. |
| **Workload SLO / error budget** | **배포됨.** § 3.3 참조. | Workload SLI/SLO/burn을 control-plane SLO와 분리 유지. |
| **Runbook orchestration** | **배포됨.** § 3.4 참조. | Bounded step/rollback orchestration 제공. |
| **On-call schedule** | **배포됨.** § 3.5 참조. | Static + PagerDuty schedule과 role fallback 제공. |
| **Postmortem draft** | **배포됨.** § 3.6 참조. | Template-first draft와 grounded learning candidate 제공. |
| **Full T1/T2 wiring into ControlLoop** | **Action build + risk/HIL route 배포, eligible execution pending.** § 3.7 참조. | Quality-gated T2 candidate는 Action으로 빌드되어 unified risk gate에 도달합니다. |

## 2. 명시적으로 deferred 된 axes (이 확장에 포함되지 않음)

| Axis | Position | Rationale |
|------|----------|-----------|
| Multi-cloud (AWS / GCP) | 이후 phase 로 deferred. | 구현 focus 는 Azure 유지; wire-contract seam (§ 3.2) 이 AWS adapter 를 additive 로 유지. |
| Predictive capacity / autoscaling | Deferred. | Telemetry ingestion (§ 3.2) 이 stub 이 아니라 real 이어야 depend 가능. § 3.2 먼저 ship 후 이것을 이후 phase 에서. |
| Public status-page endpoint | Deferred. | Stakeholder briefing과 다중 channel delivery는 배포됐고 public endpoint binding만 external입니다. |

## 3. 구조적 변경 (design contract)

아래 모든 subsystem 은
[architecture.instructions.md § Safety Invariants](../../../.github/instructions/architecture.instructions.md#safety-invariants)
의 standing invariant 를 honor MUST: 모든 자율 액션은 stop-condition,
rollback path, blast-radius limit, audit entry 를 carry; 새 capability
는 shadow mode 로 먼저 ship.

이 절의 `Problem`은 채택 당시 gap이고 `Design`은 현재 landed contract를 설명합니다. 구체 status는
위 구현 상태와 §6 coverage 표를 따릅니다.

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
  `(incident_id, target_state, actor_oid)` 로 idempotent. Severity는
  `resolved → triaging` reopen edge에서만 변경할 수 있으며 replay에 보존됩니다.
- **Persistence**: `StateStore` 를
  `append_incident_transition(entry: Mapping)` 로 확장; concrete
  Postgres adapter 는 transition 을 동일한 audit stream 으로 hash-chain
  (see [security-and-identity.md § Auditability](../architecture/security-and-identity-ko.md)),
  append-only 보장을 어느 것도 bypass 하지 않음. Append는 `applied` 또는
  `duplicate`를 반환하며 stale expected state는 `IncidentWriteConflictError`를
  발생시킵니다. PostgreSQL은 per-incident advisory lock을 잡고 persisted current
  state를 확인한 뒤 global audit hash chain에 한 transaction으로 append합니다.
  Losing replica는 conflict를 반환하기 전에 canonical audit projection을 reload합니다.
- **Ownership**: `core/incident/` (신규 패키지). Vertical 은 candidate
  transition 을 emit; incident 모듈만이
  `append_incident_transition` 을 호출할 수 있는 유일한 writer.
- **Lifecycle metadata**: assignment 변경은 `incident.assigned`를 append합니다.
  성공한 GitHub/Jira/tool receipt는 provider, external id, optional HTTPS URL을
  포함한 `incident.ticket`을 append합니다. 둘 다 idempotent하고 replay-safe하며
  동일한 audit-backed incident roster에 표시됩니다. Vendor call은 delivery adapter에
  유지되고 registry는 성공 receipt만 연결합니다.

**기본 제공 lifecycle workflow.** `IncidentLifecycleWorkflow`는
`IncidentRegistry` 위에서 생성과 transition을 처리하는 단일 경로를 제공합니다.

- Contributor 역할의 운영자는 영어 또는 한국어 채팅으로 incident 생성을 요청할
  수 있습니다. 결정론적 parser는 incident/open 의도, severity, 대상을 요구하며
  누락된 값은 추측하지 않고 다시 묻습니다. 완전한 요청은 생성 내용을 설명하는
  10분짜리 proposal을 만들고, 같은 conversation의 같은 운영자만 확인할 수 있습니다.
- allowlist에 포함된 agent는 하나 이상의 member event와 비어 있지 않은 reason을
  제공할 때만 대화형 확인 없이 incident를 열 수 있습니다. 따라서 자율 생성은
  관찰된 evidence에 grounding됩니다.
  Production은 pantheon이 event consume을 시작하기 전에 Heimdall의 repeated-event
  candidate hook을 동일한 durable workflow에 전달합니다.
- open 재전송과 같은 상태로의 transition은 idempotent하며 중복 알림을 보내지
  않습니다. 모든 lifecycle audit row는 결정론적 incident id를 top-level
  `correlation_id`로 전달하므로 console roster가 resource name에서 연관 관계를
  추론하지 않고 투영할 수 있습니다. 새 member event는 `incident.members` row를
  append하므로 correlation 확장이 재시작 후에도 유지됩니다.
- 생성, 합법적인 상태 변경, 요청된 roster summary는
  `DurableIncidentLifecycleNotifier`로 감싼 `RoutedIncidentLifecycleNotifier`를 통해
  A2 운영 알림을 보냅니다. 각 lifecycle occurrence는 stable `audit_id`를 가지며,
  sent checkpoint는 반복 전달을 막고 startup replay는 checkpoint가 없는 audit
  row를 재시도합니다. 실제 channel adapter가 bind되지 않으면 production default는
  알림을 버리지 않고 StateStore-backed HIL escalation sink로 라우팅합니다.
  Lifecycle 메시지는 자유 형식 reason과 resource correlation key를 제외하며,
  roster 메시지는 최대 20개 incident id와 전체 roster 링크를 포함합니다.

in-process registry는 source of truth가 아니라 projection입니다. Production startup은
Postgres에서 정렬된 `incident.open`, `incident.members`, `incident.transition` row를
읽고 API가 traffic을 받기 전에 registry를 재구성합니다. 유효하지 않은 id, state
ordering, timestamp는 이전 snapshot을 교체하지 않고 startup을 실패시킵니다. Pending
chat proposal은 async `IncidentProposalStore`를 사용합니다. Local development는 bounded
in-memory store를 bind하고 production은 atomic Postgres `DELETE ... RETURNING` consume을
사용하므로 하나의 replica만 confirmation을 수락할 수 있습니다. Persisted proposal은
operator text 원문이 아니라 hash만 저장합니다. Local projecting store는 채팅에서
생성한 incident를 `/incidents`에 즉시 표시합니다.

**SLA escalation 및 metrics.** `IncidentSlaPolicy`는 모든 severity에 대해 설정된
acknowledgment 및 resolution seconds를 받습니다. Production monitor는
`FDAI_INCIDENT_SLA_POLICY_JSON`이 공급되기 전까지 disabled입니다. Enable되면 ordered
audit row에서 현재 state-entry timestamp를 도출하고 deadline에 stable `sla_breach`
A2 notice를 emit하며 durable notification checkpoint로 반복 scan을 dedup합니다.
Resolved 및 closed incident는 alert하지 않습니다. `project_incident_metrics`는
deduplicated audit row를 agent/operator 생성 수, 현재 state/severity 수, assignment 및
ticket 수, reopen 수, mean acknowledgment/resolution duration으로 투영합니다. 이 값은
KPI 및 briefing surface에 사용할 수 있는 measured fact입니다.
성공한 `tool_call` ticket receipt는 terminal executor success 전에 receipt observer를
통과합니다. Linkage 실패는 retryable합니다. Redelivery에서 adapter ledger가
`already_applied`를 반환하고 incident link만 다시 시도합니다.

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

**Problem.** [csp-neutrality.md](../architecture/csp-neutrality-ko.md) 는 다섯 개의
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
- Wire contract 수가 **5 → 8** 로 증가; [csp-neutrality.md](../architecture/csp-neutrality-ko.md)
  는 seam 을 introduce 하는 동일 PR 에서 update.
- **Default upstream binding**: 빈 iterator 를 반환하는 local no-op
  provider. 첫 live `MetricProvider` adapter 가 land 했다 -
  `delivery/azure/metric_logs.py` (`AzureMonitorLogsMetricProvider`,
  query REST API 위의 Log Analytics KQL). composition root 에서
  `bind_azure_monitor_logs` 로 bind 되고 dev 에서는 `Noop` 이 기본이라
  parity 계약이 유지된다. 남은 `LogQueryProvider` / `TraceQueryProvider`
  adapter 는 이어지는 work item 에서 land; seam 만으로도 anomaly /
  forecast / RCA subsystem 이 안정된 interface 에 대해 author 되기에
  충분.
- **데이터가 흐르는 곳**: provider 는 structured record 를 produce 하고
  이것이 internal bus 상의 `Event` 객체가 되므로, trust-router 와
  risk-gate 가 무엇이 자율적으로 실행되는지에 대한 유일한 authority
  로 유지.

### 3.3 Workload SLO subsystem

**Problem.** [deployment.md § Observability, SLOs, and Alerting](../deployment/deployment-ko.md)
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
- **SLO subsystem 이 하지 않는 것**: [goals-and-metrics.md](../architecture/goals-and-metrics-ko.md)
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
- **Docs**: [action-ontology.md](../decisioning/action-ontology-ko.md) vocabulary
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
  gate 재사용. [action-ontology.md](../decisioning/action-ontology-ko.md) 의
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
  ([rule-catalog-collection.md](../rules-and-detection/rule-catalog-collection-ko.md)) 에
  feed 되고 catalog 에 영향을 주기 전 표준 quality gate 를 통과해야 한다.

### 3.7 T1 / T2 tier 를 `ControlLoop` 로 wire

**Status.** T1 과 T2 모두 loop에 wired됐습니다. T2 candidate의 Action build, unified risk
evaluation, deny/HIL routing까지 배포됐고 risk-eligible candidate의 executor handoff만 남았습니다.
`ControlLoop.__init__` 은 optional `t1_engine`(`T1Tier`) 과
`t2_engine`(`T2Tier`) - 둘 다 Protocol-typed - 을 accept. `process` 는
`T0.abstain -> T1.reuse-log -> T2.propose + quality-gate` 를 실행하며,
각 tier hop 은 자체 audit entry 를 write 하여 decision 이 reconstructable.
T1 reuse는 **shadow-only**입니다. T2는 candidate를 Action/risk path까지 전달합니다. T1 similarity hit은
`T1_REUSE_LOGGED` 로, T2 verdict 는
`T2_PROPOSED_LOGGED` / `T2_ESCALATED` / `T2_DENIED` / `T2_ABSTAINED` 로
기록됩니다. T2 output은 eligible이 되기
전에 `QualityGate`(mixed-model cross-check + verifier + grounding)를
통과함.

**Remaining design (T2 실행).**

- unified risk decision이 `auto`인 T2 Action을 selected executor로 handoff하고 terminal
  receipt를 기록합니다. Action build와 risk routing은 이미 완료됐습니다.
- gate `ELIGIBLE` verdict 만 risk-gate 에 도달; `ESCALATE` / `DENIED` /
  `ABSTAIN` 은 절대 auto-execute 되지 않음. execution eligibility 는
  결정론적 gate 가 부여하며, model 은 절대 부여하지 않음.

**Scenario replay.** [tests/scenarios/v2026.07/](../../../tests/scenarios/v2026.07)
의 frozen 시나리오는 shipped 룰이 매핑되는 곳마다
[tests/scenarios/enrichment/v2026.07/](../../../tests/scenarios/enrichment/v2026.07)
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
([architecture.instructions.md § Safety Invariants](../../../.github/instructions/architecture.instructions.md#safety-invariants)).
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

- Phase plan 아님. Phase 는 [docs/roadmap/phases/](../phases) 아래 존재
  하며 이러한 subsystem 을 maintainer 의 schedule 에 따라 slot.
- Customer-facing spec 아님. FDAI 는 customer-agnostic 유지; § 3.2 의
  wire contract 는 fork model
  ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md))
  intact 유지.
- 완전한 운영 coverage claim 아님. § 2 의 deferred axis 는 phase 가
  명시적으로 집을 때까지 의도적으로 out of scope 유지.

## 6. SRE Agent duty coverage

SRE agent 가 커버하리라 기대되는 baseline 의무를, 그것을 구현하는 FDAI
서브시스템에 대해 정직하게 매핑합니다. `Covered` 는 `core/` 서브시스템과 그
규칙/테스트가 존재함을 뜻하고; `Partial` 은 서브시스템은 있으나 선언된 의존성이
아직 deferred 임을 뜻하며; `Deferred` 는 seam 만 설계됨(§ 2 / § 3), 배선 안 됨을
뜻합니다.

상세 비교는 이제 Azure SRE Agent의 51개 원자 capability, Microsoft Learn 공식 source,
runtime parity status와 정확한 FDAI evidence를
[SRE Agent parity audit](../../internals/sre-agent-parity-audit.md)에서 추적합니다. 아래 표는
duty 수준의 짧은 요약으로 유지합니다.

| SRE 의무 | 상태 | 위치 |
|----------|------|------|
| Incident 감지 / triage / lifecycle | Covered | `core/incident/` (§ 3.1), `core/event_ingest/` |
| Root-cause analysis | Covered | `core/rca/`, [observability-and-detection.md](../rules-and-detection/observability-and-detection-ko.md) |
| 자동 완화(risk-gated) | Covered | `core/risk_gate/`, `core/executor/`, [risk-classification.md](../decisioning/risk-classification-ko.md) |
| Postmortem | Covered | `core/postmortem/` (§ 3.6) |
| Anomaly / forecast / correlation | Covered | `core/detection/`, [observability-and-detection.md](../rules-and-detection/observability-and-detection-ko.md) |
| Capacity planning | Covered | `core/capacity/` |
| Runbook orchestration | Covered | `core/runbook/` (§ 3.4) |
| Change safety / pre-deploy feasibility | Covered | `core/deploy_preflight/`, [deployment-preflight.md](../deployment/deployment-preflight-ko.md) |
| Posture 리뷰 / 아키텍처 Q&A | Covered | `core/assurance_twin/`, [assurance-twin.md](../operations/assurance-twin-ko.md) |
| **Dev-to-ops 핸드오프 (정책 + RBAC 리뷰)** | Covered | [operational-readiness.md](../operations/operational-readiness-ko.md) (ORR) |
| **Identity / RBAC 최소권한 posture** | Covered | 워크로드 RBAC 규칙 팩(`*.role-assignment.*`) + `remediate.right-size-role` |
| SLO / error budget | Covered | `core/slo/`와 routed Prometheus, Azure Monitor Metrics, KQL provider를 사용하며 `SloBurnRunner`는 데이터 누락 시 fail closed합니다. |
| Monitoring / alerting (외부 signal ingestion) | Covered | Metric, bounded KQL, App Insights trace, Activity Log, diagnostic stream, anomaly, forecast, RCA telemetry grounding을 제공합니다. |
| On-call 스케줄 / paging | Covered | fail-safe `OnCallResolver`, 명시적 Entra mapping을 사용하는 PagerDuty roster adapter, PagerDuty Events v2 paging, role fallback을 제공합니다. |
| Status page / stakeholder broadcast | Covered | Stakeholder briefing과 Teams, Slack, email, webhook, PagerDuty, SMS channel을 제공합니다. Public status-page endpoint는 external binding입니다. |
| DORA change-failure-rate / deploy-frequency | Covered | `core/measurement/dora.py`가 정규화된 deployment observation에서 네 가지 DORA measure와 invalid/coverage count를 계산합니다. |

Deployment credential과 endpoint는 repository gap이 아니라 external configuration입니다.
설정되지 않은 adapter는 unavailable을 보고하거나 문서화된 role fallback을 사용하며 fixture를
대체하거나 autonomy를 승격하지 않습니다. Direct write CLI와 global auto-approval은 FDAI의 typed
action, policy, risk, approval, rollback, lock, idempotency, audit path로 의도적으로 대체합니다.
