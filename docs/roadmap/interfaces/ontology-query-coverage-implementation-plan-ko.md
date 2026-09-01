---
translation_of: ontology-query-coverage-implementation-plan.md
translation_source_sha: f0dc0613d14183234c548a231086a26677303daa
translation_revised: 2026-09-01
---
# 온톨로지 조회 커버리지 구현 계획

이 계획은 FDAI의 범위가 제한된 대화/온톨로지 기반과 운영자 질문을 위한 목표 non-keyword
경로 사이의 구현 공백을 닫습니다. 100% structural 조회 커버리지에 필요한 검증된 현재 기준선,
서비스/에이전트 소유권, 의존성 순서 작업 패키지, 전환 게이트 및 롤백 단위를 기록합니다.

> **커버리지 경계:** 100%는 하나의 활성 온톨로지 release에서 읽을 수 있는 모든 선언이
> principal 범위로 한정된 조회 서술자 또는 타입이 지정된 사용 불가 사유를 갖는다는 뜻입니다. 신원,
> 프로바이더 데이터, 이력 또는 근거가 없을 때 완전하거나 정확한 답을 보장한다는 뜻이 아닙니다.
>
> **권한 경계:** 자연어 및 임베딩 출력은 후보 전용으로 유지합니다. 읽기 계획에는
> 실행 권한이 없습니다. 명시적 변경 요청은 기존 judgment, 안전성, 사람 승인, 실행, 복구 및
> 감사 경로로 다시 들어가는 타입이 지정된 초안만 만들 수 있습니다.
>
> **무작위 보증 상태(2026-08-11):** 인증된 Console은 생성된 영어 및 한국어 턴 100/100개를
> 완료했지만 측정된 경로는 로컬 Azure 서술기만 사용했습니다. 의도 인식은 100%, 답변 성공은
> 20%였으며 카드 100개 모두 근거 0/0의 검증되지 않은 상태였습니다. Core는 이제 Azure 모델
> 후보, exact 온톨로지 release 및 온톨로지 인스턴스 저장소를 사용할 수 있을 때 의미 런타임을
> 구성합니다. 측정된 실행은 이 연결 이전의 결과입니다. Operator 서비스는 이제 의미 턴을
> publish하고 근거에 묶인 변환 결과를 consume합니다. Visible Console 경로에서 새 실제 운영 서비스 간
> 및 randomized 실행 증적을 만들 때까지 운영 완료 보고는 계속 차단됩니다.
> [온톨로지 쿼리 무작위 보증](ontology-query-randomized-assurance-ko.md)을 참조하세요.
>
> **서비스 간 계약 상태(2026-08-11):** 가산 버전 1.2 요청/변환 결과 묶음은
> 범위가 제한된 의미 턴, 인증된 principal 역할, 기한, 멱등성 신원, 최종 처리 결과 및
> exact 근거 다이제스트를 정의합니다. 이 계약만으로 운영 라우팅이 활성화되지는 않습니다.
> 의미 페이로드는 N-1 형태로 translate하지 않고 실패 시 차단합니다. Core는 이제 설정된 의미
> 요청을 consume하고 정본 결과를 저장하며 최종 변환 결과를 publish하고 시작
> 준비 상태에 exact missing-provider 사유를 보고합니다. Operator 발신함 게시, 영속 재생 및
> Console `done` 변환 결과는 이제 compose됩니다. POST 재생은 요청 기한까지 기다리고 Core 변환 결과가
> 없으면 typed hold를 영속화합니다. Operator 영속성은 JSONB text parameter의 타입을 명시하여 실제
> psycopg claim 및 변환 결과 경로를 실행 가능하게 유지합니다. Receipt-backed 실제 운영 통합 근거는
> release 게이트로 유지됩니다.
>
> **구현 상태(2026-08-10):** Exact 온톨로지 release, 의미 후보, 범위가 제한된 ObjectSet, secured 조회
> 증적, 타입이 지정된 함수 등록, 현재 인벤토리 변환 결과, 메트릭 프로바이더 및 causal-analysis
> 기본 요소가 있습니다. 운영 경로는 여전히 정규식/토큰 라우팅과 선택적인 serial 2-3 명령
> 읽기 계획을 사용합니다. 서버 측 의도 그래프, principal 범위로 한정된 release 기반 조회
> 매니페스트, `OntologyQueryPlan`, 영속 의미 인덱스, 과거 토폴로지 및 리소스 간 temporal
> 프로바이더 조립은 이제 제공됩니다. 운영 턴 완료 연결, 영속 의미 인덱스 활성화 결과 발행 및
> 통제된 서비스 간/무작위 보증 증적은 아직 완료되지 않았습니다.
> 의미 problem 프레임, 조회 DAG, 의도 그래프, 작업 증적 및 structural 커버리지 증적의 OQ-01
> implementation-free SDK 모델은 이제 제공됩니다. 생산자/소비자 변환 결과 배선은 OQ-04 및
> OQ-05에 남아 있습니다.
> OQ-02에는 이제 함수를 역할/용도로 필터하고 supplied release 선언 전체를 계정하는
> 내용 기반 주소를 가진 principal 범위로 한정된 매니페스트 빌더가 포함됩니다. 모든 directed LinkType은 이제
> 결정론적 나가는/들어오는 엔드포인트 query-side 식별자를 변환 결과합니다. 운영 카탈로그는
> 검토된 `Identifiable` Interface를 부하하고 모든 현재 ObjectType의 명시적 연결을 검증하며
> polymorphic 카탈로그를 compile하고 exact 런타임 release에 선언을 포함합니다. 이 매니페스트를
> 서술기 및 범용 조회 표면에 연결하는 작업은 남아 있습니다.
> OQ-03에는 이제 범위가 제한된 의존성 wave, 동시성, 시간 초과, 취소, blocked-descendant 처리,
> 고정된 실패 사유 및 작업 증적을 갖춘 exact-release 조회 DAG 실행기가 포함됩니다. Built-in
> 핸들러는 이제 secured ObjectSet 구체화, union, intersection, subtraction, 정렬,
> 변환 결과, grouped 집계 및 exact-release 조회/derive/validate 함수 호출을 다룹니다.
> 결정론적 검증기는 I/O 전에 principal 매니페스트, readable 속성, LinkType, closed 노드 인자,
> 의존성 출력 종류와 ObjectSet, Project, Order 및 집합 연산 의존성을 통해 전파된 집계 필드,
> 함수 스키마 및 등록된 확장 스키마를 검사합니다. Temporal, metric-series 및
> evidence-join 핸들러는 이제 검증기와 실행기가 공유하는 핸들러 맵에 포함됩니다. 운영 조립은
> 비어 있지 않은 state-store DSN에서 PostgreSQL 토폴로지 이력을 연결하고 검토된 레지스트리와
> no-op이 아닌 프로바이더가 모두 있을 때만 metric/evidence 핸들러를 연결합니다. 그렇지 않으면
> 해당 기능은 타입이 지정된 사용 불가 상태로 유지됩니다.
> OQ-07은 이제 현재 connected VNet 피어링 기록을 관찰된 direction으로 변환 결과하고 비공개
> 엔드포인트를 exact private-link 서비스 대상에 첨부합니다. Reverse 피어링에는 여전히 독립적인
> remote-VNet 관측이 필요합니다. 또한 명시적 ARM 리소스 next-hop id에서만 `routes_to`를
> 변환 결과하며 IP, 접두사 및 hostname은 온톨로지 간선이 되지 않습니다. 스냅샷과 real-time 제약은
> 검토된 피어링/라우팅 vocabulary를 수락합니다. 프로바이더 관계 추출은 속성 경로, 허용된
> 프로바이더 타입, 엔드포인트 방향, 출처 스키마 다이제스트 및 근거 정책을 고정하는 검토된 mapping
> 카탈로그를 사용합니다. 하나의 완전한 인벤토리 세대에 두 엔드포인트가 모두 있고 독립적으로 검증된
> 링크만 active graph에 들어갑니다. 엔드포인트 누락, 모호한 방향, stale mapping, 중복 또는
> conflicting 관찰, 부분 세대는 stable dropped reason과 함께 absent 상태로 남습니다.
> 워크로드/서비스 mapping 및 운영 network-path 발급자는 남아 있습니다.
> OQ-04에는 이제 whole 범위가 제한된 턴과 후보 서술자에서 의미 프레임 및 타입이 지정된 노드 DAG를
> 제안하는 스키마로 제한한 모델 경계가 있습니다. Core는 모든 다이제스트/권한 필드를 다시 만들고
> exact principal 매니페스트를 검증하며 검증된 계획, 명확화 하나, action-draft 인계,
> 지원하지 않는 또는 사용 불가 결과를 반환합니다. 호환성 조정기는 이 경로를 shadow로
> 실행하고 처리 결과/내용 다이제스트만 기록할 수 있습니다. Azure 어댑터는 이제 워크로드 신원을
> 통해 범위가 제한된 JSON-object 호출 두 개를 실행하고 제안 스키마 두 개를 검증하며 resolved 후보를
> 순서대로 시도합니다. Core 조립은 모든 선행 조건을 사용할 수 있을 때 이 어댑터를 exact
> release, 현재 인스턴스 저장소, principal 범위로 한정된 매니페스트, 결정론적 검증기 및
> request-role-specific secured 실행기에 연결합니다. 실제 운영 서비스 간 hardening은 Core가
> 프레임 다이제스트를 다시 만들기 전에 프레임 제안의 evidence-requirement 식별자를 shared wire
> 계약과 일치시킵니다. 입력을 포함하지 않는 단계 및 검증 진단은 운영자 텍스트나 프로바이더
> 상세를 보존하지 않고 실패 attribution을 유지합니다.
> OQ-05는 이제 결정론적하게 최대 8개 목표의 의도 그래프를 만들고 실행기 증적을 해당 목표에
> 연결하며 내부 exact-plan 계약을 Console v2/v1 wire 형태로 변환 결과합니다. Console은 명시적
> 취소 증적도 수락합니다. 의미 계획 실행 및 운영 turn-completion 스트림에 이
> 변환 결과를 첨부하는 작업은 남아 있습니다.
> OQ-06은 이제 atomic 단계/activate, stale-generation, 타입이 지정된 검색 및 롤백 행동을 가진
> service-owned 구체적인 in-memory 의미 인덱스를 복원했습니다. Full 온톨로지 세대 빌더는 모든
> principal-manifest 선언과 조건을 충족한 deployment-local 객체 변환 결과를 발행하고 incremental
> 빌드에서 변경되지 않은 문서 인스턴스를 다이제스트로 재사용합니다. 커버리지와 문서 루트를
> 독립적으로 다시 계산하며 해당 검증 증적이 연결되기 전에는 activation을 거부합니다. 영속
> PostgreSQL 어댑터, scheduled 발행기 프로세스 및 운영 descriptor-selector 연결은 남아 있습니다.
> OQ-08에는 이제 retained 프로바이더 세대, 객체/링크 개정 번호 및 tombstone을 위한 추가 전용
> bitemporal 토폴로지 계약과 Core-owned 이행, 결정론적 `graph_at`/`topology_diff`, `known_at`에
> 따른 late-evidence 재생, incomplete-history 의미 규칙 및 검증기 스키마를 가진 타입이 지정된 조회 핸들러가
> 포함됩니다. PostgreSQL 읽기 담당/쓰기 담당 연결과 inventory-promotion 개정 번호 발행기는 남아 있습니다.
> OQ-09에는 문구 별칭이 없는 exact 검토된 metric-concept 레지스트리, 권위 있는 메트릭 구간,
> zero와 누락된 데이터를 구분하는 equal-duration 비교, 범위가 제한된 metric-series/evidence-join 핸들러 및
> competing explanation을 보존하는 topology-aware temporal support/refutation이 포함됩니다. 운영
> 메트릭 프로바이더 연결과 검토된 카탈로그 데이터에는 이제 검토된 alias-free 카탈로그와 구체적인
> `MetricProvider` 구간 어댑터가 포함됩니다. 이 어댑터는 관찰된 zero를 보존하고 빈 프로바이더
> 결과를 불완전한 결과로 보고하며, 명시적인 프로바이더 실패를 사용할 수 없는 불완전한 구간으로
> 변환합니다. 어느 한 메트릭 구간이라도 불완전하면 causal join은 미해결 상태를 유지하고 실행 권한을
> 부여하지 않습니다. 런타임 semantic-turn 조립은 현재 ObjectSet과 pure
> 집합/순서/project/집계 핸들러만 노출합니다. Metric-series 및 evidence-join 핸들러는
> 권위 있는 프로바이더가 명시적으로 연결될 때까지 사용 불가 상태로 남습니다.
> OQ-05에는 이제 accepted ordinary-language 턴을 답변, 명확화, 보류, 지원하지 않는, 액션 초안
> 또는 취소로 종료하는 비동기 서버 측 의미 턴 런타임도 포함됩니다. 검증된 조회
> DAG만 실행하며 exact Console 그래프/근거 변환 결과를 발행합니다.
> OQ-10은 synchronous 호환성 조정기의 기본값을 exact 정본 명령 only로 변경합니다.
> Natural-language 별칭, 키워드 서술 및 canonical-string 읽기 계획은 테스트 또는 명시적 temporary
> 호출자가 `legacy`를 선택할 때만 실행되며 ordinary 언어는 의미 런타임이 담당합니다.
> OQ-11은 모든 shipped principal 매니페스트와 bilingual competency 집단을 대상으로 executable fast 게이트를
> 추가합니다. 완전한 structural accounting, 최종 처리 결과 100%, 이전 방식 ordinary-language 경로 0,
> 지원하지 않는 점유 0 및 승인되지 않은 실행 0을 요구합니다. 답변 개수는 universal 완전한으로
> 주장하지 않고 집단별로 보고합니다.
> Committed competency 집단은 `receipt_source=deterministic_fixture`를 사용합니다. 게이트 증적은
> 로컬 structural 검증 결과를 `passed`에 유지하고 질문 하나라도 결정론적 고정본 근거를
> 사용하면 `production_ready=false`로 보고합니다. 운영 완료를 주장하는 호출자는
> `require_production_ready=True`를 설정하고 외부에서 생성된 `cross_service_e2e` 또는
> `live_assurance` 증적을 제공해야 합니다. 따라서 일반 fast 게이트는 로컬 CI에서 계속 실행할 수
> 있으며 hand-authored 고정본을 서비스 간 또는 실제 운영 증명으로 취급하지 않습니다. Catalog
> 구조가 변경되면 모든 answered fixture는 새로 계산한 release 및 principal-manifest digest를
> 고정해야 게이트를 통과하며 stale 결정론적 receipt는 compatibility로 수락하지 않습니다.
> `resource_classified_as` 카탈로그 개정과 `Forecast`/`Pattern` 카탈로그 개정은 각각 같은 release
> 변경에서 해당 결정론적 고정본 다이제스트를 갱신했습니다.
> 현재 구조 release 갱신은 답변이 있는 결정론적 고정본 4개를 정확한 release 및 Reader
> principal-manifest 다이제스트에 고정합니다. 설계 경로는 전체 Operator Console 소유자를
> 중복하지 않고 App Shape 계약을 사용하며 `production_ready=false`를 유지합니다.
> 첫 인식 상태 완결성 구현 구획은 이제 변경할 수 없는 유한 `QuestionUniverseReceipt`, 형식이
> 지정된 `EpistemicStatus`, 증명을 포함하는 `EpistemicQuestionRecord`, 0건 임계값을 적용하는
> `EpistemicCoverageReceipt`를 제공합니다. 기존 커버리지 게이트는 외부 증적 출처가
> `production_ready=true`를 만들기 전에 일치하며 통과한 인식 상태 증적을 요구합니다. 이는
> release 게이트 기반일 뿐입니다. 생성된 질문 우주, 런타임 이해/완전성/주장 증적, 공급자 기반
> L3/L4 인증은 아직 완료되지 않았습니다.
> OKQ-01에는 이제 `resource_classified_as`의 카탈로그 선언, 결정론적 ResourceType 매핑
> 다이제스트, 안전하게 실패하는 분류 변환 결과, 단일 작성자 영속성 테스트가 있습니다. 운영
> 운영 인벤토리 작업 주입은 완료되었고 리소스에서 Rule로 이어지는 질의 함수는 남아 있습니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 서비스 간 의미 계약 및 Core 처리 | 구현됨 | `semantic_turn.py`, `semantic_turn_consumer.py`, `semantic_turn_processor.py`, 통과한 의미 경로 테스트 88개 | 버전 1.2 요청은 90초로 제한되고 결과는 멱등성을 보장하며 점유를 복구할 수 있습니다. Rule 결과는 실행 권한이 없는 후보 전용으로 유지됩니다. |
| Operator 영속성과 Rule 변환 결과 | 구현됨 | `semantic_turn.py`, `semantic_turn_runtime.py`, `postgres_semantic_turn_store.py`, `test_semantic_turn_bridge.py`, 통과한 의미 경로 테스트 88개 및 롤백 전용 PostgreSQL 트랜잭션 검사 | 유효한 호출자 제공 요청 UUID를 의미 묶음과 상관관계 신원 전체에서 보존하면서 멱등성 키는 분리합니다. 요청 UUID를 생략하면 재시도에도 안정적인 결정론적 대체값을 사용합니다. 발신함과 결과 점유를 복구할 수 있고 잘못된 소유권은 안전하게 차단됩니다. 재생 순서는 타임스탬프를 인식하며 exact Rule 읽기는 principal과 조회 다이제스트로 격리됩니다. `SemanticTurnBridge`는 권위 있는 저장소와 의미 전송이 있을 때만 활성화되고, 로컬 서술기가 구성되면 주기적 갱신은 독립적인 Operator 수명 주기 서비스로 유지됩니다. |
| 과거 토폴로지 영속성과 발행 | 구현됨 | `inventory_topology_history.py`, `postgres_topology_history.py`, `inventory_sync_cli.py`, 통과한 범위가 제한된 인벤토리/토폴로지 테스트 31개 | 완전한 승격 관측은 bitemporal 개정 번호를 하나의 트랜잭션으로 추가합니다. 과거/현재 파생 쓰기는 서로 독립적으로 시도하며 불완전한 관측은 완전한 과거 기준선을 만들 수 없습니다. |
| Temporal, metric 및 근거 프로바이더 조립 | 구현됨 | `wire_semantic_query.py`, `bootstrap.py`, `bootstrap_bindings.py`, `test_wire_semantic_query.py`, `test_bootstrap_config.py`, 통과한 focused 조립 및 프로바이더 선택 테스트 16개 | 하나의 핸들러 맵이 검증기 가용성과 실행을 함께 제어합니다. 운영 환경은 상태 저장소 DSN에서 PostgreSQL 이력을 연결하고 검토된 레지스트리와 no-op이 아닌 프로바이더가 모두 있을 때만 metric/evidence 핸들러를 연결합니다. |
| 의사 결정 핵심 보안 쿼리 승인 | implemented | `query_receipt_authority.py`, `query_source_handlers.py`, `wire_semantic_query.py`, 집중 권한, FunctionType 및 조립 테스트 | 발행된 결과는 진단에 사용할 수 있지만 `verify`와 `resolve`는 변환 결과 다이제스트, 역할과 목적 범위, 온톨로지 릴리스 및 출처 세대가 일치하는 현재 유효한 공유 의사 결정 근거 승인 결과를 요구합니다. 조립은 승인 프로바이더 seam을 노출합니다. 기본값으로는 연결되지 않으므로 의사 결정 핵심 Function은 자체 발행 쿼리 증적을 신뢰하지 않고 보류됩니다. |
| 수명 주기 없는 선언 커버리지 | implemented | `object-type-lifecycle-classification.yaml`, 엄격한 온톨로지 로더 및 이중 언어 일치 검사 | 수명 주기가 없는 모든 ObjectType을 정확히 한 번 분류합니다. 새 항목, 삭제된 항목, 중복 항목 또는 오래된 항목이 있으면 소유권 의미를 조용히 바꾸는 대신 카탈로그 로딩을 차단합니다. |
| 통제된 운영 보증 | 진행 중 | [온톨로지 조회 무작위 보증](ontology-query-randomized-assurance-ko.md)과 아래의 검증된 기준선 공백 표 | 로컬 검사는 안전하게 실패하는 조립을 입증하지만 운영 준비 상태를 입증하는 통제된 실제 서비스 간 증적은 없습니다. |
| 타입 기반 Console 보증 실행기 | 구현됨 | `console-routes.spec.ts`, `ontology-query-assurance.ts`, `ontology-query-assurance.spec.ts`, focused Console 검사 | 한 실행기는 게시, Core 처리, exact projection 읽기 및 인증된 증적 렌더링을 검증합니다. Seed 기반 100-turn 실행기는 타입 전용 oracle로 영어 50개와 한국어 50개 prompt를 다룹니다. 보존 artifact가 통과하기 전에는 어느 구현도 실제 운영 근거가 아닙니다. |
| T1 명확화 및 frame-plan 정렬 | 구현됨 | `semantic_planning_models.py`, `semantic_planning_cascade.py`, `semantic_planning_frame.py`, `semantic_planning_alignment.py`, 집중 플래너 검사 90개 통과 | Frame 제안은 누락된 사용자 맥락을 범위가 제한된 `clarification_requirements`로 분류합니다. 정당한 T1 명확화는 T2 없이 종료됩니다. 집중된 결정론적 helper는 서버 소유 명확화 맥락을 결속하고 승인된 frame 또는 정확한 기능군을 바꾸는 plan을 거부합니다. Server-bound context 요청, 모호하거나 혼합된 대상, 유효하지 않은 스키마, 결정론적 frame-plan 불일치는 T2 없이 안전하게 종료되고 타입이 지정된 T1 unavailable만 interactive runtime의 범위가 제한된 fallback을 사용할 수 있습니다. |
| 복합 서비스-담당 Agent 인스턴스 경로 | 구현됨 | `ontology_query.py`, `query_gateway.py`, `query_source_handlers.py`, `semantic_relationship_planning.py`, 집중 계약, 조회, 플래너, 실행기 및 보증 검사 451개 통과 | 일관된 단일 그래프 스냅샷이 실제 서비스, 워크로드, 리소스 및 담당 Agent의 각 경로를 보존합니다. 최종 증적은 정확한 매니페스트와 인벤토리 입력, principal 범위, release, 기준 시점, 출처 세대, 경로 정의 및 결과 다이제스트를 결합합니다. 빈 경로는 신원을 주장하지 않으며 담당 체계는 실행 권한을 부여하지 않습니다. |
| 컬렉션 범위 Resource 상태 및 근거 기능군 격리 | implemented | `semantic_resource_state_planning.py`, `resource_state_queries.py`, `semantic_planning_value_filters.py`, `inventory-query-language.yaml`, 집중 플래너, FunctionType, 조립, prompt 및 표현 검사 | 서버 소유 FunctionType이 보안이 적용된 Resource 컬렉션을 완전한 observed `StateFactMetadata`로 필터링합니다. 스키마로 검증한 언어 레지스트리는 현재 인벤토리 상태와 구독 상태 평가를 분리하며, 바인딩되지 않은 상태 평가, 메트릭, 이력, 맥락 및 커버리지 기능군은 관련 없는 Resource 행 대신 타입이 지정된 보류를 반환합니다. 인증된 로컬 Console 관측은 구현 주장을 뒷받침하지만 통제된 릴리스 근거는 아닙니다. |
| 정확한 대상이 없는 Resource 하위 유형 후보 계약 | validated | `semantic_target_candidate_planning.py`, `inventory_query_language.py`, `inventory-query-language.yaml`, 집중 계획 검사 204개 통과, 인증된 한국어 Console 행렬 | Core는 정확한 신원이 하나로 정해지지 않은 단수 하위 유형 요청을 보안이 적용된 유형 필터 ObjectSet 하나로 바꾸고 `execution_authority=false`를 보존합니다. 스키마로 검증한 대상 수 신호는 FunctionType을 선택할 수 없고 컬렉션은 항상 단수보다 우선하며 정확한 신원은 후보 축소를 우회합니다. Current-source SRE 예시 첫 턴 8개는 hard-zero 표현 카운터가 모두 0인 검증된 목록 또는 후보 답변으로 완료됐습니다. 정확한 대상 기능 완성은 열린 상태입니다. |
| Kubernetes 워크로드 대상 선택 및 평가 | implemented | Kubernetes rollout, Pod 복구, Resource 이벤트 이력 플래너 및 FunctionType, 검토된 메트릭 의미 규칙, 프로바이더 읽기 경로, 집중 검사, 인증된 대상 없는 Console 증적과 정확한 대상 Console 증적 | 검토된 용어는 S12 및 S1 대상을 연결합니다. 정확한 Deployment 및 Pod 계획은 소유권과 동일 UID 재시작 변화량을 검증하고 `source_incomplete`를 보존하며 원인 및 실행 권한을 false로 유지합니다. Descriptor가 광고한 `resource_event.kubernetes` frame은 typed judgment duration이 범위가 제한된 frame lookback과 같을 때만 기존 2-node 계획으로 컴파일됩니다. 출처에 근거한 Resource 이름 하나가 있으면 서버 계획은 전체 Resource 유형으로 넓히지 않고 정확한 조건식을 추가합니다. Function은 정확한 현재 child 하나에 증적에 결속된 UID selector를 사용할 수 있고 identity가 없거나 일치하지 않으면 provider I/O 전에 incomplete로 유지합니다. 명시적인 cluster scope만 삭제된 객체 이력을 조회할 수 있습니다. 답변은 관측 행, 출처 완전성 및 정확한 제한 사항을 보여주고 `source_retention_unverified`이면 행 0개가 과거 부재를 증명하지 않는다고 명시합니다. 인증된 실행은 정확한 Event Function에 도달해 `source_unavailable`을 렌더링했으므로 성공적인 프로바이더 접근과 영속 보존은 열린 상태입니다. |
| 정확한 대상 메트릭 시계열 및 표현 | validated | `semantic_resource_metric_planning.py`, `resource_metric_queries.py`, `wire_semantic_query.py`, `presentation_artifact_v2.py`, 집중 검사, 인증된 표준 포트 Console 및 Browser 근거 | 명시적 시각화 요청은 T2 없이 `target_resource_metric_series`와 `query.resource_metric_series`를 사용했습니다. FunctionType은 source 표본 1085개에서 완전한 양 끝점 및 구간별 최솟값/최댓값 행 20/20개를 `display_truncated=false`로 반환했고 Operator는 검증된 시계열 블록과 exact-values 대체 표를 컴파일했습니다. 집계 요청은 `query.resource_metric_inventory`를 계속 사용하며 결과는 실행 권한을 부여하지 않습니다. |
| 명시적 리소스 필터 근거 확인 | 구현됨 | `semantic_planning_value_filters.py`, `test_semantic_planning.py`, focused 플래너 검사(`27 passed`) | Core는 발화에 명시된 모든 카탈로그 값 필터와 frame이 보존한 정확한 자유 텍스트 subject 하나를 유지합니다. 결과를 좁히는 조건식만 추가하고 subject가 발화에 그대로 존재해야 하며 실행 권한을 부여하지 않습니다. |
| 정확한 대상 상태 근거 평가 | validated | `semantic_health_planning.py`, `resource_health_assessment_queries.py`, 운영 의미 조립, 집중 검사 및 인증된 Console 증적 | 의미 런타임은 정확한 대상 하나와 명시적인 근거 또는 상태 평가 축이 있을 때만 보존된 읽기 전용 상태 frame을 수정합니다. Core는 범위가 제한된 노드 7개와 결정론적 평가 FunctionType을 컴파일합니다. 준비 상태, 애플리케이션 작업 성공, 의존성, 프로세스 재시작, 메모리, 로그, 최신성 근거가 불완전하면 명시적인 제한으로 유지되며 정상 상태로 보고할 수 없습니다. 같은 질문의 런타임은 T2나 관련 없는 행 없이 노드 7/7과 근거 검사 13/13을 완료했습니다. |
| 정확한 대상 요청 오류 및 Activity Log 상관 평가 | validated | `semantic_error_activity_planning.py`, `resource_error_activity_correlation_queries.py`, Azure 메트릭 및 읽기 조사 프로바이더, 집중 검사 및 인증된 Console 증적 | Core는 정확한 Resource 읽기 하나, 길이가 같은 직전/현재 `request.errors` 구간, 같은 구간의 Activity Log 읽기, 원인을 단정하지 않는 결정론적 reducer를 컴파일합니다. 완전한 0은 누락 근거와 구분하고 동시 관측은 인과관계가 되지 않으며 모델이 작성한 프로바이더 명령이나 실행 권한을 허용하지 않습니다. 재시작 후 같은 질문은 노드 5/5와 근거 검사 11/11을 완료했습니다. Activity Log는 검증된 0건을 반환했고 사용할 수 없는 요청 오류 매핑은 명시적인 공백으로 유지했습니다. |
| 타입 기반 extension 답변 projection | 구현됨 | `semantic_turn_processor.py`, focused Core processor 테스트 | 검증된 `TopologyGraphAt`, `TopologyDiff`, `MetricWindow`, `CausalEvidenceJoin` 출력은 exact digest, 완전성, 개수, 제한 사항 및 `execution_authority=false`가 있는 범위 제한 요약으로 렌더링됩니다. Raw provider payload는 계속 제외하고 evidence reference는 기존 receipt 경로로 전달합니다. |
| Principal 범위 스키마 인벤토리 | 구현됨 | `core/ontology_platform/manifest_queries.py`, `composition/wire_semantic_query.py`, focused 매니페스트, 핸들러, 조립 및 prompt 검사(`42 passed`) | `query.manifest`는 exact role 및 purpose 필터가 적용된 매니페스트에서 선언 인벤토리 질문에 범위 제한 일반 table과 호출 증적 하나로 답합니다. 임의 관계 또는 인스턴스 조회로 대체하지 않습니다. |
| 인시던트 의미 근거 | 구현됨 | `core/incident/ontology_projection.py`, `core/ontology_platform/incident_queries.py`, focused Core, Operator 및 Console 검사 | Canonical 인시던트 상태를 ObjectSet으로 조회할 수 있고 T0는 범위가 제한된 영향 근거를 기록하며, `query.incident_evidence`는 서로 다른 canonical 인시던트 신원과 감사 상관관계 신원을 보존하면서 감사 기반 프로파일, 상관 기록, 인용으로 근거를 확인한 기록된 근본 원인 또는 허용 목록의 결정론적 최종 실패, 영향 근거, 인용 및 명시적 공백을 반환합니다. 경로는 읽기 전용이며 실행 권한을 부여하지 않습니다. 인증된 Console 근거는 아직 남아 있습니다. |
| 증적에 결속된 의미 답변 권한 | 구현됨 | `functions.py`, `query_execution.py`, `intent_graph.py`, `semantic_turn_processor.py`, `semantic_turn_presentation.py`, 집중 Core, Operator 및 서비스 간 테스트 통과 | 서버 함수 레지스트리가 최초 권한 생산자입니다. 쿼리 노드와 목표 증적은 권한을 근거 참조와 함께 보관합니다. 구독 상태, 인벤토리 그래프, 사용량 측정 및 온톨로지 매니페스트 권한을 서로 구분합니다. 권한이 없거나 충돌하면 턴을 보류하며 모델 또는 클라이언트 권한 텍스트로 증적을 재정의할 수 없습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-09-01 | 구현됨 | 서비스와 담당 Agent 간 혼합 권한 보류를 명시적인 복합 읽기 권한 및 계보를 보존하는 인스턴스 경로 노드로 대체했습니다. 이 노드는 정확한 LinkType 선언 의존성을 검증하고 principal 범위의 현재 그래프를 하나의 저장소 스냅샷에서 읽으며, 완전하고 가려지지 않은 실제 경로에서만 신원 주장을 변환합니다. | `current change`, 서비스 계약, 온톨로지 조회, 플래너, 실행기, 프로바이더, 영속성 및 보증 집중 검사 451개 통과, Ruff 및 엄격한 mypy 통과 | 범위가 제한된 canary 10개를 실행합니다. 10개가 모두 통과한 경우에만 20개 캠페인을 제안하고 100개 캠페인은 시작하지 않습니다. |
| 2026-09-01 | 구현됨 | 첫 canary에서 확인된 완전한 빈 결과 경계를 수정했습니다. 실제 루트에서 Agent로 이어지는 서비스 담당 경로가 없으면 필요한 신원 사실 없이 답변 완료로 반환하지 않고 보류합니다. | `current change`, 집중 인스턴스 경로 및 의미 계획 검사. 첫 탐색용 EN/KO 관계 cohort는 예상된 서비스-Agent 빈 경로 실패 2건을 포함해 5/10으로 보존했습니다. | 의도된 canary cohort 10개를 다시 실행합니다. 10개가 모두 통과한 경우에만 20개 캠페인을 제안합니다. |
| 2026-09-01 | 구현됨 | 빈 경로 수정 후 의도된 exact-source canary 10개를 실행했습니다. 실제 매핑이 없을 때 소유권 결과를 안전하게 보류하여 `service-agent-authority.direct.en`이 통과했습니다. 전체 cohort는 8/10이었으며 `change-correlation` 처리 결과와 `service-current-health` 프레임 불일치는 이번 소유권 범위 밖에 남아 있습니다. | 출처 `e04ff33323f9eb25366d457ed2cc4b3f930f16d5`, 출처에 고정된 로컬 원장 다이제스트 `sha256:53212597522ce977dee23e7f64f090f56da614249c298e9fa6dc6cf4c389428d`. 기존 중지 표식과 질문, 평가 및 회귀 원장은 실행 전후 다이제스트가 같았습니다. | canary가 10/10이 아니므로 20개 캠페인을 제안하지 않습니다. 100개 캠페인은 계속 비활성화합니다. |
| 2026-09-01 | 구현됨 | 권한을 넓히지 않고 남은 canary 결함 2건을 해결했습니다. 바인딩되지 않은 변경 상관관계 판단은 이제 정확한 `compare/windowed` 프레임을 유지하고 타입이 지정된 보류를 반환합니다. 검토된 서비스 상태 질문은 별개의 Kubernetes `Service` 객체 대신 AKS에 배포된 비즈니스 서비스를 명시합니다. | 커밋 `a49aa3812`와 `c268e1f79`, 의미 계획 검사 398개, Golden 데이터 세트 및 질문 은행 검사 18개, Golden 캠페인 oracle 검사 10개가 통과했습니다. 이후 exact-source 라이브 시도는 Foundry 계정이 프라이빗 전용 상태가 된 후 구성된 모든 모델 요청이 HTTP 403을 반환했으므로 점수를 매길 수 있는 cohort가 아닙니다. 중지 표식과 기존 원장은 실행 전후 다이제스트가 같았습니다. | VNet 통합 runner에서 같은 exact-source cohort 10개를 실행합니다. 유효한 10/10 결과가 나온 후에만 20개를 제안합니다. 100개 캠페인은 계속 비활성화합니다. |
| 2026-09-01 | implemented | 검토된 운영 매핑, Rule 상태 및 추적, Resource 분류, 서비스 상태, 서비스 담당 체계에 의미 판단을 맞췄습니다. Golden 인증은 이제 커밋된 예상 최종 처리 결과를 사용하고, 새 근거가 필요한 답변 사례가 안전한 비답변으로 빠져나가는 것을 막으며, 모든 처리 결과에서 근거 및 권한 게이트를 유지합니다. | `current change`; 의미 판단 프롬프트, Golden 데이터 세트 어댑터 및 인증 테스트, Operator 로케일 전달 테스트, 집중 의미 및 Golden 검사, 검토된 라이브 canary의 정확한 계약 통과가 0/10에서 5/10으로 개선되었습니다. | 검증된 Rule 추적 및 서비스 담당 체계 실행을 구현하고, 대상 후보의 최종 처리 의미를 맞추며, 전체 Golden 범위를 주장하기 전에 완전한 관계 근거를 보존합니다. |
| 2026-09-01 | implemented | Framework와 FrameworkControl을 Identifiable 구현체로 등록했습니다. 인터페이스 구현 레지스트리는 이제 출하된 모든 객체 유형을 나열합니다. | `current change`; 집중 온톨로지 카탈로그 및 객체 유형 카탈로그 검사 통과. | 이 인터페이스 등록으로 추가 쿼리 커버리지 작업은 없습니다. |
| 2026-09-01 | 구현됨 | 터미널의 `ontology-query` 권한 평탄화를 증적에서 도출한 출처 권한과 타입이 지정된 누락 및 충돌 보류로 대체했습니다. | `current change`; 집중 Core, Operator, 계약 및 서비스 간 권한 테스트 통과 | 별도로 승인된 캠페인에서 관리되는 실제 증적을 보존하기 전까지 이 권한 경로를 검증됨으로 높이지 않습니다. |
| 2026-08-29 | implemented | 보안 ObjectSet 쿼리 소비 경계를 공유 의사 결정 핵심 근거 승인 결과로 마이그레이션했습니다. 정확한 결과 발행은 계속 범위가 제한되며, 이제 해석과 FunctionType 검증은 승인 결과가 없거나 일치하지 않거나 만료되면 차단합니다. 조립 seam은 주입된 프로바이더만 허용하고 합성 또는 기본 긍정 결속을 제공하지 않습니다. | `current change`; 쿼리 권한 및 핸들러 출처, 의미 조립, 집중 권한, Pod 텔레메트리, Pod 복구, rollout, 쿼리 핸들러 및 조립 테스트, Ruff 및 strict mypy. | 프로덕션 프로바이더를 신뢰할 수 있는 증적 검증기 레지스트리에 연결한 다음 인증된 서비스 간 쿼리 묶음을 보존합니다. |
| 2026-08-27 | implemented | 서버 소유 Event ObjectSet에 출처에 근거한 Resource 이름 하나를 보존하고 일반 검증 행 개수를 이중 언어 Resource Event 답변으로 교체했습니다. 답변은 범위가 제한된 정규화 Event field만 나열하고 출처 완전성, 안정적인 제한 사항 및 `execution_authority=false`를 항상 보고합니다. 보존이 확인되지 않은 행 0개는 과거 부재를 증명하지 않는다고 명시합니다. | `current change`, Event 계획, FunctionType, 읽기 경로, 조립, processor 및 Operator 표현 검사 287개 통과, Ruff, formatter 및 strict mypy 통과. 오래된 Core를 교체한 뒤 인증된 정확한 Deployment 후속 실행이 노드 2/2와 근거 검사 8/8을 완료하고 원인 또는 복구 주장 없이 범위가 제한된 `source_unavailable`을 렌더링했습니다. | 런타임 workload identity의 권위 있는 Kubernetes Event 출처 접근을 복구한 뒤 `source_retention_unverified` 또는 정규화 Event 행을 담은 정확한 child 결과를 보존합니다. 영속 이력은 별도의 열린 작업입니다. |
| 2026-08-27 | implemented | 구문 경로나 새 plan shape 없이 child-only Kubernetes Event 조회 공백을 닫았습니다. 기존 dependency-issued ObjectSet은 불변 identity-aware reader capability을 통해 inventory UID와 cluster를 전달하고, legacy reader는 호환성을 유지하며, Core는 다른 provider properties를 adapter에 노출하지 않습니다. | `current change`, 집중 FunctionType, 복합, Kubernetes, Azure, immutable identity, legacy compatibility, selector 전달, 위조 identity 검사 27개 통과, Ruff, formatter, strict mypy 통과 | 인증된 정확한 child 근거를 보존합니다. 영속 보존은 여전히 열려 있으므로 행 0개는 불완전한 과거 근거로 유지합니다. |
| 2026-08-26 | implemented | 구문 경로를 추가하지 않고 `query.resource_event_history`에 descriptor-driven Kubernetes Event 계획과 프로바이더 조립을 추가했습니다. 서버 계획은 정확한 ObjectSet 범위와 요청한 조회 구간을 유지하고, 복합 읽기 경로는 다른 기능군을 사용할 수 없을 때 사용할 수 있는 기능군의 근거를 보존하며, Kubernetes 어댑터는 불변 UID 또는 정확히 선택한 클러스터에 귀속하면서 프로바이더 메시지를 제외합니다. Judgment-bound 정규화는 명시적인 Kubernetes Event, Resource, typed duration, time-range 및 ordering 근거를 요구하고 typed duration과 frame lookback이 같아야 합니다. | `current change`, Resource 이벤트 FunctionType, Kubernetes 및 복합 읽기 경로, 런타임 연결, 공유 UID 신원 helper, 집중 계획, FunctionType, 어댑터, 라우팅, 조립 및 런타임 검사, 혼합 범위 보존, 인코딩 응답 거부, raw 256 KiB 상한을 검사했습니다. 의미 판단 v4와 frame v39가 canonical Kubernetes 기능군과 3,600초 조회 구간을 만들었고 인증된 정확한 클러스터 Console 턴이 6.8초에 노드 2/2와 근거 검사 8/8을 실행 권한 없이 완료했습니다. 행 0개는 과거 부재를 증명하지 않으며, 강화한 어댑터는 `source_retention_unverified`를 보고합니다. | 영속 이벤트 보존을 추가한 뒤 S1 원인 또는 복구를 닫기 전에 변경, replica, 교체 UID, 영향 범위, 새 기준 시점 근거를 결합합니다. |
| 2026-08-25 | implemented | S1의 정확한 Pod 의미 구획에 검토된 `pod.restart.history`와 명시적인 나가는 소유자 탐색을 추가했습니다. 서버 소유 5-node 계획은 모델이 작성한 계획 없이 정확한 Resource 하나를 선택하고, 30분 동일 UID 재시작 횟수 변화량을 읽고, ReplicaSet 하나와 Deployment 하나를 해석한 뒤 발급된 축약기를 호출합니다. 보안이 적용된 모든 증적과 소유권 link를 검증하고, 종속성의 정적 대체를 거부하며, 소유자 replica 전체의 복구를 요구합니다. | `current change`, 집중 메트릭, 검증기, Pod 축약기, 증적, 플래너, 운영 조립 검사 49개 통과, 의미 rollout 및 tier-routing 회귀 검사 370개 통과, Ruff, formatter, strict mypy 통과 | 인증된 정확한 Pod 근거를 보존하고 S1 원인 및 복구를 닫기 전에 독립적인 Kubernetes 이벤트, 변경, 교체 UID, 영향 범위, 새 기준 시점 근거를 추가합니다. |
| 2026-08-25 | implemented | 원본 완전성을 보존하면서 인증된 대상 없는 S12 턴을 완료했습니다. 보안이 적용된 ObjectSet 처리기는 불완전하고 잘리지 않은 그래프를 안정된 `source_incomplete` 표 제한으로 변환합니다. 따라서 후보 0개는 기능 실패나 부재 증명이 아니라 검증된 범위 제한 결과로 유지됩니다. | `current change`, `query_source_handlers.py`, 집중 대상 없는 요청, rollout, 증적, 탐색, 조립, 불완전 원본 검사 19개 통과, 인증된 Console에서 관측 이벤트 4개와 근거 검사 5/5를 `execution_authority=false`로 완료 | 정확한 Deployment 하나가 포함된 완전한 Kubernetes 세대를 구성한 뒤 정확한 대상 4-node 평가와 새 기준 시점 복구 턴을 보존합니다. |
| 2026-08-25 | implemented | S12의 지원되지 않음 경계를 두 단계로 닫았습니다. 대상 없는 요청은 유효하지 않은 인과 frame에서 정확한 Kubernetes Deployment 후보로 복구하고, 정확한 대상 후속 요청은 모델이 작성한 계획 없이 서버 소유 ObjectSet, 명시적 소유권 탐색 두 단계, 발급된 rollout FunctionType을 사용합니다. | `current change`, 집중 대상 없는 요청 및 rollout 수직 경로 검사 17개 통과, 작업 범위 Ruff 및 strict mypy 통과 | Core를 재시작하고 같은 질문의 후보 응답, 정확한 대상 근거 응답, 새 기준 시점의 복구 검증을 보존합니다. |
| 2026-08-22 | implemented | 의미 계획 escalation을 타입이 지정된 T1 unavailable trigger로 좁히고 인증된 서비스 간 요청에 별도의 no-T2 golden campaign profile을 추가했습니다. | `current change`, 집중 shared, Core, Operator, golden adapter, Console 검사 통과 | 560-turn 캠페인을 시작하기 전에 표준 port readiness probe를 실행합니다. |
| 2026-08-22 | validated | 비인과 집계, 근거, 목록, 시간 비교 T1 frame 변형의 결정론적 복구를 완료한 뒤 별도의 정확한 대상 메트릭 시계열 기능과 표현을 검증했습니다. | `current change`, 집계/시계열 격리 집중 검사 4개와 Ruff 및 strict mypy 통과, 인증된 Console이 query node 2/2개와 근거 검사 8/8개를 완료했고 기술 출력이 반환/전체 행 20/20개, 완전한 근거, `min_max_envelope_v1`, 표시 잘림 없음을 보고했으며 세 viewport 검사에서 비어 있지 않은 막대 20개와 문서 및 Deck overflow 0을 확인 | 남은 정확한 대상 활동 및 인과 cell을 완료합니다. 더 넓은 통제된 request-to-Console 및 무작위 보증은 별도 열린 근거로 유지합니다. |
| 2026-08-22 | implemented | 인증된 Console에서 시각화 요청이 7일 평균 행 하나로 축약된 것을 확인한 뒤 별도의 정확한 대상 메트릭 시계열 기능을 추가했습니다. Frame, 검증된 plan, FunctionType, presentation intent가 브라우저 추론 없이 요청된 추세를 보존합니다. | `current change`, 집중 메트릭 FunctionType, T1 계획, 조립 가시성, prompt 레지스트리, Operator 표현 검사 43개 통과, 변경한 운영 파일의 Pylance 진단 없음 | 로컬 Core와 Operator 서비스를 재시작하고 런타임 검증을 주장하기 전에 인증된 3개 viewport 근거를 보존합니다. 더 넓은 정확한 대상 7/7 행렬은 열린 상태입니다. |
| 2026-08-22 | validated | 정확한 대상이 없는 Resource 하위 유형 질문에 서버 소유 후보 조회 형태와 스키마로 검증한 단수 및 컬렉션 게이트를 추가했습니다. 유효하지 않거나 사용할 수 없는 단수 모델 frame은 T2 전에 복구할 수 있고 컬렉션 요청과 정확한 대상은 기존 기능 경로를 유지합니다. | `current change`, 집중 플래너 검사 204개 통과, Ruff, formatter, strict mypy 통과, 인증된 current-source Console에서 한국어 SRE 예시 첫 턴 8개 전체가 context-required, unsupported, held, unverified, 의미 대체 답변, 실행 권한 없이 완료됨 | 타입이 지정된 정확한 대상 인그레스, 범위가 제한된 7일 활동, 공식 Container Apps `MemoryPercentage`, 결정론적 인과 조사 완성을 추가합니다. 검증 범위를 확대하기 전에 정확한 대상 증적 7/7을 보존합니다. |
| 2026-08-21 | implemented | SRE Agent 비교 표면에서 가져온 서로 다른 한국어 Console 질문 30개를 실행하고 드러난 상태 및 근거 기능군 대체를 수정했습니다. Core는 이제 `query.resource_state_inventory`로 컬렉션 상태를 컴파일하고, 근거가 없는 모델 enum 피연산자와 표시 필드용 존재 조건식을 거부하며, 카탈로그가 선언한 구독 상태 평가를 현재 인벤토리 상태와 분리하고, 근거 커버리지 또는 화면 범위가 없으면 넓은 Resource 답변 전에 멈춥니다. Frame prompt v31-v34는 후보 지침으로만 유지되고 exact 매니페스트, 서버 소유 plan, 결정론적 기능 정렬이 계속 권한을 가집니다. | `current change`, 집중 의미 계획, tier-routing, FunctionType, 조립, prompt 레지스트리, Operator 표현 검사, 인증된 로컬 Console 수정 후 관측. 중지된 데이터베이스 상태 행은 검증된 결과로 반환했고 맥락, 혼합 상태 평가, 인벤토리 커버리지 및 바인딩되지 않은 근거 기능군은 관련 없는 행이나 실행 권한 없이 보류했습니다. | 전용 컬렉션 상태 평가, 메트릭, 이벤트 이력, 인벤토리/상태 커버리지 및 맥락 Resource FunctionType을 바인딩합니다. Console, Operator, Core 전체에 타입이 지정된 선택 화면/그룹 신원을 전달한 뒤 런타임 보증을 높이기 전에 통제된 이중 언어 캠페인 산출물을 보존합니다. |
| 2026-08-21 | validated | 정확한 요청 오류 및 Activity Log 상관 질문에 대한 일반 근거 보류를 서버 소유 5-node plan과 소스에서 파생한 결정론적 reducer로 교체했습니다. Reducer는 이어지는 동일 길이 구간을 비교하고 검증된 0을 사용할 수 없는 텔레메트리와 구분하며 `causal_claim_supported=false`와 `execution_authority=false`를 고정합니다. | `current change`, 집중 플래너, reducer, 조립, 처리기, Operator 표현 테스트 218개, Ruff, formatter, strict mypy, ontology-query coverage, independent-service, file-LOC, fanout, diff 검사 통과, 인증된 Console이 `plan_source=server_target_error_activity`와 T2 없이 5.8초에 노드 5/5와 근거 검사 11/11을 source 6개로 완료 | `http.server.request.error.count`의 권한 있는 Azure 매핑을 결속합니다. 현재 Container Apps direct Metrics map은 CPU와 응답 시간은 노출하지만 요청 오류는 노출하지 않으므로, 정확한 Activity Log 0건은 보존하되 오류 추세와 상관관계는 확인되지 않은 상태로 유지합니다. |
| 2026-08-21 | validated | 같은 질문의 정확한 대상 상태 대체 결함을 닫았습니다. 이전에는 `validate/evidence_validation` frame이 principal 범위 ObjectSet을 만들고 관련 없는 행 586개 중 20개를 반환했습니다. 전용 상태 기능군은 I/O 전에 대상, 현재 상태, 범위가 제한된 활동, 검토된 메트릭 3개, 결정론적 근거 불충분 reducer를 결속합니다. | `current change`, 인증된 Azure/FDAI 비교, 집중 플래너, 함수, 처리기, 표현, 조립 검사 202개, Ruff, formatter, strict mypy, ontology-query coverage, independent-service, design-route gate 통과, 재시작 후 Console이 6.7초에 노드 7/7과 근거 검사 13/13을 `execution_authority=false`로 완료 | 프로세스 재시작, 런타임 로그, 메모리, 의존성, 성공한 작업 근거는 열린 프로바이더 작업으로 유지하며 답변에 명시해야 합니다. |
| 2026-08-13 | 진행 중 | 이전 출처 이력을 재구성하지 않고 구현 ledger를 도입했습니다. | 구현 범위 표에 나열된 현재 출처, 테스트 및 상태 근거 | 아래의 실제 운영 보증 및 프로바이더 조립 근거를 확보합니다. |
| 2026-08-13 | 구현됨 | 10회가 넘는 adversarial 검토를 통해 Rule 검색 계약, Core 멱등성과 점유, Operator 재시도와 임대, exact 영속성, 재생 및 소유권 검증을 강화했습니다. | `current change`, `pytest -q services/core-control-plane/tests/test_semantic_turn_processor.py services/operator-service/tests/test_semantic_turn_bridge.py services/operator-service/tests/test_operator_workflow_family.py tests/integration/test_semantic_turn_roundtrip.py` 테스트 88개 통과, 작업 범위 Ruff 통과 및 롤백 전용 PostgreSQL 트랜잭션 검사 통과 | 운영 검증은 통제된 실제 증적을 확보할 때까지 차단됩니다. |
| 2026-08-13 | 구현됨 | 결정론적 인벤토리 승격 토폴로지 개정 번호 발행과 추가 전용 bitemporal PostgreSQL 읽기/쓰기를 추가하고 현재/과거 파생 쓰기를 독립시켰습니다. | `current change`, 범위가 제한된 인벤토리/토폴로지 테스트 31개 통과, 작업 범위 Ruff 및 mypy 통과 | 과거 읽기 경로를 운영 의미 조회 런타임에 연결하고 통제된 런타임 근거를 확보합니다. |
| 2026-08-13 | 구현됨 | Temporal 토폴로지, metric-series 및 evidence-join 기능을 exact-release 의미 런타임 조립에 연결했습니다. 선택적 메트릭 의존성은 원자적으로 처리하며 프로바이더가 없으면 검증기와 실행기 모두에서 사용 불가 상태를 유지합니다. | `current change`, `wire_semantic_query.py`, `bootstrap.py`, `test_wire_semantic_query.py`, `test_bootstrap_config.py`, focused 검사 16개 통과 | 통제된 request-to-Console 및 무작위 보증 증적을 기록합니다. |
| 2026-08-13 | 구현됨 | 구체적인 의미 조회 프로바이더 선택을 런타임 바인딩 도우미로 옮겨 프로세스 진입점이 검토된 조립 fanout 범위 안에 머물도록 했습니다. | `current change`, `bootstrap.py`, `bootstrap_bindings.py`, `test_bootstrap_config.py`, focused 프로바이더 선택 테스트 3개 통과 | 통제된 request-to-Console 및 무작위 보증 증적을 기록합니다. |
| 2026-08-13 | 진행 중 | 타입 기반 증적 oracle과 계산된 준비 상태 카운터를 사용하는 인증된 요청-Console 및 결정론적 이중 언어 무작위 보증 실행기를 추가했습니다. | `current change`, 통과한 focused Console 테스트, 보증 oracle 테스트, typecheck 및 Playwright discovery | 인증된 로컬 스택에서 두 실행기를 실행하고 통과한 두 보존 근거 기록을 연결합니다. |
| 2026-08-13 | 구현됨 | 유효한 호출자 제공 요청 UUID를 Operator 의미 묶음과 상관관계 신원 전체에서 보존하면서 멱등성 키와 혼합하지 않았습니다. 요청 신원을 생략하는 호출자를 위한 결정론적 UUID 대체값은 유지했습니다. | `current change`, `semantic_turn.py`, `test_semantic_turn_bridge.py`, focused 호출자 신원 및 재시도 안정성 테스트 통과 | 무작위 보증을 실행하기 전에 exact 요청 신원의 통제된 인증 증적을 확보합니다. |
| 2026-08-14 | 구현됨 | 서버 소유 `bound_context`를 담은 추가적 `operator-core-request` 1.3.0을 도입해, Console 인시던트 대화가 바인딩된 인시던트 신원을 버리지 않고 Core까지 전달합니다. Core는 해당 바인딩을 마지막 `system` 맥락 턴으로 붙여 플래너의 제한된 창이 버리지 못하게 합니다. | `current change`, `semantic_turn.py`(계약/Operator/Core), `contract_codecs.py`, `compatibility-manifest.json`, Core 처리기 32개·Operator 브리지 42개·계약 76개·라우트 대상 326개 통과, independent-services 및 ontology-query-coverage 게이트 통과, strict mypy 통과 | 바인딩된 인시던트는 아직 답변 가능하지 않습니다. 의미 질의 매니페스트가 인시던트 ObjectSet과 인시던트 근거 FunctionType을 노출하지 않아 인시던트 조사는 명확화로 귀결됩니다. |
| 2026-08-14 | 구현됨 | 의미 요청 발행기를 1.3.0 producer 코덱으로 옮겼습니다. 묶음 빌더는 이미 1.3.0을 검증했기 때문에, 낡은 발행기가 바인딩된 모든 턴을 조용히 거부해 Console 요청이 Core에 도달하지 못했습니다. | `current change`, `semantic_kafka.py`, Operator 어댑터 및 브리지 스위트 51개 통과, 재시작한 로컬 스택이 바인딩된 인시던트 턴을 6.4초에 응답했고 Core가 디코딩 실패 없이 계획 3단계를 기록 | 인시던트 역량이 여전히 열린 공백입니다. |
| 2026-08-14 | 진행 중 | Canonical `Incident` 인스턴스를 projection하고 추가 전용 감사 출처 위에 exact-release, correlation-scoped `query.incident_evidence` FunctionType을 추가했습니다. 함수는 프로파일, 상관 기록, 잘림 및 근거 공백을 노출하면서 `cause_claim_supported=false`와 `execution_authority=false`를 고정합니다. | 커밋 `285341732` 및 `current change`, focused 인시던트, registry, adapter 및 의미 조립 검사 62개 통과, 작업 범위 Ruff 및 strict mypy 통과 | A3 답변 계약과 액션 초안 전용 다음 안전 단계를 추가하고 인증된 Console 근거를 보존합니다. |
| 2026-08-14 | 진행 중 | 초기 인시던트 FunctionType 계약을 수정해 바인딩된 Console 맥락의 canonical `incident_id`와 감사 `correlation_id`가 검증된 계획 실행 및 근거 변환 전체에서 서로 다르게 유지되도록 했습니다. | `current change`, 인시던트 FunctionType 테스트와 end-to-end 의미 조립 회귀가 통과해 focused 범위가 63개 사례가 되었습니다. | 로컬 스택을 재시작하고 같은 인증된 인시던트 턴을 검증한 뒤 기능 상태를 변경하기 전에 통제된 근거를 보존합니다. |
| 2026-08-14 | 진행 중 | 의미 frame 및 plan prompt v2를 서로 다른 바인딩 신원에 맞춰 모델이 잘못된 부분 인자 집합을 만들지 않고 검증된 Function node에 `incident_id`와 `correlation_id`를 모두 보존하도록 했습니다. | `current change`, focused prompt registry 계약 5개 사례 통과 | 기능 상태를 변경하기 전에 로컬 스택을 재시작하고 같은 인증된 인시던트 턴을 검증합니다. |
| 2026-08-14 | 구현됨 | 지역화되고 읽기 쉬운 내용, 재생 가능한 관찰 진행 상황, 접힌 exact 기술 출력, 명시적인 인과 및 근거 공백, 기본 다음 단계인 읽기 전용 근거 수집, 재생성에서 유지되는 검증된 인시던트 정체성을 포함하도록 인시던트 답변 변환을 완료했습니다. | `current change`, Core 집중 검사 36개, Operator 46개, 교차 서비스 1개, Console 74개와 Console 타입 검사 및 작업 범위 Ruff 통과, 보존하지 않은 인증된 Browser Entra 관찰에서 재생성 뒤에도 동일한 검증된 감사 기록 3건 결과를 확인했습니다. | 이 범위를 `검증됨`으로 승격하기 전에 통제된 request-to-Console 근거와 한국어 동등 근거를 보존합니다. |
| 2026-08-14 | 구현됨 | 원래의 범위가 제한된 history와 검증된 요청 신원을 보존하고, 요청 신원을 Operator 멱등성에 결속하고, 정본 locale을 전달하고, 반복되는 Azure throttling 또는 schema-invalid 후보를 adapter budget 안에서 재시도해 의미 재생성을 재시도에 안정적으로 만들었습니다. | `current change`, Console stream, normalizer, session 및 event 집중 검사 128개와 Azure 의미 계획 adapter 검사 5개가 통과했고 Console 타입 검사와 작업 범위 Ruff가 통과했습니다. 보존된 인증 한국어 Browser working-tree 실행은 두 턴 모두 통과했고 Core 계획 수명 주기 5단계가 한 번만 관찰됐습니다. | 범위가 제한된 변경을 커밋하고 중앙 검증한 뒤 exact-source 인증 Browser 산출물을 보존해야 인시던트 답변 행을 `검증됨`으로 승격할 수 있습니다. |
| 2026-08-14 | 검증됨 | 중앙 검증 뒤 범위가 제한된 인증 인시던트 답변 근거 공백을 닫았습니다. | Source revision `7f2b740b1` 및 `244d003ef`에 중앙 receipt가 있고, 보존된 post-validation 한국어 Browser 산출물은 재생성 전체에서 일치하는 요청, 인시던트 바인딩 및 기술 출력 digest, 관찰된 단계 5개, 실행 권한 없음을 기록합니다. | 전체 request-to-Console 실행기와 이중 언어 무작위 집단은 운영 보증의 열린 작업으로 유지합니다. |
| 2026-08-14 | in-progress | 현재 bounded action-draft 및 browser-readiness 변경에 새 governed artifact가 필요해 incident assurance를 다시 열었습니다. | `current change`, focused semantic, Console 및 browser-assurance 검사 | `validated`를 복원하기 전에 replacement request-to-Console 및 bilingual randomized evidence를 보존합니다. |
| 2026-08-15 | 구현됨 | 로컬 서술기 갱신을 의미 전송과 독립적으로 유지하면서 전송에 의해 제한되는 `SemanticTurnBridge` 활성화 계약을 보존했습니다. | `current change`, 집중 운영 조립 및 의미 브리지 검사 2개와 작업 범위 Ruff가 통과했습니다. | 운영 보증 상태를 변경하기 전에 통제된 요청-Console 및 이중 언어 무작위 근거를 보존합니다. |
| 2026-08-15 | 구현됨 | Machine-readable 명확화 requirement를 추가하고 Core가 이미 바인딩한 principal 범위 또는 용도를 묻는 T1 frame 제안을 거부했습니다. 의미 frame prompt v4는 두 tier 모두 해당 값을 trusted server context로 취급하도록 지시합니다. | `current change`, focused 의미 planner 검사 21개, prompt 및 Azure adapter 검사 10개, 작업 범위 Ruff와 strict mypy 통과 | 중앙 검증 뒤 Core를 재시작하고 통제된 요청-Console 보증 경로를 다시 실행합니다. |
| 2026-08-15 | 구현됨 | 검증된 topology graph, topology diff, metric window 및 causal join 출력을 위한 범위 제한 projection을 추가했습니다. | `current change`, focused Core processor 테스트 43개와 작업 범위 Ruff 및 strict mypy 통과 | Planner 계약을 활성화한 뒤 인증된 temporal 및 causal 답변 근거를 보존합니다. |
| 2026-08-15 | 구현됨 | `query.manifest`를 통한 exact-release 스키마 인벤토리 조회, 닫힌 함수 table 변환, 인벤토리, 속성 filter, topology, aggregation 및 causal 질문의 명시적 frame/plan grammar를 추가했습니다. | `current change`, focused 매니페스트, 핸들러, 조립, 관계, 의미 조립 및 prompt 검사 42개와 작업 범위 Ruff 및 strict mypy 통과 | Clean 통과 14-cell 산출물을 보존한 뒤 seed 기반 100-case 집단을 실행하고 답변 근거가 하나라도 누락되면 준비 상태를 계속 차단합니다. |
| 2026-08-15 | 구현됨 | 직접 ObjectSet 집계 필드를 실행 전에 exact 행 스키마와 대조해 유효하지 않은 T1 plan만 T2로 plan 단계를 다시 시도하도록 했습니다. | `current change`, focused 검증기 및 tier 라우팅 검사 16개와 작업 범위 Ruff 및 strict mypy 통과 | Clean 14-cell 및 seed 기반 100-case 근거를 보존하기 전에 보류된 한국어 집계 cell을 다시 실행합니다. |
| 2026-08-15 | 구현됨 | 집계 필드 스키마를 table-transform 의존성 전체에 전파하고 점 표기 projection 필드를 결정론적 downstream 집계에서 보존했습니다. | `current change`, focused 검증기, 핸들러 및 tier 라우팅 검사 24개와 작업 범위 Ruff 및 strict mypy 통과 | Clean 14-cell 및 seed 기반 100-case 근거를 보존하기 전에 보류된 한국어 집계 cell을 다시 실행합니다. |
| 2026-08-15 | 구현됨 | Plan 검증 전에 모델이 제안한 모든 ObjectSet 기준 시각을 단일 trusted evaluation time으로 다시 바인딩해, secured gateway 허용 구간을 벗어난 모델 timestamp 때문에 current-state 실행이 거부되지 않게 했습니다. | `current change`, stale 모델 기준 시각 회귀를 포함한 focused 의미 계획 테스트 15개 통과 | Exact-source Core stack을 재시작하고 clean 14-cell 및 seed 기반 100-case Browser 근거를 보존합니다. |
| 2026-08-16 | 구현됨 | 시작 시 영속 `Incident` 객체를 읽기 전에 durable 온톨로지 release 이력을 먼저 적재하도록 했습니다. 이전에는 인시던트 projection이 catalog 동기화보다 먼저 실행돼, 이전 catalog digest에 고정된 객체가 모두 fail closed 되고 catalog가 한 번이라도 바뀌면 런타임이 시작되지 못했습니다. | `current change`, bootstrap 순서 가드를 포함한 focused catalog-ontology 검사 6개 통과, 작업 범위 Ruff 및 strict mypy 통과, 로컬 스택 시작 후 바인딩된 인시던트 turn 응답 확인 | 이 행에 남은 작업은 없습니다. |
| 2026-08-16 | 구현됨 | 바인딩된 인시던트 읽기를 서버 소유로 만들었습니다. 계획 단계가 제안된 `query.incident_evidence` 노드의 식별자와 기록 조회 범위를 대화 바인딩 값으로 다시 쓰고 plan을 재검증하므로, 모델이 문장으로만 가진 UUID와 correlation 신원을 그대로 옮겨 적는 데 답변이 좌우되지 않습니다. 조회한 감사 구간 밖에 신원 기준 기록이 있는 프로파일은 모순이 아니라 근거 공백으로 처리하며, fail closed 보류마다 실패한 검사 이름을 런타임 로그에 남깁니다. | `current change`, focused 대화, 처리기 및 계약 검사 606개 통과, 작업 범위 Ruff 및 strict mypy 통과, 변경 전 동일 입력에서 연속 2회 보류되던 바인딩 인시던트 turn이 변경 후 두 언어에서 연속 4회 응답 | 복구된 인시던트 답변에 대한 통제된 요청-Console 및 이중 언어 무작위 근거를 보존합니다. |
| 2026-08-16 | 구현됨 | Prompt 업그레이드에서 `object_types`, limit 및 `root_ids` 금지 제약이 빠진 뒤 의미 plan prompt v8에 exact `query.ontology_relationships` Function 묶음을 복원했습니다. 이제 스키마 관계 plan은 검증된 frame의 exact ObjectType 이름 한두 개만 사용하며 이를 런타임 객체 신원으로 다시 해석할 수 없습니다. | `current change`, `test_wire_ontology_relationships.py::test_semantic_prompts_select_exact_relationship_function` 통과 | 중앙 검증된 후속 commit에서 엄격한 이중 언어 관계 cell과 seed 기반 집단 근거를 보존합니다. |
| 2026-08-16 | 구현됨 | 고정된 인시던트 읽기에서 모델을 완전히 제외했습니다. 이 turn이 인시던트 근거를 원한다는 판단은 여전히 타입이 있는 frame이 하고, 그 뒤 노드는 바인딩에서 구성되어 plan 제안을 요청하지 않으며 동일한 빌더와 검증기가 그대로 적용됩니다. 바인딩이 `incident_reference` 확인 요구를 해소해 고정된 turn이 이미 고정된 인시던트를 되묻지 않고, 영어 전용 `this incident` 부분 문자열 경로를 제거해 어떤 발화 부분 문자열도 경로를 결정하지 않습니다. | `current change`, focused 대화 검사 458개와 로컬 서비스 로그 실행기 검사 11개 통과, 작업 범위 Ruff 및 strict mypy 통과, 라이브 고정 turn 3회 연속 `plan_source="bound_incident"` 기록 및 응답 | 통제된 요청-Console 및 이중 언어 무작위 근거를 보존합니다. |
| 2026-08-16 | 구현됨 | 고정된 읽기에 대한 비평 지적 4건을 해소했습니다. 재작성 경로를 제거했고, 읽기 범위는 근거 역량의 기록 상한을 따르며, 답변은 검증된 총계와 잘림을 명시하고, 영속 요청이 없는 변환 결과는 제한된 재시도 뒤 격리되어 이후 변환 결과를 막지 않습니다. | `current change`, focused Core 검사 913개와 Operator 검사 310개 통과, 재시작한 Operator가 막혀 있던 미매칭 변환 결과 20건을 배출하고 정상 상태로 복귀 | 통제된 요청-Console 및 이중 언어 무작위 근거를 보존합니다. |
| 2026-08-16 | 구현됨 | 답변 표현 경계에 소유자 교차 가드를 추가하고 변환 결과 충돌 카운터에 상한을 두었습니다. | `current change`, 가드가 Console의 slot 허용 목록과 상한을 직접 읽어 두 언어의 모든 artifact를 검사, Operator 검사 318개 통과, 알 수 없는 slot으로 바꾸면 가드가 실패 | 통제된 요청-Console 및 이중 언어 무작위 근거를 보존합니다. |
| 2026-08-16 | 구현됨 | 기록 시각이 역행하는 인시던트 근거를 보류합니다. 답변은 뒷부분을 잘라 최신 기록이라고 말하는데 리더의 순서를 검증하는 곳이 없었습니다. | `current change`, focused 처리기 검사 54개 통과, 라이브 인시던트 상관관계 2건이 해당 불변식 활성 상태에서 응답 | 통제된 요청-Console 및 이중 언어 무작위 근거를 보존합니다. |
| 2026-08-16 | 구현됨 | 바인딩이 `incident_reference` 질문을 대신 해소하는 범위를 좁혔습니다. 고정된 인시던트를 읽는 turn에서만 바인딩이 답하고 다른 output shape에서는 질문이 유지되므로, 운영자가 보지 못한 질문 뒤에서 제안된 plan이 다른 인시던트를 읽을 수 없습니다. | `current change`, focused 대화 검사 458개 통과, shape 조건을 제거하면 새 사례가 실패, 라이브 고정 turn 4회가 두 언어에서 `plan_source="bound_incident"`로 응답 | 통제된 요청-Console 및 이중 언어 무작위 근거를 보존합니다. |
| 2026-08-16 | 구현됨 | 읽기가 이미 담아 온 인시던트 근거를 실제로 보고합니다. `query.incident_evidence`가 각 기록의 행위 주체를 버려 세어 놓은 기록을 누구에게도 귀속할 수 없었고, 프로파일에 제목·심각도·버티컬·최초·최종 기록 시각이 있는데도 두 표면 모두 상태만 보고했습니다. 이제 projection이 행위 주체를 보존하고, 두 표면 모두 값이 있는 프로파일 필드를 모두 나열하며 제목에 자기 상한을 밝힌 기록 활동 표를 덧붙이고, 다음 안전 단계는 측정한 공백을 따릅니다. 값이 있는 필드만 나열해 미기록 상태가 사라지지 않도록 상태 미기록 사실을 계속 밝히고, 보고하는 건수는 검증한 총계를 유지합니다. | `current change`, `incident_queries.py`, `semantic_turn_processor.py`, Operator 표현 계층, focused Core 검사 388개와 Operator 검사 322개 통과, 작업 범위 Ruff와 strict mypy 통과, mutation 3건이 각각 정확히 가드 하나씩만 실패시킴 | 통제된 요청-Console 및 이중 언어 무작위 근거를 보존합니다. |
| 2026-08-16 | 구현됨 | 한국어 다음 안전 단계가 한국어 문장으로 읽히게 했습니다. 측정한 공백이 여러 개일 때 경어 명령문을 쉼표로 이어 붙여 한국어 문장이 아니었으므로, 여러 단계는 도입 문구로 시작해 각각 독립된 문장이 됩니다. | `current change`, focused 처리기 검사 60개 통과, 새 사례가 단일 단계와 복수 단계 형태를 모두 고정 | 이 행에 남은 작업은 없습니다. |
| 2026-08-17 | implemented | 인시던트 의미 경로를 통해 기록된 grounded RCA, 영향 근거 및 인용을 노출했습니다. T0는 기존 발견 사항 심각도와 리소스 타입 범위를 영향 근거로 기록하고 알 수 없는 측정값은 비워 둡니다. Core 변환 결과는 일치하는 인용이 포함된 grounded 가설이 있어야 원인을 지원하며, Operator와 Console은 액션 권한을 추가하지 않고 두 언어로 세 근거 섹션을 렌더링합니다. | `current change`; focused Core, Operator 및 Console 검사 138개 통과, Ruff, strict mypy 및 Console typecheck 통과 | 기록된 RCA 인시던트와 명시적 근거 공백이 있는 인시던트에 대해 인증된 Browser 근거를 보존합니다. |
| 2026-08-17 | implemented | Append, lease claim, 요청 조회 및 변환 결과 소유권을 하나의 Operator 실행에 묶는 선택적 영속 semantic outbox 네임스페이스를 추가했습니다. 기본 네임스페이스는 운영과 byte-compatible하게 유지합니다. 격리된 보증 Operator는 실행 id를 사용하므로 동시에 실행 중인 표준 Operator가 측정 요청을 다른 Core 세대를 통해 게시할 수 없습니다. | `current change`, focused Operator bridge, composition 및 supervisor 검사 114개 통과, 작업 범위 Ruff 및 strict mypy 통과 | Seed 기반 집단을 시작하기 전에 중앙 검증된 네임스페이스 runner에서 새로운 엄격한 아티팩트를 보존합니다. |
| 2026-08-17 | implemented | 허용 목록의 알림 최종 실패를 정확한 감사 행에서 변환해 활성 인시던트의 세 근거 공백을 닫았습니다. `route_unresolved`, `trust_mismatch`, `escalated_to_hil`은 범위가 제한된 T0 원인, 영향 및 인용 레코드를 만들며 성공하거나 알 수 없는 결과는 만들지 않습니다. | `current change`; focused 인시던트, 의미 처리기 및 Operator 표현 검사 133개 통과, Ruff 및 strict mypy 통과 | Exact-source 로컬 스택을 재시작하고 인증된 positive 경로 근거를 보존합니다. |
| 2026-08-17 | implemented | 의미 plan prompt v8을 v9으로 교체하고 검증기의 exact 선언 집계 및 속성 predicate envelope을 고정했습니다. 선언 개수는 `query.manifest` 의존성 하나와 범위가 제한된 aggregate 출력 하나를 사용하며, 존재, 동등 및 membership 필터는 허용된 operand 필드만 사용합니다. | `current change`, v9만 포함한 격리된 tracked 카탈로그에서 focused prompt 계약 검사 2개 통과, 작업 범위 Ruff 및 strict mypy 통과 | Seed 기반 집단을 시작하기 전에 새로운 엄격한 아티팩트를 보존합니다. |
| 2026-08-17 | implemented | 읽기 전용 metric window 어댑터의 명시적인 `MetricProviderError`를 범위가 제한된 사용할 수 없는 불완전한 구간으로 변환했습니다. 부분 sample은 폐기하고 요청한 concept과 구간은 인용하며, causal join은 `execution_authority=false`인 `UNRESOLVED` 상태를 유지합니다. 프로바이더 신원 drift와 잘못된 데이터는 계속 fail closed 됩니다. | `current change`, focused metric 및 causal semantics 검사 12개 통과, 작업 범위 Ruff 및 strict mypy 통과 | Exact-source 스택에서 새로운 엄격한 causal cell을 보존합니다. |
| 2026-08-17 | implemented | 두 metric window 의존성이 이미 요구하는 상위 scope를 중복으로 지정한 causal evidence join을 정규화했습니다. 계획 단계는 exact plan digest를 다시 만들기 전에 해당 전이 edge만 제거하며 principal 매니페스트, metric concept, 검증기 및 실행 handler는 변경하지 않습니다. | `current change`, focused 의미 구성 회귀 검사가 이전 `semantic_plan_invalid` 결과를 재현하고 이제 검증된 4-node 읽기 전용 DAG로 통과합니다. | 중앙 검증 증적을 확보하고 새로운 영어 causal cell을 보존한 뒤 엄격한 질문 집합을 다시 실행합니다. |
| 2026-08-17 | implemented | 타입이 지정된 frame을 수락한 뒤 검증된 principal 범위 `Resource` 서술자에서 evidence-validation plan을 구성했습니다. Frame prompt v8은 더 좁은 모델 선택 subject를 요구하지 않고 principal-scope 근거 검사를 완전하게 유지하며, plan prompt v10은 Core가 단일 secured ObjectSet plan을 소유한다고 기록합니다. Exact release, 매니페스트, 역할, 목적, ObjectSet 스키마, plan digest 및 실행 handler 검사는 변경하지 않습니다. | `current change`, focused tier 라우팅 및 prompt 레지스트리 회귀 검사가 통과하며 T1과 T2 어느 쪽도 evidence plan을 제안하지 않음을 입증합니다. | 중앙 검증을 확보한 뒤 새로운 이중 언어 evidence-validation cell을 보존하고 엄격한 질문 집합을 다시 실행합니다. |
| 2026-08-17 | implemented | 기본 semantic outbox claim 경로와 실행 범위 보증 행 사이의 겹침을 닫았습니다. 이전 namespace는 key prefix를 변경했지만 기본 `prefix%` claim은 중첩된 namespaced key도 계속 선택했습니다. 이제 영속 요청이 명시적인 namespace token을 보존하고, claim, 인증된 읽기 및 변환 결과 소유권이 exact namespace 동등성을 요구하며 기존 기본 행은 빈 token으로 해석됩니다. | `current change`, 기본 claim과 namespaced claim, append, 읽기 및 변환 결과 회귀를 포함한 focused Operator bridge 검사 64개와 작업 범위 Ruff 및 strict mypy 통과. 이전 엄격한 아티팩트 두 개는 전용 요청 토픽을 각각 12/14 및 9/14만 전진시켰고, 범위가 제한된 high-watermark 읽기에서 빠진 5개 request/projection 쌍이 표준 physical stream에 있음을 확인했습니다. | Seed 기반 질문 집합을 시작하기 전에 exact 실행 범위 transport coverage가 있는 새로운 엄격한 아티팩트를 보존합니다. |
| 2026-08-17 | implemented | Runner의 exact transport 관측을 hashed topic identity와 단계별 건수로 각 원본 아티팩트에 연결하고, 리포지토리에 안전한 변환기에도 같은 근거를 요구했습니다. 따라서 답변 필드를 만족하지만 exact 실행 범위 request/projection coverage가 없는 아티팩트는 나중에 runner 밖에서 승격될 수 없습니다. | `current change`, focused runner 및 baseline-projector 검사 13개와 작업 범위 Ruff 및 strict mypy 통과 | Exact 14/14 transport 근거가 포함된 새로운 엄격한 아티팩트를 보존합니다. |
| 2026-08-17 | implemented | 감독 대상 보증 실행마다 Vite 의존성 캐시 소유권을 할당했습니다. 이전 exact-source 시도는 모든 서비스 준비 상태 검사를 통과했지만 첫 측정 turn 전에 Browser 사전 단계가 오래된 공유 MSAL optimizer URL을 가져왔습니다. 이제 runner는 자기 실행 루트 아래 캐시를 지정하고 일반 Console 시작은 표준 기본값을 유지합니다. | `current change`, 실패한 시도는 질문을 하나도 실행하지 않았고 아티팩트도 생성하지 않음, focused Console 캐시 검사 2개, supervisor 검사 9개, Console typecheck, Ruff 및 strict mypy 통과 | 중앙 검증된 캐시 격리 소스에서 새로운 엄격한 아티팩트를 보존합니다. |
| 2026-08-17 | in-progress | 캐시가 격리된 엄격한 실행은 live Browser turn 14개를 모두 완료했지만 전용 요청 및 변환 결과 토픽을 각각 6만큼만 전진시켰습니다. Exact transport gate가 아티팩트를 거부하고 seed 기반 질문 집합을 닫힌 상태로 유지했습니다. | [Issue #63](https://github.com/dotnetpower/fdai/issues/63), 중앙 검증된 소스 `40fbd0c41eda506e6976e3090fab3bd9502b98f0`, 실행 `issue63-40fbd0c41e-20260817T084406Z`, live 14개, resumed 0개, transport 6/6 | Turn 8개가 소유하지 않은 물리 stream을 통과했으므로 의미 disposition을 release 근거로 사용하지 않습니다. |
| 2026-08-17 | implemented | 실행 범위 outbox key를 기본 key prefix의 자식에서 형제 prefix로 변경했습니다. 운영 기본 key를 바꾸거나 exact namespace 동등성을 약화하지 않으면서 이전의 넓은 prefix claim을 계속 실행하는 오래된 기본 프로세스에 대해서도 소유권을 닫습니다. | `current change`, focused bridge 검사 62개, Ruff 및 strict mypy 통과 | Seed 기반 질문 집합을 시작하기 전에 요청 및 변환 결과 transport가 exact 14/14인 새로운 엄격한 아티팩트를 보존합니다. |
| 2026-08-17 | implemented | Exact transport를 적용한 첫 전체 집단에서 답변된 기능 불일치 11건이 드러난 뒤 seed 기반 질문 분류를 넓은 작업 범주와 분리하고 의미 frame prompt v9을 적용했습니다. Prompt별로 유효한 plan은 계속 허용하면서 관계 탐색, 인과 근거, 보존 세대 비교 및 근거 속성 선택은 서로 다른 기능 요구 사항을 유지합니다. | `current change`, focused prompt 레지스트리 검사 5개와 assurance oracle 검사 99개 통과 | 중앙 검증을 확보하고 seed 기반 실행을 다시 시작하기 전에 strict 집단을 한 번 실행합니다. |
| 2026-08-17 | implemented | `validate` frame을 `evidence_validation` 출력 계열에 묶고 topology cutoff 순서 검증을 deterministic plan 검증 단계로 이동했습니다. 잘못 분류된 근거 요청은 frame만 다시 시도한 뒤 Core가 principal 범위 ObjectSet을 구성하며, event cutoff가 knowledge cutoff보다 늦은 topology snapshot은 프로바이더 실행 전에 거부됩니다. 비어 있거나 불완전한 보존 history는 계속 타입이 지정된 불완전 근거를 반환하며 합성되지 않습니다. | `current change`, focused 의미 계획 및 query verifier 검사 41개 통과, 작업 범위 Ruff 및 strict mypy 통과 | 중앙 검증을 확보한 뒤 runner가 seed 기반 집단을 시작하기 전에 strict 14/14 답변 및 완전 근거 아티팩트 하나를 보존합니다. |
| 2026-08-17 | implemented | Exact-source strict 근거에서 evidence-completeness 요청 하나가 server-owned evidence plan 대신 범위가 제한된 plan 제안으로 진행된 뒤 semantic frame prompt를 v10으로 올렸습니다. Prompt는 complete-scope 및 evidence-gap 검증에 operation `validate`와 output shape `evidence_validation`을 함께 요구하며 기존 deterministic 양방향 frame guard가 계속 authoritative 경계입니다. | `current change`, focused prompt 레지스트리 회귀 통과 | 중앙 검증을 확보한 뒤 runner가 seeded를 시작하기 전에 strict 14/14 답변 및 완전 근거 아티팩트를 보존합니다. |
| 2026-08-17 | implemented | 다음 strict 실행에서 유일한 unsupported cell이 temporal comparison으로 이동한 뒤 semantic plan prompt를 v11로 올렸습니다. Prompt는 trusted cutoff가 있는 dependency-free `topology_at` source 두 개와 baseline-then-current `topology_diff` output 하나로 구성된 일반 three-node topology-diff DAG를 고정합니다. 질문 route나 프로바이더 데이터는 추가하지 않습니다. | `current change`, focused prompt 레지스트리 회귀 통과 | 중앙 검증을 확보한 뒤 seeded 시작 전에 strict 14/14 근거를 보존합니다. |
| 2026-08-17 | implemented | 타입이 지정된 `validate` 및 `evidence_validation` frame에 남은 principal-scope subject clarification만 해소했습니다. Core는 기존 readable `Resource` descriptor를 bind하고 동일한 secured ObjectSet을 구성합니다. Concrete subject 또는 다른 clarification category는 계속 unresolved 상태입니다. | `current change`, focused positive 및 negative tier 라우팅 회귀 통과 | 중앙 검증을 확보한 뒤 seeded 시작 전에 strict 14/14 근거를 보존합니다. |
| 2026-08-17 | implemented | Evidence frame에 concrete subject가 없을 때 server-owned evidence resolver를 타입이 지정된 `resource_identity` clarification까지 확장하고, `explain_change`를 `causal_evidence` output 계열과 양방향으로 연결했습니다. Concrete evidence subject는 계속 unresolved 상태이며 잘못 분류된 causal frame은 plan 선택 전에 종료되지 않고 범위가 제한된 T1-first cascade를 통해 다시 시도합니다. | `current change`, focused evidence 및 causal tier 라우팅 회귀 통과 | 중앙 검증을 확보한 뒤 seeded 시작 전에 strict 14/14 근거를 보존합니다. |
| 2026-08-18 | implemented | Semantic frame prompt를 v11로 versioning하고 최종 answer-shape audit를 추가했습니다. Cardinality와 grouping은 schema declaration을 대상으로 해도 `aggregation_table`을 유지하며, evidence sufficiency와 coverage는 요청이 resource, property, identity 또는 relationship을 명시해도 타입이 지정된 `validate` 및 `evidence_validation` 쌍을 유지합니다. 질문 literal, keyword router, provider fact 또는 권한은 추가하지 않았습니다. | `current change`, focused prompt 레지스트리 계약 통과 | 중앙 검증을 확보한 뒤 seeded 시작 전에 strict 14/14 근거를 보존합니다. |
| 2026-08-18 | implemented | Semantic plan prompt를 v12로 versioning하고 generic causal scope envelope을 닫았습니다. Principal 범위 causal plan은 predicate, traversal 또는 root id가 없는 unfiltered `Resource` ObjectSet을 사용합니다. 모델이 선택한 scope restriction은 계속 terminal denial이며 더 넓은 access로 재시도할 수 없습니다. | `current change`, focused prompt 레지스트리 계약 및 기존 no-T2 scope-denial 회귀 통과 | 중앙 검증을 확보한 뒤 seeded 시작 전에 strict 14/14 근거를 보존합니다. |
| 2026-08-18 | implemented | Semantic frame prompt를 v12로 versioning하고 evidence-property membership과 evidence sufficiency를 분리했습니다. 일치하는 객체를 나열하거나 식별하는 요청은 비어 있지 않은 predicate가 있는 `property_filtered_resources`를 요구하며, completeness 및 gap 판단은 `validate` 및 `evidence_validation` 쌍을 유지합니다. | `current change`, focused prompt 레지스트리 계약 통과 | 중앙 검증을 확보한 뒤 seeded 집단 전에 strict를 다시 실행합니다. |
| 2026-08-18 | implemented | Semantic frame prompt를 v13으로 versioning하고 evidence-contract subject와 runtime object property를 분리했습니다. Claim, evidence reference, verification coverage 및 gap은 `validate`와 `evidence_validation`을 사용하며, readable evidence-valued property로 선택한 runtime ontology object만 `property_filtered_resources`를 사용합니다. | `current change`, focused prompt 레지스트리 계약 통과 | 중앙 검증을 확보한 뒤 seeded 집단 전에 strict를 다시 실행합니다. |
| 2026-08-18 | implemented | Semantic plan prompt를 v13으로 versioning하고 ObjectSet predicate를 선택된 descriptor의 readable `properties` map에 있는 direct key로 고정했습니다. Predicate input은 projected row path나 natural-language alias를 사용할 수 없으며 downstream `properties.<name>` path는 presentation에만 사용합니다. | `current change`, focused ObjectSet prompt 계약 통과 | 중앙 검증을 확보한 뒤 seeded 집단 전에 strict를 다시 실행합니다. |
| 2026-08-18 | implemented | Semantic frame prompt를 v14로 versioning하고 membership을 정의하는 axis를 보존했습니다. 보존 세대 사이에 추가, 제거 또는 변경된 객체는 list 답변이어도 `temporal_comparison`을 유지하며 현재 evidence state로 선택한 객체는 `property_filtered_resources`를 유지합니다. | `current change`, focused frame prompt 계약 통과 | 중앙 검증을 확보한 뒤 seeded 집단 전에 strict를 다시 실행합니다. |
| 2026-08-18 | implemented | Randomized assurance에서 드러난 두 typed boundary를 위해 deterministic frame invariant와 prompt v15를 추가했습니다. `ontology_manifest`는 canonical declaration-kind subject만 허용하고 `select` resource listing은 비어 있지 않은 measure concept를 조용히 버릴 수 없습니다. 유효하지 않은 T1 frame은 planning 전에 bounded T2 frame cascade로 retry합니다. | `current change`, 전체 semantic planning tier-routing 및 prompt-registry 테스트 통과, Ruff와 strict mypy 통과 | 중앙 검증을 확보한 뒤 seeded 집단 전에 strict를 다시 실행합니다. |
| 2026-08-18 | implemented | 중앙 changed-tests가 제안된 deterministic invariant 두 개를 모두 반증했습니다. 정상적인 Pod telemetry path query는 `Resource` subject 및 비어 있지 않은 measure concept와 함께 resource-list output을 사용합니다. Runtime invariant를 제거하고 declaration inventory, runtime membership 및 명시적 grouping 사이의 일반 answer-shape 구분을 위한 prompt v15만 유지했습니다. | 중앙 검증에 실패한 source `90c592bfcc673e4764e4480be7ffa54c5b66b0b8`, 두 Pod telemetry composition 회귀 테스트와 인접 prompt suite가 현재 로컬 통과 | 수정된 prompt-only v15 slice를 중앙 검증한 뒤 seeded 집단 전에 strict를 다시 실행합니다. |
| 2026-08-18 | implemented | Semantic frame prompt를 v16으로 versioning하고 일반적인 incident 명사와 authoritative incident reference를 분리했습니다. `incident_evidence`에는 하나의 정확한 trusted binding 또는 request의 정확한 identity 두 개가 필요하며 명시된 원인을 일반적으로 지지하거나 반박하는 질문은 `explain_change`와 `causal_evidence`를 유지합니다. | `current change`, focused prompt-registry 계약 통과 | 중앙 검증을 확보한 뒤 seeded 집단 전에 strict를 다시 실행합니다. |
| 2026-08-18 | implemented | Semantic plan prompt를 v14로 versioning하고 generic causal evidence를 위한 최종 closed-shape audit를 추가했습니다. Unfiltered visible Resource scope 하나, supplied cause 및 effect concept를 사용하는 scoped metric window 두 개, evidence-join output 하나로 구성합니다. Specialized incident function, filtered scope, root 및 standalone ObjectSet output은 이 family에서 제외합니다. | `current change`, focused prompt-registry 계약 통과 | 중앙 검증을 확보한 뒤 seeded 집단 전에 strict를 다시 실행합니다. |
| 2026-08-18 | implemented | Semantic frame prompt를 v17로 versioning하고 모호한 surface 두 개를 위한 최종 family audit를 추가했습니다. 변경이 관측된 regression보다 먼저 발생했는지 묻는 질문은 causal evidence를 유지하며 현재 inventory generation의 ontology object는 principal-scoped declaration manifest를 선택합니다. Retained-generation object delta는 temporal comparison을 유지합니다. | `current change`, focused prompt-registry 계약 통과 | 중앙 검증을 확보한 뒤 seeded 집단 전에 strict를 다시 실행합니다. |
| 2026-08-18 | implemented | Semantic frame prompt를 v18로 versioning하고 최종 relationship-scope audit를 추가했습니다. Specialized schema relationship family에는 정확한 ObjectType declaration 한두 개가 필요하며 현재 visible 또는 readable inventory의 connectivity와 containment는 operational topology traversal을 유지합니다. | `current change`, focused prompt-registry 계약 통과 | 중앙 검증을 확보한 뒤 seeded 집단 전에 strict를 다시 실행합니다. |
| 2026-08-18 | implemented | Semantic frame prompt를 v19로 versioning하고 generic visible-resource causal request가 cause concept 하나와 effect concept 하나를 명시하면 완전하도록 했습니다. Frame은 resource identity, incident binding, 더 좁은 subject 또는 provider metric identifier를 operator에게 묻지 않고 causal evidence를 반환해야 하며 grounding은 이후 verifier concern으로 유지합니다. | `current change`, focused prompt-registry 계약 통과 | 중앙 검증을 확보한 뒤 seeded 집단 전에 strict를 다시 실행합니다. |
| 2026-08-18 | implemented | Semantic frame prompt를 v20으로 versioning하고 요청된 runtime relation verb가 ontology noun보다 우선하도록 했습니다. 다른 object에 depend, route, connect, attach 또는 contain되는 visible resource는 target을 ontology object라고 부르더라도 topology traversal을 유지하며 declaration manifest는 runtime membership에 답하지 않습니다. | `current change`, focused prompt-registry 계약 통과 | 중앙 검증을 확보한 뒤 seeded 집단 전에 strict를 다시 실행합니다. |
| 2026-08-18 | validated | 중앙 검증된 source `a38922762ed805794b11bb9c6aaef43916f6f6c4`에서 통제된 strict-to-seeded ontology assurance를 완료했습니다. Strict는 14/14, seeded는 exact transport, evidence-complete answer 85개, 통제된 action draft 9개, clarification 6개, capability mismatch 0건, unsupported operational claim 0건 및 unauthorized execution 0건을 유지하며 100/100을 통과했습니다. | 실행 `issue63-a38922762e-20260818T034940Z`, repository-safe 기준선 [`ontology-query-randomized-assurance-2026-08-18.json`](../../baselines/ontology-query-randomized-assurance-2026-08-18.json) | 원시 local artifact를 보존하고 최신 integration source에서 baseline commit을 검증합니다. |
| 2026-08-18 | implemented | 검증된 행 표를 사람이 읽을 수 있게 유지했습니다. 표가 온톨로지 필드를 모두 투영하는 바람에 열린 형태의 속성 묶음이 한 셀에 수백 자 분량의 직렬화된 JSON으로 표시되었고, 기술 세부 궤적이 이미 담고 있는 기계 출력을 답변이 반복했습니다. 이제 표는 스칼라 필드만 투영하고 중첩 묶음에서 지정된 스칼라 leaf를 끌어올리며, 정확한 원본 행은 그대로 유지됩니다. | `current change`, [Issue #180](https://github.com/dotnetpower/fdai/issues/180), focused Operator 검사 392개 통과(중첩 묶음 회귀 1건 신규), 작업 범위 Ruff 및 strict mypy 통과, 인증된 실제 turn이 JSON 덩어리 대신 id, object type, name, type 열로 표시 | 읽기 쉬운 답변 표에 대한 통제된 request-to-Console 및 이중 언어 무작위 근거를 보존합니다. |
| 2026-08-18 | implemented | 각 리소스 하위 타입이 선언한 질의 용어를 `Resource.type` 값 도메인에 연결했습니다. 도메인이 범주 그룹과 명시적 질의 그룹만 투영해 하나의 하위 타입을 지목한 질문이 연결할 선언 값을 갖지 못했고, 피연산자를 지어낼 수 없는 플래너가 존재 술어로 후퇴해 ObjectType 전체를 선택했습니다. 이제 plan shape 로그가 선택된 ObjectType과 필터 대상 속성 및 연산자를 기록하며 술어 피연산자는 기록하지 않습니다. | `current change`, [Issue #183](https://github.com/dotnetpower/fdai/issues/183), focused composition, conversation, ontology-platform, rule-catalog 검사 2222개 통과, 작업 범위 Ruff 및 strict mypy 통과, 실제 turn이 504행을 반환하던 `object_set[Resource;type exists]`에서 42개 리소스 그룹을 반환하는 `object_set[Resource;type equals]`로 전환 | 좁혀진 속성 필터에 대한 통제된 request-to-Console 및 이중 언어 무작위 근거를 보존합니다. |
| 2026-08-18 | implemented | 검증된 목록 답변을 한눈에 읽을 수 있게 했습니다. 완전한 범주형 결과는 제한된 막대 분포를 그리고, 잘린 결과는 검증된 전체 중 몇 건을 표시했고 나머지가 어디에 있는지 밝히며, 이름 있는 읽기 쉬운 필드가 불투명한 식별자보다 앞에 오고, 항목이 하나인 요약은 빈 격자 칸을 남기지 않고 행을 채웁니다. 불완전하거나 상한에 걸린 결과는 차트를 그리지 않아 부분 집계가 전체처럼 읽히지 않습니다. | `current change`, [Issue #184](https://github.com/dotnetpower/fdai/issues/184), focused Operator 검사 394개 통과(차트 회귀 2건 신규), Console typecheck 및 작업 범위 Ruff와 strict mypy 통과, 인증된 실제 turn이 검증된 42행 중 20행을 상한과 함께 표시 | 차트와 행 상한 안내에 대한 통제된 request-to-Console 및 이중 언어 무작위 근거를 보존합니다. |
| 2026-08-18 | implemented | 의미 turn이 관측한 단계를 스트림에서 주소 지정 가능한 step으로 만들었습니다. Operator가 진행 이벤트만 발행해 Console의 관측 과정 타임라인이 그릴 대상이 없었고, 답변이 도착할 때까지 한 줄이 고정돼 있었습니다. 이제 관측된 각 단계가 제한된 step을 함께 발행하며, 대기 step은 종단 projection이 생길 때까지 running으로 보고되고 disposition과 무관하게 종단 이벤트 전에 정리됩니다. | `current change`, [Issue #187](https://github.com/dotnetpower/fdai/issues/187), focused Operator 검사 394개 통과, Ruff 및 strict mypy 통과, 실제 turn이 running 대기 step과 완료 step 5개로 표시 | Core는 종단 projection 하나만 발행하므로 계획 하위 단계는 스트림이 관측하지 못하며 보고하지 않습니다. |
| 2026-08-18 | implemented | 검증된 쿼리를 해당 step에 보고했습니다. 쿼리와 행 수는 이미 종단 projection으로 전달되고 있었지만 근거 step에 연결하는 곳이 없어 Console의 명령 블록에 출처가 없었습니다. 이제 근거 step이 투영된 intent graph와 보고된 출력 행 수로 구성한 제한된 읽기 전용 실행 기록을 담습니다. | `current change`, [Issue #188](https://github.com/dotnetpower/fdai/issues/188), focused Operator 검사 396개 통과, Ruff 및 strict mypy 통과, 실제 turn이 ObjectSet 정의를 코드로 표시 | goal이 여러 개인 plan은 명령을 보고하지 않으므로 복합 쿼리는 기술 세부에만 남습니다. |
| 2026-08-19 | implemented | `query.manifest` 집계를 frame이 정확히 같은 canonical declaration kind를 요청할 때로 제한했습니다. 인시던트 및 감사 로그 개수 질문은 더 이상 declaration 행으로 대체되지 않으며 T1/T2의 제한된 제안이 결정론적 검증에 실패하면 unsupported가 됩니다. 일치하는 declaration 개수는 계속 유효합니다. | `current change`, [Issue #174](https://github.com/dotnetpower/fdai/issues/174), 재현된 운영 개수 질문 3개와 declaration-kind 불일치 재시도를 포함한 전체 semantic planning tier-routing suite 40개 사례 통과 | 이 수정을 새로운 운영 근거로 취급하기 전에 통제된 대화 보증을 다시 실행합니다. |
| 2026-08-20 | 구현됨 | 모델이 `Resource.name exists`만 제안한 경우에도 모든 명시적 필터를 보존하도록 했습니다. Core는 frame이 보존한 정확한 이름 조각과 카탈로그가 선언한 리소스 타입 값 그룹을 결합해, 전체 Resource 집합을 실행하는 대신 이름 조각과 리소스 타입 조건식으로 결과를 좁힙니다. 운영자 발화에 없는 subject는 피연산자로 승격하지 않습니다. | `current change`, `semantic_planning_value_filters.py`, `test_semantic_planning.py`, 영어와 한국어를 포함한 focused 의미 계획 파일 27개 사례 통과 | Core를 재시작하고 좁혀진 검증 쿼리, 읽기 쉬운 표, 범위가 제한된 trace 및 가로 overflow가 없음을 보여 주는 인증된 Console 결과를 보존합니다. |
| 2026-08-27 | 구현됨 | 서버가 소유하는 contextual Resource FunctionType과 정확한 화면/리소스 그룹 바인딩을 추가했습니다. Console은 선택된 resource id 집합을 opaque server-issued token으로 게시하고 Operator는 전용 redaction allowlist를 통해 전달한 뒤 인증된 principal, 일반 소문자 role 범위, purpose, 정확한 release, source generation, completeness 및 id에 결속된 token을 조회합니다. Core의 contextual FunctionType 자체도 capability를 요구하고, 연결되지 않은 specialized plan을 거부하며, object-only read 전에 명시적 조건과 교집합합니다. 클라이언트 위조/recompute id나 재시작 후 사라진 token은 거부하고 불완전한 결과는 전체 Resource 집합으로 대체하지 않습니다. | `current change`, contextual FunctionType, semantic planning, service-contract, Operator envelope 및 Console context focused 검사 통과; 인증된 근거는 아직 열려 있습니다. | 완전한 selection token이 발급된 뒤 인증된 화면/리소스 그룹 및 인시던트 Console receipt를 보존합니다. |
| 2026-08-27 | 구현됨 | 이제 context 선택에는 인증된 principal, principal 범위, ontology release, source generation, complete 플래그 및 정확한 id를 결속한 서버 발급 digest가 필요합니다. Contextual plan은 모든 명시적 발화 필터와 id를 교집합하고, 불완전한 FunctionType 결과는 semantic turn을 hold하며, 잘린 Console snapshot은 선택 신원을 게시하지 않습니다. | `current change`, 이중 언어 adversarial Core/Operator/Console 검사, typecheck, Ruff 및 pre-commit 통과 | 서버가 complete selection identity를 발급한 뒤 인증된 receipt를 보존합니다. |
| 2026-09-01 | 구현됨 | `QueryNodeResult`에서 `GoalTaskReceipt`와 `intent_graph_evidence`를 거쳐 Operator `done` payload까지 이어지는 종단 근거 계보 공백을 닫았습니다. 각 투영 claim은 완료된 goal의 evidence reference를 명시하며, 정확히 일치하는 읽기 receipt가 있을 때만 trajectory 또는 execution detail을 생성합니다. 완전한 0행과 불완전한 0행을 구분하고, 프로바이더 실패는 프로바이더 원문 없이 범위가 제한된 사유와 관측 시각을 보존합니다. | `current change`, 집중 Core 및 Operator 의미 suite 207개, Conversation Assurance 계약 검사 78개, Ruff 및 formatting 통과 | 별도로 승인된 통제 캠페인을 실행하기 전에는 구현 검사를 실제 Conversation Assurance 근거로 취급하지 않습니다. |
### 남은 작업

- [ ] 보안 쿼리 승인 프로바이더를 신뢰할 수 있는 검증기 레지스트리에 연결하고 긍정적인 의사 결정 핵심 Function 결과를 복원하기 전에 서비스 간 쿼리 경로에서 인증된 `DecisionCriticalEvidenceReceipt`와 독립 묶음 하나를 보존합니다.
- [ ] 완전한 Kubernetes 세대에서 인증된 S12 및 S1 정확한 대상 근거를 보존합니다. S12에는 Deployment rollout과 새 기준 시점 복구 증적이 필요합니다. S1에는 현재 Pod 상태가 원인 또는 과거 복구 주장이 되지 않도록 이벤트, 변경, replica, 교체 UID 근거도 필요합니다.
- [ ] 별도의 정확한 대상 Container Apps 후속 증적 7/7을 완료합니다. 검증된
  `MemoryPercentage` 집계와 인증되고 범위가 제한된 차트는 보존했습니다. 일반 ObjectSet 대체 없이
  타입이 지정된 인그레스 변환 결과, 범위가 제한된 7일 활동, 결정론적 인과 조사 완성을
  추가로 입증해야 합니다.
- [ ] Operator 게시, Core 처리, exact Operator 변환 결과 읽기 및 인증된 Console 렌더링을 포함하는 통제된 요청-Console 증적 하나를 기록합니다. 이중 언어 무작위 보증 집단을 다시 실행하고 통과한 두 근거 기록을 연결합니다.
- [x] `query.resource_event_history`를 정확한 범위, 범위가 제한된 조회 구간, 명시적 제한 및 실행 권한 없음과 함께 독립적으로 라우팅한 Azure Resource Health 및 Kubernetes Event 출처에 연결합니다.
- [x] 전용 `query.resource_health_inventory`, `query.resource_metric_inventory`, 인벤토리/상태 커버리지 및 맥락 Resource FunctionType을 바인딩합니다. 각 권위 있는 근거 출처와 검증기 스키마가 준비될 때까지 타입이 지정된 사용 불가 결과를 유지합니다.
- [x] 인증된 선택 화면 또는 리소스 그룹 신원 하나를 Console, Operator, Core 계약 전체에 전달하고, 맥락 컬렉션 조회가 principal 가시 Resource 집합으로 넓어질 수 없음을 입증합니다.
- [x] Canonical `Incident` 인스턴스를 현재 온톨로지 저장소에 projection해 bounded `ObjectSet`으로 선택할 수 있게 했습니다.
- [x] 선택적인 인용 기반 기록 원인, 영향 근거, 인용 및 명시적 공백이 있는 correlation-scoped 감사 근거 위에 읽기 전용 `query.incident_evidence` FunctionType을 등록했습니다.
- [x] 인시던트 답변을 프로파일, 상관 근거 및 명시적 공백으로 제한하고 다음 안전 단계를 후보 `SemanticOperation.ACTION_DRAFT`로만 표현합니다. 인증된 Console 증적도 보존합니다.
- [x] Console에서 Operator를 거쳐 Core까지 바인딩된 대화 맥락을 추가적인 타입 요청 상태로 전달합니다.
- [x] 영속 의미 인덱스, 과거 토폴로지 읽기 경로, metric-series 및 evidence-join 프로바이더를 타입이 지정된 사용 불가 동작과 focused 검사와 함께 조립합니다.

## 설계 개요

![설계 개요. 주요 단계는 Operator turn, SemanticProblemFrame candidate, Active ontology release, Principal-scoped query manifest, Deterministic verifier, Verified OntologyQueryPlan, Bounded task DAG, Authoritative evidence and receipts, Verified answer or explicit limitation입니다.](../../diagrams/generated/fdai-roadmap-interfaces-ontology-query-coverage-implementation-plan-01.ko.svg)

모델은 언어를 분해하고 meaning 표현을 제안합니다. 검증기는 스키마 신원,
관계 조립, 시간 한계, 범위, 용도 및 기능 검사를 소유합니다. 구체적인 객체는
계획 검증 이후 권위 있는 읽기로만 선택합니다.

## 검증된 기준선 및 공백

| 영역 | 검증된 현재 구현 | 목표를 차단하는 공백 |
|------|------------------|---------------------|
| 대화 라우팅 | 기본값 호환성 조정기는 exact 정본 명령만 수락합니다. 구성된 의미 토픽은 ordinary 언어를 Operator 발신함, Core Azure 플래너/검증된 DAG, 영속 변환 결과 및 Console `done` 프레임으로 전달합니다. | 실제 운영 서비스 간 증적과 complete-manifest 한계를 넘는 매니페스트를 위한 서술자 인덱스가 남아 있습니다. `legacy`는 명시적 temporary 호환성 모드로만 존재합니다. |
| 서비스 간 의미 wire | 버전 1.2 요청/변환 결과 묶음은 실행 권한 없이 범위가 제한된 의미 입력과 근거에 묶인 최종 출력을 전달합니다. Operator와 Core는 Terraform-provisioned 요청/변환 결과 토픽, 영속 재생 및 범위가 제한된 재시도를 사용합니다. | 운영 준비 상태는 evidence-gated로 유지되며 의미 기록은 N-1로 downgrade하지 않습니다. |
| Console 의도 그래프 | Core는 검증된 계획에서 범위가 제한된 그래프/증적 근거를 만들고 Operator는 Console-compatible 최종 프레임으로 이를 스트림합니다. | 새 인증된 randomized 실행이 실제 운영 근거에 대해 visible 브라우저 경로를 검증해야 합니다. |
| 의미 interpretation | Azure OpenAI 어댑터는 bearer-token authentication과 resolved-candidate 대체 경로를 통해 `SemanticProblemFrame` 및 타입이 지정된 DAG를 strict 범위가 제한된 JSON 객체 두 개로 제안합니다. Core는 신원을 부여하고 Pydantic 스키마와 principal 매니페스트를 검증하며 exact 요청 역할로 실행하고 Operator는 결정론적 근거에 묶인 답변을 스트림합니다. | 서술자 한계를 넘으면 complete-manifest 선택자가 보류합니다. |
| 객체 조회 | `OntologyQueryPlan`은 이제 변경할 수 없는 내용 기반 주소를 가진 표 위에서 secured ObjectSet, 집합 algebra, 정렬, 변환 결과, grouped 집계 및 타입이 지정된 읽기 전용 함수를 구성합니다. | Temporal 스냅샷, 메트릭 series 및 근거 결합에는 등록된 확장 핸들러가 필요합니다. |
| 조회 매니페스트 | principal 범위로 한정된 내용 기반 주소를 가진 빌더가 ObjectType/filtered 속성, LinkType 양쪽 엔드포인트 side, Interface, 읽기 전용 함수 및 초안 전용 ActionType을 변환 결과합니다. | 운영 서술기는 아직 매니페스트를 사용하지 않으며 완전한 운영자/근거 가용성 서술자가 남아 있습니다. |
| Interface | 운영 카탈로그 로딩은 `Identifiable`, 출처 이력 및 모든 현재 ObjectType의 명시적 연결을 검증합니다. 런타임 조립은 이를 compile하고 exact release에 pin합니다. | 추가 기능 Interface와 운영 ObjectSet 조회 연결은 남아 있습니다. |
| 관계 | 모든 directed LinkType은 엔드포인트, cardinality, causal, transitive 및 temporal 메타데이터와 함께 결정론적 `<name>.outgoing`/`<name>.incoming` 머신 조회 id를 변환 결과합니다. | 이 side를 사용하는 범용 계획 검증기와 플래너 연결은 남아 있습니다. |
| 의미 세대 | 구체적인 service-owned atomic in-memory 인덱스와 off-path full/incremental 온톨로지 세대 발행기가 선언 및 조건을 충족한 deployment-local 객체를 독립적인 검증과 함께 다룹니다. | 영속 PostgreSQL 어댑터, scheduled 발행기 프로세스 및 운영 의미 서술자 선택자는 남아 있습니다. |
| 현재 토폴로지 | Azure 변환 결과는 containment, attachment, dependency, peering 및 exact-resource routing 후보에 검토된 관계 mapping을 사용합니다. 완전한 세대 verifier는 두 엔드포인트, 독립 verifier 신원, 변경할 수 없는 receipt 및 정본 state-fact 메타데이터를 갖춘 링크만 허용합니다. Mapping은 받아들일 대상 유형을 선언하므로, 선언되지 않은 관리형 서비스 연결 대상은 프로바이더가 기록했더라도 링크를 생성하지 않습니다. | 워크로드 및 서비스 의존성 커버리지와 운영 network-path 발급자가 아직 불완전합니다. |
| Historical 토폴로지 | Bitemporal 추가 전용 개정 번호 계약, 이행, retained 세대 참조, tombstone, `graph_at`, `topology_diff`, late-evidence 재생 및 타입이 지정된 조회 핸들러가 있습니다. | PostgreSQL 읽기 담당/쓰기 담당 조립과 inventory-promotion 발행은 남아 있습니다. |
| 메트릭 및 causality | Exact metric-concept 레지스트리, 완전한/불완전한 구간, aligned 비교 및 topology-aware temporal support/refutation 핸들러가 있습니다. | 운영 프로바이더 연결과 검토된 메트릭 카탈로그 항목은 남아 있습니다. |

## 소유권 및 서비스 경계

| Responsibility | Accountable 소유자 | 런타임 placement |
|----------------|-------------------|-------------------|
| 자연어 분해 및 명확화 | Bragi | Core 에이전트 런타임입니다. Operator 서비스는 인증된 중계 및 변환 결과 호스트입니다. |
| 온톨로지 및 query-manifest 수명 주기 | Mimir | Core mechanical 빌더 및 카탈로그 수명 주기입니다. |
| 현재/historical 맥락 구체화 | Muninn | Core 변환 결과 워커 및 owned 영속성 어댑터입니다. |
| 근거 관측 및 완전성 | Heimdall | Core 읽기 전용 프로바이더 연결 및 타입이 지정된 관측입니다. |
| Correlated 감사 및 재생 근거 | Saga | 추가 전용 감사 경로입니다. |
| 외부 조회 authentication, 범위, 스트리밍 및 display 변환 결과 | Operator 서비스 | Versioned shared 계약만 사용하는 독립 서비스입니다. |
| 조회 및 증적 wire 계약 | Shared service-contract SDK | 서비스 구현 또는 프로바이더 접근을 포함하지 않습니다. |

Authority-bearing 전이는 event-bus 메시지로 유지합니다. 읽기 전용 조회 실행은
purpose-bound 변경할 수 없는 변환 결과를 사용할 수 있지만 한 서비스가 다른 서비스 구현을 가져오기하지
않습니다. 새 에이전트를 추가하지 않습니다.

## 목표 계약

### 의미 problem 프레임

`SemanticProblemFrame`은 언어 interpretation과 객체 수집을 분리합니다. 다음을 포함합니다.

- 선택, compare, explain 변경, validate 또는 초안 액션 같은 연산 등급
- 발명된 런타임 신원이 없는 대상 제약
- measure 및 단위 개념
- trusted 시간에 고정된 temporal/비교 구간
- requested 답변 형태 및 근거 요구사항
- 해결되지 않은 개념 및 competing interpretation

프로바이더 조회, raw SQL/KQL, 객체 점유 또는 실행 권한은 포함하지 않습니다.

### 온톨로지 조회 계획

검증된 `OntologyQueryPlan`은 다음 연산으로 구성된 closed DAG입니다.

- 객체/인터페이스 선택 및 exact 맥락 기준점
- 타입이 지정된 속성 조건식/변환 결과
- 검토된 LinkType-side 탐색
- 집합 union, intersection 및 subtraction
- 정렬, 그룹화 및 범위가 제한된 집계
- 등록된 읽기 전용 조회, derive 및 validate 함수
- temporal 스냅샷, 차이, metric-window 및 evidence-join 노드

모든 노드는 활성 release, 용도, 역할, 범위, 한도, 의존성 및 예상 증적 형태를
고정합니다. 계획은 executable 프로바이더 텍스트 또는 변경 핸들러를 포함할 수 없습니다.

### 복합 읽기 전용 인스턴스 경로

현재 관계 답변은 검증된 단일 복합 노드를 통해서만 온톨로지 선언과 런타임 인스턴스를
결합할 수 있습니다. 이 노드는 정확한 release, 인증된 principal 범위 다이제스트, 단일
용도, 현재 그래프 기준 시점, 모든 보안 그래프 증적, 경로 정의 및 최종 결과 다이제스트를
결합합니다. 권한은 `server_ontology_instance_path`이고 `execution_authority=false`로
고정됩니다.

복합 노드는 `server_ontology_manifest`의 선언 근거와 `server_inventory_graph`의 인스턴스
근거만 받습니다. 여러 권한을 서로 바꿔 쓸 수 있다고 간주하지 않고 입력을 검증합니다.
전체 답변 검증은 각 의존성의 권한 검사가 통과한 뒤 최종 출력 노드의 권한을 확인합니다.
관련 없는 혼합 권한, 검증되지 않은 파생, 누락된 principal 범위, release 불일치, 세대
불일치, 가려진 경로 신원, 불완전한 근거 및 경로 한도 초과가 있으면 답변을 보류합니다.

인스턴스 경로는 각 루트에서 대상으로 이어지는 실제 계보를 보존합니다. 서로 독립적으로
선택한 끝점의 곱집합을 반환하지 않습니다. 빈 루트 또는 빈 단계로는 현재 담당 관계를
추적하라는 요청에 답할 수 없으므로 신원을 주장하지 않고 노드를 보류합니다. 스키마의
LinkType 근거만으로는 가능한 관계만 설명할 수 있으며 현재 서비스, 워크로드, 리소스 또는
담당 Agent 인스턴스를 입증할 수 없습니다.

## 작업 패키지

| ID | 작업 패키지 | 의존성 | Exit 근거 |
|----|--------------|------------|---------------|
| OQ-00 | 현재 구현 기준선을 고정하고 상태 점유를 수정하며 모든 정규식/토큰 경로를 인벤토리합니다. Exact, 모호한, 지원하지 않는, temporal, causal 및 액션 질문의 bilingual competency 집단을 추가합니다. | 없음 | 기계가 읽는 기준선과 재생 고정본이 모든 호환성 경로를 식별합니다. |
| OQ-01 | `SemanticProblemFrame`, `OntologyQueryPlan`, 의도 목표, 명확화, 작업 증적 및 structural 커버리지 증적의 versioned shared 계약을 추가합니다. | OQ-00 | N/N-1 codec 테스트가 알 수 없음 권한, unbounded 계획, cycle 및 stale 참조를 차단합니다. |
| OQ-02 | 온톨로지 카탈로그 데이터에 LinkType 조회 side와 검토된 Interface 선언을 추가하고 exact release에서 완전한 principal 범위로 한정된 매니페스트를 생성합니다. | OQ-01 | 읽을 수 있는 모든 ObjectType, Property, LinkType side, Interface, FunctionType 및 초안 전용 ActionType에 서술자 또는 사용 불가 사유가 있습니다. |
| OQ-03 | ObjectSet, 집합 연산, 정렬, 집계, 변환 결과 및 타입이 지정된 함수 노드 위에 범용 계획 검증기/실행기를 구현합니다. | OQ-01, OQ-02 | Property 테스트가 한계, 타입 안전성, 용도 좁히기, ACL 종결, 잘림, 취소 및 고정된 증적을 입증합니다. |
| OQ-04 | String-command `ReadPlanNarrator` 계획 수립을 Bragi-owned 스키마로 제한한 decomposition, 매니페스트 검색/describe, 결정론적 검증 및 영속 명확화로 교체합니다. 호환성 경로 옆에서 shadow로 실행합니다. | OQ-02, OQ-03 | English/Korean 턴이 replay-stable 검증된 계획 또는 범위가 제한된 명확화 하나를 만들며 검증되지 않은 읽기를 호출하지 않습니다. |
| OQ-05 | 범위가 제한된 동시성, 취소, 차단된 descendant, 충돌 detection, 근거 원장 하나 및 점유 검증을 갖춘 서버 측 의도 그래프와 dependency-wave 작업 실행기를 구현합니다. | OQ-03, OQ-04 | Operator 서비스가 Console이 이미 검증하는 같은 versioned 그래프/증적을 스트림하며 부분 가지가 완전한 답변이 되지 않습니다. |
| OQ-06 | Owning 서비스에 구체적인 semantic-index 어댑터와 off-path 세대 발행기를 복원한 뒤 세대 문서를 Rule에서 선언 및 조건을 충족한 deployment-local 객체 변환 결과로 확장합니다. | OQ-02 | Full initial 세대, digest-reusing incremental 세대, 독립적인 검증, atomic activation, stale 성능 저하 및 롤백 테스트가 통과합니다. |
| OQ-07 | VNet 피어링, 경로, 비공개 엔드포인트, 네트워크 구성원, 워크로드 placement 및 서비스 의존성의 현재 Azure 토폴로지 변환 결과를 완성하고 network-path 증적 발급자를 연결합니다. | OQ-02, OQ-03 | VM-to-service 및 service-to-data-store 경로 고정본이 direction, reciprocal 피어링 근거, 완전성 및 알 수 없음 absence를 보존합니다. |
| OQ-08 | 추가 전용 토폴로지 관계 개정 번호와 retained provider-generation 참조를 추가하고 범위가 제한된 `graph_at`/`topology_diff` 함수를 구현합니다. 현재 그래프는 fast current-state 변환 결과로 유지합니다. | OQ-03, OQ-07 | Before/after 피어링 고정본이 결정을 다시 쓰지 않고 exact retained 그래프, tombstone, late 근거 및 불완전한 이력을 재구성합니다. |
| OQ-09 | 검토된 metric-semantic 레지스트리와 메트릭 series, 변경 지점, aligned 구간, cross-resource temporal 상관관계 및 causal support/refutation 함수를 추가합니다. | OQ-03, OQ-05, OQ-08 | Request-growth 및 storage-write-loss 시나리오가 zero와 누락된 데이터를 구분하고 시간 순서를 원인으로 단정하지 않으며 competing explanation을 인용합니다. |
| OQ-10 | 새 경로를 모든 호환성 경로와 shadow 재생하고 집단으로 승격한 뒤 ordinary 언어에서 정규식, 키워드 서술기, phrase-based 답변 의도 및 canonical-string 읽기 계획 수립을 제거합니다. 명시적 exact-command 표면은 별도로 유지합니다. | OQ-05, OQ-06, OQ-09 | 새 경로가 집단 quality/지연 시간을 유지하거나 개선하고 이전 방식 ordinary-language 라우팅 share는 0이며 exact technical 명령은 결정론적하게 남습니다. |
| OQ-11 | 모든 온톨로지 release/기능 변경에 연속 구조 및 인식 상태 커버리지 게이트를 적용합니다. | OQ-10 | 구조 커버리지, 유한 질문 우주 집계, 최종 인식 상태 처리 결과는 100%이고, 지원되지 않거나 근거 없는 주장, 숨겨진 범위 누출, 안전하지 않은 변이 생존, 언어 차이, 권한 없는 실행은 0이며 답변 커버리지는 집단별로 보고합니다. |

## 병렬 레인 및 병합 지점

- **레인 A - 계약 및 매니페스트:** OQ-01 -> OQ-02입니다.
- **레인 B - 조회 kernel:** OQ-01 계약 freeze 이후 OQ-03을 시작하고 release 전에 OQ-02와 결합합니다.
- **레인 C - 의미 변환 결과:** OQ-02의 서술자 신원이 고정된해지면 OQ-06을 시작합니다.
- **레인 D - operational 근거:** OQ-03 이후 OQ-04/OQ-05와 병렬로 OQ-07 -> OQ-08 -> OQ-09를 진행합니다.
- **레인 E - 대화 전환:** OQ-04 -> OQ-05 -> OQ-10이며 전환에서 OQ-06/OQ-09와 결합합니다.

각 레인은 focused 테스트만 실행합니다. OQ-10은 완전한 종단 간 행동을 비교하는 첫 통합
지점이고 OQ-11은 release 게이트입니다.

## Competency 시나리오

### 지난주 이후 요청 양 증가

예상 계획은 요청을 `explain_change`, request-volume measure, 서비스 대상 제약,
equal 기준선/현재 구간 및 causal-evidence 요구사항으로 분해합니다. 이어서 메트릭 개념을
해석하고 영향받은 서비스를 찾으며 워크로드/pod로 탐색합니다. 변경 지점 주변 변경을
조회하고 완전한 구간을 비교해 supported/refuted/해결되지 않은 가설을 순위합니다. "요청" 또는
calendar 경계를 맥락으로 해석할 수 없으면 명확화로 유지합니다.

### 네트워크 변경 이후 저장소 쓰기 중단

예상 계획은 저장소 객체와 write-success series를 기준점으로 사용하고 retained pre-change 그래프에서
업스트림 워크로드/VM 의존성을 찾습니다. 변경 전후 네트워크 경로를 비교하고 피어링 개정 번호 및
write-attempt 근거를 조회하며 DNS, 경로, firewall, 자격 증명 및 애플리케이션 대안을 테스트합니다.
현재 간선이 없다는 사실만으로 old 경로가 없었다거나 피어링 변경이 symptom 원인이라고 입증할 수
없습니다.

## 이행, 롤아웃 및 롤백

- **가산 계약 우선:** 새 필드/표는 현재 읽기 경로를 바꾸지 않고 landing합니다.
- **Shadow 비교:** 새 계획은 호환성 라우팅 옆에서 읽기 전용으로 실행되며 집단 게이트 전에는
  visible 답변을 바꾸지 않습니다.
- **Atomic 세대:** 의미 세대는 포인터 activation 전에 단계/validate하며 롤백은 retained
  compatible 세대를 다시 activate합니다.
- **Temporal 저장소 분리:** Historical 관계 개정 번호는 현재 인스턴스 저장소를 암묵적
  latest-wins bitemporal 권한으로 만들지 않습니다.
- **기능 전환:** 가용성, 활성화된 상태 및 권한은 독립적으로 유지합니다. 의미
  계획 수립을 끄면 키워드 guessing이 아니라 exact 명령과 타입이 지정된 사용 불가 결과로 돌아갑니다.
- **이전 방식 제거는 마지막:** 정규식/토큰 경로는 재생 근거와 고정된 롤백 release 이후에만
  제거합니다. 다시 활성화하는 것을 장기 롤백 방식으로 사용하지 않습니다.

## 검증 및 measure

| Measure | release expectation |
|---------|---------------------|
| Structural 스키마 커버리지 | 읽을 수 있는 활성 선언 100%가 표현되거나 타입이 지정된 사용 불가입니다. |
| 질문 처리 결과 | 수락한 턴 100%가 답변, 명확화, 보류, 지원하지 않는 또는 초안으로 끝납니다. |
| 유한 질문 우주 처리 결과 | 생성된 사례 100%가 형식이 지정된 인식 상태 또는 검토된 제외로 끝납니다. |
| 해석과 주장 증명 | 취소되지 않은 턴의 원문 범위와 의미 원자 커버리지가 100%이고 모든 답변이 주장 증명을 가집니다. |
| 빈 결과와 부정 증명 | 검증된 모든 빈 결과 또는 부정 결과가 닫힌 모집단 증명을 가집니다. |
| 지원하지 않는 operational 점유 | 정확히 0건입니다. |
| 근거 없는 주장, 해결되지 않은 충돌, 숨겨진 범위 누출, 안전하지 않은 변이 생존, 언어 차이 | 정확히 0건입니다. |
| 대화에서 승인되지 않은 실행 | 정확히 0건입니다. |
| Exact 신원 및 stale-revision 오류 | 정확히 0건입니다. |
| 답변 커버리지 | 질문, 언어, 도메인, 프로바이더 및 근거 집단별로 별도 측정합니다. |
| 명확화 quality | 실질적인 competing interpretation이 남은 경우에만 정확히 질문합니다. |
| Full/incremental 세대 동등성 | Ordered 문서 다이제스트와 수집 집단 결과가 동일합니다. |
| Historical 재생 | 같은 기준 시점이 같은 retained 그래프 및 근거 증적을 해석합니다. |

## 20-round 강화 기록

처음 landing한 세 구획을 계약 다이제스트, 한계, DAG, 동시성, 권한, 직렬화, 오류
처리, 취소, 민감정보 제거, 재생 시간, 매니페스트 accounting, stale release, ObjectSet,
증적, performance, 서비스 경계, Operator 변환 결과, 서술기 권한, 성능 저하 및
docs-code 동등성의 독립된 20개 관점으로 검토했습니다.

검증된 Medium 이상 발견 사항은 다음과 같이 해결했습니다.

- principal 범위로 한정된 매니페스트가 호출자 역할 또는 용도 밖의 속성을 제거합니다.
- Exact release에 없는 선언은 조용히 무시하지 않고 차단합니다.
- 실행이 온톨로지 release와 query-manifest 다이제스트를 모두 다시 검사합니다.
- 매니페스트 hashing은 작은 per-record JSON 상한 대신 명시적인 8 MiB 상한을 사용합니다.
- 취소를 핸들러 실행 전과 실행 중, semaphore wait 동안에도 관측합니다.
- 노드 기한이 queueing 및 핸들러 실행 전체를 포함합니다.
- 권한 확인 denial, 사용 불가 핸들러, 잘못된 핸들러 결과, 시간 초과, 취소 및 unexpected
  프로바이더 실패가 프로바이더 상세 없는 고정된 타입이 지정된 증적을 만듭니다.
- Focused 테스트가 동시 wave, 차단된 descendant, stale 권한, 취소 race, 합계 기한,
  속성 filtering, 선언 mismatch 및 다이제스트 stability를 검증합니다.

핸들러 내부 동시 확산, 계약 검증 이후 불가능한 DAG cycle, timezone-naive 증적 수락 및
candidate-limit 잘림 발견 사항은 기각했습니다. 실행기 경계 밖이거나 기존 계약이 이미
실패 시 차단하기 때문입니다. Landing한 계약, 매니페스트 및 실행기 구획에는 재현 가능한 Medium 이상
발견 사항이 남아 있지 않습니다.

잔여 Low 관측은 최종 증적 빌더 사이의 코드 duplication, 여러 번 수행되는 범위가 제한된
그래프 변환 결과 통과 및 developer-only 어댑터의 더 명확한 진단입니다. 추가 의미 Interface,
운영 플래너 연결, 의미 세대, 토폴로지 이력 및 temporal 결합은 숨겨진 강화
defect가 아니라 계획된 기능으로 남아 있습니다.

OQ-04/OQ-05 기반에는 권한, 모델 trust, 다이제스트 연결, structural 커버리지, 역할/용도,
서술자 변경, 입력 한계, 프롬프트 주입, 명확화, 액션 초안, 검증기 bypass,
그래프/증적 대응, 취소, Console 동등성, 재생, 민감정보 제거, 호환성 라우팅, 서비스 경계,
에이전트 소유권, 동시성, 테스트 및 docs를 다루는 추가 25-lens adversarial 검토를 수행했습니다.
재현 가능한 Medium 발견 사항 하나를 수정했습니다. 런타임 메타데이터가 누락된 release 선언은 더 이상
structural 커버리지에서 사라질 수 없으며 매니페스트 construction이 fail-close합니다. 제안된 서술자
변경 발견 사항은 선택자가 exact 매니페스트 subset으로 검사되고 모델 노출 전에 deep copy되며 테스트가
출처 매니페스트 불변을 입증하므로 기각했습니다. Owning bilingual design은 새 경계를 이미 문서화합니다.
이 shadow-only 구획에는 재현 가능한 Medium 이상 발견 사항이 남아 있지 않습니다.

OQ-06부터 OQ-11까지 landing한 후 전체 프로그램을 대상으로 8,500-row 세대 동등성, activation 및
롤백, 임베딩 한계, Interface ACL, LinkType side, 조회 typing, 전환 escape 경로, 합계
처리 결과, 근거 잘림, 취소, bitemporal 시간, tombstone, 이행/권한 부여,
`routes_to`, zero-vs-missing 메트릭, causal refutation, 프로바이더 신원, continuous-gate honesty,
경계, docs 및 테스트 blind spot을 다루는 추가 25-lens 검토를 수행했습니다. 재현 가능한 Medium
발견 사항 두 개를 수정했습니다. Interface 속성은 이제 ObjectType 속성과 같은 역할/용도 filtering을
받으며 목표 증적은 기존 최종 사유와 evidence-reference 잘림을 모두 보존합니다. Focused
회귀가 두 수정 사항을 입증합니다. 구현된 ontology-query 프로그램에는 재현 가능한 Medium 이상
발견 사항이 남아 있지 않습니다. 남은 운영 프로바이더/영속 어댑터 연결은 명시적인 전달 공백이며
fail-close합니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 무작위 Console 근거와 현재 릴리스 차단 항목 | [온톨로지 쿼리 무작위 보증](ontology-query-randomized-assurance-ko.md) |
| 목표 질문 계획 수립 및 커버리지 계약 | [계층형 대화 계획](hierarchical-conversation-planning-ko.md) |
| Exact release, ObjectSet 및 타입이 지정된 함수 | [FDAI 온톨로지 안전성 Infrastructure](../architecture/operating-ontology-platform-ko.md) |
| Operating 객체, 관계, 신원 및 시간 | [FDAI 운영 온톨로지](../architecture/operating-ontology-ko.md) |
| Rule-specific 의미 세대 | [Rule 의미 검색](../rules-and-detection/rule-semantic-retrieval-ko.md) |
| Causal 가설 근거 및 종결 | [인과 인시던트 그래프](../rules-and-detection/causal-incident-graph-ko.md) |
| Console 및 서술기 권한 | [FDAI Console 대화](operator-console-ko.md) |
