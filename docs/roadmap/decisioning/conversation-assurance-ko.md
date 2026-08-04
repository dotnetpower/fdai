---
translation_of: conversation-assurance.md
translation_source_sha: 4f3ea9d8175252607c3e8b915160d48b73deaa0a
translation_revised: 2026-08-04
---
# 대화 품질 보증

대화 품질 보증은 응답 경로 밖에서 완료된 답변을 평가하고 클라우드 실행 권한을 부여하지 않은
채 채팅 전용 정책을 개선합니다. 결정론적 검사, 독립 모델 계열, 제한된 토론, 블라인드 재실행,
자동 승격 및 자동 롤백을 결합합니다.

> FDAI는 각 구독에서 검증된 사용 근거가 쌓일수록 답변 정확도를 개선할 수 있지만, 이는 보장이
> 아니라 측정 결과입니다. 동일한 고정 시나리오 세트에서 통계적으로 뒷받침되는 향상과 하드
> 안전성 이탈 0건을 확인해야 승격할 수 있습니다.

## 설계 요약

Bragi는 최종 turn을 저장합니다. Norns는 응답 경로 밖에서 이를 평가하고, Saga는 각 평가와
정책 전환을 기록하며, Mimir는 고정 루브릭을 관리합니다. 이 루프는 RBAC, 승인, 위험, 정책,
agent 역할 또는 executor 권한을 변경할 수 없습니다.

```mermaid
flowchart LR
    TURN[최종 turn] --> CHECK[결정론적 검사]
    CHECK -->|판정 가능| LEDGER[평가 원장]
    CHECK -->|의미 평가| A[독립 평가자 A]
    CHECK -->|의미 평가| B[독립 평가자 B]
    A --> REDUCE[결정론적 reducer]
    B --> REDUCE
    REDUCE -->|불일치| TIE[독립 중재자]
    TIE --> LEDGER
    LEDGER --> CLUSTER[Norns 실패 군집화]
    CLUSTER --> CANDIDATE[제한된 정책 후보]
    CANDIDATE --> REPLAY[블라인드 이중 언어 재실행]
    REPLAY --> SHADOW[shadow 및 canary]
    SHADOW -->|보호 지표 통과| PROMOTE[자동 승격]
    SHADOW -->|회귀| ROLLBACK[자동 롤백]
    HUMAN[운영자 이의 제기] --> LEDGER
```

## 구독마다 학습 결과가 다른 이유

구독은 리소스 구성, 명명 규칙, 토폴로지, 텔레메트리 범위, 운영 절차, 장애 빈도 및 근거 지연이
서로 다릅니다. 전역 사전 분포는 시작 시 유용하지만 모든 배포 환경을 같은 수준으로 표현할 수
없습니다. FDAI는 고객 값을 리포지토리 외부에 유지하고 배포 소유의 principal 범위 근거에서만
학습합니다.

구독 `s`의 평가 기준 `k`에는 검증된 결과에 대한 beta-binomial 사후 분포를 사용합니다.

$$
p_{s,k} \mid D_{s,k} \sim \operatorname{Beta}(\alpha_{0,k}+c_{s,k},\;\beta_{0,k}+n_{s,k}-c_{s,k})
$$

여기서 `n`은 평가 가능한 결과 수이고 `c`는 검증된 정답 수입니다. 사후 평균은 다음과 같습니다.

$$
\hat p_{s,k}=\frac{\alpha_{0,k}+c_{s,k}}{\alpha_{0,k}+\beta_{0,k}+n_{s,k}}
$$

전역 사전 분포는 근거가 적은 구독의 과적합을 제한합니다. 검증된 로컬 근거가 늘어나면 사후
분산이 줄고 로컬 추정치의 비중이 커집니다. 따라서 FDAI는 해당 환경에서 잘 작동한 근거 소스,
route 및 응답 정책을 학습할 수 있습니다. 블라인드 재실행과 canary 보호 지표를 통과한 변경만
유지합니다.

예상 오류 곡선은 다음과 같이 모델링하지만 보장하지는 않습니다.

$$
E_s(n)=E_{s,\infty}+(E_{s,0}-E_{s,\infty})e^{-\lambda_s n}
$$

`lambda_s`는 관측 구간에서 추정합니다. 신뢰 구간이 향상을 보여주지 않으면 FDAI는 측정된
개선이 없다고 보고하고 기존 정책을 유지합니다.

## 평가 계약

각 평가는 제한된 메타데이터, content digest, 모델 식별자, 기준별 점수, 근거 참조, 비용 및
생명주기 상태를 저장합니다. 제한 없는 대화 본문, 숨은 reasoning 또는 도구 출력을 복제하지
않습니다.

Terminal intake는 exact verification reason, route id, evidence-manifest completeness, ontology
release 및 graph revision이 있으면 함께 보존합니다. Deterministic assessment는 모든 unverified
답변을 하나의 generic class로 축약하지 않고 failure signature에 exact reason을 포함합니다. 따라서
provider, context, routing, rendering, policy, rule, ontology, Dynamic failure가 서로의 recurrence
floor를 충족하지 않습니다.

Ontology-owned failure는 별도 `OntologyAdequacyReview`를 열 수 있습니다. 첫 runtime slice는
hold-first입니다. StateStore에 idempotent shadow review를 기록하지만 replay success를 주장하거나
catalog proposal을 만들지 않습니다. Complete evidence, verified routing, resolved identity, exact
release 및 graph revision, deterministic reproduction이 모두 있을 때만 review가 ready가 됩니다.
Provider, context, rendering, policy failure는 ontology review를 만들지 않습니다. Ready review는
provider mapping, projection binding, ontology declaration, rule candidate 또는 Dynamic model review 중
가장 작은 owning artifact만 추천할 수 있습니다.

### 하드 검사

하드 검사는 모델 호출 없이 완료된 모든 답변에 적용됩니다.

- **무결성**: 답변 형식이 올바르고 크기 제한 안에 있습니다.
- **근거 확인**: 인용 근거가 존재하고 원자적 주장이 지원됩니다.
- **범위**: 구독, 리소스 및 대화 범위가 서버 소유 컨텍스트와 일치합니다.
- **권한**: 답변 agent와 근거 provider가 주장한 도메인을 소유합니다.
- **안전성**: 답변이 실행, 승인 또는 정책 권한을 부여하지 않습니다.
- **최신성**: 시간에 민감한 근거가 주장에 충분히 최신입니다.

하드 검사 실패는 `fail`입니다. 근거 부족은 `inconclusive`이며 통과로 바뀌지 않습니다.

### 의미 루브릭

하드 검사로 판정할 수 없는 turn만 의미 평가로 이동합니다. 서로 다른 두 모델 계열이 다음 고정
기준을 `0`부터 `4`까지 평가합니다.

| 기준 | 의미 | 가중치 |
|------|------|-------:|
| `factual_correctness` | 주장이 제공된 근거 및 참조 사실과 일치합니다. | 4 |
| `intent_resolution` | 답변이 운영자 요청을 직접 해결합니다. | 3 |
| `completeness` | 필요한 제약, 주의 사항 및 다음 단계가 포함됩니다. | 2 |
| `calibration` | 불확실성과 판단 보류가 근거 가용성과 일치합니다. | 3 |
| `actionability` | 적절할 때 안전하고 사용할 수 있는 다음 단계를 제공합니다. | 2 |
| `clarity` | 요청 언어에서 일관되고 자연스럽습니다. | 1 |

정규화된 콘텐츠 점수는 다음과 같습니다.

$$
Q=100\frac{\sum_k w_k s_k}{4\sum_k w_k}
$$

reducer는 `pass`, `fail`, `inconclusive`를 `Q`와 별도로 저장합니다. 높은 평균이 하드 실패를
숨길 수 없습니다.

고정된 blind scenario는 평가자에게 제한된 trusted reference fact를 제공합니다. 이 fact는
transient trial input이며 assessment ledger에 복사되지 않습니다. 일반 운영자 turn에는 benchmark
reference fact가 없습니다.

## 독립 모델 평가

평가자 A와 평가자 B는 독립적으로 실행되며 서로의 결과를 읽을 수 없습니다. 모델 식별자와
계열은 서로 달라야 하며 답변 생성 모델은 자기 답변을 평가할 수 없습니다. 모든 의미 점수는
제공된 allowlist의 근거를 인용합니다.

reducer는 판정이 같고 모든 기준 점수 차이가 1점 이하일 때 직접 합의로 수락합니다. 그렇지
않으면 평가자는 불일치한 기준에 한정해 한 번만 반론합니다. 서로 다른 세 번째 계열이 한 번
중재할 수 있습니다. 남은 불일치는 `inconclusive`가 됩니다.

모델 출력은 감점 방향으로만 작동합니다. 결함을 찾거나 turn을 보류할 수 있지만 결정론적
실패를 무시하거나, 근거를 만들거나, 임계값을 변경하거나, 실행 권한을 부여할 수 없습니다.

## 비용 인식 cascade

평가기는 충분한 단계 중 가장 저렴한 단계를 사용합니다.

1. 질문, 답변, 근거 manifest, 루브릭 및 모델 세트 digest가 같으면 캐시 평가를 재사용합니다.
2. 모든 새 turn에 하드 검사를 실행합니다.
3. 미결 turn과 제한된 결정론 통과 대조 표본에만 두 독립 경량 평가자를 실행합니다.
4. 불일치한 경우에만 반론과 중재자를 실행합니다.

최적화 목적은 다음과 같습니다.

$$
\min_{\pi}\; C_{\text{eval}}(\pi)+\eta C_{\text{error}}(\pi)
$$

하드 안전성 이탈 0건, 일별 micro-USD 상한, turn당 최대 세 번의 모델 호출 및 구성된 지연
제한을 제약으로 둡니다. 예산 소진은 평가를 연기하며 보호 지표를 약화하지 않습니다.
각 호출 전에 reviewer는 선택된 평가자 중 가장 높은 구성된 호출별 상한을 예약합니다. provider가
측정된 token 사용량을 반환하면 adapter는 공유 pricing catalog에서 `cost_microusd`를 계산하고 같은
호출을 durable metering stream에 기록합니다. catalog 가격이 없는 평가자는 보수적으로 전체 상한을
사용하며, 답변 모델이 primary, secondary 또는 tie-breaker 역할에 있으면 평가 호출 전에 거부합니다.

## 자율 개선 생명주기

Norns는 구독에 안전한 feature digest, 실패 기준, route, authority, locale 및 근거 상태를
기준으로 반복 실패를 그룹화합니다. 원시 고객 식별자는 군집 키가 아닙니다. 군집이 구성된 지원
수와 반복 횟수 하한에 도달해야 제한된 후보 하나를 만들 수 있습니다.
privacy-preserving `principal_scope`는 cluster key와 signature digest에 모두 참여하며, 서로 다른
scope의 sample은 지원 하한을 충족하기 위해 합산되지 않습니다.

후보는 narrator prompt pack, glossary, 읽기 전용 route, 근거 선택, 응답 렌더링, locale 표현,
narrator 모델 순서를 변경할 수 있습니다. 루브릭, benchmark label, evaluator prompt, 근거
verifier, RBAC, 위험 정책, agent 역할, 승인 규칙 또는 executor 동작은 변경할 수 없습니다.
각 candidate는 stage를 제외하면 해당 `principal_scope` 안에서 immutable입니다. durable ledger는
candidate content를 멱등하게 추가하고, `from_stage`가 저장된 stage와 일치할 때만 transition을
적용하며 append-only transition history를 기록합니다. 이미 적용된 transition 재생은 no-op이고,
stale 또는 cross-scope transition은 거부됩니다.
실행 가능한 candidate는 SHA-256 digest가 `policy_digest`와 정확히 일치하는 제한된 typed
artifact도 포함합니다. legacy digest-only candidate는 audit을 위해 읽을 수 있지만 shadow를
벗어나거나 runtime registry에 들어갈 수 없습니다.
lifecycle coordinator는 scoped cluster, target 및 policy digest에서 stable candidate identity를
계산합니다. injected proposer는 이 제한된 identity만 반환할 수 있고, injected blind trial
measurer는 모든 promotion metric을 제공합니다. stage 변경 시 publisher가 candidate를 먼저 적용하고
ledger가 transition을 두 번째로 commit합니다. persistence가 실패하면 error를 전달하기 전에
publisher가 incumbent를 복원합니다. persistence와 restore가 모두 실패하면 terminal error는
원래 store 실패를 숨기지 않고 복구에 필요한 두 원인을 모두 보존합니다. proposal, measurement
또는 publisher 근거가 없으면 candidate는 shadow에 남습니다.
배포된 lifecycle은 narrator backend, catalog pricing, PostgreSQL store 및 서로 다른 evaluator
family 두 개 이상을 모두 사용할 수 있을 때만 활성화됩니다. 부분 배포는 assessment-only로 남아
semantic review를 `inconclusive`로 보고하며 단일 모델이나 비용 0으로 대체하지 않습니다. 현재
resolved local profile도 secondary reasoner가 `hil-only`이면 이 hold 동작을 따릅니다.

### 블라인드 승격과 롤백

각 후보는 원래 실패 질문, 실패당 최소 세 개의 paraphrase, 고정된 영어 및 한국어 benchmark,
숨겨진 holdout에서 실행됩니다. 이후 shadow, 트래픽 1 percent, 5 percent, 25 percent, 100
percent 단계를 진행합니다.

각 단계에는 관측 중인 단계에 결속된 새로운 측정 기간이 필요합니다. stage `r`의 candidate
`c`에 대해 trial은 `observed_stage = r`과 시나리오 세트 버전, holdout 버전, 입력 cohort, 정책
버전 및 관측 기간에 대한 stable evidence digest `d(M_r)`을 보고합니다. transition ledger는
candidate lifecycle 전체에서 각 `(c, d(M_r))`을 최대 한 번만 소비합니다.

$$
r_{next}>r \Longrightarrow d(M_{r_{next}}) \ne d(M_r)
$$

stage 불일치, 이미 소비된 digest 또는 누락된 측정 identity는 진행을 차단합니다. 반복 intake는
기록된 transition을 재생할 수 있지만 하나의 shadow 또는 canary 결과를 재사용해 이후 트래픽
단계를 진행할 수 없습니다.

별도의 durable runtime registry가 각 `(principal_scope, target)`에 현재 적용된 artifact를
소유합니다. canary assignment는 server-owned principal, turn identity 및 candidate identity를
hash하므로 retry도 고객 식별자를 artifact에 저장하지 않고 동일한 variant를 선택합니다. 각
publish는 immutable before 및 after snapshot을 기록합니다. restore는 restart 후 before snapshot을
재생하고, rollback은 candidate에 기록된 incumbent digest를 선택하거나 incumbent가 built-in base
policy이면 overlay를 제거합니다.

자동 승격에는 다음 조건이 필요합니다.

$$
\operatorname{LCB}_{95}(Q_{candidate}-Q_{incumbent})>\delta,
\quad C_{verified,candidate}\le C_{verified,incumbent},
\quad H=0
$$

`H`는 하드 실패 이탈 수입니다. 하드 이탈, 0보다 낮은 신뢰 하한, 비용 또는 지연 회귀, locale
격차 또는 불일치 증가가 있으면 이전 immutable 정책을 자동 복원합니다.

## 운영자 이의 제기 화면

Conversation Assurance 콘솔은 읽기 중심입니다. 인증된 운영자는 잘못된 사실, 의도 누락,
오래된 근거, 잘못된 범위, 부적절한 판단 보류 또는 언어 품질을 보고할 수 있습니다. 보고는
append-only 이의 제기 이벤트이며 승인이나 직접 정책 편집이 아닙니다.
멱등 재시도는 제한된 projection 목록 대신 ledger 단건 조회를 통해 최초 timestamp를 포함한
원래 principal-scoped dispute record를 반환합니다.

검증된 이의 제기는 회귀 corpus에 들어가며 롤백을 촉발할 수 있습니다. 지원되지 않은 보고는
품질 label을 바꾸지 않고 미해결 상태로 표시합니다.

## 개인정보 보호 및 실패 동작

- 평가 레코드는 principal 및 배포 범위로 분할됩니다.
- 근거 참조는 최종 turn의 evidence manifest에 속해야 합니다.
- 모델 독립성 부족, 잘못된 점수, 알 수 없는 기준 또는 지원되지 않는 근거는 `inconclusive`입니다.
- 큐 또는 예산 소진은 `deferred`를 기록하고 제한된 정책에서 재시도합니다.
- intake capacity 거부, delegate 거부 및 최종 평가 실패는 이미 저장된 답변을 변경하지 않고
    structured warning을 기록합니다.
- 저장소 실패 시 활성 정책을 변경하지 않습니다.
- 다음 버전이 완전히 승격될 때까지 이전 immutable 정책을 유지합니다.

## 측정

구독에 안전한 범위, intent, agent, locale, 정책 버전, 루브릭 버전 및 측정 기간별로 하드
실패율, 검증 정답률, 적절한 판단 보류율, 불일치율, 이의 제기 정밀도, 검증 답변당 비용, p50 및
p95 지연, 승격 및 롤백을 보고합니다.

영어와 한국어에는 같은 시나리오 intent와 임계값을 적용합니다. 구성된 신뢰 구간 밖의 locale
격차는 승격을 차단합니다.

Manual 및 browser campaign run은 `scripts/quality/conversation-assurance-ledger.py`를 통해 QID,
variant 및 fresh 또는 positive mode별 bounded local JSONL result 하나를 append합니다. 각 record는
expected 및 actual authority, status, optional reason, check, model-call count, commit 및 timezone-aware
timestamp를 저장합니다. `passed`와 `unexpected_unverified`를 derive하고 prompt 또는 environment
identifier는 저장하지 않으며 symlink output을 거부하고 ignored output file을 mode `0600`으로 유지합니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 기존 post-turn 학습 | [Post-Turn Improvement Review](post-turn-improvement-review-ko.md) |
| 감점 전용 모델 점수 | [Hallucination Rubric Gate](hallucination-rubric-gate-ko.md) |
| 운영자 화면 경계 | [Operator Console](../interfaces/operator-console-ko.md) |
| baseline 및 신뢰 구간 | [Goals and Metrics](../architecture/goals-and-metrics-ko.md) |
