# Inventory Query Evidence Hardening Review

이 문서는 Command Deck의 observed execution evidence를 35개 독립 반례로 비평하고 하드닝한
결과를 기록합니다. 범위는 inventory, subscription health, read investigation, Web SSE,
Slack, Teams, durable replay 및 Console persistence입니다.

> 결론: 실제 process invocation receipt가 있는 경우만 `input_kind=command`를 사용합니다.
> Server-owned read는 `input_kind=query`로 verifier가 승인한 canonical query를 그대로 표시합니다.
> Provider-specific command를 추정하거나 exit code를 만들지 않습니다.

## Design at a glance

기존 구현은 cached inventory 또는 REST/ARG read가 완료되면 질문과 유사한 Azure CLI command를
재구성했습니다. 이 command는 실제 실행된 작업이 아니었고 status, name, location, resource group,
query kind, activity lookback 및 workload authority를 손실할 수 있었습니다. 새 계약은 typed query와
actual command를 분리하고 Web, Slack, Teams 및 durable replay에서 같은 의미를 유지합니다.

## Critique rounds

| # | Severity | Critique | Hardening |
|---:|----------|----------|-----------|
| 1 | Critical | Cached inventory read를 live Azure CLI 실행처럼 표시했습니다. | Canonical query로 교체했습니다. |
| 2 | Critical | Activity Log read가 generic resource-list command로 표시됐습니다. | Activity source와 lookback을 query에 보존합니다. |
| 3 | Critical | Durable replay가 query/command 구분을 삭제했습니다. | `input_kind`를 serialize/deserialize합니다. |
| 4 | Critical | Query에 shell exit code 0을 만들었습니다. | Query는 exit code를 거부합니다. |
| 5 | Critical | Provider가 REST인지 ARG인지 모른 채 Azure CLI를 추정했습니다. | Provider command reconstruction을 제거했습니다. |
| 6 | High | Status predicate가 표시 command에서 누락됐습니다. | 전체 verified predicate를 query JSON에 보존합니다. |
| 7 | High | Resource type predicate가 일부 hardcoded branch에만 반영됐습니다. | Canonical `InventoryQuery`를 그대로 사용합니다. |
| 8 | High | Resource group predicate가 표시 command에서 누락됐습니다. | Query predicate에 lossless하게 유지합니다. |
| 9 | High | Location predicate가 표시 command에서 누락됐습니다. | Query predicate에 lossless하게 유지합니다. |
| 10 | High | Name `contains` predicate가 표시 command에서 누락됐습니다. | Operator와 value를 모두 유지합니다. |
| 11 | High | `count` kind인데 list command를 표시했습니다. | Query kind를 그대로 표시합니다. |
| 12 | High | `types` kind인데 grouping 없는 list command를 표시했습니다. | Query kind를 그대로 표시합니다. |
| 13 | High | `relationships` 답변을 단순 resource list로 설명했습니다. | Relationship kind를 query에 보존합니다. |
| 14 | High | Activity operation predicate가 표시되지 않았습니다. | Operation 및 event status predicate를 유지합니다. |
| 15 | High | Activity lookback이 표시되지 않았습니다. | Bounded `lookback_seconds`를 유지합니다. |
| 16 | High | Kubernetes workload evidence를 Azure resource command로 오인할 수 있었습니다. | Authority와 canonical operation을 분리합니다. |
| 17 | High | Subscription health pseudo-command가 실행 가능한 것처럼 보였습니다. | Server-owned query JSON으로 교체했습니다. |
| 18 | High | T2 recovery pseudo-command가 실행 가능한 것처럼 보였습니다. | Server-owned query JSON으로 교체했습니다. |
| 19 | High | Read investigation pseudo-command가 shell command처럼 보였습니다. | Typed intent query로 교체했습니다. |
| 20 | High | UI badge가 모든 input을 `TOOL`로 표시했습니다. | Query는 `QUERY`, command는 `TOOL`로 표시합니다. |
| 21 | High | Copy tooltip이 query에도 `Copy command`라고 표시했습니다. | `Copy query` / `쿼리 복사`를 추가했습니다. |
| 22 | High | Query result를 output log라고 표시했습니다. | `Query result` / `쿼리 결과`로 분리했습니다. |
| 23 | High | Slack fallback이 query를 Command라고 표시했습니다. | Query/Command label을 분리했습니다. |
| 24 | High | Slack block title도 query를 Command라고 표시했습니다. | Plain-text Query block을 사용합니다. |
| 25 | High | Teams는 input 종류를 표시하지 않았습니다. | FactSet에 Input을 추가했습니다. |
| 26 | High | Browser parser가 unknown input kind를 받아들일 수 있었습니다. | `command|query`만 허용합니다. |
| 27 | High | Browser persistence가 input kind를 검증하지 않았습니다. | Bounded enum과 query exit-code invariant를 검증합니다. |
| 28 | Medium | 과거 transcript에는 `inputKind`가 없어 replay가 깨질 수 있었습니다. | Missing 값은 backward-compatible command로 해석합니다. |
| 29 | Medium | Snapshot source와 freshness가 command에 없었습니다. | Query projection에 provenance를 포함합니다. |
| 30 | Medium | Active inventory view가 표시 command에 없었습니다. | Snapshot projection에 active view를 포함합니다. |
| 31 | Medium | Empty 또는 unavailable result에서 시도한 query가 사라졌습니다. | Query가 유효하면 status와 함께 유지합니다. |
| 32 | Medium | Truncation 경계가 command와 연결되지 않았습니다. | Bounded result summary에 `truncated`를 포함합니다. |
| 33 | Medium | Mixed PostgreSQL/Azure SQL 질문에서 command scope가 흔들렸습니다. | Type-specific command 생성을 제거했습니다. |
| 34 | Medium | Shell quoting과 KQL field validity를 보장할 수 없었습니다. | 실행하지 않은 shell text를 만들지 않습니다. |
| 35 | Medium | 실제 command와 reconstructed equivalent를 같은 schema로 구분할 수 없었습니다. | Channel-neutral `input_kind` contract를 추가했습니다. |

## Implemented hardening

| Area | Result |
|------|--------|
| Backend | `InventoryQuery.from_mapping(...).to_dict()`로 query를 재검증하고 JSON으로 렌더링합니다. |
| Wire | `input_kind`는 `command` 또는 `query`만 허용합니다. |
| Safety | Query는 exit code를 포함할 수 없고 sensitive-data scan과 size bound를 유지합니다. |
| Web | QUERY/TOOL badge, query/command copy tooltip, query result/output log label을 분리합니다. |
| Channels | Slack, Teams 및 fallback text가 Query/Command를 구분합니다. |
| Replay | Python durable response와 browser transcript가 input kind를 보존합니다. |
| Coverage | 20 inventory prompts, activity query, subscription health, read investigation 및 channel round-trip을 검증합니다. |

## Residual risk

- Provider receipt가 actual argv를 명시적으로 제공하는 future path만 `command`를 사용해야 합니다.
- Query JSON은 operator-facing reproduction command가 아니라 verified server operation evidence입니다.
- Raw subscription id, tenant id, resource id, credential 및 provider payload는 계속 표시하지 않습니다.
