---
title: Data Governance와 Privacy Evidence
translation_of: data-governance.md
translation_source_sha: faeba4063730f3262c9b764df5b727625dc49cd0
translation_revised: 2026-07-13
---
# Data Governance와 Privacy Evidence

이 문서는 FDAI의 data classification, minimization, lifecycle, residency, privacy evidence
contract를 정의합니다. 재사용 가능한 control model을 제공하며 각 production 포크는 customer
data를 upstream에 commit하지 않고 승인 값과 evidence를 기록합니다.

> **범위:** 이 문서는 certification 또는 완료된 privacy impact assessment가 아닙니다.
> 포크가 privacy owner, data owner, retention 값, model-provider 조건, 승인 assessment를
> `config/architecture-review.yaml`에 binding할 때까지 production 승인은 blocked입니다.

## 한눈에 보는 설계

FDAI는 가능한 경우 raw customer payload 대신 identifier와 derived operational fact를
저장합니다. Machine/audit record는 English를 유지하고 access는 role-scoped이며 transit와
at-rest encryption이 필요합니다. Model로 보내는 content는 trust boundary를 벗어나기 전에
redaction합니다.

## Data inventory

| Data class | 예 | 기본 처리 | System of record |
|------------|----|-----------|------------------|
| Event metadata | Event id, resource type, correlation id, normalized property | 최소화하고 ingress에서 secret을 거부합니다. | Event bus, 이후 audit/state store |
| Tool과 inventory output | Resource graph fact, policy result, deployment-plan fact | 결정과 evidence에 필요한 field만 유지합니다. | State store 또는 short-lived buffer |
| Audit record | Decision, actor id, tier, rule citation, idempotency/rollback reference | Append-only, tamper-evident, legal-hold capable | Audit ledger |
| Telemetry | Log, metric, trace, health/performance measurement | Telemetry는 sample/aggregate할 수 있지만 필수 audit entry는 sample하지 않습니다. | Log Analytics 또는 configured backend |
| Embedding과 pattern | 해결 incident와 승인 knowledge에서 파생한 vector | Model과 source를 versioning하고 secret/raw personal data embedding을 피합니다. | PostgreSQL + pgvector |
| Operator conversation | Question, verified tool call, grounded answer, proposal reference | Presentation text와 machine decision을 분리하고 승인 session retention을 적용합니다. | Operator-memory store |
| Governance artifact | Rule, assignment, exemption, override, ADR | Code로 versioning하고 review합니다. | Git |

## Classification과 access

포크는 각 class를 public, internal, confidential, restricted 같은 organization taxonomy에
mapping합니다. Data owner, 허용 principal, 승인 region, encryption profile, downstream
processor를 기록합니다. Classification이 없으면 가장 제한적인 configured class로 처리하고
model provider export를 차단합니다.

Access는 다음 규칙을 따릅니다.

- **Minimum permission:** Console은 projection을 읽으며 executor identity를 보유하지 않습니다.
- **Purpose limitation:** Provider는 선언된 operation에 필요한 field만 받습니다.
- **Secret propagation 방지:** Secret은 event, log, audit, prompt, fixture, evidence attachment에
  기록하지 않습니다.
- **Actor traceability:** Human/workload identity는 audit에서 stable object identifier를 사용합니다.
- **Break-glass visibility:** Emergency access는 time-bounded, alerted, reviewed 상태입니다.

## Lifecycle과 retention

포크는 모든 data class에 다음 field를 포함한 retention schedule을 유지합니다.

| Field | 요구 사항 |
|-------|-----------|
| Purpose | Operational, security, legal, training 또는 다른 승인 목적 |
| Active retention | Primary store에서 query 가능한 기간 |
| Archive retention | 기간, archive tier, restore expectation |
| Legal hold | Authority, hold marker, release process, immutable evidence |
| Deletion | Trigger, method, verification, downstream propagation |
| Backup inheritance | Backup expiry를 기다리는지 승인 key destruction을 사용하는지 |
| Review cadence | Owner와 다음 review date |

Azure day-zero telemetry 기본값은 30일입니다. Audit, conversation, embedding, customer record
retention은 이 값을 자동 상속하지 않습니다. 포크에서 값을 승인하고 production evidence
binding에 첨부해야 합니다.

## Privacy assessment

Privacy impact assessment는 다음을 기록합니다.

1. 시스템에 들어올 수 있는 data subject와 personal/customer-identifying field;
2. purpose, lawful basis, necessity, proportionality, minimization control;
3. event, state, telemetry, Git, ChatOps, model-provider boundary의 data flow;
4. region과 cross-border transfer constraint;
5. processor 조건, retention, training-use restriction, incident notification 조건;
6. 적용 가능한 access, correction, export, deletion, legal-hold 처리;
7. residual privacy risk, mitigation, approver, review date.

선택한 model-provider 조건에 맞게 payload를 충분히 redaction할 수 없으면 FDAI는 사람 검토로
보내고 전송하지 않습니다.

## Model과 embedding control

- Provider, publisher, model family/version, deployment region, retention 조건, submitted data의
  provider training 비활성 여부를 기록합니다.
- Model 또는 embedding call 전에 secret/personal-data redaction을 적용합니다.
- Prompt/tool input을 deterministic verdict와 audit authority에서 분리합니다.
- Source provenance, classification, model, deletion lineage와 함께 embedding을 versioning합니다.
- 승인 source가 삭제되고 legal hold가 없으면 derived vector를 재생성하거나 삭제합니다.

## Compliance evidence

Upstream catalog는 MCSB, CIS 또는 다른 standard control을 인용할 수 있지만 certification을
증명하지는 않습니다. Production 포크는 control id, implementation, automated/manual evidence,
owner, frequency, exception, residual risk가 포함된 crosswalk를 만듭니다. Unsupported 또는
not-applicable control은 명시적으로 남기며 조용히 누락하지 않습니다.

## Production gate

Production data/privacy readiness에는 다음이 필요합니다.

- 승인된 data inventory와 classification mapping;
- privacy/data owner binding;
- 승인된 retention, legal-hold, deletion, backup behavior;
- data-flow와 residency validation;
- model-provider와 subprocessor review;
- 완료된 privacy impact assessment;
- 선택한 customer profile의 compliance crosswalk;
- access review, deletion, incident-response test evidence.

이 artifact는 customer record이므로 포크 또는 governed evidence store에 둡니다. Upstream
manifest에는 required evidence key와 generic blocker state만 기록합니다.

## 다음 단계

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| ARB 결정과 evidence binding | [Architecture Review Board 패킷](architecture-review-board-ko.md) |
| Security와 threat model | [Security and Identity](security-and-identity-ko.md) |
| Human authorization | [User RBAC and Entra Identity](../interfaces/user-rbac-and-identity-ko.md) |
| Audit와 telemetry scale | [Hyperscale Cell Architecture](hyperscale-cell-architecture-ko.md) |
