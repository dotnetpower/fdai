---
title: 목표와 메트릭
translation_of: goals-and-metrics.md
translation_source_sha: 230ee547d6c61c039e49f0b6f704d37c78d50d0c
translation_revised: 2026-08-29
---

# 목표와 메트릭

로드맵은 **증명이 있는 자율성(자율성 with 증명)**을 최적화합니다. 모든 자율성 주장은
측정된 베이스라인으로 뒷받침되며, 어떤 것도 추정으로 단언되지 않습니다. 아래의 개선 배수
(`5×`, `large reduction`, `1/5`)는 달성된 결과가 아니라 **목표(targets)** 이며 - 동일한
시나리오 세트에서 레퍼런스 베이스라인과 FDAI 트리트먼트가 **모두 측정된 후에만**
달성으로 언급할 수 있습니다 ([Measurement-First 규칙](#measurement-first-규칙) 참조).

이 문서는 KPI의 진실 원본(정본)입니다.
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)의
티어 커버리지 목표와 정합하며
[phase-0-instrumentation-ko.md](../phases/phase-0-instrumentation-ko.md) 에서 운영으로
구현됩니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 결정론적 KPI와 가드 메트릭 집계 | implemented | `core/measurement/mttr.py`; `dora.py`; `regression.py`; `tests/core/measurement/` 아래의 집중 테스트 | MTTR, 변경, 회귀, 지연 시간, 모델 및 pattern 메트릭에 실행 가능한 reducer와 실패 시 차단 검사가 있습니다. |
| 승격 및 운영 근거 평가 | implemented | `core/measurement/promotion_gate.py`; `operational_promotion.py`; 집중 승격 테스트 | 승격 평가는 개정 번호, 시나리오, 표본, 신뢰 구간, 가드 및 결과 근거를 연결합니다. 현재 유효한 공유 의사 결정 근거 승인 결과가 전체 묶음과 일치해야만 준비 완료 결과가 나올 수 있습니다. 기존 저장 증적은 읽을 수 있지만 증적 및 검증 묶음 다이제스트가 없으면 승격 권한에 사용할 수 없습니다. |
| 관리되는 운영 커버리지 주장 계약 | implemented | `packages/service-contracts/src/fdai_service_contracts/operational_coverage.py`; `packages/service-contracts/tests/test_operational_coverage.py` | 변경할 수 없는 분모, 최종 처리 결과, 최신성, 정확한 베이시스 포인트, 무관용 조건 및 다이제스트 검사를 통해 불완전한 전체 집합이 99% 주장으로 바뀌지 않도록 합니다. 증적은 실행 권한을 부여하지 않습니다. |
| 정식 의사 결정 핵심 근거 봉투 | implemented | `packages/service-contracts/src/fdai_service_contracts/decision_evidence.py`; `schemas/decision-critical-evidence/1.0.0.json`; 집중 계약 테스트 | 이 봉투는 근거와 해당 인증 증명, 권위, 범위, 목적, 정확한 생성기와 방법, 시간, 정책에서 파생된 최신성, 완전성 증명, 충돌 판정, 출처 계보 및 합성 상태를 연결합니다. 주장 사전 검사는 입력을 차단하거나 별도의 권위 있는 검증으로 전달할 수만 있으며 실제 운영 준비 상태를 주장하지 않습니다. 기존 의사 결정 경계는 아직 마이그레이션해야 합니다. |
| 독립적인 의사 결정 근거 검증 | implemented | `decision_evidence_verification.py`; `core/readiness/decision_evidence.py`; `shared/providers/decision_evidence_verifier.py`; `delivery/azure/decision_evidence.py`; 집중 계약, 준비 상태 및 Azure 어댑터 테스트 | 내용 기반 증명 5개가 인증, 근거, 완전성, 충돌 및 최신성 정책을 다룹니다. Core는 현재 유효한 신뢰 묶음이 통과한 후에만 수명이 짧고 권한이 없는 승인 결과를 생성합니다. 이제 ChatOps qualification, 운영 승격, 보안 온톨로지 쿼리 소비, 운영 컨텍스트 상태 근거, 분석기 대상 선택, 시작 준비 상태 및 운영 준비 상태가 이 승인 결과를 사용하고 각 전체 입력에 다시 연결합니다. 런타임 프로바이더 조립과 남은 직접 상태 경계 마이그레이션은 아직 열려 있습니다. |
| 고정된 시나리오 집합 계산 | in-progress | `tests/scenarios/manifests/v2026.07.json`; `test_frozen.py`; `test_v2026_07_replay.py` | 이제 SRE 묶음에는 실행 가능한 차원 4개가 있습니다. 성공적인 전체 루프와 목표 간 충돌 근거는 아직 열려 있으며 나머지 4개 묶음도 불완전합니다. |
| 실제 운영 KPI 기준선, 처리 및 대시보드 종결 | in-progress | [데이터 수집과 원격측정](#데이터-수집과-원격측정); `config/constitution-traceability.json`의 `FDAI-CONST-002` 요구 사항 | 런타임 기록과 작업은 있지만 하나의 고정된 개정에서 모든 성공 및 임계값 0 가드 메트릭을 입증하는 완전한 실제 운영 기준선 및 처리 집단은 보존되지 않았습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-29 | implemented | 감사와 발행 전에 운영 준비 상태 검토를 공유 승인 결과로 마이그레이션했습니다. 정확한 발견 사항, 범위, 환경 및 출처 리비전에는 현재 유효한 승인 결과가 필요합니다. 승인 결과가 없거나 수락되지 않으면 실제 판정은 보존하지만 `mode=shadow`를 강제하고 `blocks_handoff=false`로 만들며 유효 모드와 차단 참조를 감사에 기록합니다. | `current change`; 준비 상태 보고서 및 승인 모델, 애플리케이션 서비스, 집중 조정기, 서비스, 체크리스트, 교정 및 런타임 수집 검사, Ruff 및 strict mypy. | 프로덕션 준비 상태 근거 프로바이더를 연결하고 통제된 검토 묶음 하나를 보존합니다. 런타임 검증기 조립과 직접 상태 소비자는 열려 있습니다. |
| 2026-08-29 | implemented | 영속화 및 전환 발행 전에 시작 준비 상태를 공유 승인 결과로 마이그레이션했습니다. 조정기는 축약된 전체 보고서와 탐색 집합 리비전을 현재 유효한 승인 결과에 연결합니다. 승인 결과가 없거나 수락되지 않으면 차단되지 않은 결과를 `DEGRADED`로 바꾸고 모든 기능을 최대 `SHADOW`로 제한하며 `READY` 주장 대신 차단 이유를 보존합니다. | `current change`; 준비 상태 모델, 조정기, 런타임 조립, 집중 조정기 및 런타임 테스트, Ruff 및 strict mypy. | 시작 조정기를 프로덕션 검증기 레지스트리에 연결하고 실제 보고서 묶음 하나를 보존합니다. 운영 준비 상태 및 남은 직접 상태 경계를 마이그레이션합니다. |
| 2026-08-29 | implemented | 변환된 Resource가 상태 메타데이터를 전달할 때 분석기 대상 선택을 공유 승인 결과로 마이그레이션했습니다. 해석기는 정확한 상태 및 리소스 범위 다이제스트를 파생하고 신뢰할 수 있는 승인 결과를 요청하며, 프로바이더가 없거나 승인 결과가 일치하지 않으면 `unverified_state_fact`로 대상을 건너뜁니다. 상태 주장 없이 신원과 유형만 있는 Resource는 기존 적격 경로를 유지합니다. | `current change`; 분석기 대상 해석기, 집중 라우팅 tick 테스트, Ruff 및 strict mypy. | 분석기 작업을 신뢰할 수 있는 승인 프로바이더에 연결하고 남은 직접 상태 소비자를 마이그레이션합니다. |
| 2026-08-29 | implemented | 운영 컨텍스트 상태 근거를 공유 승인 결과로 마이그레이션했습니다. 각 묶음은 재생 신원에 승인 결과를 보존하고 순환 약속값 없이 정확한 상태 항목 및 범위 다이제스트를 다시 계산하며, 승인 결과가 없거나 일치하지 않거나 만료되면 명시적 보류와 함께 `SHADOW_ONLY`로 낮춥니다. | `current change`; 운영 근거 모델, 신원, 빌더, 공유 승인 결과 매핑, 집중 묶음 및 materializer 검사, Ruff 및 strict mypy. | 권위 있는 상태 승인 결과 생성기를 연결하고 직접 상태 소비자를 마이그레이션합니다. 준비 상태 및 런타임 조립은 열려 있습니다. |
| 2026-08-29 | implemented | 보안 온톨로지 쿼리 소비를 공유 승인 계약으로 마이그레이션했습니다. 진단을 위해 쿼리 결과를 계속 보존할 수 있지만, 의존성 해석과 의사 결정 핵심 FunctionType 검증에는 정확한 변환 결과, 범위, 목적, 온톨로지 릴리스 및 출처 세대에 연결된 현재 유효한 승인 결과가 필요합니다. 프로덕션 승인 프로바이더 seam은 연결되지 않았으므로 실패 시 차단합니다. | `current change`; 쿼리 권한, 출처 핸들러, 의미 조립, 집중 쿼리 및 조립 검사, Ruff 및 strict mypy. | 프로덕션 쿼리 승인 프로바이더를 신뢰할 수 있는 검증기 레지스트리에 연결하고 서비스 간 증적과 묶음을 보존합니다. 준비 상태 및 상태 경계를 마이그레이션합니다. |
| 2026-08-29 | implemented | 운영 승격 준비 상태를 공유 의사 결정 근거 승인 결과로 마이그레이션했습니다. 평가기는 정확한 묶음, 리비전, 시나리오, ActionType, 목적 및 유효 구간을 연결하고 증적과 검증 묶음 다이제스트를 모두 보존하며, 이 정보 없이는 준비 완료 증적을 만들 수 없습니다. 저장소는 진단을 위해 기존 1.0 증적을 읽지만 레지스트리와 직접 실행기는 적용 모드에서 이를 모두 차단합니다. | `current change`; 운영 승격 평가기, 위험 레지스트리, 영속성 코덱, 직접 실행기 및 집중 승격 테스트, Ruff 및 strict mypy. | 프로덕션 승격 근거 출처를 독립 검증기 레지스트리에 연결합니다. 남은 준비 상태, 쿼리 및 상태 경계를 마이그레이션합니다. |
| 2026-08-29 | implemented | 독립적인 의사 결정 근거 검증이 성공한 경우에만 생성되는 수명이 짧고 권한이 없는 승인 결과를 추가한 다음, ChatOps qualification이 정확한 묶음 근거와 범위 다이제스트를 파생하고 승인 결과가 없거나 일치하지 않거나 만료되면 차단하도록 마이그레이션했습니다. 독립 실행형 qualification CLI는 계속 진단 전용이며 검증기 결속 없이 자격을 주장할 수 없습니다. | `current change`; 공유 검증기 seam, Core 준비 상태 게이트, ChatOps qualification 축약기, 집중 단위 및 CLI 검사, Ruff 및 strict mypy. | 런타임 조립에 검증기 레지스트리를 연결하고 남은 준비 상태, 쿼리, 상태 및 승격 의사 결정 경계를 마이그레이션합니다. 검증된 집단을 주장하기 전에 프로덕션 qualification 증적과 묶음을 보존합니다. |
| 2026-08-29 | implemented | 의사 결정 핵심 증명 클래스 5개 모두에 독립적인 검증기 계약과 준비 상태 게이트를 추가했습니다. 버전이 지정된 검증기 결속은 이제 신뢰 기준점, 유효 구간 및 폐기 상태를 전달합니다. 검증기 결속이 없거나 오래된 경우, 생성기 자체 검증, 증적 또는 대상 불일치, 만료된 증명, 시간 초과 및 합성 근거가 있으면 검증을 차단합니다. Azure 어댑터는 Managed Identity로 권위 있는 원본 읽기를 인증하고 액세스 토큰을 반환하거나 저장하지 않습니다. | `current change`; 서비스 계약 모델과 등록된 Draft 2020-12 스키마, 공급자 중립 검증기 seam, Core 준비 상태 게이트, Azure 어댑터 및 집중 계약, 준비 상태, Azure 어댑터 테스트. | FDAI-CONST-002를 `partial`에서 변경하기 전에 런타임 조립에 검증기 레지스트리를 연결하고 기존 준비 상태, 쿼리, 상태, 승격 및 자격 판정 경계를 마이그레이션합니다. |
| 2026-08-29 | implemented | FDAI-CONST-002에 필요한 공급자 중립 `DecisionCriticalEvidenceReceipt` 기반을 추가했습니다. 정식 다이제스트는 근거 페이로드, 인증 증명, 권위 클래스, 출처, 범위, 목적, 생성기와 방법 버전, 출처 개정, 이벤트와 기록 시각, 정책에서 파생된 최신성, 완전성과 충돌 증명, 출처 계보, 합성 상태 및 권한 없음 플래그를 연결합니다. 검토에서 자체 진술 필드로 실제 운영 자격을 부여하는 결과를 차단했으므로, 계약은 이제 잘못된 주장을 차단하거나 별도의 권위 있는 검증기로 전달하기만 합니다. 등록된 스키마 경계도 JSON Schema로 표현할 수 없는 의미 모델 검사를 실행합니다. | `current change`; 서비스 계약 모델, Draft 2020-12 스키마와 의미 검증, 패키지 레지스트리와 내보내기, 추적성 기록 및 집중 계약 테스트. | FDAI-CONST-002를 `partial`에서 변경하기 전에 신뢰할 수 있는 인증, 근거, 완전성, 충돌 및 정책 검증기를 구현하면서 준비 상태, 쿼리, 상태, 승격 및 자격 판정 경계를 마이그레이션합니다. |
| 2026-08-29 | in-progress | `sre.slo-signal-source-unmapped.002`에 대해 사실에 맞는 A3-E 비해당 근거를 추가했습니다. 이제 재생 검사는 라우팅 종결 시 발견 항목이나 T2 작업이 생성되지 않고, 실행 권한 평가에 진입하지 않으며, 실행 결과나 PR을 만들지 않고, 판단 보류를 기록함을 입증합니다. 검토에서 제안된 주장 두 가지를 기각했습니다. 게시자 자체의 메모리 내 기록은 독립적인 SRE 효과 검증이 아니라 전달 근거이며, 직접 작성한 후보를 `PrecedenceResolver`에 전달하는 방식은 런타임 중재를 입증하지 않습니다. 해당 테스트와 매니페스트 주장은 커밋 전에 제거했습니다. | `current change`; `services/core-control-plane/tests/scenarios/test_v2026_07_replay.py`; `manifests/v2026.07.json`; 집중 시나리오, 매니페스트, Ruff 및 strict mypy 검사. | `successful_full_loop`에는 독립적이고 권위 있는 복구 및 재발 종결 근거가 여전히 필요합니다. `cross_objective_conflict`에는 시나리오 런타임과 프로덕션 중재 경로에서 생성되고 감사되는 경쟁 작업이 여전히 필요합니다. 비합성 기준선과 처리 결과도 열려 있습니다. |
| 2026-08-29 | implemented | 강화 라운드 1에서 커버리지 계약 관점 22개를 검토하고 다이제스트 계산 전에 모든 증적 시각을 UTC로 정규화했습니다. 따라서 표준 시간대 오프셋이 달라도 같은 절대 시각은 하나의 재생 신원을 공유합니다. | `current change`; 집중 운영 커버리지 테스트. | 권위 있는 생성기를 연결하고 관리되는 증적을 보존합니다. |
| 2026-08-28 | implemented | 자산 인벤토리, 거버넌스 평가, 운영 범위, 인시던트 진단, 수정 효과 및 지식 근거 확인을 위한 하나의 공급자 중립 운영 커버리지 증적을 추가했습니다. 정책 결과와 평가 가능 여부를 분리하고, 커버되지 않은 모든 항목을 분모에 유지하며, 완전한 계산, 최신성, 정확한 베이시스 포인트 임계값 및 무관용 처리 결과를 사용해 주장 자격을 결정적으로 계산합니다. | `current change`; `operational_coverage.py`; 집중 계약 테스트 13건 통과; Ruff 및 strict mypy 통과. | 99% 운영 주장을 하기 전에 각 생성기를 권위 있는 분모에 연결하고 관리되는 증적을 보존합니다. |
| 2026-08-19 | implemented | 커밋된 기준선을 다시 생성했습니다. `sre.*` 시나리오 3건이 추가되어 고정 세트가 12개가 된 뒤에도 기준선은 여전히 9개 세트를 기술하고 있었습니다. 발행된 모든 지표와 표본 크기, 신뢰구간이 더 이상 존재하지 않는 세트를 설명하고 있었고, `routed_correctly_rate`는 0.111에서 0.083이 되었습니다. 기준선 테스트는 이제 `9`와 "t2 시나리오가 정확히 하나"를 고정하는 대신 세트에서 시나리오 개수와 t2 경제성을 도출하므로, 다음 추가는 숫자 속에서 조용히 어긋나는 대신 산출물에서 크게 실패합니다. | `current change`, `tools.baseline_run`이 `docs/baselines/v2026.07.{json,md}`와 한국어 쌍을 재생성, core와 공유 패키지 suite가 11913건 통과(스킵 131건)하며 이전에 실패하던 `test_baseline_runner`와 `test_models_facade_only` 포함 | 기준선은 여전히 `synthetic-harness` 근거이며 주장 자격이 없습니다. 실측 기준선과 처리군 코호트는 아래의 열린 항목으로 남아 있습니다. |
| 2026-08-19 | in-progress | `sre` 팩에 세 번째 커버리지 차원을 manifest 항목이 아니라 실제로 단언되는 근거로 추가했습니다. 전용 테스트가 첫 요청을 떨어뜨리는 publisher를 상대로 `sre.cluster-diagnostics-missing.001`을 재생해 효과 결과가 진짜 알 수 없는 상태로 만들고, 오류가 빠져나가기 전에 종단 `publish_outcome_unknown` audit 항목이 닫히며 PR이 기록되지 않고 캐시도 남지 않는다는 점, 그리고 같은 executor로 재시도하면 shadow PR이 정확히 하나만 발행된다는 점을 입증합니다. 어느 팩에서도 처음 확보한 `partial_failure_recovery` 근거입니다. | `current change`, `tests/scenarios`와 `test_shadow_eval.py`가 focused 116건 통과, 신규 테스트는 변이 검증 완료 - `_close_unknown_publish`를 no-op으로 바꾸면 `assert 0 == 1`로 실패합니다. | `sre`의 `successful_full_loop`, `cross_objective_conflict`, `a3e_or_non_applicability`는 여전히 근거가 없습니다. full-loop 주장은 shadow 실행이 제공하지 않는 독립 효과 검증이 필요하고, A3-E 주장은 아직 연결되지 않은 standing-authority 평가기가 필요합니다. manifest 검사는 인용된 테스트의 존재만 확인할 뿐 그 차원을 단언하는지는 확인하지 않습니다. |
| 2026-08-14 | in-progress | 이전 이력을 재구성하지 않고 구현 원장을 도입했으며 실행 가능한 측정 mechanics를 입증되지 않은 결과 주장과 분리했습니다. | `current change`; 위에 인용한 측정 소스, 집중 테스트, 시나리오 매니페스트 및 헌법 레지스터입니다. | 시나리오 커버리지를 완료하고 권위 있는 결과 종결을 포함한 실제 운영 기준선 및 처리 집단을 보존합니다. |
| 2026-08-18 | in-progress | `sre` 능력 팩에 첫 시나리오를 부여해 `missing` 상태인 팩이 사라졌습니다. 고정 시나리오 3개가 제공되는 카탈로그로 실제 컨트롤 루프를 재생합니다. `kubernetes-cluster.diagnostic-settings-required`를 발화시켜 shadow PR을 여는 관측 가능성 전제 조건, 모델링되지 않은 대상의 error budget 소진이 abstain하고 아무것도 발행하지 않는 경우, 검토된 상한을 넘는 텔레메트리 보존입니다. 도메인마다 하나씩 배치해 균형 검사를 만족시킵니다. `unknown_or_deny`와 `deterministic_replay_with_evidence`만 주장했습니다. 나머지 네 차원은 근거가 없어 팩은 `partial`, 집합은 `incomplete`로 유지합니다. | `current change`, `tests/scenarios` focused 테스트 98건 통과. 신규 재생 3건 모두 제공되는 규칙·정책·ActionType으로 `ControlLoop.process`를 통과했습니다. | 모든 팩에 대해 successful-full-loop, cross-objective-conflict, partial-failure-recovery, A3-E 또는 비해당 사례를 작성해야 합니다. full-loop 주장에는 shadow 실행이 제공하지 않는 독립 효과 검증이 추가로 필요합니다. |

### 남은 작업

- [ ] 독립적이고 권위 있는 복구 및 재발 종결 근거로 SRE `successful_full_loop`를 완료하고, 시나리오가 생성한 경쟁 작업을 프로덕션 중재 경로에서 감사해 `cross_objective_conflict`를 완료합니다.
- [ ] ARB / 변경 안전성, FinOps / 비용 거버넌스, DR 및 Chaos Engineering 묶음에 실행 가능한 헌법상 6개 차원을 모두 갖춥니다.
- [ ] 동일한 고정 시나리오 집합에서 표본 크기, 신뢰 구간, 절대값 및 지원되지 않는 배수 주장이 없는 하나의 참조 기준선과 FDAI 처리를 보존합니다.
- [ ] 실제 운영 인시던트, 변경, 비용, 사람 터치포인트 및 독립적으로 검증된 결과 기록을 KPI 변환 결과에 연결한 다음 모든 임계값 0 가드가 0을 유지함을 입증합니다.
- [ ] 독립적인 검증기 레지스트리를 런타임 조립에 연결하고 남은 모든 직접 상태 의사 결정 경계에서 `DecisionCriticalEvidenceReceipt`와 `DecisionEvidenceVerificationBundle`을 사용하며 프로덕션 시작, 운영 준비 상태, qualification, 승격, 쿼리 및 상태 묶음을 보존한 다음 합성 또는 불완전 근거가 실제 운영 주장을 충족하지 못함을 입증합니다.
- [x] 공급자 중립 `OperationalCoverageReceipt`를 정의하고 집중 테스트를 통해 분모,
  처리 결과, 최신성, 임계값, 무관용 조건 및 다이제스트 불변 조건을 입증합니다.

## 주요 목표(기본 목표)

3개 초기 버티컬(복원력, 변경 안전성, 비용 거버넌스)을 가진 AIOps 접근에서 클라우드
운영의 사람 검토를 최소화 - 대부분의 이벤트를 결정론적(T0/T1)으로 해결하고 LLM 추론(T2)은
잔여 모호한 소수에 한정하며, **가드 메트릭을 회귀시키지 않은 채로** 달성합니다. 성공 메트릭을
개선하면서 가드 메트릭을 악화시키는 자율성은 실패이지 승리가 아닙니다.

SRE는 세 버티컬 전체의 운영 모델입니다. 재해 복구와 Chaos Engineering은 복원력
기능이고, 아키텍처 검토 Board 거버넌스는 도메인 전체에 적용되며, FinOps는 비용
거버넌스 규율입니다.

### 정확성 계약

FDAI는 모든 새로운 진단이 맞는다고 주장하지 않습니다. 목표는 **100% contract-conformant
행동**입니다. 에이전트는 schema-valid, evidence-supported, authorized 결과를 만들거나
명시적인 알 수 없음, no-op, denial, 롤백 또는 사람 검토 결과를 기록합니다. 강제 답변이
아니라 unsafe guess 0건이 플랫폼 목표입니다.

다음 위반의 release 임계값은 정확히 0입니다.

- 잘못된 객체 신원 또는 stale 대상 개정 번호를 대상으로 한 액션
- 등록된 ActionType, standing 권한 또는 영향 범위 밖의 실행
- 독립적인 효과 검증 없이 브로커/API 증적으로 성공을 주장하는 경우
- 권위 있는 관측이 아닌 온톨로지 쓰기로 외부 상태를 주장하는 경우
- 검토와 승격 근거 없이 권한을 높이는 learning 출력

### 커버리지 주장 계약

FDAI는 관리되는 각 전체 집합마다 변경할 수 없는 `OperationalCoverageReceipt` 하나를
사용해 운영 커버리지를 보고합니다. 지원 도메인은 자산 인벤토리, 거버넌스 평가, 운영 범위,
인시던트 진단, 수정 효과 및 지식 근거 확인입니다.

각 증적은 범위, 분모 및 근거를 다이제스트로 고정합니다. 모든 분모 항목에는 `covered`,
`unknown`, `stale`, `unsupported`, `inaccessible`, `conflicting` 또는 `invalid`라는 최종
커버리지 처리 결과 하나가 지정됩니다. 거버넌스 결과가 준수 또는 미준수여도 현재 근거로
평가했다면 `covered`일 수 있습니다. 정책 결과와 FDAI가 항목을 평가했는지는 서로 구분합니다.

증적은 정수 베이시스 포인트로 커버리지를 계산합니다. 모든 분모 항목이 계산되고, 평가 시점에
근거가 최신이며, 커버된 개수가 구성된 임계값을 충족하고, 구성된 모든 무관용 처리 결과가
0건일 때만 목표를 충족할 수 있습니다. 이 증적은 측정 근거일 뿐 승인, 변경 또는 실행 권한을
부여하지 않습니다.

### 사람 검토 전 자율 처리

해결되지 않은 이벤트를 즉시 사람 작업으로 만들지 않습니다. 범위가 제한된 기한 안에서 fresh 근거
acquisition, alternate 권위 있는 출처, 결정론적 reevaluation, 검증된 pattern reuse,
더 작은 safe 계획, no-op 또는 pre-authorized 복구를 시도합니다. 모호함이 남거나 정책이
승인을 요구하거나 risk가 standing 권한을 넘을 때만 사람 검토를 시작합니다. 모든 시도는
이벤트 상관관계를 공유하고 추가 human touchpoint를 만들지 않습니다.

## 정의(Definitions)

메트릭 전반에서 사용되는 용어를 여기서 고정해 모호성을 없앱니다:

- **Event**: `event-ingest` 이후 컨트롤 루프에 들어가는 정규화·중복제거된 한 항목. 안정적인
  멱등성 키로 식별됩니다. 이벤트당(비율) 계산은 모두 이 단위 위에서 이루어집니다.
- **시나리오 집합**: SRE, ARB / 변경 안전성, FinOps / 비용 거버넌스, DR 및 Chaos Engineering
  기능 묶음을 포괄하며 기준선과 처리에 동일하게 사용하는 고정된, versioned
  수집입니다. 각 release는 시나리오 집합 및 묶음별 버전을 기록합니다(예: `v2026.07`).

> **현재 커버리지 공백:** `services/core-control-plane/tests/scenarios/manifests/v2026.07.json`은 모든 고정본을 SRE, ARB /
> 변경 안전성, FinOps, DR 또는 Chaos에 할당합니다. 커버리지 dimension은 해당 묶음이 소유한
> 시나리오와 실제 실행 가능한 테스트를 함께 인용할 때만 계산됩니다. 집합은 `incomplete`입니다.
> SRE에는 실행 가능한 차원 4개가 있지만 성공적인 전체 루프와 목표 간 충돌 근거가 아직 없고,
> 나머지 4개 묶음도 하나 이상의 필수 사례를 누락합니다. 다섯 묶음이 모두
> 완전한일 때까지 완전한 도메인 커버리지를 주장하면 안 됩니다.
- **참조 에이전트**: 단계 0에서 측정된 고정 비교 시스템(문서화됨, 단일 모델, 티어링 없음).
  버전은 베이스라인 실행마다 고정됩니다.
- **Human touchpoint**: 사람의 결정 또는 입력이 필요한 모든 액션(HIL 승인, 수동 편집, 수동
  롤백). 고유하게 식별된 액션 또는 승인은 각각 한 번 계산하며, 같은 액션 또는 승인의
  반복 수명 주기 행은 touchpoint를 추가하지 않습니다. 하나의 이벤트가 둘 이상의 touchpoint를
  제공할 수 있습니다. 콘솔의 읽기 전용 조회는 touchpoint가 **아닙니다**.
- **Auto-resolved 이벤트**: 측정 윈도우 내에서 사람 터치포인트 0회, 사후 롤백 없이 종단의
  올바른 결과에 도달한 이벤트. 실행기 전달은 명시적인 `measurement.action_outcome.v1`
  기록이 강제 적용 모드, 검증 통과, auto 결정 및 롤백 없음으로 관측을 닫을
  때까지 resolved가 아니라 pending입니다.
- **측정 구간**: 실행당 고정된 관측 기간(기본값: 30일 롤링, 또는 전체 시나리오 세트
  1회 리플레이). 보고되는 모든 수치와 함께 명시됩니다.
- **Contract-conformant 결과**: 대상, 근거, 권한, 액션, 효과 검증, 감사
  기록이 exact versioned 계약을 충족하는 최종 결과입니다. 명시적 알 수 없음 또는 safe
  no-op은 conformant하지만 지원하지 않는 성공은 아닙니다.

## 성공 메트릭(성공 Metrics)

각 메트릭은 단위, 공식, 보고 윈도우를 고정합니다. 목표는 동일 시나리오 세트 버전에서 레퍼런스
에이전트 대비 상대값이며, 측정 전까지는 방향 목표(directional 대상)입니다.

| # | 메트릭 | 정확한 정의 | 단위 | 방향 | 베이스라인 대비 목표 |
|---|--------|------------|------|------|---------------------|
| 1 | 비용 per 단위 | 처리된 단위당 귀속 총 지출 ÷ 처리 단위 수. `$/incident`, `$/change`, `$/optimization`로 각각 계산 | USD/단위 | 낮을수록 좋음 | 큰 폭 감소 (측정된 경우에만 배수 명시) |
| 2 | Auto-resolution 비율 | 자동 해결된 이벤트 ÷ 총 이벤트 (`[0, 1]`) | 비율 | 높을수록 좋음 | 베이스라인의 5×(최대 1.0) |
| 3a | MTTR | 해결된 인시던트의 mean(resolve_time − detect_time) | 초 | 낮을수록 좋음 | 5× 짧게(베이스라인의 0.2×) |
| 3b | 변경 lead 시간 | 변경의 mean(merge_time − change_request_time) | 초 | 낮을수록 좋음 | 5× 짧게(베이스라인의 0.2×) |
| 4 | Human intervention | 사람 터치포인트 ÷ (총 이벤트 ÷ 100) | 100 이벤트당 터치포인트 | 낮을수록 좋음 | 베이스라인의 0.2×(즉 1/5) |

주의:
- 메트릭 1의 비용은 처리에 귀속되는 모델 추론, 컴퓨트, 저장소, 이벤트 버스 지출을 포함합니다.
  FDAI가 아닌 워크로드와 공유되는 고정 플랫폼 오버헤드는 제외합니다.
- MTTR과 lead 시간은 mean과 함께 **median과 p90**을 보고합니다. 지연 분포가 편향돼 있어 평균만
  으로는 꼬리(회귀)를 감춥니다.
- 비율(메트릭 2)에서의 `5×` 목표는 상한이 있습니다 - 배수와 절대 비율을 함께 보고합니다.
  베이스라인이 이미 높으면 배수는 의미가 없어지기 때문입니다.

## 가드 메트릭(회귀 금지)

가드 메트릭은 승격을 거부합니다: 위반이 발생하면 액션은 강제 적용에서 shadow로 강등됩니다. 각
메트릭은 방향이 아니라 명시적 임계값(임계값)을 갖습니다.

| 가드 메트릭 | 정의 | 임계값 |
|-------------|------|--------|
| 변경 실패 비율 (CFR) | 인시던트/롤백을 유발한 변경 ÷ 총 변경 | ≤ 베이스라인 CFR(증가 없음) |
| False-positive 비율 | 잘못된 액션 ÷ 실행된 액션 | ≤ 베이스라인. > 베이스라인 + 1pp면 알림 |
| False-negative 비율 | 놓친 진짜 이벤트 ÷ 진짜 이벤트 | ≤ 베이스라인. > 베이스라인 + 1pp면 알림 |
| Rollback 비율 | 롤백된 액션 ÷ 실행된 액션 | ≤ 베이스라인 롤백률 |
| Policy-violation escapes | 정책을 위반하고 강제 적용에 도달한 자율 액션 | **정확히 0**(모든 escape은 release-blocking) |
| Wrong-target 또는 stale-revision 실행 | 승인 계획과 다른 객체 또는 개정 번호에 적용된 액션 | **정확히 0** |
| 승인되지 않은 실행 | 등록 타입, 신원, standing 권한 또는 영향 범위 밖의 액션 | **정확히 0** |
| 검증되지 않은 성공 점유 | 독립적인 expected-effect 종결 없이 성공으로 보고된 액션 | **정확히 0** |

임계값은 성공 메트릭과 동일한 측정 윈도우와 시나리오 세트 버전에서 평가되어, 이득과 가드 위반이
다른 데이터에서 비교되지 않습니다.

## 선행 vs 후행 지표(Leading vs Lagging Indicators)

성공 메트릭 1-4는 **후행(lagging)** 입니다(충분한 이벤트가 해결된 후에만 관측 가능). 승격
결정은 가드-메트릭 건강을 더 일찍 예측하는 **선행(leading)** 지표도 함께 봅니다:

- 티어별 커버리지 비율(T0 70-80%, T1 15-20%, T2 5-10%)이 대역을 벗어남,
- mixed-model 불일치율(T2 quality 게이트)의 상승 추세,
- 검증기 abstain/fail 비율의 상승,
- 후보 액션의 shadow-vs-enforce 결정 다이버전스(divergence).

선행 지표는 후행 가드 메트릭이 회귀하기 전에 조사를 트리거합니다.

## Measurement-First 규칙

- 자율성은 자신의 효과를 측정할 원격측정(metrics 1-4 + 모든 가드 메트릭) 없이는 출시되지 않습니다.
- 단계 0가 KPI 대시보드와 레퍼런스 베이스라인을 **어떤 티어도 라이브 가기 전에** 확립합니다
  ([phase-0-instrumentation-ko.md](../phases/phase-0-instrumentation-ko.md)).
- 배수 주장(2-4)은 베이스라인과 트리트먼트가 **동일한 고정 시나리오 세트 버전에서** 모두
  측정된 후에만 언급됩니다.
- **통계적 타당성**: 각 배수는 표본 크기(이벤트 수), 신뢰구간, 시나리오 세트 버전과 함께
  보고합니다. 신뢰구간 안의 차이는 개선이 아니라 "측정된 변화 없음"으로 보고합니다. Zero-sample
  Wilson 간격은 accuracy가 정확히 0이라는 근거가 아니라 `[0, 1]` 알 수 없음입니다.
- **Operational 승격 근거**: 고정된 벤치마크와 live-shadow 샘플을 하나의 full FDAI
  개정 번호, ActionType 다이제스트, 시나리오 사례, 권위 있는 측정 단위에 연결하고 최신
  correction이 집단, 시나리오, 관측 시간, causal 계보를 바꾸지 않고 이전 행을
  대체합니다. Separate 고정된/실제 운영 Wilson 95% lower 한계, 서로 다른 실제 운영 일, zero escape,
  executed-action 롤백과 완전한 recurrence 구간, 검증된 causal 증적, Dynamic 검토가
  모두 통과해야 합니다. Closed causal 증적은 confirmed 종결일 때만 계산합니다. Raw 메트릭은
  promote할 수 없고 검증된 증적은 별도 검토만 허용합니다.
- **공정성**: 베이스라인과 트리트먼트는 동일한 시나리오, 동일한 입력 분포, 동일한 측정
  윈도우에서 실행합니다. 레퍼런스 에이전트를 의도적으로 불리하게 만들지 않습니다.

## 데이터 수집과 원격측정

모든 메트릭은 대시보드가 구축 가능하도록(열망만이 아닌) 구체적인 원격측정 소스에 매핑됩니다:

- **구조화된 이벤트 + 트레이스** (OpenTelemetry)가 `event_id`, `tier`, `decision`,
  `mode`(shadow/강제 적용), 타임스탬프를 운반 - 메트릭 2, 3a/3b, 선행 지표의 소스.
- **추가 전용 감사 로그**가 사람 터치포인트(메트릭 4), 롤백, 정책 escape의 소스.
- **결과 finalization 기록**(`measurement.action_outcome.v1`)가 auto-resolution의 권한입니다.
  Dispatch-only 이벤트는 pending으로 유지되고, 검증된 non-rollback 결과만 finalized denominator에
  들어가며, 롤백/adverse 결과는 성공이 되지 않고 계속 표시됩니다. 하나의 액션에
  correction finalization 행이 있으면 가장 높은 감사 순서만 권위 있으며, 명시적
  검증 실패는 사라지지 않고 rejected 관측으로 유지됩니다.
- **명시적 메트릭 관측값**은 각 `event_id` 및 메트릭 키의 최신 행을 사용합니다. 하나의 이벤트에
  대한 재시도 또는 correction은 통계 가중치를 추가하지 않고 이전 값을 대체하며, 서로 다른 이벤트의
  관측값은 독립 표본으로 유지합니다.
- **MTTR(메트릭 3a)** 은 순수 집계기
  [`core/measurement/mttr.py`](../../../services/core-control-plane/src/fdai/core/measurement/mttr.py) 가 계산합니다. 해결된
  인시던트(`resolved_at - opened_at`)를 **mean, median, p90** 초로 접습니다. 미해결/무결성
  위반 인시던트는 카운트하되 계산에서 제외하며, 절대 `0` 이나 음수 소요 시간을 기여하지 않습니다.
  라이브 인시던트를 공급해 `/kpi/autonomy` 패널의 synthetic 데모값을 대체하는 전달 레이어
  배선은 후속 작업으로 추적합니다.
- **비용/사용 기록**(모델 토큰, 컴퓨트 시간, 저장소, 버스 처리량)이 메트릭 1의 소스.
  귀속 키는 지출을 발생 `event_id`에 연결합니다. 하나의 액션에 반복된 수명 주기 행이 있으면
  재시도를 가중하거나 합산하지 않고 최신 관측 절감 값을 한 번만 반영합니다.
- 모든 메트릭 입력은 영문, 시크릿 없음, 고객-비종속 - 저장소 범위 규칙 준수.

## 리뷰 주기(검토 Cadence)

- **승격마다**: 메트릭 + 가드 리뷰가 통과하지 않으면 shadow → 강제 적용으로 이동하는 액션은 없음.
- **주간**: 선행 지표와 가드-메트릭 드리프트 대시보드 리뷰.
- **시나리오 세트 버전 갱신마다**: 목표가 오래된 것이 아닌 현재의 공정한 레퍼런스를 추적하도록
  전체 베이스라인 재측정.

## 목표 배수가 어디서 오는가

아래 메커니즘들은 목표 이득의 **가설(hypothesized)** 출처입니다. 각각은 베이스라인 대비
측정된 후에만 인정됩니다. 프레이밍은 의도적으로 "LLM을 더 잘 쓴다"가 아니라 "LLM을 **덜 쓴다**"
입니다.

| 목표 | 가설된 메커니즘 |
|------|-----------------|
| Auto-resolution ↑ | T0/T1이 이벤트의 ~85-90% 다수를 결정론적으로 종결; T2/HIL로의 에스컬레이션 감소. |
| MTTR / lead 시간 ↓ | T0/T1에는 LLM 라운드트립(ms-s)이 없음; auto-remediation PR이 사람 대기 시간을 제거. |
| Human intervention ↓ | 리스크 게이트가 저위험 액션을 자동 승인; 학습된 T1 액션이 반복 사람 터치를 회피. |
| 비용 per 단위 ↓ | 이벤트의 ~5-10%만 프론티어 모델에 도달; OSS/CSP-중립 스택; 이벤트-기반 scale-to-zero. |

> 핵심 통찰: 이득은 더 똑똑한 LLM이 아니라 **LLM을 덜 쓰는** 구조에서 온다는 가설이며 - 이
> 주장은 단계 0 측정으로 살거나 죽습니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 베이스라인 계기화 방식 | [phases/phase-0-instrumentation-ko.md](../phases/phase-0-instrumentation-ko.md) |
| 티어별 커버리지 목표와 trust 라우터 | [../../.github/instructions/architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) |
| 가드 메트릭이 강제하는 안전 불변식 | [../../.github/instructions/coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md) |
| P0와 함께 배송되는 KPI 대시보드 | [../dashboards/phase-0-kpi.json](../../dashboards/phase-0-kpi.json) |
