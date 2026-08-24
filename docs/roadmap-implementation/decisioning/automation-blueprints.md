# Reviewable Automation Blueprints implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Evidence contract and deterministic recurrence aggregation | implemented | `services/core-control-plane/src/fdai/core/scheduler/blueprints/models.py`; `services/core-control-plane/src/fdai/core/scheduler/blueprints/aggregator.py`; `services/core-control-plane/tests/core/scheduler/test_blueprint_aggregator.py` | Focused tests cover inert defaults, threshold and order independence, deduplication, scope and authority separation, outcome stability, scheduler-failure veto, recursion blocking, and input validation. |
| Review, materialization, bounded drafting, audit events, and metric bookkeeping | implemented | `services/core-control-plane/src/fdai/core/scheduler/blueprints/review.py`; `services/core-control-plane/src/fdai/core/scheduler/blueprints/text.py`; `services/core-control-plane/tests/core/scheduler/test_blueprint_review.py` | Focused tests prove authorization, no self-review, terminal suppression, expiry, bounded text, command-mediated and safe-to-retry materialization, audit events, and realized-usage counters. |
| Suggestion orchestration and configuration-review projection | in-progress | `services/core-control-plane/src/fdai/core/scheduler/blueprints/suggestion.py`; `services/core-control-plane/src/fdai/core/scheduler/blueprints/configuration_review.py` | The off-path service and inert configuration-review projection exist, but no production evidence feed, composition binding, or focused orchestration test is present. |
| PostgreSQL durability and compare-and-swap transitions | in-progress | `alembic/versions/20260720_0043_automation_blueprint.py`; `services/core-control-plane/src/fdai/delivery/persistence/postgres_automation_blueprint.py`; `services/core-control-plane/tests/persistence/test_automation_blueprint.py` | The migration, store, and codec exist and the codec test passes. The database-backed persistence and compare-and-swap test was skipped because `FDAI_DATABASE_URL` was unset, so durable behavior is not yet claimed as implemented. |
| Read-only Console route and response decoder | implemented | `console/src/routes/automation-blueprints.tsx`; `console/src/routes/automation-blueprints.test.ts`; `console/src/panel-sources.ts` | The route renders inert candidate and metric fields, rejects contradictory responses, and exposes no mutation controls. This state does not claim an end-to-end Operator API source. |
| Operator API projection and authorized ChatOps review routes | in-progress | `services/operator-service/src/fdai_operator_service/families/operations/manifest.py`; `services/operator-service/tests/test_operator_operations_family.py`; `console/src/panel-sources.ts` | The Reader-gated `GET /automation-blueprints` projection and the separately authorized `POST /automation-blueprints/{accept,reject,materialize}` routes are registered. The read route is bounded, redacted, and fail-closed; the three review routes sit at the approver floor, require an idempotency key, only queue a durable proposal, and reject a conflicting key. A contributor may propose a blueprint but cannot review one, and no proposal route may be reachable at the read floor. Binding those proposals to the review service remains open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. Recorded the focused-test-backed aggregation, review, materialization, drafting, metrics, and Console decoder as implemented while separating unbound orchestration, unproved PostgreSQL durability, and missing operator surfaces. | `current change`; source and focused tests listed in the scope table; `uv run pytest -q --no-cov services/core-control-plane/tests/core/scheduler/test_blueprint_aggregator.py services/core-control-plane/tests/core/scheduler/test_blueprint_review.py services/core-control-plane/tests/persistence/test_automation_blueprint.py` (`12 passed, 1 skipped` because `FDAI_DATABASE_URL` was unset); `npm --prefix console test -- --run src/routes/automation-blueprints.test.ts` (`2 passed`) | Bind the production services, prove database-backed transitions, expose governed Operator API and ChatOps routes, and collect runtime evidence before claiming `validated`. |
| 2026-08-14 | in-progress | Registered the Reader-gated `GET /automation-blueprints` projection in the Operator operations family so the Console panel source resolves to a real read-only route instead of a declared-but-missing path. | `current change`; `services/operator-service/src/fdai_operator_service/families/operations/manifest.py`; `services/operator-service/tests/test_operator_operations_family.py`; the Operator Service suite passed 240 cases and `npm --prefix console test -- --run src/routes/automation-blueprints.test.ts` passed 2 cases. | Add the separately authorized ChatOps accept, reject, and materialize routes; materialize the authoritative projection from the production binding; collect runtime evidence. |
| 2026-08-14 | in-progress | Registered the separately authorized accept, reject, and materialize review routes as durable proposals, so the reader who may read a candidate cannot act on it and no route reviews or materializes inline. | `current change`; `services/operator-service/src/fdai_operator_service/families/operations/manifest.py`; `services/operator-service/tests/test_operator_operations_family.py`; the Operator Service suite passed 244 cases and route-parity integration checks passed 54 cases. | Bind the queued proposals to `AutomationBlueprintReviewService`, materialize the authoritative projection from the production binding, and collect runtime evidence. |
| 2026-08-14 | in-progress | Raised the three review routes from the shared contributor floor to the approver floor and made every proposal route carry an explicit role set that can never include the reader. | `current change`; `families/operations/manifest.py`, `families/operations/factory.py`, and `test_operator_operations_family.py`; the Operator Service suite passed 257 cases. | Bind the queued proposals to `AutomationBlueprintReviewService`, materialize the authoritative projection, and collect runtime evidence. |

### Remaining work

- [ ] Bind the production evidence feed, suggestion service, PostgreSQL store, authorizer, audit
  publisher, and `CreateScheduledTaskCommand`, then pass an integration test that turns three
  qualifying completed operator turns into one inert durable candidate without recursive input.
- [ ] Run the migration against a disposable PostgreSQL database and pass
  `test_postgres_blueprint_store_persists_and_cas_transitions` with `FDAI_DATABASE_URL` set,
  including concurrent or stale-state compare-and-swap rejection.
- [x] The Reader-gated Operator Service `GET /automation-blueprints` projection is registered,
  bounded, redacted, and fail-closed, and the Console decoder test still passes against it.
- [x] The separately authorized `POST /automation-blueprints/{accept,reject,materialize}` routes are
  registered, contributor-gated, idempotency-keyed, and proposal-only; API integration tests prove a
  reader is refused and no route reviews or materializes inline.
- [ ] Bind the queued accept, reject, and materialize proposals to `AutomationBlueprintReviewService`
  so an authorized decision reaches the durable candidate without granting the route any authority.
- [ ] Materialize the authoritative `automation_blueprint.list` projection from the production
  binding so the registered read route returns candidates instead of an unavailable response.
- [ ] Export the documented blueprint metrics from the production binding and record governed
  runtime evidence for proposal, review, materialization, scheduled occurrence, and realized-usage
  attribution before changing any scope row to `validated`.
