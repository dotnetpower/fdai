---
title: 근본원인 분석
translation_of: root-cause-analysis.md
translation_source_sha: 58f727a193d66d5d986795ac491aeb343c41d787
translation_revised: 2026-08-29
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
| T0, T1, T2 가설 계약 및 grounding | implemented | `services/core-control-plane/src/fdai/core/rca/`, 집중 RCA 테스트 | T0 규칙 원인, stale-safe T1 재사용, 결정론적 인과사슬 및 grounded T2 parsing을 구현했습니다. |
| Knowledge 근거 및 프로바이더 연결 | implemented | `core/rca/knowledge_evidence.py`, `shared/providers/knowledge.py`, `delivery/pgvector/knowledge.py`, `delivery/azure/llm/rca_model.py`, `runtime/bootstrap.py`, 집중 프로바이더, 어댑터 및 런타임 테스트 | 런타임은 Azure LLM 초기화 이후와 원격 측정 전용 모드 모두에서 구성된 pgvector 소스를 연결합니다. 다시 수집하면 문서 조각을 원자적으로 교체하고 빈 교체는 삭제하므로 오래된 개정이 검색 결과에 남지 않습니다. 연결이 없을 때는 근거를 만들어 내지 않습니다. |
| 읽기 전용 운영자 프로젝션 | implemented | `services/operator-service/src/fdai_operator_service/rca_projection.py`, 집중 프로젝션 테스트 | 작업 권한 없이 감사 가설, 인용, 구조화된 인과사슬 및 연결된 대응 계획을 프로젝션합니다. |
| 통제된 운영 RCA 정확도 | in-progress | [관측성과 감지](observability-and-detection-ko.md#구현-상태) | 티어 혼합 전체에서 실제 원인 정확도, 판단 보류 및 downstream 결과 종결을 입증하는 exact-revision cohort가 없습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-28 | implemented | 모델 초기화 이후에 영속 KnowledgeSource를 연결하도록 순서를 바꿨습니다. 이제 Knowledge DSN이 구성된 Azure LLM 모드에서 RCA가 기본 빈 소스에 남지 않습니다. 동일한 조건부 호출은 원격 측정 전용 모드와 로컬 모델 동작을 유지합니다. 메모리 및 pgvector 소스는 다시 수집을 완전한 교체로 처리하고, 임베딩에 실패하면 이전 개정을 보존하며, 오래된 조각을 제거하고, 문서별 트랜잭션 잠금 아래에서 빈 교체를 삭제로 처리합니다. | `current change`; `runtime/bootstrap.py`; `shared/providers/knowledge.py`; `delivery/pgvector/knowledge.py`; 집중 부트스트랩 및 런타임 구성 검사 42건 통과; 집중 KnowledgeSource 및 SQL 수명 주기 검사 21건 통과, 실시간 데이터베이스 동등성 검사 1건은 환경 조건으로 제외; Ruff 및 strict mypy 통과. | 배포가 소유하는 색인 문서를 대상으로 관리되는 RCA cohort를 보존하고 소스 연결기를 교체 계약에 연결합니다. |
| 2026-08-21 | in-progress | 런타임 동작이나 권한을 변경하지 않고 기존 RCA 티어, grounding, 인과사슬, knowledge 및 프로젝션 계약을 집중 소유 문서로 옮겼습니다. | `current change`; 문서 크기, 번역, 경로 및 링크 검사입니다. | 권위 있는 원인 및 결과 검토가 있는 통제된 운영 cohort를 보존합니다. |

### 남은 작업

- [ ] T0, T1, T2의 지원된 원인, 판단 보류, stale 재사용 거부, 인용 유효성 및 독립적으로
  검증된 결과를 측정하는 exact-revision 운영 cohort를 보존합니다.

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

## 결정론적 T1 인과사슬

`core/rca/causal_chain.py`의 `CausalChainAnalyzer`와 `core/rca/t1.py`는 실패에서 끝나는 가장
가능성 높은 multi-hop 사슬 `root change -> symptom -> ... -> failure`를 재구성합니다. Root는
반드시 변경이어야 하며 선행 변경이 없는 symptom 구간은 판단을 보류합니다.

Resource dependency graph가 공급되면 직접 또는 범위가 제한된 transitive dependency의 변경이
무관한 변경보다 우선하며 무관한 리소스는 연결될 수 없습니다. Graph가 없으면 상관된 cross-
resource 연결을 허용합니다. `same_resource_only`는 모든 hop을 실패 리소스로 제한합니다. 신뢰도는
시간 근접성, 관계 강도, 변경 종류로 가중한 weakest-link 집계입니다. 모호성에 따라 할인되고 T1
범위 `0.35`-`0.85`로 제한됩니다. 엄격한 시간 선행성이 이벤트 집합을 DAG로 만들므로 같은 입력은
항상 같은 인용 사슬을 생성합니다.

`ControlLoop`은 `IncidentMemberSource`에서 멤버를 가져오고 `causal_chain_window`로 제한한 뒤
이벤트마다 shadow T1 가설 하나를 추가합니다. 가설은 root와 failure id, 모호성, 순서가 지정된
hop 근거가 있는 transport-safe `causal_chain`을 유지합니다. `DeploymentHistoryMemberSource`는
`DeploymentHistoryProvider`와 인시던트 조회를 선행 변경 이벤트로 연결합니다. 출처가 없으면 T1
인과사슬 경로를 사용할 수 없습니다.

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
