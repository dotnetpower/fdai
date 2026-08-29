---
title: 모델 기능 수명 주기
translation_of: model-capability-lifecycle.md
translation_source_sha: b85e6bda299ce5a4ee14528917773fec3b7e36ae
translation_revised: 2026-08-29
---
# 모델 기능 수명 주기

이 문서는 시스템이 관리하는 T1 및 T2 모델의 엔드포인트 연결, 기능 선호, 모델 프로비저닝,
런타임 해석, 범위가 제한된 제안자 복구, 수명 주기 조정을 소유합니다. 티어 적격성과 결정론적
품질 게이트는 [LLM 전략](llm-strategy-ko.md)에 유지하고, 표현 전용 선택은
[서술기 라우팅 및 지연 시간](../interfaces/narrator-routing-and-latency-ko.md)에 유지합니다.

## Heterogeneous 엔드포인트 및 게이트웨이 계약

FDAI는 모델 기능, 프로바이더, 경로, wire 프로토콜, authentication, 용량을 서로 분리된
필드로 해석합니다. 따라서 T1/T2 코어 계약을 변경하지 않고 Azure OpenAI direct,
Azure API 관리(APIM)을 경유하는 Azure OpenAI, APIM을 경유하는 OpenAI-compatible
자체 호스팅 GPU 모델을 사용할 수 있습니다.

`resolved-models.json`은 선택적 `endpoint_bindings`를 포함합니다. 검증된 각 연결은 다음을
선언합니다.

- **프로바이더 및 경로:** `azure-openai` 또는 `self-hosted`를 `direct` 또는 `apim-gateway`와
  독립적으로 선언합니다.
- **Wire 프로토콜:** Azure 배포 경로(`azure-openai`) 또는 요청 본문 모델 id를 사용하는
  `/v1` 경로(`openai-v1`)를 선언합니다.
- **Authentication:** Entra 대상 또는 자격 증명 참조를 선언합니다. 현재 런타임 T1/T2
  연결은 Entra를 요구하며 지원되지 않는 auth 종류는 direct 엔드포인트 대체 경로 대신 시작을
  차단합니다.
- **용량:** 하나의 양수 값과 함께 `tpm`, `ptu`, `gpu`를 선언합니다. PTU와 GPU 값은 TPM처럼
  변환하지 않습니다.
- **Feature 및 출처 이력:** 스트리밍, embeddings, 구조화된 출력, 도구 calling, 발견
  출처, resource-reference 다이제스트, 검증 시간을 포함합니다.

엔드포인트 URL과 자격 증명은 운영자 변환 결과에 serialize하지 않습니다. 연결은 opaque
`endpoint_ref`를 저장하고 조립 루트가 protected 배포 구성에서 HTTPS URL로
해석합니다. 해석기가 주입되지 않은 연결은 시작에 실패합니다. 임베딩, 제안자,
기본 및 보조 교차 검증, 비평자, Judge, RCA, 서술기 경로가 같은 request-target 빌더를
사용합니다. `endpoint_bindings`가 없는 이전 방식 파일은 direct Azure OpenAI 경로를 유지합니다.

APIM은 경로 및 거버넌스 경계이며 모델 발행기가 아닙니다. Mixed-model quality 게이트는
게이트웨이 뒤의 발행기와 계열을 계속 비교합니다. 기본과 보조 기능은 같은 APIM
hostname을 사용해도 별도 연결을 유지하며 same-publisher 쌍은 계속 잘못된입니다.

자체 호스팅 엔드포인트는 virtual 네트워크 검사 또는 `/v1/models`만 신뢰해 discover하지 않습니다.
Publisher-keyed domain-separated Ed25519 등록
(`fdai.model-endpoint-registration.v1`)을 통해 후보 집합에 들어옵니다. 잘못된 서명은
parse 전에 차단합니다. 등록된 GPU 모델이 shadow 모드를 벗어나기 전 기능 탐색과 quality
재생이 계속 필요합니다.

프로비저닝된 용량 발견은 Azure 모델 Capacities 관리 API를 사용합니다. 실제 운영 해석기는
regional 카탈로그에서 최신 generally available 모델 버전을 먼저 선택한 뒤 모델 format, 계열,
버전으로 subscription-scoped 용량 엔드포인트를 조회합니다. 응답을 지역 및 프로비저닝된
SKU로 필터하고 범위가 제한된 `management.azure.com` 페이지 나누기만 따라가며 `availableCapacity`를 PTU로
사용합니다. 카탈로그 버전 누락, malformed 응답, 신뢰할 수 없는 next 링크, 서비스 용량 부족은
`hil-only`로 실패 시 차단 처리합니다.

APIM 경로는 `x-fdai-model-backend`, `x-fdai-capacity-unit`, `x-fdai-spillover` 응답 헤더를
반환해야 합니다. T2 제안자 및 교차 검증 클라이언트는 근거가 누락되거나 malformed이면 성공
응답도 거부합니다. 수락된 근거는 영속 model-health 싱크를 통해 민감정보가 제거된 `selected`
전이를 덧붙이기하고 실제 백엔드, TPM/PTU/GPU 단위, spillover 결정, 연결 id를 기록합니다.
엔드포인트 URL, APIM 요청 id, 프로바이더 오류 텍스트는 저장하지 않습니다.

`infra/modules/llm/apim-ai-gateway`의 선택적 Terraform 패키지는 기존 APIM 인스턴스에 하나의
기능을 연결합니다. FDAI 호출자의 Entra 대상을 검증하고 managed 신원으로 APIM을 두
Azure OpenAI 백엔드에 인증하며 첫 요청을 PTU로 보내고 HTTP 429에서 same-family Standard
배포로 정확히 한 번 재시도한 뒤 mandatory 근거 헤더를 발행합니다. APIM 서비스는
생성하지 않습니다. 루트 조립은 모듈을 기본 비활성화된으로 유지하므로 minimum-cost day-zero
인벤토리는 변경되지 않습니다.

`fdai-model-endpoint-discovery`는 protected management-plane 병합 명령입니다. Strict 구성은
예상 Azure OpenAI 계정/배포 및 APIM API/백엔드를 나열하며 엔드포인트 URL 또는 자격 증명
값을 받지 않습니다. Azure 출처는 계정 종류, 배포 준비 상태, 모델 계열/버전,
SKU, TPM/PTU 용량을 검증합니다. APIM 출처는 API, 두 백엔드 id, managed-identity 정책,
HTTP 429 전환, 모든 FDAI 근거 헤더를 검증합니다. 중복 기능 경로는 출력 전에
실패합니다. Command는 검증된 연결을 기존 `resolved-models.json`에 atomic mode-`0600` 쓰기로
병합하고 `--force` 없이 overwrite하지 않습니다.

Signed 자체 호스팅 등록은 injected `Ed25519SignedRegistrationSource`를 통해 같은 출처
집계 경로를 사용합니다. 따라서 raw GPU 엔드포인트는 범용 Azure 발견 구성에 들어가지
않고 발행기 키가 등록 문서 parse 전에 필요합니다.

## 모델 프로비저닝과 라이프사이클

모델 가용성, 버전, 폐기는 지속 shift. 모델 id 하드코딩은 rot 보장. 아래 프로비저닝 모델은
기능→구체-모델 매핑을 **부트스트랩에서 자동, 업데이트 시 리뷰** 로 유지, 다른 어떤 변경
처럼 모델 변경이 shadow-before-enforce 원칙을 통해 흐르도록.

### 기능 선호 레지스트리

상류가 *기능* 와 **기능당 선호 리스트** 정의; 포크가 자체 리전, 컴플라이언스 자세,
비용 목표에 매칭되도록 선호 오버라이드. 레지스트리는 다른 거버넌스 아티팩트처럼 리뷰되는
catalog-as-code(경로 `rule-catalog/llm-registry.yaml`).

```yaml
# rule-catalog/llm-registry.yaml (상류 기본; 포크는 오버라이드 가능)
models:
  t1.embedding:
    preferences:
      - { publisher: OpenAI, family: text-embedding-3-small }
      - { publisher: OpenAI, family: text-embedding-3-large }
    sku: Standard
    capacity_tpm: 100_000
  t1.judge:                       # 소형/저렴 기본 (mini 티어)
    preferences:
      - { publisher: OpenAI, family: gpt-4o-mini }
    capacity_tpm: 40_000
  t2.reasoner.primary:            # 첫 프론티어 reasoner
    preferences:
      - { publisher: OpenAI, family: gpt-4o }
      - { publisher: OpenAI, family: gpt-4.1 }
      - { publisher: OpenAI, family: gpt-4-turbo }
    capacity_tpm: 20_000
  t2.reasoner.secondary:          # mixed-model peer - 별개 publisher여야 함
    preferences:
      - { publisher: Anthropic, family: claude-opus-4 }
      - { publisher: MistralAI, family: mistral-large-2 }
    capacity_tpm: 10_000
  t2.reasoner.escalated:          # Opus-급 천장, on-demand 전용
    preferences:
      - { publisher: OpenAI, family: o1 }
      - { publisher: Anthropic, family: claude-opus-4 }
    invocation: on_disagreement                # 모든 T2 호출에 아님
    capacity_tpm: 5_000
```

레지스트리가 강제하는 규칙(MUST, 구성 로드에서):

- **버전이 아니라 계열.** 선호는 모델 *계열* 를 pin(예: `gpt-4o-mini`); 부트스트랩 해석기
  가 프로비저닝 시점에 최신 안정 버전 선택하고 resolved 매핑에 기록. 레지스트리에 절대 dated
  버전 pin 안 함 - 폐기를 숨김.
- **용량 단위는 명시적입니다.** Standard 및 Global Standard는 `capacity_tpm`을 요청 천장으로
  사용합니다. Azure 사용량 `Count`는 1K TPM 단위에서 변환하며 배치 및 fine-tune 할당량은 제외합니다.
  `ProvisionedManaged`, `GlobalProvisionedManaged`, `DataZoneProvisionedManaged`는 `capacity_ptu`를 사용합니다.
  프로비저닝된 SKU에 TPM을 공급하거나 standard SKU에 PTU를 공급하면 잘못된이며 초과분은 HIL로 강등됩니다.
- **Escalated 기능은 호출별 명시적 선택** (`invocation: on_disagreement`); 모든 T2
  요청에 호출되지 않고 절대 quality 게이트를 우회하지 않음.
- **RCA reasoner는 호출별 명시적 선택** (`invocation: on_novel_case`, 기능
  `t2.rca`); 결정론적 계층이 해결하지 못한 novel 인시던트에만 발화하며, 제공된 근거에
  근거에 기반한 되지 않으면 그 출력은 거부됨 (observability-and-detection.md 섹션 4 참조).
- **도구 기능은 독립적으로 해석합니다.** `tool_calling_required`는 일반 함수
  도구를 게이트합니다. 공개 수집은 전용 `t1.web_search` 선호 설정을 사용하며 해당
  배포만 `web_search_candidates`로 serialize합니다. Protected 적용은 정확한 도메인
  허용 목록으로 Foundry 프롬프트 에이전트를 조정하고 Operator API는 시작에 실제 managed-tool
  요청을 전송합니다. 모델, project, 에이전트, 권한 또는 도구 준비 상태가 없으면 서술기
  풀을 빌리지 않고 검색만 사용 불가로 전환합니다. 대화 권한은 바뀌지 않습니다.

### 부트스트랩 Provisioner

`azd up` (또는 등가) 에서 해석기가 레지스트리를 읽고 대상 리전의 Azure OpenAI / Foundry 카탈로그를 쿼리하여 **구체 기능당 하나의 배포** 를 프로비저닝합니다. 가상 `t1.vision`은
별도 배포를 만들지 않고 일치하는 서술기 배포를 재사용합니다. Resolved `{기능 →
배포}` 매핑이 Key Vault에 기록되고 감사됨.

보호된 `deploy_core_model_quorum` 모드는 누락된 코어 쌍을 복구하는 범위가 제한된 경로입니다.
계획은 상위 계정 신원 1건의 현재 위치 업데이트를 허용하고 `t1.judge`와
`t2.reasoner.primary`를 정확히 생성해야 합니다. 범위 검사는 누락, 추가, 교체 또는 관련 없는
리소스 변경을 차단합니다. 계획은 Terraform 상태 밖에 이미 존재하는 정확한 이름의 배포를 먼저
채택하며, 채택 후에는 빈 계획을 수렴 결과로 허용합니다. 채택한 primary가 정확한 기존 `gpt-4o`
프로필이면 해석기가 선택한 계열, 버전, SKU 및 용량으로 한 번 교체할 수 있으며 적용 전에 모든
필드를 확인합니다. 정확한 적용은 봉인된 계획만 소비하며 ActionType, Workflow 또는 자율성
모드를 승격하지 않습니다.

배포자가 `Cognitive Services Contributor` 를 갖지 않을 때, 선호 계열이 리전에 없을 때,
`capacity_tpm` 쿼터가 부족할 때, mixed-model 불변식을 만족할 수 없을 때의 **배포자-권한 게이트
전체 표** 는
[dev-and-deploy-parity-ko.md § 배포자-스코프 LLM 프로비저닝](../deployment/dev-and-deploy-parity-ko.md#배포자-스코프-llm-프로비저닝)
에서 저술; 이 섹션은 happy-path 형태만 보여줌.

![부트스트랩 Provisioner. 주요 단계는 Terraform / Bicep: azd up, Azure OpenAI or Foundry resource, resolver, llm-registry.yaml, query catalog: / available families + versions in region, for each capability: / first preference available, capability를 hil-only로 표시 / completeness impact 보고, create deployment / with TPM or PTU capacity, verify mixed-model invariant: / primary.publisher ≠ secondary.publisher, FAIL, write resolved-models.json to Key Vault / + audit entry입니다.](../../diagrams/generated/fdai-roadmap-architecture-llm-strategy-02.ko.svg)

**부트스트랩 불변식 (MUST)**
- 누락된 역할, 선호 계열 부재, zero 할당량 같은 환경 실패는 영향을 받은 기능을
  `hil-only`로 표시하고 계속합니다. 프로비저닝 평가가 이 성능 저하를 표시하며
  배포는 `--assess-fail-on critical`로 차단하도록 선택할 수 있습니다.
- 두 T2 reasoner가 명시적 `hil-only` 모드 밖에서 모두 해석되면
  `t2.reasoner.primary.publisher`와 `t2.reasoner.secondary.publisher`는 달라야 합니다.
  Same-publisher 쌍은 hard 해석기 오류입니다.
- Resolved 매핑은 기능당 `{deployment, family, version, publisher}` 를 기록하여 감사
  로그가 어떤 케이스를 결정한 정확한 모델을 이름 지을 수 있음.

### 프로비저닝 완결성 게이트

해석기는 프로비저닝 불가능한 기능을 `hil-only`로 강등시키고 계속한다 -
하나의 누락된 계열 때문에 전체 부트스트랩을 막지 않으므로 **부분 배포가
조용하다**: `resolved-models.json`이 T1 쌍 + `t2.reasoner.primary`만 담고 있는데
레지스트리는 보조 reasoner, 비평자, RCA reasoner, 에스컬레이션 상한까지
선언할 수 있다. 그러면 조립 루트는 조용히 forced-disagree 교차 검증으로
대체 경로 하고 모든 T2 케이스가 HIL로 라우팅되며, reasoning 계층이 사실상 꺼졌다는
신호가 배포 시점에 없다.

[`assess_provisioning`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/provisioning_assessment.py)
이 그 공백을 닫는다. 권위 `llm-registry.yaml`(의도)과 `resolved-models.json`(실제)
을 비교해 결정론적 `ProvisioningReport`를 반환한다:

- 선언된 각 기능을 `resolved` / `capacity-reduced` / `hil-only` / `missing`
  으로 분류하고 `core` / `quorum` / `optional`로 태깅하며, 부재 시 런타임 영향을 명시;
- `quorum_ok`는 mixed-model T2 교차 검증이 형성 가능한지(두 reasoner 가용 + 다른
  발행기) 보고 - `hil-only` 모드에서는 기대하지 않음;
- `ProvisioningSeverity`가 `ok`(전부 resolved), `degraded`(선택적 기능만
  누락 - 토론 / RCA / 에스컬레이션 / 평가 기준 off는 허용), `critical`(코어 기능
  누락 또는 정족수 미형성 - T2가 사실상 off)로 롤업.

배포 파이프라인은 심각도로 게이팅하고 리포트를 감사 로그에 기록(`critical` 시 A2
운영 알림)하므로, 반쪽만 프로비저닝된 reasoning 계층이 런타임 HIL storm으로 숨지
않고 `azd up` 시점에 보인다.

부트스트랩 CLI가 이를 직접 노출한다: `fdai-llm-resolver --assess-fail-on critical`
은 평가를 stderr에 출력(`critical` 시 `A2 alert:` 라인)하고 non-zero로 종료하므로,
CI 배포 단계가 모든 T2 케이스를 조용히 HIL로 보내는 reasoning 계층을 배포하기 전에
차단한다. 기본값 `--assess-fail-on none`은 하위호환을 위해 report-only로 유지된다.

### 런타임 해석

코어 코드는 기능 계약에만 의존. `resolved-models.json` 은 시작 시 Key Vault에서 로드;
stale 참조(배포 삭제 또는 404) 는 다른 기능이 아니라 **HIL로 fail-close**.

```python
# core/tiers/t2-reasoning/reasoner.py (illustrative)
primary   = client.for_capability("t2.reasoner.primary")
secondary = client.for_capability("t2.reasoner.secondary")
cand_a = primary.chat(...)
cand_b = secondary.chat(...)
if not agree(cand_a, cand_b):
    escalated = client.for_capability("t2.reasoner.escalated")   # cost-capped
    return arbitrate(cand_a, cand_b, escalated.chat(...))
return quorum_result(cand_a, cand_b)
```

- `core/` 에 모델 id가 나타나지 않음.
- 누락 배포는 장애로 취급: 요청은 HIL로 라우팅되고 운영 알림 발행(A2, [channels-and-notifications-ko.md](../interfaces/channels-and-notifications-ko.md#3-categories-a1a4)
  에 따라). 다른 기능로의 조용한 스위치는 금지.

### 에스컬레이션 단계 구조 정책

위의 `if not agree(...): escalated = ...` 스텝은 하드코딩된 분기가 아니라
**정책 결정**이다. [`core/quality_gate/escalation_ladder.py`](../../../services/core-control-plane/src/fdai/core/quality_gate/escalation_ladder.py)
(`decide_escalation`)에 순수·결정론 함수로 구현되며, 형제
[`debate_router`](../../../services/core-control-plane/src/fdai/core/quality_gate/debate_router.py)를 그대로
미러링한다: 고정된 `EscalationLadderConfig` + "더 강한 모델로 올라갈까,
멈추고 HIL로 라우팅할까?"에 답하는 stateless 함수. 정책을 먼저 단독으로 -
라이브 배선 전에 테스트·감사 가능하게 - 출하하는 것은 debate-router
delta-2a -> delta-2b 순서를 따른다. `QualityGate`는 `EscalationLadderConfig`가
배선되면 결정을 **shadow**(`QualityDecision.escalation_route` /
`escalation_reason`, 그리고 읽은 `self_consistency` stability,
`quality_decision_audit_fields`로 표면화)로 기록한다 - 측정만 하고 행동은 안 함;
escalated 모델을 실제 호출하는 것은 다음 강제 적용 스텝. `on_self_consistency_below`
트리거는 조립 루트의 self-consistency cascade가 후보에 얹은
`action_stability` 신호를 읽는다 - 게이트는 모델을 직접 샘플링하지 않는다(샘플러의
"cascade 트리거는 조립 관심사" 계약).

어떤 트리거도 단계 구조를 오르기 전에 검증된 온톨로지, 룰 또는 deterministic-evidence 개선의 trusted
개수가 필요합니다. 기본 최소는 10입니다. 개수는 모델 후보가 아니라 orchestration에서 오며,
개수와 구성된 최소 모두 `escalation_metadata`에 기록됩니다. 개수가 없으면 0으로 기본 설정되어
`ontology_improvement_budget_remaining`으로 안전하게 중단됩니다. 영속 case-history orchestration이
개수를 공급하고 별도 승격이 호출을 활성화할 때까지 shadow 관측으로 유지됩니다.

단계 구조 rung(`EscalationTier`)은 레지스트리 기능과 일대일:
`PRIMARY` -> `SECONDARY` -> `ESCALATED`. `decide_escalation`은 `ESCALATE`
(다음 더 강한 reasoner를 tiebreaker로 소비) 또는 `STOP`(호출자가 미해결 케이스를
HIL로 라우팅)을 반환하며, 다음 하드닝 불변식을 지킨다:

- **단계 구조는 실행 자격을 절대 부여하지 않는다.** *더 강한 모델을 쓸지*만
  결정한다. escalated 모델의 제안도 신뢰할 수 없는 이며 같은 quality 게이트(검증기 +
  grounding + 정족수)로 재진입한다; disagreement는 단계 구조를 오른다고 auto-resolve
  되지 않으며 - 결정론 검증기가 유일한 권위로 남는다.
- **실패 시 차단.** `escalated_available=False`(`t2.reasoner.escalated`를 해석
  하지 않은 포크)는 `STOP`을 반환하며, precedence에서 deny-list보다 위.
- **Cost-bounded.** 한 번의 호출은 최대 한 rung만 오르고 `ESCALATED` 천장을
  넘지 않는다; `enabled=False`는 비용 spike용 killswitch.
- **Ontology-first.** 구성된 트리거가 있어도 trusted validated-improvement 개수가
  `minimum_ontology_improvement_attempts`에 도달하기 전에는 중단됩니다.
- **Triggers.** `cross_check_disagreement`(주 트리거, 레지스트리의
  `invocation: on_disagreement` 반영) + 선택적 `on_self_consistency_below`
  임계값(self-consistency 샘플러가 흔들리는 제안자를 보고하면 nominal agreement
  에서도 escalate). ActionType별 `never`/`always` 리스트로 튜닝하며 거부가 allow
  우선.

Resolved 모델 계열은 배포 별칭과 별도로 각 T2 어댑터에 전달됩니다. GPT-5 및 o-series
채팅 계열은 `max_completion_tokens`를 보내고 custom `temperature`를 생략합니다. Classic 채팅
계열은 `max_tokens`와 `temperature`를 유지합니다. 이 규칙은 기본 latency-pool 구성원을 포함한
RCA, 제안자 및 교차 검증 요청에 동일하게 적용되므로 friendly 배포 별칭이 잘못된 wire
필드를 선택할 수 없습니다.

### Narrator 라우팅 및 지연 시간

Narrator 배포 선택, 멀티모달 탐색, 사용자별 선호 설정, TTFT, 웹 검색 풀 및 런타임
전달 결정은 [Narrator 라우팅 and 지연 시간](../interfaces/narrator-routing-and-latency-ko.md)가
소유합니다. T2 quality-gate 배정은 system-governed 상태를 유지하며 same-publisher T2 기본
예외는 아래에 이어집니다.

### T2 기본 라우팅 및 통제된 복구

T2는 서로 다른 두 복구 범위를 사용합니다. 호출별 지연 시간 라우팅은
`t2.reasoner.primary` 슬롯 안의 배포 중 하나를 선택합니다. 요청 간 제안자 복구는 통제된 액션
파이프라인을 통해서만 선호하는 등록 제안자 경로를 바꿉니다. 어느 범위도 모델 출력에 권한을
부여하거나 mixed-model quality 게이트를 약화하지 않습니다.

- **동일 발행기 지연 시간 풀:** 모든 primary 풀 배포는 하나의 발행기를 공유하고, 그 발행기는
  `t2.reasoner.secondary`와 달라야 합니다. 지연 시간 라우팅은 primary 슬롯에만 적용되고,
  secondary 교차 검사, Critic, Judge 및 에스컬레이션 단계는 고정된 역할을 유지합니다. 리졸버는
  발행기가 섞인 풀을 거부합니다. `llm.t2_primary_latency_routing`은 기본값이 `true`이며 후보가
  두 개 이상일 때만 활성화되고, 후보가 하나이면 해당 primary를 그대로 사용합니다.
- **범위가 제한된 호출 내 선택:** 라우터는 선택한 배포를 기록하고, 프로바이더 오류 텍스트 없이
  실패를 분류하며, 범위가 제한된 cooldown을 적용하고, 남은 동일 발행기 배포를 각각 최대 한 번
  시도합니다. 교차 검사의 secondary를 지연 시간 primary로 대체하지 않습니다.
  `ModelHealthTransitionSink`는 선택, 비정상 및 복구된 배포 상태를 영속화합니다. 이 기록의 실패는
  실패한 모델 호출을 성공으로 바꾸거나 이미 성공한 제안을 차단하지 않습니다.
- **예산이 적용된 제안자 대체 경로:** `BoundedFailoverT2Proposer`는 실제 호출 전에 공유 T2 예산을
  예약하고 등록된 `primary` 및 `secondary` 제안자 경로를 각각 최대 한 번 시도합니다. 모든 후보는
  신뢰할 수 없는 상태로 같은 검증기, 근거 확인, 교차 검사 및 리스크 게이트에 다시 들어갑니다.
  예산 소진이나 전체 후보 실패는 더 약한 판단을 반환하지 않습니다.
- **영속 근거:** 각 시도는 경로 역할, 시도 번호, 상태, 실패 등급, 최종 상태 및 복구 상태를 담되
  끝점이나 예외 텍스트는 제외한 `T2AttemptReceipt`를 발행합니다. 런타임은 Huginn 유입 전에 증적과
  감사 항목을 저장하고, 전달되지 않은 증적을 다시 보내며, 프로바이더 호출을 재생하지 않고 범위가
  제한된 이전 실패를 구체화할 수 있습니다.
- **통제된 경로 변경:** 복구 증적은 정보로만 남습니다. 최종 후보 소진만 Heimdall 이상과 Forseti의
  `ops.switch-t2-proposer-route` `hil` 결정이 됩니다. Var가 승인을 운반하고, Thor가 멱등 CAS 경로
  변경을 수행하며, Saga가 감사 체인을 보존하고, Vidar가 실패한 상관관계의 변경만 복원합니다.
  오래된 롤백은 더 최신 경로 개정을 덮어쓸 수 없습니다. ActionType은 shadow 우선이며 강제 적용된
  전환 전에 사람 승인이 필요합니다.
- **읽기 전용 가시성:** 경로 상태와 증적은 재시작 후에도 유지됩니다. Operator 변환 결과는 모델
  상태와 민감정보가 제거된 복구 상세를 표시할 수 있지만 경로 변경, cooldown 해제, 승인 또는
  배포 승격을 수행할 수 없습니다.

조립은 구성된 제안자가 해당 프로토콜을 노출할 때만 관측기와 선택기를 연결합니다. 그렇지 않으면
기존 단일 경로 동작을 유지합니다.

### 조정기 작업

계획된 주간 작업은 더 선호되는 새 계열, 60일 안의 사용 중단, 측정된 용량 또는 품질 표류를 감시합니다. 범위가 제한된 이슈 또는 초안 PR과 A2 알림만 만들며 실제 매핑을 바꾸지 않습니다.
제안 스키마 v2는 모델 계열, 발행자, 상태뿐 아니라 SKU와 유효 용량 단위/값도 비교하므로 제자리 확장이나 교체를 변경 없음으로 잘못 분류하지 않습니다.
병합되지 않은 교체가 만료되면 기능을 사람 검토로 낮추고, 승인된 레지스트리 변경도 Owner 검토와 고정 시나리오 shadow 재현을 통과해야 합니다.

### Mixed-Model 계열 전략

Quality 게이트는 두 독립 모델 계열 필요. 포크가 실제로 얻는 쌍은 부트스트랩 시점 선택:

| 모드 | 보조 위치 | 언제 선택 |
|------|--------------|-----------|
| `azure-foundry` (기본) | Azure AI Foundry 모델 카탈로그를 통해 서비스되는 Anthropic / Mistral / Cohere 모델 | 리전과 컴플라이언스가 비-OpenAI Foundry 모델 허용; 단일 청구 표면 |
| `external` | 직접 서드파티 엔드포인트를 통한 보조(Anthropic API 등) | 필요 계열이 리전의 Foundry에서 이용 불가 |
| `hil-only` | 보조 프로비저닝 안 됨; 모든 T2 케이스가 HIL로 라우팅 | 포크가 두 번째 계열을 얻을 수 없음(일시); 명시적 명시적 선택 |

선택된 모드는 구성 값 (`llm.mixed_model_mode`); 부트스트랩 해석기가 이를 읽고 그에 따라
불변식 강제. 나중에 모드 스위치는 런타임 토글이 아니라 거버넌스 PR.

### 포크 vs 상류 분리

상류는 기능 이름, 스키마, 기본 선호, resolver 행동, mixed-model 불변식 및 범용 Azure IaC를
소유합니다. 포크는 지원되는 구성과 DI 경계로 지역, compliance, 비용, 일정, 알림, 리소스 및
해석된 모델 값을 제공합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 티어 경계 및 품질 게이트 | [LLM 전략](llm-strategy-ko.md) |
| 표현 전용 모델 선택 | [서술기 라우팅 및 지연 시간](../interfaces/narrator-routing-and-latency-ko.md) |
| 배포 프로비저닝 제약 | [개발 및 배포 동등성](../deployment/dev-and-deploy-parity-ko.md) |
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/architecture/model-capability-lifecycle.md) |
