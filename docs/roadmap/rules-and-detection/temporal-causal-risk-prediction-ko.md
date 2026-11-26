---
title: 시계열 온톨로지 인과추론 및 Azure 변경 위험 예측 설계 스펙
status: active
scope: fdai-domain-core, fdai-ports, fdai-adapter-postgres, migrations
---

# 시계열 온톨로지 인과추론 및 Azure 변경 위험 예측 설계 스펙

## 1. 목적 및 권한 경계

이 문서는 FDAI가 PostgreSQL에 저장된 양시제(Bitemporal) 운영 온톨로지와 Azure 리소스 변경·메트릭 시계열을 결합하여 **원인-결과 검증(Rung 1.5), 사전 변경 파급 예측(Rung 2), 개입 반사실 평가(Rung 3), 2계층 근본 원인 분석(Two-Layer RCA), 동일 클래스 전역 수평 예방 갭 탐지**를 결정론적으로 수행하는 아키텍처와 불변식을 정의한다.

> **권한 경계 (불변):** 인과추론과 위험 예측 결과는 `DecisionCase`, 변경 위험 등급, 리뷰 게이트의 **근거(Evidence)** 로만 제공된다. 실제 실행 허가와 변경 적용 권한은 기존 컨트롤 루프의 규칙 검증기, 안전성 검사, 승인 정책, 감사 원장에 유지된다.

---

## 2. 계층 구조 (Hexagonal Clean-Room Architecture)

| 계층 | 위치 | 책임 | 제약 |
|---|---|---|---|
| **Domain Core** | `crates/core/fdai-domain-core` | Zero-I/O 순수 Rust 인과 그래프(`causal_ontology.rs`), 시계열 인과·예측·2계층 RCA 커널(`temporal_causal.rs`), 양시제 스냅샷(`migrated/audit/bitemporal.rs`), 컨트롤 루프 RCA(`migrated/control_loop/rca.rs`) | `std` 전용, `#![forbid(unsafe_code)]`, `unwrap`/`expect`/`panic` 금지 |
| **Ports** | `crates/ports/fdai-ports` | 저장소 독립 트레이트 `TemporalCausalStorePort` | I/O 드라이버 의존 금지 |
| **Postgres Adapter** | `crates/adapters/fdai-adapter-postgres` | `as_of` 기준 양시제 토폴로지 조회, Azure 시계열 조회, 실측 승격 인과 간선 upsert SQL 빌더 및 `PgWireClient` 실행 | SQL 인젝션 차단, 유한 수치 및 식별자 정규화 강제 |
| **Database Schema** | `migrations/0002_temporal_causal_ontology.sql` | PostgreSQL 양시제 토폴로지, Azure 변경·메트릭 시계열, 인과 근거 원장, 예방 가드 갭 테이블 | `CHECK` 제약으로 오염·분산 0·비유한 값 차단 |

---

## 3. PostgreSQL 3계층 온톨로지 × 시계열 저장 모델

### 3.1 양시제 온톨로지 토폴로지 (`ontology_topology_bitemporal`)
- 각 관계 간선 `(source_ref, relation_type, target_ref)`은 유효 시각 구간 `[valid_from, valid_to)`와 기록 시각 `recorded_at`을 함께 보관한다.
- 모든 인과 조사와 변경 위험 예측은 고정된 근거 기준 시점 `evidence_cutoff (as_of)` 이전(`recorded_at <= as_of AND valid_from <= effective AND (valid_to IS NULL OR valid_to > effective)`)의 간선만 조회한다.
- 서로 다른 시점의 토폴로지 세대(`graph_generation`)를 혼합하지 않으며, 미래 시점 표본과 간선은 DB 쿼리와 도메인 커널 양쪽에서 이중 차단한다.

### 3.2 Azure 리소스 변경·메트릭 통합 시계열 버스 (`azure_telemetry_series`)
- **핵심 원칙:** Azure Activity Log / ARM / Terraform / AKS 변경 이벤트(`nsg_rule_change`, `rbac_assignment_change`, `keyvault_secret_expiry`, `vm_power_state_change`, `sku_downscale`, `diagnostic_settings_disabled` 등)와 관측 메트릭(`http_5xx_rate`, `p99_latency_ms`, `cpu_utilization`, `memory_pressure`, `connection_failures`)을 **동일한 스키마의 시계열 포인트**로 적재한다.
- 주요 컬럼: `(subscription_id, resource_id, resource_type, metric_or_change_concept, valid_at, ingested_at, value, status_tag, change_digest)`.

### 3.3 실측 승격 인과 간선 원장 (`causal_edge_evidence`)
- 시계열 검정을 통과한 간선만 `(cause_concept, relation_type, effect_concept, evidence_grade, optimal_lag_seconds, granger_r2_gain, confounder_controlled, counterfactual_verified, evidence_cutoff, graph_digest)`로 영속화한다.
- 상수(분산 `<= 1e-9`) 시계열, 동시 변화(시차 0), 로그/URL/파일경로 오염 식별자, 역방향과 동등한 상관 간선은 승격을 거부하고 `AssociationOnly` 또는 `InsufficientEvidence`로 유지한다.

---

## 4. 핵심 추론 알고리즘 및 불변식

### 4.1 Pearl 백도어 교란변수 정밀 식별 (도구변수 오판 금지)
- `Z -> X -> Y` 체인에서 `Z`는 `X`의 도구변수(Instrument)이지 `X`와 `Y`의 교란변수(Confounder)가 아니다.
- 백도어 교란변수 집합은 `ancestors(X)`와 **`X` 경유를 차단한 `ancestors_excluding(Y, X)`** 의 교집합에서 `descendants(X)`를 제외하여 계산한다.
- 제3변수 `Z`의 d-separation 역할을 `Confounder`, `Mediator`, `Collider`, `Neutral`로 분류하여 매개변수(`X -> Z -> Y`) 과통제와 충돌변수(`X -> Z <- Y`) 편향을 원천 방지한다.

### 4.2 Rung 1.5 시계열 인과 검증 (Azure 비정상성·이상치·교란 방어)
1. **미래 표본 차단 (`as_of` cutoff):** `valid_at_ms > evidence_cutoff_ms`인 모든 표본은 통계 계산 전 제거한다.
2. **비정규 타임스탬프 as-of 정렬:** 원인 시계열과 결과 시계열의 샘플링 주기가 달라도 결과 시점 `t_i` 직전 유효 원인값을 허용 오차 내에서 정렬한다.
3. **자동 1차 차분(Unit-Root Guard):** 두 시계열의 1차 자기상관 `|rho_1| >= 0.85`인 비정상 추세(예: 주간 트래픽 상승)가 감지되면 자동으로 1차 차분(`Δx_t`, `Δy_t`) 후 검정하여 허위 추세 인과를 차단한다.
4. **MAD 이상치 클램핑:** 중앙값 절대 편차(`MAD`) 기반 `±6 * 1.4826 * MAD` 클램핑으로 단발 스파이크 왜곡을 억제한다.
5. **AR(2) + 비선형 2차항 Granger & 역방향 대칭 검증:** 유효 자유도 `eff_n >= 8`을 강제하고, 순방향(`X -> Y`)과 역방향(`Y -> X`)의 `R² gain`을 비교해 순방향이 통계적으로 우세할 때만 방향성 인과 후보로 채택한다.
6. **다변량 편상관 교란 통제:** 후보 교란변수 시계열을 선형 직교화(Gram-Schmidt / OLS 잔차화)한 뒤 잔차 간 편상관과 Granger 이득이 기준 미만으로 붕괴하면 `Confounded`로 차단한다.
7. **다중 시차 보정:** 탐색한 최대 시차 수 `max_lag`에 대해 임계치를 보정하여 우연한 거짓 양성을 억제한다.

### 4.3 Rung 2 사전 변경 위험 예측 (`do(Azure Change)` × `is_a` × 3값 `unless`)
- 상위 실패 메타-온톨로지 5대 클래스:
  - `ComputeLivenessFailure`: VM 중지, AKS 노드 다운, 헬스 프로브 실패, 네트워크 차단
  - `CapacityExhaustionFailure`: 디스크 고갈, OOM/메모리 압박, 커넥션 풀 고갈, SKU 축소
  - `CredentialOrCertExpiryFailure`: TLS 인증서 만료, KeyVault 시크릿/토큰 만료, 관리 ID 권한 만료
  - `ObservabilityBlindspot`: Diagnostic Settings 제거, Alert Rule 누락, 텔레메트리 지연/끊김
  - `ControlPlaneDriftFailure`: NSG/방화벽 드리프트, RBAC 과권한 변경, 롤아웃 정체/재시작 루프
- 변경 적용 전 `do(change_concept)` 그래프 수술을 수행하며, 각 간선의 억제 가드(`unless_inhibitors`)는 `Allow`, `Inhibit`, `Unknown` 3값으로 평가한다. `Unknown` 가드는 무효화하지 않고 `uncertain_edges`로 분리 보고하여 운영자가 과신하지 않게 한다.

### 4.4 2계층 인시던트 RCA & Azure 전역 수평 예방 갭 추론
- **Layer 1 (물리/변경 원인):** 관측 시계열의 Granger + 교란 통제 + 온톨로지 `do(X)` 파급을 종합해 원인을 특정한다. 관측 표본이 부족하거나(`points < 2`) 유의한 인과 근거가 없으면 추측하지 않고 `abstain_insufficient_causal_evidence`로 정직하게 기권한다.
- **Layer 2 (관측 사각지대 RCA):** `MTTD = t_detect - t_fail`이 SLA 예산을 초과하거나 해당 `AzureFailureClass`의 필수 예방 가드가 비활성이면 `blindspot_detected = true`와 누락 가드 명세를 산출한다.
- **전역 수평 예방 갭 추론:** 장애 또는 고위험 변경이 감지된 상위 클래스(`is_a`)를 공유하는 전체 Azure 리소스 인벤토리를 순회해, 동일 필수 가드가 누락된 미발생 리소스를 선제 위험 목록으로 추출한다.

---

## 5. 필수 회귀 검증 기준 (16대 불변식 시나리오)

구현된 도메인 커널은 다음 16개 불변식 테스트를 전부 통과해야 한다.

1. 순방향 지연 인과 (`X_{t-1} -> Y_t`) 정탐
2. 역인과 (`Y -> X`가 진짜일 때 `X -> Y` 기각)
3. 공통 교란변수(`Z -> X, Z -> Y`) 다변량 편상관 차단
4. 매개변수(`X -> M -> Y`) 과통제 방지 및 역할 분류
5. 충돌변수(`X -> C <- Y`) 역할 분류 및 편향 차단
6. Pearl 백도어 `Z -> X -> Y` 도구변수 비오판
7. 비정상 단위근 공통 추세(Spurious Trend) 1차 차분 차단
8. 극단 단발 이상치 MAD 방어
9. 상수/분산 0 시계열 정직 기권
10. 미래 표본(`valid_at > as_of`) 엄격 차단
11. 비선형(`Y_t = X_{t-1}^2`) 지연 인과 탐지
12. `do(Azure Change)` + 3값 `unless` (`Allow`/`Inhibit`/`Unknown`) 분리 판정
13. 2계층 RCA 물리 원인 + 관측 사각지대 동시 판정
14. 근거 부족 인시던트 2계층 RCA 정직 기권
15. 동일 상위 클래스(`is_a`) Azure 리소스 전역 수평 예방 갭 추론
16. 오염 식별자(URL/파일경로/로그라인/제어문자) 거부 및 양시제 `BitemporalSnapshot` 재구성
17. 자연실험·복구 반전 증거 등급 승격(`TemporalGrangerSupported -> QuasiExperimental -> InterventionalVerified`) 및 동일 출처 에코챔버 중복 제거
18. 역순 도착(Late-Arriving) 과거 이벤트로부터 최신 `valid_at` 헤드 보호(`BitemporalEntityChain`)
