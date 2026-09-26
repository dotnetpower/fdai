---
title: 어슈어런스 트윈 (질의가능하고 선제적이며 검증가능한 리뷰)
translation_of: assurance-twin.md
translation_source_sha: f9322b97e1f3e30d3d06ef3c3d66f41d63f7a332
translation_revised: 2026-09-27
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

## 구현 상태

결정론적 Twin 코어와 스칼라 및 그래프 시뮬레이션 기본 기능은 집중 테스트로
검증됩니다. 자세 및 검토 표면은 **부분 구현**입니다. Heimdall 보고서 작성기와
독립적인 Forseti 검토 작성기는 주입된 신뢰할 수 있는 출처에서 완전하고 최신이며
정확한 개정에 연결된 보관 근거만 받습니다. 각 작성기는 읽기 전용 활동을 영속
`state_kv` 행 및 Saga에 귀속된 추가 전용 감사 이력과 원자적으로 준비합니다.
감독되는 두 아웃박스 중계기가 스키마 검증을 거친 정확한 개정의 참고용 이벤트를
게시합니다. 인증된 Operator API와 콘솔은 이벤트 알림이 아닌 영속 행을 계속
읽습니다. 기본 구성에는 운영 보관 근거 출처가 연결되지 않아 선제적 수집
페이로드만으로 발견 사항이나 검토 판정을 만들 수 없습니다. 운영 인벤토리,
외부 검토 전달, 통제된 런타임 증적은 아직 남아 있습니다.

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 변환 결과, 검증된 질의, 자세 보고, 발행기 중립 검토 코어 | implemented | [`core/assurance_twin/`](../../../services/core-control-plane/src/fdai/core/assurance_twin), [`tests/assurance_twin/`](../../../services/core-control-plane/tests/assurance_twin) | 메모리 내 변환 결과, strict typed-query 검증기, 보고서 집계, 검토 발행기 연결부가 집중 검사를 통과합니다. 기본 자연어 컴파일러는 `semantic_model_unavailable`을 반환하며 의미를 lexical 방식으로 추론하지 않습니다. |
| 스칼라 Dynamic 효과 모델, 충실도 측정, 범위가 제한된 런타임 조정 | implemented | [`effect_model.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/effect_model.py), [`fidelity.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/fidelity.py), [`runtime.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/runtime.py) 및 해당 집중 테스트 | 활성 모델은 변경하지 않고, challenger는 적격 결과에서만 학습하며, 불일치는 사람 검토로 낮춥니다. |
| 그래프 전역 Dynamic 궤적, 전파, 불변식, 에피소드 종결, 모델 레지스트리 | implemented | [`graph_effect.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/graph_effect.py), [`graph_runtime.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/graph_runtime.py), [`graph_closure.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/graph_closure.py) 및 그래프 집중 테스트 | 런타임은 근거를 반환하기 전에 예측 에피소드를 저장하고 완전한 독립 관측에서만 challenger 구획을 갱신합니다. |
| 심층 Security Assessment 피드, 결정론적 분석기, 카탈로그 보고서 | implemented | [`core/security/`](../../../services/core-control-plane/src/fdai/core/security), [`security_assessment.py`](../../../services/core-control-plane/src/fdai/core/reporting/datasources/security_assessment.py), [`test_assessment.py`](../../../services/core-control-plane/tests/core/security/test_assessment.py), [`test_security_assessment_datasource.py`](../../../services/core-control-plane/tests/core/reporting/test_security_assessment_datasource.py) | 아래에서 설명하는 Twin 전용 자세 패널과는 별도의 보고 하위 시스템입니다. |
| 운영 인벤토리 변환 결과와 선제적 변경 검토 전달 | not-started | [`projection.py`](../../../services/core-control-plane/src/fdai/shared/providers/projection.py)와 [`iac_review.py`](../../../services/core-control-plane/src/fdai/shared/providers/iac_review.py)가 프로바이더 시임을 정의합니다. | 업스트림에는 운영 인벤토리 어댑터, 변경 이벤트 조정기, Checks API 발행기가 연결되지 않았습니다. |
| 엄격한 의미 컴파일과 판단 보류 피드백 | implemented | [`query.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/query.py), [`semantic_query.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/semantic_query.py), [`runtime/assurance_twin_query.py`](../../../services/core-control-plane/src/fdai/runtime/assurance_twin_query.py), 집중 질의 및 런타임 테스트 50개 | 주입된 컴파일러는 읽기 전용 계획이 검증을 통과하기 전에 정확한 입력 다이제스트, 컴파일러 개정, 제한된 결과 수, 근거 참조를 연결해야 합니다. 판단 보류는 주입된 발견 sink를 통해 내용 없는 무권한 공백만 발행합니다. 런타임 기본값은 명시적인 모델 사용 불가입니다. |
| T1 재사용, ChatOps 입력, 통제된 런타임 근거 | in-progress | [`chat.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/chat.py), 공유 의미 판단 계약 | 메시지 라우팅, T1 재사용, 구체적인 모델 프로바이더, 인증된 종단 증적은 아직 검증되지 않았습니다. |
| Heimdall/Forseti 로컬 이벤트 게시 | implemented | [`assurance_twin_writers.py`](../../../services/core-control-plane/src/fdai/delivery/assurance_twin_writers.py), [`assurance_twin_publication.py`](../../../services/core-control-plane/src/fdai/delivery/assurance_twin_publication.py), [`test_assurance_twin_publication.py`](../../../services/core-control-plane/tests/delivery/test_assurance_twin_publication.py) | 요청에는 발견 사항이 없습니다. 주입된 출처가 요청한 개정의 완전하고 최신이며 상충하지 않는 근거를 반환한 경우에만 해당 작성기가 저장합니다. Saga에 귀속된 감사 이력과 내장 아웃박스는 정확한 행과 함께 원자적으로 저장됩니다. 재시작한 중계기는 영속 개정을 검증한 후에만 스키마 검증을 거친 참고용 이벤트를 발행합니다. 실제 보관 근거와 통제된 런타임 연결은 아직 없습니다. |
| Twin 전용 운영자 패널과 거버넌스가 적용된 수정 제안 연결 | in-progress | [`posture_activity.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/posture_activity.py), [`assurance_twin_posture.py`](../../../services/core-control-plane/src/fdai/delivery/assurance_twin_posture.py), [`state_store_assurance_twin_posture.py`](../../../services/core-control-plane/src/fdai/delivery/persistence/state_store_assurance_twin_posture.py), [`assurance_twin_posture_projection.py`](../../../services/operator-service/src/fdai_operator_service/assurance_twin_posture_projection.py), [`assurance-twin` 콘솔 경로](../../../console/src/routes/assurance-twin.tsx) | 레코더는 출처와 내장된 게시 대기를 포함하는 제한된 보고서 및 검토 본문을 감사 기록과 같은 트랜잭션에서 개정 번호로 보호하여 저장합니다. Heimdall과 Forseti는 각자 소유하는 별도의 활동을 사용합니다. 관찰자에게만 허용되는 공유 운영 활동 스키마를 Forseti 소유로 위장하지 않습니다. 중계기는 정확한 영속 개정을 확인하고 게시 사실을 기록합니다. 늦거나 상충하는 근거는 현재 행을 바꾸거나 게시하지 못합니다. Operator와 콘솔은 영속 발견 사항과 근거 공백을 읽고 권한을 재계산하지 않습니다. 신뢰할 수 있는 출처, 외부 Checks 발행기, 수정 제안 연결, 통제된 실제 증적은 여전히 연결되지 않았습니다. |

일치하는 검토 재전달은 읽기 전용 no-op이므로 감사 항목을 추가하지 않고 최신 순서를 바꾸지
않습니다. 범위가 제한된 최근 검토 읽기는 정규 `generated_at` 순서로 정렬하며 변환 결과가
1,000행의 읽기 용량을 넘으면 명시적으로 실패합니다.

### 구현 이력

보관 행의 아웃박스와 Saga에 귀속된 감사 이력은
[`assurance_twin_outbox.py`](../../../services/core-control-plane/src/fdai/delivery/persistence/assurance_twin_outbox.py)에
있습니다. 기존 `StateStore`의 원자적 상태 및 감사 작업을 사용하며 패키지 스키마나
마이그레이션은 필요하지 않습니다. 작성기는 명시적인 관측 범위와 생성 시각부터
만료 시각까지 최대 30분인 근거를 요구합니다. Forseti는 보관된 검토 판정이 완전한
발견 사항 집합에 부합하는지 확인하며, 근거가 없거나 오래되거나 상충할 때 판정을
추론하지 않습니다. 버스 알림에는 `current: false`와
`publication_complete: false`를 넣습니다. 중계기가 마지막으로 읽은 뒤 더 새로운
행이 저장될 수 있으므로 현재 상태는 영속 변환 결과만 판단합니다.

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-09-27 | implemented | Heimdall 보고서와 Forseti 검토 작성기를 분리하고, 정확한 개정의 상태, 아웃박스, 감사를 원자적으로 저장하며 재시작 중계기를 감독하도록 했습니다. 출처를 사용할 수 없거나 근거가 충돌할 때 검토 판정을 만들어 내지 않습니다. | `current change`; `assurance_twin_writers.py`, `assurance_twin_publication.py`, Core, Operator 및 콘솔 집중 검사. | 신뢰할 수 있는 운영 근거를 연결하고 통제된 런타임 증적을 보관합니다. |
| 2026-09-09 | in-progress | 일치하는 검토 재전달이 동시에 기록되는 충돌 표식과 올바른 순서로 수렴하도록 두 번째 개정 번호 및 다이제스트 읽기를 추가했습니다. 확인 과정은 읽기 전용이며 감사 항목을 추가하지 않습니다. 두 읽기 사이에 충돌이 기록되면 사용 불가 결과를 반환합니다. | `current change`; 읽기와 충돌 표식의 교차 순서를 강제한 사례를 포함해 집중 영속성 및 전달 검사 45개와 Ruff 통과. | 신뢰된 생산자 또는 트랜잭션 발행기를 연결할 때도 같은 읽기 전용 순서 보장을 유지합니다. |
| 2026-09-09 | in-progress | 일치하는 변경 검토 재전달을 실제 읽기 전용 no-op으로 만들고, 범위가 제한된 최근 검토 변환 결과를 쓰기 최신성이 아니라 정규 근거 생성 시각 순서로 정렬했습니다. 읽기 용량인 1,000행을 넘으면 오해를 일으키는 부분 순서를 반환하지 않고 명시적으로 실패합니다. | `current change`; 집중 영속성 및 전달 검사 44개와 Ruff 통과. | 신뢰된 생산자를 연결하고 통제된 재현 근거를 보존합니다. 레코더는 계속 연결되지 않은 상태입니다. |
| 2026-09-08 | in-progress | 영속성, 활동 신원, 스키마 소유권, Operator 변환 결과 신원, 콘솔 상태 표현에서 마지막 Medium 이상 검토 결과를 해결했습니다. 자세 쓰기는 가장 최근에 생성된 근거로 수렴하고, 활동 키는 개인정보를 노출하지 않는 보고서 근거에 결속됩니다. 스키마는 `assurance-twin` 생산자가 다른 활동 종류를 가장하는 것을 차단합니다. 검토 목록은 영속 키를 정확한 본문 신원에 결속하고, 모든 자세 범위를 표시하며, 보류된 행을 빈 원장으로 표현하지 않습니다. | `current change`; 집중 Core, 계약, Operator, 콘솔 회귀 검사는 지연되거나 동시 발생한 자세 쓰기, 오래된 게시 억제, 범위 간 활동 신원, 생산자 가장, 영속 키 불일치, 다중 범위 요약, 보류 상태 레이블을 검증합니다. | 신뢰된 생산자를 연결하고 통제된 실제 근거를 보존합니다. 이 강화만으로 연결되지 않은 화면이 운영 검증 완료 상태가 되지는 않습니다. |
| 2026-09-06 | in-progress | Assurance Twin 소유권을 Python 및 콘솔 검증기뿐 아니라 공개 `agent-operational-activity` `1.2.0` JSON 스키마에도 결속했습니다. 이제 자세 활동은 Heimdall 소유권, `assurance-twin` 생산자, 관측 도메인 없음 조건을 모두 충족해야 하므로 스키마만 사용하는 소비자도 위조된 소유권을 수락할 수 없습니다. | `current change`; 위조된 소유자, 생산자 및 도메인 거부 사례를 포함해 집중 운영 활동 계약 테스트 15개 통과. | 이후 모든 스키마 버전과 생성된 소비자에서 같은 관계를 보존합니다. |
| 2026-09-06 | in-progress | 원장의 쓰기 경계를 Operator 변환 결과의 열거형과 일치시켰습니다. 이제 알 수 없는 최신성, 검토 판정 또는 발견 사항 심각도 값은 모든 읽기 구성 요소가 형식 오류로 보류해야 하는 성공 행을 만들지 않고 영속화 전에 실패합니다. | `current change`; 세 열거형 모두 쓰기가 발생하지 않음을 확인하는 회귀 사례를 포함해 집중 영속성 테스트 33개 통과. | 변환 결과 계약이 변경될 때 쓰기와 읽기 열거형 집합을 함께 동기화합니다. |
| 2026-09-06 | in-progress | 타임스탬프 표준화 이전에 기록한 검토 행의 멱등 재현을 보존했습니다. 이제 충돌 비교 자료에서만 레거시 행의 타임스탬프를 정규화하고 보존된 행과 기록된 다이제스트는 바이트 호환 상태로 유지하므로, 같은 시각의 다른 오프셋 때문에 영구적인 잘못된 충돌 표식이 생기지 않습니다. | `current change`; 레거시 `Z` 행을 같은 시각의 다른 오프셋으로 재현하는 사례를 포함해 집중 영속성 테스트 32개 통과. | 레거시 행이 남아 있지 않다는 통제된 이행 근거를 확보한 뒤에만 호환 경로를 제거합니다. |
| 2026-09-06 | in-progress | Assurance Twin 읽기 경로 3개를 Operator Service의 `operational-state` 데이터 출처에 모두 등록했습니다. 이제 `/system/data-sources`가 권위 있는 PostgreSQL 소유자와 사용 불가 이유를 보고하므로, 해당 변환 결과가 구성되지 않았을 때 콘솔이 소유자 없는 읽기를 요청하지 않습니다. | `current change`; Operator Service 조립 및 집중 출처 소유권 테스트 통과. | 신뢰된 생산자를 연결하고 통제된 실제 근거를 보존해야 합니다. 출처 소유권은 기존 읽기 표면의 상태를 설명할 수 있게 할 뿐입니다. |
| 2026-09-06 | in-progress | 저장되는 모든 자세 및 검토 `generated_at` 값을 다이제스트 계산과 쓰기 전에 표준 UTC로 정규화했습니다. 이제 같은 시각을 나타내는 서로 다른 오프셋 타임스탬프는 멱등성을 유지하고, 범위가 제한된 검토 조회는 오프셋 차이 때문에 더 최신 시각을 제외하지 않고 문자열 기준 최신순 정렬을 유지할 수 있습니다. | `current change`; `state_store_assurance_twin_posture.py`; 집중 영속성 테스트 31개 통과. | 신뢰된 생산자를 연결하고 통제된 실제 근거를 보존해야 합니다. 표준 타임스탬프 저장만으로 연결되지 않은 레코더가 운영 검증 완료 상태가 되지는 않습니다. |
| 2026-09-02 | in-progress | Heimdall이 소유하는 범위 제한 자세/검토 활동 신호(`agent.operational-activity` 스키마 `1.2.0`, `assurance-twin.posture` 종류), 운영 `state_kv` 자세 보고서 및 변경 검토 원장, 읽기 전용 `/assurance-twin/posture`, `/assurance-twin/reviews`, `/assurance-twin/reviews/{review_id}` Operator API 연산, 드릴다운 검토 상세를 갖춘 지역화된 읽기 전용 콘솔 패널을 추가했습니다. | `current change`; 집중 core, Operator API, 콘솔 검사 32개 통과. 콘솔 타입 검사, 빌드, 지역화 카탈로그 일치성 게이트 통과. | 운영 `Inventory` 출처를 연결하고, 선제적 변경 이벤트를 운영 게시자에 연결하고, 수정 제안 연결을 추가합니다. |
| 2026-09-03 | in-progress | 독립 검토에서 발견한 결함 일곱 건을 보완했습니다. 조립 루트에서 레코더를 Heimdall의 기존 `object.event` 구독 위 책임 주체 트리거에 연결했고, 상충하는 `review_key` 재전달이 진실을 둘로 나누는 대신 명시적인 사용 불가 신호로 실패 시 닫히도록 했으며, 이벤트-보고서 재생을 위해 범위가 제한된 활동, 상관관계, 증거 다이제스트 출처를 저장하고 노출했습니다. Operator API와 콘솔은 오래되었거나 사용 불가, 알 수 없음, 형식 오류, 다이제스트 불일치 행을 사용 가능한 결과 대신 명시적 공백으로 보류합니다. `agent-operational-activity` N/N-1 호환성 경계와 재생성한 Python/TypeScript 산출물, 스키마 `1.2.0`을 인식하는 콘솔 디코더를 추가했고, 콘솔 라우팅에서 불투명한 검토 키 식별자를 그대로 보존합니다. | `current change`; 집중된 코어, Operator API, 콘솔 검사 110건과 서비스 호환성 focused 게이트, 계약 생성, 프로젝트 ruff 및 strict mypy, 콘솔 타입 검사와 빌드, 카탈로그 일치/번역/로드맵 추적 게이트가 통과했습니다. | 통제된 실제 런타임 증적은 없습니다. 선제적 Twin 후보 이벤트를 게시하는 상류 구성 요소가 아직 없고 운영 `Inventory` 연결과 수정 제안 연결도 미착수입니다. |
| 2026-09-03 | in-progress | 두 번째 독립 검토 이후 같은 표면을 바로잡았습니다. 선제적 `object.event`/Huginn 트리거와 Heimdall 및 조립 루트 연결을 제거했습니다. 공격자가 영향을 줄 수 있는 수집 속성은 권위 있는 Twin 근거가 될 수 없기 때문입니다. 신뢰할 수 없는 다른 수집 경로로 대체하지 않았으므로 레코더는 현재 연결되지 않은 상태입니다. 상충하는 `review_key` 재전달은 영속 충돌 표식을 기록해 Operator API와 콘솔이 해당 식별자를 항상 사용 불가로 표시하도록 했습니다. `blocks_action`은 반드시 존재하는 boolean이어야 하며, 값이 없거나 문자열이면 `evidence_malformed` 사용 불가로 표시합니다. 검토 드릴다운을 정확한 질의 값(`/assurance-twin/review?review_key=`, 콘솔 `/assurance-twin?review=`)으로 옮겨 `/`가 포함된 불투명한 키가 정규화 없이 바이트 그대로 왕복하도록 했습니다. `agent-operational-activity` 호환성 행렬 경계를 되돌려, 과거 독립 서비스 실제 증적과 로컬 전환 근거를 다시 표시하지 않고 변경 전 값으로 복원했습니다. | `current change`; 집중된 코어, Operator API, 콘솔 검사와 ruff, strict mypy, 콘솔 타입 검사/빌드, 카탈로그 일치/번역/로드맵 추적/설계 게이트가 통과했습니다. | 신뢰된 생산자가 없어 이 행을 쓰는 구성 요소가 없고, 운영 `Inventory` 연결과 수정 제안 연결은 미착수이며, 통제된 실제 런타임 증적도 없습니다. |
| 2026-09-03 | in-progress | 연결되지 않은 표면에서 독립 검토 발견 사항 두 건을 추가로 해결했습니다. (1) 변경 검토 활동 신호는 원장의 CAS 기반 영속 충돌 표식과 원자적으로 순서를 맞출 수 없습니다. 영속 쓰기와 버스 게시는 순서가 보장되지 않는 별도의 비동기 단계이므로, 완료 신호든 사용 불가 신호든 동시 재전달이 이미 영속적으로 대체한 행의 상태를 설명하는 신호가 구독자에게 도달할 수 있고, 이미 게시된 오래된 신호를 철회할 방법도 없습니다. 추측성 잠금이나 아직 만들어지지 않은 트랜잭션 아웃박스를 추가하는 대신, `record_change_review`는 이제 두 결과 어느 쪽에 대해서도 `publisher.publish`를 호출하지 않습니다. 영속 원장, Operator API, 콘솔이 검토 상태에 대한 유일한 근거로 남고, 충돌은 여전히 그곳에서 영속적으로 사용 불가로 표시됩니다. 자세 보고서 게시는 영향을 받지 않습니다. 자세 쓰기에는 충돌 표식이 없으므로, 게시된 완료 신호는 "이 보고서가 기록되었다"는 사실만 주장하며 이후 보고서가 이를 대체해도 계속 참으로 남습니다. (2) 원장의 쓰기 경로는 이제 Operator API 투영이 읽을 때 이미 강제하는 모든 쓰기측 경계를 강제합니다. 발견 사항의 `evidence_refs`와 보고서/검토의 `reason_codes`는 각각 200개 항목을 초과하거나 비어 있거나 512자를 초과하거나 중복된 항목이 있으면 거부되고, `evidence_source_revision`은 비어 있거나 512자를 초과하면 거부됩니다. 이 모든 검증은 영속화나 게시 이전에 이루어지며 `assurance_twin_posture_projection.py`의 `_strict_string_list`/`_bounded_identity`를 정확히 그대로 반영합니다. | `current change`; 집중 core, delivery, persistence, Operator API 검사 278건(core-control-plane 229건 + operator-service 49건) 통과, 모든 수정 파일에 대한 ruff check/format과 mypy --strict(오류 0건) 통과. | 신뢰된 생산자가 없어 이 행을 쓰는 구성 요소가 없습니다. 운영 `Inventory` 연결, 수정 제안 연결, CAS/비동기 게시 순서 위험을 견디는 변경 검토 활동 게시 설계는 모두 남은 작업이며, 통제된 실제 런타임 증적도 없습니다. |
| 2026-08-31 | implemented | 엄격한 의미 컴파일러 조정기와 런타임 조립 경계를 추가했습니다. 검증은 정확한 질문 계보, 컴파일러 개정, 근거 인용, 결과 한계를 요구합니다. 유효하지 않은 계획은 명시적 모호성으로 바뀌고 내용 없는 무권한 발견 공백만 게시합니다. | `current change`; 집중 질의 및 런타임 조립 검사 50개 통과. | 통제된 모델 컴파일러와 발견 sink를 연결한 뒤 인증된 런타임 증적 하나를 보존합니다. |
| 2026-08-14 | in-progress | 구현 원장을 도입하고 테스트된 Twin 기본 기능과 연결되지 않은 전달 표면을 분리했습니다. 이전 구현 이력은 재구성하지 않았습니다. | 현재 변경과 구현 범위 표에 인용한 어슈어런스 트윈, Security Assessment, 보고 집중 테스트. | 운영 근거와 전달 표면을 연결한 다음 거버넌스가 적용된 런타임 증적을 수집합니다. |
| 2026-08-21 | in-progress | 기본 Twin 컴파일러에서 lexical 자연어 grammar를 제거했습니다. 바인딩되지 않은 컴파일은 `semantic_model_unavailable`을 반환하며 결정론적 읽기 전용 검증기는 주입된 모든 컴파일러에 계속 authoritative합니다. | `current change`; 집중 Assurance Twin 검사 45개가 통과했고 semantic-routing guard에 migrate 경로가 없습니다. | 자연어 컴파일을 사용할 수 있다고 설명하기 전에 Twin 전용 모델 projection과 ChatOps 입력을 연결합니다. |

### 남은 작업

- [ ] 권위 있는 `Inventory` 출처를 변환 결과에 연결하고 신선도, 범위가 제한된 변경분 처리,
  결정론적 재생을 집중 통합 테스트로 입증합니다.
- [x] 프로바이더 중립 의미 컴파일 및 발견 경계를 구현하고, 수락된 모든 질의가 범위 제한,
  근거 인용, 정확한 입력 연결, 읽기 전용 조건을 충족하며 지원되지 않는 질문은 명시적인
  사용 불가 또는 모호성 결과를 만드는지 테스트합니다.
- [ ] 구체적인 통제 모델 컴파일러와 ChatOps 입력을 연결하고 인증된 런타임 증적을 보존합니다.
- [ ] 선제적 변경 이벤트를 운영 `IacReviewPublisher`에 연결하고 변경, 발견 사항, 규칙 근거,
  게시된 검토를 연결하는 거버넌스 적용 shadow 증적을 기록합니다.
- [x] 보고서와 검토 게시 대기를 정확한 영속 개정 및 추가 전용 감사와 같은
  트랜잭션에서 준비하고, 검증된 대기 개정만 중계합니다. 집중 재시작, 순서 역전,
  충돌 테스트로 저장소 내 경로를 확인했습니다.
- [ ] 판단 보류된 질문과 수정 제안을 발견 및 정상 risk-gate 액션 경로로 보내고 Twin이 실행하거나
  권한을 높이지 않는지 테스트합니다.
- [ ] 신뢰할 수 있는 보관 근거 출처와 운영 인벤토리 및 변경 수신 경로를
  독립적으로 감독되는 Heimdall/Forseti 작성기에 연결합니다. 내용 없는 요청은
  근거가 아니며 공격자가 영향을 줄 수 있는 선제적 수집 페이로드는 권위 있는
  Twin 근거가 될 수 없습니다.
- [ ] 하나의 전체 인벤토리-보고서 렌더링에 대한 통제된 런타임 증적을 수집합니다. 이 항목은
  운영 `Inventory` 연결과 신뢰된 생산자를 필요로 하므로 구현도 검증도 완료되지 않았습니다.
  실제 증적은 아직 없으며 대체 증적을 만들어 넣어서도 안 됩니다.

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

트윈은 요청이 아니라 이벤트에서 변경을 리뷰합니다. 변경 신호가 도착하면(IaC pull 요청
열림, Activity Log 리소스 쓰기, 표류 차이), `event-ingest` 가 정규화하고, 트윈이 scratch
투영에 차이를 적용하며, T0가 영향받는 규칙을 평가하고, 결과가 리뷰로 되돌아 게시됩니다 -
PR의 Checks API 주석 또는 인시던트의 발견 사항. "요청 시 배포 후 평가" 케이스가 "변경 시,
요청 없이 평가됨"이 됩니다.

예: 개발자가 비공개 엔드포인트 없이 저장소 계정을 추가하는 IaC PR을 엽니다. 리뷰가
요청되기 전에 트윈이 검사를 게시합니다: `차단된 - object-storage.private-endpoint.필수
(규칙 인용), 해석: 비공개 엔드포인트 추가 또는 exemption 적용`.

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
| `projection` | 변경할 수 없는 in-memory 기준선을 만들고 scratch 차이를 적용합니다. 운영 `Inventory.full_snapshot()` + `delta()` 유지는 목표 연결입니다. |
| `query` | 결정론적 pattern 컴파일러로 well-typed 읽기 전용 조회를 검증하고 실행합니다. Model-backed 컴파일러는 프로토콜 목표입니다. |
| `review` | Precomputed 발견 사항을 `IacReviewPublisher`로 게시합니다. Change-signal 평가와 운영 발행기는 목표 연결입니다. |
| `report` | 발견 사항으로부터 `PostureAssessmentReport` 를 조립 |
| `chat` | 변경할 수 없는 근거에 기반한 chat-session 값과 영속성 프로토콜을 제공합니다. 브라우저 또는 전달 연결은 없습니다. |
| `graph_effect` / `graph_runtime` | 범위가 제한된 그래프 효과를 전파하고 필수 active-trajectory 불변식을 평가하며 review-only 시뮬레이션 근거를 반환합니다. |
| `trajectory_ledger` | Predicted trajectory 에피소드를 저장하고 완전한 comparable 결과만 StateStore를 통해 atomically close합니다. |
| `graph_closure` | 독립적인 관측을 off-path로 배출하고 challenger 구획을 갱신하며 활성 변경과 승격이 없었음을 감사합니다. |
| `posture_activity` | Heimdall의 기존 제한된 자세 활동과 Forseti의 별도 읽기 전용 검토 활동을 만듭니다. 전달 레코더는 각 활동을 보관 기록 및 Saga에 귀속된 추가 전용 감사와 함께 준비합니다. 독립적으로 감독되는 두 중계기가 개정에 결속된 이벤트를 게시합니다. 발견 사항을 계산하려면 주입된 신뢰할 수 있는 출처가 여전히 필요합니다. |

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
