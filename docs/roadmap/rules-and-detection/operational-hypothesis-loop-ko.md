---
translation_of: operational-hypothesis-loop.md
translation_source_sha: dcbc0a47733237770ded247c89e4d1ac56f51151
translation_revised: 2026-08-31
---
# 운영 가설 루프

운영 가설 루프는 FDAI가 운영 개입 전에 예상한 내용, 이후 독립적으로 발생한 결과, 그리고 그
비교에서 학습할 수 있는 통제된 logic을 기록합니다. 이 문서는 두 번째 계획, 인과, simulation 또는
승격 시스템을 추가하지 않고 통합된 graph evidence, reconciliation, lineage 및 model-promotion
runtime을 기록합니다.

> **권한 경계:** Ontology 선언, simulation, logic asset, model 및 가설 근거는 권한을 유지하거나
> 낮출 수 있습니다. 액션을 승인, 실행 또는 승격할 수 없습니다.
>
> **Object 경계:** 첫 구현은 `DecisionCase`, `ActionOption`, `ExpectedEffect`, `Process`,
> `CausalHypothesis`, `ActionRun` 및 `ObservedOutcome`을 재사용합니다. 동결된 competency test가
> 이러한 object와 link로 필수 query에 답할 수 없어서 실패한 뒤에만 `HypothesisCampaign`
> ObjectType을 추가할 수 있습니다.
>
> **J1 상태:** Lane A-D 산출물은 `main`에 통합되어 있습니다. J1은 composition, runtime
> lifecycle, 기존 delivery routing 및 bilingual code-map 업데이트만 소유합니다. 새 service,
> agent 또는 권한을 보유한 coordinator를 추가하지 않습니다.
>
> **Hardening 상태(2026-08-12):** 독립 비평 14라운드에서 권한, 범위, dry-run identity,
> idempotency, lease, ARM update 의미, 비동기 polling, input canonicalization, 오류 노출, 계약
> 일치 및 독립 outcome 경계를 검토했습니다. 수용된 finding에 따라 실행 시점 VM Scale Set 재관측,
> ETag 기반 `If-Match`, 명시적 412 conflict 처리, 정확한 reason 검증, 누적 polling deadline 및 VMSS
> 장기 실행 작업 replay test를 추가했습니다. 최종 검토에서 재현 가능한 Medium 이상 defect는
> 없었습니다. observer identity record와 timeout 분류에 대한 남은 Low 작업은 종료되었으며, 보호된 live
> drill과 recurrence window는 코드 defect나 완료 claim이 아니라 명시적 release evidence로 남습니다.
>
> **서명 맥락 하드닝(2026-08-30):** 추가 16개 라운드에서 키 구문 분석, 서명 정규 형식, 발급 시각과
> 재생 의미, 자격 증명 분리, 시작 실패, 지원하지 않는 대상, 압축 이벤트 대체, secret 노출,
> Terraform 소유권, 보호된 입력 채움, 구성 순서, 의존성 잠금 및 문서의 사실성을 검토했습니다.
> 라운드에서 High 산출물 해석기 Protocol 불일치 1건과 Medium 경계 결함 7건을 수정했습니다. 집중
> 회귀, 엄격한 타입, Terraform 및 문서 검사가 통과합니다. 의도적인 향후 서명 키 순환을 위한 Low
> 후속 작업과 별도의 보호된 실제 증적 campaign만 남아 있습니다.

## 설계 요약

FDAI는 no-action baseline과 범위가 제한된 `ActionOption` 값을 포함하는 변경할 수 없는
`DecisionCase`로 사전 가설을 표현합니다. 각 option은 `ExpectedEffect`를 인용하고, 통제된
`Process`가 여러 단계의 작업을 기록합니다. 관측 구간이 닫힌 후 독립 근거가 기존
`CausalHypothesis`를 개정할 수 있으며, provider acceptance는 dispatch 근거로만 남습니다.

![설계 요약. 주요 단계는 DecisionCase, No-action baseline, ActionOption, ExpectedEffect and horizon, Process and ActionRun, Provider receipt, Independent observation, CausalHypothesis revision, Active/challenger comparison, Inert promotion evidence, Mimir review and promotion registry입니다.](../../diagrams/generated/fdai-roadmap-rules-and-detection-operational-hypothesis-loop-01.ko.svg)

## 재사용 계약

이 루프는 기존 object의 join이며 새로운 권한 보유 aggregate가 아닙니다.

| 단계 | 기존 계약 | 필수 내용 |
|------|-----------|-----------|
| 사전 액션 case | `DecisionCase` | 근거 cutoff, 보호 objective, constraint, 범위가 제한된 option 및 필수 no-action baseline입니다. |
| 처리 option | `ActionOption` | 기존 `ActionType` 또는 명시적 hold/no-op, assumption, logic 및 simulation receipt, 제외 이유입니다. |
| 예상 효과 | `ExpectedEffect` | metric과 unit, 예측 interval과 direction, 관측 구간, uncertainty, predictor version 및 금지 효과입니다. |
| 여러 단계 journal | `Process` | 고정된 Workflow와 ActionType version, target revision, 현재 단계 및 correlation identity입니다. |
| Dispatch | `ActionRun` 및 provider receipt | Provider에 요청하고 수락 또는 거절된 내용입니다. 효과 종결이 아닙니다. |
| 독립 효과 | `ObservedOutcome` | 관측 구간 이후 authoritative observation, completeness, censoring, recurrence, rollback 및 objective 변화입니다. |
| 사후 액션 주장 | `CausalHypothesis` | Support 및 refutation reference, evidence grade, ambiguity, revision cutoff 및 closure 결과입니다. |

모든 case에는 처리 option과 동일한 구간에서 평가한 no-action option이 포함됩니다. 이것이 없으면
FDAI는 개선을 자연 회복이나 배경 변화와 구분할 수 없습니다. 모든 인과 revision에는 하나 이상의
refutation query 또는 명시적 unavailable 결과도 포함됩니다. 누락된 refutation 근거는 support가
아니라 `unknown`입니다.

## 관측 및 종결

관측 구간은 실행 전에 고정합니다. 예상 시작, 종료, telemetry grace, 적용 가능한 recurrence window
및 정확한 completeness policy를 포함합니다. 이후 액션, topology revision, policy 변경 또는 중요한
외부 이벤트는 episode를 intervened 또는 censored로 표시하며, 예측 결과를 조용히 승계하지 않습니다.
관측 envelope는 이러한 censoring 참조를 담고, censored episode는 마감 분류와 모든 효과 비교보다
먼저 unscorable로 처리합니다. 그래서 늦은 평가가 개입된 근거를 시간 초과 복구 요청으로 바꿀 수
없습니다. 결정론적 순서는 독립 관측 유효성, censoring, 의미 효과 커버리지, incomplete, synthetic,
conflicting, stale입니다.

종결된 모든 에피소드는 관찰자 신원 기록 하나를 보존합니다. 이 기록은 인증된 관찰자, 실행자, 근거
소스, 검증자를 상관관계 안전 핸들과 파생된 역할 분리 판정으로 투영하므로, 원본 주체를 다시 읽지
않고도 재생에서 독립성과 완전한 귀속을 증명할 수 있습니다. 이 기록은 근거일 뿐이며 관측 권한을
부여하지 않습니다.

시간이 초과된 에피소드는 여전히 복구로 라우팅되며, 그 reason code는 왜 늦게 종결되었는지를
지목합니다: incomplete, synthetic, conflicting, stale 근거이거나, 그 밖에 완전하고 신선한 관측인데
평가가 마감을 넘긴 경우입니다. 이 분류는 검증된 envelope 필드만 사용하며 시간 초과를 채점된 결과로
바꾸지 않습니다.

Provider receipt와 독립 outcome은 분리합니다.

- **Provider receipt:** 실행 channel을 통한 제출, 수락, 거절 또는 command 완료를 증명합니다.
  Dispatch는 닫을 수 있지만 관리 objective의 변화를 증명할 수 없습니다.
- **독립 outcome:** Heimdall의 authoritative observation 경로에서 나오고, 고정된 target과 관측
  구간을 사용하며, completeness와 conflict를 보고하고, 예상 효과를 닫습니다.
- **인과 종결:** Forseti는 support 및 refutation 근거를 비교한 후에만 `CausalHypothesis`를
  개정합니다. `confirmed`, `refuted`, `inconclusive` 및 `unsafe`는 서로 구분합니다.

독립 outcome이 없거나 충돌하면 성공한 provider receipt도 `inconclusive`로 남습니다. Provider가
성공을 보고했더라도 예상 방향과 반대인 완전한 독립 observation은 refutation 근거입니다.

## Logic 및 승격 분리

Active logic은 현재 `DecisionCase`를 만들거나 채점하는 데 사용된 정확한 검토 완료 release입니다.
Challenger logic은 동일한 동결 input을 대상으로 shadow에서만 실행되며 실행 가능한 branch의 순위를
지정할 수 없습니다. 두 record 모두 logic artifact, ontology release, input 및 output schema, evidence
cutoff, model 또는 algorithm version 및 deterministic seed policy를 고정합니다.

비교 component는 divergence, error measure, support 및 refutation count, exclusion 및 rollback
reference를 포함하는 범위가 제한된 inert 근거를 만들 수 있습니다. Active key를 대체하거나 promotion
registry에 쓸 수 없습니다. Mimir는 계속 promotion 및 demotion governor이며, 일반적인 reviewed
registry만 activation을 수행할 수 있습니다. Challenger regression은 challenger를 철회할 근거이며
active release를 다시 쓰지 않습니다.

## Agent ownership

고정 pantheon은 현재 single-writer 권한을 유지합니다.

| Agent | 이 루프에서의 책임 |
|-------|--------------------|
| Forseti | 변경할 수 없는 decision과 사후 액션 causal claim을 소유합니다. 실행하거나 승격하지 않습니다. |
| Heimdall | 독립 observation, completeness, support 및 refutation 근거를 제공합니다. |
| Thor | 이미 eligible한 선택된 ActionType만 실행하고 execution receipt를 만듭니다. |
| Saga | Case, receipt, observation, causal revision 및 review reference를 append합니다. |
| Muninn | 판단 없이 범위가 제한된 case 및 graph projection을 materialize합니다. |
| Norns | 균형 잡힌 근거에서 inert challenger candidate를 제안할 수 있습니다. |
| Mimir | Active/challenger 근거를 검토하고 catalog 또는 logic promotion 및 demotion만 통제합니다. |
| Var | 결정된 액션 ceiling에서 필요할 때 독립적인 사람 승인을 기록합니다. |
| Vidar | Rollback 및 recovery 근거를 소유합니다. 성공한 rollback은 처리 성공이 아닙니다. |

협업에는 schema-validated typed event를 사용합니다. 어떤 worker도 direct agent call, shared mutable
workflow state, 새 executor 경로 또는 권한을 보유한 ontology function을 추가할 수 없습니다.

## 통합 runtime

통합 runtime은 기존 composition 및 lifecycle surface를 재사용합니다.

| Lane | 통합 책임 | Runtime 결과 |
|------|-----------|--------------|
| A - graph evidence | 고정된 operational context, 검증된 topology, inventory, 검토된 metric semantics, objective, constraint 및 ActionType 영향 제한에서 graph Dynamic 요청을 만듭니다. | 완전한 prerequisite 집합만 production provider를 연결합니다. 모두 없으면 명시적 unavailable이며 일부만 있으면 startup이 중단됩니다. |
| B - reconciliation | 독립 observation을 인증하고 exact local artifact를 복원하며 예상 효과와 관측 효과를 reconcile하고 proposal-only terminal outbox를 commit합니다. | Request subscriber와 outbox drainer는 supervised cancellation을 공유합니다. 한 drain은 최대 100개를 publish한 뒤 yield하고 stop signal을 기다립니다. |
| C - lineage | 기존 `DecisionCase -> ActionOption -> ExpectedEffect -> ActionRun -> ObservedOutcome` record와 link를 immutable object rewrite 없이 append합니다. | Projection은 evidence-only로 유지되며 agent 또는 authority를 추가하지 않습니다. |
| D - promotion | 검토된 graph-model evidence를 seal하고 immutable rollback target을 보존하며 active pointer만 atomic하게 변경합니다. | `governance.promote-effect-model`은 기존 risk, Owner 사람 승인, Thor direct-API, rollback 및 Saga audit 경로로 진입합니다. |

Graph Dynamic은 기본 build budget 5초와 hard ceiling 10초를 유지합니다. 독립 topology,
inventory 및 metric read는 동시에 실행합니다. Timeout, cancellation, partial evidence 또는
unscorable invariant는 authority를 높일 수 없습니다. Graph simulation은 T1 reuse가 safety
check에 들어가기 전 lower-only guard로 유지됩니다.

Effect reconciliation은 `ontology.effect-reconciliation.requests` 및
`ontology.effect-reconciliation.outcomes`를 compact typed mechanical transport topic으로
사용합니다. 새 Pantheon-owned object topic이 아닙니다. Outbox payload는 항상
`proposal_only: true`와 `grants_authority: false`를 유지하며, recovery 또는 promotion 요청은
기존 typed pipeline에 다시 진입합니다. Event handling은 lane의 기본 5초를 유지하고 broker
publication은 2초 deadline을 유지하며, shutdown은 무기한 기다리지 않고 child cancellation을
5초로 제한합니다.

일반 실행은 실행된 Action이 ActionType, operation, target 및 argument digest가 여전히 일치하는
정확한 semantic V2 plan을 이미 참조할 때만 reconciliation request를 생성합니다. Legacy Action에
V2 plan을 새로 만들어 붙이지 않습니다. Producer는 주입된 독립 source를 통해 observation을
가져오고 publication 전에 request를 lease로 보호되는 durable outbox에 commit하며, 사용할 수 없는
observation은 held evidence로 기록합니다. Broker failure 또는 알 수 없는 publication outcome은
request를 replay를 위한 pending 또는 held 상태로 남기며, executor가 이미 반환한 outcome을 변경하지
않습니다.

Learner, closure, projection 및 outbox 실패는 이미 반환된 execution result를 rewrite하지
않습니다. Unavailable, held, pending 또는 failed evidence로 계속 표시됩니다. Durable store,
exact receipt, artifact, active pointer, ontology release, property semantics, invariant evidence
또는 rollback target이 없거나 일치하지 않으면 promotion은 fail closed합니다.

## Agent 및 authority join

통합 lane은 고정 Pantheon 역할을 보존합니다.

- **Heimdall:** 독립적으로 인증된 observation evidence와 completeness를 제공합니다.
- **Forseti:** Effect judgment와 causal closure를 소유하며 실행하거나 승격하지 않습니다.
- **Saga:** Reconciliation attempt, terminal outcome, pointer transition 및 failure를 기록합니다.
- **Norns:** Inert challenger artifact를 저장하며 활성화할 수 없습니다.
- **Mimir:** 검토된 promotion receipt를 seal하며 registry mutation을 직접 호출하지 않습니다.
- **Thor, Var 및 Vidar:** 기존 ActionType 경로에서 execution, 사람 승인 및 rollback ownership을
  유지합니다.

Heimdall은 관찰자 역할로만 최종 `object.action-run` 이벤트를 구독합니다. 안정적인 correlation
index를 통해 pre-dispatch kinetic artifact 저장소에서 정확한 `Action`과 semantic V2 plan을
복원하며 ActionRun payload에서 어느 body도 다시 만들지 않습니다. 주입된 collector는 하나의
`ExecutedActionObservation`을 만들 수 있고 기존 mailbox는 Heimdall producer 경계에서 이를
검증하고 봉인합니다. Artifact 누락, legacy Action, shadow 실행, 지원하지 않는 ActionType, 사용할
수 없는 근거, signed-context issuer 누락은 관측을 만들지 않으며 권한을 부여하지 않습니다.

첫 concrete collector는 Azure VM Scale Set `ops.scale-out`으로 제한됩니다. Promoted inventory의
`AzureOperationalSnapshot`을 사용하고 정확한 대상 및 plan 이후 snapshot을 요구하며 불변 plan이
이미 선언한 expected-property 이름만 투영합니다. 모든 속성은 snapshot의 finite metric으로
존재해야 합니다. 배포가 제공하는 issuer는 독립 observer, executor, source, verifier credential
계보를 `AuthenticatedObservationContext`에 바인딩해야 하며 collector는 자체 주장을 verified로
표시할 수 없습니다.
배포된 Core 서비스는 Managed Identity 기반 Key Vault 참조를 통해서만 무작위 Ed25519 seed를
받습니다. 런타임 구성은 공개 키 계보를 파생하고 쓰기 및 재생 시 정확한 서명 관측을 검증합니다.
구성이 일부만 제공되거나 로컬 실행 위치에서 키를 사용하거나 자격 증명 계보가 겹치거나 제한된
발급 구간 밖에서 관측이 서명되면 시작을 거부합니다.

## Competency 및 수락

집중 test가 다음 질문을 입증하는 경우에만 구현이 충분합니다.

1. 하나의 query로 decision의 no-action baseline, 선택된 option, `ExpectedEffect`, 관측 구간 및
   Process lineage를 복구할 수 있나요?
2. 하나의 query로 provider receipt와 독립적으로 관측된 outcome을 구분할 수 있나요?
3. Support 및 refutation 근거가 병렬 causal object를 만들지 않고 기존 `CausalHypothesis`를 개정할
   수 있나요?
4. Intervened, censored, incomplete 또는 conflicting horizon이 unscorable 상태를 유지할 수 있나요?
5. Active/challenger divergence가 decision을 hold하면서 challenger의 active logic 대체 또는
   promotion state 쓰기를 방지할 수 있나요?
6. 모든 결과에서 ontology, simulation, model 및 logic output이 evidence-only 상태를 유지하나요?

첫 반증 check는 worker A의 competency test입니다. 기존 graph로 여섯 질문을 모두 표현할 수 있다면
`HypothesisCampaign` 추가는 설계 실패입니다. 표현할 수 없는 질문이 있다면, 가장 작은 ontology
확장을 검토하기 전에 실패한 query가 누락된 identity, property 또는 relationship을 식별해야 합니다.

## Non-goal 및 완료된 foundation

이 campaign은 다음 완료 capability를 다시 구현하거나 fork하지 않습니다.

- `SecuredQueryReceiptAuthority`
- `query.network_path_segments` 및 `query.pod_telemetry_path`
- semantic Function runtime
- bitemporal topology 및 metric semantics
- reconciliation event, ledger 및 binder
- Dynamic engine 및 graph closure job
- `ops.scale-out` core planning vertical

Worker는 public contract를 통해 이러한 capability를 evidence source 또는 fixture로 인용할 수 있습니다.
구현을 수정, wrap, rename 또는 duplicate하지 않습니다.
## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/rules-and-detection/operational-hypothesis-loop.md) |
| DecisionCase, ActionOption, ExpectedEffect 및 Process semantic | [FDAI Operating Ontology](../architecture/operating-ontology-ko.md) |
| Versioned logic 및 candidate planning | [Operational Planning](../decisioning/operational-planning-ko.md) |
| 사후 액션 causal claim 및 refutation | [Causal Incident Graph](causal-incident-graph-ko.md) |
| Active/challenger simulation 경계 | [Assurance Twin](../operations/assurance-twin-ko.md) |
| Process journal 및 독립 outcome check | [Process Automation](../decisioning/process-automation-ko.md) |
