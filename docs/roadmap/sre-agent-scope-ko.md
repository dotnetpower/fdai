---
title: SRE Agent 스코프 및 구조적 갭
translation_of: sre-agent-scope.md
translation_source_sha: 14e9a75f7270edd72c8af8802957a13e0f8e0289
translation_revised: 2026-07-07
---
# SRE Agent 스코프 및 구조적 갭

FDAI는 자율 클라우드 운영 컨트롤 플레인으로 자리잡고 있지만
([copilot-instructions.md](../../.github/copilot-instructions.md)),
초기 vertical - Change Safety, Resilience, Cost Governance -는
canonical SRE agent의 duty 중 일부만 cover 한다. 이 문서는 P2/P3 axis
확장을 위한 **스코프 결정**을 못박아, 이후의 모든 구조적 변경이
명시된 design intent 를 기준으로 landing 하도록 한다.

Reference: 20-axis SRE canonical duty 목록은
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
| **Full T1/T2 wiring into ControlLoop** | **library-only 에서 wired 로 promote.** § 3.7 참조. | Tier 라이브러리는 `core/tiers/` 아래 존재; `ControlLoop.__init__` 은 오늘 `t0_engine` 만 accept. 이 이유로 다섯 시나리오 `xfail`. |

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

### 3.7 T1 / T2 tier 를 `ControlLoop` 로 wire

**Problem.** `core/tiers/t1_lightweight/` 와 `core/tiers/t2_frontier/`
는 테스트와 함께 library-complete 이지만 `ControlLoop.__init__` 은
`t0_engine` 만 accept. 이 이유로
[tests/scenarios/test_v2026_07_replay.py](../../tests/scenarios/test_v2026_07_replay.py)
의 다섯 시나리오가 `xfail`.

**Design.**

- `ControlLoop.__init__` 을 optional `t1_engine` 과 `t2_engine`
  parameter 로 확장 (Protocol-typed, `core/control_loop.py` 에서
  Protocol 을 넘는 concrete class import 없음).
- Flow: `T0.abstain → T1.reuse (if wired) → T2.propose + quality-gate
  (if wired) → risk-gate`. 각 tier hop 은 audit entry 를 write 하여
  decision 이 reconstructable.
- Fixture stack 이 fake-adapter reachable 한 네 시나리오를 un-xfail
  (`dr.chaos-experiment-novel.003` 은 xfail 유지 - real Chaos Studio
  dry-run 이 필요하고 P3 backlog 로 유지).
- Trust-router 의 public contract 에 변경 없음; 기존 테스트는 unchanged
  regress.

## 4. Rollout 순서 및 safety mode

위 모든 subsystem 은 **shadow mode** 로 먼저 ship
([architecture.instructions.md § Safety Invariants](../../.github/instructions/architecture.instructions.md#safety-invariants)).
Enforce 로의 promotion 은 module 의 `promotion_gate` 가 선언하는
shadow accuracy 로 gated 된 별도 change (rule / ActionType promotion
계약을 mirror).

Rollout 순서는 strict prerequisite chain 을 pick:

1. **§ 3.1 Incident** 와 **§ 3.2 Telemetry** 는 독립적 - 둘 다 동일
   phase 에서 ship, 순서 무관.
2. **§ 3.7 T1/T2 wiring** 은 신규 depend 없음 - 편리하면 먼저 ship 가능.
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
- Coverage claim 아님. § 2 의 deferred axis 도 land 할 때까지 FDAI
  는 "full SRE agent" 라 자칭하지 않음.
