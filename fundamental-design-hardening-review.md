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

## Work unit 2: Approval decision delivery recovery

This unit covers the registry-backed callback path that records an operator decision and publishes
it to the typed runtime. It does not invent tenant-specific rate limits, quiet hours, or escalation
destinations. Those remain configuration and routing policy.

| # | Critique | Evidence | Severity | Decision and hardening |
|---|----------|----------|----------|------------------------|
| 1 | Callback authentication binds timestamp, approval id, and body | HMAC material includes all three | Pass | Retain existing tests |
| 2 | Replay window rejects stale signed callbacks | `max_skew_seconds` is validated and enforced | Pass | Retain existing tests |
| 3 | Callback payload and approval id are bounded before expensive work | Body and path caps run before parsing | Pass | Retain existing tests |
| 4 | Registry writes a decision before attempting event delivery | `record_decision` precedes publisher invocation | Pass | Preserve durable-first ordering |
| 5 | Registry rejects a different terminal decision for one key | Conflicting decisions raise `HilItemAlreadyResolvedError` | Pass | Preserve conflict semantics |
| 6 | Self-approval comparison is raw-string equality | Callback does not trim or case-normalize OIDs | High | Normalize actor and submitter identities before comparison and storage |
| 7 | Registry callback can start without a delivery publisher | Optional publisher returns success after record-only | High | Fail route construction when publisher is absent |
| 8 | Publisher invocation has no timeout | One stuck broker call can occupy the request indefinitely | Medium | Apply a validated per-attempt timeout |
| 9 | Transient publisher failure has no bounded retry | First failure returns 503 immediately | Medium | Retry with bounded exponential backoff |
| 10 | The documented same-decision retry can return 404 | In-memory registry removes pending before publish | High | Retrieve durable receipts by approval id after resolution |
| 11 | Successful delivery has no durable marker | A repeated callback republishes or cannot distinguish delivery | High | Persist a delivered marker on the decision receipt |
| 12 | Same decision from a different actor can masquerade as replay | Registry idempotency keys only by action and decision | Medium | Require replay actor to match the recorded approver |
| 13 | StateStore decisions remain visible in the pending queue | Decision rows do not change the parked record's `pending` status | High | Exclude parks with a durable decision row from pending projection |
| 14 | Undelivered decisions wait for another human callback | Production has no background drain for durable undelivered receipts | High | Run a bounded startup and periodic recovery loop over the receipt outbox |
| 15 | Event transport wiring discards existing shutdown callbacks | The final tuple replaces the callbacks passed into runtime wiring | High | Preserve existing callbacks and stop recovery before closing the bus |
| 16 | Concurrent recovery can regress a delivered checkpoint | A stale failed attempt can overwrite a successful delivery state | High | Make terminal delivery states monotonic and update Postgres rows under lock |

### Discriminating checks

- A callback route without a decision publisher fails during composition.
- Transient delivery failures retry within configured attempt and timeout bounds.
- A persistent failure leaves one durable, undelivered receipt and returns retryable `503`.
- Replaying the same signed decision loads that receipt, publishes it, and marks it delivered.
- Replaying an already delivered receipt returns success without another event publication.
- A conflicting decision or different replay actor returns `409` and never publishes.
- Case or surrounding whitespace cannot bypass no-self-approval.
- A durably resolved decision no longer appears in the pending approval queue.
- Broker recovery or process restart drains undelivered receipts without another human action.

### Verification evidence

- Callback, registry, recovery, approval-tool, provider, and production tests: 132 passed.
- Strict mypy passes for every changed production module.
- Ruff passes for every changed source and test module.

## Remaining work units

The next unit starts only after every accepted finding in the current unit is implemented, tested,
and committed. Later units add their own 10-or-more-point critique table and close every accepted
Low-or-higher finding before advancing.
