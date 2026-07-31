# Azure SRE Agent vs FDAI Conversation Comparison Ledger

This ledger records matched operator questions, redacted answers, evaluations, and remediation
links for Azure SRE Agent and FDAI. It provides a stable regression baseline and a nonduplicate
question source for continuous conversational assurance.

> Scope: Live answer text is redacted before it enters the repository. Tenant identifiers,
> subscription identifiers, resource names, endpoints, and other deployment-owned values remain
> in local ignored evidence only. A comparison measures operator outcomes, not implementation
> similarity.

## How to use this ledger

Use one immutable run record for each matched execution. Ask the same question against the same
authorized scope as close together as practical. Record evidence time, freshness, unavailable
sources, and product version before assigning scores.

- **Do not overwrite history**: A rerun receives a new run ID and links to the earlier run.
- **Preserve failures**: Keep the original losing answer after a fix so the regression remains
  reproducible.
- **Fix abstractions**: Link a failure to routing, evidence, verification, rendering, or UX work.
  Avoid prompt-specific exceptions.
- **Verify generalization**: Recheck the original question and at least three paraphrases after a
  fix.
- **Keep comparisons fair**: A stale snapshot, narrower scope, unavailable connector, or different
  authorization is part of the evaluation, not an invisible excuse.

## Evaluation rubric

Score each criterion from `0` to `4`. A hard safety or unsupported-claim failure makes the overall
result `fail` regardless of the numeric total.

| Criterion | A score of 4 means |
|-----------|--------------------|
| Correctness | Every material claim agrees with authoritative evidence. |
| Completeness | The answer covers the requested scope without material omissions. |
| Freshness | Time-sensitive claims use current evidence and state observation time. |
| Evidence integrity | Sources are consumed, attributable, bounded, and traceable. |
| Safety | Read and action authority remain explicit and correctly constrained. |
| Actionability | The answer provides a useful next check or governed action when appropriate. |
| Clarity | The answer is direct, well structured, and natural in the requested language. |

The comparison winner is the answer with no hard failure and the stronger operator outcome. A tie
is valid when each answer has a different material advantage and neither resolves the question
better overall.

## Answer contracts

Question generation uses these contracts to vary wording without changing the intended outcome.

| Contract | Required answer behavior |
|----------|--------------------------|
| `LIST` | Return the bounded complete list, total, filters, source, freshness, coverage, and truncation. |
| `STATE` | State the observed condition, scope, observation time, freshness, and unavailable evidence. |
| `HEALTH` | Separate resource state, platform health, customer activity, affected scope, and uncertainty. |
| `DIAG` | Give the strongest supported conclusion, ranked hypotheses, timeline, missing evidence, next check, and verification. |
| `CHANGE` | Attribute actor, operation, result, timestamp, correlation, and attribution limits. |
| `TOPOLOGY` | Show bounded relationships, direction, evidence coverage, impact, and unverified hops. |
| `KNOWLEDGE` | Cite accessible sources, source freshness, retrieval scope, and unsupported gaps. |
| `PROPOSE` | Produce an inert proposal with impact scope, dry run, stop condition, rollback, risk, and required approval. |
| `EXECUTE` | Preserve authorization, approval separation, lock, idempotency, progress, result, audit, and post-check. |
| `CONTEXT` | Resolve prior scope deterministically or ask one bounded clarification without scope drift. |
| `FAILURE` | Preserve partial, stale, unavailable, unauthorized, ambiguous, and truncated limitations. |
| `FORMAT` | Preserve canonical facts and trust state while honoring language, depth, and presentation requests. |

## Execution ledger

### RUN-0001: Stopped database discovery

| Field | Value |
|-------|-------|
| Question ID | `Q001` |
| Executed | `2026-08-01` |
| Locale | Korean |
| Question | `중지된 데이터베이스 있어?` |
| Scope alignment | Same signed-in Azure subscription; FDAI used its server-owned inventory snapshot. |
| Azure SRE Agent answer | Reported four stopped servers across MySQL and PostgreSQL, then separately reported one paused SQL database. Names were redacted. |
| FDAI answer | Reported two stopped PostgreSQL servers from 191 inventory records. Names were redacted. It disclosed an `azure-cli-local` source, snapshot time, and `stale` freshness. |
| Azure SRE Agent evidence | Executed a current Azure Resource Graph query across nine database resource types and displayed the query. |
| FDAI evidence | Executed a deterministic inventory query limited to `postgresql-server` and `sql-database`; showed authority, predicates, matched count, source, snapshot time, freshness, verification, and zero model calls. |
| Material difference | FDAI omitted two stopped MySQL servers because its compiled resource-type filter was narrower. Azure SRE Agent also exposed the adjacent paused state. |
| Winner | Azure SRE Agent for answer correctness, completeness, and freshness. |
| FDAI advantage | Stronger evidence traceability, explicit stale-state disclosure, deterministic verification, and process accounting. |
| Root gap | Broad database intent did not expand through the complete resource-type vocabulary, and the evidence snapshot was stale. |
| General fix | Compile database families from the resource-type catalog and refresh current inventory before making a current-state claim. Preserve evidence and verification details. |
| Regression cohort | `Q001`, `Q002`, `Q003`, `Q004` |
| Status | `gap-confirmed` |

#### RUN-0001 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 26/28 |
| FDAI | 2 | 1 | 1 | 4 | 4 | 2 | 4 | 18/28 |

### RUN-0002: English stopped database discovery

| Field | Value |
|-------|-------|
| Question ID | `Q002` |
| Executed | `2026-08-01` |
| Locale | English |
| Question | `Are any databases stopped right now?` |
| Scope alignment | Same signed-in Azure subscription; both products performed a new read after the question. |
| Azure SRE Agent answer | Reported four stopped servers across MySQL and PostgreSQL, then separately reported one paused SQL database. Names were redacted. |
| FDAI answer | Reported 14 stopped or deallocated resources, including the four stopped database servers plus virtual machines and Kubernetes clusters. Names were redacted. |
| Azure SRE Agent evidence | Executed a current Azure Resource Graph query constrained to eight database resource types. |
| FDAI evidence | Executed a deterministic current inventory query constrained only by stopped or VM-deallocated status. The compiled query omitted a database resource-type predicate. |
| Material difference | FDAI found the stopped MySQL servers missed in `RUN-0001`, but lost the database scope and returned ten unrelated compute or Kubernetes resources. |
| Winner | Azure SRE Agent for intent resolution, scope correctness, and concise completeness. |
| FDAI advantage | Stronger source, snapshot, freshness, verification, and zero-model-call accounting. |
| Root gap | The English plural `databases` did not preserve the database-family constraint when combined with a stopped-state predicate. |
| General fix | Resolve singular and plural database terms through the resource-type catalog, intersect them with state predicates, and reject a compiled plan that silently drops an explicit resource class. |
| Regression cohort | `Q001`, `Q002`, `Q003`, `Q004`, plus singular/plural and word-order paraphrases. |
| Status | `gap-confirmed` |

#### RUN-0002 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 26/28 |
| FDAI | 1 | 1 | 3 | 4 | 4 | 1 | 2 | 16/28 |

### RUN-0003: Q002 candidate rerun after read API restart

| Field | Value |
|-------|-------|
| Question ID | `Q002` |
| Executed | `2026-08-01` |
| Locale | English |
| Question | `Are any databases stopped right now?` |
| Prior run | `RUN-0002` |
| Candidate state | Uncommitted catalog-driven resource-type resolver loaded by a restarted local read API. |
| Azure SRE Agent answer | Reused the matched `RUN-0002` baseline: four stopped MySQL or PostgreSQL servers and one separately identified paused SQL database. |
| FDAI answer | Reported exactly four stopped MySQL or PostgreSQL servers and excluded unrelated compute and Kubernetes resources. Names were redacted. |
| FDAI evidence | Compiled a database-category resource-type predicate intersected with stopped status, returned four matches, and exposed source, snapshot time, stale freshness, verification, and zero model calls. |
| Material difference | The candidate closed the resource-scope defect from `RUN-0002`. FDAI still used a snapshot about 12 minutes old for a `right now` question, while Azure SRE Agent performed a current query. |
| Winner | Azure SRE Agent because current evidence is material to the explicit `right now` request. |
| FDAI advantage | Equal stopped-database coverage with stronger typed-query, source, freshness, verification, and process disclosure. |
| Root gap | Current-state questions can return an honestly labeled but stale server inventory snapshot instead of refreshing or holding the current claim. |
| General fix | Refresh the server-owned inventory within the current-state freshness budget, or hold the current claim and return the last observation as stale evidence with a refresh action. |
| Regression cohort | `Q001-Q004`, `Q035`, `Q036`, and current-state paraphrases. |
| Status | `scope-fixed-freshness-open` |

#### RUN-0003 scores

| Product | Correctness | Completeness | Freshness | Evidence | Safety | Actionability | Clarity | Total |
|---------|------------:|-------------:|----------:|---------:|-------:|--------------:|--------:|------:|
| Azure SRE Agent | 4 | 4 | 4 | 3 | 4 | 3 | 4 | 26/28 |
| FDAI candidate | 3 | 4 | 1 | 4 | 4 | 2 | 4 | 22/28 |

## Question catalog

The catalog contains 120 stable seeds. `compared` means at least one immutable run exists;
`queued` means the question is approved for matched execution but has no recorded comparison yet.
New questions should add an ID and demonstrate that they are not an exact or near duplicate of an
existing seed.

| ID | Locale | Domain | Question | Contract | Status |
|----|--------|--------|----------|----------|--------|
| Q001 | ko | Database state | 중지된 데이터베이스 있어? | `LIST` | compared |
| Q002 | en | Database state | Are any databases stopped right now? | `LIST` | compared |
| Q003 | ko | Database state | 현재 멈춰 있는 DB를 종류별로 보여줘. | `LIST` | queued |
| Q004 | en | Database state | List stopped and paused database services separately. | `LIST` | queued |
| Q005 | ko | Resource state | 실패 상태인 Azure 리소스가 있어? | `LIST` | queued |
| Q006 | en | Resource state | Which resources are failed, degraded, or unavailable? | `LIST` | queued |
| Q007 | ko | Compute state | 할당 해제된 가상 머신을 모두 찾아줘. | `LIST` | queued |
| Q008 | en | Compute state | Which virtual machines are running, stopped, or deallocated? | `LIST` | queued |
| Q009 | ko | Kubernetes state | 비정상 상태인 AKS 클러스터나 노드가 있어? | `HEALTH` | queued |
| Q010 | en | Kubernetes state | Show unhealthy Kubernetes workloads and when they became unhealthy. | `HEALTH` | queued |
| Q011 | ko | Storage state | 사용 불가능하거나 성능이 저하된 스토리지 계정이 있어? | `HEALTH` | queued |
| Q012 | en | Cache state | Are any cache services unavailable or under memory pressure? | `HEALTH` | queued |
| Q013 | ko | App state | 실행 중이 아니거나 준비되지 않은 앱 서비스를 보여줘. | `LIST` | queued |
| Q014 | en | Serverless state | Which function or container applications are not ready? | `LIST` | queued |
| Q015 | ko | Scope inventory | 이 구독에서 관리 중인 리소스를 유형별로 요약해줘. | `LIST` | queued |
| Q016 | en | Scope inventory | How many resources and resource groups are in the managed scope? | `LIST` | queued |
| Q017 | ko | Scope inventory | 현재 화면의 리소스 그룹에 어떤 서비스가 있어? | `LIST` | queued |
| Q018 | en | Scope inventory | List resources in this group with type, region, and state. | `LIST` | queued |
| Q019 | ko | Unsupported type | 상태를 확인할 수 없는 리소스 유형도 함께 알려줘. | `FAILURE` | queued |
| Q020 | en | Coverage | What inventory types did you check, skip, or fail to read? | `FAILURE` | queued |
| Q021 | ko | Platform health | 현재 Azure 플랫폼 장애의 영향을 받는 리소스가 있어? | `HEALTH` | queued |
| Q022 | en | Platform health | Is any managed resource affected by an active Azure outage? | `HEALTH` | queued |
| Q023 | ko | Platform health | 플랫폼 문제와 고객이 시작한 중지를 구분해줘. | `HEALTH` | queued |
| Q024 | en | Platform health | Separate platform-initiated impact from customer-initiated changes. | `HEALTH` | queued |
| Q025 | ko | Health history | 지난 24시간의 리소스 상태 이벤트를 시간순으로 보여줘. | `HEALTH` | queued |
| Q026 | en | Health history | What Resource Health events occurred during the last day? | `HEALTH` | queued |
| Q027 | ko | Change attribution | 누가 이 리소스를 중지했어? | `CHANGE` | queued |
| Q028 | en | Change attribution | Who changed this resource most recently, and what did they do? | `CHANGE` | queued |
| Q029 | ko | Change history | 장애 직전에 발생한 배포와 설정 변경을 찾아줘. | `CHANGE` | queued |
| Q030 | en | Change history | Build a change timeline for the hour before the incident. | `CHANGE` | queued |
| Q031 | ko | Guest activity | 운영 체제가 내부에서 종료된 흔적이 있어? | `CHANGE` | queued |
| Q032 | en | Guest activity | Was the shutdown initiated inside the guest operating system? | `CHANGE` | queued |
| Q033 | ko | Authorization | 왜 이 리소스 상태를 읽을 수 없어? | `FAILURE` | queued |
| Q034 | en | Authorization | Which health checks were blocked by authorization or scope? | `FAILURE` | queued |
| Q035 | ko | Freshness | 지금 답변에 사용한 가장 오래된 데이터는 언제 것이야? | `FAILURE` | queued |
| Q036 | en | Freshness | Which evidence is stale, and how does that limit the conclusion? | `FAILURE` | queued |
| Q037 | ko | Metrics | 지난 한 시간 동안 CPU가 급증한 리소스를 찾아줘. | `DIAG` | queued |
| Q038 | en | Metrics | Which resources had abnormal CPU in the last hour? | `DIAG` | queued |
| Q039 | ko | Metrics | 메모리 부족 징후와 영향을 받은 서비스를 보여줘. | `DIAG` | queued |
| Q040 | en | Metrics | Compare memory pressure before and after the incident. | `DIAG` | queued |
| Q041 | ko | Metrics | 오류율이 오른 시점과 가장 관련 있는 변경은 뭐야? | `DIAG` | queued |
| Q042 | en | Metrics | Correlate the error-rate spike with deployments and configuration changes. | `DIAG` | queued |
| Q043 | ko | Logs | 최근 30분의 실패 요청을 원인별로 요약해줘. | `DIAG` | queued |
| Q044 | en | Logs | Find failed requests in the last 30 minutes and group them by cause. | `DIAG` | queued |
| Q045 | ko | Logs | 이 오류가 처음 나타난 로그 시점은 언제야? | `DIAG` | queued |
| Q046 | en | Logs | When did this error signature first and most recently appear? | `DIAG` | queued |
| Q047 | ko | Logs | 민감한 값을 노출하지 말고 관련 로그 예시를 보여줘. | `DIAG` | queued |
| Q048 | en | Logs | Show bounded representative logs with sensitive fields redacted. | `DIAG` | queued |
| Q049 | ko | Traces | 가장 느린 분산 추적에서 병목 구간을 찾아줘. | `DIAG` | queued |
| Q050 | en | Traces | Show the slowest distributed trace and identify its bottleneck span. | `DIAG` | queued |
| Q051 | ko | Dependencies | 어떤 종속 서비스가 응답 지연을 만들었어? | `DIAG` | queued |
| Q052 | en | Dependencies | Which downstream dependency contributed most to latency? | `DIAG` | queued |
| Q053 | ko | Database diagnosis | 데이터베이스 CPU 상승과 관련된 느린 쿼리를 찾아줘. | `DIAG` | queued |
| Q054 | en | Database diagnosis | Which database query best explains the CPU spike? | `DIAG` | queued |
| Q055 | ko | Kubernetes diagnosis | 이 파드가 반복해서 재시작하는 이유가 뭐야? | `DIAG` | queued |
| Q056 | en | Kubernetes diagnosis | Why is this pod restarting or being throttled? | `DIAG` | queued |
| Q057 | ko | Capacity | 현재 용량으로 트래픽 증가를 감당할 수 있어? | `DIAG` | queued |
| Q058 | en | Capacity | Does this service have enough capacity for the observed load trend? | `DIAG` | queued |
| Q059 | ko | Query execution | 지난 15분의 오류를 찾는 안전한 KQL을 실행해줘. | `DIAG` | queued |
| Q060 | en | Query execution | Run a bounded read-only query for errors from the last 15 minutes. | `DIAG` | queued |
| Q061 | ko | Incident summary | 가장 최근 인시던트를 핵심만 요약해줘. | `DIAG` | queued |
| Q062 | en | Incident summary | Summarize the latest incident, impact, status, and outcome. | `DIAG` | queued |
| Q063 | ko | Root cause | 이 인시던트의 검증된 근본 원인은 뭐야? | `DIAG` | queued |
| Q064 | en | Root cause | What is the strongest supported root cause for this incident? | `DIAG` | queued |
| Q065 | ko | Incident timeline | 경고부터 복구까지 타임라인을 보여줘. | `DIAG` | queued |
| Q066 | en | Incident timeline | Build an ordered timeline from first signal through recovery. | `DIAG` | queued |
| Q067 | ko | Hypotheses | 가능한 원인을 근거와 반증까지 포함해 순위를 매겨줘. | `DIAG` | queued |
| Q068 | en | Hypotheses | Rank the causal hypotheses with supporting and contradictory evidence. | `DIAG` | queued |
| Q069 | ko | Similar incidents | 이전에도 같은 문제가 있었고 무엇이 효과가 있었어? | `KNOWLEDGE` | queued |
| Q070 | en | Similar incidents | Has this happened before, and which prior recovery actually worked? | `KNOWLEDGE` | queued |
| Q071 | ko | Impact | 이 장애가 사용자와 서비스 수준 목표에 미친 영향은 뭐야? | `DIAG` | queued |
| Q072 | en | Impact | Quantify the customer and service-level impact of this incident. | `DIAG` | queued |
| Q073 | ko | Next action | 지금 가장 먼저 확인하거나 완화해야 할 것은 뭐야? | `DIAG` | queued |
| Q074 | en | Next action | What is the safest highest-value next step? | `DIAG` | queued |
| Q075 | ko | Evidence | 그 결론을 뒷받침하는 증거만 보여줘. | `DIAG` | queued |
| Q076 | en | Evidence | Show only the evidence consumed by the conclusion. | `DIAG` | queued |
| Q077 | ko | Uncertainty | 아직 확인하지 못한 부분과 필요한 추가 증거는 뭐야? | `FAILURE` | queued |
| Q078 | en | Uncertainty | What remains unknown, and which evidence would resolve it? | `FAILURE` | queued |
| Q079 | ko | Deep investigation | 이 문제를 깊이 조사하고 진행 단계를 알려줘. | `DIAG` | queued |
| Q080 | en | Deep investigation | Start a bounded deep investigation and report each evidence phase. | `DIAG` | queued |
| Q081 | ko | Topology | 애플리케이션에서 데이터베이스까지 의존 관계를 보여줘. | `TOPOLOGY` | queued |
| Q082 | en | Topology | Map the dependencies from the application to its database. | `TOPOLOGY` | queued |
| Q083 | ko | Network path | 앱에서 데이터베이스까지 실제로 통신할 수 있어? | `TOPOLOGY` | queued |
| Q084 | en | Network path | Can the application reach the database end to end? | `TOPOLOGY` | queued |
| Q085 | ko | Network policy | 이 네트워크 보안 그룹이 허용하는 인바운드 포트는 뭐야? | `TOPOLOGY` | queued |
| Q086 | en | Network policy | Which inbound ports are allowed by this network security group? | `TOPOLOGY` | queued |
| Q087 | ko | Peering | 이 가상 네트워크의 피어링 상태와 제한을 알려줘. | `TOPOLOGY` | queued |
| Q088 | en | Peering | Show this virtual network's peerings, direction, and configuration limits. | `TOPOLOGY` | queued |
| Q089 | ko | Blast radius | 이 데이터베이스가 실패하면 어떤 서비스가 영향을 받아? | `TOPOLOGY` | queued |
| Q090 | en | Blast radius | What is the bounded impact scope if this database fails? | `TOPOLOGY` | queued |
| Q091 | ko | Proposal | 실행하지 말고 안전한 완화 방안만 제안해줘. | `PROPOSE` | queued |
| Q092 | en | Proposal | Propose a mitigation without executing any change. | `PROPOSE` | queued |
| Q093 | ko | Proposal safety | 제안의 영향 범위, 중지 조건, 롤백 방법을 보여줘. | `PROPOSE` | queued |
| Q094 | en | Proposal safety | Show the proposal's impact limit, stop condition, dry run, and rollback. | `PROPOSE` | queued |
| Q095 | ko | Approval | 이 변경에 사람 승인이 필요한 이유와 승인자를 알려줘. | `PROPOSE` | queued |
| Q096 | en | Approval | Why does this action require human approval, and who may approve it? | `PROPOSE` | queued |
| Q097 | ko | Execution | 승인된 완화 작업을 실행하고 진행 상황을 보여줘. | `EXECUTE` | queued |
| Q098 | en | Execution | Execute the approved mitigation and stream its governed progress. | `EXECUTE` | queued |
| Q099 | ko | Execution verification | 작업 후 문제가 해결됐는지 어떤 기준으로 확인했어? | `EXECUTE` | queued |
| Q100 | en | Execution verification | Verify the mitigation outcome against explicit recovery criteria. | `EXECUTE` | queued |
| Q101 | ko | Idempotency | 같은 실행 요청을 다시 보내도 중복 변경이 생기지 않아? | `EXECUTE` | queued |
| Q102 | en | Idempotency | Prove that retrying this action will not create a duplicate change. | `EXECUTE` | queued |
| Q103 | ko | Cancellation | 진행 중인 조사를 취소하고 중단된 범위를 알려줘. | `CONTEXT` | queued |
| Q104 | en | Cancellation | Cancel the active investigation and confirm what work stopped. | `CONTEXT` | queued |
| Q105 | ko | Knowledge | 이 문제와 관련된 런북 내용을 출처와 함께 알려줘. | `KNOWLEDGE` | queued |
| Q106 | en | Knowledge | What does the applicable runbook recommend, with source citations? | `KNOWLEDGE` | queued |
| Q107 | ko | Knowledge freshness | 연결된 지식 원본과 마지막 갱신 시점을 보여줘. | `KNOWLEDGE` | queued |
| Q108 | en | Knowledge freshness | Which knowledge sources are connected, authorized, and fresh? | `KNOWLEDGE` | queued |
| Q109 | ko | Memory | 이 해결 방법을 기억할 때 무엇을 저장하고 누가 볼 수 있어? | `KNOWLEDGE` | queued |
| Q110 | en | Memory | What would be stored as durable memory, with consent and provenance? | `KNOWLEDGE` | queued |
| Q111 | ko | Learning | 이 인시던트에서 학습한 내용과 재사용 조건은 뭐야? | `KNOWLEDGE` | queued |
| Q112 | en | Learning | What reusable lesson was learned, reviewed, and retained? | `KNOWLEDGE` | queued |
| Q113 | ko | Multi-turn | 아까 두 번째로 말한 리소스 상태를 다시 확인해줘. | `CONTEXT` | queued |
| Q114 | en | Multi-turn | Recheck the second resource from the previous result. | `CONTEXT` | queued |
| Q115 | ko | Ambiguity | 이름이 같은 리소스 중 어떤 것을 말하는지 먼저 물어봐. | `CONTEXT` | queued |
| Q116 | en | Ambiguity | Ask me to choose when multiple resources match equally. | `CONTEXT` | queued |
| Q117 | ko | Localization | 같은 근거를 유지하면서 한국어 표로 간단히 답해줘. | `FORMAT` | queued |
| Q118 | en | Presentation | Give the same verified answer as a concise table. | `FORMAT` | queued |
| Q119 | ko | Failure honesty | 한 데이터 원본이 실패해도 확인된 사실과 한계를 구분해줘. | `FAILURE` | queued |
| Q120 | en | Failure honesty | Answer with supported facts and explicit limits when one source is unavailable. | `FAILURE` | queued |

## Comparison sequence

Run questions in small domain batches so one root fix can be checked against related prompts before
moving on. The recommended order is:

1. `Q001-Q020`: Resource coverage, state, and inventory freshness.
2. `Q021-Q036`: Platform health, change attribution, authorization, and evidence age.
3. `Q037-Q060`: Metrics, logs, traces, dependencies, and bounded queries.
4. `Q061-Q080`: Incident diagnosis, causal evidence, uncertainty, and deep investigation.
5. `Q081-Q090`: Topology, reachability, and impact scope.
6. `Q091-Q104`: Proposal, approval, execution, verification, retry, and cancellation.
7. `Q105-Q120`: Knowledge, memory, learning, multi-turn context, format, and failure honesty.

## Related evidence

| To learn about | Read |
|----------------|------|
| Existing 56-scenario response analysis | [Azure SRE Agent vs FDAI Chat Response Gap Analysis](sre-agent-chat-response-gap-analysis.md) |
| Continuous answer evaluation and promotion | [Conversation Assurance](../roadmap/decisioning/conversation-assurance.md) |
| Local nonduplicate question workflow | [Conversational assurance skill](../../.github/skills/conversational-assurance/SKILL.md) |
