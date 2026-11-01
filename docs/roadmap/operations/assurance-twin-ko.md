---
title: 어슈어런스 트윈 (질의가능하고 선제적이며 검증가능한 리뷰)
translation_of: assurance-twin.md
translation_source_sha: 237ae8aba9777067fd758bb8022d8931ed3f8926
translation_revised: 2026-11-01
---
# 어슈어런스 트윈 (질의가능하고 선제적이며 검증가능한 리뷰)

"아키텍처 리뷰 에이전트" 요청에 대한 FDAI의 답은 문서 인덱스에 붙인 챗봇이
아닙니다. 그것은 **어슈어런스 트윈(Assurance Twin)** 입니다: 거버넌스 대상 구독의
질의가능하고 온톨로지에 근거한 디지털 트윈으로, 질문에 결정론적으로 답하고, 누가
요청하기 전에 변경을 리뷰하며, 교정을 제안(실행은 절대 하지 않음)합니다. 모델은
자연어를 타입이 있는 그래프 질의로 컴파일하고 마지막에 결과를 산문으로 렌더링합니다;
답 자체는 트윈 위에서 결정론적 엔진이 산출하므로, 모델의 주장이 아니라 **구성에 의해**
근거가 있고 검증가능합니다.

> **범위**: 고객-비종속. 트윈의 스키마, 규칙, 임계값은 제네릭합니다; 포크는 `Inventory`
> 시임과 자신의 규칙 세트를 통해 자체 리소스 모집단을 공급합니다. 고객 값, 테넌트 id,
> 리소스 이름은 여기에 존재하지 않습니다
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

> **위치**: 트윈은 온톨로지 그래프 위의 **읽기 전용 투영(변환 결과)** 입니다. 특권
> 아이덴티티를 절대 보유하지 않습니다. 모든 변경은 여전히
> `risk-gate -> executor -> delivery` 를 거치며,
> [app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md) 의
> 읽기 전용 표면 규칙을 보존합니다. 질문에 답하는 것은 결코 액션이 아닙니다.

## 이 문서가 다루는 것

이 문서는 아키텍처 리뷰, Q&A, 평가 리포트 유스케이스를 deterministic-first,
event-driven, risk-gated 설계를 저하시키지 않으면서 커버하는 리뷰/어슈어런스 표면을
규정합니다. [llm-strategy-ko.md](../architecture/llm-strategy-ko.md) 의 온톨로지,
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 의
계층 라우터와 quality 게이트,
[observability-and-detection-ko.md](../rules-and-detection/observability-and-detection-ko.md) 의 탐지 발견 사항,
[deployment-preflight-ko.md](../deployment/deployment-preflight-ko.md) 의 배포 analyzer를 재사용합니다.
새 서브시스템 `core/assurance_twin/` 하나와 전달 인텐트 하나를 추가하며, 나머지는
기존 부품의 조합입니다.
## 왜 챗봇이 아닌가

retrieval-augmented 챗봇은 다섯 가지 구조적 결함을 안고 리뷰 유스케이스에 답합니다.
트윈은 각각을 뒤집습니다.

| 챗봇의 한계 | 결과 | 어슈어런스 트윈의 전환 |
|--------------------|-------------|----------------------|
| **Reactive** - 물어봐야만 답함 | 리뷰 큐 리드타임을 재현(요청 대기, 그다음 사람 대기) | **주변** - 요청이 존재하기 전에 변경 이벤트에서 선제적으로 리뷰 |
| **Ungrounded** - 산문에 대한 벡터 유사도 | 환각 판정이 배포까지 도달 | **Ontology-grounded** - 답은 규칙 경로가 인용된 결정론적 그래프 질의 |
| **Stateless** - 실제 estate가 아니라 문서를 읽음 | "왜 non-compliant인가"에 대한 실제 근거 없음 | **Stateful twin** - 인벤토리 delta로 최신화되는 구독의 라이브 투영 |
| **Inert** - 정보만 반환하고 멈춤 | 사람이 여전히 손으로 고침 | **Action-bridging** - 답이 shadow remediation-PR 제안을 실을 수 있음 |
| **Static** - 인덱스가 stale됨 | 정책 변경 후 틀린 답 | **Self-improving** - 답 못한/abstain한 질문이 규칙 발견 루프로 투입 |

## 다섯 가지 전환

### 1. 주변 (reactive에서 proactive로)

현재 구현은 다음 운영 흐름 전에 멈춥니다. 안정적인 `sha256:` `Resource` 개정은
활성 스냅샷의 신원과 내용, 관측 시각을 포함한 범위가 제한된 실시간 `Resource`
변경분을 함께 식별합니다. `load_at_revision`은 내용을 다시 읽어 다른 개정이면
거부합니다. 주입된 신뢰할 수 있는 출처는 해당 개정을 다시 읽고 명시적인 규칙
적용 범위, 평가한 규칙 식별자, 규칙 집합 다이제스트 및 완전한 점검
결과 집합의 다이제스트를 제공해야 합니다. 발견된 문제가 없다는 결과도 이 독립적이고
완전한 규칙 평가가 있어야만 정상으로 표시합니다. 보류 중인 관계 변경, 근거 부재, 개정
불일치, 오래되거나 상충하는 출처는 사용할 수 없습니다. 이 읽기 전용 기록은 승인, 변경 또는
실행 권한을 부여하지 않습니다.

Forseti는 IaC 계획이 아니라 FDAI 자체의 형식화된 변경 제안을 검토합니다. 2026-09-28 소유자
결정에 따라 Terraform은 로컬 배포 도구이며 거버넌스 수준에서 사용하지 않으므로, Terraform
계획, 렌더링된 템플릿 또는 pull request 차이는 Twin 검토 입력이 될 수 없습니다. 검토 입력
하나는 정확한 ActionType 식별자와 버전, 정확한 대상 `Resource` 참조, 정규 매개변수
다이제스트, 그리고 내용으로 식별되는 같은 제안 다이제스트에 결속된 완료된 what-if 또는
dry-run 결과 하나를 묶습니다. what-if는 통과했고 완전하며 최신이고 합성되지 않았으며
`simulation_engine` 권한 분류에서 나와야 하고, 제안의 대상을 정확히 명시해야 합니다. 해당
ActionType 버전에 대해 검토를 거쳐 선언된 효과 모델은 매개변수를 대상의 최상위 속성에
대응시킵니다. 모든 매개변수는 사용되거나 비활성으로 선언되어야 합니다.

트윈은 요청이 아니라 형식화된 변경이 제안될 때 검토합니다. 형식화 파이프라인 생산자는 제안과
what-if를 내용으로 식별되는 영속 입력 대기열에 제출합니다. Forseti의 생산자는 보관 인벤토리
개정에 있는 제안 대상의 임시 변환 결과에 선언된 효과를 적용하고, 컨트롤 루프 T0/OPA 세대가
완전한 평가 증적으로 변경된 대상을 평가합니다. 기록되는 각 속성의 보관 값과 예측 값을 리프 단위로
비교하며, 실제로 바뀌는 모든 리프는 해당 대상에 적용되는 Rule 하나 이상이 선언한 입력으로 포함되어야
합니다. 상위 경로의 입력은 하위 경로를 포함하지만, 하위 경로의 입력은 상위나 형제 경로를 포함하지
않으며, 바뀌지 않은 리프에는 입력이 필요하지 않습니다. 그렇지 않으면 변경은
`effect_unassessed`입니다. 그런 다음 Forseti의 작성기는 정확한 개정의 아웃박스를 통해 범위가
제한된 읽기 전용 검토를 게시합니다. 효과 모델 누락, 없거나 오래되었거나 불완전하거나 실패했거나
상충하는 what-if, 보관 개정 밖의 대상, 선언되지 않은 매개변수, 평가되지 않은 속성이 있으면
제안은 `clear`가 아니라 사용할 수 없음으로 정리됩니다.

검토 키는 제안 참조이므로 원장은 제안마다 정확히 하나의 현재 검토를 유지합니다. 더 새로운 개정은
하나의 compare-and-set으로 이전 검토, 그 아웃박스, Saga 계보를 대체하며, 지연된 이전 개정은
이를 대체하지 못합니다. Operator 변환 결과도 한 변경 핸들에 사용 가능한 검토가 둘이면 충돌
공백으로 처리합니다. 입력 대기열 행은 작성기가 그 정확한 검토를 확인할 때까지 `recorded`로
남습니다. Rule 세대나 인벤토리 개정 변경으로 작성기의 보호된 커밋이 막히면, Forseti는 중계기가
멈추도록 오래된 요청을 폐기합니다. what-if가 최신인 동안 최대 세 번의 도출 시도 안에서 다시
도출하며, 그렇지 않으면 `rule_generation_changed` 또는 `inventory_revision_changed`로 제안을
사용할 수 없음으로 정리합니다. 외부 Checks 발행기는 나중에 보관된 검토를 표시할 수 있지만, 이는
전달이지 입력이 아닙니다.

예: 형식화된 제안이 저장소 계정 하나에 `public_access: enabled`를 설정하려 합니다. 해당
ActionType 버전에 대한 검토된 효과 모델과 그 정확한 제안에 대한 완료된 what-if가 있으면,
Forseti는 누가 요청하기 전에 해당 대상에서 위반된 공개 접근 Rule을 인용하는 `blocked` 검토를
게시합니다. 이 검토는 제안을 승인, 실행 또는 승격하지 않습니다.

### 2. Ontology-grounded (수집에서 그래프 질의로)

트윈은 산문 인덱스가 아니라 온톨로지 그래프입니다. 모든 거버넌스 대상 리소스는 `Resource`
ObjectType이고; 관계는 기존의 타입 있는 LinkType(`contains`, `attached_to`, `depends_on`)이며,
규칙 매치는 `Finding` 입니다([llm-strategy-ko.md](../architecture/llm-strategy-ko.md) 참조). "왜 이 리소스가
non-compliant인가"는 구체적인 근거 체인을 반환하는 그래프 탐색으로 답합니다, 예:

```text
Resource:storage-x --attached_to--> Resource:subnet-y
subnet-y --contains(-1)--> vnet-z
Finding: storage-x violates rule:object-storage.private-endpoint.required
  evidence: rule path + evaluated property (publicNetworkAccess=Enabled)
```

체인은 결정론적이고 재현가능합니다: 같은 트윈 상태는 누가 묻든 어떻게 표현하든 같은 답을
산출합니다.

### 3. Verifiable (text-to-answer가 아니라 text-to-query)

이것이 핵심 메커니즘입니다. 모델은 **자연어 질문을 타입 있는 온톨로지 질의로 컴파일**하고,
마지막에 **결과를 산문으로 렌더링**하는 데 쓰입니다. 사실의 출처는 결코 모델이 아닙니다.

![3. Verifiable (text-to-answer가 아니라 text-to-query). 주요 단계는 NL 질문, 모델: NL을 타입 있는 / 온톨로지 질의로 컴파일, verifier: 질의가 / well-typed하고 읽기 전용인지, T0: 트윈 위에서 질의 실행 / (결정론적), 어슈어런스 트윈 / 온톨로지 그래프, 근거 있는 결과 집합, 모델: 결과 설명 / + 규칙 경로 인용, 답 + provenance / + confidence + what-if, abstain: '모름'입니다.](../../diagrams/generated/fdai-roadmap-operations-assurance-twin-01.ko.svg)

- **컴파일이 검증됨**: 컴파일된 질의는 온톨로지 스키마에 대해 well-typed여야 하고 읽기
  전용이어야 합니다; 검사를 통과하지 못한 질의는 실행되지 않고 거부됩니다. 이는 T2
  검증기와 동일한 실패 시 차단 자세입니다.
- **컴파일 근거가 정확함**: 런타임 조립은 컴파일러 개정, 정확한 질문 다이제스트, 제한된 결과
  수, 하나 이상의 근거 참조를 요구합니다. 유효하지 않거나 주입된 출력은 명시적 모호성 결과가
  되며 내용 없는 발견 공백만 발행할 수 있습니다.
- **답은 계층을 거침**: 정확한 규칙/그래프 매치는 **T0** 에서 해결되고; 알려진 패턴에
  가까운 모호한 질문은 **T1** 유사도를 쓰며; 진정으로 새롭거나 모호한 질문만 **T2** 에
  도달하고, T2 출력은 표시되기 전에
  [quality 게이트](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2)
  (mixed-model 교차 검증, 검증기, grounding)를 통과합니다.
- **grounding 아니면 abstain**: 모든 답은 그것을 정당화하는 규칙과 그래프 노드를 인용합니다.
  근거를 댈 수 없는 답은 추측 대신 "모름"을 반환합니다. 환각은 프롬프트 튜닝이 아니라
  구성에 의해 차단됩니다.

### 4. Action-bridging (inert에서 제안으로)

답은 제안된 수정을 실을 수 있지만, 트윈은 결코 실행하지 않습니다. 질문이 고칠 수 있는
발견 사항으로 해소되면, 트윈은 규칙의 `remediates` ActionType로부터 만든 **shadow
remediation-PR 제안**을 붙일 수 있습니다. 그것에 대해 행동하는 것은 기존의 gated 경로입니다:
`risk-gate -> executor -> delivery`, 고위험은 무엇이든 HIL로
([risk-classification-ko.md](../decisioning/risk-classification-ko.md) 참조). 챗과 콘솔은 읽기 전용
표면으로 남습니다; 제안은 PR로의 링크이지 mutate하는 버튼이 아닙니다.

예: "비공개 엔드포인트 없는 저장소 계정을 고쳐줘"는 발견 사항 집합으로 해소됩니다; 트윈은
리소스당 하나의 shadow remediation-PR을 엽니다(blast-radius 상한 아래 배치), 각각 롤백
계약을 가지며 HIL로 라우팅됩니다. 사람이 승인하기 전에는 아무것도 바뀌지 않습니다.

### 5. Self-improving (static에서 living으로)

질문은 발견 신호입니다. 트윈이 **abstain** 한 질문, 또는 커버하는 규칙이 없는 반복 질문은
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 의
자율 규칙 발견 루프로 후보로 발행됩니다(HIL 패턴과 재정의를 지켜보는 것과 같은 루프).
후보는 출처 이력을 실으며 카탈로그에 들어가기 전에 표준 quality 게이트를 통과합니다; 트윈은
카탈로그를 직접 mutate하지 않습니다. 따라서 지식 표면은 stale되는 대신 estate를 추적합니다.

첫 설계에서는 모델을 직접 연결하고 모델을 사용할 수 없을 때 lexical 컴파일러를 사용하는 방안을
검토했습니다. 이 대체 경로는 의미를 날조하고 표현 코드를 의미 권한으로 만들 수 있습니다.
수정된 설계는 프로바이더 중립 컴파일러와 발견 경계를 제공하고 기본값을 명시적 사용 불가로
유지하며 주입된 모든 계획을 결정론적으로 검증합니다. 발견 인계에는 질문 다이제스트와 판단
보류 코드만 전달합니다. 원시 질문, 결정, 변경 권한은 이 경계를 통과하지 않습니다.

## 시뮬레이터로서의 트윈 (그래프 전체에 대한 what-if)

액션별 what-if 검증기
([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2))
는 단일 변경의 효과를 예측합니다. 트윈은 이를 그래프 전체로 일반화합니다: 제안된 변경을
**scratch 투영**에 적용하고 라이브 estate에 손대기 전에 결과를 평가합니다. 하나의
시뮬레이션 표면이 세 버티컬 모두를 서비스하며, 그래서 트윈은 설계를 복잡하게 하는 게
아니라 단순화합니다.

| 버티컬 | 시뮬레이션 질문 | 답하는 방법 |
|----------|---------------------|-------------|
| **변경 안전성** | 이 변경의 영향 범위는? 하류에서 무엇이 깨지는가? | 변경된 `Resource` 로부터 `attached_to` / `depends_on` 탐색; 영향 집합 + 새로 위반된 규칙 보고 |
| **복원력 (DR)** | estate가 목표 RPO/RTO를 만족하는가? 무엇이 장애 조치되는가? | 리전/존 손실 시나리오를 트윈에 대해 재생; 복구 경로 없는 리소스와 예상 RPO/RTO 갭 보고 |
| **비용 거버넌스** | 이 변경/이 최적화의 비용 델타는? | 투영에 SKU/스케일 델타 적용; 예상 unit-cost 변화 보고 |

- **읽기 전용이고 결정론적**: 시뮬레이션은 scratch 투영만 mutate하고, 라이브 estate나
  감사 저장소는 절대 건드리지 않습니다. 이는 T0 성격의 패스입니다: 정적 그래프 평가가
  대부분을 해결하고, 범위가 제한된 읽기 전용 프로브가 나머지를 확증합니다,
  [deployment-preflight-ko.md](../deployment/deployment-preflight-ko.md) 가 하는 것과 정확히 같습니다.
- **Shadow-first**: 각 시뮬레이션 파생 발견 사항은 shadow 모드로 배포되고, 정확도와
  false-positive 비율이 고정된 시나리오 세트에서 측정된 후에만 shadow-to-enforce 규칙에
  따라 승격됩니다([goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md)).
- **Fidelity 측정**: `core/assurance_twin/fidelity.py`
  (`SimulationFidelityLedger`) 가 그 승격의 메커니즘이다. 각 **예측된** 효과(비용 delta,
  blast-radius 개수, RPO/RTO 공백)를 안정적인 prediction id 로 **실제** 관측 결과와 조인해
  예측기별 MAE, MAPE, within-tolerance 비율을 누적한다. `is_reliable` 은 이를 실패 시 차단
  승격 신호로 바꾼다: 최소 표본 수 미만이거나 MAPE 기준 초과인 예측기는 신뢰할 수 없으므로,
  호출자는 그것을 shadow 에 유지(또는 강등)한다. 이는 측정되지 않은 what-if 가 oracle 로
  작동하는 것을 막는다 - 실현되지 않는 시뮬레이션은 강제 적용 자격을 자동으로 잃는다.
- **적응하지만 promotion-gated**: `effect_model.py`는 versioned 활성 모델로 no-op 및 액션
  가지를 평가하고 별도 challenger는 기준 시점 이후의 scorable `ResponseOutcome`에서만 학습합니다.
  Scheduled growth 작업은 optimistic 동시성으로 challenger 개정 번호를 저장하며 활성 키를
  교체하지 않습니다. 활성/challenger divergence 또는 `quasi_experimental` 미만 근거는
  검토를 요구합니다. `rca/temporal_causality.py`는 선택적 confounder 조정, reverse-direction
  검사 및 multiple-testing 보정을 포함한 differenced lag 상관관계를 추가합니다. 이
  observational 경로는 최대 `predictive_precedence`까지만 도달하고 experimental causal grade를
  만들지 않습니다.
  `runtime.py`는 최대 32개 current-state 가지의 활성 및 challenger 모델을 로드합니다. 활성
  모델 누락, 낮은 근거 또는 divergence는 검토를 요구하며 T1 호출자는 abstain 상태를 유지하고
  learned 액션을 정상 re-verification 경로로 보냅니다.

### 스칼라 피드백의 신뢰성

스칼라 학습은 기존 `ResponseOutcome`, StateStore 모델 키, 활성/challenger 읽기 경로를
유지합니다. 실행 요청 수락, 독립적으로 관측한 효과, 실행 허용, 롤백, 판단 정보의 충분성은
서로 구분합니다. 실제 적용된 조치의 실행 결과가 수락 상태이고, 결정이 `auto` 또는 `hil`이며,
`rollback_succeeded: false`가 명시된 평가 가능 관측만 challenger 보정에 사용합니다.
승인 거절, shadow 실행, 롤백 상태 미확인, 관측 불가는 실패나 보상이 아닙니다. 효과 검증
결과에서 실행 허용 결정을 만들어 내지 않고 원래 결정을 보존합니다. 효과 관측 구간의
검증만으로 복구의 지속이나 부작용 부재가 확인되는 것은 아닙니다.

`ResponseOutcome` 1.1은 선행 기록에 결속된 결과 리비전, 변경할 수 없는 예측 스냅샷,
관측 단위와 증적 참조를 추가합니다. 버전 1.0은 기존 전송 형식과 감사 읽기 호환성을
유지하지만, 운영상 허용 범위를 점 예측으로 간주하여 모델을 보정하지는 않습니다.
스냅샷은 정확한 조치, 이벤트, 대상, 예측기 버전/다이제스트, 단위, 독립성 키, 원본 다이제스트,
지식 시점, 점 예측, 구간과 명목 포함률을 기록합니다. 논리적 조치/예측 식별자와 내용 기반
변환 결과는 실행 전에 감사와 함께 저장합니다. 스냅샷 누락, 단위/예측기 불일치, 관측 증적
부재, 최신 리비전 출처의 사용 불가는 학습 부적격이며 임의의 성공이나 실패가 아닙니다.

모델 행에는 버전이 있는 피드백 체크포인트를 둡니다. 최초 학습 기준 시점, 다이제스트로만
구성된 에피소드별 처리 증적 최대 256개, 선택적인 보류 사유를 저장합니다. 모델 파라미터,
처리 증적, 감사 기록은 리비전을 확인하는 하나의 트랜잭션에서 커밋합니다. 응답이 유실된 뒤
동일 결과를 재전송해도 중복 갱신하지 않으며, 커밋되지 않은 쓰기는 재시도할 수 있습니다.
기록 시각이 같거나 도착 순서가 뒤바뀐 서로 다른 이벤트도 최초 기준 시점 이후라면 학습할 수
있습니다. 모델의 지식 시점은 뒤로 이동하지 않으며 처리 시계도 반영합니다. 조치/메트릭
모델마다 권위 있는 독립성 키 하나는 최대 한 표본만 제공합니다. 학습기는 리소스 이름이나
confidence로 이 키를 만들지 않습니다. 등록된 seed 파라미터와 실제 결과 적용 순서를
보존하며, 모델 변환 결과의 내용 검증값으로 확인된 손상이 조용히 예측에 쓰이지 않게 합니다.

이미 적용한 버전의 내용 변경, 식별자 재사용, 정정은 추가 표본으로 세지 않고 challenger를
보류합니다. 범위가 제한된 재구축은 완전한 선행 리비전 체인을 검증하고, 정확히 등록된
seed에서 최신 적격 관측을 재생하며 실제 적용한 에피소드 대표와 순서를 보존합니다.
검토 매니페스트는 seed의 모든 사실과 입력 리비전을 결속합니다. 이전 세대 보존, 교체,
감사는 원자적으로 저장합니다. 재구축 인가, 최신 원본 확인, 예측 보관 확인이 필요하며
unknown 입력만으로 모델을 초기화해 준비된 것처럼 만들지 않습니다. seed나 처리 증적을
귀속할 수 없는 기존 비어 있지 않은 모델은 계속 보류합니다. 과거 피드백을 새 결과처럼
처리하지 않도록 증적을 퇴출하지 않습니다. 이는 JSON 변환 결과의 추가이며 DB
마이그레이션은 아닙니다. 재구축의 1,024개 기록 한도는 자원 한도이지 통계적 증거 기준이 아닙니다.

Dynamic 학습기는 패턴 성장과 독립적인 감사 소스 처리 위치를 유지합니다. challenger 미등록,
동시 갱신 충돌, 체크포인트 사용 불가는 해당 처리 위치가 전진하기 전에 귀속 가능한 감사
사유를 남기고 배치를 중단합니다. 앞서 커밋한 갱신은 재시도 시 중복 적용하지 않습니다.
CLI는 `dynamic-learning`, `pattern-growth`, `graph-dynamic`을 독립적으로 실행할 수 있습니다.
스칼라 소비자와 구성된 런타임은 소유 감사 DSN의 읽기 전용 PostgreSQL 리비전 출처를
연결합니다. 버전 1.1 감사 변환 결과는 응답 계약을 바꾸지 않고 다시 계산할 수 있는 결과
다이제스트를 조회용으로 보존합니다. 같은 반복 읽기 스냅샷에서 조회 근거와 결과별 전체
이력을 확인하며, 잘못되거나 누락되거나 미래인 기록, 대체된 리비전, 불완전한 체인은
명시적인 진단과 함께 학습과 학습 모델 읽기를 보류합니다.

`dynamic-rebuild`는 `FDAI_EFFECT_REBUILD_ACTION_TYPE`과 `FDAI_EFFECT_REBUILD_METRIC`으로
정확히 보관된 seed와 실제 적용 순서를 미리 확인합니다. 독립 검토용 결정적 매니페스트를
보고하고 기존 의사 결정 근거의 정확한 인가를 요구한 뒤 challenger와 이전 세대만 원자적으로
저장합니다. 검토가 없으면 모델을 바꾸지 않고 실패 상태를 반환하며 완료된 요청을 다시
처리하면 갱신하지 않습니다. 이 명령은 승인을 발급하지 않습니다.
검토가 필요하면 권한 값이 false인 명시적 JSON 검토 대상을 출력합니다. 패키지의 재구축
도구는 로컬 실행 환경 전용입니다. 배포 환경의 승인된 비공개 인가 제공자가 명시적으로
조립되기 전까지는 DB나 인가를 조회하기 전에 배포 환경의 실행을 차단합니다.

호환 `growth` 명령은 확인된 단계 실패를 보고하되 성공한 독립 단계의 결과는 버리지 않습니다.
패턴 성장은 holdout을 기다리는 동안 범위가 제한된 원본 참조만 보관하고, 재시작 후 원본을
다시 확인하며, 새 입력에도 실행 예산을 남깁니다. 시계가 고정돼도 처리가 대기하기 전에
재시도 순서를 영속화합니다. 이미 소유한 원본 행은 새 입력의 처리 예산을 쓰지 않고 인계를
완료합니다. 쓰기 대상은 관련 없는 상태 저장소 DSN이
아니라 구성된 패턴 라이브러리 DSN을 사용합니다. 서로 다른 DB의 모델/벡터 쓰기는 멱등
인계이며 하나의 분산 트랜잭션이 아닙니다.
명시한 대상 구성은 존중하며, 미설정 시의 기존 동작은 유지합니다. 모든 배포의 읽기/쓰기
구성이 이미 일치한다고 주장하는 것은 아닙니다.

설계에서는 시각만 있는 커서를 처리 완료 증거로 사용하지 않으며, 불필요한 두 번째 DB나
새 보상 모델도 추가하지 않습니다. 검토 과정에서 두 조건을 보완했습니다. 기존 학습 데이터를
다시 받아들이지 않도록 최초 기준 시점을 유지하고, 정정이나 용량 소진 시 중복 방지 증적을
버리지 않고 안전하게 보류합니다. 로컬 평가는 독립적인 테스트 결과를 제공하기 전에 활성 및
challenger 예측을 동결하고, 이후 `DynamicRuntimeCoordinator`로 저장된 challenger를 읽습니다.
오차와 예측 구간 포함률을 따로 보고하며 승격 권한을 부여하지 않습니다. 이는 회귀 검증이지
운영 환경이나 환경 간 일반화 성능 검증은 아닙니다.

2026-10-17의 집중 회귀 검사에서는 합성 사례의 다음 예측 오차가 10에서 0으로 줄었습니다.
baseline 오차는 10이었고, 검토 가드는 유지됐으며, 실행과 승격은 모두 0건이었습니다.
검증 이력은 [영문 구현 기록](assurance-twin.md#implementation-history)에 남깁니다.
구성된 스칼라 시뮬레이션은 요청과 모든 모델 I/O에 하나의 협력적 전체 기한을 적용합니다.
시작 시 같은 리비전의 전체 모델 본문을 대조하고, 갱신된 challenger의 구성 원본을 보관된
불변 seed와 결속합니다. 출처 장애로 계보 검증을 건너뛸 수 없으며 근거가 없는 기존 계보는
모델 관계를 추정하지 않고 검토 후 복구해야 합니다.
challenger가 없거나 보류되면 가드를 없애지 않고 검토를 위한 사용 불가 상태를 유지합니다.
기본값이 꺼진 T1 적격성 비교는 권한이 없는 baseline/challenger 결과만 기록하고 실제
선택을 바꾸지 않습니다. 시간순 평가는 동결 예측과 독립 에피소드 그룹을 사용하고 오차,
구간 포함률, 구간 폭을 따로 기록합니다. 새 정책의 복구율을 측정하는 것은 아닙니다.

> **미완료 전달 범위:** 권위 있는 최신 리비전/재구축 증적 연결, 예측 및 세대의 보존 검증,
> baseline과 분리된 shadow 저장소를 사용하는 적격 Pattern의 T1 편입, 짝지은 운영 평가,
> 대상별 런타임 증적은 아직 필요합니다. 누락된 연결을 항상 수락하는 대역으로 대체하지
> 않습니다. 이 로컬 체크포인트만으로 프로덕션 활성화, 전범위 Low 이하 하드닝 완료,
> 게시나 병합을 주장하지 않습니다.

설치 소유의 일관된 보관 패턴 인가 발급자와 독립적으로 측정한 운영 효과는 #2194에서
추적합니다. 이는 로컬 픽스처나 소스 병합으로 추정할 수 없는 선행 조건입니다.

### 운영 연결 및 가드

`FDAI_DYNAMIC_CONFIG_JSON`은 배포된 코어 런타임에서 scalar Dynamic을 활성화합니다. Strict
객체는 ActionType별 메트릭, 목표, 효과 delta, uncertainty, divergence 및 최신성 설정,
exact 활성/challenger 모델 기록, causal 증적 다이제스트 허용 목록을 포함합니다. 시작은 부분
필드, 알 수 없음 필드, 누락된 모델 쌍, 충돌하는 영속 모델 또는 허용 목록에 없는 증적을 가진
모델을 차단합니다. 이 설정이 없으면 Dynamic은 명시적으로 사용 불가 상태를 유지하고 기존
결정론적 라우팅은 변경되지 않습니다.

Azure 어댑터는 promoted 인벤토리 근거의 `operational_context.metric_values`를 읽고 범위가 제한된
액션 가지 하나를 만듭니다. 활성/challenger 모델은 영속 StateStore 레지스트리에서 가져옵니다.
구성된 Dynamic 시뮬레이션은 T1 reuse가 안전성 검토에 들어가기 전 lower-only 가드가 됩니다.
사용 불가 요청, 누락된 모델, divergence, 그래프 검토 사유, 불변식 실패 또는 누락된
Dynamic 감사 근거는 사람 검토로 라우팅됩니다. Prediction은 액션을 승인하거나 자율성
상한을 높일 수 없습니다.

### Graph-wide temporal Dynamic

기존 액션/메트릭 모델은 첫 번째 Dynamic 계층으로 유지됩니다. Graph-wide 시뮬레이션은 이를
`OperationalStateTrajectory`, `GraphEffectModel`, `DynamicInvariant`, `TrajectoryOutcome`으로
확장합니다. Trajectory는 온톨로지 release, 그래프 및 인벤토리 개정 번호, 근거 기준 시점, horizon,
정규화된 객체/메트릭 구획, intervention 참조, watermark, 완전성, 잘림 및
결정론적 다이제스트를 고정합니다. 대화 및 실행 `TrajectoryEnvelope`와 구별되며 어느
기록도 자체적으로 프로바이더 상태 근거가 아닙니다.

Graph propagation은 fixed 간선, 깊이, 구획, horizon 한계 아래 선언된 LinkType 경로만 따릅니다.
결정론적 토폴로지 효과를 검증된 활성 모델보다 먼저 적용합니다. Interaction 용어는 병렬
액션 효과를 linear sum으로 취급하지 않게 합니다. 모델 누락, stale 기준 시점, cycle, 사용 불가
기준선, 잘림, 낮은 causal grade 또는 활성/challenger divergence는 검토를 요구합니다.
Challenger prediction은 가지 순위를 정하지 않습니다.

모든 그래프 시뮬레이션 요청은 비어 있지 않고 범위가 제한된인 불변식 튜플을 전달합니다. Simulator는
각 불변식을 활성 trajectory에서 평가하고 정확한 불변식별 결과를 반환합니다. Violation 또는
unscorable 불변식은 고정된 검토 사유를 추가하며 권한을 높일 수 없습니다. 실행 중 관찰된
불변식 violation은 실행 중 계획을 rewrite할 수 없으며 forward 전달을 중지하고 기존 타입이 지정된
복구 경로에 다시 진입합니다.

Graph 런타임은 시뮬레이션 근거를 반환하기 전에 predicted 다이제스트, exact trajectory 및 challenger
모델 참조를 StateStore trajectory 원장에 기록합니다. Heimdall의 완전한 독립적인 관측은 `close_trajectory_outcome`을
통해 에피소드를 matched 또는 mismatched로 종료합니다. 신원 mismatch, censoring, incompleteness 및
unscorable 비교는 에피소드를 열림 상태로 두며 모델을 갱신하지 않습니다. 동일한 종결 재생은
no-op이고 conflicting 재생은 실패 시 차단됩니다. Off-path 그래프 종결 실행기는 완전한 comparable
challenger 구획에 대해서만 learning 관측을 만들고 `StateStoreGraphEffectModelRegistry`를 통해
적용합니다. 활성 그래프 모델은 별도의 검토된 승격 근거가 적용될 때까지 변경할 수 없는 상태를
유지합니다. Scheduled growth 작업은 텔레메트리 grace 구간 이후 구성된 메트릭 프로바이더를 통해 due 열림
에피소드를 관측하는 `MetricGraphTrajectoryOutcomeSource`를 사용합니다. 모든 predicted 구획에 독립적인
finite 근거가 있을 때만 종결 명령을 생성하며, 그렇지 않으면 값을 날조하지 않고 에피소드를
열림 상태로 유지합니다.

`GET /dynamic-assurance`는 scalar/그래프 모델 개수, 샘플/오류 요약 및 열림/closed trajectory
에피소드를 제공하는 Reader-only 영속 변환 결과입니다. 모델 등록, 승격, 승인 또는 실행
명령을 노출하지 않습니다.

## 평가 리포트 (구독 자세, 온디맨드)

변경별 선제 리뷰는 estate 전체 리포트로 조합됩니다. 현재 트윈에 대해 적용가능한 모든
규칙을 실행하면 `PostureAssessmentReport` 가 산출됩니다 - `DeploymentReadinessReport`
([deployment-preflight-ko.md](../deployment/deployment-preflight-ko.md))를 단일 배포에서 구독 전체로
일반화한 것입니다. 각 항목은 동일한 세 필수 부분을 유지합니다 - 근거 있는 근거(인용된
규칙), 심각도, 구체적인 레버에 매핑된 해석 - 그래서 리포트는 단순 점수가 아니라
실행가능합니다. 콘솔은 읽기 전용 `ReadPanel` 라우트를 통해 이를 렌더링하며
([project-structure-ko.md](../architecture/project-structure-ko.md)); 특권 호출을 하지 않습니다.

### 심층 보안 평가

보안 범위 리포트는 severity-only 발견 사항 목록보다 더 많은 맥락을 유지합니다.
Collector는 Azure Resource Graph 속성, 서버 매개변수, Defender 평가, WAF
기록, 정책 compliance, 진단 설정, 버전/참고용 일치를
`SecurityControlObservation` 값으로 정규화합니다. 각 관측은 현재값과 기대값,
컨트롤 상태, 적용 가능성, 출처와 수집 시각, 근거 참조, 교정과
검증 단계, 우선순위와 조치 기한, CVE 적용 가능성과 patch 상태, compliance 대응,
managed-service patch note를 기록합니다.

적용 가능성은 범위가 제한된 enum(`applicable`, `not_applicable`, `unknown`)이며 관측
시각은 timezone-aware입니다. `unknown` 컨트롤은 실행 가능한 권고가 아니라
근거 공백입니다. 권고는 근거가 있는 교정 텍스트를 가진 fail 또는 경고
컨트롤에서만 파생합니다.

평가는 각 사실을 제공한 출처를 기록합니다.

| 출처 데이터 | 추출하는 정보 |
|-------------|---------------|
| Azure Resource Graph 리소스 속성 | AKS 버전, 비공개 API, RBAC, 네트워크 정책, Entra/local-account 상태, 워크로드 신원, 이미지 cleaner, add-on, 업그레이드 채널과 MySQL 네트워크, 백업, HA, encryption, 버전 |
| Azure Resource Graph `sku` 및 `kind` | AKS와 MySQL 서비스 계층 및 리소스 종류 |
| AKS node-pool 리소스 속성 | 노드 이미지 버전, secure boot, virtual TPM |
| MySQL 서버 매개변수 | Secure 전송 계층, 허용 TLS 버전, 감사 로깅 |
| Azure Monitor 진단 설정 | 승인된 platform 로그와 메트릭이 근거 저장소로 라우팅되는지 여부 |
| Defender for Cloud 평가 | 런타임 protection 커버리지와 actionable unhealthy 발견 사항 |
| 애플리케이션 게이트웨이 WAF 로그 | Matched/차단된 룰, attack 상세, 리소스, 이벤트 근거 |
| Security bulletin 및 참고용 일치 | CVE id, 적용 가능성, patch 상태, 출처 URL, managed-service backport note |
| Rule 및 compliance 메타데이터 | 기대값, 근거 설명, 교정, 검증, priority, 조치 기한, compliance 컨트롤 |
| Report-feed 시각 및 출처 오류 | 근거 구간, 출처 가용성, 부분 읽기, 최신성 공백 |

관측된 ARG 또는 ARM 인벤토리 스냅샷이 promote되면 인벤토리 작업은 범위가 제한된 행
상한 아래에서 활성 AKS, node-pool, MySQL 기록만 읽고 결정론적 Azure analyzer를
실행한 다음 시각이 있는 컨트롤 신호를 영속 보고 피드에 기록합니다.
Supplemental 프로바이더는 서버 매개변수, diagnostic-setting 상태, Defender 커버리지,
참고용 일치를 추가할 수 있습니다. 프로바이더가 구성되지 않았으면 해당 컨트롤과
출처 커버리지는 컨트롤 실패가 아니라 `unknown` 또는 `unavailable`로 남습니다.

`build_security_assessment`는 순수하고 결정론적인 접기로 유지됩니다. Verdict와 함께
다음을 파생합니다.

- 발견 사항, 룰, 리소스, 리소스 타입, 컨트롤, 근거 개수
- 통과, fail, 경고, not-applicable, 알 수 없음 컨트롤 개수
- 컨트롤 통과 비율, 근거 커버리지, 출처 커버리지
- category 및 리소스 타입 분포
- 긍정 컨트롤과 알 수 없음 컨트롤
- due 시각과 검증 단계를 포함한 우선순위별 권고
- CVE 적용 가능성, patch 상태, compliance 대응
- available, 부분, 사용 불가, stale 데이터 출처 개수

`clear` 판정은 관측된 위험만 설명하며 평가가 완전하다는 뜻은 아닙니다.
`completion_status`, 출처 커버리지, stale 출처, 알 수 없음 컨트롤, 누락된 근거를
계속 표시하므로 프로바이더를 사용할 수 없는 상태가 잘못된 clean 결과로 바뀌지 않습니다.

읽기 전용 `Security Assessment` 카탈로그 보고는 기존 Reports 페이지에서 이 변환 결과를
렌더링합니다. KPI, control-status, chart, 표, 그룹, tabs, note 위젯을 재사용하므로
새 브라우저 실행 표면이나 특권 신원을 도입하지 않습니다.

## 모듈 배치

서브시스템은 `core/assurance_twin/` 에 있으며 다른 모든 코어 서브시스템처럼 `shared/`
계약과 프로바이더만 가져옵니다
([project-structure-ko.md](../architecture/project-structure-ko.md)). 클라우드 SDK도 특권 아이덴티티도
보유하지 않습니다.

| 컴포넌트 | 책임 |
|-----------|----------------|
| `projection` | 변경할 수 없는 메모리 내 기준선을 만들고 임시 변경을 적용합니다. 보관된 Inventory 스냅샷과 범위가 제한된 실시간 Resource 변경으로 새로운 변환 결과를 만들 수 있습니다. 운영 조립 및 관계를 고려한 유지 관리는 여전히 목표 연결입니다. |
| `query` | 결정론적 pattern 컴파일러로 well-typed 읽기 전용 조회를 검증하고 실행합니다. Model-backed 컴파일러는 프로토콜 목표입니다. |
| `review` | Precomputed 발견 사항을 `IacReviewPublisher`로 게시합니다. Change-signal 평가와 운영 발행기는 목표 연결입니다. |
| `report` | 발견 사항으로부터 `PostureAssessmentReport` 를 조립 |
| `chat` | 변경할 수 없는 근거에 기반한 chat-session 값과 영속성 프로토콜을 제공합니다. 브라우저 또는 전달 연결은 없습니다. |
| `graph_effect` / `graph_runtime` | 범위가 제한된 그래프 효과를 전파하고 필수 active-trajectory 불변식을 평가하며 review-only 시뮬레이션 근거를 반환합니다. |
| `trajectory_ledger` | Predicted trajectory 에피소드를 저장하고 완전한 comparable 결과만 StateStore를 통해 atomically close합니다. |
| `graph_closure` | 독립적인 관측을 off-path로 배출하고 challenger 구획을 갱신하며 활성 변경과 승격이 없었음을 감사합니다. |
| `typed_proposal` | 내용으로 식별되는 형식화 ActionType 제안, what-if 결과, Forseti 작성기가 다시 검증하는 보관 형식화 제안 판독 결과를 정의합니다. |
| `proposal_effects` | 정확한 검토된 ActionType 효과 모델을 찾아 제안의 보관 대상에 대한 예측 임시 변경을 도출하거나 명시적인 사용 불가 사유를 반환합니다. |
| `posture_activity` | Heimdall의 기존 제한된 자세 활동과 Forseti의 별도 읽기 전용 검토 활동을 만듭니다. 전달 레코더는 각 활동을 보관 기록 및 Saga에 귀속된 추가 전용 감사와 함께 준비합니다. 독립적으로 감독되는 두 중계기가 개정에 결속된 이벤트를 게시합니다. 발견 사항을 계산하려면 주입된 신뢰할 수 있는 출처가 여전히 필요합니다. |

`PostgresTwinInventorySource`는 반복 읽기 트랜잭션에서 보관된 Inventory 데이터베이스의
활성 관측 스냅샷을 전체 범위로 읽습니다. 오래되었거나 불완전하거나 대체된 범위를 거부하고,
기준 `Resource`와 실시간 변경의 개수를 제한합니다. `Resource`만 표현하는 임시 변환 결과에
반영할 수 없는 관계 변경도 거부합니다. Heimdall의 프로덕션 자세 생산자는 이벤트 루프 밖에서
컨트롤 루프의 변경할 수 없는 T0/OPA 세대를 재사용하고, 모든 `Resource`의 선언된 Rule 입력과
증적을 요구하며, 원본 저장과 작성기 확인이 끝날 때까지 인벤토리 승격 및 실시간 그래프 잠금을
유지합니다. Forseti의 검토 생산자는 같은 인벤토리 출처와 T0/OPA 세대를 공유합니다. 영속 입력
대기열의 형식화된 ActionType 제안만, 그리고 검토된 효과 모델을 통해서만 검토합니다. 카탈로그가
비어 있으면 평가되지 않은 변경을 오해를 부르는 `clear` 판정으로 바꾸지 않고 모든 제안을 사용할
수 없음으로 유지합니다. 인벤토리 스냅샷 식별자만으로는 두 생산자가 요구하는 정확한 개정이 되지
않습니다.

목표 전달은 기존 `chatops` 어댑터에 인텐트 하나를 추가하고(질문 입력, 근거 있는 답 출력)
제안과 Checks API 리뷰에 `gitops-pr` 어댑터를 재사용합니다. 현재 저장소에는
`IacReviewPublisher` 프로토콜과 테스트 double만 있고 운영 발행기 또는 ChatOps 연결은
없습니다. 이를 추가하더라도 새 특권 표면을 도입하지 않습니다.

## 안전 자세

- **읽기 전용 트윈, gated 실행**: 트윈과 모든 답은 읽기 전용입니다; 변경으로의 유일한
  경로는 `risk-gate -> executor` 로 진입하는 제안이며, 7개 안전조건(stop-condition, 롤백,
  blast-radius 제한, 예행 실행, 리소스 잠금, 멱등성, 감사 항목)은 거기서 강제됩니다.
- **실패 시 차단**: 근거 댈 수 없는 답은 abstain하고; 잘못 타입되거나 읽기 전용이 아닌 컴파일된
  질의는 거부되며; stale된 트윈(`Inventory` 최신성이 `freshness_ttl` 초과)은 ghost 데이터로
  답하는 대신 estate 상태 질문에 답하기를 거부합니다, `RequiresInventoryFresh`
  ([llm-strategy-ko.md](../architecture/llm-strategy-ko.md))를 반영.
- **신뢰할 수 없는 입력**: 질문 텍스트와 변경 페이로드는 신뢰할 수 없으며 프롬프트 주입을
  실을 수 있습니다; 검증기와 읽기 전용 질의 계약이 권위이지, 모델의 자유 텍스트가 아닙니다
  (위협 모델은 [security-and-identity-ko.md](../architecture/security-and-identity-ko.md)).
- **감사됨**: 모든 제안, 리뷰, 시뮬레이션 파생 발견 사항은 그 근거와 함께 감사 항목을
  씁니다; 제안을 산출하지 않는 읽기 전용 질문은 로그되지만 액션이 아닙니다.

## 페이즈

트윈은 기존 페이즈 위에 점진적으로 착지합니다; 새 계층도, risk 게이트가 이미 관장하지 않는 새
자율성도 도입하지 않습니다.

| 페이즈 | 착지하는 것 | 게이트 |
|-------|------------|------|
| **P2** ([phase-2-quality-and-t1-ko.md](../phases/phase-2-quality-and-t1-ko.md)) | 인벤토리로부터 트윈 투영; 검증된 text-to-query; quality 게이트를 통한 근거 있는 답; abstain-to-discovery 피드백 | 답은 근거가 있거나 abstain; 시나리오 세트에서 근거 없는 답 0 |
| **P3** ([phase-3-integrated-loop-ko.md](../phases/phase-3-integrated-loop-ko.md)) | 주변 변경별 리뷰; 변경/DR/FinOps에 대한 그래프 전체 시뮬레이션; shadow remediation-PR 제안; `PostureAssessmentReport` 패널 | 각 시뮬레이션 발견 사항은 강제 적용 전에 shadow-first로 측정 |

## 다음 단계

| 배우고 싶은 것 | 읽을 문서 |
|----------------|------|
| 트윈이 질의하는 온톨로지 | [llm-strategy-ko.md](../architecture/llm-strategy-ko.md) |
| 답이 거치는 계층과 quality 게이트 | [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2) |
| 리포트가 일반화하는 배포 analyzer | [deployment-preflight-ko.md](../deployment/deployment-preflight-ko.md) |
| 리뷰가 소비하는 탐지 발견 사항 | [observability-and-detection-ko.md](../rules-and-detection/observability-and-detection-ko.md) |
| 서브시스템이 리포에서 있는 위치 | [project-structure-ko.md](../architecture/project-structure-ko.md) |
| 제안이 어떻게 risk-classify되는가 | [risk-classification-ko.md](../decisioning/risk-classification-ko.md) |

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/operations/assurance-twin.md) |
