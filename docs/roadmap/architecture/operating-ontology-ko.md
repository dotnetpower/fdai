---
title: FDAI 운영 온톨로지
translation_of: operating-ontology.md
translation_source_sha: 11d3d7a150f45c8ae5d521cccc12a07cc6cbc8eb
translation_revised: 2026-08-01
---
# FDAI 운영 온톨로지

이 문서는 FDAI의 15개 에이전트가 공유하는 운영 의미를 정의합니다. FDAI는 클라우드 운영
도메인에 특화되지만 cloud-provider-neutral하고 customer-agnostic하게 유지됩니다. Upstream은
안정적인 운영 개념을 소유하고, 각 deployment는 service map, objective, budget, evidence,
resource instance를 제공합니다.

> **권한 경계:** 온톨로지 graph는 공유 semantic read model이며 mutable system of record 또는
> execution surface가 아닙니다. Event, 승인된 configuration, telemetry source, append-only audit
> ledger, catalog-as-code는 각자 소유한 사실의 authority로 유지됩니다.
>
> **안전 경계:** Ontology context는 autonomy를 유지하거나 낮출 수만 있습니다. 누락되거나
> 오래되거나 충돌하거나 입증되지 않은 context는 결정을 검토 대기로 보냅니다. 실행 권한을
> 제공하지 않습니다.
>
> **구현 상태(2026-08-01):** O1 semantic-spine declaration과 competency query, O2 immutable
> context materialization 및 Forseti ceiling wiring, O3/O4 공유 decision-case selection과 response
> closure, operational-learning O2의 Muninn/Norns fingerprint cohort intake를 구현했습니다.
> Mimir behavior와 catalog compilation은 변경하지 않았습니다. Bounded JSON
> `OperatingModelProvider`가 startup에서 deployment instance를 project할 수 있으며, Reader-gated
> ontology projection에서 revision과 aggregate count를 확인할 수 있습니다.

## 한눈에 보는 설계

운영 온톨로지는 현재 resource 중심 graph가 하나의 deterministic path로 답하지 못하는 네 가지
질문을 연결합니다. 무엇을 운영하는지, 좋은 상태가 무엇인지, 지금 무엇이 일어나거나 앞으로
일어날 수 있는지, intervention이 의도한 효과를 냈는지를 연결합니다. Reliability, architecture
review, predictive cost governance, operational learning이 같은 언어를 사용합니다.

```mermaid
flowchart LR
    BC[BusinessCapability] -->|delivered_by| BS[BusinessService]
    BS -->|implemented_by| W[Workload]
    W -->|runs_on| R[Resource]
    W -->|depends_on| W2[Workload]
    BS -->|governed_by| O[Operational objectives]
    S[Signal] -->|observes| R
    F[Forecast] -->|predicts_breach_of| O
    C[Change] -->|affects| W
    D[DecisionCase] -->|protects| O
    D -->|considers| AO[ActionOption]
    AO -->|expects| EE[ExpectedEffect]
    AO -->|executed_as| AR[ActionRun]
    AR -->|resulted_in| OO[ObservedOutcome]
    OO -->|learned_as| P[Pattern]
```

## 도메인 관점

FDAI는 domain-agnostic하지 않습니다. 안정적인 domain model을 가진 cloud operations control
plane입니다. 경계는 다음과 같습니다.

| 경계 | Upstream 관점 |
|------|---------------|
| Cloud operations 의미 | Deployment 간에 특화되고 안정적으로 유지합니다. |
| Cloud provider | Neutral contract를 유지하고 Azure를 구현 provider로 사용합니다. |
| Customer organization | Generic type과 link만 포함하고 customer instance나 value를 포함하지 않습니다. |
| Business semantics | 안정적인 개념은 upstream에 두고 deployment별 mapping과 value는 downstream에 둡니다. |
| Autonomy | Graph 외부의 policy, risk, approval, execution, audit contract가 통제합니다. |

이 구분은 두 가지 실패를 방지합니다. Provider-specific model은 모든 운영 개념을 Azure resource
property로 만듭니다. 완전히 domain-agnostic한 model은 service, reliability, cost, architecture
의미를 에이전트가 안정적으로 공유할 수 없는 untyped property bag으로 밀어냅니다.

## 의미 계층

### 운영 범위

다음 object는 무엇을 운영하고 왜 중요한지 설명합니다.

| ObjectType | 목적 |
|------------|------|
| `BusinessCapability` | 하나 이상의 service가 제공하는 generic business outcome입니다. |
| `BusinessService` | Ownership, criticality, objective, impact에 사용하는 안정적인 service identity입니다. |
| `Workload` | Service를 구현하는 deployable 또는 operable unit입니다. |
| `Resource` | 기존 ontology에서 유지하는 관측된 cloud resource입니다. |
| `Environment` | Production 또는 non-production과 같은 governed lifecycle scope입니다. |

초기 SRE deployment에서는 `BusinessCapability`를 선택적으로 사용할 수 있습니다.
`BusinessService`, `Workload`, resource mapping은 최소 operational spine을 구성합니다. Mapping되지
않은 resource는 `unknown_service`로 계속 표시하며 synthetic service에 자동 할당하지 않습니다.

### 운영 의도

다음 object는 FDAI가 보존해야 하는 조건을 정의합니다.

| ObjectType | 목적 |
|------------|------|
| `ServiceObjective` | SLI와 window가 있는 availability, latency, correctness, freshness target입니다. |
| `RecoveryObjective` | Service 또는 workload의 RTO 및 RPO target입니다. |
| `CostObjective` | Currency와 period가 있는 budget, run-rate, unit-cost, variance target입니다. |
| `ArchitectureConstraint` | ARB와 change assurance가 사용하는 reviewed architecture condition입니다. |
| `Ownership` | 책임 운영 owner와 escalation reference입니다. |

Objective는 free-form metric label이 아닙니다. Kind, unit, target 또는 range, measurement source,
scope, owner, effective interval, evidence freshness policy를 기록합니다.

### 운영 현실

기존 `Signal`, `Finding`, `Incident` object를 유지합니다. 공유 model은 finding의 열린 `context`
bag에만 정보를 두는 대신 명시적인 time 및 prediction 개념을 추가합니다.

| ObjectType | 목적 |
|------------|------|
| `Observation` | Event-time cutoff의 정규화된 측정 value와 evidence reference입니다. |
| `Change` | Affected scope와 provenance가 있는 proposed, in-progress, completed change입니다. |
| `Forecast` | Horizon, interval, confidence, feature cutoff가 있는 versioned projection입니다. |
| `Experiment` | 관측 episode에 intervention을 줄 수 있는 범위 제한 chaos 또는 validation activity입니다. |

### 결정과 학습

다음 object는 model prose를 authority로 취급하지 않고 전체 intervention trace를 query할 수 있게
합니다.

| ObjectType | 목적 |
|------------|------|
| `DecisionCase` | Objective, constraint, evidence, no-action baseline이 있는 immutable decision context입니다. |
| `ActionOption` | Hold 또는 no-op option을 포함하는 하나의 검토 response입니다. |
| `ExpectedEffect` | Predicted metric range, observation window, uncertainty, predictor version입니다. |
| `ActionRun` | 기존 execution identity와 terminal receipt입니다. |
| `ObservedOutcome` | 관측된 effect, rollback, SLO recovery, recurrence, scoring status입니다. |
| `Pattern` | Balanced case cohort가 뒷받침하는 reviewed generic mechanism입니다. |

`DecisionCase`는 RiskGate decision 또는 audit record를 대체하지 않습니다. Forseti, Odin, Var,
Saga, replay consumer가 같은 사실을 참조하게 하는 immutable semantic input입니다.

## 관계 계약

초기 relationship set은 작고 query-driven하게 유지하는 것이 좋습니다.

| LinkType | Endpoint | 의미 |
|----------|----------|------|
| `delivered_by` | BusinessCapability -> BusinessService | Capability를 제공하는 service입니다. |
| `implemented_by` | BusinessService -> Workload | Service를 구현하는 workload입니다. |
| `runs_on` | Workload -> Resource | Resource ownership을 바꾸지 않는 runtime placement입니다. |
| `depends_on` | Workload/Resource -> Workload/Resource | 올바른 운영에 필요한 dependency입니다. |
| `governed_by` | Service/Workload -> Objective/Constraint | Target에 적용하는 intent입니다. |
| `owned_by` | Service/Workload/Objective -> Ownership | 책임 운영 owner입니다. |
| `observes` | Observation/Signal -> Service/Workload/Resource | 측정 evidence의 target입니다. |
| `affects` | Change/Incident/Experiment -> Service/Workload/Resource | Episode가 영향을 주는 scope입니다. |
| `predicts_breach_of` | Forecast -> Objective | 선언된 horizon 안에서 위험한 objective입니다. |
| `considers` | DecisionCase -> ActionOption | 함께 평가한 bounded alternative입니다. |
| `protects` | DecisionCase/ActionOption -> Objective | Decision이 보존하려는 objective입니다. |
| `expects` | ActionOption -> ExpectedEffect | 실행 전 predicted effect입니다. |
| `executed_as` | ActionOption -> ActionRun | 선택된 option의 governed execution입니다. |
| `resulted_in` | ActionRun -> ObservedOutcome | Independent effect closure입니다. |
| `learned_as` | ObservedOutcome -> Pattern | Reviewed learning projection이며 direct promotion이 아닙니다. |

Cardinality, causal direction, temporal ordering, allowed endpoint combination은 각 LinkType
declaration에 둡니다. 필수 competency question을 지원하지 못하는 relation은 visualization만을
위해 추가하지 않는 것이 좋습니다.

현재 LinkType schema는 declaration마다 source 및 target type을 하나씩 사용합니다. 따라서 union
관계는 `workload_runs_on`, `workload_depends_on`, `service_has_service_objective`,
`service_has_recovery_objective`, `service_has_cost_objective`,
`service_has_architecture_constraint`, `service_owned_by`, `workload_owned_by`,
`objective_owned_by`와 같은 명시적인 물리 이름으로 compile합니다. Endpoint validation은
deterministic하게 유지됩니다.

## Identity와 시간

운영 의미는 시간에 따라 변합니다. Decision-critical object는 사실이 유효하거나 관측된 시간과
FDAI가 기록한 시간을 모두 포함합니다.

- **Stable identity:** Service 및 workload id는 resource replacement와 deployment를 지나도 유지됩니다.
- **Effective time:** Objective, ownership, budget, constraint는 `effective_from`과 선택적인
  `effective_to`를 포함합니다.
- **Event time:** Observation, change, forecast, incident, outcome은 source time과 evidence cutoff를 포함합니다.
- **Recorded time:** 모든 projection은 FDAI가 수락한 시간과 source revision을 기록합니다.
- **Append-only revision:** 늦게 도착한 사실은 새 revision 또는 link interval을 만듭니다. 과거
  decision이 사용한 context를 다시 쓰지 않습니다.
- **Freshness:** 모든 decision context는 source별 freshness를 기록합니다. 하나의 fresh source가
  오래된 objective, topology edge, cost observation을 숨길 수 없습니다.

Replay는 원래 decision cutoff와 catalog version 시점의 graph를 resolve합니다. Current-state
query는 freshness check를 통과한 최신 valid revision을 사용합니다.

## 사실의 권위 원천

Ontology는 독립적인 authority를 하나의 mutable graph로 합치지 않습니다.

실행 권한 부여는 capability, requirement, policy assignment, execution profile, provider
mapping, observation, grant 및 decision object를 semantic graph에 추가합니다. 이러한 object는
decision을 설명하고 replay할 수 있게 하지만 graph 자체는 접근 권한을 부여하지 않습니다. Scoped
policy, deployment identity binding, provider evidence 및 risk gate는 독립 authority로 유지됩니다.
[실행 권한 부여 온톨로지](../decisioning/execution-authorization-ontology-ko.md)를 참조하세요.

| 사실 | Authority | Ontology 역할 |
|------|-----------|---------------|
| Type, link, action, rule definition | Git catalog-as-code | Versioned schema와 meaning입니다. |
| Service 및 workload mapping | Deployment service catalog 또는 approved manifest | Provenance가 있는 runtime projection입니다. |
| Resource topology | Injected `Inventory` provider | Fresh resource 및 dependency projection입니다. |
| Objective, budget, constraint, ownership | Approved system과 fork configuration | Effective-time intent projection입니다. |
| Telemetry 및 cost observation | Configured evidence provider | Source ref가 있는 event-time observation입니다. |
| Decision, approval, action, rollback | Append-only audit와 Process journal | Immutable semantic link입니다. |
| Case 및 pattern | Case history와 reviewed catalog | Learning projection과 governed reuse입니다. |

각 ObjectType은 하나의 owning agent, 하나의 authority class, freshness policy, retention, allowed
purpose를 선언합니다. 충돌하는 source는 명시적인 conflict 또는 `unknown` state를 만들고 autonomy를
낮춥니다.

## 에이전트 소유권

Ontology는 중앙 coordinator를 추가하지 않고 고정된 pantheon을 더 유능하게 만듭니다.

| Agent | 소유 semantic write |
|-------|---------------------|
| Huginn | Normalized observation과 discovered topology change event입니다. |
| Heimdall | Finding, forecast, independent effect observation입니다. |
| Njord | Cost observation, cost forecast, cost objective status입니다. |
| Freyr | Demand, capacity forecast, sizing option입니다. |
| Loki | Experiment와 resilience evidence입니다. |
| Forseti | Decision case와 governed decision입니다. |
| Odin | Cross-objective arbitration decision과 score breakdown입니다. |
| Var | Independent approval record입니다. |
| Thor | Action run과 attempt입니다. |
| Vidar | Rollback 및 recovery outcome입니다. |
| Saga | Audit evidence와 immutable correlation link입니다. |
| Muninn | Time-consistent context snapshot과 case revision입니다. |
| Norns | Pattern과 inert candidate입니다. |
| Mimir | Reviewed ontology, rule, action catalog lifecycle입니다. |
| Bragi | Decision write가 없으며 cited projection을 localized explanation으로만 표현합니다. |

에이전트는 typed event로 협업합니다. 다른 에이전트의 object를 mutate하거나 직접 호출하거나 mutable
workflow state를 공유하지 않습니다.

## 운영 context와 결정

Muninn은 각 decision cutoff에 immutable `OperationalContextSnapshot`을 materialize합니다. 새로운
authority가 아니라 projection contract입니다. 최소한 다음을 포함합니다.

- Target service, workload, resource, environment, dependency neighborhood;
- active service, recovery, cost, architecture objective;
- ownership 및 escalation reference;
- active change, experiment, incident, maintenance window;
- current observation과 bounded forecast;
- source freshness, provenance, unresolved conflict, catalog version.

Snapshot은 데이터 표면을 넓히지 않으면서 replay lineage를 보존합니다. 도달 가능한 각 context
object에 대해 object id, type, revision, effective interval, allowlist에 포함된 provenance ref,
target resource에서 시작하는 하나의 결정론적 최단 typed path를 기록합니다. 각 source의
observation time과 허용된 maximum age도 유지합니다. Snapshot identity는 이러한 revision, path,
effective interval, provenance ref, freshness receipt, stale-source 결과, conflict를 포함하므로
topology, revision, validity, provenance 또는 freshness가 바뀌면 이전 identity를 재사용할 수
없습니다. Raw object property는 권위 있는 provider에 남으며 snapshot에 복사하지 않습니다.

Materialization은 `effective_from <= cutoff`이고 `effective_to`가 없거나
`cutoff < effective_to`인 object만 포함합니다. 이 half-open interval 밖의 object는 replay를 위한
typed temporal exclusion으로 보존하지만 현재 decision fact로 사용하지 않습니다.
`context_temporal_exclusion`은 autonomy ceiling을 `SHADOW_ONLY`로 낮추므로 만료되거나 미래의
mapping이 자동 실행 권한을 유지할 수 없습니다. Provenance allowlist는 `source_ref`,
`measurement_source_ref`, `expression_ref`로 제한합니다.

범위가 제한된 traversal이 node limit에 도달하면 근거가 불완전한 상태입니다. Materialization은
`context_graph_truncated`를 conflict로 기록하고 autonomy ceiling을 `SHADOW_ONLY`로 낮춥니다. 일부
graph만으로 자동 실행 권한을 유지하지 않습니다.

Forseti는 snapshot에서 `DecisionCase`를 만듭니다. 각 case는 no-action baseline, bounded option,
expected effect, protected objective, violated constraint, uncertainty, evidence reference를 포함합니다.
Odin은 eligible option이 objective 사이에서 충돌할 때만 중재합니다. 사람 승인이 필요하면 Var가 같은
case를 받고, Saga는 replay를 위해 digest를 기록합니다.

Production startup은 provider boundary를 통해 `FDAI_OPERATING_MODEL_PATH`를 읽고, 전체 object/link
snapshot을 검증한 뒤 provider-owned subgraph를 atomically replace합니다. `applying` manifest는 stale
deletion과 crash recovery를 위해 이전 및 현재 owned identity의 union을 보존합니다. Replacement가
성공하면 `projected` manifest는 current ownership으로 compact되므로 historical revision이 configured
model bound를 초과하지 않습니다. Startup은 다른 snapshot을 stage하기 전에 중단된 `applying` union을
정리하므로 반복 crash가 revision 사이의 ownership을 누적하지 않습니다. 선택적
`FDAI_OPERATING_MODEL_MAX_BYTES` ceiling의 기본값은 16 MiB입니다. `GET /ontology/graph`는 projection
status, source revision, aggregate count만 노출하며 deployment instance property는 반환하지 않습니다.

Cost 및 capacity specialist의 event-time은 advice와 함께 전달됩니다. Forseti는 하나의
time-consistent snapshot을 materialize하고 공유 case를 만들어 arbitration request에 포함합니다.
Odin이 resolve한 선택은 Forseti verdict로 돌아오고, Thor의 durable `ActionRun`과 Var의 HIL ticket은
bounded baseline, option effect, constraint, evidence를 보존합니다. Thor는 verdict action이 selected
option과 정확히 일치하는지 확인합니다. Case evidence가 없거나 malformed 또는 mismatched이면 승인이나
실행 authority를 만들지 않고 deny합니다.

## 지속 운영 루프

"살아있는 에이전트"는 effect를 닫는 event-driven 및 time-driven control loop를 의미합니다. LLM이
계속 실행되거나 암묵적 authority를 얻는다는 뜻이 아닙니다.

### Reliability loop

`Observation -> Finding/Forecast -> DecisionCase -> ActionRun -> ObservedOutcome -> objective`

이 loop는 개별 resource utilization이 아니라 service objective와 error-budget risk를 우선합니다.

### Architecture review loop

`Change -> graph diff -> ArchitectureConstraint/Objective evaluation -> DecisionCase -> approval`

Assurance Twin은 proposed graph를 read-only branch로 simulation합니다. Review는 change를 approve,
condition, reject, hold할 수 있지만 `ActionType`을 활성화하거나 execution check를 우회할 수 없습니다.

### Predictive cost loop

`Cost observation -> CostObjective/Forecast -> options -> reliability guard -> outcome settlement`

Cost optimization은 선택한 option이 service 및 recovery objective를 보존할 때만 유효합니다. Estimated
savings는 observed outcome이 settlement window를 닫기 전까지 prediction으로 유지됩니다.

### Outcome learning 루프

Huginn은 bounded `case_history.operational_case.v1` event를 정규화합니다. Muninn은 O1
case-history materializer를 요구하고 strict input을 seal한 뒤 failure fingerprint별 immutable case를
최대 100개 durable하게 보존하여 `operational_case_fingerprint_cohort` context를 publish합니다.
Norns는 하나의 failure fingerprint와 ActionType, 최소 하나의 verified reusable success, 최소 하나의
failure, refusal, no-op, rollback 또는 recurrence control을 요구한 뒤 기존 consensus 및 rate limit
경로로 inert candidate를 emit합니다. 모든 candidate는 case id, revision, manifest digest, resource
type, fingerprint, outcome별 count, digest evidence를 인용합니다. Raw
`measurement.action_outcome.v1`은 mechanism evidence가 부족한 telemetry로 유지되며 promotable
cohort에 들어갈 수 없습니다.

## 확장 모델

Ontology는 통제된 네 계층으로 성장합니다.

1. **Operating kernel:** 모든 deployment가 공유하는 upstream ObjectType 및 LinkType입니다.
2. **Vertical pack:** Upstream reliability, architecture review, cost-governance profile입니다.
3. **Fork extension:** Kernel을 따르는 reviewed industry 또는 organization-specific type, link,
   objective, adapter입니다.
4. **Deployment instance:** Upstream source control 외부에 유지하는 customer service mapping,
   objective, budget, owner, resource, evidence입니다.

Extension은 meaning을 추가할 수 있지만 kernel identity를 다시 정의하거나 cardinality를 약화하거나
owning agent를 교체하거나 autonomy를 높일 수 없습니다. Unknown observed type은 self-register하지 않고
governed proposal을 엽니다. Breaking schema change는 semantic versioning, migration fixture,
deprecation window, replay test를 사용합니다.

## 역량 질문

Ontology 품질은 object 수가 아니라 deterministic question으로 측정합니다. Version 1은 evidence와
명시적인 unknown을 사용하여 다음 질문에 답하는 것이 좋습니다.

1. 이 resource change가 어떤 business service와 objective에 영향을 줄 수 있습니까?
2. 설정된 horizon 안에 어떤 service가 objective를 위반할 수 있으며 그 이유는 무엇입니까?
3. 어떤 active change 또는 experiment가 현재 service degradation을 설명할 수 있습니까?
4. Cost envelope 안에서 reliability 및 recovery objective를 보존하는 response option은 무엇입니까?
5. FDAI가 아무 action도 취하지 않으면 어떻게 됩니까?
6. Odin이 한 objective를 선호한 이유와 alternative와의 차이는 얼마입니까?
7. 선택한 action이 guard metric regression 없이 expected effect를 냈습니까?
8. 현재 topology, objective, policy version에서 이전 case를 계속 재사용할 수 있습니까?

각 질문은 positive, negative, stale, conflicting, unknown case를 가진 versioned query fixture가 됩니다.
새 type 또는 link는 실패하는 fixture로 필요성을 입증한 후 regression으로 유지합니다.

## 제공 계획

| Wave | Deliverable | 종료 기준 |
|------|-------------|-----------|
| O0 - Constitution | 이 authority, competency fixture, identity/time rule, ownership matrix입니다. | Schema work 전에 term, authority, unknown handling, extension boundary 검토가 합의됩니다. |
| O1 - Semantic spine | 구현됨: catalog declaration과 deterministic query fixture입니다. | Catalog-owned runtime writer 없이 loader, provenance, cardinality, versioning, query test가 통과합니다. |
| O2 - Context projection | 구현됨: immutable `OperationalContextSnapshot`, materializer, runtime store 공유, Forseti ceiling입니다. | Fresh context는 authority를 유지하고 stale, conflicting, unmapped context는 auto를 사람 승인으로 낮춥니다. |
| O3 - Reliability loop | Core 구현됨: objective-aware decision case, option selection, `ResponseOutcome` closure입니다. | Frozen test가 service -> objective -> option -> action -> effect를 하나의 correlation으로 통과합니다. |
| O4 - ARB 및 cost loop | Core 구현됨: architecture-constraint exclusion과 protected-objective cost tradeoff입니다. | Cost option이 protected reliability objective를 희생할 수 없습니다. |
| O5 - Governed learning | Operational-learning O2까지 구현됨: strict Huginn case event, Muninn fingerprint cohort, balanced inert Norns candidate입니다. Mimir catalog behavior는 변경하지 않았습니다. | Success-only 및 raw-response cohort를 보류하고 candidate가 immutable revision을 인용하며 outcome은 live catalog declaration을 직접 수정하지 않습니다. |

O0 이후 첫 code slice는 semantic-spine declaration, link constraint, query fixture만 추가하는 것이
좋습니다. Runtime writer, decision 변경, execution behavior는 이후 별도로 검증하는 slice에 둡니다.

## 검증 매트릭스

| 항목 | 필요한 증명 |
|------|-------------|
| 의미 | Decision-critical field가 typed되거나 typed objective를 참조하며 open bag이 authority가 아닙니다. |
| Provenance | 모든 instance가 source, revision, effective/event time, recorded time, freshness를 명시합니다. |
| Unknown safety | 누락 mapping, stale topology, conflicting objective가 autonomy를 낮추고 계속 표시됩니다. |
| Ownership | 각 object에 하나의 owning agent가 있고 cross-agent collaboration이 typed event를 사용합니다. |
| Replay | Historical decision이 같은 snapshot, version, option, score breakdown을 resolve합니다. |
| Effect closure | 실행된 option이 scored 또는 명시적으로 unscorable한 outcome에 도달합니다. |
| Extension safety | Fork addition이 kernel semantics를 다시 정의하거나 execution authority를 높일 수 없습니다. |
| Customer isolation | Upstream fixture는 synthetic value를 사용하고 deployment instance를 포함하지 않습니다. |

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 현재 resource, rule, signal, finding foundation | [LLM strategy](llm-strategy-ko.md#ontology-foundation) |
| Runtime ontology storage | [Rule lookup ontology storage](rule-lookup-ontology-storage-ko.md) |
| Action safety contract | [Action ontology](../decisioning/action-ontology-ko.md) |
| Agent role 및 arbitration | [Agent pantheon](../agents/agent-pantheon-ko.md) |
| Forecast 및 response outcome closure | [Observability and detection](../rules-and-detection/observability-and-detection-ko.md) |
| Operational case reuse | [Operational learning ontology](../rules-and-detection/operational-learning-ontology-ko.md) |
| Read-only graph simulation | [Assurance Twin](../operations/assurance-twin-ko.md) |
