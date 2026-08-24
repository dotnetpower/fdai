# Execution Authorization Ontology implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status (2026-07-31):** The strict requirement and assignment loaders,
> resolver-backed evaluator, hierarchical scope resolver, effective-access probe assembly,
> exact-plan grant validation, composition binder, role-filtered pending-grant browser projection,
> and revision-bound browser review are implemented. A deployment enables the gate by binding its context, identity,
> permission mapping, probe, and optional grant adapters. The development operations gateway maps
> `ops.scale-out` to the FinOps executor identity and rechecks one exact configured Uniform VM Scale
> Set before permitting a one-instance capacity increase. The mutation uses the fresh provider ETag
> as an `If-Match` precondition, and Core bounds long-running-operation polling with one cumulative
> deadline. This delivery mapping does not replace the capability, policy-assignment,
> effective-access, risk, or approval decisions.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Requirement, assignment, and policy loading | implemented | [`test_execution_authorization.py`](../../../services/core-control-plane/tests/rule_catalog/schema/test_execution_authorization.py) | Strict loading rejects duplicates, unknown references, and unsupported scope expressions before startup. |
| Conservative resolution and effective-access evaluation | implemented | [`test_resolver.py`](../../../services/core-control-plane/tests/core/execution_authorization/test_resolver.py), [`test_evaluator.py`](../../../services/core-control-plane/tests/core/execution_authorization/test_evaluator.py) | Prohibit dominates, constraints intersect, and missing or conflicting evidence never authorizes. |
| Exact grant lifecycle and separation of duties | implemented | [`test_grant_request.py`](../../../services/core-control-plane/tests/core/execution_authorization/test_grant_request.py) | Approval, apply, verification, expiry, revocation, idempotency, and distinct actors are covered by focused checks. |
| Control-loop and direct-executor integration | implemented | [`test_unified_control_loop.py`](../../../services/core-control-plane/tests/pipeline/test_unified_control_loop.py), [`test_direct_api_executor.py`](../../../services/core-control-plane/tests/core/executor/test_direct_api_executor.py) | Authorization remains an independent fail-closed decision before ordinary risk and dispatch authority. |
| Rule-governance ordering boundary | implemented | `runtime/control_loop.py`; `core/control_loop/_process.py`; focused T0 governance pipeline tests | Assignment effects and exemptions can observe, hold, or deny before dispatch. An enforcing remediation still enters execution authorization and cannot gain provider access from governance state. |
| Role-filtered pending-grant browser projection | implemented | [`postgres_iam.py`](../../../services/operator-service/src/fdai_operator_service/postgres_iam.py), [`test_operator_service_postgres.py`](../../../services/operator-service/tests/test_operator_service_postgres.py); focused Operator suite passed 394 cases with 1 skipped and `GET /access-grants/stream` returned 200 on an authenticated local session | The Operator reads the authoritative `execution-authorization:grant-request:` records and filters them by the authenticated reviewer before projecting. A requester never sees their own request, and the browser record still omits requester, executor identity, provider mapping, decision, and apply-plan digests. |
| Browser review authority and receipt fidelity | implemented | [`postgres_iam.py`](../../../services/operator-service/src/fdai_operator_service/postgres_iam.py), [`test_operator_service_postgres.py`](../../../services/operator-service/tests/test_operator_service_postgres.py); focused Operator suite passed 394 cases with 1 skipped | The decision path refuses an unknown, non-pending, expired, self-approved, or wrong-role request before anything is queued, fences each decision per request, revision, and reviewer, and reports the quorum, approval count, and revision recorded on the authoritative request. |
| Deployment policy, identity, and provider bindings | not-applicable | [Extension and deployment boundaries](../../roadmap/decisioning/execution-authorization-ontology.md#extension-and-deployment-boundaries) | Real policy bundles, identities, scopes, observations, and provider mappings are deployment-owned inputs rather than upstream implementation. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | implemented | Adopted the implementation ledger without reconstructing earlier provenance. | Current source boundaries and focused checks listed in the scope table. | No upstream implementation work remains for this document's bounded scope. |
| 2026-08-16 | implemented | Recorded the shipped enforcement default, which the document did not state. The control-loop integration is real, but `execution_authorization_evaluator` defaults to `None`, `execution_authorization_required` defaults to `False`, and only `bind_execution_authorization` sets them, so a default deployment runs with this gate inert. No scope row changes, because deployment-owned bindings are already declared outside this document's scope; the omission was the default itself. | `current change`; `composition/_helpers.py` lines defining both fields; separate searches for `execution_authorization_evaluator=` and `execution_authorization_required=` match only `wire_execution_authorization.py` and the two `control_loop.py` reads. | Bind the seam from a deployment path, or record a decision that binding stays deployment-owned. |
| 2026-08-17 | implemented | Corrected the 2026-07-31 claim that the role-filtered pending-grant browser projection was implemented. The Operator read a materialized `operator-projection:iam:access-grants.snapshot` key that no code in this repository ever wrote, so `GET /access-grants/stream` failed closed with HTTP 503 on every reconnect in every venue. The adapter also ignored `reviewer_ref` and `reviewer_roles`, so materializing that key as written would have shown every reviewer their own request and broken the no-self-approval boundary. The Operator now reads the authoritative grant-request records through a bounded prefix scan and applies pending, expiry, requester, and approver-role filters at its own boundary. | `current change`; `postgres_family_store.py`, `postgres_iam.py`, and `test_operator_service_postgres.py`; focused Operator suite passed 374 cases with 1 skipped; Ruff and strict mypy passed for the changed sources; an authenticated local session observed `GET /access-grants/stream` return 200 with no reconnect loop. | Record a deployed-revision observation of the same stream once a real grant request exists in a deployed environment. |
| 2026-08-17 | implemented | Hardened the browser review path across a critique campaign. Six defects were fixed: a truncated scan silently dropped older pending requests; a malformed counter surfaced as HTTP 500 instead of the fail-closed 503; an out-of-range field made the browser discard the whole snapshot with no operator signal; newest-first truncation could starve the longest-waiting approval; the decision receipt reported a constant quorum of one so the console showed `0 of 1` for a request needing two; and the decision path accepted a self-approval or a wrong-role decision from anyone who knew a request id. Two further defects were fixed in the durable path: the decision idempotency key used the request id alone, so a second distinct approver collided with the first and no quorum above one was reachable, and role sets reached the outbox as a hash-seed-dependent Python repr that made the fencing digest differ between processes. | `current change`; `postgres_family_store.py`, `postgres_iam.py`, `test_operator_service_postgres.py`; focused Operator suite passed 394 cases with 1 skipped; Ruff and strict mypy passed; the bounded scan, its filtered form, and its truncation signal were exercised against local PostgreSQL; payload determinism was measured across four interpreter hash seeds, showing three distinct orderings before and one stable digest after. | Core still owns applying a decision, so a deployed observation of an accumulated quorum remains open. |
| 2026-08-23 | implemented | Preserved execution authorization as an independent gate after immutable rule-governance assignment resolution and before dispatch. | `current change`; focused governance assignment and unified safety-path checks. | No authorization capability, identity, policy posture, or effective-access evidence is inferred from an assignment or exemption. |

### Remaining work

- [x] The upstream execution-authorization scope is implemented and retained by the strict-loader,
  resolver, evaluator, grant-lifecycle, control-loop, and direct-executor focused checks listed
  above; deployment-owned bindings remain outside this document's implementation scope.
- [ ] Observe `GET /access-grants/stream` returning a reviewer-scoped pending grant in a deployed
  environment, so the browser review path carries deployed-revision evidence rather than local
  evidence only ([#152](https://github.com/dotnetpower/fdai/issues/152)).
