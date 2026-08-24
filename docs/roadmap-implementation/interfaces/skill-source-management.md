# Skill Source Management implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

The current tree contains the deterministic lifecycle and durable adapters, but it does not yet
compose an end-to-end external-source capability.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Source, quarantine, scan, verification, candidate, approval, and revocation domain lifecycle | implemented | [`source_registry.py`](../../../services/core-control-plane/src/fdai/core/skills/source_registry.py), [`skill_source_pipeline.py`](../../../services/core-control-plane/src/fdai/core/supply_chain/skill_source_pipeline.py), [`skill_source_admin.py`](../../../services/core-control-plane/src/fdai/core/supply_chain/skill_source_admin.py), and focused supply-chain tests | Current focused tests cover registration, refresh, blocking, proposal creation, approval guards, and revocation delegation. |
| PostgreSQL schema, stores, durable claims, and transactional revocation | implemented | [Alembic revision `20260720_0045`](../../../alembic/versions/20260720_0045_skill_source_quarantine.py), [`postgres_skill_source.py`](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_skill_source.py), [`postgres_skill_quarantine.py`](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_skill_quarantine.py), and codec tests | Offline store tests pass. The live PostgreSQL restart and provenance test exists but requires `FDAI_DATABASE_URL`. |
| Operator HTTP read and proposal contracts | implemented | [`manifest.py`](../../../services/operator-service/src/fdai_operator_service/families/workflow/manifest.py), [`routes.py`](../../../services/operator-service/src/fdai_operator_service/families/workflow/routes.py), and [`test_operator_workflow_family.py`](../../../services/operator-service/tests/test_operator_workflow_family.py) | Reader GET routes and Approver/Owner proposal routes are registered and role-tested. They intentionally do not import or call the core authority implementation. |
| Concrete GitHub fetch adapter | implemented | [`skill_source.py`](../../../services/core-control-plane/src/fdai/delivery/github/skill_source.py); [`test_skill_source.py`](../../../services/core-control-plane/tests/delivery/github/test_skill_source.py); focused adapter tests (`28 passed`) | The adapter resolves a full immutable commit SHA with strict ETag support and fetches exact bounded regular files while rejecting redirects, substitutions, symlinks, malformed content, authentication failures, and rate limits. Provider and credential failures remain redacted. Runtime composition remains separate. |
| Production composition and scheduled runner | not-started | Current runtime/bootstrap usage audit | No bootstrap path instantiates `SkillSourceRefreshService`, `SkillSourceRefreshOrchestrator`, `SkillSourceAdministrationService`, or their PostgreSQL adapters. |
| Console source-management projection and governed runtime evidence | not-started | Current Console usage audit and focused test run | The Console does not call the source-management routes, and no current runtime receipt proves fetch-to-proposal or approval/revocation execution. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger, corrected stale production-binding and HTTP execution claims, and repaired the focused test command; earlier implementation provenance was not reconstructed. | `current change`; `37 passed, 1 skipped` from the exact-path skill-source and Operator workflow suite; roadmap, translation, punctuation, Hangul, size, and link checks. | Implement and bind the missing adapter and runtime path, validate live persistence, expose the read-only projection, and record governed runtime evidence. |
| 2026-08-14 | implemented | Added the concrete GitHub skill-source adapter with immutable revision, conditional request, exact-path, content-bound, authentication, redirect, and rate-limit enforcement. | `current change`; `services/core-control-plane/src/fdai/delivery/github/skill_source.py`; `services/core-control-plane/tests/delivery/github/test_skill_source.py`; focused adapter tests `21 passed`. | Compose the independently runnable owner, connect the authority-bearing event path, validate live persistence, and expose the read-only projection. |
| 2026-08-14 | implemented | Hardened conditional requests to accept only bounded quoted entity tags and suppressed credential-provider exception context so secrets cannot escape through chained errors. | `current change`; `services/core-control-plane/src/fdai/delivery/github/skill_source.py`; `services/core-control-plane/tests/delivery/github/test_skill_source.py`; focused adapter tests `28 passed`. | Runtime composition, authority-bearing event integration, live persistence, and the read-only projection remain open. |

### Remaining work

- [x] Implement a concrete GitHub `SkillSourceAdapter` that enforces immutable revision, bounded path,
  redirect, symlink, content-size, UTF-8, authentication, and rate-limit rules, with focused adapter
  tests for every rejection path.
- [ ] Compose the source stores, quarantine stores, verifier factory, refresh service,
  administration service, and scheduled orchestrator in the independently runnable owning service;
  prove duplicate-runner exclusion and restart recovery with focused integration tests.
- [ ] Connect workflow read and proposal operations to the authority-bearing event path without
  importing core implementations into the Operator Service, and prove approval and revocation remain
  role-gated, idempotent, disabled-by-default, and replayable.
- [ ] Run the live PostgreSQL restart/revocation test with `FDAI_DATABASE_URL`, add the read-only
  Console projection, and record governed runtime receipts for refresh, approval, and revocation.
