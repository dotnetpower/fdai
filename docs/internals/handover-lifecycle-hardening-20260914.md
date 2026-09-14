# Human-agent handover implementation and hardening

This engineering record tracks the bounded source-delivery work for
[issue #946](https://github.com/dotnetpower/fdai/issues/946). It separates local implementation
evidence from the provider configuration, live cohorts, deployment, and independent promotion
owned by [issue #458](https://github.com/dotnetpower/fdai/issues/458) and its dependencies.

## Scope and evidence rules

- Source delivery is authorized through an opened pull request, not deployment or automatic merge.
- Existing shadow and promotion gates remain closed until their independently required evidence
  exists. A new boolean, an accepted request, or passing synthetic tests cannot grant authority.
- Tenant values and credentials remain outside source, chat, test output, and this record.
- Each stage requires at least ten distinct critique rounds. A round records a hypothesis, the
  inspected or executable evidence, the change if needed, and the residual disposition. Repeating
  a test does not create another review round. A clean round may make no source change.
- A stage with a confirmed unresolved Medium or High finding does not pass. External prerequisites
  remain blocked rather than being relabeled Low. No later stage inherits an unearned pass.
- Unit, integration, external-provider, and governed operational evidence are separate claims.

## Revised design and sequence

| Stage | Scope | Required exit |
|-------|-------|---------------|
| S0 | Reconcile the implementation contract and task boundaries | Review the existing owner documents; make source, runtime, and deployment gaps resumable. |
| S1 | Revoked ownership commands and fair reconciliation | Regression tests reproduce both defects before repair; revocation, replay, revision, pagination, and provider-failure boundaries pass. |
| S2 | Assignment and knowledge service handoffs | Versioned events preserve authenticated request identity and inert proposal semantics; independent services never use a shared mutable workflow as authority. |
| S3 | Assignment effects and approval continuity | Exact review, ownership receipt, allowlist, replacement coverage, immutable action, and independent promotion boundaries remain enforced. |
| S4 | Knowledge goals, acceptance, and fatigue | Current ownership and admitted evidence gate every transition; independent review, required evidence, replay, and interruption budgets are tested. |
| S5 | Operational readiness and recovery evidence | Local readiness reports missing external prerequisites truthfully and supplies bounded drill/receipt contracts without invoking a provider. |
| S6 | Final integration review and source delivery | At least ten final rounds, exact task-owned validation, local commits, verified non-force push, and an open PR. |

The primary design owners remain the four documents in `docs/roadmap/interfaces/`:
`human-agent-assignment-and-knowledge-handover`, `human-agent-assignment-implementation-plan`,
`agent-stewardship-and-handover`, and `agent-stewardship-operations`. This record is evidence and
work planning, not a competing source of runtime authority.

## S0 design critique and revision

| Round | Critique | Evidence and revision | Disposition |
|-------|----------|-----------------------|-------------|
| S0-01 | Local code completion could be confused with operational readiness. | The owners distinguish implemented from validated; live IAM, escalation, and proactive promotions have no current receipt. Keep them separate. | External gates remain blocked. |
| S0-02 | The old plan instructs direct work on main. | The current repository contract requires a task branch or worktree; this change uses an isolated task branch and preserves the primary checkout. | Revise the delivery wording. |
| S0-03 | Package 4's merge consumer could conceal its missing request producer. | `postgres_iam.py` retains inert proposals; `bootstrap_core.py` binds only the matching-merge coordinator. Treat request-to-PR and merge-to-IAM as separate legs. | S2 requires boundary evidence. |
| S0-04 | Same key prefixes do not prove service data delivery. | The migration permits namespace-owned shared `state_kv`; existing tests seed both shapes into one store. Do not claim separate databases are already disconnected. | S2 must test real service-role contracts. |
| S0-05 | Removing the enforce refusal would grant unreviewed IAM authority. | `identity/direct_api.py` refuses enforce and revocation deliberately. Reuse the authoritative promotion and executor boundary; do not invent an enabling flag. | No authority change in S1. |
| S0-06 | A stale invitation can authorize later commands. | The previous memory-only reproduction removed the ownership mapping, then successfully snoozed without an ownership read. | S1 adds regression before repair. |
| S0-07 | Bounded reconciliation could permanently starve later cases. | The previous memory-only reproduction observed one of two cases in three passes at limit one. | S1 requires progressing bounded scans. |
| S0-08 | Retry identity can conceal a changed payload. | Goal commands replay on actor, operation, and revision alone. Review payload binding before accepting a replay. | S1 review target, not a claimed fix. |
| S0-09 | Optional features could block the deterministic baseline. | Adaptive interpretation and standing authority have separate seams and promotion prerequisites. Preserve abstention and audited no-op as valid outcomes. | Keep H21/H22 separate and unpromoted. |
| S0-10 | Historical test counts could become invented current evidence. | The prior eight-file run passed 144 tests; this branch needs its own results after relevant inputs change. Every later row names the actual check. | No inferred percentages or production-ready claim. |

## Implementation and review evidence

### S1: revoked ownership and reconciliation

The initial regression run produced **24 failures and 16 passes** before the source repair.
The completed S1 selection passed **115 tests** across the Operator runtime, command guard, IAM
routes, Core production controls, and reconciliation worker. Ruff passed the six changed Python
files, format verification passed all six, and strict mypy passed the three changed source files.
These are local synthetic results, not deployed or provider evidence.

| Round | Critique and evidence | Action | Residual |
|-------|-----------------------|--------|----------|
| S1-01 | Revoked ownership still allowed all four subject commands; 16 parameterized current-owner cases failed before repair. | Re-read current mapping and exact source revision for every mutation. | No unresolved finding in this tested boundary. |
| S1-02 | Cached success bypassed revocation. `test_exact_command_replay_is_revalidated_after_ownership_removal` failed before repair. | Revalidate before the replay return. | No unresolved finding in this tested boundary. |
| S1-03 | Changed evidence digest, reference, or kind returned the old success; all three regressions failed. | Persist and compare a complete canonical command digest. | No unresolved finding in this tested boundary. |
| S1-04 | Acceptance could borrow the goal subject as the read principal. Independent-review regression failed. | Read as the authenticated reviewer while revalidating the goal subject; retain independent Owner checks at the command boundary. | No extra role or authority introduced. |
| S1-05 | Case differences and non-Owner or emergency roles could weaken review separation. | Pure guard tests cover normalized identity, subject ownership, and role eligibility. | No unresolved finding in this tested boundary. |
| S1-06 | Old replay records have no evidence of equivalent payload. | Fail closed on missing digest; test the legacy record explicitly. | Operators refresh old commands rather than receiving inferred success. |
| S1-07 | Ownership-provider failure must not become absence or permission. | Provider-outage test proves no requested state change and continued permitted evidence reads. | Provider recovery remains an external drill. |
| S1-08 | The first page repeated forever, including after a partial failure. Both page regressions failed before repair. | Advance the cursor only after the page finishes; retain it on store failure. | Sustained arrivals beyond scan capacity remain visible through truncation warnings. |
| S1-09 | Concurrent ticks, process restart, or retention could skip work or duplicate audit. | Serialize local cursor progress; verify restart-safe audit reuse and wrap after a shrinking page set. | Restart begins a fresh sweep, not an authority-bearing durable cursor. |
| S1-10 | HTTP permissions, worker composition, types, or formatting could regress. | Focused IAM and worker regressions pass with source type/format checks; corrected import, line-length, and final-newline findings. | No unresolved Medium or High finding within S1. |
| S1-11 | Two concurrent different evidence requests could share an outbox request digest even though sequential replay was fenced. | Bound `command_digest` into the atomic proposal payload; a barrier-verifier regression proves one successful write and one conflict. The five-file selection now passes 116 tests. | No unresolved finding in this tested race. |

S1 is complete within the tested scope. S2-S6 and the external gates below remain open; this
statement is not a whole-workflow Low-risk or completion claim.

### S2 design review: authority-bearing connection

The existing document-draft publisher and merge-effects worker are not an assignment-request
consumer. Wiring an arbitrary `PostgresIamAdapters` approved projection directly to
`AssignmentOwnershipCoordinator.open_proposal` would turn presentation into authority. It is not
an acceptable shortcut, even while the IAM executor remains in shadow mode.

The implementation must preserve these boundaries before S2 can pass:

1. Operator persists authenticated immutable request intent and verified human-review evidence.
2. A bounded, durable outbox publishes a versioned request reference and digest; broker acceptance
  never marks the assignment active.
3. Huginn admits the request, Forseti owns validation, Var carries the independent human review,
  and Saga seals the state transition through their existing owned pub/sub topics.
4. Only the exact approved case revision can open its digest-bound ownership proposal. Signed
  merge receipt consumption is a separate existing leg, not a substitute for steps 1-3.
5. A Core-owned result projection feeds the Operator read model without shared mutable workflow
  authority or a browser-derived approval.

No new `HandoverReviewer` role, duplicate handover state machine, caller-selected promotion flag,
or unverified `SignedHandoverClaim` is justified. Existing requester/target/reviewer/executor
separation and the four ordinary App Roles remain unchanged. The current generic EventBus
envelope does not authenticate a claimed human on its own; the connection needs an explicit
trusted ingress receipt rather than treating a payload role or source string as that receipt.

S2 implementation is not yet complete. Do not proceed to enforcement, claim a Low-only complete
workflow, or close the source-delivery issue on the strength of S1.

### S2 implementation and hardening

The source connection now runs Operator immutable receipt/outbox -> Huginn -> Forseti -> Saga ->
Var for independent review -> Saga -> Muninn case CAS -> Saga -> existing review-only ownership
artifact delivery. Operator reads the Core case/effect projection without importing Core. Goal
observation has a separate content-free read-only adapter and bounded fair scan. Neither path
grants IAM authority or knowledge promotion. The earlier S2 design-state paragraph above records
the pre-implementation checkpoint; this section records the subsequent evidence.

Agent role review: Huginn owns Event/Change ingress; Forseti owns Verdict judgment; Var owns
Approval; Saga owns append-only AuditEntry and remains a hard dependency; Muninn owns
StateSnapshot/context materialization. Thor remains the sole privileged executor and explicitly
ignores this non-action workflow. Odin observes it without counting an action. Their existing
declared subscriptions and publish ownership are unchanged; no new hot-path LLM is introduced.
Saga remains the only changed hard dependency. Layout and bilingual Pantheon parity tests pass.

| Round | Critique and observed evidence | Hardening or retained boundary | Residual |
|-------|--------------------------------|--------------------------------|----------|
| S2-01 | A hash over shared mutable `state_kv` does not authenticate an Operator request; the existing role had broad writes. | Added atomic insert-only receipt capture, Core-only case namespaces, an exact-role read adapter, and real SQL role-denial tests. | No unresolved source finding in tested role boundary; deployed migration remains external. |
| S2-02 | Invalid/expired notices could reserve the canonical intake key ahead of a valid source. | Notice-specific held audit namespace; later valid intake regression passes. | No authority from a hold. |
| S2-03 | Independent notices could overtake case creation or review revisions. | Partition by immutable Operator case; outbox waits for Core revision or expiry; real SQL order test passes. | Transport acceptance is not convergence. |
| S2-04 | Lease ownership or expiry might allow stale completion; a failed head could starve later requests. | Claim id and unexpired lease fence every closure; attempt ordering; PostgreSQL steal/duplicate tests pass. | Publisher remains stable-identity at-least-once. |
| S2-05 | Case CAS may succeed before its separate result write; timestamp equality alone cannot prove exact replay. | Full command receipt in the atomic case+audit snapshot; restart at all three operations and changed-key regression pass. | Old unsealed proposals are not backfilled as authority. |
| S2-06 | Wiring a worker directly to all lifecycle methods would erase agent ownership. | Existing declared owner-topic chain tested through live in-memory subscribers; missing binding is an audited hold. | No added agent, role, subscription owner, or executor capability. |
| S2-07 | Requester/target review, missing quorum, stale revision, expiry after intake, or Saga failure could advance a case. | Normalized independent Owner checks, elevated two-review quorum, each-stage freshness, audit-before-materialization tests pass. | Provider freshness and promotion evidence remain independent. |
| S2-08 | A forged materialized result or mismatched merge could open/apply the wrong ownership proposal. | Compare exact Core-only result; reuse idempotent review-only publisher; single PR and wrong/exact merge tests pass. | Live App installation, webhook, and provider recovery remain external. |
| S2-09 | Operator approval could be presented as applied access. | Read exact Core command lineage; `active` requires both effect references; absent Core is `awaiting_core`. | Console presentation polish remains S4; no membership effect inferred. |
| S2-10 | Knowledge scan counted only newly emitted rows, causing unbounded rereads and source starvation; malformed evidence could be dropped silently. | Bound scanned rows, rotate page/source priority, retain failed page, strict typed observations, independent stores and real SQL read/write isolation tests. | Candidate consumption and document ACL/deletion lifecycle remain S4. |
| S2-11 | Schema and role migration changes could be assigned to the wrong service or lose receipts on rollback. | Core owns shared triggers/table; dependent Operator grant; empty down/up passes and retained receipts block destructive rollback. Migration graph validates five branches,196 tables,12 transitions. | Deployment N/N-1 receipts remain external, not Low. |
| S2-12 | Wire dispositions accepted a reviewed create and held-success reasons. Four focused tests failed before correction. | Enforced operation/disposition/reason consistency and unsupported-version refusal; 15 contract tests pass. | No unresolved contract finding in tested combinations. |
| S2-13 | New handlers may be unreachable or absent from packages/tests; readiness might conceal missing schema. | Actual runtime bindings, required task supervision, outbox health, Core wheel inventory, service-suite registration; 18 layout/parity/package tests pass. | No source-stage completion claim for live infrastructure. |

Completed S2 focused selection: **355 passed, 1 skipped**. The skip is the unchanged optional PDF
report extra, unrelated to assignment. Included **14 actual PostgreSQL tests** with disposable
databases and explicit Core/Operator roles, and the full asynchronous agent-to-review-PR chain.
Ruff passes all task-owned Python paths; strict mypy passes 36 changed source modules. The Core
wheel/layout/Pantheon parity selection passes 18 tests. No live Graph, Azure, model, GitHub App,
tenant deployment, or runtime promotion was performed. S3-S6 remain open.

### S3 safety hardening checkpoint

The local safety slice passes **244 focused tests** and strict mypy on **21 source modules**.
It connects exact ownership-effect notices to the existing Huginn/Forseti/Thor shadow-HIL path,
not an enforce executor. The ordinary control loop records that owner handoff instead of invoking
a model or a second execution. The provider boundary verifies exact target receipts and inverse
rollback observations. The current-role supervisor loads the reviewed catalog and never defaults
to eligible. H05/H06 enforce activation and the reviewed revoke-request/duty-removal workflow are
still incomplete; the read-only replacement planner must not be mistaken for a bound revoker.

| Round | Critique / evidence | Hardening | Residual |
|-------|----------------------|-----------|----------|
| S3-01 | Shadow planning ignored the supplied case revision. | Exact integer revision is checked before any plan/provider path;5 regressions pass. | None in tested boundary. |
| S3-02 | Provider success did not bind the planned subject/group/operation. | Shared canonical target digest; mismatched receipt degrades without attributing or rolling back an unknown target. | Current external provider effect evidence still required. |
| S3-03 | Rollback returned success after inverse dispatch, before readback. | Verify the inverse membership; a 204-with-still-present member test refuses success. | Real provider rollback drill remains external. |
| S3-04 | String coercion could accept booleans/numbers as target identifiers or operation. | Typed plan identity and operation validation;4 negative provider-contract tests. | None in tested boundary. |
| S3-05 | Replacement could reuse the old person or cover the wrong agent/scope. | Exact active revisions, distinct provider subjects, one primary and independent fallback per scope. | Planner is inert, not a revoke authorization. |
| S3-06 | Revoking one assignment's group could remove access another active assignment still needs. | Bounded same-subject/same-role demand scan; unrelated assignments and other roles remain unchanged. | Bound revoke-review workflow remains open. |
| S3-07 | Missing eligibility silently allowed every escalation rung. | Enforce construction requires a verifier; fresh exact active person/ordinary-role checks use the real directory shape. | Runtime remains shadow; no promotion. |
| S3-08 | Provider outage could be treated as role loss and skip a person. | Audited unavailable hold; no advancement/exhaustion on failed identity lookup. | Live directory outage evidence external. |
| S3-09 | Shadow integrity failure resolved a live approval. Regression failed. | Observe the discrepancy without changing pending status or decision; repaired regression passes. | None in tested shadow boundary. |
| S3-10 | Approval could expire during role lookup, then still be delivered. Regression failed. | Recheck the current clock after I/O before claiming delivery; repaired regression passes. | Authority can still be checked again only at the normal decision boundary. |
| S3-11 | Catalog groups could be inferred by position or environment guessed as nonprod. | Explicit environment and exact audience bindings, unavailable reason, immutable bounded windows, confidence-gated pure compression. | Verified production forecast inputs and measured cohorts remain open. |
| S3-12 | A matching merge event had no actual IAM agent consumer and could fall into generic reasoning. | Exact-effect reader, Huginn normalization, Forseti shadow-HIL, existing Thor path;5 new chain/evidence tests plus prior merge regressions. | Direct adapter still refuses enforce and revoke; no authority change. |

S3 is a validated local safety checkpoint, not complete delivery of H05/H06. These remaining
authority-bearing connections cannot be labeled Low or silently enabled. Independent goal/knowledge
work can be prepared without using those unavailable effects; final delivery must report them.

S3 follow-on review S3-13 connected the replacement planner to the existing revoke ActionType's
shadow adapter with bounded explicit replacement revisions, preserving the unconditional enforce
refusal. Its focused adapter/runtime/catalog selection passed66 tests, including a real planner
through the adapter and a refusal to convert that plan to enforce. This closes the previously
unbound shadow plan, not provider mutation, reviewed old-duty removal, or promotion. The remaining
provider-effect workflow stays held and is not reclassified Low.

S3-14 reviewed token destination confinement: the membership provider previously accepted an
arbitrary HTTPS host. It now permits only the implemented Graph endpoint/port before token
acquisition. Four destination-refusal regressions pass; the final provider/IAM-reader/replacement/
catalog safety selection passes58 tests. Source rollback semantics and shared plan digests remain
unchanged. The separate bootstrap/wheel checkpoint passes67 tests on the updated catalog.

## External completion gates

- [ ] Current deployment identity and v2 coverage readback, GitHub App installation and token
  refresh, signed webhook, one draft/replay/reviewed-merge/notification/audit/identity-recovery drill
  ([#458](https://github.com/dotnetpower/fdai/issues/458)).
- [ ] Teams A1 plan consumer, approval-bot provisioning and package, provider consent and install,
  authenticated decisions, and selected A2/A4 notification receipts
  ([#942](https://github.com/dotnetpower/fdai/issues/942),
  [#303](https://github.com/dotnetpower/fdai/issues/303),
  [#944](https://github.com/dotnetpower/fdai/issues/944)).
- [ ] Governed document lifecycle, ACL/protection/deletion/restart and performance evidence
  ([#424](https://github.com/dotnetpower/fdai/issues/424)).
- [ ] Exact-plan, current-human-approved standalone deployment; no GitHub Actions tenant apply
  ([#803](https://github.com/dotnetpower/fdai/issues/803)).
- [ ] Independent IAM, non-response, and proactive promotion cohorts: 30 days or 100 assignment
  cases, 20 non-production membership cycles, historical timing plus 50 pending approvals, and
  20 mapped-user handover pilots as specified by the implementation-plan owner.
