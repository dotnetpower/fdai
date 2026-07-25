# Fundamental Design Hardening Review

This audit evaluates whether FDAI behaves like a resident team of 15 autonomous operators rather
than a collection of disconnected features. Runtime wiring, durable state, failure degradation,
and executable tests count as completion evidence. Design text without a live composition path is
recorded as partial or missing.

## Readiness summary

| Work unit | Intended outcome | Current evidence | Readiness | Priority |
|-----------|------------------|------------------|-----------|----------|
| Pantheon event boundary | Independent agents exchange ordered, attributable, replayable records | Strict mutation envelopes, authenticated producers, ordered poison handling, bounded DLQ retry, and safe redrive are implemented and agent-tested | Hardened | P0 |
| Resource discovery and drift | Agents discover resources, retain a complete graph, and detect changes without operator enumeration | Realtime ingress, inventory projection, analyzer jobs, tombstones, and restricted-egress design exist; durable fallback and restart proofs need consolidation | Partial | P0 |
| Human approval intelligence | Approval requests are safe, grouped, rate-aware, and actionable without notification fatigue | Identity, expiry, HMAC, RBAC, fingerprint dedup, and fail-closed parking exist; durable delivery recovery and aggregation policy need focused review | Partial | P0 |
| Fifteen-agent conversation | A human can select any agent and receive role-grounded answers with role-appropriate tools | Conversational routing and introspection exist; independent prompts, specialist live data paths, direct selection, and tool evidence vary by agent | Partial | P1 |
| Connected and isolated onboarding | One guided path validates prerequisites and reaches observe-ready state in either network posture | Terraform, private runner, offline kit, preflight, and readiness probes exist; operator recovery evidence and end-to-end isolated acceptance remain fragmented | Partial | P1 |
| Deterministic-first safety | Routine cases avoid model inference and every mutation remains bounded, reversible, and auditable | Tiering, risk, quality, executor, rollback, and audit modules exist; durable authority and restart behavior need focused proof | Partial | P1 |

## Campaign rules

Each work unit follows the same gate:

1. Review at least 10 independent failure modes or controls.
2. Reject speculative findings and record why they are not defects.
3. Harden every accepted finding rated Low or higher before starting the next unit.
4. Run the narrowest executable checks, route-selected checks, and the fast repository gate.
5. Commit the validated unit without staging unrelated work.

## Work unit 1: Pantheon mutation event boundary

This unit covers the transport shared by all 15 agents. It does not change any agent role, owned
topic, subscription, model policy, or hard-dependency status. Thor remains the sole executor,
Forseti the judge, Var the approver, Saga the auditor, and Vidar the rollback principal.

| # | Critique | Evidence | Severity | Decision and hardening |
|---|----------|----------|----------|------------------------|
| 1 | Topic ownership is checked before publish | `PantheonRegistry.assert_can_publish` runs before transport I/O | Pass | Retained and regression-tested |
| 2 | Caller-provided `producer_principal` can override the authenticated principal | Both buses used `setdefault` | High | Always stamp the authenticated principal |
| 3 | Transport and domain contracts share `schema_version` | Forecast outcomes use `"1.0.0"` while the bridge used integer `1` | High | Preserve domain `schema_version`; stamp `envelope_schema_version` separately |
| 4 | Mutation records without `idempotency_key` were only counted | `_check_envelope` warned and continued | High | Reject before provider publish |
| 5 | Mutations could use `correlation_id` instead of `resource_id` for partitioning | Mutation partitioning had a fallback | High | Require non-empty `resource_id` |
| 6 | Mutations without `correlation_id` could publish | Correlation was warning-only | Medium | Require non-empty `correlation_id` |
| 7 | Unknown `object.*` subscriptions created dead seams | Registration warned and continued | Low | Reject during registration |
| 8 | Producer verification could be disabled on owned topics | A constructor bypass existed | High | Remove the bypass |
| 9 | Ordered consumers continued after poison mutations by default | Halt default was false | Critical | Halt the ordered consumer after parking poison |
| 10 | Handler execution was unbounded by default | Timeout default was `None` | Medium | Apply a finite default |
| 11 | DLQ failure was swallowed while the consumer advanced | `_safe_dead_letter` logged and returned | High | Retry boundedly, then propagate for consumer restart |
| 12 | Redrive bypassed owner/envelope checks and nested wrappers | Redrive invoked handlers directly | High | Revalidate and re-park only the original payload |

### Verification evidence

- Focused bridge safety and parity tests: 64 passed.
- Complete Pantheon agent suite: 611 passed.
- Ruff and strict mypy checks pass for the touched slice.
- Bilingual translation, punctuation, catalog, stewardship, architecture, and integrity gates pass.

## Remaining work units

The next unit starts only after every accepted finding in the current unit is implemented, tested,
and committed. Later units add their own 10-or-more-point critique table and close every accepted
Low-or-higher finding before advancing.
