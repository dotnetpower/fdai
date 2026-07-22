---
title: RCA 증거 수집 Runbook
description: 근본 원인 가설을 수락하기 전에 범위와 citation이 있는 evidence set을 구성하는 템플릿입니다.
translation_of: rca-evidence-collection.md
translation_source_sha: 4480d9b66dab37abfa3f605c47ef74c863a4817d
translation_revised: 2026-07-22
---

# RCA 증거 수집 Runbook

Root-cause analysis (RCA) hypothesis를 수락하거나 게시하기 전에 범위와 citation이 있는
evidence set을 구성할 때 이 runbook을 사용합니다. Collection과 interpretation을 구분하여
모든 causal claim을 알려진 source와 time으로 추적할 수 있게 합니다.

> Incident scope에 authorized된 evidence만 수집하세요. Secret 또는 raw restricted payload
> 대신 opaque reference와 hash를 저장합니다.

## 진입 기준

[Incident triage](incident-triage-ko.md)가 incident ID, affected scope, accountable owner,
evidence time range, next decision deadline을 설정한 뒤 시작합니다. Scope 또는 timeline이
크게 변경되면 collection을 반복합니다.

## 역할과 collection boundary

| 항목 | 필요한 값 |
|------|-----------|
| Investigation owner | Scope, budget, final evidence set을 책임지는 사람 |
| Reviewer | Source identity, citation, unsupported gap을 검증하는 사람 |
| Time boundary | 정당한 lead-in time을 포함한 start 및 end timestamp |
| Resource boundary | Included resource, dependency, region, explicit exclusion |
| Evidence budget | Source, query, volume, retention limit |
| Access boundary | Authorized identity와 handling requirement |

Collection boundary를 조용히 확장하지 않습니다. 추가 resource 또는 time range를 query하기
전에 수정된 boundary를 기록하고 승인합니다.

## Evidence inventory

| Evidence class | 수집할 내용 | Reliability check |
|----------------|-------------|-------------------|
| Event와 audit | 발견된 문제, state transition, 결정, approval, action | Producer, sequence, correlation ID, hash |
| Change | Deployment, configuration, catalog, policy, ownership update | Version, actor, scope, completion state |
| Metric | SLI, saturation, error, latency, dependency health | Source, aggregation, missing data, timestamp |
| Log와 trace | Correlated execution 및 request record | Clock, sampling, redaction, trace continuity |
| Inventory | 관련 시점의 resource state와 relationship | Snapshot time, source, completeness |
| Knowledge | Rule, runbook, prior incident, architecture reference | Version, approval state, provenance |

Source가 해당 record를 생성해야 했고 source health가 absence에 의미가 있음을 입증하는 경우에만
record가 없다는 사실을 evidence로 사용합니다.

## 수집 절차

1. **Boundary를 동결합니다.** Incident, target resource, time range, source allowlist,
	evidence budget, access scope를 기록합니다.
2. **Source health를 수집합니다.** Returned data를 해석하기 전에 clock, ingestion delay,
	retention, sampling, known gap을 검증합니다.
3. **Immutable reference를 수집합니다.** Correlated event, change, metric, log, trace,
	inventory, rule, approved knowledge reference를 수집합니다.
4. **Time을 normalize합니다.** Source timestamp를 보존하고 known clock offset을 기록합니다.
	Ordering을 강제하기 위해 timestamp를 다시 작성하지 않습니다.
5. **Chronology를 구성합니다.** Cause를 정렬하기 전에 supported fact를 정렬합니다.
	Gap과 conflicting record를 명시합니다.
6. **Hypothesis를 구성합니다.** 각 candidate cause에 supporting evidence, contradicting
	evidence, claim을 반증할 observation을 기록합니다.
7. **Citation을 test합니다.** 모든 claim이 supplied reference로 resolve되고 collection
	boundary 안에서 reference를 사용할 수 있었는지 확인합니다.
8. **Set을 review합니다.** Reviewer가 scope, handling, freshness, citation integrity,
	alternative, unresolved ambiguity를 확인합니다.

## Hypothesis record

Leading hypothesis와 alternative에 동일한 field를 사용합니다.

| Field | Content |
|-------|---------|
| Claim | 하나의 bounded causal statement입니다. |
| Supporting evidence | Claim confidence를 높이는 reference입니다. |
| Contradicting evidence | Confidence를 낮추거나 alternative를 지원하는 reference입니다. |
| Falsifier | Claim을 반증할 observation입니다. |
| Confidence | Basis가 포함된 configured confidence value입니다. |
| Gap | Conclusion에 영향을 주는 missing 또는 unreliable evidence입니다. |

Correlation만으로 causation으로 promote하지 않습니다. Incident 시작과 가까운 change는
mechanism과 evidence가 causal link를 지원할 때까지 candidate입니다.

## 중지 조건

Evidence가 scope를 벗어나거나 citation을 검증할 수 없거나 timestamp가 일치하지 않거나
source health를 알 수 없거나 provider response에 unvouched data가 포함될 수 있으면
중지합니다. Collection이 approved handling boundary를 벗어난 secret 또는 restricted
payload를 노출할 수 있는 경우에도 중지합니다.

Unsupported result는 unresolved hypothesis로 사람 검토에 전달합니다. Execution-eligible
mitigation으로 만들지 않습니다.

## Evidence package와 audit

Final package는 boundary, source inventory, source-health check, chronology, evidence
reference와 hash, hypothesis record, reviewer, confidence basis, unresolved gap을 포함합니다.
Collection start 및 end time을 기록하고 package version을 incident audit trail에 연결합니다.

## 완료 기준

모든 material claim에 verifiable citation이 있고 credible alternative가 기록되며 handling
rule이 충족되고 reviewer가 package를 수락하면 collection이 완료됩니다. Outcome은 supported
cause, disproved cause 또는 explicit unresolved result일 수 있습니다.

## 관련 runbook

| 다음 작업 | 문서 |
|-----------|------|
| Incident scope 또는 severity refresh | [Incident triage](incident-triage-ko.md) |
| Supported mitigation proposal 라우팅 | [Incident mitigation과 rollback](incident-mitigation-and-rollback-ko.md) |
| Final causal review 보존 | [Postmortem workflow](postmortem-workflow-ko.md) |
