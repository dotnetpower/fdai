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
| Fifteen-agent conversation | A human can select any agent and receive role-grounded answers with role-appropriate tools | Independent charters, semantic fallback, direct selection, and 30 exact-owner read tools are registered with bounded output and health evidence | Hardened | P1 |
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

## Work unit 3: Ordered inventory delta projection

This unit covers the PostgreSQL overlay that applies Huginn-normalized resource changes above the
last complete inventory snapshot. It preserves Huginn's ingress ownership and does not turn the
delta stream into proof of inventory completeness.

| # | Critique | Evidence | Severity | Decision and hardening |
|---|----------|----------|----------|------------------------|
| 1 | Missing inventory changes are ignored | Projector returns a zero-row result | Pass | Retain |
| 2 | Resource and link change kinds are allowlisted | Only `upsert` and `delete` are accepted | Pass | Retain |
| 3 | Resource identity and type are mandatory | Boundary helpers reject empty values | Pass | Retain |
| 4 | Properties must be JSON-object mappings | Resource and link props are checked | Pass | Retain |
| 5 | Observation timestamps require timezone-aware RFC 3339 | `_timestamp` rejects malformed and naive values | Pass | Retain |
| 6 | Arbitrarily future timestamps can block later real changes | No future-skew ceiling exists | Critical | Reject events beyond a configured server-clock skew |
| 7 | Delta resource type must belong to active coverage | Active snapshot JSON coverage is queried | Pass | Retain |
| 8 | A delayed pre-snapshot event can override the newer snapshot | Coverage query does not compare event time with active snapshot start | Critical | Ignore events at or before active snapshot start |
| 9 | Promotion and delta writes share one advisory lock | Both use `_PROMOTION_LOCK` | Pass | Retain |
| 10 | Older overlay rows cannot replace newer rows | Conflict update compares `observed_at` | Pass | Retain |
| 11 | Equal-time delete and upsert are ordered by opaque event id | Lexical event id can resurrect a deleted resource | High | Make delete win before deterministic same-kind event-id tie-break |
| 12 | Resource delete can carry link upserts | Mixed payload can leave live links for a tombstoned resource | High | Require every attached link change to be delete |
| 13 | Link endpoint types bypass active coverage | Only the primary resource type is checked | High | Require resource and every endpoint type in active coverage |
| 14 | One event can contain an unbounded link array | `_links` has no item ceiling | Medium | Apply a configurable bounded link count before database work |
| 15 | Event and idempotency identities are mandatory | Both are read with `_required_str` | Pass | Retain |
| 16 | Resource and link overlay writes are one transaction | Projector uses one transaction under the promotion lock | Pass | Retain |

### Discriminating checks

- Future-dated changes fail before opening a database connection.
- Oversized link sets and delete-plus-upsert-link payloads fail before database work.
- Coverage checks include every link endpoint type.
- Events covered by the active snapshot start fence produce a zero-row no-op.
- At equal observation time, delete beats upsert; same-kind ties remain deterministic by event id.

### Verification evidence

- Inventory delta boundary tests: 8 passed.
- Strict mypy and Ruff pass for the projector and tests.
- Six PostgreSQL integration cases are selected but skipped locally because
	`FDAI_DATABASE_URL` is unset; CI remains the authoritative live-database check.

## Work unit 4: Independent agent conversation charters

This unit covers direct human selection of each fixed agent and the role/tool policy passed to its
read-only conversational port. It does not grant any conversational path execution authority or
increase model use in the typed hot path.

| # | Critique | Evidence | Severity | Decision and hardening |
|---|----------|----------|----------|------------------------|
| 1 | The Pantheon contains exactly 15 agents | `PANTHEON_SPECS` and parity tests pin the set | Pass | Retain |
| 2 | Explicit agent names override domain scoring | Router returns `explicit_agent` | Pass | Retain |
| 3 | Every agent declares question domains | All 15 specs have non-empty domains | Pass | Retain |
| 4 | Every concrete agent implements grounded introspection | All 15 classes override or own the deterministic fallback | Pass | Retain and test direct reachability |
| 5 | Conversational action intent cannot execute directly | Base port returns `requires_typed_pipeline` | Pass | Retain |
| 6 | Session ownership prevents cross-user reuse | Bragi compares the stored user id | Pass | Retain |
| 7 | Bragi cannot be selected as its own responder | Runtime excludes Bragi from responder registration | High | Register Bragi's read-only turn responder too |
| 8 | A2A introspection cannot target Bragi | Responder lookup returns `responder_not_registered` | High | Route Bragi through the same read-only responder map |
| 9 | Agents have no independent system prompt contract | `AgentSpec` carries role metadata but no conversation instructions | High | Require a unique immutable conversation charter per agent |
| 10 | Agents have no allowed conversational tool manifest | Owned-state methods are not declared for model-backed use | High | Require bounded ASCII tool ids per charter |
| 11 | Prompt and tools are not injected into responder context | `on_conversation_turn` forwards caller context unchanged | Medium | Overwrite internal policy context from immutable spec |
| 12 | Responses cannot attribute the policy version used | Envelope contains no prompt or tool policy digest | Medium | Return prompt SHA-256 and allowed tool ids, never raw prompt text |
| 13 | Unknown A2A requesters are rejected | Bragi checks `PANTHEON_NAMES` | Pass | Retain |
| 14 | Contributor fan-out and latency are bounded | Three contributors and two-second timeout | Pass | Retain |
| 15 | Responder registration accepts unknown agent names | `register_responder` writes any key | Medium | Reject names outside the fixed Pantheon |
| 16 | Responder registration silently overwrites an existing binding | Dictionary assignment has no duplicate guard | High | Reject duplicate registration |
| 17 | A2A requester attribution is process-local only | Response carries requester but no durable Turn is published | Medium | Publish a digest-only Bragi-owned Turn with requester, target, and trace |

### Discriminating checks

- Explicitly naming each of the 15 agents returns that agent as primary with a non-empty answer.
- Direct and A2A requests to Bragi use Bragi's own read-only responder without recursion.
- Every agent has a unique non-empty prompt and a bounded non-empty tool manifest.
- Responder context receives server-owned prompt and tool policy even if caller context is forged.
- Responses expose only prompt SHA-256 and tool ids for attribution, never raw system prompts.
- Unknown or duplicate responder bindings fail during composition.

### Verification evidence

- Complete Pantheon agent suite: 616 passed.
- Strict mypy passes for all changed agent source modules.
- Ruff, bilingual translation, document-size, punctuation, and diff checks pass.

## Work unit 5: Offline provisioning inspection

This unit connects signed offline-kit verification to the read-only provisioning inspection
contract without allowing an operator-supplied trust root. The first public release-root ceremony
remains an explicit operational blocker rather than a generated test key committed as authority.

| # | Critique | Evidence | Severity | Decision and hardening |
|---|----------|----------|----------|------------------------|
| 1 | Connectivity mode is explicit or evidence-selected | `auto`, `online`, and `offline` are distinct | Pass | Retain |
| 2 | Inspection performs no host or cloud mutation | Result always records `mutation_performed=false` | Pass | Retain |
| 3 | Offline file presence does not establish trust | Candidate state remains review | Pass | Retain |
| 4 | Inspection cannot consume a pinned verifier | Candidate existence is the only offline evidence | High | Add an injected verifier boundary |
| 5 | Invalid signatures and digests look like valid candidates | Inspect never calls the verifier | High | Return a failed artifact check and incomplete status |
| 6 | Verified kit metadata is absent from machine output | Result carries no digest, version, platform, or count | Medium | Add bounded non-secret verification metadata |
| 7 | A verified offline existing host still cannot become ready | All offline selections unconditionally return review | Medium | Permit ready only when verifier succeeds and other host checks pass |
| 8 | Missing pinned verifier is indistinguishable from verification failure | Both appear only as candidate | Medium | Keep `candidate` for missing authority and `fail` for rejected content |
| 9 | Metadata files reject symlinks and size overflow | Verifier checks both before parsing | Pass | Retain |
| 10 | Artifact path can change between scan and digest read | `_file_digest` follows the path after earlier checks | High | Open with no-follow and verify the opened file descriptor |
| 11 | Manifest exact file set rejects missing and extra artifacts | Actual and listed sets must match | Pass | Retain |
| 12 | CLI and platform compatibility are exact | Manifest must match both inputs | Pass | Retain |
| 13 | File count and total bytes are bounded | Verifier enforces both ceilings | Pass | Retain |
| 14 | Online mode prefers allowlisted TLS sources when reachable | Auto selection checks all required hosts | Pass | Retain |
| 15 | Operator-supplied release roots would defeat trust pinning | Current design intentionally exposes no override | Rejected | Do not add an override; complete the release root ceremony separately |
| 16 | Offline execution still requires workload identity and tools | Existing-host readiness does not weaken in offline mode | Pass | Retain |

### Discriminating checks

- A verified kit produces `verified` evidence and can make an otherwise complete offline profile ready.
- A rejected kit produces `fail` evidence and an incomplete profile without leaking verifier details.
- A kit with no pinned verifier remains a candidate requiring review.
- Machine output includes only manifest digest, versions, platform, count, and total bytes.
- Digesting a symlink fails even if a prior directory scan accepted the original path.

### Verification evidence

- Complete deployment CLI suite: 107 passed.
- Strict mypy and Ruff pass for all deployment CLI source and tests.
- Public pinned-root packaging remains explicitly incomplete; no test key is treated as authority.

## Work unit 8: Agent read-tool implementation parity

This unit turns the 30 tool ids declared by the 15 immutable conversation charters into a guarded
runtime surface. Each call remains read-only and uses the owning agent's conversational port. It
does not expose a new HTTP endpoint, call a cloud SDK directly, or bypass the typed action path.

| # | Critique | Evidence | Severity | Decision and hardening |
|---|----------|----------|----------|------------------------|
| 1 | Declared tool ids can lack a runtime owner | Charters were metadata only | High | Build one fixed registry from every `PANTHEON_SPECS` charter |
| 2 | Duplicate ids can create ambiguous ownership | No composition-time owner check existed | High | Reject owner conflicts during registry construction |
| 3 | A caller can invoke a tool through the wrong agent | No tool invocation surface existed | High | Require exact declared owner before dispatch |
| 4 | Unknown ids can fall through to general conversation | No explicit unknown result existed | Medium | Hold with stable `unknown_tool` reason |
| 5 | Disabled agents can appear callable | Runtime disabled responders but had no tool availability report | High | Hold calls and report both unavailable tools in health |
| 6 | A provider call can block indefinitely | Agent introspection can await injected providers | High | Apply a finite configurable timeout per invocation |
| 7 | A provider exception can expose details or collapse the caller | No tool exception boundary existed | High | Convert exceptions to a detail-free `error` hold |
| 8 | Runtime cancellation can be swallowed as an error | Broad exception handling is easy to misuse | High | Re-raise `CancelledError` before the provider error boundary |
| 9 | An unbounded question can consume excess parsing or model budget | The tool entry had no local input cap | Medium | Reject questions over 2,000 characters before dispatch |
| 10 | Caller trace values can leak secrets or expand records | Trace attribution was unconstrained | Medium | Cap trace ids, scan them, and return no rejected value |
| 11 | Agent facts can produce unbounded or non-serializable output | Agent implementations return open mappings | High | Normalize to JSON and hold output above 64 KiB |
| 12 | Answers can surface secrets or personal data | Existing introspection had no final sensitivity gate | Critical | Scan the complete serialized result and return only value-free labels on a hit |
| 13 | Results cannot prove which charter authorized the tool | Prompt policy was only inside the response context | Medium | Return prompt SHA-256 and the immutable allowed-tool tuple |
| 14 | Grounding references can be lost between agent and caller | No normalized tool result contract existed | Medium | Preserve bounded evidence refs and stable id/ref facts |
| 15 | Startup and invocation health are invisible | Runtime health exposed only the conversational port boolean | Medium | Report 30-tool availability and per-agent status counters |
| 16 | A read-tool API could accidentally gain mutation authority | The owning port already redirects action intent to the typed pipeline | Pass | Reuse that port; do not bind executors or cloud SDKs |
| 17 | Delivery authorization could be duplicated inconsistently | The new API is internal and exposes no network route | Rejected | Keep authentication and RBAC at the delivery boundary when a route is added |

### Discriminating checks

- All 30 declared ids resolve through their exact owner across all 15 agents.
- Unknown, wrong-owner, disabled, timed-out, and raising calls return stable held results.
- Oversized questions, trace values, and outputs are rejected before they can escape the boundary.
- Secret and personal-data findings return only detector labels, never matched values.
- Successful results carry evidence references, trace attribution, prompt digest, and tool policy.
- Runtime health reports registered, available, disabled, and per-agent invocation counters.

### Verification evidence

- Agent read-tool registry tests: 6 passed, including all 30 declared tools.
- Strict mypy and Ruff pass for the registry, runtime wiring, exports, and tests.

## Work unit 9: Connected and offline deployment recovery

This unit connects existing protected-plan, signed-kit, and startup-readiness machine statuses to
one bilingual operator procedure. It adds no trust override, local apply path, or synthetic health.

| # | Critique | Evidence | Severity | Decision and hardening |
|---|----------|----------|----------|------------------------|
| 1 | Expired plan recovery is spread across code and roadmap text | Exact apply rejects expiry | High | Map expiry to full replan and new approval |
| 2 | Operators can be tempted to edit `expires_at` | Metadata is signed and digest-bound | Critical | Explicitly forbid metadata edits and plan-id reuse |
| 3 | Context or digest mismatch lacks one recovery sequence | Verifier has distinct mismatch guards | High | Correct input and create a new protected plan |
| 4 | A blocked plan can tempt local apply | Approved runner is part of the bound context | Critical | Require blocker repair and runner-side replan |
| 5 | Offline kit presence can look trusted | `candidate` is not `verified` | High | Require overall ready, exit 0, and verified status |
| 6 | A rejected kit can be repaired in place | Exact manifest file set and signature would be invalid | Critical | Quarantine and replace the complete kit |
| 7 | An operator trust-root override would bypass release authority | No override exists by design | Critical | Forbid local roots and test keys as recovery |
| 8 | CLI exit meanings are distributed | Inspect uses 0, 2, 4; preflight uses 0, 2, 3 | Medium | Document each exit as evidence, not permission |
| 9 | `/live` can be mistaken for readiness | Liveness and readiness are separate endpoints | High | Require `/ready` plus startup report evidence |
| 10 | `degraded` can be mistaken for full authority | Report carries per-capability ceilings | Critical | Keep operations at or below each authority ceiling |
| 11 | Stale evidence can be relabeled as recovered | Readiness reducer checks expiry | Critical | Require a fresh unexpired probe result |
| 12 | Manual consumer restarts can bypass lifecycle gating | Runtime suspends and resumes on readiness | High | Wait for periodic evaluation instead of manual restart |
| 13 | Failure evidence can be lost during replacement | Existing contracts expose sanitized fields | Medium | Define one audit evidence checklist |
| 14 | Recovery claims lack executable drills | Safety tests already pin each state transition | High | Define expired-plan, rejected-kit, and readiness-loss drills |
| 15 | Recovery after an already-started action is ambiguous | Rollback has its own governed procedure | Medium | Hand off with original correlation and idempotency keys |

### Verification evidence

- Protected-plan, offline-kit, readiness reducer, and runtime readiness tests: 35 passed.
- English and Korean runbooks pass translation, terminology, punctuation, and document gates.
- Drills require a new verified artifact or fresh evidence; no status edit can complete recovery.

## Work unit 10: Deterministic and model cost evidence

This unit extends the frozen baseline runner rather than creating a second evaluation system. It
records the economics and quality fields needed for a release decision and fails closed when the
current evidence is too small, incomplete, or below threshold.

| # | Critique | Evidence | Severity | Decision and hardening |
|---|----------|----------|----------|------------------------|
| 1 | Predicted tier is collected but discarded from the summary | `ScenarioOutcome` held both tiers | High | Aggregate T0/T1/T2 count and share |
| 2 | Per-tier latency is absent | Observations had no latency field | High | Require measured latency and report sample count, p50, and p95 |
| 3 | Model-call volume is absent | No observation counter existed | High | Require and aggregate non-negative model-call counts |
| 4 | Token volume is absent | Pricing cannot be checked without usage | High | Require input and output token counts |
| 5 | Cost can be guessed from illustrative catalog prices | Baseline had no measured cost field | Critical | Accept measured cost or explicit `null`; report unpriced calls |
| 6 | Abstentions are mixed into general decisions | No explicit aggregate existed | Medium | Report abstention count and rate |
| 7 | Verifier outcomes are invisible | No observation field existed | High | Require a bounded verifier outcome and aggregate failures |
| 8 | Outcome quality omits tier correctness | Routing metric existed only in success metrics | Medium | Carry count and rate into quality evidence |
| 9 | Nine synthetic cases can look release-ready | `claim_eligible=false` was informational | Critical | Require at least 30 measured scenarios |
| 10 | Missing telemetry can appear as zero | Synthetic runner has no latency observations | Critical | Separate known zero calls/cost from unmeasured latency and block release |
| 11 | T2 share has no release threshold | The 5-10 percent target was prose only | High | Block above 0.15, allowing a measured operating margin |
| 12 | Quality and guard thresholds do not affect CLI status | Runner always exited zero | High | Add `--require-release-eligible` exit code 3 |
| 13 | Unknown model pricing can disappear in total cost | Null cost was not represented | High | Count unpriced calls and make total cost null |
| 14 | Generated reports omit the new evidence | JSON and bilingual Markdown share one generator | Medium | Render tier economics, model usage, quality, and every gate check |
| 15 | Baseline regeneration can drift from committed artifacts | A reproducibility test compares exact content | Pass | Preserve and extend exact regeneration testing |

### Verification evidence

- Baseline runner and artifact reproducibility tests: 8 passed.
- Frozen `v2026.07` reports 9 scenarios, 100 percent reference T2 routing, zero actual model calls,
  unmeasured latency, 0.111 routing quality, and `release_eligible=false`.
- The blocking CLI returns exit code 3 for the current incomplete, undersized evidence.

## Work unit 11: Public offline release trust bootstrap

This unit reviews the boundary between shipped verification code and the external authority needed
to create a production root. The repository can define and test the ceremony, but it must not mint
authority with a generated test key or place a root private key in CI.

| # | Critique | Evidence | Severity | Decision and hardening |
|---|----------|----------|----------|------------------------|
| 1 | No production root exists | CLI injects no verifier | Critical | Keep kits at candidate and publish explicit ceremony exit criteria |
| 2 | A test key could be promoted for convenience | Tests generate ephemeral keys | Critical | Forbid test keys as authority |
| 3 | One signer could control root authority | No ceremony policy existed | Critical | Require approved multi-key threshold and independent custody |
| 4 | CI could receive a root private key | Release signing is not yet separated | Critical | Keep root private keys offline; CI receives delegated keys only |
| 5 | Operators could substitute a root | CLI has no override | Pass | Preserve wheel-pinned bootstrap and forbid new overrides |
| 6 | Signed metadata can expire unnoticed | Exact-content manifest has no expiry | Critical | Require expiring TUF timestamp and snapshot metadata |
| 7 | An old valid release can roll back clients | Manifest versions are compatibility labels only | Critical | Require monotonic TUF metadata versions |
| 8 | Metadata and targets can be mixed | Exact file hashes do not bind repository metadata | High | Require TUF snapshot/timestamp bindings |
| 9 | Root rotation can lock out clients | No rotation drill existed | Critical | Update one version at a time under old and new thresholds |
| 10 | Online signing compromise can persist | Roles were not operationally separated | High | Delegate targets, snapshot, and timestamp under offline root |
| 11 | Artifact omission can survive repository authentication | TUF authenticates named targets | High | Retain exact file-set and digest verification after TUF |
| 12 | Wrong CLI or platform can consume a valid kit | Exact bindings already exist | Pass | Preserve CLI and platform equality checks |
| 13 | Symlink replacement can redirect hashing | No-follow descriptor hashing exists | Pass | Preserve and drill symlink rejection |
| 14 | Ceremony evidence can leak private material | No evidence contract existed | High | Record public fingerprints and signatures only; scan output |
| 15 | A deviation can be accepted informally | No stop decision owner existed | High | Name coordinator, reviewer, witness, and hard stop conditions |

### Verification evidence

- Offline-kit and provisioning inspection tests cover signatures, digests, file sets, symlinks,
	compatibility, bounds, ready, candidate, and sanitized failure states.
- The bilingual ceremony runbook defines role separation, TUF metadata, packaging, acceptance,
	sequential rotation, evidence, and eight fail-closed negative drills.
- Production root generation remains intentionally external. No private key or test authority was
	created, committed, transferred, or placed in CI.

## Work unit 12: Private-network onboarding acceptance

This unit exercises the development environment through the VNet-integrated self-hosted runner.
It uses the maintainer's default Azure CLI profile only after explicit subscription verification;
no customer profile, laptop data-plane apply, public runner IP, or local Terraform apply is used.

| # | Critique | Evidence | Severity | Decision and hardening |
|---|----------|----------|----------|------------------------|
| 1 | Azure extension and CLI auth contexts can differ | Extension context used another home tenant | Critical | Verify `az account show` before every Azure operation |
| 2 | Same-named resources can exist in another profile | User memory records the duplicate-name trap | Critical | Keep `AZURE_CONFIG_DIR` unset and verify subscription id |
| 3 | Private runner can be deallocated | VM was `deallocated` with no public IP | Pass | Start it and require online `fdai-deploy` label |
| 4 | Laptop cannot reach private state or secrets | State and data services are private | Pass | Run all data-plane plan/apply work on the VNet runner |
| 5 | Stopped PostgreSQL blocks provider refresh | First plan returned `ServerStoppedError` | Medium | Start the server, confirm `Ready`, and rerun plan |
| 6 | Direct workflow dispatch skips protected evidence | Empty request id skipped guard, live preflight, and storage | High | Use `fdaictl deploy plan` for acceptance |
| 7 | GitHub dispatch API returned no run details | Old API pin returned HTTP 204 | High | Pin the current API returning run id and URLs |
| 8 | CLI plan omitted enabled topology flags | Protected guard found a broad delete plan | Critical | Add all four feature flags to plan, guided, and apply CLI |
| 9 | Feature flags were outside the context digest | Plan and apply could disagree | Critical | Bind every flag into `DeploymentPlanContext` digest |
| 10 | Apply could omit the plan's topology | Workflow inputs defaulted false | Critical | Send identical flags for plan and exact apply |
| 11 | Moving `main` invalidated exact apply | Release automation advanced the branch | High | Checkout requested commit and compare actual `HEAD` |
| 12 | Expiry cleanup omitted two artifacts | Source and Azure preflight evidence were absent | Medium | Add both to the strict cleanup allowlist |
| 13 | Cleanup deleted one blob at a time | 120 expired blobs delayed plan publication | Medium | Delete at most 1000 with eight bounded workers |
| 14 | Derived-doc refresh ignored inline YAML | Quickstart pin stayed stale after review | Low | Support inline and multiline entries with tests |
| 15 | The delete gate cannot distinguish security retirement from destructive drift | Live plan blocked removal of the broad PostgreSQL Azure-services firewall | High | Permit only that exact address as a pure delete; reject its replacement and every other delete |
| 16 | Plan can drift between approval and apply | Binary, source, context, evidence, commit, status, and expiry are bound | Pass | Restore and verify the exact immutable artifact set |
| 17 | Existing private endpoints can be disconnected | Management snapshot covered eight endpoints | Pass | Require `Succeeded` and `Approved` before completion |
| 18 | A successful apply can remain unconverged | Workflow reruns Terraform with detailed exit code | Pass | Block receipt unless post-apply plan is empty |
| 19 | A post-apply check failure cannot safely rerun apply | Claim existed without a receipt | Critical | Verify claim, skip Terraform apply, and resume post-checks |
| 20 | Targeted plans can leave console output empty | Static Web App remained in exact Terraform state | High | Resolve hostname from the state-bound resource id through ARM |
| 21 | Root-owned action cache can block checkout | `infra/None/.cache` caused `EACCES` | High | Remove only that legacy path before checkout and isolate future cache |
| 22 | `runner.temp` is invalid in job-level environment | GitHub rejected workflow parsing with HTTP 422 | High | Export `$RUNNER_TEMP` path through `GITHUB_ENV` in the prepare step |
| 23 | Read API can deploy without real stewardship bindings | Latest revision failed at startup | Critical | Bind deployment Variables and enforce resource preconditions |
| 24 | Inventory job omits required runtime config | Recovery delta failed with eight missing vars | Critical | Inherit the shared core config map in the job |
| 25 | Workflow definition identity omits action catalog digest | New catalog collided with an older immutable row | Critical | Migrate uniqueness to include the catalog digest |
| 26 | Dev PostgreSQL keeps public access and broad Azure firewall | Private endpoint was already approved | High | Close public access whenever private networking is enabled |
| 27 | Targeted gateway plans omit the inventory reconciliation Job | Live execution retained the old image and failed with eight missing runtime variables | Critical | Target the inventory Job with core, canary, and realtime publishers; pin the address in workflow tests |

### Verification evidence

- Full-topology protected plan `plan-30154144825-1` completed with 4 add, 2 in-place change, and
	0 destroy after managed-identity login, private state init, egress, live Azure preflight, and
	destructive-plan checks.
- Verified-image plan run `30156461386` stopped before artifact storage because the fail-closed
	gate found the intended broad PostgreSQL firewall retirement. The hardened gate passes that one
	pure delete and rejects an unrelated delete plus a replacement at the allowlisted address.
- Exact apply run `30157115500` produced a receipt after convergence, migration, latest-revision
	health, and canary checks. A fresh inventory execution then proved that the gateway target set had
	not converged the Job's shared runtime configuration, so acceptance remains open pending reapply.
- Exact-plan, topology, workflow transport, cleanup, and derivation tests pass with strict mypy,
	Ruff, and the complete fast gate stack.
- Exact apply receipt and post-apply runtime evidence are required before this unit is complete.

## Remaining work units

The next unit starts only after every accepted finding in the current unit is implemented, tested,
and committed. Later units add their own 10-or-more-point critique table and close every accepted
Low-or-higher finding before advancing.

## Completed hardening units

| Unit | Commit | Executable evidence | Result |
|------|--------|---------------------|--------|
| Pantheon event boundary | `d83796ae` | 611 agent tests; 1,799 exact-commit selected tests | Complete |
| Approval decision delivery | `3606aec6` | 132 focused tests; 10,231 exact-commit selected tests | Complete |
| Ordered inventory delta projection | `44d32236` | 8 boundary tests; 2,037 exact-commit selected tests | Complete; live PostgreSQL cases await CI |
| Independent conversation charters | `26bd1db8` | 616 agent tests; citation drift repaired by `3451377c` and 1,091 selected tests | Complete |
| Offline provisioning inspection | `77ce624d` | 107 deployment CLI tests; 445 exact-commit selected tests | Code complete; public trust root remains blocked |
| Approval load intelligence | `ca0031d3` | No-drop simulation, quiet-hour/critical bypass, grouping, fatigue, and reminder tests | Complete |
| Live inventory ordering proof | current main evidence | Six PostgreSQL migration/snapshot/delta integration cases in a dedicated temporary database | Complete |
| Semantic agent routing | current main batch | Frozen multilingual charter vectors, zero-call T0 paths, threshold/margin abstention, provider-error fallback | Complete |
| Agent read-tool parity | current main batch | 30-tool exact-owner registry, timeout and error holds, bounded sensitivity-gated output, policy/evidence attribution, and health counters | Complete |
| Connected/offline recovery runbooks | current main batch | Protected-plan, signed-kit, and startup-readiness statuses map to safe replacement, fresh evidence, and governed rollback drills | Complete |
| Deterministic/model cost evidence | current main batch | Frozen runner reports tier share, calls, tokens, latency, cost, abstention, verifier failures, quality, and blocking thresholds | Complete; current evidence fails the release gate |
| Offline trust ceremony readiness | current main batch | Bilingual role, threshold, expiry, packaging, rotation, and disconnected-drill procedure | Prepared; production root ceremony remains external |

Every unit passed `scripts/verify.sh --fast`, strict mypy, Ruff, bilingual translation, document
size, punctuation, customer-scope, catalog, stewardship, architecture, and integrity gates.

## Prioritized residual plan

FDAI should not be described as fully ready until these work units meet their exit criteria.

| Priority | Work unit | Why it remains | Observable exit criteria |
|----------|-----------|----------------|--------------------------|
| P0 | Public offline trust bootstrap | In-repo verifier and ceremony controls are ready, but no production root authority exists | Threshold ceremony completed outside CI; public TUF root packaged in wheel; delegated release metadata verifies on a disconnected host; tamper, expiry, rollback, mix-and-match, wrong-version, and wrong-platform drills fail |
| P0 | Private-network onboarding acceptance | Component probes and runner IaC exist, but no single acceptance proves bootstrap to observe-ready on the actual isolated runner | Fresh subscription run completes policy preflight, private state bootstrap, exact plan, apply, DNS/TLS/identity/ARG/Event Hubs/PostgreSQL probes, inventory promotion, 15-agent startup, and sanitized handoff report |

## Readiness verdict

The architecture is directionally sound and stronger than a typical agent demo: role separation,
typed pub/sub, deterministic-first routing, fail-closed execution, durable state, approval identity,
inventory generations, and audit evidence are real implementations. The project is not yet fully
ready for the stated resident-operations-team promise. The remaining P0 items are operational proof
and load-intelligence gaps, not reasons to weaken the current safety boundaries.
