---
title: 관측성과 감지(Observability and Detection)
translation_of: observability-and-detection.md
translation_source_sha: 183885acea5bcde38c5028519b49f48b6b5df0ec
translation_revised: 2026-07-08
---

# 관측성과 감지(Observability and Detection)

FDAI가 원시 원격측정을 컨트롤 루프가 액션할 수 있는 **finding** 으로 어떻게 바꾸는가:
**이벤트 상관관계**, **이상 감지**, **예측 / 예보**, **근본원인 분석(RCA)**. 이들은 AIOps
플랫폼이 제공하리라 기대되는 감지 신호이며 - **결정론 우선을 깨지 않고** 여기에 추가됩니다:
모든 신호는 기존 `trust-router → tiers → risk-gate → executor → audit` 경로를 통해 흐르는
정규화된 finding을 emit하며, 사이드 채널이 아니고, 어떤 것도 리스크 게이트와 네 안전 불변식
밖에서 auto-execute 하지 않습니다.

참조: 컨트롤 루프, 티어, quality gate는
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md);
측정과 가드 메트릭은 [goals-and-metrics-ko.md](goals-and-metrics-ko.md); 규칙/신호 소스는
[rule-catalog-collection-ko.md](rule-catalog-collection-ko.md); 모듈 배치와 DI seam은
[project-structure-ko.md](project-structure-ko.md); 프롬프트-인젝션 위협 모델은
[security-and-identity-ko.md](security-and-identity-ko.md). 상관관계와 out-of-band 감지는
[phase-1-rule-catalog-t0-ko.md](phases/phase-1-rule-catalog-t0-ko.md) 에 도입; FinOps 비용
이상과 DR RPO/RTO 예측은
[phase-3-integrated-loop-ko.md](phases/phase-3-integrated-loop-ko.md) 에 도착. 고객-비종속;
모든 예시는 합성.

## 설계 관점 (deterministic-first, not ML-first)

- 감지는 **먼저 설명 가능하고 증거 기반**: 통계적 베이스라인, 임계, 상관관계 규칙이 대부분
  신호를 모델 호출 없이 해결. 모델(T1 유사도, T2 추론)은 fuzzy 상관관계와 신규 RCA에만 진입
  - 같은 5-10% 예산.
- 감지 신호는 액션이 아니라 **finding**. 다른 이벤트처럼 라우팅되고 risk-gate 됨; 예측이나
  이상은 절대 자체로 auto-remediate 하지 않음 - 리스크 게이트와 HIL이 관장하는 shadow-mode
  finding 또는 remediation PR을 발동.
- 새 감지기는 **shadow 모드** 로 출시되고 shadow→enforce 규칙에 따라 승격; 정확도와
  false-positive 비율은 Phase 0 베이스라인 대비 측정됨.

## 1. 이벤트 상관관계(Event Correlation)

`event-ingest` 의 한 스테이지, normalize + deduplicate 직후
([project-structure-ko.md](project-structure-ko.md) 와
[phase-1-rule-catalog-t0-ko.md](phases/phase-1-rule-catalog-t0-ko.md) 참조): 관련된 원시
이벤트를 하나의 **인시던트** 로 묶어 하류 티어가 폭풍이 아니라 한 가지만 추론하게 함.

- **Deterministic-first**: bounded **time window** 내에서 공유 키(리소스 id, 배포 id,
  trace/correlation id, 원인 부모)로 상관 지음(규칙 사용); 퍼지 그룹화에 한해서만 **T1 임베딩
  유사도** 로 fallback.
- **그룹화이지 인과 아님**: 상관관계는 이벤트가 *함께 속한다* 만 단언; 공유 윈도우는 우연일 수
  있음. *원인* 배정은 RCA의 일(4절)이며 상관관계가 아님.
- **윈도우와 늦은 도착**: 상관관계 윈도우는 신호 클래스별로 설정; 열린 인시던트의 키와 매칭되는
  late/out-of-order 이벤트는 여기에 부착(또는 윈도우 이후면 linked follow-on 인시던트 오픈) -
  이벤트는 절대 조용히 드롭되지 않고,
  [architecture.instructions.md](../../.github/instructions/architecture.instructions.md) 의
  per-resource 순서 보장이 보존됨.
- **멱등 그룹화**: 인시던트 id는 상관관계 키에서 결정론적으로 파생되므로 같은 멤버 재처리는
  도착 순서와 무관하게 같은 인시던트를 산출.
- **노이즈 감소**: 한 root 이벤트로부터의 알림 버스트는 하나의 인시던트로 접힘. 이것은 **측정된**
  노이즈-감소 비율(인시던트 ÷ 원시 알림)로 보고, 주장된 이득이 아님, 데이터 손실 없음 -
  멤버는 감사에 링크되어 남음.
- **출력**: 멤버 이벤트 id와 안정 idempotency 키를 운반하는 하나의 상관된 인시던트 이벤트;
  순서/멱등 키 보존.
- **업스트림 구현**: `core/event_ingest/correlator.py`
  (`EventCorrelator`) 가 이벤트의 correlation-id (또는 resource ref) 와
  time-window bucket 으로부터 `incident_id_for` 를 통해 인시던트 anchor 를
  결정론적으로 도출한다; 한 window 에서 key 를 공유하는 버스트는 하나의
  인시던트로 접히고, 새 window 는 linked follow-on 을 연다. anchor 없는
  이벤트는 `correlated=False` 로 보고된다(드롭 없음). key 들은
  `IncidentRegistry.open` 에 공급되어 멤버십을 idempotent 하게 누적한다.

## 2. 이상 감지(Anomaly Detection)

기존 FinOps 비용-이상 훅
([phase-3-integrated-loop-ko.md](phases/phase-3-integrated-loop-ko.md))을 **어떤 메트릭 스트림**
(성능, 신뢰성, 보안, 비용)에도 일반화.

- **방법**: 통계적 베이스라인(rolling 및/또는 seasonal, seasonality 윈도우는 config)과 편차
  임계(예: z-score 또는 robust percentile 밴드), 신호 클래스별로 계산. 결정론적이며 설명 가능;
  베이스라인, 편차 크기, **방향**(over/under) 이 기록되어 사람이 왜 발동했는지 볼 수 있음.
- **콜드스타트**: 신뢰할 만하기에 충분한 베이스라인 히스토리가 없는 감지기는 얇은 베이스라인에
  발동하지 않고 **abstain**(shadow에 머물고 finding emit 없음); 콜드스타트 억제는 숨겨지지
  않고 메트릭으로 카운트.
- **카테고리**: finding은 rule 카탈로그와 공유되는 정본 `category` enum
  (`security | reliability | cost | config-drift`) 으로 정규화 - 성능 신호
  (latency/error-rate/saturation) 와 replication lag는 `reliability`, 비정상 접근 패턴은
  `security`, 지출 run-rate는 `cost` 로 매핑. 심각도는 편차 크기에서 파생.
- **변경 인지 억제**: in-flight 변경/유지 윈도우와 동시적인 이상은 발생 변경 이벤트와 상관
  지어져 억제되거나 주석 처리 - 배포가 false positive를 제조하지 않게 함.
- **False-positive와 false-negative 컨트롤**: debounce/settling 윈도우 + 새 감지기가 회귀시키면
  안 되는 측정된 false-positive 비율 *과* false-negative(놓친 이상) 비율 - 둘 다
  [goals-and-metrics-ko.md](goals-and-metrics-ko.md) 의 가드 메트릭에 매핑.
- **출력**: `event-ingest` 로 재진입(idempotency key와 dedup을 위해)하는 이상 finding, 이후
  다른 이벤트처럼 신뢰 라우터로.
- **업스트림 구현**: `core/detection/anomaly.py`
  (`MetricAnomalyDetector`) 가 위에 기술한 결정론적 z-score baseline 을
  ship 한다 - cold-start abstain, flat-baseline 안전 처리, deviation
  크기 기반 severity - 그리고 각 finding 을 `to_event` 로 shadow 모드의
  `Event(event_type="anomaly.finding")` 로 정규화하며, `detector + metric
  + window` 로 keying 해 반복 tick 을 dedup 한다.
- **계절성(Seasonality)**: `core/detection/seasonal.py`
  (`SeasonalAnomalyDetector`) 는 주기적 형태를 가진 metric 을 처리해,
  정상적인 phase 별 peak(월요일 아침 트래픽 스파이크, 야간 배치 작업)이
  24x7 통합 평균 대비 발화하지 않도록 한다. history 를 설정된 **phase**
  (`hour_of_day`, `day_of_week`, `hour_of_week`, 또는 커스텀 함수)로
  버킷팅하고, 관측 샘플을 *같은* phase 의 과거 샘플하고만 비교한다. base
  detector 를 감싸는 얇은 wrapper 로 - history 를 phase 로 필터링하고
  z-score, cold-start-abstain, flat-baseline, event 정규화 로직을 위임한다
  - 두 detector 가 어긋날 수 없다. phase 별 cold-start 는 독립적이고(얇은
  일요일 baseline 이 월요일 데이터를 빌리지 않는다), phase 는 finding 의
  `window_bucket` 에 기록되며, finding 은 여전히 shadow 모드 이벤트다.

## 3. 예측 / 예보(Predictive / Forecasting)

Proactive 감지: 발생 **전에** 임계 위반을 예측 - AIOps "용량 병목과 서비스 장애 예측" 사례 -
결정론 우선으로 유지.

- **방법**: 설정된 **예보 지평** 까지 측정된 시리즈에 대한 트렌드 외삽(linear/seasonal fit),
  예상 값이 설정된 임계를 넘을 때 finding 발동. 모든 예보는 그 지평과 **신뢰 구간** 을 운반;
  명시된 불확실성 있는 projection - **결정론적 진실도 아니고 LLM 신탁도 아님** - 그리고 실행
  자격을 절대 부여하지 않음.
- **대상**: 용량/쿼터 고갈, RPO 위반 방향의 replication-lag 드리프트, 예산 대비 비용 run-rate,
  인증서/시크릿 만료, 백업-보존 드리프트. RPO/RTO와 FinOps 대상은
  [phase-3-integrated-loop-ko.md](phases/phase-3-integrated-loop-ko.md) 가 소유.
- **승격 전 backtest**: 예보기는 과거 시리즈에 대해 **backtest**(알려진 과거 위반 예측)하고
  shadow에서 정확도 바를 통과해야 shadow 모드를 떠날 수 있음.
- **드리프트**: 예보 오차는 시간에 걸쳐 추적; 측정된 저하(드리프트)는 자동으로 예보기를 shadow로
  **강등**.
- **안전**: 예측은 **finding 발동**(기본 shadow 모드) 또는 proactive remediation PR; 자체로
  auto-execute 하지 않음. 예보에 액션하는 것은 여전히 리스크 게이트를 통과하고 네 안전 불변식을
  운반.
- **측정**: **lead time** = `actual_breach_time − finding_time` 정의(유효한 예측은
  actionable minimum 위의 positive lead time을 가짐), **precision/recall** 스코어 (true
  positive = 예측된 위반의 실제 위반이 지평 내에 발생). 놓친 위반은 false negative(가드 메트릭);
  나쁜 예보기는 shadow에 머무름.
- **업스트림 구현**: `core/detection/forecast.py`
  (`LinearForecastDetector`) 가 최소제곱 선형 예보기를 ship 한다 -
  cold-start 와 weak-fit(낮은 R-squared) 입력은 abstain, direction-gated
  rising/falling 위반 projection, 그리고 지평으로 bound 된 positive lead
  time(위반 ETA). 각 예보는 `to_event` 로 shadow 모드의
  `Event(event_type="forecast.finding")` 로 정규화되며, `detector + metric
  + window` 로 keying 해 반복 tick 을 dedup 한다; severity 는 임박도
  (lead / horizon)로 스케일. anomaly 감지기와 `MetricSample` series 타입을
  공유한다 (`core/detection/series.py`).

## 4. 근본원인 분석(Root-Cause Analysis)

RCA를 암묵적 부작용이 아니라 티어의 first-class 출력으로 만듦.

| 티어 | RCA 역할 |
|------|---------|
| **T0** | 직접 원인: 매칭된 규칙/정책이 위반된 컨트롤과 remediation을 명명 |
| **T1** | 상관관계 원인: (a) 인시던트를 이전 **해결된** 인시던트와 매칭하고 그 식별된 root cause + 학습된 액션 재사용(provenance와 재검증), 또는 (b) 인시던트 자신의 상관 이벤트로부터 **결정론적 인과사슬**을 재구성 - 관련 리소스에서 bounded window 내 실패에 선행한 가장 가까운 change / mutation 을 식별("deploy 가 나갔고, 그 다음 error rate 가 올랐다" 사슬) |
| **T2** | 추론 원인: 신규/모호 인시던트에 대해 quality gate를 통과하는 **증거를 인용**(규칙, 상관 이벤트, 원격측정) 하는 근거 있는 root-cause 가설 생산 |

- RCA 출력은 권위 있는 판정이 아니라 **인용 있는 가설**; **실행 자격은 여전히 결정론적 검증**
  (verifier + 정책 재검사) 으로 부여, RCA 텍스트나 예보만으로 절대 아님.
- T2 RCA에 공급되는 원격측정과 상관 이벤트는 **untrusted 입력** 이며 프롬프트 인젝션을 운반할
  수 있음; [security-and-identity-ko.md](security-and-identity-ko.md) 에 따라 verifier와
  정책 재검사가 어떤 모델 텍스트에 대해서도 권위.
- 이전 해결된 인시던트의 root cause를 T1이 재사용할 때는 이전 원인과 학습된 액션이 여전히
  **적용된다는 것을 재검증**(provenance와 함께) 해야 하며, 결과 액션은 리스크 게이트 전에
  what-if를 실행 - stale 학습된 액션은 절대 눈감고 재생되지 않음.
- 근거를 가질 수 없는 RCA는 **abstain** 하고 HIL로 라우팅.
- 상관된 인시던트(1절)가 RCA 입력이므로 RCA는 중복 폭풍이 아니라 하나의 인시던트를 추론.
- **업스트림 구현**: `core/rca/` 가 RCA 계약
  (`RootCauseHypothesis` + `Citation`), 결정론적 **T0** cause
  (`t0_root_cause`, 매칭된 rule 에 confidence 1.0 으로 grounded 되고
  remediation 포함), 그리고 **grounding gate** (`enforce_grounding`,
  ungrounded 이거나 confidence 미만인 hypothesis 는 HIL 로 abstain) 를
  ship 한다. **T2** reasoner 는 `RcaReasoner` Protocol seam - fork 가
  mixed-model, RAG-grounded producer (via `core/quality_gate`) 를 그
  뒤에 plug 한다. Upstream 은 `core/rca/llm.py` (`LlmRcaReasoner` + the
  `RcaModel` seam) 를 ship 하며, 그 결정론적 parser 는 malformed 답변,
  fabricated citation (prompt injection), ungrounded 답변을 거부한다 -
  모델은 제안하고, parser 와 grounding gate 가 결정한다. Azure T2
  binding 은 `delivery/azure/llm/rca_model.py` (`AzureOpenAIRcaModel`)
  로, managed-identity token 으로 Azure OpenAI 를 호출하고 upstream
  parser 가 검증할 raw JSON 을 반환하는 `RcaModel` 어댑터다. composition
  root 가 이것을 `resolved-models.json` 의 `t2.rca` capability 로
  바인드한다 (`bind_azure_llm_bindings`, Critic / Judge 바인딩과
  대칭) - capability 나 prompt 가 없으면 `LlmBindings.rca_reasoner =
  None` 이라 T2 RCA 는 dark 상태로 남고 T0 RCA 만 동작한다.
  `__main__` 은 그 결과의 `RcaCoordinator` (그리고 `EventCorrelator`) 를
  `ControlLoop` 에 주입한다. 그 출력도
  grounding gate 와 risk-gate verifier 를 통과하며, 모델의 prose
  만으로는 절대 실행하지 않는다. `RcaCoordinator`
  가 세 tier 를 모두 orchestrate 한다 - T0, **T1** correlation-reuse
  (prior resolved incident 의 cause, 현재 evidence 대비 stale 이면
  abstain), 그리고 T2 (공급된 evidence 밖의 citation 은 fabricated 로
  거부). 이것이 `ControlLoop` 에 배선되어, finding 마다 결정론적 T0
  `rca.hypothesis` audit 엔트리 하나를 append 하며, 상관된 `incident_id`
  (`EventCorrelator`, 1절) 를 실어 한 인시던트의 finding 들을 묶는다 -
  "왜"이지 새로운 실행 경로가 아니다. T2 reasoner 가 배선되면, novel (T0
  no-match) case 는 추가로 grounded T2 `rca.hypothesis` (또는 abstain) 를
  받으며, reasoner-gated 라 LLM 없는 배포는 T2 노이즈를 emit 하지 않는다.
- **T1 인과사슬 (결정론적)**: `core/rca/t1.py` (`t1_causal_chain`) 은 T1
  correlation (b) 의 model-free 형태다: 인시던트의 상관 이벤트(각각
  timestamp, generic `resource_ref`, `is_change` 마커를 carry)가 주어지면,
  **실패에 strictly 선행하고 window 내에 발생한 가장 최근의 change** 를 가장
  probable 한 trigger 로 선택한다. cross-resource causation 은 기본 허용
  (shared-dependency deploy)되거나 `same_resource_only` 로 실패 리소스에
  국한된다. confidence 는 temporal proximity 로 scale 되고 T1 band
  (`0.35`-`0.85`)로 bound 된다 - temporal antecedent 는 강한 hint 이지
  T0-style 확실성이 아니다 - 그리고 plausible 한 선행 change 가 없으면 tier 는
  **abstain**(`None` 반환, T2 로 defer)한다. hypothesis 는 trigger 와 failure
  event citation 에 grounded 되고 결정론적(동일 이벤트 집합은 항상 동일 cause)
  이므로, 이것도 grounding gate 와 risk-gate verifier 를 통과한 뒤에야 무언가
  act 한다.

## 컨트롤 루프에 플러그

상관관계는 `event-ingest` 안에서 실행. 이상과 예보 감지기는 **out-of-band 생산자**
([app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md) 및 phase-1
out-of-band 감지 참조) 로 finding을 버스에 publish; 그 finding은 idempotency 키와 dedup을
얻기 위해 **`event-ingest` 로 재진입** , 그래서 flapping 감지기가 중복 작업을 주입할 수 없음.
어떤 감지기도 새로운 자율성 표면이 아님:

```text
telemetry / metrics
  -> anomaly / forecast detectors emit findings ---.               # sections 2-3
  raw events -------------------------------------- +-> event-ingest
                                                       (normalize + dedup + correlate)   # section 1
  -> trust-router -> T0 | T1 | (T2 -> quality-gate)                                       # RCA per tier, section 4
  -> risk-gate -> auto -> executor -> delivery (PR) | HIL | abstain/deny -> audit
```

- **Finding** 은 `shared/contracts` 의 first-class, 버전된 이벤트 타입이며 안정 idempotency
  키(예: `detector-id + metric + window-bucket`, 또는 인시던트 id) 를 가짐 - 반복 평가 tick이
  쌓이지 않고 dedup.
- 감지기는 설정 주도(베이스라인, 임계, 지평, 상관관계 키, 모델 바인딩이 config, 하드코딩 아님),
  shadow-before-enforce 준수, 모든 finding과 결정이 감사됨.

## AIOps 정합

일반 AIOps 모델에서 채택한 것과 의도적으로 다른 곳:

| AIOps 능력 | 우리의 자세 |
|------------|-------------|
| 인시던트 감지 & 알림 | 채택 - 상관관계 + 이상이 finding emit |
| Root-cause analysis | 채택 - 티어별 first-class RCA (4절) |
| 이상 감지 | 채택 - 통계적, 설명 가능 (2절) |
| 예측 분석 | 채택 - 트렌드 + 임계 예보, 불확실성 있음 (3절) |
| 알림 노이즈 감소 / false positive 감소 | 채택 - 상관관계 + 측정된 FP 비율 |
| 수동 작업 감소 / 빠른 해결 | 채택 - 리스크 게이트된 auto-remediation |
| 감사 트레일 / 컴플라이언스 | 채택 - append-only 감사가 이미 코어 |
| **주 엔진으로서의 ML/NLP** | **다름** - 결정론 우선; 모델은 5-10% 잔여 |
| **불투명 / black-box 이상 스코어링** | **다름** - 설명 가능 우선; finding이 베이스라인, 편차, 방향 기록 |
| **모델이 추천 *하고* 실행** | **다름** - 실행 자격은 모델이 아니라 결정론적 검증에서 |
| **벤더-플랫폼 락인** | **다름** - CSP-중립; 관측성 플랫폼은 원격측정 *소스* 이지 두뇌 아님 |

## 설정과 안전

- 베이스라인, 편차 임계, 예보 지평, 상관관계 키, 모델 바인딩은 **설정**; 포크는
  [project-structure-ko.md](project-structure-ko.md) 의 DI seam으로 오버라이드, 절대 코어를
  편집하지 않음.
- 감지기는 시작 시 설정을 검증하고 **fail closed** - 깨진 감지기, 부족한/콜드스타트 베이스라인,
  stale 원격측정은 false finding emit 이나 auto-act가 아니라 감지기 **abstain** 하게 함.
- 감지 finding은 **untrusted 입력**; 어떤 LLM 사용(퍼지 상관관계, T2 RCA)도 quality gate
  ([architecture.instructions.md](../../.github/instructions/architecture.instructions.md))
  와 [security-and-identity-ko.md](security-and-identity-ko.md) 의 프롬프트-인젝션 위협 모델을
  통과.
- 감지기 메트릭 발행 - fire rate, false-positive 비율, false-negative/놓친-위반 비율, abstain
  및 콜드스타트 억제 카운트, 예보 lead time, RCA groundedness - 를 KPI 대시보드로.

## Open Decisions

- [ ] 신호 클래스별 이상 방법(z-score vs robust percentile vs seasonal decomposition).
- [ ] 대상별 예보 모델 패밀리와 기본 지평(용량, lag, 비용, 만료).
- [ ] 상관관계 키 세트와 시간-윈도우 기본; 퍼지 상관관계를 T1으로 escalate하는 때.
- [ ] 콜드스타트 정책: 감지기가 발동하기 전 신호 클래스별 최소 베이스라인 히스토리.
- [ ] Backtest 주기와 예보기가 shadow를 떠나기 위해 통과해야 할 정확도 바.
- [ ] 변경 윈도우 억제: 이상이 in-flight 변경 이벤트와 어떻게 상관되는가.
- [ ] RCA 가설이 콘솔에 표면화될지(읽기 전용) P2 또는 P3에서.
