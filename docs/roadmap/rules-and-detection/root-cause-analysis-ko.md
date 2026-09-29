---
title: 근본원인 분석
translation_of: root-cause-analysis.md
translation_source_sha: 52a3dbfb75e2cb9195e65ec5948060e98d82acfc
translation_revised: 2026-09-29
---
# 근본원인 분석

이 문서는 근본원인 분석(RCA)을 기존 trust 티어가 생성하는 인용 가능하고 범위가 제한된 가설로
정의합니다. RCA는 인시던트를 설명하지만 승인 또는 실행 권한을 부여하지 않습니다.

> **안전 경계:** 결정론적 검증, 정책, what-if, risk, 승인, 실행 및 효과 관측은 모든 RCA
> 가설보다 높은 권위를 유지합니다.
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
6. 자동 로그와 추적 변환 결과는 5초 RCA side-path deadline 안에서 별도의 4초 출처 상한으로
  병렬 실행합니다. Timeout은 출처별 사용 불가 근거가 되므로 지연된 출처 하나가 다른 출처에서
  완료된 인용을 취소하지 않습니다.

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
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/rules-and-detection/root-cause-analysis.md) |
| 상관관계, 이상 감지 및 예측 | [관측성과 감지](observability-and-detection-ko.md) |
| 모델 출력 및 근거 경계 | [보안 및 신원](../architecture/security-and-identity-ko.md) |
| 읽기 전용 인시던트 표시 | [운영자 콘솔 인시던트 명단](../interfaces/operator-console-incident-roster-ko.md#1351-rca-view-root-cause-analysis) |
