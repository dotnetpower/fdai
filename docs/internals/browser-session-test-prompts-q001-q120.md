# FDAI Browser Session Test Prompts Q001-Q120

이 문서는 FDAI Console의 새 대화에서 Q001-Q120을 사람이 직접 다시 테스트하기 위한 복붙용
프롬프트 모음입니다. 각 문항은 기존 seed와 의미를 유지한 변형 두 개를 포함합니다.

## 테스트 방법

1. FDAI Console에서 **새 대화**를 엽니다.
2. 한 QID의 원문, 변형 A, 변형 B를 각각 **서로 다른 새 대화**에서 실행합니다.
3. 현재 화면을 전제로 하는 질문은 관련 화면을 연 뒤 실행하고, 화면 없는 상태도 별도 확인합니다.
4. 이전 답변, 선택된 리소스, 인시던트, action이 필요한 질문은 fresh session에서 먼저 실행해
   `prior_context_required` 또는 exact-context hold를 확인합니다.
5. 같은 문항의 positive path는 아래 선행 시퀀스로 context를 만든 뒤 같은 대화에서 target prompt를
   실행합니다.
6. Q097-Q102는 실제 변경을 만들기 위한 절차가 아닙니다. 별도 승인된 action context가 없는 새
   대화에서는 실행하지 않고 hold하는 것이 정상입니다.

## 공통 선행 시퀀스

### 리소스 context

1. `현재 관리 범위의 리소스를 이름, 유형, 상태와 함께 보여줘.`
2. 결과에서 리소스 하나를 선택하거나 이름을 명시합니다.
3. resource-dependent target prompt를 같은 대화에 붙여 넣습니다.

### 인시던트 context

1. `가장 최근 인시던트를 ID, 상태, 마지막 근거 시각과 함께 보여줘.`
2. 결과에서 인시던트 하나를 선택합니다.
3. incident-dependent target prompt를 같은 대화에 붙여 넣습니다.

### 이전 검증 답변 context

1. `현재 관리 범위에서 상태가 확인된 리소스를 근거와 함께 하나 보여줘.`
2. verified 또는 explicit fail-closed 답변이 끝난 뒤 freshness, reformat, evidence target prompt를
   같은 대화에 붙여 넣습니다.

### Governed action context

1. `최근 governed action의 상태를 실행 없이 읽기 전용으로 보여줘.`
2. exact action ID가 확인된 경우에만 proposal, approval, execution-status target prompt를 같은 대화에
   붙여 넣습니다.
3. 실제 승인이나 실행은 이 수동 테스트 팩의 범위가 아닙니다.

### Active investigation context

1. `이 문제를 bounded deep investigation으로 조사하고 진행 단계를 보여줘.`
2. investigation이 active 상태일 때 cancellation target prompt를 같은 대화에 붙여 넣습니다.

### Source failure context

1. `현재 사용할 수 없는 데이터 원본과 확인 가능한 사실을 분리해서 보여줘.`
2. explicit source-failure receipt가 반환된 뒤 failure-honesty target prompt를 같은 대화에 붙여 넣습니다.

## Q001-Q020 Resource coverage

### Q001 Database state

- 원문: `중지된 데이터베이스 있어?`
- 변형 A: `현재 중지 상태인 데이터베이스가 있나?`
- 변형 B: `지금 멈춰 있는 DB 서비스를 찾아줘.`

### Q002 Database state

- Original: `Are any databases stopped right now?`
- Variant A: `Are there any database services currently stopped?`
- Variant B: `Show me any databases that are not running right now.`

### Q003 Database state by type

- 원문: `현재 멈춰 있는 DB를 종류별로 보여줘.`
- 변형 A: `중지된 데이터베이스를 유형별로 묶어서 보여줘.`
- 변형 B: `지금 멈춘 DB 서비스가 어떤 종류인지 나눠서 알려줘.`

### Q004 Database state groups

- Original: `List stopped and paused database services separately.`
- Variant A: `Separate stopped database services from paused ones.`
- Variant B: `Show two groups for database services: stopped and paused.`

### Q005 Failed resources

- 원문: `실패 상태인 Azure 리소스가 있어?`
- 변형 A: `현재 failed 상태로 관측된 Azure 리소스가 있나?`
- 변형 B: `실패한 Azure 리소스를 확인해줘.`

### Q006 Degraded or unavailable resources

- Original: `Which resources are failed, degraded, or unavailable?`
- Variant A: `List resources whose state is failed, degraded, or unavailable.`
- Variant B: `Are any managed resources failed, degraded, or currently unavailable?`

### Q007 Deallocated VMs

- 원문: `할당 해제된 가상 머신을 모두 찾아줘.`
- 변형 A: `현재 deallocated 상태인 VM을 전부 보여줘.`
- 변형 B: `할당 해제 상태로 관측된 가상 머신 목록을 알려줘.`

### Q008 VM state groups

- Original: `Which virtual machines are running, stopped, or deallocated?`
- Variant A: `Group the virtual machines by running, stopped, and deallocated state.`
- Variant B: `Show VM counts and names for running, stopped, and deallocated states.`

### Q009 AKS health

- 원문: `비정상 상태인 AKS 클러스터나 노드가 있어?`
- 변형 A: `현재 건강하지 않은 AKS 클러스터 또는 노드가 있나?`
- 변형 B: `AKS 클러스터와 노드 중 비정상 상태를 찾아줘.`

### Q010 Kubernetes workload health

- Original: `Show unhealthy Kubernetes workloads and when they became unhealthy.`
- Variant A: `Which Kubernetes workloads are unhealthy, and when did that state begin?`
- Variant B: `List unhealthy Kubernetes workloads with the observed transition time.`

### Q011 Storage health

- 원문: `사용 불가능하거나 성능이 저하된 스토리지 계정이 있어?`
- 변형 A: `현재 unavailable 또는 degraded 상태인 스토리지 계정을 찾아줘.`
- 변형 B: `스토리지 계정 중 사용할 수 없거나 성능 저하가 관측된 것이 있나?`

### Q012 Cache health

- Original: `Are any cache services unavailable or under memory pressure?`
- Variant A: `Which cache services are unavailable or showing memory pressure?`
- Variant B: `Check whether any cache is down or experiencing high memory pressure.`

### Q013 App readiness

- 원문: `실행 중이 아니거나 준비되지 않은 앱 서비스를 보여줘.`
- 변형 A: `현재 running 또는 ready 상태가 아닌 앱 서비스를 찾아줘.`
- 변형 B: `준비되지 않았거나 실행되지 않는 앱 서비스가 있나?`

### Q014 Serverless readiness

- Original: `Which function or container applications are not ready?`
- Variant A: `List function apps and container apps that are not ready.`
- Variant B: `Are any serverless or container applications currently unready?`

### Q015 Subscription inventory summary

- 원문: `이 구독에서 관리 중인 리소스를 유형별로 요약해줘.`
- 변형 A: `현재 구독의 관리 리소스를 종류별 개수로 정리해줘.`
- 변형 B: `이 구독에 있는 리소스를 유형 기준으로 요약해줘.`

### Q016 Managed scope counts

- Original: `How many resources and resource groups are in the managed scope?`
- Variant A: `Count the resources and resource groups in the current managed scope.`
- Variant B: `What are the total resource and resource-group counts for this managed scope?`

### Q017 Current screen group inventory

- 원문: `현재 화면의 리소스 그룹에 어떤 서비스가 있어?`
- 변형 A: `지금 보고 있는 리소스 그룹의 서비스 목록을 보여줘.`
- 변형 B: `현재 화면에 선택된 리소스 그룹에는 어떤 리소스 유형이 있나?`

### Q018 Current group details

- Original: `List resources in this group with type, region, and state.`
- Variant A: `Show this group's resources with their type, location, and current state.`
- Variant B: `For the current group, list each resource's name, type, region, and status.`

### Q019 Unsupported inventory types

- 원문: `상태를 확인할 수 없는 리소스 유형도 함께 알려줘.`
- 변형 A: `현재 상태를 읽지 못한 리소스 유형을 별도로 표시해줘.`
- 변형 B: `지원되지 않거나 상태 확인이 불가능한 리소스 종류도 알려줘.`

### Q020 Inventory coverage

- Original: `What inventory types did you check, skip, or fail to read?`
- Variant A: `Separate inventory types into checked, skipped, and failed-to-read groups.`
- Variant B: `Which resource types were inspected, omitted, or unavailable to the inventory reader?`

## Q021-Q036 Health, change, authorization, freshness

### Q021 Platform impact

- 원문: `현재 Azure 플랫폼 장애의 영향을 받는 리소스가 있어?`
- 변형 A: `지금 활성 Azure 플랫폼 문제로 영향받는 관리 리소스가 있나?`
- 변형 B: `현재 플랫폼 장애 영향이 관측된 Azure 리소스를 확인해줘.`

### Q022 Active Azure outage

- Original: `Is any managed resource affected by an active Azure outage?`
- Variant A: `Which managed resources, if any, are impacted by a current Azure outage?`
- Variant B: `Check the managed scope for resources affected by an active platform incident.`

### Q023 Platform versus customer stop

- 원문: `플랫폼 문제와 고객이 시작한 중지를 구분해줘.`
- 변형 A: `플랫폼 원인과 고객 또는 자동화가 시작한 중지를 나눠서 보여줘.`
- 변형 B: `이 상태가 Azure 플랫폼 영향인지 고객 시작 변경인지 구분해줘.`

### Q024 Impact attribution

- Original: `Separate platform-initiated impact from customer-initiated changes.`
- Variant A: `Distinguish Azure platform impact from changes initiated by the customer.`
- Variant B: `Classify observed events as platform-initiated or customer-initiated.`

### Q025 Health history

- 원문: `지난 24시간의 리소스 상태 이벤트를 시간순으로 보여줘.`
- 변형 A: `최근 하루 동안 발생한 Resource Health 이벤트를 순서대로 정리해줘.`
- 변형 B: `지난 24시간의 리소스 상태 변경 이력을 타임라인으로 보여줘.`

### Q026 Resource Health events

- Original: `What Resource Health events occurred during the last day?`
- Variant A: `List Resource Health events from the past 24 hours in time order.`
- Variant B: `Show the managed resources' health events during the previous day.`

### Q027 Change attribution

- 원문: `누가 이 리소스를 중지했어?`
- 변형 A: `이 리소스의 중지 작업을 시작한 주체는 누구야?`
- 변형 B: `누가 또는 어떤 자동화가 이 리소스를 멈췄는지 알려줘.`

### Q028 Most recent change

- Original: `Who changed this resource most recently, and what did they do?`
- Variant A: `Identify the latest actor who changed this resource and the operation performed.`
- Variant B: `What was the most recent change to this resource, and who initiated it?`

### Q029 Pre-incident changes

- 원문: `장애 직전에 발생한 배포와 설정 변경을 찾아줘.`
- 변형 A: `인시던트 바로 전에 있었던 배포 또는 구성 변경을 보여줘.`
- 변형 B: `장애 발생 전의 최근 배포와 설정 변경 이력을 찾아줘.`

### Q030 One-hour change timeline

- Original: `Build a change timeline for the hour before the incident.`
- Variant A: `Show an ordered timeline of changes during the hour preceding the incident.`
- Variant B: `List deployments and configuration changes from the 60 minutes before the incident.`

### Q031 Guest shutdown evidence

- 원문: `운영 체제가 내부에서 종료된 흔적이 있어?`
- 변형 A: `게스트 OS 안에서 종료가 시작됐다는 근거가 있나?`
- 변형 B: `이 리소스가 운영 체제 내부 명령으로 종료됐는지 확인해줘.`

### Q032 Guest-initiated shutdown

- Original: `Was the shutdown initiated inside the guest operating system?`
- Variant A: `Is there evidence that the guest OS initiated the shutdown?`
- Variant B: `Determine whether the shutdown came from inside the virtual machine.`

### Q033 Read authorization

- 원문: `왜 이 리소스 상태를 읽을 수 없어?`
- 변형 A: `이 리소스 상태 조회가 불가능한 이유를 알려줘.`
- 변형 B: `권한, 범위, 원본 중 무엇 때문에 상태를 읽지 못했어?`

### Q034 Blocked health checks

- Original: `Which health checks were blocked by authorization or scope?`
- Variant A: `List health checks that could not run because of permissions or scope.`
- Variant B: `What authorization or scope limits blocked the health evidence reads?`

### Q035 Oldest evidence

- 원문: `지금 답변에 사용한 가장 오래된 데이터는 언제 것이야?`
- 변형 A: `이번 답변의 근거 중 가장 오래된 관측 시각을 알려줘.`
- 변형 B: `사용한 데이터 원본 가운데 제일 오래된 것은 언제 갱신됐어?`

### Q036 Stale evidence limits

- Original: `Which evidence is stale, and how does that limit the conclusion?`
- Variant A: `Identify stale evidence and explain the resulting limits on the answer.`
- Variant B: `What data is out of date, and which conclusions can no longer be confirmed?`

## Q037-Q060 Metrics, logs, traces, bounded queries

### Q037 CPU spikes

- 원문: `지난 한 시간 동안 CPU가 급증한 리소스를 찾아줘.`
- 변형 A: `최근 60분에 CPU 사용량이 비정상적으로 오른 리소스를 보여줘.`
- 변형 B: `지난 한 시간의 CPU 급증 리소스를 근거와 함께 찾아줘.`

### Q038 Abnormal CPU

- Original: `Which resources had abnormal CPU in the last hour?`
- Variant A: `Find managed resources with unusual CPU activity during the past 60 minutes.`
- Variant B: `Show resources whose CPU spiked in the previous hour.`

### Q039 Memory pressure

- 원문: `메모리 부족 징후와 영향을 받은 서비스를 보여줘.`
- 변형 A: `메모리 압박이 관측된 리소스와 영향받은 서비스를 알려줘.`
- 변형 B: `메모리 부족 신호가 있었던 대상과 서비스 영향을 찾아줘.`

### Q040 Before-and-after memory

- Original: `Compare memory pressure before and after the incident.`
- Variant A: `How did memory pressure change from before the incident to after it?`
- Variant B: `Compare the memory metric windows immediately before and after the incident.`

### Q041 Error spike correlation

- 원문: `오류율이 오른 시점과 가장 관련 있는 변경은 뭐야?`
- 변형 A: `오류율 급증과 시간상 가장 가까운 배포 또는 설정 변경을 찾아줘.`
- 변형 B: `어떤 변경이 오류율 상승 시점과 가장 강하게 연관돼 있어?`

### Q042 Error-rate and changes

- Original: `Correlate the error-rate spike with deployments and configuration changes.`
- Variant A: `Compare the error spike timeline against recent deployments and config updates.`
- Variant B: `Which deployment or configuration event is temporally associated with the higher error rate?`

### Q043 Failed requests by cause

- 원문: `최근 30분의 실패 요청을 원인별로 요약해줘.`
- 변형 A: `지난 30분 동안 실패한 요청을 작업과 결과 코드별로 묶어줘.`
- 변형 B: `최근 30분의 요청 실패를 확인 가능한 원인 그룹으로 정리해줘.`

### Q044 Failed request groups

- Original: `Find failed requests in the last 30 minutes and group them by cause.`
- Variant A: `Summarize request failures from the past 30 minutes by operation and result code.`
- Variant B: `Group recent failed requests by the strongest supported failure category.`

### Q045 Error signature timing

- 원문: `이 오류가 처음 나타난 로그 시점은 언제야?`
- 변형 A: `선택한 오류 시그니처가 최초로 관측된 시각을 알려줘.`
- 변형 B: `이 오류 패턴의 첫 로그 발생 시간을 찾아줘.`

### Q046 First and latest error

- Original: `When did this error signature first and most recently appear?`
- Variant A: `Find the earliest and latest timestamps for this exact error signature.`
- Variant B: `What are the first-seen and last-seen times of the selected error pattern?`

### Q047 Redacted log examples

- 원문: `민감한 값을 노출하지 말고 관련 로그 예시를 보여줘.`
- 변형 A: `비밀과 식별자를 가린 bounded 로그 샘플을 보여줘.`
- 변형 B: `관련 오류 로그를 민감 정보 없이 대표 예시만 제공해줘.`

### Q048 Bounded logs

- Original: `Show bounded representative logs with sensitive fields redacted.`
- Variant A: `Return a small set of representative log rows with secrets removed.`
- Variant B: `Provide redacted examples of the relevant logs without exposing sensitive values.`

### Q049 Slowest trace

- 원문: `가장 느린 분산 추적에서 병목 구간을 찾아줘.`
- 변형 A: `최장 지연 분산 trace의 가장 느린 span을 알려줘.`
- 변형 B: `가장 느린 추적을 선택해서 병목 span과 근거를 보여줘.`

### Q050 Trace bottleneck

- Original: `Show the slowest distributed trace and identify its bottleneck span.`
- Variant A: `Find the highest-latency trace and point out the span causing the delay.`
- Variant B: `Which span dominates latency in the slowest observed distributed trace?`

### Q051 Dependency latency

- 원문: `어떤 종속 서비스가 응답 지연을 만들었어?`
- 변형 A: `응답 시간 증가에 가장 크게 기여한 downstream 서비스는 뭐야?`
- 변형 B: `지연을 유발한 종속성 경로를 근거와 함께 알려줘.`

### Q052 Downstream contributor

- Original: `Which downstream dependency contributed most to latency?`
- Variant A: `Identify the dependent service with the largest latency contribution.`
- Variant B: `What downstream call is the strongest supported source of delay?`

### Q053 Slow database query

- 원문: `데이터베이스 CPU 상승과 관련된 느린 쿼리를 찾아줘.`
- 변형 A: `DB CPU 급증 시점에 관측된 느린 쿼리를 찾아줘.`
- 변형 B: `데이터베이스 CPU 증가를 설명할 수 있는 장시간 쿼리를 보여줘.`

### Q054 Query explaining CPU

- Original: `Which database query best explains the CPU spike?`
- Variant A: `Find the slow query most strongly associated with the database CPU increase.`
- Variant B: `What query evidence best accounts for the observed CPU spike?`

### Q055 Pod restarts

- 원문: `이 파드가 반복해서 재시작하는 이유가 뭐야?`
- 변형 A: `선택한 Pod의 반복 재시작 원인을 근거와 함께 알려줘.`
- 변형 B: `이 파드가 계속 다시 시작되는 이유를 확인해줘.`

### Q056 Pod restart or throttling

- Original: `Why is this pod restarting or being throttled?`
- Variant A: `What evidence explains the selected pod's restarts or CPU throttling?`
- Variant B: `Determine why this Kubernetes pod is repeatedly restarting or throttled.`

### Q057 Capacity for growth

- 원문: `현재 용량으로 트래픽 증가를 감당할 수 있어?`
- 변형 A: `관측된 부하 추세가 계속되면 현재 용량이 충분한가?`
- 변형 B: `지금의 리소스 용량으로 예상 트래픽 증가를 처리할 수 있는지 알려줘.`

### Q058 Capacity trend

- Original: `Does this service have enough capacity for the observed load trend?`
- Variant A: `Can the current capacity sustain the measured traffic growth?`
- Variant B: `Assess whether this service has sufficient headroom for the observed demand trend.`

### Q059 Safe KQL

- 원문: `지난 15분의 오류를 찾는 안전한 KQL을 실행해줘.`
- 변형 A: `최근 15분 오류만 조회하는 bounded read-only KQL을 실행해줘.`
- 변형 B: `변경 없이 지난 15분의 오류를 확인하는 안전한 로그 쿼리를 실행해줘.`

### Q060 Bounded error query

- Original: `Run a bounded read-only query for errors from the last 15 minutes.`
- Variant A: `Execute a safe KQL read limited to errors in the previous 15 minutes.`
- Variant B: `Query recent errors with a 15-minute window and no write operations.`

## Q061-Q080 Incident diagnosis

### Q061 Recent incident summary

- 원문: `가장 최근 인시던트를 핵심만 요약해줘.`
- 변형 A: `최근 인시던트의 상태와 핵심 영향을 짧게 정리해줘.`
- 변형 B: `최신 인시던트를 중요한 사실만 포함해서 요약해줘.`

### Q062 Incident impact and outcome

- Original: `Summarize the latest incident, impact, status, and outcome.`
- Variant A: `Give a concise summary of the newest incident with impact, current state, and result.`
- Variant B: `What happened in the latest incident, who was affected, and how did it end?`

### Q063 Verified root cause

- 원문: `이 인시던트의 검증된 근본 원인은 뭐야?`
- 변형 A: `선택한 인시던트에서 근거로 확인된 root cause를 알려줘.`
- 변형 B: `citation으로 검증된 인시던트 원인이 있으면 보여줘.`

### Q064 Strongest supported cause

- Original: `What is the strongest supported root cause for this incident?`
- Variant A: `Which root-cause hypothesis has the strongest evidence for the selected incident?`
- Variant B: `State the best-supported cause, or say that no grounded cause is confirmed.`

### Q065 Incident timeline

- 원문: `경고부터 복구까지 타임라인을 보여줘.`
- 변형 A: `첫 신호에서 복구 완료까지 인시던트 단계를 시간순으로 정리해줘.`
- 변형 B: `탐지, 판단, 조치, 복구 이벤트를 순서대로 보여줘.`

### Q066 Ordered incident timeline

- Original: `Build an ordered timeline from first signal through recovery.`
- Variant A: `Show the incident chronology from detection to final recovery.`
- Variant B: `List each observed incident phase in time order, ending with recovery.`

### Q067 Ranked hypotheses

- 원문: `가능한 원인을 근거와 반증까지 포함해 순위를 매겨줘.`
- 변형 A: `원인 가설을 supporting evidence와 contradictory evidence 기준으로 정렬해줘.`
- 변형 B: `가능한 원인을 우선순위로 보여주고 각 가설의 근거와 반증을 붙여줘.`

### Q068 Causal hypotheses

- Original: `Rank the causal hypotheses with supporting and contradictory evidence.`
- Variant A: `Order the possible causes by evidence strength and include counter-evidence.`
- Variant B: `Compare incident hypotheses using both supporting facts and facts against them.`

### Q069 Similar incidents

- 원문: `이전에도 같은 문제가 있었고 무엇이 효과가 있었어?`
- 변형 A: `비슷한 과거 인시던트와 실제로 성공한 복구 방법을 찾아줘.`
- 변형 B: `이 문제와 유사한 사례가 있었는지, 어떤 조치가 검증됐는지 알려줘.`

### Q070 Prior successful recovery

- Original: `Has this happened before, and which prior recovery actually worked?`
- Variant A: `Find similar resolved incidents and identify the recovery with verified success.`
- Variant B: `Which past incident matches this one, and what proven action resolved it?`

### Q071 Customer and SLO impact

- 원문: `이 장애가 사용자와 서비스 수준 목표에 미친 영향은 뭐야?`
- 변형 A: `선택한 인시던트의 고객 영향과 SLO 영향을 근거로 설명해줘.`
- 변형 B: `사용자, 서비스, 서비스 수준 목표에 관측된 영향을 정리해줘.`

### Q072 Quantified impact

- Original: `Quantify the customer and service-level impact of this incident.`
- Variant A: `What measured customer impact and SLO impact did the incident cause?`
- Variant B: `Summarize the incident's service impact using only observed quantities.`

### Q073 Safest next action

- 원문: `지금 가장 먼저 확인하거나 완화해야 할 것은 뭐야?`
- 변형 A: `현재 근거에서 가장 안전하고 가치가 높은 다음 단계를 제안해줘.`
- 변형 B: `지금 우선 확인할 항목과 안전한 완화 순서를 알려줘.`

### Q074 Highest-value next step

- Original: `What is the safest highest-value next step?`
- Variant A: `Recommend the next action with the best value and lowest supported risk.`
- Variant B: `What should be checked or mitigated first, given the current evidence?`

### Q075 Consumed evidence

- 원문: `그 결론을 뒷받침하는 증거만 보여줘.`
- 변형 A: `이전 결론에 실제로 사용된 evidence만 나열해줘.`
- 변형 B: `추가 추론 없이 결론이 소비한 근거만 보여줘.`

### Q076 Evidence only

- Original: `Show only the evidence consumed by the conclusion.`
- Variant A: `List the exact evidence references used for the prior conclusion and nothing else.`
- Variant B: `Return only the observed facts that supported the previous answer.`

### Q077 Remaining unknowns

- 원문: `아직 확인하지 못한 부분과 필요한 추가 증거는 뭐야?`
- 변형 A: `현재 결론에서 미확정인 사항과 이를 해결할 evidence를 알려줘.`
- 변형 B: `무엇이 아직 unknown이고 어떤 원본을 더 확인해야 해?`

### Q078 Evidence needed

- Original: `What remains unknown, and which evidence would resolve it?`
- Variant A: `Separate unresolved questions from the additional evidence needed for each one.`
- Variant B: `Which conclusions are still uncertain, and what data would confirm them?`

### Q079 Deep investigation

- 원문: `이 문제를 깊이 조사하고 진행 단계를 알려줘.`
- 변형 A: `bounded deep investigation을 시작하고 각 evidence phase를 보여줘.`
- 변형 B: `이 이슈를 단계별로 조사하면서 현재 진행 상태를 보고해줘.`

### Q080 Investigation phases

- Original: `Start a bounded deep investigation and report each evidence phase.`
- Variant A: `Investigate this issue within a fixed scope and show progress by phase.`
- Variant B: `Run a bounded investigation and report the evidence collected at each stage.`

## Q081-Q090 Topology and reachability

### Q081 Application dependencies

- 원문: `애플리케이션에서 데이터베이스까지 의존 관계를 보여줘.`
- 변형 A: `선택한 앱에서 DB까지 연결된 dependency 경로를 그려줘.`
- 변형 B: `애플리케이션과 데이터베이스 사이의 의존 리소스를 방향과 함께 보여줘.`

### Q082 Dependency map

- Original: `Map the dependencies from the application to its database.`
- Variant A: `Trace the directed dependency path between the selected app and database.`
- Variant B: `Show the resource relationships connecting this application to its database.`

### Q083 End-to-end reachability

- 원문: `앱에서 데이터베이스까지 실제로 통신할 수 있어?`
- 변형 A: `선택한 애플리케이션이 DB endpoint까지 도달 가능한지 확인해줘.`
- 변형 B: `앱과 데이터베이스 사이의 실제 네트워크 연결을 bounded probe로 확인해줘.`

### Q084 Application to database path

- Original: `Can the application reach the database end to end?`
- Variant A: `Verify end-to-end network reachability from the selected app to its database.`
- Variant B: `Is the complete application-to-database path reachable based on an active probe?`

### Q085 NSG inbound ports

- 원문: `이 네트워크 보안 그룹이 허용하는 인바운드 포트는 뭐야?`
- 변형 A: `선택한 NSG의 허용 inbound rule과 포트를 보여줘.`
- 변형 B: `이 네트워크 보안 그룹에서 인바운드로 열려 있는 포트를 알려줘.`

### Q086 Inbound network policy

- Original: `Which inbound ports are allowed by this network security group?`
- Variant A: `List allowed inbound rules and destination ports for the selected NSG.`
- Variant B: `What inbound traffic does this network security group permit?`

### Q087 VNet peering

- 원문: `이 가상 네트워크의 피어링 상태와 제한을 알려줘.`
- 변형 A: `선택한 VNet의 peering 방향, 상태, 구성 한계를 보여줘.`
- 변형 B: `이 가상 네트워크가 어떤 네트워크와 피어링됐고 제약은 무엇인지 알려줘.`

### Q088 Peering direction and limits

- Original: `Show this virtual network's peerings, direction, and configuration limits.`
- Variant A: `List peerings for the selected VNet with state, direction, and known limits.`
- Variant B: `What networks are peered with this VNet, and what configuration constraints apply?`

### Q089 Database impact scope

- 원문: `이 데이터베이스가 실패하면 어떤 서비스가 영향을 받아?`
- 변형 A: `선택한 DB 장애의 bounded impact scope를 dependency 기준으로 보여줘.`
- 변형 B: `이 데이터베이스에 의존해 영향받을 수 있는 서비스를 알려줘.`

### Q090 Bounded impact scope

- Original: `What is the bounded impact scope if this database fails?`
- Variant A: `List services within the verified blast radius of the selected database.`
- Variant B: `Which dependent resources could be affected by a failure of this database?`

## Q091-Q104 Proposal, execution context, cancellation

### Q091 Safe proposal only

- 원문: `실행하지 말고 안전한 완화 방안만 제안해줘.`
- 변형 A: `변경은 수행하지 말고 근거 있는 mitigation proposal만 만들어줘.`
- 변형 B: `실행 없이 검토 가능한 안전한 완화 제안을 보여줘.`

### Q092 Mitigation without execution

- Original: `Propose a mitigation without executing any change.`
- Variant A: `Prepare a safe mitigation proposal, but do not apply it.`
- Variant B: `Recommend a bounded recovery action in proposal-only mode.`

### Q093 Proposal safety fields

- 원문: `제안의 영향 범위, 중지 조건, 롤백 방법을 보여줘.`
- 변형 A: `이 proposal의 blast-radius limit, stop condition, dry run, rollback을 정리해줘.`
- 변형 B: `제안된 작업이 안전한 이유를 영향 범위와 복구 절차로 설명해줘.`

### Q094 Proposal safeguards

- Original: `Show the proposal's impact limit, stop condition, dry run, and rollback.`
- Variant A: `List the safety controls attached to this proposal, including rollback and what-if.`
- Variant B: `Explain the proposed action's bounded scope, stop rule, dry run, and recovery path.`

### Q095 Human approval

- 원문: `이 변경에 사람 승인이 필요한 이유와 승인자를 알려줘.`
- 변형 A: `왜 이 action이 human approval 대상이고 누가 승인할 수 있어?`
- 변형 B: `승인 필요성, 승인 역할, 실행 주체를 분리해서 알려줘.`

### Q096 Approval authority

- Original: `Why does this action require human approval, and who may approve it?`
- Variant A: `Explain the approval requirement and the authorized approver role for this action.`
- Variant B: `Who can approve this change, and why must approval remain separate from execution?`

### Q097 Governed execution

- 원문: `승인된 완화 작업을 실행하고 진행 상황을 보여줘.`
- 변형 A: `exact approved action이 있다면 governed progress를 보여줘. 새 실행은 만들지 마.`
- 변형 B: `승인된 action context의 실행 상태를 단계별로 확인해줘.`

### Q098 Approved mitigation progress

- Original: `Execute the approved mitigation and stream its governed progress.`
- Variant A: `For the exact approved action, show governed execution progress without creating a new action.`
- Variant B: `Display the lifecycle of the selected approved mitigation under its existing action context.`

### Q099 Outcome verification

- 원문: `작업 후 문제가 해결됐는지 어떤 기준으로 확인했어?`
- 변형 A: `선택한 action의 terminal post-check와 recovery criteria를 보여줘.`
- 변형 B: `완화 작업 성공을 판단한 effect verification 근거를 알려줘.`

### Q100 Recovery criteria

- Original: `Verify the mitigation outcome against explicit recovery criteria.`
- Variant A: `Show whether the selected action passed its post-change recovery checks.`
- Variant B: `Compare the mitigation result with the recorded success and rollback criteria.`

### Q101 Idempotent retry

- 원문: `같은 실행 요청을 다시 보내도 중복 변경이 생기지 않아?`
- 변형 A: `선택한 action의 idempotency key가 재시도 중복을 막는지 보여줘.`
- 변형 B: `이 작업을 retry해도 두 번 적용되지 않는 근거를 알려줘.`

### Q102 Duplicate prevention

- Original: `Prove that retrying this action will not create a duplicate change.`
- Variant A: `Show the idempotency receipt that suppresses duplicate execution for this action.`
- Variant B: `How does the selected action prevent a second mutation when the request is retried?`

### Q103 Cancel investigation

- 원문: `진행 중인 조사를 취소하고 중단된 범위를 알려줘.`
- 변형 A: `active investigation을 중단하고 어떤 phase가 취소됐는지 보여줘.`
- 변형 B: `현재 대화 조사를 취소하되 action이나 approval은 변경하지 마.`

### Q104 Cancellation scope

- Original: `Cancel the active investigation and confirm what work stopped.`
- Variant A: `Stop the current conversational investigation and list the cancelled phases.`
- Variant B: `Interrupt the active investigation only, then report what was and was not cancelled.`

## Q105-Q120 Knowledge, memory, context, format, honesty

### Q105 Applicable runbook

- 원문: `이 문제와 관련된 런북 내용을 출처와 함께 알려줘.`
- 변형 A: `선택한 문제에 적용 가능한 검토 완료 런북과 source를 보여줘.`
- 변형 B: `현재 context에 맞는 trusted runbook이 있으면 citation과 함께 알려줘.`

### Q106 Runbook recommendation

- Original: `What does the applicable runbook recommend, with source citations?`
- Variant A: `Load the reviewed runbook that applies here and cite its trusted source.`
- Variant B: `Which governed runbook matches this context, and what does it recommend?`

### Q107 Knowledge source freshness

- 원문: `연결된 지식 원본과 마지막 갱신 시점을 보여줘.`
- 변형 A: `enabled knowledge source별 승인 상태와 last refresh를 알려줘.`
- 변형 B: `현재 사용할 수 있는 지식 원본이 언제 마지막으로 갱신됐는지 보여줘.`

### Q108 Authorized knowledge sources

- Original: `Which knowledge sources are connected, authorized, and fresh?`
- Variant A: `List enabled knowledge sources with authorization and freshness state.`
- Variant B: `Show which reviewed knowledge sources are connected and currently fresh.`

### Q109 Memory visibility

- 원문: `이 해결 방법을 기억할 때 무엇을 저장하고 누가 볼 수 있어?`
- 변형 A: `이전 검증 답변을 memory로 저장한다면 필드와 visibility가 어떻게 돼?`
- 변형 B: `이 해결책을 기억할 때 consent, provenance, 접근 범위를 설명해줘.`

### Q110 Durable memory contract

- Original: `What would be stored as durable memory, with consent and provenance?`
- Variant A: `Describe the durable memory fields, source turn, consent time, and visibility.`
- Variant B: `If I explicitly confirm memory, what is retained and who can read it?`

### Q111 Reusable learning

- 원문: `이 인시던트에서 학습한 내용과 재사용 조건은 뭐야?`
- 변형 A: `선택한 incident에서 검토되고 보존된 lesson과 적용 범위를 알려줘.`
- 변형 B: `이 사례에서 실제로 materialized된 학습과 reuse condition을 보여줘.`

### Q112 Reviewed and retained lesson

- Original: `What reusable lesson was learned, reviewed, and retained?`
- Variant A: `Show the materialized lesson from this incident and its reuse conditions.`
- Variant B: `Which reviewed lesson remains active and eligible for reuse?`

### Q113 Second resource follow-up

- 원문: `아까 두 번째로 말한 리소스 상태를 다시 확인해줘.`
- 변형 A: `이전 목록의 두 번째 리소스만 최신 상태로 다시 조회해줘.`
- 변형 B: `방금 답변에서 두 번째 항목의 상태를 재확인해줘.`

### Q114 Recheck prior result

- Original: `Recheck the second resource from the previous result.`
- Variant A: `Refresh the state of item two in the prior resource list.`
- Variant B: `Use the previous result set and verify the second resource again.`

### Q115 Ambiguous resource name

- 원문: `이름이 같은 리소스 중 어떤 것을 말하는지 먼저 물어봐.`
- 변형 A: `동일 이름 후보가 여러 개면 추측하지 말고 선택을 요청해줘.`
- 변형 B: `리소스 이름이 모호하면 후보를 보여주고 내가 고르게 해줘.`

### Q116 Ask for disambiguation

- Original: `Ask me to choose when multiple resources match equally.`
- Variant A: `If several resources have the same match score, request an explicit selection.`
- Variant B: `Do not guess between equal resource candidates; show them and ask me to choose.`

### Q117 Korean table reformat

- 원문: `같은 근거를 유지하면서 한국어 표로 간단히 답해줘.`
- 변형 A: `이전 verified answer의 evidence를 바꾸지 말고 한국어 표로 정리해줘.`
- 변형 B: `같은 citation을 사용해서 직전 답변을 짧은 한국어 표로 바꿔줘.`

### Q118 Concise table

- Original: `Give the same verified answer as a concise table.`
- Variant A: `Reformat the prior verified answer as a short table without changing evidence.`
- Variant B: `Keep the same evidence and present the previous answer in a concise table.`

### Q119 Partial source failure

- 원문: `한 데이터 원본이 실패해도 확인된 사실과 한계를 구분해줘.`
- 변형 A: `실패한 source를 다른 근거로 대체하지 말고 known facts와 limits를 나눠줘.`
- 변형 B: `일부 원본이 unavailable일 때 확인된 내용과 미확정 내용을 분리해줘.`

### Q120 Failure honesty

- Original: `Answer with supported facts and explicit limits when one source is unavailable.`
- Variant A: `Separate verified facts from evidence gaps when a required source fails.`
- Variant B: `Do not substitute another authority for the missing source; state facts and limits separately.`

## 완료 체크

- QID마다 원문 1회, 변형 A 1회, 변형 B 1회를 서로 다른 새 대화에서 실행합니다.
- 총 target prompt 실행 수는 360회입니다.
- context-dependent 문항의 positive path를 추가하면 선행 프롬프트 실행 수는 별도로 증가합니다.
- fresh session에서 explicit hold가 나온 경우 실패로 간주하지 않습니다. reason code와 authority가 해당
  context 또는 evidence gap을 정확히 설명하는지 확인합니다.
- verified 답변은 server-owned authority, evidence reference, check count를 확인합니다.
- 실행 또는 승인 질문은 exact governed context가 없을 때 반드시 unverified hold여야 합니다.
