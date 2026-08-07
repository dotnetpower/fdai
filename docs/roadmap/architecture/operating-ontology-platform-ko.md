---
title: FDAI 온톨로지 안전 인프라
translation_of: operating-ontology-platform.md
translation_source_sha: 0985b711a640cc5aac026550ffa7021ed83b442b
translation_revised: 2026-08-07
---
# FDAI 온톨로지 안전 인프라

이 문서는 운영 온톨로지를 FDAI 에이전트를 위한 typed infrastructure layer로 확장합니다. Object
polymorphism, bounded object set, semantic action effect, typed function, authority-aware writeback,
exact schema pinning, generated SDK surface를 추가합니다. 모든 runtime transition은 여전히
에이전트가 소유하며 이 primitive는 input, plan, effect verification을 제한합니다.

> **권한 경계:** 관측된 provider state는 projection으로 유지됩니다. Action은 provider, Git,
> ledger 또는 FDAI-owned state change를 요청할 수 있지만 ontology graph를 편집하여 외부 사실을
> 참으로 만들 수 없습니다.
>
> **안전 경계:** Function은 plan, query, derive 또는 validate만 수행합니다. Thor만 승인된
> `MutationPlan`을 실행하며 모든 외부 effect는 독립 reconciliation으로 종료합니다.
>
> **구현 상태(2026-08-01):** Canonical release, ActionBuilder output, in-memory ontology write에
> K0 contract identity를 구현했습니다. K1 semantic interface compilation과 bounded ObjectSet
> query도 구현했습니다. K2-K5 core primitive는 mutation plan, stale revision check, typed
> function, projection binding, reconciliation, scoped SDK generation, read-only manifest를
> 포함합니다. PostgreSQL object/link write는 exact type version과 release digest를 보존하며,
> production ActionBuilder composition은 전체 loaded release를 사용합니다. 기존 Reader-gated
> `GET /ontology/graph` projection은 release digest, proposal-only write surface,
> `mutation_authority: false`를 노출하며 mutation route를 추가하지 않습니다.
> Pre-migration row는 original release digest를 정직하게 복원할 수 없으므로 명시적으로 unpinned
> 상태를 유지합니다. 다음 successful write는 완전히 다시 검증한 current-state revision을 새로
> 만들고 그 새 revision을 해당 시점의 active release로 pin합니다.
> Canonical release는 이제 typed function declaration을 포함합니다. Function registry는 caller
> agent, role, purpose를 검사하고, 선언된 stochastic function을 위해 replay-stable seed를 파생하며,
> 정확한 release에 고정된 content-addressed invocation receipt를 emit합니다.
> K6-K8은 immutable operational state trajectory, dependency 범위 effect propagation,
> time-bounded invariant, 독립 관측 trajectory outcome을 포함하는 graph-wide Dynamic evidence를
> 목표로 합니다. 기존 action/metric Dynamic simulation은 구현되어 있으며 graph-wide propagation과
> failure-attribution wiring은 종료 기준을 통과할 때까지 delivery 작업으로 남습니다.
>
> **하드닝 상태(2026-08-01):** Release identity, persistence, interface compatibility, ObjectSet
> closure, mutation safety, function authority, projection, reconciliation, generated SDK syntax,
> manifest disclosure를 대상으로 10회 adversarial round를 수행했습니다. 검증된 Medium 이상 core
> finding을 수정했습니다. PostgreSQL 및 runtime integration finding도 수정했으며 residual finding은
> Low입니다. Round 12에서는 legacy read에 current release를 소급 할당하는 동작을 제거했습니다.
> Round 13에서는 successful update가 새로 검증한 current-state revision을 생성하고 pin하는 것을
> 확인했습니다.

## Catalog-owned instance projection

Core runtime startup은 이제 Rule, PolicyArtifact, ResourceType, SignalType, Property 및
ActionType instance를 하나의 catalog-owned subgraph에 projection합니다. Pure builder는 누락된
정책 semantics와 ID 충돌을 차단합니다. Projector는 이전의 범위가 제한된 subgraph를 읽고
원자적으로 교체하며, 동일한 replay는 no-op이므로 startup이 거짓 graph revision을 만들지 않습니다.

이 projection은 카탈로그 관계를 query 가능하게 만들지만 권위를 변경하지 않습니다. Git
catalog-as-code가 계속 권위 원천이고 instance graph는 read model로 유지됩니다. 선택적 local
profile에서 OPA 또는 ontology store를 사용할 수 없으면 synthetic 상태로 대체하지 않고 projection을
unavailable로 유지합니다. 배포 profile은 T0 평가를 위해 계속 OPA를 요구합니다.

## 한눈에 보는 설계

Infrastructure는 semantic declaration, authority-specific state, agent-owned kinetic execution을
분리합니다. Graph write, function result, generated SDK call 또는 `MutationPlan`은 accountable agent가
judgment, authorization, execution, independent effect verification을 완료할 때까지 proposal 또는
context로 유지됩니다.

```mermaid
flowchart LR
    S[Authority sources] --> PB[ProjectionBinding]
    PB --> G[Observed object graph]
    G --> Q[ObjectSet query]
    Q --> D[Decision context]
    D --> MP[MutationPlan]
    MP --> R[Risk and approval]
    R --> A[ActionRun]
    A --> X[Provider, Git, ledger, or FDAI store]
    X --> RC[ReconciliationReceipt]
    RC --> G
    RC --> O[ObservedOutcome]
```

## 정확한 type identity

모든 declaration은 하나의 immutable `OntologyRelease`에 속합니다. Runtime record는 자신을
해석한 정확한 declaration을 고정합니다.

```yaml
type_ref:
  name: Resource
  version: 2.1.0
  catalog_digest: sha256:<digest>
```

`Action`, `ActionRun`, ontology object, ontology link, audit record, generated plan은 exact reference를
보존합니다. Compatibility check는 `compatible`, `migration_required`, `incompatible` 중 하나를
반환합니다. 기존 record를 재해석하는 방식으로 release가 declaration을 in-place 교체할 수 없습니다.

Cross-service semantic record는 declaration set을 복사하지 않고 contract `schema_version`과 exact
release `digest`를 담는 compact envelope인 `OntologyReleaseRef`를 사용합니다. Legacy discovery와
explanation record는 migration 동안 이 envelope를 생략할 수 있습니다. Decision-critical
`evaluate` 및 `action_draft` consumer는 이를 요구하며, 제공된 값이 일치하지 않으면 semantic-index
또는 provider I/O 전에 차단됩니다.

## Proof를 포함한 semantic interpretation

Lexical matching, embedding 및 model은 `SemanticInterpretationCandidate`를 만들 수 있습니다.
Candidate는 target type, ontology release, semantic catalog, normalized argument, input, unresolved
term, source 및 content digest를 고정하지만 authority는 항상 `candidate_only`입니다.

모든 term이 resolve되고, target이 exact active release와 일치하고, operation class가 typed function
또는 ActionType과 일치하며, exact catalog record, promoted language surface 또는 operator-confirmation
turn을 인용할 때만 candidate가 `VerifiedSemanticPlan`이 됩니다. Verified plan도
`execution_authority: false`를 유지합니다. Query, derive 및 validate plan은 typed function만 target할
수 있습니다. Action interpretation은 ActionType에 바인딩된 draft만 만들 수 있으며, 일반 judgment,
approval, execution, recovery 및 audit 경로로 다시 진입합니다.

Candidate 및 plan argument는 mutable nested container 대신 canonical JSON으로 저장됩니다.
Verification은 plan을 만들기 전에 candidate integrity를 다시 계산합니다. Exact-catalog verification은
catalog digest를 직접 고정하고 composition이 제공한 active semantic catalog와 일치하는지 확인합니다.
Promoted surface와 operator confirmation은 immutable promotion 또는 conversation-turn reference를
확인하는 injected evidence validator가 필요합니다.

Operator API는 `inventory.select_resources`를 read-only ontology query function으로 선언합니다.
Production semantic candidate와 `/ontology/graph` manifest는 같은 release digest 및 function
reference를 사용합니다. 다른 release의 candidate는 provider I/O 전에 차단됩니다.

## Semantic interface와 object set

`OntologyInterfaceType`은 기존 `ActionInterface` safety flag와 구별됩니다. Semantic interface는
property, required link, supported action, inherited interface를 선언합니다. Object type은 여러
interface를 구현할 수 있습니다. 초기 kernel interface는 `Operable`, `Ownable`, `Observable`,
`ObjectiveBound`, `Recoverable`, `CostBearing`입니다.

`ObjectSetDefinition`은 concrete type 또는 semantic interface로 object를 선택합니다. Typed property
predicate, named-link traversal, deterministic ordering, `as_of` cutoff, freshness, purpose, hard
result limit를 지원합니다. Free-form Cypher, SPARQL, SQL 또는 model text를 받지 않습니다. 모든
materialization은 release digest, cutoff, source watermark, truncation reason, redaction summary를
기록합니다.

Property predicate는 `equals`, `not_equals`, `in`, `exists`, `absent`, `at_least`, `at_most`,
`contains`를 지원합니다. Single-value operator는 `equals`를 사용하고, `in`은 비어 있지 않은
`values` tuple을 사용하며, presence operator는 operand를 받지 않습니다. Store에는 index
pushdown을 위해 `equals` predicate만 전달합니다. Direct query와 traversal은 모두 bounded candidate
graph에 모든 predicate를 다시 적용하고, filter된 endpoint가 있는 link를 제거하며, candidate ceiling
또는 요청한 result limit에 도달하면 truncation receipt를 유지합니다.

## Semantic action과 mutation plan

`ActionType`은 기존 stop condition, rollback, impact scope, execution path, promotion gate, autonomy
ceiling을 유지합니다. Version 2는 다음 semantic field를 추가합니다.

- **Target:** Exact ObjectType 또는 InterfaceType reference와 one-or-set cardinality입니다.
- **Parameter:** Validation 및 redaction metadata가 있는 primitive, enum, struct, object-reference
  또는 object-set input입니다.
- **Read set:** Action plan 및 verification에 필요한 object set과 property입니다.
- **Submission criteria:** Deterministic criterion 또는 `validate` function reference입니다.
- **Planner:** Declarative effect rule 또는 하나의 signed `plan` function입니다.
- **Effect:** 예상 internal write, catalog pull request, provider command, notification 또는
  schedule입니다.
- **Postcondition:** Action outcome을 종료하는 independent observation입니다.
- **Transaction policy:** Internal atomicity 또는 external saga semantic, lock scope, maximum
  affected object count입니다.

Planning은 immutable `MutationPlan`을 만듭니다. Exact target revision, computed write set, command,
impact evidence, rollback 또는 compensation step, expected effect, digest를 포함합니다. Approval과
execution은 digest와 current revision을 다시 검증합니다. Stale plan은 planning 또는 사람 검토로
돌아가며 넓어진 scope로 실행되지 않습니다.

## Typed ontology function

`OntologyFunctionType`은 네 종류 중 하나입니다.

| 종류 | Output | Authority |
|------|--------|-----------|
| `query` | `ObjectSetDefinition` 또는 bounded data | Read only입니다. |
| `derive` | Typed scalar 또는 struct | Read only입니다. |
| `validate` | Evidence가 있는 typed criterion result | Eligibility를 낮출 수만 있습니다. |
| `plan` | Immutable `MutationPlan` | Proposal only입니다. |

Function은 exact input/output schema, read set, determinism class, artifact digest, publisher,
resource ceiling, network policy를 선언합니다. Executor identity를 받지 않으며 provider mutation을
직접 호출하지 않습니다.

Diagnostic runtime은 Kubernetes reducer 22개를 exact-release `derive` function으로 등록합니다.
Live provider는 `diagnostic-evaluation` purpose에서 Heimdall로 registry를 호출하고 각 invocation
receipt와 함께 canonical function argument를 보존합니다. Observer는 active release, caller,
invocation identity, input digest 및 output digest가 모두 일치할 때만 finding을 수락합니다. 이러한
receipt는 read-only provenance이며 diagnostic function을 action으로 바꾸지 않습니다.

## Authority-aware writeback과 projection

각 ObjectType은 하나의 authority class와 write policy를 선언합니다.

| Authority class | 예 | Write policy |
|-----------------|----|--------------|
| `catalog_owned` | Rule, ActionType, policy | Reviewed Git pull request입니다. |
| `fdai_owned` | Workflow draft, approval | Atomic state transaction과 outbox입니다. |
| `provider_observed` | Cloud resource, topology | Provider command 후 independent observation입니다. |
| `ledger_owned` | DecisionCase, ActionRun | Append only입니다. |
| `derived` | Forecast, pattern projection | Owning-agent projection입니다. |

`provider_observed` object에서는 성공한 API receipt가 state update가 아닙니다. Reconciliation은
intended effect를 fresh evidence와 비교하고 `matched`, `mismatched`, `timed_out`, `unscorable` 중
하나인 `ReconciliationReceipt`을 emit합니다. Authoritative projection만 observed state를 갱신합니다.

`ProjectionBinding`은 source-to-ontology mapping을 review 가능하게 만듭니다. Source identity, type
target, identity/property mapping, watermark behavior, freshness, deletion semantics, conflict policy,
batch limit를 선언합니다. Source는 다른 authority를 조용히 overwrite할 수 없습니다.

## Dynamic state와 graph effect

Platform은 서로 authority를 부여하면 안 되는 세 layer를 분리합니다.

| Layer | 질문 | Output authority |
|-------|------|------------------|
| **Semantic** | 무엇이 존재하고 어떤 의미이며 어떤 관계가 유효합니까? | Type, unit, identity, cardinality, compatibility만 제공합니다. |
| **Kinetic** | 어떤 등록 operation이 어떤 safety contract에서 exact target을 변경할 수 있습니까? | Proposal-only `MutationPlan`이며 judgment, approval, execution은 외부 경계에 남습니다. |
| **Dynamic** | Intervention 또는 external event에서 state가 시간에 따라 어떻게 변할 수 있고 prediction이 reality와 얼마나 일치했습니까? | Read-only prediction, invariant, propagation, fidelity evidence만 제공합니다. |

`OperationalStateTrajectory`는 기존 governed conversation 및 execution `TrajectoryEnvelope`와
구별됩니다. Ontology release, baseline graph revision, inventory generation, event-time cutoff,
horizon, affected object revision, predicted 또는 observed state slice, intervention reference,
source watermark, completeness, truncation 및 replay-stable digest를 고정합니다. Raw cloud payload를
저장하지 않고 normalized value와 opaque evidence reference만 저장합니다. Predicted trajectory는
provider truth를 주장할 수 없으며 observed trajectory에는 authoritative provider 또는 telemetry
receipt가 필요합니다.

`GraphEffectModel`은 현재 action-and-metric effect model을 대체하지 않고 확장합니다. Source object
또는 interface, ActionType 또는 external-event trigger, bounded LinkType path 하나, target object 또는
interface와 metric, propagation lag, response function, uncertainty, context condition, evidence grade,
learning cutoff, active 또는 challenger status를 선언합니다. Simulator는 deterministic topology
effect를 먼저 적용한 뒤 verified active model을 적용합니다. Challenger output은 divergence evidence로만
보고하며 branch 순위 또는 선택에 사용하지 않습니다.

`DynamicInvariant`는 SLO, RTO, RPO, capacity floor, cost envelope, data-integrity predicate 또는
affected-set ceiling처럼 complete trajectory 전체에서 유지되어야 하는 machine-evaluable bound를
기술합니다. Predicted violation은 arbitration 전에 branch를 제거합니다. 실행 중 observed violation은
forward dispatch를 중지하고 기존 typed recovery path에 다시 진입하며 simulator가 실행 중 plan을
변경하도록 허용하지 않습니다.

`TrajectoryOutcome`은 object, metric, time window별 predicted state slice와 independently observed
state slice를 비교합니다. Terminal status는 `matched`, `mismatched`, `intervention_censored`,
`incomplete`, `unscorable`입니다. Complete하고 post-cutoff이며 독립적으로 관측된 outcome만
challenger model을 update합니다. Active model은 별도의 reviewed promotion이 exact evidence receipt를
적용할 때까지 immutable 상태를 유지합니다.

Conversation 또는 internal-processing failure는 deterministic attribution 단계가 exact verification
reason, route, evidence manifest, ontology release, graph revision, freshness, completeness를 보존한
뒤에만 off-path adequacy review를 열 수 있습니다. Context, provider, routing, rendering, policy,
semantic, kinetic, Dynamic failure는 서로 구별됩니다. 재현된 semantic, projection, rule 또는 Dynamic
gap만 inert ontology 또는 model-review candidate를 생성합니다.

## Query, security, SDK surface

Security는 object, property, link, object set, action discovery, action submission, function invocation
경계에 적용됩니다. Visible link를 통해 숨겨진 endpoint가 노출되지 않습니다.

Ontology release는 scoped Python/TypeScript SDK와 OpenAPI metadata를 생성할 수 있습니다. Generator는
승인된 type과 capability만 포함합니다. Write method는 typed action proposal을 submit하며 executor를
호출하지 않습니다.

## 제공 순서

| Wave | Deliverable | 종료 기준 |
|------|-------------|-----------|
| K0 | Exact `OntologyTypeRef` 및 `OntologyRelease` pinning입니다. | Action, graph, audit, replay test가 exact version과 digest를 보존합니다. |
| K1 | Interface와 bounded object set입니다. | Concrete expansion, ACL, cutoff, truncation, query fixture가 통과합니다. |
| K2 | Semantic ActionType v2 및 `MutationPlan`입니다. | Plan digest, stale revision, impact, rollback, shadow no-mutation test가 통과합니다. |
| K3 | Typed function과 authority-aware reconciliation입니다. | Function이 mutate할 수 없고 모든 external effect가 typed closure에 도달합니다. |
| K4 | Projection binding과 schema migration입니다. | Snapshot/delta parity, watermark recovery, conflict, migration fixture가 통과합니다. |
| K5 | Generated SDK와 ontology application surface입니다. | Python/TypeScript compile test와 proposal-only write test가 통과합니다. |
| K6 | Operational state trajectory와 deterministic graph propagation입니다. | 동일 release, graph, cutoff, model, intervention은 하나의 digest를 만들며 stale, truncated, cyclic 또는 unmodeled path는 review를 요구합니다. |
| K7 | Dynamic invariant와 trajectory outcome closure입니다. | Invariant 위반 branch는 arbitration에 도달하지 않고 provider acceptance는 outcome을 종료할 수 없으며 incomplete observation은 unscorable로 유지됩니다. |
| K8 | Failure attribution과 governed Dynamic learning입니다. | Exact verification reason이 intake에서 보존되고 non-ontology failure는 ontology proposal을 만들지 않으며 challenger만 학습하고 review 없이 authority를 높이지 않습니다. |

새 field는 decoding에서 optional로 시작하지만 새로 만든 runtime record에는 필수입니다. Retained audit
및 instance fixture가 exact release에서 replay된 뒤에만 legacy decoding을 제거합니다.

## 검증 매트릭스

| 항목 | 필요한 증명 |
|------|-------------|
| Replay | Historical record가 같은 declaration과 plan digest를 resolve합니다. |
| Authority | Graph write가 permission을 부여하거나 external state를 주장할 수 없습니다. |
| Query safety | 모든 object set은 bounded, purpose checked, truncation 명시 상태입니다. |
| Action safety | Stop, rollback, impact, dry-run, lock, idempotency, audit가 필수로 유지됩니다. |
| Function safety | Query 및 planning code에 executor identity 또는 direct mutation path가 없습니다. |
| Reconciliation | Provider acceptance와 observed convergence가 별도 state로 유지됩니다. |
| Dynamic replay | 동일한 bounded input이 동일한 predicted trajectory와 invariant verdict를 만듭니다. |
| Dynamic authority | Prediction, model agreement 또는 model promotion evidence가 action을 승인하거나 실행할 수 없습니다. |
| Dynamic closure | Complete independent observation만 trajectory fidelity를 score하거나 challenger를 update합니다. |

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 기존 semantic 및 authority model | [FDAI 운영 온톨로지](operating-ontology-ko.md) |
| 기존 ActionType safety contract | [Action 온톨로지](../decisioning/action-ontology-ko.md) |
| Runtime execution authority | [실행 모델](../decisioning/execution-model-ko.md) |
| Repository 및 dependency boundary | [프로젝트 구조](project-structure-ko.md) |
