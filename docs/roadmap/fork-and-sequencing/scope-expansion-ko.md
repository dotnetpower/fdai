---
title: 스코프 개선 및 구조적 갭
translation_of: scope-expansion.md
translation_source_sha: 3334d0ed5a74ed5131c2a6768a10009a3e43f6cd
translation_revised: 2026-08-11
---
# 스코프 개선 및 구조적 갭

FDAI는 자율 클라우드 운영 컨트롤 플레인으로 자리잡고 있지만
([copilot-instructions.md](../../../.github/copilot-instructions.md)),
초기 버티컬 - 변경 안전성, 복원력, 비용 거버넌스 -는
FDAI 배포가 성장해 나갈 운영 임무 중 일부만 cover 한다.
이 문서는 P2/P3 축 확장을 위한 **스코프 결정**을 못박아,
이후의 모든 구조적 변경이 명시된 design 의도 를 기준으로
landing 하도록 한다.

참조: 로드맵 레벨의 임무 목록은
[goals-and-metrics.md](../architecture/goals-and-metrics-ko.md) (KPI 1-4 + 가드
메트릭); layered 런타임 형태 은
[app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md);
CSP-neutral wire 계약 는
[csp-neutrality.md](../architecture/csp-neutrality-ko.md); trust-router / risk-gate /
컨트롤 루프 은
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md).

> **구현 상태 (2026-07-21).** §3에서 제안한 인시던트, 8개 텔레메트리 wire 계약, 워크로드
> SLO, 런북, on-call, 사후 분석, 버티컬 레지스트리는 배포됐습니다. §3의 `Problem` 문단은
> 채택 당시 historical 공백을 보존합니다. T2 후보의 액션 빌드와 unified risk/HIL 라우팅도
> 배포됐고, risk-eligible T2 액션을 실행기로 넘기는 최종 단계만 남았습니다.

## 1. In-scope axes (유지 + 확장)

| 축 | Position | 근거 설명 |
|------|----------|-----------|
| **변경 안전성** | 버티컬 유지. Foundational. | Deterministic-first ⇢ policy-gate ⇢ shadow → 강제 적용 는 현재 가장 강력한 story. |
| **복원력 (DR/Chaos)** | 버티컬 유지. Chaos Studio 어댑터 shipped. | Prod-exclusion 불변식 + `chaos:opt-out` 태그는 industry 에서 드문 안전성 하한 제공. |
| **비용 거버넌스 (FinOps)** | 버티컬 유지. | 확립된 FinOps guardrail 패턴에 align. |
| **인시던트 수명 주기** | **배포됨.** § 3.1 참조. | 영속 수명 주기, 제안, 알림, SLA, storm coordination 제공. |
| **텔레메트리 인제스트** | **Layer-0 경계 8개 및 Azure 어댑터 배포됨.** § 3.2 참조. | 메트릭/로그/추적이 SLO, detection, RCA를 grounding. |
| **워크로드 SLO / 오류 예산** | **배포됨.** § 3.3 참조. | 워크로드 SLI/SLO/burn을 control-plane SLO와 분리 유지. |
| **런북 orchestration** | **배포됨.** § 3.4 참조. | 범위가 제한된 단계/롤백 orchestration 제공. |
| **On-call 예약** | **배포됨.** § 3.5 참조. | Static + PagerDuty 예약과 역할 대체 경로 제공. |
| **사후 분석 초안** | **배포됨.** § 3.6 참조. | Template-first 초안과 근거에 기반한 learning 후보 제공. |
| **Full T1/T2 배선 into ControlLoop** | **액션 빌드 + risk/HIL 경로 배포, 조건을 충족한 실행 pending.** § 3.7 참조. | Quality-gated T2 후보는 액션으로 빌드되어 unified risk 게이트에 도달합니다. |

## 2. 명시적으로 deferred 된 axes (이 확장에 포함되지 않음)

| 축 | Position | 근거 설명 |
|------|----------|-----------|
| Multi-cloud (AWS / GCP) | 이후 단계 로 deferred. | 구현 focus 는 Azure 유지; wire-contract 경계 (§ 3.2) 이 AWS 어댑터 를 가산 로 유지. |
| Predictive 용량 / autoscaling | Deferred. | 텔레메트리 인제스트 (§ 3.2) 이 stub 이 아니라 real 이어야 depend 가능. § 3.2 먼저 ship 후 이것을 이후 단계 에서. |
| 공개 status-page 엔드포인트 | Deferred. | Stakeholder briefing과 다중 채널 전달은 배포됐고 공개 엔드포인트 연결만 외부입니다. |

## 3. 구조적 변경 (design 계약)

아래 모든 subsystem 은
[architecture.instructions.md § 안전성 Invariants](../../../.github/instructions/architecture.instructions.md#safety-invariants)
의 standing 불변식 를 honor MUST: 모든 자율 액션은 stop-condition,
롤백 경로, blast-radius 한도, 감사 항목 를 carry; 새 기능
는 shadow 모드 로 먼저 ship.

이 절의 `Problem`은 채택 당시 공백이고 `Design`은 현재 landed 계약을 설명합니다. 구체 상태는
위 구현 상태와 §6 커버리지 표를 따릅니다.

### 3.1 인시던트 를 일급 객체 로

**Problem.** 오늘의 이벤트 상관관계 은 `event_ingest` 내에서
`incident_id` 문자열을 produce 하지만, `Incident` 데이터 클래스 도, 상태
머신 도, 수명 주기 훅 도 없다. 결과적으로:

- 하나의 correlated 그룹 에 대한 여러 발견 사항 이 하나의 개체 의
 형제가 아니라 - 키 를 공유하는 이벤트일 뿐;
- 사후 분석, on-call 인계, after-action 검토 를 걸 장소가 없음;
- 인시던트 별 감사 조회 는 incident-indexed 조회 이 아니라 full-scan
 필터 요구.

**Design.**

- **스키마**: `shared/contracts/incident/schema.json` (JSON 스키마
 2020-12) + `shared/contracts/models.py` 의 pydantic `Incident` 모델.
 필드: `incident_id` (상관관계 키 로부터 결정론적), `state`,
 `severity`, `opened_at`, `mitigated_at`, `resolved_at`, `closed_at`,
 `correlation_keys`, `member_event_ids`, `related_finding_ids`,
 `related_action_ids`, `assignee_oid` (Entra OID; no-self-approval
 유지를 위해 submitter 와 서로 다른), `mitigation_summary`,
 `postmortem_ref`.
- **상태 머신**: `open → triaging → mitigated → resolved → closed`
 + reopen 경로 `resolved → triaging`. 불법 전이 은
 `IncidentTransitionError`. 전이 은
 `(incident_id, target_state, actor_oid)` 로 멱등적. 심각도는
 `resolved → triaging` reopen 간선에서만 변경할 수 있으며 재생에 보존됩니다.
- **영속성**: `StateStore` 를
 `append_incident_transition(entry: Mapping)` 로 확장; 구체적인
 Postgres 어댑터 는 전이 을 동일한 감사 스트림 으로 hash-chain
 (see [security-and-identity.md § Auditability](../architecture/security-and-identity-ko.md)),
 추가 전용 보장을 어느 것도 bypass 하지 않음. 덧붙이기는 `applied` 또는
 `duplicate`를 반환하며 stale 예상 상태는 `IncidentWriteConflictError`를
 발생시킵니다. PostgreSQL은 per-incident 참고용 잠금을 잡고 저장된 현재
 상태를 확인한 뒤 global 감사 해시 체인에 한 트랜잭션으로 덧붙이기합니다.
 Losing 복제본은 충돌을 반환하기 전에 정본 감사 변환 결과를 reload합니다.
- **소유권**: `core/incident/` (신규 패키지). 버티컬 은 후보
 전이 을 발행; 인시던트 모듈만이
 `append_incident_transition` 을 호출할 수 있는 유일한 쓰기 담당.
- **수명 주기 메타데이터**: 배정 변경은 `incident.assigned`를 덧붙이기합니다.
 성공한 GitHub/Jira/도구 증적은 프로바이더, 외부 id, 선택적 HTTPS URL을
 포함한 `incident.ticket`을 덧붙이기합니다. 둘 다 멱등적하고 replay-safe하며
 동일한 audit-backed 인시던트 명단에 표시됩니다. 벤더 호출은 전달 어댑터에
 유지되고 레지스트리는 성공 증적만 연결합니다.

**기본 제공 수명 주기 작업 흐름.** `IncidentLifecycleWorkflow`는
`IncidentRegistry` 위에서 생성과 전이를 처리하는 단일 경로를 제공합니다.

- 기여자 역할의 운영자는 영어 또는 한국어 채팅으로 인시던트 생성을 요청할
 수 있습니다. 결정론적 파서는 인시던트/열림 의도, 심각도, 대상을 요구하며
 누락된 값은 추측하지 않고 다시 묻습니다. 완전한 요청은 생성 내용을 설명하는
 10분짜리 제안을 만들고, 같은 대화의 같은 운영자만 확인할 수 있습니다.
- 허용 목록에 포함된 에이전트는 하나 이상의 구성원 이벤트와 비어 있지 않은 사유를
 제공할 때만 대화형 확인 없이 인시던트를 열 수 있습니다. 따라서 자율 생성은
 관찰된 근거에 grounding됩니다.
 운영은 pantheon이 이벤트 consume을 시작하기 전에 Heimdall의 repeated-event
 후보 훅을 동일한 영속 작업 흐름에 전달합니다.
- 열림 재전송과 같은 상태로의 전이는 멱등적하며 중복 알림을 보내지
 않습니다. 모든 수명 주기 감사 행은 결정론적 인시던트 id를 top-level
 `correlation_id`로 전달하므로 콘솔 명단이 리소스 이름에서 연관 관계를
 추론하지 않고 투영할 수 있습니다. 새 구성원 이벤트는 `incident.members` 행을
 덧붙이기하므로 상관관계 확장이 재시작 후에도 유지됩니다.
- 생성, 합법적인 상태 변경, 요청된 명단 요약은
 `DurableIncidentLifecycleNotifier`로 감싼 `RoutedIncidentLifecycleNotifier`를 통해
 A2 운영 알림을 보냅니다. 각 수명 주기 occurrence는 고정된 `audit_id`를 가지며,
 sent 체크포인트는 반복 전달을 막고 시작 재생은 체크포인트가 없는 감사
 행을 재시도합니다. 실제 채널 어댑터가 연결되지 않으면 운영 기본값은
 알림을 버리지 않고 StateStore-backed HIL 에스컬레이션 싱크로 라우팅합니다.
 수명 주기 메시지는 자유 형식 사유와 리소스 상관관계 키를 제외하며,
 명단 메시지는 최대 20개 인시던트 id와 전체 명단 링크를 포함합니다.

프로세스 내 레지스트리는 정본이 아니라 변환 결과입니다. 운영 시작은
Postgres에서 정렬된 `incident.open`, `incident.members`, `incident.transition` 행을
읽고 API가 트래픽을 받기 전에 레지스트리를 재구성합니다. 유효하지 않은 id, 상태
정렬, 시각은 이전 스냅샷을 교체하지 않고 시작을 실패시킵니다. Pending
채팅 제안은 비동기 `IncidentProposalStore`를 사용합니다. 로컬 개발은 범위가 제한된
in-memory 저장소를 연결하고 운영은 atomic Postgres `DELETE ... RETURNING` consume을
사용하므로 하나의 복제본만 확인을 수락할 수 있습니다. 저장된 제안은
운영자 텍스트 원문이 아니라 해시만 저장합니다. 로컬 projecting 저장소는 채팅에서
생성한 인시던트를 `/incidents`에 즉시 표시합니다.

**SLA 에스컬레이션 및 metrics.** `IncidentSlaPolicy`는 모든 심각도에 대해 설정된
확인 응답 및 해석 seconds를 받습니다. 운영 monitor는
`FDAI_INCIDENT_SLA_POLICY_JSON`이 공급되기 전까지 비활성화된입니다. 활성화되면 ordered
감사 행에서 현재 state-entry 시각을 도출하고 기한에 고정된 `sla_breach`
A2 notice를 발행하며 영속 알림 체크포인트로 반복 검사를 dedup합니다.
Resolved 및 closed 인시던트는 alert하지 않습니다. `project_incident_metrics`는
deduplicated 감사 행을 에이전트/운영자 생성 수, 현재 상태/심각도 수, 배정 및
티켓 수, reopen 수, mean 확인 응답/해석 소요 시간으로 투영합니다. 이 값은
KPI 및 briefing 표면에 사용할 수 있는 measured 사실입니다.
성공한 `tool_call` 티켓 증적은 최종 실행기 성공 전에 증적 관찰기를
통과합니다. 연결 실패는 retryable합니다. 재전달에서 어댑터 원장이
`already_applied`를 반환하고 인시던트 링크만 다시 시도합니다.

**Storm 처리.** 하나의 근본 결함이 다수의 상관 인시던트 로 동시 확산 될 때,
모든 교정 을 한꺼번에 발화하면 영향 범위 가 배가되고 공유
의존성에서 race 가 나며 운영자를 파묻어 버린다. `core/incident/storm.py`
(`StormCoordinator`) 는 인간 지휘관의 판단을 증류한 결정론적이고 I/O 없는
incident-command 플래너다:

- **Storm 감지** 는 sliding 구간 안의 신호 을 세고, 임계값 이상의
 개수 는 storm 이다.
- **우선순위 시퀀싱** 은 교정 을 심각도(SEV1 우선), 그다음 영향
 radius, 그다음 고정된 id 순으로 정렬해 계획을 재현 가능하게 한다.
- **동시성 캡** 은 정렬된 계획을 capped wave 로 나눈다; storm 중에는 캡이
 더 조여진다(기본 1 = 엄격한 직렬) 그래서 동시 확산 이 병렬로 실행되지 않는다.
- **동적 HIL** 은 `StormPolicy` 를 반환하며, storm 이 활성인 동안 승인 기준을
 올려(설정된 심각도 이상에서 상향) 고영향 액션이 storm 중 자동 실행되지
 않게 한다.

이 조정기 는 참고용 다 - risk 게이트 와 실행기 가 그
`StormPolicy` 와 정렬된 계획을 소비한다; 스스로 실행하거나 잠금 을 잡거나
모델 을 호출하지 않으므로 `core/` 가져오기 규칙 아래 머문다.

### 3.2 텔레메트리 인제스트 경계 (Layer-0 확장)

**Problem.** [csp-neutrality.md](../architecture/csp-neutrality-ko.md) 는 다섯 개의
wire-level 계약 를 선언 (이벤트 버스, 상태 저장소, 시크릿, 워크로드
신원, 인벤토리). OpenTelemetry 는 컨트롤 플레인 트레이스를 발행
하지만 외부 메트릭, 로그, 추적 를 consume 하는 것이 없다. 이는
`observability-and-detection.md` design 을 상관관계 only 로 상한 -
anomaly, 예측, RCA 는 real 텔레메트리 위에 ground 할 수 없음.

**Design.**

- **`shared/providers/` 아래 세 개의 새로운 비동기 프로토콜**:
 - `MetricProvider.query(query: MetricQuery) -> AsyncIterator[MetricPoint]`
 (Prometheus PromQL, Azure Monitor Logs, 또는 CloudWatch 로 backed;
 업스트림 은 로컬 no-op + 문서화된 형태 ship).
 - `LogQueryProvider.query(query: LogQuery) -> AsyncIterator[LogRecord]`
 (Log Analytics KQL, Loki LogQL 등으로 backed).
 - `TraceQueryProvider.query(query: TraceQuery) -> AsyncIterator[Span]`
 (App Insights, Tempo, Jaeger 로 backed).
- Wire 계약 수가 **5 → 8** 로 증가; [csp-neutrality.md](../architecture/csp-neutrality-ko.md)
 는 경계 을 introduce 하는 동일 PR 에서 갱신.
- **기본값 업스트림 연결**: 빈 iterator 를 반환하는 로컬 no-op
 프로바이더. 첫 실제 운영 `MetricProvider` 어댑터 가 land 했다 -
 `delivery/azure/metric_logs.py` (`AzureMonitorLogsMetricProvider`,
 조회 REST API 위의 Log Analytics KQL). 조립 루트 에서
 `bind_azure_monitor_logs` 로 연결 되고 dev 에서는 `Noop` 이 기본이라
 동등성 계약이 유지된다. 남은 `LogQueryProvider` / `TraceQueryProvider`
 어댑터 는 이어지는 작업 항목 에서 land; 경계 만으로도 anomaly /
 예측 / RCA subsystem 이 안정된 인터페이스 에 대해 작성자 되기에
 충분.
- **데이터가 흐르는 곳**: 프로바이더 는 구조화된 기록 를 produce 하고
 이것이 내부 버스 상의 `Event` 객체가 되므로, trust-router 와
 risk-gate 가 무엇이 자율적으로 실행되는지에 대한 유일한 권한
 로 유지.

### 3.3 워크로드 SLO subsystem

**Problem.** [deployment.md § Observability, SLOs, and Alerting](../deployment/deployment-ko.md)
는 **컨트롤 플레인** SLO 를 정의 (FDAI 자기 자신의 지연 시간, 성공
비율, 콘솔 가용성). 부재한 나머지 절반은 **workload-facing
SLO** - 사용자가 보는 인시던트 우선순위를 순위 하고 error-budget burn
동안 risky 변경 를 게이트 하는 SLI/SLO/error-budget 계층.

**Design.**

- **스키마**: `shared/contracts/slo/schema.json` - `SLI` (조회 +
 임계값 + 종류={가용성, 지연 시간, 정확성, 최신성}),
 `SLO` (목표 ratio + 구간), `ErrorBudget` (derived),
 `BurnRate` (short + long 구간).
- **모듈**: `core/slo/` 와 `SloRegistry` (`rule-catalog/slo/` 로부터
 YAML SLO 부하) 그리고 `BurnRateEvaluator` (Google SRE Chapter 5 의
 multi-window multi-burn-rate alerting).
- **컨트롤 루프로 wire back**: burn-rate breach 는
 `Event(event_type="slo.error_budget_burn")` 을 발행 하여 동일한
 trust-router → risk-gate → 실행기 경로 를 적중. Side 채널 없음.
- **SLO subsystem 이 하지 않는 것**: [goals-and-metrics.md](../architecture/goals-and-metrics-ko.md)
 를 replace 하지 않는다. 그 파일은 **FDAI 자신의 performance** 를
 측정; SLO subsystem 은 **FDAI 가 운영하는 워크로드** 를 측정.
 명확히 분리된 신원 로 coexist.

### 3.4 런북 DAG 오케스트레이터

**Problem.** 온톨로지의 `ActionType` 은 `stop_condition`,
`rollback_contract`, `blast_radius` 를 가진 leaf 액션. 실제 SRE
런북 은 여러 ActionType 을 체인 (예: `db.failover` → `app.restart`
→ `healthcheck` → on-fail `db.rollback`). 오늘은 조립 기본 요소
없음.

**Design.**

- **스키마**: `shared/contracts/runbook/schema.json` - `RunbookStep`
 항목 의 ordered 순서, 각각 이름 으로 ActionType 을 지점,
 선택적 `on_failure` 가지 단계 id 포함.
- **실행기**: `core/runbook/runner.py` 와 `RunbookRunner.실행(런북,
 맥락)` 가 `RunbookResult` (per-step 결과 + 최종 상태)
 반환. 실행기 는 **모든 단계 에서** 7개 안전조건을 honor -
 최종 뿐만 아니라 - 실패 단계 의 롤백 가지 자체가 실행기
 short-circuit 전에 감사.
- **최소 viable 스코프**: linear 순서 + single `on_failure` 가지
 (real DAG 는 두 호출자 가 필요할 때까지 deferred). "장애 조치 →
 재시작 → healthcheck → 롤백" encode 하기에 충분.
- **Docs**: [action-ontology.md](../decisioning/action-ontology-ko.md) vocabulary
 재사용; 새 형제 doc `docs/roadmap/runbook.md`.

### 3.5 On-call 예약 프로바이더

**Problem.** `HilChannel` 은 Teams 채널로 승인 을 경로; RBAC 은
역할 로 승인자 를 pick. 어느 쪽도 **누가 지금 shift 중인지** 모름.
새벽 3시에 "동일한" 승인자 버킷 은 자고 있는 20명.

**Design.**

- **프로토콜**: `shared/providers/oncall_schedule.py` 의
 `OnCallSchedule.current(rotation: str) -> OnCallShift`, `OnCallShift(rotation, primary_oid, secondary_oid, until)`
 반환.
- **기본값 업스트림 구현**: 구성 로부터 shift 의 JSON 목록 를
 reading 하는 `StaticOnCallSchedule`. 포크 모델 은 PagerDuty /
 OpsGenie 어댑터 를 wire.
- **통합**: `HilChannel.dispatch(...)` 는 선택적
 `on_call_shift` 를 수용; 조정기 계층 가 전달 전에
 `OnCallSchedule` 을 consult 하여 페이지 받는 party 가 역할 버킷 이
 아닌 shift-holder.
- **실패 시 차단**: 예약 프로바이더 가 오류 하면, HIL 요청은 전체
 역할 버킷 으로 대체 경로 (기존 행동) - 요청 를 폐기 하지 않음.

### 3.6 사후 분석 초안 generator

**Problem.** SRE 문화는 모든 significant 인시던트 후에 written PIR /
사후 분석 을 demand. FDAI 는 raw material (감사 로그, 발견 사항,
액션) 을 가지고 있지만 synthesizer 가 없다.

**Design.**

- **모듈**: `core/postmortem/` 와 `Incident` id + 선택적
 `PostmortemLlm` 연결 을 taking 하고 `PostmortemDraft` (구조화된
 markdown: 요약, 타임라인, 영향, 루트 원인, contributing
 factors, actions taken, 후속 조치) 를 반환하는 `PostmortemGenerator`.
- **LLM 부재 시 실패 시 차단**: `PostmortemLlm` 이 연결 되지 않으면,
 generator 는 감사 타임라인 만으로 **template-based** 초안 반환 -
 fabrication 없음, "TODO" 로 marked 된 누락된 섹션 없음; 각
 섹션 은 실제 감사 데이터 로 채워지거나 명시적인 "no 근거
 기록된" 줄.
- **출력 영속성**: 초안 는 교정 PR 을 ship 하는 동일한
 PR-native 전달 흐름 로 `rule-catalog/postmortems/<incident-id>.md`
 아래의 git-managed 위치 에 쓰기, 검토 / 승인 이 기존
 게이트 재사용. [action-ontology.md](../decisioning/action-ontology-ko.md) 의
 `pr_native` 실행 경로 를 의도적으로 재사용.
- **Knowledge 추출 (재사용 lesson)**:
 `core/postmortem/learning.py` (`PostmortemKnowledgeExtractor`) 가
 *resolved* 인시던트 와 그 감사 타임라인 을 inert `PostmortemLearning`
 후보 로 mining 한다 - 조직이 원래 엔지니어 머릿속에만 두는 "이
 패턴이 발생했을 때 이 액션 이 해결했다" 는 지식이다. 결정론적이며
 **실패 시 차단**: 감사 trail 에 기록된 루트 원인 *와* 최소 하나의
 성공적으로 실행된(enforce-mode, success-outcome) 액션 이 있을 때만
 learning 을 발행 하고, 그렇지 않으면 **abstain** - lesson 을 절대
 fabricate 하지 않는다. learning 은 특정 리소스 id 로부터 일반화한다
 (correlation-key *접두사* 로 기준점 하므로 `resource:vm-a` 는
 `vm-a` 가 아니라 재사용 가능한 기준점 `resource` 를 기여), 발견
 루프 이 반복 패턴을 dedup 할 수 있도록 결정론적 `signature` 를
 carry 하며, 다른 룰 후보 와 동일한 `CandidateGuard` 를 통과하도록
 근거에 기반한 `provenance` 를 ship 한다. 출력은 액션 도 카탈로그 편집 도
 아닌 지식이다: 기억 / 발견 루프
 ([rule-catalog-collection.md](../rules-and-detection/rule-catalog-collection-ko.md)) 에
 피드 되고 카탈로그 에 영향을 주기 전 표준 quality 게이트 를 통과해야 한다.

### 3.7 T1 / T2 계층 를 `ControlLoop` 로 wire

**상태.** T1 과 T2 모두 루프에 wired됐습니다. T2 후보의 액션 빌드, unified risk
evaluation, 거부/HIL 라우팅까지 배포됐고 risk-eligible 후보의 실행기 인계만 남았습니다.
`ControlLoop.__init__` 은 선택적 `t1_engine`(`T1Tier`) 과
`t2_engine`(`T2Tier`) - 둘 다 Protocol-typed - 을 수용. `process` 는
`T0.abstain -> T1.reuse-log -> T2.propose + quality-gate` 를 실행하며,
각 계층 홉 은 자체 감사 항목 를 쓰기 하여 결정 이 reconstructable.
T1 reuse는 **shadow-only**입니다. T2는 후보를 액션/risk 경로까지 전달합니다. T1 유사도 적중은
`T1_REUSE_LOGGED` 로, T2 판정 는
`T2_PROPOSED_LOGGED` / `T2_ESCALATED` / `T2_DENIED` / `T2_ABSTAINED` 로
기록됩니다. T2 출력은 조건을 충족한이 되기
전에 `QualityGate`(mixed-model 교차 검증 + 검증기 + grounding)를
통과함.

**Remaining design (T2 실행).**

- unified risk 결정이 `auto`인 T2 액션을 선택된 실행기로 인계하고 최종
 증적을 기록합니다. 액션 빌드와 risk 라우팅은 이미 완료됐습니다.
- 게이트 `ELIGIBLE` 판정 만 risk-gate 에 도달; `ESCALATE` / `DENIED` /
 `ABSTAIN` 은 절대 auto-execute 되지 않음. 실행 충족 여부 는
 결정론적 게이트 가 부여하며, 모델 은 절대 부여하지 않음.

**시나리오 재생.** [services/core-control-plane/tests/scenarios/v2026.07/](../../../services/core-control-plane/tests/scenarios/v2026.07)
의 고정된 시나리오는 shipped 룰이 매핑되는 곳마다
[services/core-control-plane/tests/scenarios/enrichment/v2026.07/](../../../services/core-control-plane/tests/scenarios/enrichment/v2026.07)
오버레이 로 T0 에서 enrich 됨 - 예:
`finops.stop-idle-dev-vm-off-hours.003` 은 `compute.vm.idle-detected` 발화,
`dr.replica-lag-degraded.001` 은 `postgresql-server.high-availability` 발화
(risk-gate 경유 HIL).
오버레이 가 아직 없는 시나리오는 `xfail` 유지:
`dr.chaos-experiment-novel.003`(T2 필요),
`dr.backup-vault-restore-rehearsal.002` /
`change.drift-manual-portal-edit.003`(shipped 룰 작성자 필요).

### 3.8 버티컬 레지스트리 (new-domain 온보딩 경계)

**Problem.** FDAI 는 세 버티컬 (복원력, 변경 안전성, 비용
거버넌스)을 ship 하지만, "조직 대체"는 그 집합이 **`core/` 편집 없이**
security 자세, compliance, patch 관리 로 커져야 함을 의미한다. 오늘은
셋이 직접 composed 되며, 포크 가 네 번째를 onboard 할 선언된 경계 이 없다.

**Design.**

- **모듈**: `core/verticals/registry.py` 의 `VerticalRegistry` 가 inert
 `VerticalDescriptor` (`vertical_id`, `display_name`, `category`,
 `rule_source_ids`, `enabled`, `default_mode`)를 보유한다. 포크 가
 조립 루트 에서 서술자 를 등록하고, 컨트롤 루프 은 셋을
 hard-code 하는 대신 레지스트리 를 enumerate 한다.
- **Validating, 플러그인 로더 아님.** 등록은 misconfigured onboarding 을
 즉시 거부 한다: 중복이거나 non-ASCII 인 `vertical_id`, 룰 출처 를
 명명하지 않은 **활성화된** 버티컬 (아무것도 감지하지 않는 도메인), 또는
 강제 적용 모드 로 직접 onboard 하려는 서술자. `register_all` 은 첫 실패에서
 abort 하므로 부분 배치 가 half-register 될 수 없다.
- **구성상 shadow-first.** `default_mode` 는 `Mode.SHADOW` 로 기본값 되고
 onboarding 시 shadow 로 유지되어야 한다 - 강제 적용 로의 승격 은 별도
 검토된 변경 이므로, onboarding 이 절대 자율 액션 을 silently
 활성화 할 수 없다. Enumeration (`all`, `enabled`)은 id-sorted 이고 결정론적이다.

## 4. 롤아웃 순서 및 안전성 모드

위 모든 subsystem 은 **shadow 모드** 로 먼저 ship
([architecture.instructions.md § 안전성 Invariants](../../../.github/instructions/architecture.instructions.md#safety-invariants)).
강제 적용 로의 승격 은 모듈 의 `promotion_gate` 가 선언하는
shadow accuracy 로 gated 된 별도 변경 (룰 / ActionType 승격
계약을 mirror).

롤아웃 순서는 strict 선행 조건 체인 을 pick:

1. **§ 3.1 인시던트** 와 **§ 3.2 텔레메트리** 는 독립적 - 둘 다 동일
 단계 에서 ship, 순서 무관.
2. **§ 3.7 T1/T2 배선** - T1 은 이미 shipped; T2 는 `t2_reasoning` 계층 라이브러리 구축이 선행.
3. **§ 3.3 SLO** 는 § 3.2 depend (real burn-rate 는 메트릭 인제스트
 필요).
4. **§ 3.6 사후 분석** 은 § 3.1 depend.
5. **§ 3.5 On-call** 은 독립적.
6. **§ 3.4 런북** 은 독립적 - 기존 ActionType 을 compose.

## 5. 이 문서가 아닌 것

- 단계 계획 아님. 단계 는 [docs/roadmap/phases/](../phases) 아래 존재
 하며 이러한 subsystem 을 관리자 의 예약 에 따라 자리.
- Customer-facing spec 아님. FDAI 는 customer-agnostic 유지; § 3.2 의
 wire 계약 는 포크 모델
 ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md))
 intact 유지.
- 완전한 운영 커버리지 점유 아님. § 2 의 deferred 축 는 단계 가
 명시적으로 집을 때까지 의도적으로 범위 밖 유지.

## 6. SRE 에이전트 임무 커버리지

SRE 에이전트 가 커버하리라 기대되는 기준선 의무를, 그것을 구현하는 FDAI
서브시스템에 대해 정직하게 매핑합니다. `Covered` 는 `core/` 서브시스템과 그
규칙/테스트가 존재함을 뜻하고; `Partial` 은 서브시스템은 있으나 선언된 의존성이
아직 deferred 임을 뜻하며; `Deferred` 는 경계 만 설계됨(§ 2 / § 3), 배선 안 됨을
뜻합니다.

상세 비교는 이제 Azure SRE 에이전트의 51개 원자 기능, Microsoft Learn 공식 출처,
런타임 동등성 상태와 정확한 FDAI 근거를
[SRE 에이전트 동등성 감사](../../internals/sre-agent-parity-audit.md)에서 추적합니다. 아래 표는
임무 수준의 짧은 요약으로 유지합니다.

| SRE 의무 | 상태 | 위치 |
|----------|------|------|
| 인시던트 감지 / triage / 수명 주기 | Covered | `core/incident/` (§ 3.1), `core/event_ingest/` |
| Root-cause analysis | Covered | `core/rca/`, [observability-and-detection.md](../rules-and-detection/observability-and-detection-ko.md) |
| 자동 완화(risk-gated) | Covered | `core/risk_gate/`, `core/executor/`, [risk-classification.md](../decisioning/risk-classification-ko.md) |
| 사후 분석 | Covered | `core/postmortem/` (§ 3.6) |
| Anomaly / 예측 / 상관관계 | Covered | `core/detection/`, [observability-and-detection.md](../rules-and-detection/observability-and-detection-ko.md) |
| 용량 계획 수립 | Covered | `core/capacity/` |
| 런북 orchestration | Covered | `core/runbook/` (§ 3.4) |
| 변경 안전성 / pre-deploy feasibility | Covered | `core/deploy_preflight/`, [deployment-preflight.md](../deployment/deployment-preflight-ko.md) |
| 자세 리뷰 / 아키텍처 Q&A | Covered | `core/assurance_twin/`, [assurance-twin.md](../operations/assurance-twin-ko.md) |
| **Dev-to-ops 핸드오프 (정책 + RBAC 리뷰)** | Covered | [operational-readiness.md](../operations/operational-readiness-ko.md) (ORR) |
| **신원 / RBAC 최소권한 자세** | Covered | 워크로드 RBAC 규칙 팩(`*.role-assignment.*`) + `remediate.right-size-role` |
| SLO / 오류 예산 | Covered | `core/slo/`와 routed Prometheus, Azure Monitor Metrics, KQL 프로바이더를 사용하며 `SloBurnRunner`는 데이터 누락 시 실패 시 차단합니다. |
| Monitoring / alerting (외부 신호 인제스트) | Covered | 메트릭, 범위가 제한된 KQL, App Insights 추적, Activity Log, 진단 스트림, anomaly, 예측, RCA 텔레메트리 grounding을 제공합니다. |
| On-call 스케줄 / paging | Covered | fail-safe `OnCallResolver`, 명시적 Entra 대응을 사용하는 PagerDuty 명단 어댑터, PagerDuty 이벤트 v2 paging, 역할 대체 경로를 제공합니다. |
| 상태 페이지 / stakeholder broadcast | Covered | Stakeholder briefing과 Teams, Slack, 이메일, 웹훅, PagerDuty, SMS 채널을 제공합니다. 공개 status-page 엔드포인트는 외부 연결입니다. |
| DORA change-failure-rate / deploy-frequency | Covered | `core/measurement/dora.py`가 정규화된 배포 관측에서 네 가지 DORA measure와 잘못된/커버리지 개수를 계산합니다. |

배포 자격 증명과 엔드포인트는 저장소 공백이 아니라 외부 구성입니다.
설정되지 않은 어댑터는 사용 불가를 보고하거나 문서화된 역할 대체 경로를 사용하며 고정본을
대체하거나 자율성을 승격하지 않습니다. Direct 쓰기 CLI와 global auto-approval은 FDAI의 타입이 지정된
액션, 정책, risk, 승인, 롤백, 잠금, 멱등성, 감사 경로로 의도적으로 대체합니다.
