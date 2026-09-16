---
title: 근본원인 분석
translation_of: root-cause-analysis.md
translation_source_sha: 6ceb6a5aa767251db3bd86d3e74a39efa7992924
translation_revised: 2026-09-16
---
# 근본원인 분석

이 문서는 근본원인 분석(RCA)을 기존 trust 티어가 생성하는 인용 가능하고 범위가 제한된 가설로
정의합니다. RCA는 인시던트를 설명하지만 승인 또는 실행 권한을 부여하지 않습니다.

> **안전 경계:** 결정론적 검증, 정책, what-if, risk, 승인, 실행 및 효과 관측은 모든 RCA
> 가설보다 높은 권위를 유지합니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| T0, T1, T2 가설 계약 및 grounding | implemented | `services/core-control-plane/src/fdai/core/rca/`, 집중 RCA 테스트 | T0 규칙 원인, stale-safe T1 재사용, 결정론적 인과사슬, 형식화된 원인 영역 및 grounded T2 parsing을 구현했습니다. |
| Knowledge 근거 및 프로바이더 연결 | implemented | `core/rca/knowledge_evidence.py`, `shared/providers/knowledge.py`, `delivery/pgvector/knowledge.py`, `delivery/azure/llm/rca_model.py`, `runtime/bootstrap.py`, 집중 프로바이더, 어댑터 및 런타임 테스트 | 런타임은 Azure LLM 초기화 이후와 원격 측정 전용 모드 모두에서 구성된 pgvector 소스를 연결합니다. 다시 수집하면 문서 조각을 원자적으로 교체하고 빈 교체는 삭제하므로 오래된 개정이 검색 결과에 남지 않습니다. 연결이 없을 때는 근거를 만들어 내지 않습니다. |
| 관리되는 자동 Incident RCA 맥락 | implemented | `delivery/persistence/postgres_governed_document_read.py`, `delivery/governed_rca_context.py`, `runtime/governed_rca.py`, 자동 T2 및 맥락 테스트 | 완전한 배포 바인딩이 별도 읽기 전용 DSN, 컬렉션, 접근 참조, 읽기 그룹을 제공합니다. 자동 Incident T2는 고정된 Forseti 주체와 `incident-review` 목적을 사용하고 인시던트, 리소스, 기준 시각, 온톨로지, 카탈로그 신원을 결속하며 권한 있는 문서 근거가 없으면 판단을 보류합니다. |
| Azure 배포 이력 및 의존성 맥락 | implemented | `delivery/azure/deployment_history.py`, `delivery/persistence/postgres_provider_identity.py`, `runtime/rca_bindings.py`, topology history, 프로바이더, 런타임 및 control-loop 테스트 | 전용 Monitoring Reader가 이벤트 기준 시각의 인벤토리 세대에서 프로바이더 신원을 해석합니다. 런타임은 같은 기준 시각의 bitemporal topology를 구성하고 세대가 일치하는 성공한 정확한 범위 변경만 허용하며, 재개 lifecycle을 지원하고 맥락, 분석 및 감사를 하나의 side-path deadline으로 제한합니다. |
| Azure Monitor 원격 측정 경로 및 모델 안전 fact | implemented | `delivery/azure/telemetry_workspace.py`, `delivery/azure/telemetry_query.py`, `core/rca/evidence.py`, `delivery/azure/llm/rca_model.py`, 집중 작업 영역, KQL, RCA, control-loop 및 런타임 테스트 | 이벤트 시각 인벤토리 신원으로 전용 판독기 아래의 정확한 Diagnostic Settings 및 작업 영역 기반 Application Insights 경로를 선택합니다. 발견한 작업 영역은 최대 3개이고 명시적 대체 경로 하나를 추가할 수 있습니다. T2는 범위가 제한된 fact token과 불투명한 인용만 받으며 이 원격 측정 경로의 원시 로그 본문은 받지 않습니다. |
| 적응형 telemetry recipe 조사 | implemented | `core/rca/telemetry_evidence.py`, `core/rca/telemetry_recipes.py`, `core/read_investigation/telemetry_adaptive.py`, `delivery/azure/telemetry_recipe_query.py`, `runtime/adaptive_telemetry.py`, 집중 Core, Azure, Process, Operator, Pantheon 및 Console 테스트 | Forseti는 기존의 범위가 제한된 적응형 Process를 통해 검토된 recipe id만 선택합니다. Heimdall은 타입이 지정된 완전성 증적을 제공하고 Saga는 재생 근거를 보존하며, 완전한 양성 증적만 T2 근거가 될 수 있습니다. 원시 KQL은 운영자 전용으로 유지합니다. |
| 분산 추적 원인 구분 | implemented | `core/rca/trace_continuity.py`, `tests/core/rca/test_trace_continuity.py` | 독립적으로 인용된 신호 하나로 계측, 수집기 또는 헤더 전파 원인을 구분할 수 있습니다. 근거가 없거나 충돌하거나 범위가 일치하지 않으면 검토를 위해 판단을 보류하며 결과에는 수정 참조가 없습니다. |
| 읽기 전용 운영자 프로젝션 | implemented | `services/operator-service/src/fdai_operator_service/rca_projection.py`, 집중 프로젝션 테스트 | 작업 권한 없이 감사 가설, 인용, 구조화된 인과사슬 및 연결된 대응 계획을 프로젝션합니다. |
| 통제된 운영 RCA 정확도 | in-progress | [관측성과 감지](observability-and-detection-ko.md#구현-상태) | 티어 혼합 전체에서 실제 원인 정확도, 판단 보류 및 downstream 결과 종결을 입증하는 exact-revision cohort가 없습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-09-16 | implemented | 검토된 telemetry recipe 카탈로그를 기존 적응형 조사 Process, 정확한 이벤트 시각 Azure 작업 영역 라우팅, 완전성을 인식하는 Forseti 개정, Saga Process 근거, Operator 변환 결과 및 이중 언어 Console 조사 공간에 연결했습니다. 원시 KQL은 서술기와 Pantheon의 모델 노출 도구에서 제외했습니다. 집중 비평 10회를 완료해 원시 조회 권한 노출, 버전 없는 정책 신원, 메타데이터 대체, 취소 누출, no-data 근거화, 재생 불안정 deadline과 인용, 비활성 운영 연결, 모듈 소유권, 변환 및 지역화 공백을 수정했습니다. 이 범위에는 Low를 넘는 finding이 남아 있지 않습니다. | `current change`; 집중 Core, Azure, Process 재생, 제어 루프, Pantheon, Operator, Console 모델/i18n/typecheck 및 1440/993/390 Playwright 검사 통과. | 운영 검증을 주장하기 전에 거버넌스를 따르는 live multi-workspace 증적과 정확한 개정의 원인 정확도 cohort를 보존합니다. |
| 2026-09-16 | implemented | 정확한 head의 CI가 정규식을 검토되지 않은 lexical 분류기로 올바르게 탐지한 뒤 범위가 제한된 로그 fact reducer를 검토된 typed-evidence 경로로 등록했습니다. 이 reducer는 `LogRecord` 하나만 받고 운영자 발화를 받지 않으며 의도 또는 권한을 선택할 수 없습니다. Semantic-routing 감지기는 변경하지 않았습니다. | PR #1145 CI run `35054516295`, attempt 1, regression shard 3/4 job `104662007669`, exact semantic-routing 및 typed-input 회귀 검사. | 병합 전에 새로운 정확한 head의 CI를 요구합니다. 실제 다중 작업 영역 근거는 별도입니다. |
| 2026-09-16 | implemented | 이벤트 시각 Azure 리소스 신원을 Diagnostic Settings 및 작업 영역 기반 Application Insights 발견에 연결하고, 정확한 리소스 및 시간 필터로 개수가 제한된 작업 영역 집합을 조회하며, 관리되는 문서 구성과 독립적으로 모델 안전 원격 측정 fact token을 제공했습니다. 신원, ARM 응답 무결성, 경로 상한, KQL 의미 체계, 이벤트 시각, 부분 근거, 정보 공개, 결정성, 취소, 소버린 클라우드, 런타임 동등성 및 형식을 대상으로 12회의 비평 및 하드닝을 완료했습니다. 이 과정에서 엄격한 ARM 및 Diagnostic Settings 신원 검사, 대소문자가 같은 경로 중복 제거, 대체 경로를 포함한 상한, 이스케이프 후 KQL 상한, 표지 오탐 및 인용 신원 충돌을 수정했습니다. 보고된 상위 심각도 가설 두 개는 매핑이 아닌 payload가 멤버 접근 전에 이미 실패하고 KQL `=~`가 정규식 연산자가 아니라 대소문자를 무시하는 동등 비교이므로 기각했습니다. 이 제한된 범위에는 Low를 넘는 발견 사항이 남아 있지 않습니다. | `current change`; 집중 RCA, Azure KQL, 조립, control-loop 및 런타임 테스트 483건 통과, 새 resolver branch coverage 99.16%, 작업 범위 Ruff 및 strict mypy 통과. | 통제된 실제 다중 작업 영역 RCA 증적을 보존하고 원인 정확도 및 판단 보류 결과를 정확한 개정 번호의 운영 cohort에 포함합니다. |
| 2026-09-09 | implemented | 분산 추적 불연속을 위한 결정론적 T1 구분을 추가했습니다. 분류기는 범위가 제한된 원격 측정 신호 하나만 받고, 영향을 받은 홉 또는 경계가 감지 결과와 일치하는지 확인하며, 연속성 근거와 원인 근거를 모두 인용하고, 수정 참조를 반환하지 않습니다. | `current change`; 집중 추적 RCA 검사 9건, 새 Core 범위의 Ruff 및 strict mypy가 통과했습니다. | 권위 있는 계측, 수집기, 헤더 전파 근거 생산자를 연결한 후 #142에서 추적하는 통제된 실제 cohort를 보존합니다. |
| 2026-09-09 | implemented | 범위가 제한된 추적 원인 항목과 인용을 표준화하고 공백, 중복, 전체 텍스트 상한 초과를 차단했습니다. | `current change`; 집중 추적 RCA 정규화 검사. | 범위가 제한된 추적 RCA 비평 캠페인을 계속합니다. |
| 2026-09-09 | implemented | 추적 원인 근거를 정확한 토폴로지, 시나리오, 구간, 관측 시각에 결속하여 인용을 다른 인시던트나 이후 근거에 재사용할 수 없게 했습니다. | `current change`; 집중 범위 및 시각 replay 검사. | 범위가 제한된 추적 RCA 비평 캠페인을 계속합니다. |
| 2026-09-09 | implemented | 잘못된 구성이 항상 명시적으로 실패하도록 추적 RCA 신뢰도 하한 검증을 모든 조기 판단 보류보다 앞에 배치했습니다. | `current change`; 집중 잘못된 신뢰도 회귀 검사. | 범위가 제한된 추적 RCA 비평 캠페인을 계속합니다. |
| 2026-09-09 | implemented | 결합된 연속성 및 원인 인용 집합에 100개 참조 상한 하나를 적용하고 초과분을 자르는 대신 판단을 보류했습니다. | `current change`; 집중 결합 인용 상한 초과 검사. | 범위가 제한된 추적 RCA 비평 캠페인을 계속합니다. |
| 2026-09-09 | implemented | 감지기가 문제가 있는 홉을 식별하지 않으므로 홉 순서 발견에 대한 지원되지 않는 계측 원인 배정을 제거했습니다. | `current change`; 집중 잘못된 홉 순서 판단 보류 검사. | 범위가 제한된 추적 RCA 비평 캠페인을 계속합니다. |
| 2026-09-09 | implemented | 끊긴 경계만으로 소유권을 입증할 수 없으므로 헤더 전파 원인 영역을 애플리케이션에서 `unknown`으로 낮췄습니다. | `current change`; 집중 헤더 영역 회귀 검사. | 범위가 제한된 추적 RCA 비평 캠페인을 계속합니다. |
| 2026-09-09 | implemented | 고정 추적 원인 신뢰도를 유한한 근거 점수로 바꾸고 grounding 하한 전에 T1 상한을 적용했습니다. | `current change`; 집중 신뢰도 상한 및 판단 보류 검사. | 범위가 제한된 추적 RCA 비평 캠페인을 계속합니다. |
| 2026-09-09 | implemented | 일치하는 구간 레이블이 오래된 원격 측정을 허용하지 않도록 기본 5분의 양수 원인 근거 유효 기간을 추가했습니다. | `current change`; 집중 오래된 근거 및 잘못된 유효 기간 검사. | 범위가 제한된 추적 RCA 비평 캠페인을 계속합니다. |
| 2026-09-09 | implemented | 큰 양수 값으로 오래된 근거 방어를 비활성화할 수 없도록 구성된 추적 원인 근거 유효 기간을 24시간으로 제한했습니다. | `current change`; 집중 근거 유효 기간 상한 검사. | 범위가 제한된 추적 RCA 비평 캠페인을 계속합니다. |
| 2026-09-09 | implemented | 신뢰도 0인 근거가 grounded 원인을 만들 수 없도록 추적 전용 기본 신뢰도 하한을 0에서 `0.5`로 높였습니다. | `current change`; 집중 신뢰도 0 판단 보류 검사. | 범위가 제한된 추적 RCA 비평 캠페인을 계속합니다. |
| 2026-09-09 | implemented | 추적 RCA 비평 12회를 완료했습니다. 10개의 실질 수정으로 원인 근거를 표준화하고 제한했으며, 교차 범위 및 오래된 replay를 방지하고, 판단 보류 전에 신뢰도를 검증하고, 결합 인용을 제한하고, 지원되지 않는 홉 순서 원인 배정을 차단하고, 경계 소유권 주장을 제거하고, 근거 신뢰도와 유효 기간을 제한하고, 0이 아닌 기본 신뢰도 하한을 요구했습니다. 형식화된 감지기 생산자와 의도적으로 비어 있는 수정 참조를 추적한 뒤 두 가설은 기각했습니다. 이 제한된 범위에는 Low를 넘는 발견 사항이 남아 있지 않습니다. | `current change`; 전체 RCA, 감지기, 인시던트 연결 범위 294건 통과; RCA 소스 26개 파일 strict mypy 통과; Ruff 통과. | 권위 있는 원인 근거 생산자를 연결하고 #142에서 관리하는 실제 cohort를 보존합니다. |
| 2026-09-04 | implemented | T1을 historical 인벤토리 신원, append-only topology history, canonical lifecycle Incident 매칭, 전용 reader RBAC, sovereign endpoint/audience 결합 및 전체 side-path timeout을 사용하는 event-time 맥락으로 보강했습니다. Split 배포는 정확한 platform reader identity를 hydrate하고 guard합니다. | `current change`; 집중 RCA 프로바이더, 멤버, topology, timeout, hydration, plan guard, Terraform, Ruff 및 strict mypy 검사, 잔여 하드닝 라운드 1-4, 11-12, 15-16, 22-29, 32-42. | 관리되는 exact-revision 운영 cohort를 보존합니다. |
| 2026-09-04 | implemented | 자동 Incident T2를 서버 소유의 관리되는 문서 맥락에 연결했습니다. 별도의 읽기 전용 PostgreSQL 어댑터가 lexical ranking 전에 컬렉션과 접근 참조를 필터링하고 불변 메타데이터와 정확한 읽기 그룹을 다시 확인한 뒤 인시던트, 리소스, 목적, 기준 시각, 릴리스 및 주체에 결속된 맥락을 기존 문서 근거 검증기에 전달합니다. 문서나 접근 권한이 없으면 다른 인용으로 계속하지 않고 T2 판단을 보류합니다. | `current change`; 집중 관리 맥락, 자동 T2, 문서 근거, Ruff, strict mypy 및 Core 서비스 Terraform 검사가 통과했습니다. | 관리되는 운영 RCA cohort와 배포된 문서 읽기 증적을 보존합니다. |
| 2026-09-04 | implemented | T1 RCA를 정확한 Azure Activity Log 변경과 완전하고 최신인 의존성 그래프에 연결했습니다. 어댑터는 서버 소유 인벤토리에서 중립 ID를 해석하고, 호출자 신원을 해시하며, 읽기 작업, 실패, 범위 이탈, pagination 상한 초과, 오래된 신원 및 그래프 세대 변경을 차단하고 모든 결과를 shadow로 유지합니다. | `current change`; 집중 Azure 배포 이력, 의존성 세대, 멤버 출처 및 control-loop 테스트 28건, Ruff, strict mypy가 통과했습니다. | 정확한 개정 번호의 운영 cohort와 독립적으로 검증한 결과를 보존합니다. |
| 2026-09-04 | implemented | 모든 RCA 가설에 하위 호환 가능한 원인 영역 분류를 추가했습니다. T0는 검토된 구성 위반을 기본적으로 인프라로 분류하고, T1은 루트 변경의 영역을 보존하며, T2는 지원되는 enum 값 하나만 제안할 수 있습니다. 이전 레코드는 `unknown`으로 유지됩니다. 감사, 보고, Operator 및 Console 프로젝션은 작업 권한을 부여하지 않고 값을 보존합니다. | `current change`; 집중 Core RCA, Azure 어댑터, Operator 프로젝션, Console decoder 및 타입 검사입니다. | 기본값이 아닌 영역을 제공할 수 있도록 배포 이력과 현재 그래프 근거를 연결한 후 통제된 운영 cohort를 보존합니다. |
| 2026-08-29 | implemented | 강화 라운드 6에서 KnowledgeSource 관점 26개를 검토하고 pgvector 직렬화 전에 유한하지 않은 임베딩 값을 차단했으며, 참조 인덱스에서는 유한하지 않은 유사도를 0으로 처리했습니다. 잘못된 벡터가 비결정적 검색 순서를 만들 수 없습니다. | `current change`; 집중 KnowledgeSource 및 pgvector 테스트. | 배포가 소유하는 색인 문서를 대상으로 관리되는 RCA cohort를 보존합니다. |
| 2026-08-28 | implemented | 모델 초기화 이후에 영속 KnowledgeSource를 연결하도록 순서를 바꿨습니다. 이제 Knowledge DSN이 구성된 Azure LLM 모드에서 RCA가 기본 빈 소스에 남지 않습니다. 동일한 조건부 호출은 원격 측정 전용 모드와 로컬 모델 동작을 유지합니다. 메모리 및 pgvector 소스는 다시 수집을 완전한 교체로 처리하고, 임베딩에 실패하면 이전 개정을 보존하며, 오래된 조각을 제거하고, 문서별 트랜잭션 잠금 아래에서 빈 교체를 삭제로 처리합니다. | `current change`; `runtime/bootstrap.py`; `shared/providers/knowledge.py`; `delivery/pgvector/knowledge.py`; 집중 부트스트랩 및 런타임 구성 검사 42건 통과; 집중 KnowledgeSource 및 SQL 수명 주기 검사 21건 통과, 실시간 데이터베이스 동등성 검사 1건은 환경 조건으로 제외; Ruff 및 strict mypy 통과. | 배포가 소유하는 색인 문서를 대상으로 관리되는 RCA cohort를 보존하고 소스 연결기를 교체 계약에 연결합니다. |
| 2026-08-21 | in-progress | 런타임 동작이나 권한을 변경하지 않고 기존 RCA 티어, grounding, 인과사슬, knowledge 및 프로젝션 계약을 집중 소유 문서로 옮겼습니다. | `current change`; 문서 크기, 번역, 경로 및 링크 검사입니다. | 권위 있는 원인 및 결과 검토가 있는 통제된 운영 cohort를 보존합니다. |

### 남은 작업

- [ ] 통제된 실제 다중 작업 영역 원격 측정 증적을 포함하고 T0, T1, T2의 지원된 원인,
  판단 보류, stale 재사용 거부, 인용 유효성 및 독립적으로 검증된 결과를 측정하는
  exact-revision 운영 cohort를 보존합니다.

## 티어 계약

RCA를 암묵적 부작용이 아니라 티어의 일급 출력으로 만듭니다.

| 티어 | RCA 역할 |
|------|---------|
| **T0** | 직접 원인: 매칭된 규칙 또는 정책이 위반된 제어와 교정을 명명합니다. |
| **T1** | 상관관계 원인: 재검증된 해결 인시던트를 재사용하거나 범위가 제한된 상관 이벤트에서 결정론적 인과사슬을 재구성합니다. |
| **T2** | Reasoning 원인: 새로운 또는 모호한 인시던트에 대해 공급된 근거를 인용하고 quality gate를 통과하는 grounded 가설을 생성합니다. |

- RCA 출력은 권위 있는 결정이 아니라 **인용이 있는 가설**입니다. RCA 텍스트나 예보가 아니라
  결정론적 검증이 실행 자격을 부여합니다.
- T2에 공급되는 원격 측정 및 상관 이벤트는 신뢰할 수 없는 입력입니다. 검증기와 정책 재검사가
  모든 모델 텍스트보다 높은 권위를 유지합니다.
- T1 재사용은 이전 원인과 학습된 작업이 여전히 적용되는지 재검증합니다. 결과 작업은 risk gate
  전에 what-if를 실행하며 stale 학습 작업을 맹목적으로 재생하지 않습니다.
- 근거를 가질 수 없는 RCA는 사람 검토로 보냅니다.
- [상관된 인시던트](observability-and-detection-ko.md#1-이벤트-상관관계event-상관관계)가 RCA
  입력이므로 분석은 중복 폭풍이 아니라 인시던트 하나를 다룹니다.

## Azure Monitor 원격 측정 근거 확인

초기 설계는 T2가 구성된 Log Analytics 작업 영역 하나를 조회하고 일치한 원시 행을 모델에
전달하는 방식입니다. 이 방식은 수락하지 않습니다. 리소스는 진단 데이터를 다른 작업 영역으로
보낼 수 있고 목적지를 여러 개 구성할 수도 있습니다. 원시 로그 텍스트에는 자격 증명이나 개인
데이터가 포함될 수 있습니다. 잘못된 작업 영역을 성공적으로 조회하면 완전한 빈 근거처럼 보일
수도 있습니다.

개정된 설계는 출처 선택과 정보 공개를 결정론적으로 유지합니다.

1. Azure 전달 어댑터는 읽기 전용 Diagnostic Settings와 작업 영역 기반 Application Insights
  관계를 통해서만 정확한 ARM 리소스를 해석합니다. 서버에 구성된 작업 영역은 명시적인 대체
  경로로 유지합니다. 모델은 작업 영역, 리소스, 엔드포인트 또는 교차 범위 함수를 선택할 수
  없습니다.
2. 프로바이더 I/O 전에 경로 집합의 중복을 제거하고 개수 상한을 적용합니다. 잘못된 신원,
  모호한 목적지 메타데이터, 경로 상한 초과, 부분 응답 또는 사용할 수 없는 권한은 조회 범위를
  넓히는 대신 불완전한 근거를 만듭니다.
3. 검토된 KQL 변환 결과는 정확한 리소스와 시간 범위를 유지합니다. 프로바이더별 테이블과 열은
  Azure 전달 코드에 남고 코어는 클라우드 공급자 중립적인 로그 및 추적 레코드를 받습니다.
4. 원격 측정 후보는 불투명한 인용과 범위가 제한된 의미 fact token을 함께 전달합니다. Token은
  신호, 심각도, 출처, 지속 시간, 프로토콜 및 결정론적 원인 표지를 위한 고정된 기계 문법을
  사용합니다. 원시 로그 본문, 리소스 ID, 작업 영역 ID, URL, 주소 및 자격 증명 형태 값은 이
  원격 측정 경로를 통해 모델 요청에 들어가지 않으며 감사 행에도 들어가지 않습니다.
5. 원격 측정 수집은 관리되는 문서 가용성과 독립적입니다. 필수 관리 문서가 없으면 최종 RCA를
  계속 보류할 수 있지만 해당 구성으로 정확하고 범위가 제한된 원격 측정의 수집 여부를
  결정하지 않습니다.

이 경로는 읽기 전용과 shadow 전용으로 유지됩니다. 가설과 인용을 개선할 수 있지만 작업, 승인
또는 실행 권한을 부여하지 않습니다.

### 로그 조회 시점 결정

초기 자동 경로는 T0 또는 T1이 리소스에 결속된 사례를 종결하지 못할 때 기본 로그 및 추적 변환
결과를 모두 조회합니다. 대화형 `query_log` 화면은 별도로 운영자의 원시 KQL을 받습니다. 두 동작
모두 활성 가설을 구분하는 데 어떤 누락 근거가 필요한지 에이전트가 결정하게 하지 않으며, 원시
KQL을 모델에 노출하면 신뢰할 수 없는 텍스트가 프로바이더 작업으로 바뀝니다.

개정된 경로는 타입이 지정된 `TelemetryEvidenceNeed`를 사용합니다. 현재 근거가 `missing`,
`partial`, `no_data`, `timed_out`, `unauthorized`, `unavailable` 중 하나를 선언한 뒤에만 Forseti가
카탈로그에 있는 recipe 식별자를 선택할 수 있습니다. Heimdall은 출처 완전성 레코드를 제공합니다.
요청은 인시던트, 정확한 리소스, 근거 기준 시점, lookback 프로파일, 예상 출력 스키마, 조회 및 비용
예산과 멱등성 키를 고정합니다. KQL, 작업 영역 식별자, 엔드포인트, 테이블 이름 또는 호출자가
제공한 필터 텍스트는 포함하지 않습니다.

Azure 전달 어댑터는 정확한 작업 영역을 해석한 뒤 recipe 식별자를 검토된 KQL로 컴파일합니다.
결과는 범위가 제한된 fact token과 경로 수, 행 수, 지연 시간, 잘림, 최신성, 완전성 및 예상 비용
단위를 포함한 출처 증적 하나를 반환합니다. 출처가 없거나 실패해도 빈 정상 관측으로 바뀌지
않습니다. 기존 원시 `query_log` 명령은 운영자 진단 화면으로 유지하며 Pantheon 자율 도구로
등록하지 않습니다.

런타임은 정확한 Azure telemetry 라우팅을 사용할 수 있으면 이 shadow 읽기 경로를 자동으로
연결합니다. `FDAI_RCA_ADAPTIVE_TELEMETRY_ENABLED=false`는 이를 비활성화하는 배포 상한입니다.
선택적인 `MAX_ROUNDS`, `MAX_QUERIES`, `MAX_COST_UNITS`, `DEADLINE_SECONDS` 접미사 설정은 서버
소유 상한을 더 좁힙니다. 잘못되거나 과도한 값은 시작에 실패합니다. 구성 버전, recipe 카탈로그
다이제스트, 상한, 근거 기준 시점 및 최종 사용량은 재생에 안정적인 Process 근거로 남습니다.

## 원인 영역

모든 가설은 `infrastructure`, `application`, `shared_dependency`, `external_provider`, `mixed`,
`unknown` 중 하나의 형식화된 운영 영역을 가집니다. 이 필드는 인용된 가설을 분류합니다.
최종 인시던트 판정이 아니며 작업 권한을 부여하지 않습니다.

T0 구성 규칙 원인은 기본적으로 `infrastructure`를 사용하며, 더 강한 검토 근거가 있는 호출자는
더 구체적인 영역을 제공할 수 있습니다. T1은 루트 변경 이벤트의 영역을 사용하고 해결된 사례를
재사용할 때도 이를 보존합니다. T2는 선언된 enum 값만 반환할 수 있습니다. 값이 없으면
`unknown`을 유지하고 지원되지 않는 값은 parser가 검토 대상으로 보류합니다. 이 필드가 없는
기존 감사 레코드는 `unknown`으로 프로젝션됩니다.

## 분산 추적 원인 구분

연속성 감지기는 관측된 형태만 보고하며 원인을 추측하지 않습니다.
`core/rca/trace_continuity.py`의 결정론적 T1 분류기는 감지 결과와 독립적인
`TraceCauseEvidence` 신호 하나만 받습니다.

| 원인 | 필요한 일치 조건 |
|------|------------------|
| `instrumentation` | 인용된 영향 홉이 컨텍스트 유실 결과에서 누락되었습니다. |
| `collector` | 인용된 수집기 근거가 컨텍스트 유실 결과에서 누락된 홉만 지목합니다. |
| `header_propagation` | 인용된 경계가 컨텍스트 재생성 결과에서 끊겼거나 컨텍스트 유실 결과의 누락 홉에 인접합니다. |

신호와 감지기 인용은 모두 `telemetry` 참조입니다. 신호가 없거나 두 개 이상이거나 범위가
일치하지 않거나 결과가 불연속이 아니면 명시적인 판단 보류 결과를 만듭니다. 근거가 있는 결과는
범위가 제한된 신뢰도의 T1 티어와 `remediation_ref=None`을 사용합니다. 관측된 원인을 설명하지만
복구 작업을 선택하거나 승인할 수 없습니다. 영향 항목과 근거 참조는 앞뒤 공백, 중복, 전체 텍스트
상한 초과를 차단한 후 표준 정렬 순서를 사용합니다. 따라서 같은 근거는 재현 가능한 가설 하나를
만듭니다.
잘못된 홉 순서 결과는 문제가 있는 홉을 식별하지 않습니다. 따라서 이 분류기는 임의의 관측 홉에
계측 원인을 배정하지 않고 판단을 보류합니다.
계측은 애플리케이션 원인 영역에, 수집기 손실은 공유 의존성 영역에 매핑합니다. 헤더 전파는 경계
정보만으로 어느 쪽이 결함을 소유하는지 입증할 수 없으므로 `unknown`으로 유지합니다.
각 원인 신호는 정확한 토폴로지, 시나리오, 관측 구간, 시간대가 있는 관측 시각에도 결속됩니다.
다른 범위의 신호나 연속성 결과보다 나중에 관측된 신호는 재사용할 수 없습니다.
원인 관측은 양수로 구성된 근거 유효 기간 안에도 있어야 하며 기본값은 5분입니다. 따라서 복사한
구간 레이블로 오래된 원격 측정을 다시 사용할 수 없습니다. 구성 상한은 24시간이므로 큰 양수
값으로 오래된 근거 방어를 비활성화할 수도 없습니다.
신뢰도 하한은 모든 판단 보류 결과보다 먼저 검증합니다. 따라서 잘못된 구성이 누락되거나 충돌한
근거 뒤에 숨지 않습니다.
원인 근거는 `[0, 1]` 범위의 유한한 신뢰도를 포함합니다. 가설은 이 값과 T1 상한 `0.85` 중 낮은
값을 사용한 후 기본값이 `0.5`인 신뢰도 하한을 적용합니다.
중복을 제거한 연속성 및 원인 인용은 하나의 100개 참조 상한을 공유합니다. 상한을 넘으면 가설의
grounding에 사용한 근거 집합을 자르지 않고 판단을 보류합니다.

## 업스트림 구현

`core/rca/`는 RCA 계약(`RootCauseHypothesis`, `Citation`), 결정론적 T0 원인
(`t0_root_cause`), grounding gate(`enforce_grounding`)를 제공합니다. Grounding이 없거나 신뢰도
미만인 가설은 사람 검토로 보냅니다. `RcaReasoner` Protocol은 선택적 T2 경계입니다. 업스트림
`core/rca/llm.py`는 `LlmRcaReasoner`와 `RcaModel` 경계를 제공합니다. 결정론적 parser는 잘못된
답변, 만들어 낸 인용, grounded되지 않은 답변을 거부합니다.

Azure 연결은 `delivery/azure/llm/rca_model.py`의 `AzureOpenAIRcaModel`입니다. Managed identity
토큰으로 Azure OpenAI를 호출하고 업스트림 parser가 검증할 raw JSON을 반환합니다. Composition
root는 `resolved-models.json`의 `t2.rca` 기능에서 이를 연결합니다. 기능 또는 prompt가 없으면
`LlmBindings.rca_reasoner = None`으로 남으므로 T2 RCA를 사용할 수 없고 T0는 계속 동작합니다.
모델 초기화 후 런타임 부트스트랩은 `FDAI_KNOWLEDGE_DSN` 또는 `FDAI_STATE_STORE_DSN`을 사용할
수 있을 때 구성된 pgvector KnowledgeSource를 연결합니다. 이 순서는 Azure LLM, 원격 측정 전용,
로컬 모델 모드에 적용되며 DSN이 없을 때 빈 소스를 사용하는 안전한 대체 동작을 유지합니다.

`RcaCoordinator`는 T0, stale-safe T1 상관 재사용, 인용 범위가 제한된 T2를 조정합니다.
`ControlLoop`은 발견마다 상관된 `incident_id`를 포함하는 결정론적 T0 `rca.hypothesis` 감사
항목을 추가합니다. 연결된 T2 reasoner는 새로운 사례에 grounded 가설 또는 판단 보류 하나를
추가합니다. 이는 "왜"에 대한 설명이며 새 실행 경로가 아닙니다.

Azure Monitor를 구성하면 Azure LLM 모드와 원격 측정 전용 모드에서 같은 프로바이더 연결을
사용할 수 있습니다. 표준 런타임 조립은 이벤트 시각 인벤토리 신원 resolver와 전용 Monitoring
Reader를 재사용하여 API 버전 `2021-05-01-preview`로 Diagnostic Settings를 발견하고, 작업 영역
기반 Application Insights를 해석하며, 각 Log Analytics 작업 영역 customer ID를 가져옵니다.
외부 RCA side-path deadline이 전체 발견 및 KQL 순서를 제한합니다. 인벤토리 신원, 판독기 권한,
완전한 ARM 응답 또는 범위가 제한된 경로 집합이 없으면 원격 측정을 사용할 수 없습니다. 정적
`FDAI_MONITOR_WORKSPACE_ID` 경로는 마지막 명시적 대체 경로로 유지되며 교차 작업 영역 KQL
함수 권한을 부여하지 않습니다.

## Knowledge 근거

`core/rca/knowledge_evidence.py`의 `KnowledgeEvidenceGatherer`는
`shared/providers/knowledge.py`의 Knowledge Base 경계를 사용합니다. 연결되면 coordinator가
인제스트된 런북, 아키텍처 노트 및 resource plan에서 인시던트 요약과 관련된 조각을 검색하고 각
조각을 `CitationKind.KNOWLEDGE` 후보로 추가합니다. 연결되지 않은 출처, 빈 인덱스 또는 프로바이더
장애는 아무것도 제공하지 않으며 gate는 판단을 보류할 수 있습니다. 인용 참조는 조각 본문 대신
opaque `knowledge:<source_ref>#<chunk_id>` handle을 사용합니다. Reasoner는 이 검증된 집합 밖의
조각을 인용할 수 없습니다.

Knowledge 수집은 `doc_id`별 완전한 교체 의미 체계를 사용합니다. 새 개정은 같은 트랜잭션에서
오래된 조각을 제거하고, 빈 교체는 해당 문서의 모든 조각을 삭제합니다. 메모리 구현과 pgvector
구현이 같은 동작을 사용하므로 연결기 삭제 및 개정 전파 후에 오래된 텍스트가 검색되지 않습니다.

관리되는 업로드 문서는 별도 경로를 사용합니다. `GovernedDocumentEvidenceReadAdapter`는 문서
전용 `OperationalEvidenceBundle`을 만들기 전에 문서 접근 프로바이더와 컬렉션 범위 검색을
적용합니다. 이후 `GovernedKnowledgeEvidenceGatherer`가 주체, 목적, 범위, 기준 시각, 문서 개정
번호, 접근 맥락, 가림 상태 및 인용 매니페스트를 검증한 뒤 불투명한
`CitationKind.KNOWLEDGE` 참조를 제공합니다. 관리되는 맥락이 없거나 수락되지 않으면 RCA 결과를
보류하며 범위가 없는 `KnowledgeSource`로 대체하지 않습니다. 수집기는 문서 근거 참조 집합과
문서 lane의 인용 매니페스트가 정확히 일치하는지도 확인합니다. 추가되거나 중복되거나 누락된
항목이 있으면 결과를 보류합니다.
호출자가 관리되는 문서 맥락을 요청한 경우 빈 수집 결과도 보류로 처리합니다. 필수 관리 근거
경로가 근거와 명시적 사유를 모두 반환하지 않았는데 조정기가 원격 측정 또는 다른 인용만으로
계속 진행할 수 없습니다.

자동 Incident T2는 목적이 `incident-review`인 고정 `principal:fdai-rca` Forseti 읽기 맥락을
통해 이 경로로 들어갑니다. 배포는 별도의 읽기 전용 PostgreSQL secret, 컬렉션 하나, 정확한 접근
설명자 참조 및 정확한 문서 읽기 그룹을 제공합니다. 검색은 결정론적 lexical ranking 전에
컬렉션 및 접근 참조 조건을 적용하고 이후 메타데이터와 그룹 권한을 다시 확인합니다. 요청은
인시던트, 리소스, 근거 기준 시각, 온톨로지 릴리스 및 카탈로그 개정 번호를 결속합니다. 일부
구성만 제공하면 startup이 실패하며 완전한 구성이 없으면 관리되는 문서 근거를 사용할 수 없습니다.

## 결정론적 T1 인과사슬

`core/rca/causal_chain.py`의 `CausalChainAnalyzer`와 `core/rca/t1.py`는 실패에서 끝나는 가장
가능성 높은 multi-hop 사슬 `root change -> symptom -> ... -> failure`를 재구성합니다. Root는
반드시 변경이어야 하며 선행 변경이 없는 symptom 구간은 판단을 보류합니다.

재사용 가능한 analyzer는 격리된 분석에서 범위가 없는 상관 입력을 채점할 수 있지만 운영
ControlLoop는 비어 있지 않은 Resource dependency graph를 요구합니다. 직접 또는 범위가 제한된
transitive dependency의 변경은 무관한 변경보다 우선하며 무관한 리소스는 연결될 수 없습니다.
`same_resource_only`는 모든 hop을 실패 리소스로 제한합니다. 신뢰도는
시간 근접성, 관계 강도, 변경 종류로 가중한 weakest-link 집계입니다. 모호성에 따라 할인되고 T1
범위 `0.35`-`0.85`로 제한됩니다. 엄격한 시간 선행성이 이벤트 집합을 DAG로 만들므로 같은 입력은
항상 같은 인용 사슬을 생성합니다.

`ControlLoop`은 현재 이벤트 기준 시각의 멤버와 의존성 그래프를 담은 `IncidentRcaContext`
하나를 가져옵니다. 정확한 리소스, 신호 및 선택적 correlation key로 EventCorrelator ID를
lifecycle Incident 하나에 매핑하며 재개 구간도 처리합니다. Azure 판독기는 전용 Monitoring
Reader를 사용하고 일치하는 historical 인벤토리 세대에서 프로바이더 ID를 해석하며, 성공한
정확한 리소스 변경만 유지합니다. Append-only topology history는 같은 event time과 known-at
기준 시각의 완전한 `depends_on` 그래프를 구성합니다. 세대 불일치, 모호성, 오래된 범위,
불완전한 topology, timeout 또는 감사 지연은 범위 없는 대체나 권한 부여 없이 side path를
종료합니다.

## 읽기 전용 운영자 화면

Shadow `rca.hypothesis` 감사 항목은
`services/operator-service/src/fdai_operator_service/rca_projection.py`의
`GET /rca?correlation=<id>`를 통해 **History > RCA** 패널로 프로젝션됩니다. 이 프로젝션은 같은
감사 스트림에서 티어별 가설, 인용, 구조화된 T1 사슬, grounding 상태 및 연결된 대응 계획을
표시합니다. 판단을 보류한 가설은 신뢰할 수 있는 원인이 아니라 근거 부족으로 표시됩니다. 이
화면은 읽기 전용이며 새 진실 원천을 추가하지 않습니다. [운영자 콘솔 인시던트
명단](../interfaces/operator-console-incident-roster-ko.md#1351-rca-view-root-cause-analysis)을
참조하세요.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 상관관계, 이상 감지 및 예측 | [관측성과 감지](observability-and-detection-ko.md) |
| 모델 출력 및 근거 경계 | [보안 및 신원](../architecture/security-and-identity-ko.md) |
| 읽기 전용 인시던트 표시 | [운영자 콘솔 인시던트 명단](../interfaces/operator-console-incident-roster-ko.md#1351-rca-view-root-cause-analysis) |
