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

### S3 continuation design: reviewed reverse-order lifecycle

The resumed checkout is the unchanged `d737bdb535e0725120e19e97aff28f91d25e772a` checkpoint.
The original grant approval does not authorize removal. A removal uses a new immutable assignment
intent binding the old case revision and exact replacement revisions, through the existing
Operator receipt and fixed-agent review path. It does not introduce a second authorization store.

The reverse effect order is `approved -> iam_applying -> iam_revoked -> ownership_pr_open ->
revoked`. The ordinary grant order is unchanged. A revoke intent can never become `active`, and
an IAM dispatch acknowledgement is not an IAM effect receipt. Core old-case goal mutations are held
before a revoke attempt; a failed attempt never silently reactivates that assignment. Only an
independently verified removal effect permits a review-only old-duty proposal, and only its exact
signed merge closes that proposal. Unrelated duties, roles, maintainers, and channels are retained.

Design critique: (1) do not reuse grant reviews; (2) do not reverse the order for grants;
(3) bind original and replacement revisions; (4) do not treat a shadow plan as removal;
(5) retain an interrupted old-case hold rather than guessing restoration; (6) use the existing
Saga-sealed command chain; (7) do not infer current people from old active-case receipts;
(8) do not remove non-platform duties from a global map; (9) do not publish against a stale base;
(10) leave enforcement, provider drills, and promotion evidence explicitly unavailable.

This is a source-continuation design, not an enforcement pass. The current #946 exit criteria
explicitly separate locally verifiable delivery from the operational #458 gates. A completed
source boundary therefore does not complete S3 enforcement or lower an external blocker. Independent
knowledge work does not use unavailable IAM effects, and final delivery still needs its own complete
local evidence. No stage inherits an unearned operational pass.

### S3 continuation review: reverse-order source boundary

| Round | Distinct hypothesis and evidence | Hardening / result | Residual |
|-------|----------------------------------|--------------------|----------|
| S3-15 | A removal could inherit the original grant's approval. `test_grant_history_cannot_supply_the_new_revocation_review` exercises an active original and unreviewed new case. | Separate immutable intent and existing independent review chain; the original stays active until the reviewed pre-effect hold. | Current execution approval remains separately blocked. |
| S3-16 | Subject, role, scope, duty, old revision, or replacement pins could change inside an approved removal. `test_revocation_cannot_substitute_another_target_or_duty` and changed-pin replay cover them. | Exact immutable references and canonical digests; changed intent conflicts. | No relaxed target matching. |
| S3-17 | Reverse ordering might allow grants to skip ownership or removals to become active. State and legacy-serialization regressions pass. | Separate opposite effect edges; grant order and historical digest inputs retained. | Provider receipt ingestion still separate. |
| S3-18 | Two removals could use the same original, or interruption could reactivate it. Concurrent-hold, restart, and Core goal-mutation regressions pass. | Original CAS hold has one immutable removal identity; interruption stays held. | Operator goal authority reconciliation remains S4. |
| S3-19 | Removal could be silently read as a grant by an old consumer. The new v1 refusal test failed before the fix. | Version 1.1.0 notices/results; all removal commands and cached results reject v1 downgrade; legacy reader fixture rejects v1.1. | Deployment N/N-1 drill remains external. |
| S3-20 | Forseti's fixed apply ActionType could rewrite a verified revoke proposal. Actual Huginn/Forseti/Thor subscription regression passes after preserving the Core-verified type. | Existing owner topics, HIL verdict, shadow ceiling, and no execution are retained. | No AgentSpec or runtime promotion change. |
| S3-21 | Candidate labels alone might open a duty-removal PR without an audited review. Actual fixed-owner chain plus bounded recovery test passes; unsealed synthetic source is held. | Resolve exact Core-only review result and independent IAM effect before review-only delivery. | Live effect observer remains blocked. |
| S3-22 | Map drift, replacement state/revision drift, or unrelated entries might be removed. Five drift cases plus complete map comparison pass. | Remove only exact old platform duties; preserve unrelated agents, maintainers, channels, and roles. | Current deployed map and Git-host concurrency proof remain required. |
| S3-23 | Exact matching merge could publish a new grant or lose old-case closure after interruption. Wrong-digest and interrupted closure/replay tests pass. | Revoke terminal never emits grant; original stays held until exact merge replay repairs closure. | No remote merge was performed. |
| S3-24 | Another uncertain or degraded grant might still need the membership. Two regressions failed before repair. | Preserve active, applying, and degraded other grants; read-only bounded scan still refuses incomplete evidence. | Enforce requires a membership-target distributed lock, not a case-only lock. |
| S3-25 | An arbitrary rollback response could be reported as restored. Wrong-outcome and wrong-target tests failed before repair. | Require ROLLED_BACK and exact inverse target digest. | Real independent rollback drill remains external. |
| S3-26 | HTTP exact lookup might return another person/group, while disabled-user removal was impossible. Three failures reproduced. | Check exact person and provider; inactive target allowed only for removal; Owner and pre-I/O schema gates tested. | No Graph request made. |
| S3-27 | A new optional field could break old durable grant retries. Real PostgreSQL replay failed before correction. | Omit absent revocation from grant serialization; original immutable proposal and digest replay. | Existing SQL receipt ownership unchanged. |
| S3-28 | The public additive renderer could accept removal intent. Regression failed before repair. | Explicitly refuse removal in grant renderer; only the post-effect removal renderer accepts it. | None in tested renderer boundary. |
| S3-29 | Earlier review alleged unstable identical shadow retry identity. Exact repeated-plan and own-hold retry tests pass. | Rejected unsupported allegation; no invented idempotency rewrite. | A changed reviewed plan remains a different revision. |

The completed local selection passed214 tests; the SQL role/receipt selection passed16 tests and
the additional actual PostgreSQL legacy-replay regression passed1. The selections overlap with
earlier checks and are not summed into a historical total. Ruff and format pass33 task-owned
Python files. A prior strict-mypy pass covered23 source modules; later changes still require their
own final type check. This source boundary does not resolve H05/H06 enforcement, live role and
map readback, membership-target locking, independent observer ingestion, rollout, or promotion.

### S4 source design: evidence acceptance and interruption budgets

Use a shared versioned six-slot checklist contract, not arbitrary document kinds or an LLM's
assessment of completeness. Each slot has either an admitted exact document reference/digest or
a reasoned not-applicable claim. Readiness is derived from all six slots. Independent Owner
acceptance binds the exact goal revision and evidence digest; high-impact goals also require a
distinct current backup acknowledgement. No source creates IAM, catalog, or execution authority.
Legacy one-document goals are incomplete rather than silently accepted under the new contract.

Session admission revalidates current subject, ownership revision, fixed target agent, nonterminal
goal, and server-owned interruption guard. A durable per-subject claim enforces one active session,
at most three unique request identities, and a non-sliding five-minute window across restart.
Same request replay consumes no extra question; changed payload conflicts. Exhaustion holds the
handover branch without blocking ordinary Console access, and never invokes a model to infer budgets.

Design critique: fixed slots avoid invented taxonomy; acceptance and backup are independent; source
withdrawal invalidates review; missing legacy requirements cannot imply completion; shared contracts
cannot import Core; repeat identities bind whole content; budget reservation precedes narration;
clock expiry is exact and non-sliding; one subject session spans agents; declined/stale/accepted
goals never reopen through conversation. Accountable candidate/withdrawal consumers remain a separate
S4 boundary with their own typed owner chain and audit requirements.

### S4 accountable knowledge continuation design

The existing worker's source labels do not constitute agent ownership. Replace its three inert
candidate emissions with one versioned, content-free source notice over the ordinary Huginn
ingress. The notice pins the source namespace, goal id, revision, observation digest, and bounded
check window. The worker is a mechanical scheduler; its delivery receipt is never an agent verdict.

Forseti re-reads the exact source and independently checks current document admission through a
same-venue, boolean-only SQL read capability. It emits a non-action Verdict; missing bindings and
malformed data hold, and withdrawn or conflicting sources never become eligible. Saga seals the
Verdict before Muninn records the source revision in its own durable context projection. Saga
then seals Muninn's StateSnapshot. Norns consumes that seal, applies its existing three-perspective
consensus, publication ceiling, and rate limiter, and publishes only a review-required candidate.
Mimir independently rechecks its source and records the inert review disposition, which Saga audits.
No handler synthesizes a Rule, ontology fact, measured recurring pattern, or promotion receipt from
one document. Existing compilation, shadow dwell, reviewed catalog PR, and promotion remain separate.

Each owner stores only its own idempotent stage projection; the next owner consumes the typed
event, never another owner's mutable stage row as authority. Source revisions and withdrawal
tombstones prevent an older admission from reviving revoked evidence. Periodic notices recheck
source availability even when the goal revision did not change, and retained source identities
allow a deleted goal to produce a withdrawal. Read-time retrieval continues to require source ACL
and availability; candidate withdrawal never impersonates document deletion or changes another
service's retained content. Conflicting explicit evidence is routed by Forseti to Odin for an
audited clarification-required decision, never resolved by text similarity or a made-up winner.

Role review: Huginn owns Event ingress; Forseti owns Verdict and ArbitrationRequest; Odin owns
ArbitrationDecision; Muninn owns StateSnapshot; Norns owns RuleCandidate; Mimir owns Rule; Saga owns
AuditEntry and remains the hard dependency. All use existing declared topics; no AgentSpec, role,
new agent, hot-path model, Var approval, Thor execution, or Vidar recovery authority changes.

Design critique and revision: pin namespaces to prevent cross-source collisions; keep the source
private and transport content-free; do not count old checklist acceptance; distinguish missing
source from temporarily unavailable I/O; revalidate at every materialization; preserve negative
withdrawal even when positive publication is disabled; use owner-local CAS plus audit; never count
broker delivery as Mimir receipt; retain source identities for deletion recovery; and keep semantic
candidate compilation and external lifecycle/performance evidence explicitly separate.

### S4 review evidence: locally executable boundaries

| Round | Hypothesis and observed evidence | Result and residual |
|-------|----------------------------------|---------------------|
| S4-01 | A single document could imply all requirements. Shared checklist and Core/Operator slot tests exercise all six omissions. | Explicit slots or per-slot reasoned exemptions; unassigned evidence counts as none. |
| S4-02 | Evidence completeness could substitute for human review. Owner and distinct-current-backup tests pass for documents and exemptions. | Review digest binds subject, agent, scope, template, impact, and source. No IAM or catalog authority. |
| S4-03 | Shared acceptance accepted self review, padded identity, or a future revision. Three regressions failed before repair. | Exact independent reviewer and prior positive integer revision are required. |
| S4-04 | Old accepted one-document rows still projected success. Regression failed before repair. | Read-only legacy projection is blocked; original history remains, and an authenticated CAS can adopt new requirements. |
| S4-05 | A backup case substituted for an ordinary role or the implemented provider. Three regressions failed. | Current ordinary human role plus exact Entra backup duty; no emergency-role substitution. |
| S4-06 | First Owner review relied only on a token, and Core could accept without current reviewer evidence. Both regressions failed. | Current roster checks for new/prior reviewers; Core's explicit read-only eligibility port is required. Unbound Core paths hold. |
| S4-07 | Ownership alone could authorize a Reader to inspect a document. Actual ingestion role policy was inspected; Reader-backup negative test passes. | Contributor/Approver/Owner read-role proof retained; Reader-only group proof remains unavailable, not granted. |
| S4-08 | A second slot update restored the preceding command receipt. The second-slot replay regression failed before repair. | New revision and complete command digest survive checklist merging; changed payload conflicts. |
| S4-09 | Cross-agent reuse might copy review authority or stale ownership. Accepted-source reuse and changed-revision replay tests pass. | Same person/scope/current revision only; target copies evidence but no reviews. |
| S4-10 | Core revocation holds might not stop Operator contribution. Actual PostgreSQL role tests pass. | Negative-only exact namespace read; unrelated subjects/agents unaffected, no Core write permission. |
| S4-11 | Session retry/restart/concurrency could refund question or time budgets. Actual PostgreSQL four-request race admits three; restart reuses exact deadline. | One subject session, three unique turns, fixed five minutes, two weekly sessions; no raw prompt in budget. |
| S4-12 | Clock rollback could extend a session. Regression failed before repair. | Time before persisted start is held; each turn rechecks current ownership, identity, workload, and closed state. |
| S4-13 | Scheduler labels could masquerade as agent candidate consumption. Actual owner-subscriber tests now exercise the whole chain. | Mechanical source notices only; Forseti -> Saga -> Muninn -> Saga -> Norns -> Mimir -> Saga, no ActionRun or catalog mutation. |
| S4-14 | Source API failure could be treated as deletion or permission. Read-only checker tests distinguish changed, absent, and unavailable sources. | Only authoritative absence/lifecycle loss withdraws; I/O failure holds. Every owner rechecks. |
| S4-15 | Core might receive raw document-table authority. Actual SQL tests deny Core/Operator document SELECT and Operator function execution. | Core-only source-bound boolean function checks exact revision, uploader, digest, availability, governed disposition, index, and retention. |
| S4-16 | Same-name Core/Operator goals, reordering, or restart could restore a withdrawn source. Namespace and monotonic owner-CAS tests pass. | Withdrawn source revision stays withdrawn; source and owner identities remain distinct. |
| S4-17 | Ordinary redelivery was classified as a Mimir flood. Actual subscriber regression failed before repair. | Revalidate source, then reuse only this owner's matching receipt before repeat-counting; live source withdrawal still wins. |
| S4-18 | Deleted goals could retain only the first observed revision. Regression failed with revision1 instead of2. | CAS advances the tracked source revision; fixed-window rechecks survive deletion and restart. |
| S4-19 | Source reads could outlive their notice or Saga failure could still advance memory. Clock/revision I/O and failed-Saga tests pass. | Expiry/change holds; no Muninn or candidate receipt after failed Saga seal. |
| S4-20 | Old chunk ACL metadata could survive source deletion or protection change. Focused retrieval tests pass. | Exact goal evidence plus current source/ACL reader required before returning a chunk; unbound retrieval is unavailable. |
| S4-21 | Console accepted malformed reviews or another goal response. 21 new decoder/API cases pass. | Strict slots/reviews/identity/revision/time and exact requested goal; existing four-file UI selection also passes. |
| S4-22 | Checklist overflowed at320px under200% text and spacing overrides. Browser assertion failed before CSS repair. | Minmax grid and wrapping pass the same desktop-first four-width, keyboard, disclosure, forced-color, reduced-motion scenario. |

Latest focused evidence: the knowledge/audit/actual-SQL selection passed40 tests; the Console
five-file selection passed41 tests; layout/Pantheon/migration-contract selection passed15 tests;
the isolated actual-document-route browser scenario passed after the reflow repair. These overlap
earlier selections and are not summed. Static cleanup, final combined input validation, public
doc parity, and operational readiness remain unfinished. No authenticated full-stack, live model,
Graph, deployment, permission grant, or candidate promotion evidence is claimed.

### S5 design: truthful readiness and bounded recovery

Add a content-free, observation-only lifecycle report to the existing bounded reconciliation tick,
not another executor or polling daemon. It reports exact sampled counts, malformed/partial data,
observed effect-interval samples, source-owner dispositions, and existing enabled preference.
Missing metrics are null, not zero; partial scans are labeled. Alerts name overdue convergence,
degraded assignments, source holds, invalid data, and unresolved prerequisites without sending a
notification or inventing operational measurements. Store the report with an atomic audit and an
explicit expiry; the Owner-only Operator read refuses stale or malformed snapshots.

The source report cannot assert operational readiness. Enforce dispatch, membership-target locking,
independent live effect observation, current replacement identity, exact-plan deployment, and
independent cohorts remain blocked. Group/schedule scoped ownership and effective-date realization
remain explicit source-scope gaps rather than being mislabeled external or Low. The report provides
resumable next steps but never edits a DB row as a recovery instruction, changes a role, reenables
an action, or promotes a candidate. Existing runtime enablement and independent promotion axes stay
authoritative; no new flag may remove a guard.

Design critique: bound scans; label partial counts; reject future timestamps; keep empty metrics
null; separate source presence from deployment proof; let kill switches only lower eligibility;
store report and audit atomically; expire stale snapshots; restrict detailed reads to Owner; and
retain every unimplemented/external requirement in the report and delivery evidence.

### Continuing upload-link boundary review

The actual document route currently binds one selected checklist slot to an entire upload batch.
The first admitted file can occupy that slot, leaving later uploaded files unlinked. The revised
UI accepts one file per explicit handover slot, rejects multi-file drops before content transfer,
and preserves the existing ordinary multi-file document workflow. Per-file slot assignment is
deferred rather than inferred from document contents. A rejected selection is visible and blocks
the old queued selection until the user selects one file again; it never silently truncates input.

Independent critique: the browser restriction is guidance, not admission authority. Goal revision,
current ACL, source disposition, and unique slot assignment remain server-validated. A second
failure hypothesis is that a document-processing warning overwrites the more important failed-link
notice. Preserve both outcomes and exercise the actual route with synthetic API responses; these
checks do not establish authenticated ingestion or operational readiness.

### Continuing current-source SQL review

Real service-role tests reproduced an indefinitely retained denial after a completed removal,
even when a separately verified new grant was active, and an unrelated-scope hold blocking a
Core goal. Ongoing removal holds still override every new grant. Closed removal history permits
contribution only when another current, same-person, same-agent, same-scope Entra grant has both
effects; a Core goal must additionally pin that exact active case. A global Operator map can prove
only `scope:platform`, never a scoped assignment by inference.

The direct reader also accepted a notice with a different revision. Existing owner source checks
already compare revision and digest before and after I/O; no whole-chain admission bypass was
demonstrated. Bind the contribution read itself to the same exact goal identity, revision, and
digest, so this port cannot silently check another snapshot. Malformed or over-bound inputs remain
unavailable. These changes do not add SQL writes, document reads, IAM effects, or promotion.

### Reader-backup admission design and critique

The existing ingestion access policy permits an uploader, an ordinary Contributor/Approver/Owner
role marker, or a verified member of a document's configured reader group. Handover must use that
policy without turning the backup duty itself into document access. Retain membership identifiers
already proved by the uncached Entra application-role group expansion as private directory metadata;
do not add them to the browser projection, request body, goal review, or event. A direct App Role
assignment proves no group membership. Unsupported or missing membership evidence remains held.

A new Operator-owned migration exposes only bounded booleans for strict document admission and
reviewer access. It grants no raw document SELECT and performs no identity mutation. The existing
four-field verifier omits disposition, active index, and retention; test those inputs before
replacement. The new verifier requires governed, active, available, live-retention content and the
exact uploader/version/hash. Reader acknowledgement additionally joins current observed group
membership to the exact document ACL. First and retained backup reviews repeat this check.

Critique/revision: no token or caller-supplied group list supplies the proof, no new Graph operation
or permission is introduced, and a partial roster remains unavailable. Existing ordinary roles
retain the ingestion policy's read access. An absent migration or verifier cannot become an allow.
The alternate Core goal/retrieval bindings, semantic compiler, H10, and verified urgency remain
separate source work; implementing this reader does not close those requirements.

### Reader-backup continuation review evidence

The Reader-only document boundary is now implemented for memberships actually observed through
the existing uncached FDAI role-group expansion. This does not claim a complete directory group
census. No observed ACL match means deny; it never means a guessed membership. The production
Operator composition already binds the updated directory and SQL verifier. Required migration,
live directory permission, and deployed source evidence remain operational prerequisites.

| Round | Distinct critique and evidence | Result |
|-------|--------------------------------|--------|
| R-01 | A ready workspace draft passed the old boolean verifier; real SQL regression failed first. | New admission requires governed knowledge. |
| R-02 | Purged retention passed the old verifier; real SQL regression failed first. | Live retention is required. |
| R-03 | A tombstoned index passed the old verifier; real SQL regression failed first. | Active index is required. |
| R-04 | The JSON string `"true"` was coerced into availability; real SQL regression failed first. | Only the actual JSON boolean admits the source. |
| R-05 | A direct Reader App Role might imply membership. Provider and runtime tests distinguish direct grants from observed role-group membership. | No group is invented. |
| R-06 | Duty or goal metadata might supply an ACL match. Real goal commands reject missing/wrong current group despite injected goal metadata. | Only current directory evidence reaches the SQL reader. |
| R-07 | A prior Reader review might survive group loss during the acceptance sequence. Current-goal regression passes. | Final Owner acceptance holds when the prior backup loses access. |
| R-08 | Group evidence could leak to the browser or accepted record. Provider `to_dict` and accepted-goal tests pass. | Membership metadata stays private and is not review authority. |
| R-09 | Group and direct-role query order could erase or retain obsolete membership. Both provider orders and a later removal pass. | A fresh roster replaces prior membership evidence. |
| R-10 | Multiple slots might amplify document reads or allow unbounded groups. Deduplication and malformed/501-group tests pass. | One check per distinct document per review pass; bounded evidence only. |
| R-11 | Role, self-review, wrong digest/subject/version, or malformed ACL might override source checks. Real SQL matrix passes. | Each independent condition remains required. |
| R-12 | SQL functions could expose document content or survive rollback as a successful fallback. Real-role and rollback tests pass. | No Core/Operator raw SELECT; missing new function is unavailable. |
| R-13 | An administrator DSN was accepted by the evidence reader. Real SQL regression failed first, then passed. | Exact Operator SQL role and read-only transaction required. |
| R-14 | An unmapped backup probed a document ACL before duty eligibility. Regression failed first, then passed. | Agent/source revision checked before document ACL I/O. |

The final related Operator selection passed 35 tests; the updated real SQL fixture selection passed
48 tests. These overlapping results are not summed with earlier selections. Five source modules
passed strict typing; eight recent Python files passed formatting. The migration head/ownership/
dependency selection passed three checks. No Graph request was executed outside MockTransport.

The two additional upload-route regressions passed after reproducing multi-file slot ambiguity and
processing-warning overwrite of a failed evidence link. The direct Core contribution reader's
revision/digest, closed-removal recovery, scope, bound, and source-document checks passed eight
tests plus one subsequent global-map ceiling test. These are source and isolated-route results.

Classification correction: target-lock, isolated human-access Executor binding, and independent
IAM-effect ingress remain unfinished source wiring, not merely external prerequisites. Readiness
now lists them as source gaps. Current approval, provider identity, live drills, and cohorts remain
external gates; no blocker was downgraded to Low or marked operationally complete.

### Verified forecast timing design and critique

Use the existing Heimdall-owned forecast evaluator and transactional publication outbox as the
source, not caller-supplied `forecast_confidence` or an R-squared proxy. The evaluator will retain
its configured prediction-band confidence and computed breach ETA beside the exact episode payload.
No new model, collection, table, topic, or prediction authority is introduced. Legacy payloads that
lack these fields cannot compress human response windows.

Before parking an approval, the coordinator will resolve only the exact `forecast:<episode-id>`
correlation and Action target through a Core-role, read-only SQL adapter. A pure verifier compares
episode identity, detector/version, target, access-scope digest, feature cutoff, horizon, interval,
and retained publication metadata; it rejects closed, missing, stale, malformed, ambiguous, or
already-passed forecasts. The interval must independently clear the threshold. Its bounded result
is a process-local typed value, not a serialized caller boolean. Catalog timing accepts only that
value and records its content digest; ordinary contexts keep conservative timing.

Critique/revision: a forecast is uncertain evidence, not observed effect or permission. ETA derives
from the observed feature cutoff rather than request time, and confidence is the governed band
level, never fit quality. Source lookup is deadline-bounded; failure records a stable unavailable
reason while retaining the existing ladder. Replay must preserve the original parked deadlines.
No current or standing approval, executor identity, mode, or promotion registry changes.

### Verified forecast timing review evidence

| Round | Distinct critique and executable evidence | Result |
|-------|-------------------------------------------|--------|
| U-01 | Raw lead-time/confidence numbers shortened catalog windows without source proof; regression failed first. | Only the internal verified source type can supply compression. |
| U-02 | Producer might relabel fit quality as probability. Real evaluator regression proves confidence comes from the configured prediction band. | R-squared is not used as confidence. |
| U-03 | Request time might restart ETA. Evaluator and remaining-time tests bind ETA to feature cutoff. | Remaining lead decreases with the current clock. |
| U-04 | Wrong target, detector version, source digest, metric lineage, or evidence could substitute another episode. Parameterized source regressions pass. | Exact episode/publication identity required. |
| U-05 | Point prediction could bypass interval uncertainty. Both breach directions and point-outside-band tests pass. | The whole relevant near edge clears the threshold. |
| U-06 | Closed, negative, future, stale, or passed forecasts could still compress. Boundary matrix passes. | Missing urgency preserves normal catalog windows. |
| U-07 | An old outbox row might receive invented new confidence. Legacy/malformed metadata tests pass. | Old records remain valid for learning but provide no new timing proof. |
| U-08 | Low governed confidence might bypass the catalog threshold. The 0.80-band regression passes. | Existing confidence floor and starvation clamp remain authoritative. |
| U-09 | Read timeout or caller cancellation could trigger retry or hide cancellation. Focused tests pass. | One bounded lookup; timeout unavailable, cancellation propagates. |
| U-10 | A forecast could expire while the source is read. Slow-source attachment test passes. | Current post-I/O clock prevents compression. |
| U-11 | Replayed approval might extend or rewrite original deadlines. Actual coordinator test passes. | Parked action, original deadline, and non-execution remain unchanged. |
| U-12 | Runtime might expose an unwired Protocol or wrong SQL role. Real store/reader test and startup binder test pass. | Same-venue Core source, no startup query, no Operator/admin fallback. |
| U-13 | PostgreSQL normalizes offsets and incorrectly rejects the same source instant. +09:00 SQL regression failed first, then passed. | Original identity encoding and semantic time equality preserved without rewriting history. |
| U-14 | Formatting-only edits could alter module structure. Seven AST fingerprints matched; direct lint/format and strict typing followed. | No delegated validation of the dirty tree. |

Related forecast, HIL, actual agent publication, runtime, and SQL checks passed 104 tests. The
subsequent source/timezone selection passed 31; results overlap and are not summed. Eight source
modules passed strict typing. One test fixture initially used the wrong publisher property and
another relied on another suite's import order; both were fixed without changing product checks.
All provider interactions remained synthetic or task-only loopback SQL. Current timing cohorts,
authorization, live delivery, and independent promotion remain external gates. H10, alternate Core
goal/retrieval readers, semantic compilation, and executor/lock/effect-ingress source work remain
incomplete. No overall task completion or publication is claimed.

### H10 scope and temporal planning decision

The operator was asked whether group/schedule duty selection must remain separate from per-person
IAM approval. The response requested autonomous progress, not a grant to groups or future on-call
people. The safe implementation therefore models a review-only duty plan: explicit user, group,
or configured schedule subjects; exact agent and operational scope; half-open effective windows;
fresh bounded identity expansion; and a mandatory static person fallback for schedules. It never
creates one aggregate IAM grant or treats future schedule membership as current authority.

Keep `config/agent-stewardship.yaml` and its v2 global accountability contract unchanged. A scoped
plan is a versioned review artifact, not an implicitly loaded v2 overlay. Rendering retains scope,
time, exact source revision, identities, and unresolved coverage; it cannot silently write a scoped
duty into the global map. A real plan consumer and reviewed projection are required before H10 is
complete. Personal assignment ingress continues rejecting groups/schedules until separately modeled.

Critique/revision: future schedule coverage cannot be proved from today's on-call answer. Coverage
is observed at an explicit timestamp within the resolver validity window, never asserted for the
entire effective interval. Distinct declaration ids do not prove distinct humans. Duplicate or
overlapping same-subject duties, expired intervals, unresolved scopes, self fallback, stale expansion,
and missing primary/backup must be held or rejected. No test fake enters production binding.

### S5 observation-boundary review evidence

| Round | Distinct critique and executable evidence | Disposition |
|-------|-------------------------------------------|-------------|
| S5-01 | Empty state could be reported as zero latency or operational success. `test_empty_readiness_is_not_zero_latency_or_operational_success` passes. | Unmeasured interval is null; operational readiness stays false. |
| S5-02 | A sampled count could be mistaken for complete coverage. Partial-page test passes. | Exact observed/total and partial flag retained. |
| S5-03 | One malformed case could hide later valid observations. Invalid-case test passes. | Invalid rows counted separately; no success invented. |
| S5-04 | Provider dispatch time could be presented as verified activation latency. Effect-interval test passes. | Only two recorded effect times contribute; metric is explicitly interval, not product latency. |
| S5-05 | Future effects could produce a valid metric. Future-effect test passes. | Invalid future evidence supplies no sample. |
| S5-06 | A disabled preference could be treated as promotion. Disabled-preference test passes. | Existing enabled value only lowers eligibility; report always shadow. |
| S5-07 | Recovery, convergence delay, and source holds could collapse into one healthy status. Distinct-alert tests pass. | Separate reason codes; no automatic repair or notification dispatch. |
| S5-08 | Concurrent publication or restart could lose report/audit alignment. CAS and restart test passes. | Each accepted revision is atomically audited. |
| S5-09 | Failed audit could still produce a report. Audit-failure test passes. | No report on failed atomic write. |
| S5-10 | A stale/future report or clock rollback could appear current. Expiry, future, and rollback tests pass. | Owner reader holds; old report is not overwritten backwards. |
| S5-11 | A new endpoint could bypass Owner or be absent from real composition. Route tests and aggregate manifest regressions pass after exact197/42 route baseline updates. | Owner-only read, no provider writer, exact route ownership. |
| S5-12 | An old admitted source was counted as currently admitted. Regression failed before correction; readiness selection now passes21 tests. | Expired source check is stale and requires review. |

This is an implemented local observation boundary, not S5 operational acceptance. Missing H10,
alternate reader bindings, Reader-backup group proof, semantic compilation, urgency production,
external drills, and independent cohorts remain blocking remaining work. No row is relabeled Low.

### Integration review of the current checkpoint

| Round | Cross-boundary hypothesis and evidence | Result / limitation |
|-------|----------------------------------------|---------------------|
| I-01 | Old grant replay might change after the removal field and version upgrade. Actual PostgreSQL legacy replay and transport tests pass. | Legacy grant digest retained; removal never downgrades to v1. |
| I-02 | New removal approval could trigger an additive grant or premature duty PR. Actual agent and removal-delivery tests pass. | Fresh review, original hold, post-IAM draft, exact merge; enforce remains unavailable. |
| I-03 | Core hold could be lost in Operator contribution. Actual SQL read-boundary test passes. | Current negative hold blocks only matching subject/agent; no cross-service writes. |
| I-04 | Shared review records could let one API bypass Core or Operator checks. Combined goal/checklist tests and strict types pass. | Exact independent reviewers; alternate unbound Core paths remain held. |
| I-05 | A later login reused the same exhausted goal-only Deck session. Browser-open regression failed before adding login identity;83 focused Console/Deck tests pass. | Same login stays stable; next login remains subject-budgeted with the same goal suffix. |
| I-06 | Upload-to-Deck handoff might omit the server goal budget. Existing session-suffix and backend-context tests verified the goal is preserved; allegation rejected. | Upload now uses the same login-scoped key as invitation; no lexical or authority bypass. |
| I-07 | Mechanical source notices might also enter generic model/action handling. Normal-loop regression and actual owner subscribers pass. | Audited owner handoff only; no second workflow or ActionRun. |
| I-08 | Same-namespace replay, periodic checks, deletion, or audit failure could revive withdrawn evidence. Source-stage, scheduler, and failed-Saga tests pass. | Latest source identity and owner-local monotonic CAS; no mutable peer authority. |
| I-09 | A new Core document check could grant raw content or require wrong service order. Actual SQL denial tests and migration dependency-order test pass. | Boolean-only function; ingestion schema precedes Core consumer; no deployed grant executed. |
| I-10 | New routes or modules could be absent from packaged runtime. Wheel/composition selection passed168 cases plus an unchanged optional PDF skip;two intentional manifest expectations were corrected and passed separately. | Source packaging only; not rollout proof. |
| I-11 | Shared refactoring could exceed agent limits or expose private imports.37 agent/layout/parity tests,strict typing,and scoped Operator boundary gate pass. | Forseti1110 <=1111 baseline;Norns812 <=814;Operator state split preserves reexports. |
| I-12 | UI state and reflow could hide source uncertainty or break keyboard review. Strict decoder tests and isolated document-route scenario pass after a200%/320px overflow regression was repaired. | Synthetic API/real route only; full visual rubric and authenticated external states remain unverified. |
| I-13 | Formatting delegation could change symbol placement. Formatter diff exposed three class-indented `__all__` declarations; main restored them before passing86-file lint/format. | No delegated test result used; direct typed/import/test validation retained. |
| I-14 | Local passes or static blockers could imply full delivery. Scope and issue exit criteria were reread; source and external gaps remain explicit in owners and ledgers. | No task-complete, commit, push, PR, merge, or deployment claim. |

The integrated local slice passed451 tests before the final focused fixes; each subsequently
changed boundary has its own focused result above. Overlapping selections are not summed. The
remaining work below prevents overall completion and therefore prevents conditional publication.

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

## Second continuation: source restoration and H10 design

The 2026-09-14 continuation verified the same inherited HEAD, 100 tracked changed files,
49 untracked files, and an empty index. Existing changes are retained. The dedicated offline
environment reports Python 3.13.14; the editor environment lookup points to another checkout
and is not used for execution. Issues #946 and #458 remain open with distinct source and
operational exits. No new commit, publication, permission, or live provider call is implied.

Direct source inspection confirms `OnCallSchedule.current` and `OnCallShift` already exist.
The earlier exploratory assertion that this Protocol was absent is rejected. The existing
`GroupMembershipProvider` has best-effort semantics and the role roster is a bounded presentation;
neither can prove a complete current H10 expansion without a stricter reader. `ScopedDutyPlanner`
has no production constructor yet. Alternate Core goal readers and the unconditional human-access
enforce refusal remain actual source gaps, not external prerequisites.

### Revised H10 source sequence

1. Bind exact current scopes and configured rotations through a bounded deployment-owned catalog
  reader. Derive its revision from validated content, reread it at use, and never infer a child,
  parent, or platform scope. Reuse `OnCallSchedule`, not a duplicate schedule Protocol.
2. Add a strict read-only Entra duty resolver. Expand only exact configured group references into
  complete active-person observations. Missing identity fields, pagination truncation, unexpected
  destinations, time expiry, and provider errors hold; they never become partial coverage.
  A schedule result must identify the current shift and separately resolve its exact person.
3. Connect a typed ownership-only request to independent fixed-owner review, a versioned reviewed
  artifact consumer, and exact agent/scope projection. Group and schedule declarations are not
  personal IAM cases. Any later IAM request still names one current person and needs its own
  approval, safeguards, and effects. The global v2 map remains unchanged.
4. Revalidate source revision, current people, and effective windows at each consuming boundary.
  A reviewed declaration can remain future-effective, but today's schedule answer proves no
  future human coverage. Expired, replaced, conflicting, or partially observed sources hold.

Design critique and revision: catalog configuration defines allowed scope rather than external
resource truth; a reference is not provider permission; best-effort groups cannot prove coverage;
current schedule receipts cannot authorize future members; static fallback is independently read;
post-I/O checks cannot restart a freshness window; mid-read catalog drift invalidates the plan;
review binds immutable declarations rather than mutable expansion; replay retains the original
review and cannot bless changed content; and no request, projection, or fallback grants IAM.

H10 remains in progress until its real request, review consumer, and scoped projection are connected
and have their own ten or more distinct critique rounds. Subsequent work remains alternate Core
goal/retrieval admission, semantic compilation, isolated human-access execution/target locking/
independent effect ingress, Console recovery, paired docs/catalogs, and a new final integrated review.

### H10 current-source boundary review

| Round | Distinct critique and evidence | Result / remaining boundary |
|-------|--------------------------------|-----------------------------|
| H10-S01 | A scope removed during person reads still proved coverage; both new regressions failed first. | Planner rereads exact catalog revision before returning; the 30-test owning file passes. |
| H10-S02 | A caller revision or parent, child, wildcard, or platform reference could imply scope. | Current catalog tests admit only exact configured reference plus content-derived revision. Configuration is not observed resource truth. |
| H10-S03 | Startup caching could retain a replaced catalog. | Fresh-file read test replaces content and proves the old revision no longer admits. |
| H10-S04 | FIFO, symlink, oversized file, duplicate keys, or missing source could block or admit partial config. | Bounded regular-file reads, no-follow/nonblocking open, and strict decoder tests pass. |
| H10-S05 | Absent or string-valued active state could imply a live person. | Five malformed active-state cases and disabled/wrong-person cases pass; no passthrough identity proof. |
| H10-S06 | A truncated, duplicate, partial-user, or wrong-group expansion could prove two-person coverage. | Complete expansion only, at most 100 observed identities; each malformed case holds. |
| H10-S07 | Continuation query could be lost by passing an empty params mapping. The two-page regression failed first. | Preserve the exact next-link query with absent params; canonical two-page observation now passes. |
| H10-S08 | Continuation or redirect could send credentials to a different source. | Wrong group, host, fragment, empty/repeated link, and redirect tests all refuse before a second destination request. |
| H10-S09 | Provider failure or huge/ambiguous JSON could trigger retries or expose private output. | One-attempt 403/429/503 checks, streaming byte cap, duplicate-key rejection, and content-free exceptions pass. |
| H10-S10 | Current schedule response could count its secondary as a separate duty or prove future coverage. | Only the independently resolved current primary occupies the declared duty; future/stale queries make no directory call. |
| H10-S11 | Schedule outage could use an unverified fallback. | Real planner plus file schedule and synthetic Graph independently resolve the explicit fallback and distinct backup. |
| H10-S12 | Slow I/O, shift expiry, or clock rollback could restart validity. | Freshness begins at the query instant; post-I/O boundary tests hold rather than extend. |
| H10-S13 | Invalid object refs or cancellation could acquire credentials or turn into fallback success. | Invalid refs are rejected before token access; cancellation propagates. |

The current-source adapter file passes 42 focused synthetic tests. Its two source modules pass
strict mypy; all three new files pass Ruff and formatting. The separate pure-planner file passes
30 tests and both planner source modules pass strict mypy. These selections prove local contracts,
not production binding, live Graph permission, deployment, or H10 completion. No validation was
delegated and no repository-wide check was run.

### H10 connected review/observation checkpoint

The source path now has its own shared ownership-only declaration contract and transport `1.2.0`
inside the existing immutable assignment receipt/outbox. The existing fixed-owner callbacks route
the version to `ScopedDutyRequestProcessor`; no agent role/topic or personal IAM state changes.
The real Operator family has six scoped routes, exact current catalog exposure, and proposal-only
submit/review. Core binds actual current readers when the private catalog and read identity exist.
Two current independent Owners review a retained exact plan. Reviewed artifacts use the existing
draft publisher, an artifact-target lock, and prepublication intent plus terminal audit. A separate
GitHub GET reader verifies head review, human merge, immutable content, and current default-branch
content. The existing reconciliation publishes expiring, exact agent/scope observations only.

| Round | Distinct critique and evidence | Result / limitation |
|-------|--------------------------------|---------------------|
| H10-C01 | Group/schedule requests could be treated as personal IAM by an older reader. | Dedicated `1.2.0` marker requires the scoped source kind; `1.0`/`1.1` refuse it. Personal views exclude these proposals. |
| H10-C02 | Requester, current group member, backup or fallback could self-review. | Current reviewed-target exclusion and two distinct Owner reviews; scoped case tests pass. |
| H10-C03 | A retained first review could survive Owner-role loss. | Fresh first/prior reviewer checks block the second review. |
| H10-C04 | Reviewer I/O could outlive the source observation. Regression failed first. | Post-review and pre-CAS expiry checks hold. |
| H10-C05 | Persisted literal false accepted integer zero. Regression failed first. | Explicit pre-validation rejects coercion; canonical plan digest is revalidated. |
| H10-C06 | Interrupted result replay could report a later review's approved revision. Regression failed first. | Original command state/revision now persists inside case CAS; exact replay returns the original transition. |
| H10-C07 | Concurrent reviews or failed audit could grant two transitions. | One CAS winner and no write after audit failure; source stays revision-bound. |
| H10-C08 | A draft dispatch could be mislabeled merged or active. | No personal case or IAM result; current independent merge observation is separately required. |
| H10-C09 | Two artifact deliveries could open duplicate drafts or lose pre-effect intent. | Artifact-target lock, stable publisher key, immutable candidate and intent audit; duplicate and audit-failure tests pass. |
| H10-C10 | A bot, wrong head, dismissed review, wrong repository/base, or changed current file could prove ownership. | Synthetic GitHub source matrix checks each condition; source test file passes23 cases. |
| H10-C11 | Exact merge proof could outlive a source/shift transition. | Projection TTL is capped by merge, resolution, freshness, and the next duty boundary. |
| H10-C12 | A final catalog read could publish already-expired positive rows with an earlier timestamp. Regression failed first. | Use the clock after final catalog I/O; single regression passes. |
| H10-C13 | A half-bound runtime could silently use a fake reader or conceal available catalog data. | Real source constructors are bound without provider I/O; partial configuration fails and missing GitHub leaves delivery unavailable, not catalog absence. |
| H10-C14 | New transport could lack SQL source capture or wait for a personal case revision. | Real loopback SQL test proves existing immutable receipt capture, scoped revision outbox, Core-only writes, and no personal-case pollution. |
| H10-C15 | Handler tests could conceal disconnected agent/API paths. | Actual fixed subscribers pass2 cases; actual Operator family/adapter passes19; exact route assembly passes4. No live provider call was performed. |
| H10-C16 | Formatter output could change executable structure. | AST check found incorrect indentation in merge-source digest validation; restored it, then all26 fingerprints matched. Main session alone validated. |

Checkpoint evidence is deliberately narrow: scoped case/request files passed23 tests; artifact
consumer12; GitHub source23; Operator19; actual fixed-agent2; runtime7 plus the later timing
regression1; actual loopback SQL1; existing assignment source/intake/processor selection had65
passes and one expected-version test failure, then the corrected SDK selection passed24. These
overlap and are not a combined regression total. The new26 H10 files passed Ruff/format before the
later current-Owner tests and worker-cadence edit; those newest inputs still need their own checks.

This is not a completed H10 product stage: the full Console editor, future-effective review policy,
and explicit supersession/recovery for overlapping scoped cases still need integration review.
No deployed scope configuration, Graph membership, GitHub App, live merge, or promotion is verified.

H10 follow-on C17 reproduced an unreviewed pending case withdrawing an already observed scope.
Only independently merged artifacts now enter positive coverage; unreviewed proposals cannot
displace it. C18 added explicit `supersedes_case_id` over the same exact agent/scopes and included
that reference in the reviewed plan digest. The prior case's resolved humans are also excluded
from the new independent review. A verified successor retains negative supersession history;
loss of its source holds instead of resurrecting old duties. C19 checked bounded history, source
expiry, case-scan incompleteness, and catalog availability without Git credentials. Future-only
declarations remain draft until current coverage can be independently checked, never pre-granted.

Latest focused H10 source evidence: 53 model/case/request tests, 17 runtime/Owner-reader tests,
14 artifact/actual-subscriber tests, 19 Operator route/adapter tests, and one real loopback SQL
test pass on their respective current inputs. The 21-source strict check and subsequent three
changed-source check pass; 32 H10 source/test/connection paths pass Ruff and formatting. Results
overlap and are not summed. These close the bounded H10 source review/observation checkpoint,
not its still-pending Console integration or any of the remaining Core/semantic/executor work.

### Alternate Core admission and retrieval continuation design

The actual Core `HandoverGoalService` and `HandoverKnowledgeRetrieval` constructors had no
production users. Do not register unused objects and claim this gap closed. First provide
current exact-person/ordinary-role observations, current active backup-case checks, and restricted
Core-role document admission/access/search functions. Search must bind the current Core goal,
source revision, uploader, immutable document/version/digest, collection, document ACL and chunk
lineage, not a caller-supplied access label alone. No raw document-table SELECT is granted.

Every current review is checked independently and existing reviewers' document ACLs are rechecked
before final acceptance. Core public mutation still requires its active assignment. Accepted-goal
read validation may lower admission or withdraw derived candidates, but must not rewrite historical
reviews. Runtime source consumption must use the bound Core service, and retrieved chunks must
retain their original source, version, locator, and digest. Empty permitted output is not complete
coverage. A missing binding, migration, current identity, source, ACL, or exact chunk becomes a hold.

Critique/revision: active role fields require explicit booleans; cached roles are not current;
backup scope and provider must be exact; a prior review cannot retain lost ACL; source checks
precede content reads; query bounds and service SQL role are fixed; readback after I/O prevents
expired evidence; legacy document:// spans are not silently equated with doc: identity; independent
services never import each other's implementations; runtime registration needs actual consumer
evidence, not a catalog-shaped availability claim. Semantic compilation remains the next separate
boundary and cannot be satisfied by this admission work.

### Core source and retrieval critique checkpoint

This checkpoint covers current admission, reviewer eligibility, actual source consumers, and the
existing authenticated `query.governed_documents` function. It does not complete semantic
compilation, independent execution, Console integration, or the final integrated critique.

| Round | Distinct hypothesis | Finding and disposition |
|-------|---------------------|-------------------------|
| CORE-R01 | A first backup can lose document ACL before final Owner acceptance. | Reproduced acceptance instead of denial; recheck all retained reviewers' exact document access. |
| CORE-R02 | Six exemptions bypass current source-holder identity. | Reproduced acceptance with unavailable subject; the admission port now checks the source holder even without documents. |
| CORE-R03 | A supplied request timestamp masks slow role I/O. | Reproduced six-minute I/O accepting under the old timestamp; non-sliding real-clock/async bounds and pre-CAS checks hold. |
| CORE-R04 | Private observed groups are confused with role labels. | Actual directory-group expansion retains only observed memberships; direct App Roles prove no group, and serialization omits groups. |
| CORE-R05 | Shared HTTP redirect settings can move role evidence to another host. | Reproduced a followed redirect; the real directory reader explicitly refuses redirects. |
| CORE-R06 | A current-person receipt can refer to another query instant or incomplete expansion. | Exact query echo, person, completeness, explicit active bool, role type, source expiry, and cancellation checks pass. |
| CORE-R07 | Bare subject ids conflate an unrelated provider with Entra. | Reproduced real SQL retrieval from an other-provider assignment; admission now binds provider-qualified active assignment and post-read equality. |
| CORE-R08 | Core goal state is writable through the shared Operator table grant. | Inspected missing handover_goal namespace guard; added Core-owned trigger and tested insert/update/delete/rename boundaries with real roles. |
| CORE-R09 | Source admission occurs only after document content is read. | Both missing and false admission reproduced a content query; standalone retrieval now admits subject and sources first. |
| CORE-R10 | An exact doc: string bypasses chunk provenance. | Reproduced unrelated chunk acceptance; canonical doc citations now bind exact document/version/hash and original chunk source. |
| CORE-R11 | Document metadata checks miss changed chunk bytes during I/O. | Goal and document races already held; real chunk race failed, then independent identical-query readback fixed it. |
| CORE-R12 | Restrictive labels can accidentally expand collection or uploader access. | Real SQL requires exact goal revision, uploader, version, digest, collection, and access reference; wrong scope returns no chunks. |
| CORE-R13 | Draft, purged, unavailable, or string-true records look admitted. | Exact source SQL rejects each; active index and live source/chunk retention remain required. |
| CORE-R14 | Adding constructors still leaves the runtime disconnected. | Existing knowledge-owner source consumption invokes current Core goal validation; actual governed-document function returns real SQL-backed original citations. |
| CORE-R15 | Search obtains raw document grants or another service's authority. | Core receives bounded functions only; actual raw document/chunk SELECT and Operator function execution fail. Wrong SQL role fails before reads. |
| CORE-R16 | The new function can load before its chunk schema or rollback away retained authority. | Added explicit worker schema dependency, single-head verification, and rollback refusal while Core goals remain. |

Focused evidence: latest Core goal/acceptance/retrieval selection passed 28; current runtime binder
passed 8; identity/direct directory selection passed 21; latest real loopback SQL read selection
passed 26. Two exact migration contract/head nodes passed before SQL whitespace-only changes;
the new runtime modules are registered for packaging, whose final wheel check remains pending.
Twelve direct source files passed strict mypy, and 21 focused Python paths passed Ruff and format.
The formatter-only delegation was not validation: the main session compared all 21 normalized AST
fingerprints before later semantic fixes. Counts overlap and are never summed. No source content,
credentials, real directory calls, model invocation, deployment, or authority promotion occurred.

### Semantic candidate compilation design and critique

Norns remains the off-path learner and sole `object.rule-candidate` publisher. Mimir remains the
deterministic Rule steward and `object.rule` publisher; Saga seals its result. They are not hard
dependencies, do not call one another, and gain no execution or catalog-promotion authority.
Keep every existing AgentSpec, owned topic, subscription, and Norns/Mimir publication gate.

Compile only independently accepted, currently admitted handover sources whose documents explicitly
include the existing `manual_distillation` purpose. Read the actual bounded normalized envelope
from the configured same-venue artifact store, not a reconstructed or falsely complete chunk set.
Validate exact document/version/source digest, source ACL, original structural locators, retention,
and repeated readback. The source holder and prior reviewers are rechecked through their owning
admission path. No arbitrary user URL, path, cross-service implementation import, or raw table grant.

Use the existing described Distiller/ontology council for residual prose. Canonical typed Rule
declarations can use an explicit machine-marked artifact form and the same Rule loader without
inferring intent from words. Full Rule and ontology candidates retain exact source spans and require
schema, reference, safety, source, and independent-review gates. Unsupported prose or an unbound
extractor remains an explicit abstention, not generated metadata disguised as semantic success.
Rule prose extraction availability must be reported separately from typed artifact compilation.

Norns retains an immutable, source/binding/release-bound private compilation package before emitting
its content-free reference. Mimir independently reads the package and current sources and reruns
deterministic compilation; a digest on the event is not a verifier. Review packages are inert,
retain unresolved coverage and all future shadow/regression/promotion requirements, and never enter
an active RuleIndex or ontology projection. Duplicate delivery reuses the retained attempt; source
or binding changes create a new identity. Withdrawal disables current consumption, not audit history.
Bound total/per-read/model work; cancellation, unavailable source, schema failures, changed bytes,
model disagreement, and partial context hold without retries or automatic source replacement.

### Reboot recovery and semantic compilation critique checkpoint

The 2026-09-15 restart retained HEAD `d737bdb535e0725120e19e97aff28f91d25e772a`,
108 tracked changed paths, 93 untracked paths, and an empty index. No recovery reset, stash,
branch switch, commit, push, or issue mutation occurred. The task uses its own offline environment;
the editor's interpreter lookup still points at another checkout and is not used for execution.
The operator explicitly authorized starting Docker Desktop, including its existing automatic
container restart behavior. SQL checks use a new task-only loopback database, not application data.

The interrupted semantic test initially reproduced one failure with twelve passes. Source
inspection also disproved the exploratory claims that bootstrap binding, semantic tests, and the
SQL migration were absent: all three already existed in this checkout. Their existence alone was
not treated as validation. The actual constructors, subscribers, compiler, source reader, and SQL
store were then exercised separately.

| Round | Distinct critique and observed evidence | Result / boundary |
|-------|-----------------------------------------|-------------------|
| SEM-01 | A single extractor's prose Rule passed without source-fidelity evidence; the inherited regression failed first. | Only an exact typed source artifact compiles as a Rule. Prose extraction alone remains held. |
| SEM-02 | Independent review accepted a mismatched original claim; regression failed first. | Match exact source/revision/compiler identity on the durable claim. |
| SEM-03 | A recomputed package digest concealed a different embedded identity; regression failed first. | Package identity must equal the independent request identity. |
| SEM-04 | A package moved to an unrelated key still passed review; regression failed first. | Recompute and match the content-addressed package reference. |
| SEM-05 | Claim I/O could expire the source window before a model call; regression failed first. | Recheck after I/O and before each extraction; real async budget is capped by the original notice deadline. |
| SEM-06 | Withdrawal during deterministic review was missed; regression failed first. | Independent post-compilation source readback is required. |
| SEM-07 | Cancellation could refund the durable model attempt. | Cancellation propagates; its retained claim makes later replay an explicit interrupted hold without another model call. |
| SEM-08 | Text normalization changed significant spaces inside typed JSON; regression failed first. | Preserve JSON string values while normalizing layout whitespace. Ordinary prose behavior remains unchanged. |
| SEM-09 | Changed Rego bytes at the same path retained an old verified package; regression failed first. | Package binds current bounded policy bytes and its Rule schema digest. |
| SEM-10 | Changed remediation template bytes retained the old package; regression failed first. | Independently hash the exact bounded, non-symlink template on compilation and review. |
| SEM-11 | Candidate counts and disposition could be supplied by the producer instead of independently derived. | Recompute counts and outcome from deterministic compilation; transport rejects inconsistent status/reason pairs. |
| SEM-12 | Rule citations retained line numbers but omitted original structural location. | Compiled Rules retain source format, unit id, original locator, source version, and both content digests. |
| SEM-13 | A withdrawn source was checked only after private candidate text had been read; regression failed first. | Current source admission precedes private package access. |
| SEM-14 | Local FIFO, symlink, oversize, duplicate-key or wrong-identity input could supply an envelope. | Focused real file tests reject each without an unbounded read. |
| SEM-15 | A redirect or provider failure could move credentials or retry work. | MockTransport 301/403/429/503 cases make one GET only; cancellation remains a control signal. No live request occurred. |
| SEM-16 | Present constructors could still leave the actual owner path unused. | Real local/deployed constructor and Norns/Mimir subscription tests pass; independent reader instances and Mimir's lack of a model port are asserted. |
| SEM-17 | Source purpose, protection, ACL, reviewer loss, changed bytes or withdrawal could permit reuse. | Actual task-only PostgreSQL source tests hold each case, including final independent review after Owner loss. |
| SEM-18 | Failed audit could leave a claim or compiled package committed. | Actual PostgreSQL claim and completion rollback tests pass; exact duplicate completion adds no audit. |
| SEM-19 | Operator or administrator roles could read the private package adapter. | Actual Operator SELECT fails and the adapter refuses an administrator DSN before package I/O. |
| SEM-20 | Formatting delegation could silently alter executable scope. | Main-session AST comparisons matched all ten, then fourteen exact files; no delegated validation was used. |

The current compiler/real-SQL selection passes37 tests. The earlier contract, bounded-envelope,
constructor, and actual-owner selection passed40 on its then-current inputs. The source bridge
and compiler selection passed28 before the latest source-order and locator changes. Counts overlap
and are not summed. Eight semantic source files passed strict typing before those latest changes;
their updated type checks and final format checks remain necessary. Source-private retention,
full package lifecycle integration, actual provider conformance, and the remaining execution and
Console work still need their owning checks. This checkpoint is not final S6 integration review,
operational readiness, or permission to publish an incomplete task.

### Semantic package retention design and critique

Mimir owns derived-package retirement through its existing `object.rule-candidate` consumer, not
a new agent or autonomous deletion worker. Norns retains an immutable source/retention descriptor
beside each completed private package. Current document policy is read through a Core-only,
package-bound metadata function; neither agent receives raw document-table access. Missing source
metadata or an unavailable read blocks package access and does not grant erasure permission.

Retirement is monotonic. Source withdrawal, current purpose/access/digest drift, or original/current
derived expiry closes content access. Known current legal hold preserves private bytes but never
read eligibility. Only explicitly observed absence of legal hold permits content scrubbing; unknown
or missing policy retains inaccessible bytes. Scrubbing keeps the immutable claim, content-free
receipt, digest, and original audit, so the same identity cannot restart extraction. A later fresh
goal revision creates a separately reviewed identity, not resurrection of the retired package.

The existing source scheduler already republishes every retained source identity. Mimir processes
at most 25 packages per source notice, rotates by last check, and records retirement/scrubbing
atomically with content-free audit. Replays do not inflate audit history; failures roll back and
remain retryable. The consumer rechecks even when positive publication is disabled. No source
projection, catalog, policy, or actual provider resource is written by this retention path.

Critique/revision: do not erase receipt identity; bind policy lookup to retained document ids; do
not treat an outage as deletion; a legal hold can preserve bytes but cannot restore access; expiry
cannot slide on replay; current and original retention use the stricter boundary; changed policy
cannot extend a retained package; incomplete metadata prevents erasure; rotate bounded checks so
held packages do not starve later rows; and keep Norns compilation and Mimir retirement as distinct
column transitions with explicit SQL guards and no AgentSpec/topic/role changes.

### Semantic retention review evidence

| Round | Distinct hypothesis and evidence | Result / limitation |
|-------|----------------------------------|---------------------|
| RET-01 | One current source state could hide an older original expiry. | Pure tests enforce both original and current derived expiry; replay cannot extend either. |
| RET-02 | Withdrawal could erase content under legal hold. | Actual SQL tests retain inaccessible private bytes when current legal hold is true. |
| RET-03 | Missing, string, or integer legal-hold fields could imply false. | Strict pure-policy cases and actual null-policy tests forbid erasure. |
| RET-04 | A later legal-hold release might reactivate content. | Real SQL permits only scrub after release; retired state never reopens. |
| RET-05 | Scrubbing could remove the stable attempt and repeat extraction. | Real SQL preserves claim identity and content-free receipt; completion and schema guards reject resurrection. |
| RET-06 | A source-policy read failure could be treated as deletion. | Revoke function access in the task DB; the failed read changes neither package nor retirement state. |
| RET-07 | Missing source metadata could silently mean no legal hold. | Real deletion-of-source-metadata test retains inaccessible bytes and never assumes erasure authority. |
| RET-08 | Delayed candidate consumption could leave expired packages readable. | Real read-before-consumer test denies private bytes immediately without impersonating Mimir's retirement transition. |
| RET-09 | Failed retirement audit could leave scrubbed content without evidence. | Real transaction-failure test preserves exact package and nonretired state. |
| RET-10 | First-page legal holds could starve later packages indefinitely. | A27-package actual SQL test processes at most25 and reaches all27 across two oldest-check passes. |
| RET-11 | Closing positive publication could disable safety maintenance. | Real owner-subscriber tests still invoke Mimir retention for held and withdrawn candidates; no model call or ActionRun. |
| RET-12 | A retention failure could still emit semantic success. | Actual subscriber regression emits an audited held result with no semantic reference. |
| RET-13 | An old withdrawal could retire a newer source revision. | SQL selection bounds withdrawal to package revisions no newer than the verified notice; every package independently checks current policy. |
| RET-14 | A formatter could move or alter the new transition code. | All9 main-session AST fingerprints matched after edit-only delegation. Main owns all checks. |

The completed retention/actual-SQL/agent selection passed49 tests before later scan and failure
coverage. The later actual SQL/agent selection passed33; the newest policy-failure, compiler,
retention, and agent selection passed60. These selections overlap and are never summed. Five
changed source modules pass strict typing. The package lifecycle is source-connected on the existing
Mimir subscription and source scheduler; legal-hold release/deletion policy in a deployment and
operational latency/cohort evidence remain separate. Retained unknown-policy content is an explicit
held outcome, not a completed purge or Low-only operational claim.

### Next execution connection: source findings, not an enforcement shortcut

Current isolated dispatch accepts only canonical Azure operation targets; a human-assignment case
is not such a target. The existing operations gateway has only Change/Resilience/FinOps identities
and no human-access operation. Core's current human-access binder still constructs the privileged
provider, although the direct adapter unconditionally refuses enforce. Removing that refusal or
forwarding the request to the gateway would not complete the isolation, target, or approval contract.

The source extension must keep the reviewed Action bytes unchanged, independently bind a private
exact case/role-group execution plan, and let only the isolated Executor hold a dedicated human
access identity. All grant/revoke attempts must share a normalized membership-target lock, not
only a case lock. Core alone owns case transitions; dispatch cannot mark IAM active. The existing
Heimdall terminal ActionRun hook is a real independent observation seam, but its current artifact
resolver and collector do not yet support the human-assignment target. An exact independent source
receipt must precede Saga-sealed Core effect recording. Provider acknowledgement is not that receipt.

This source work remains open and has not been downgraded to a deployment prerequisite. No
enforcement guard, approval model, ActionType promotion, provider credential, or executor authority
was changed during this research. The independent H10 UI can proceed without those unavailable
effects; final task publication still waits for the execution source requirements.

### H10 Console integration design

Keep scope-specific ownership separate from personal IAM in the existing Mapping reviews view.
Render an Owner-only structured editor for exact agent, server-provided scope, user/group/schedule,
primary/backup/escalation duty, UTC effective interval, and explicit static schedule fallback. Keep
up to30 declarations, show the source revision and observation expiry, and never infer scope,
directory identity, future coverage, or IAM from a display label. A superseding draft pins the exact
Core case id rather than editing approved history.

The six existing API routes supply a catalog, exact scope observation, case creation/get, and
submit/review. There is no case-list endpoint: provide exact case-id navigation and an explicit
refresh instead of inventing a list. POST acceptance always displays awaiting Core; only a later
authoritative GET can show a materialized revision and enable the next command. Requester and
reviewer controls derive from server identity and current case state; the server remains the final
authority. All controls suppress concurrent writes and stale cross-case responses.

Critique/revision: keep one stable creation key for retry; changed draft data needs a new key;
preserve the original command payload after uncertain submission; reject foreign response ids;
do not turn awaiting Core into an approved case; don't treat group declarations as distinct human
coverage; require a current source window at submission; no automatic polling or provider writes;
use skeletons from first render, native keyboard controls, original evidence disclosures, and
desktop-first responsive wrapping. The actual isolated Console route, not a sample shell, supplies
visual evidence; no Browser Entra or live-provider claim is inferred from synthetic API tests.

### H10 Console implementation and focused critique evidence

The actual `/agent-oversight/mapping-reviews` route now includes the ownership-only workspace.
Its six existing API calls preserve request bytes, exact selector/case identity, current catalog
windows, proposal-only POST receipts, and manually refreshed Core state. Route-local English and
Korean messages preserve machine tokens. No case-list endpoint, personal IAM effect, new role,
background polling, browser persistence, or privileged client was added.

| Round | Distinct hypothesis and evidence | Result / limitation |
|-------|----------------------------------|---------------------|
| UI-01 | A structured declaration could imply IAM or invented scope. | Model cases reject unknown Pantheon names, wildcard/related scopes, unnormalized subjects and extra request fields. |
| UI-02 | Schedule declaration could silently imply a distinct backup. | Explicit static user fallback is required; the browser scenario sends the declared schedule and fallback, not a fabricated resolved person. |
| UI-03 | Retrying creation could duplicate a different request. | Actual route sends identical body/key after synthetic503; edits rotate the retained creation identity. |
| UI-04 | HTTP202 could be rendered as approved or materialized. | Actual route stays awaiting Core, with no revision or approval control until GET evidence arrives. |
| UI-05 | GET could accept another case or rewrite prior evidence. | Decoder cases reject foreign IDs, revision rollback, changed request, Core identity, review history and frozen plans. |
| UI-06 | A current Owner could self-review or repeat a review. | Unit guards reject requester/target/prior reviewer; browser tests retain pending state after POST and block repeat approval after revision3. |
| UI-07 | Account replacement could retain the old Owner observation. | New actual-component regression failed with five old-context inputs visible. Mapping review sessions now reset immediately and fence late IAM responses; regression passes. |
| UI-08 | A fresh GET might renew expired source evidence. | Original non-sliding expiry remains visible; the actual route marks expiry after a focus-time clock refresh. |
| UI-09 | Unavailable scope could look like zero or healthy coverage. | Korean route renders the synthetic unavailable reason without manufacturing people or healthy state. |
| UI-10 | Compact layout could hide controls or identifiers. | Actual route measures no document/panel horizontal overflow at1440,993,390,320px; token-based200% enlargement and spacing override pass. |
| UI-11 | Decorative skeletons could resemble live data or be absent initially. | A deliberately held catalog response shows the first-frame status/busy skeleton with hidden decorative blocks. |
| UI-12 | Shared hairline could be too faint to identify inputs. | Measured active boundaries failed at1.25:1. Local shared text-soft token fixes boundaries; light/dark text>=4.5 and controls>=3 pass. |
| UI-13 | Touch, native focus or preference styling could disappear. | All measured active controls meet44px; keyboard activation, focus outline, reduced motion and forced colors exercised. |
| UI-14 | Independent JS fixtures could disagree with Core serialization. | Main session fed actual Core service pending/one-review/approved cases through the real TS decoder; all three accepted. This is synthetic source parity, not a deployed API round trip. |

Main-session validation:95 focused model/API tests remain reusable for unchanged source inputs;
the latest six actual-route/component Playwright scenarios pass after context and contrast fixes;
Console source and test TypeScript checks pass. The six tests use the isolated leased harness and
synthetic API responses only. No browser Entra context, primary app restart, live directory or
provider request was used. Existing personal-assignment panels intentionally receive synthetic503
in this focused fixture and are not evaluated as the new scoped workspace.

Rubric1.0 scope is this new bounded workspace, not the shared shell or the full user-handover page.
Core IDs plus form/recovery/provenance/accessibility and responsive gates were selected in the design.
Measured contrast, targets, first-frame skeleton, native interaction, no-overflow, source-state and
identity evidence are available; no numerical quality score or full WCAG claim is made. Exhaustive
keyboard order, required assistive-technology announcements, all long-content/expanded states and
complete per-ID rubric accounting remain U for final review, not N/A or passed. Screenshots are
synthetic and visually inspected; slot output is volatile and later tests can replace it. Paired
public owner docs and the final integrated critique remain separate unfinished work.

### Isolated human-access implementation design, revision 1

Implement the remaining source path in dependency-bounded changes, without promoting an action:

1. Move only provider-neutral human membership value/port definitions to the shared SDK and keep
  Core compatibility imports. Preserve the existing target receipt digest. Add one normalized
  membership lock identity that excludes case, operation and retry key, so opposite operations
  and different cases cannot acquire different locks for the same subject/group.
2. Separate pure current-case planning from the legacy apply coordinator. Core runtime binds only
  that planner; role-group configuration must never construct a mutation identity or Graph writer
  in Core. Missing external execution remains explicit, not a Core fallback.
3. Bind immutable exact-Action execution material before current human approval, and revalidate it
  against current case/replacement revisions, current role/group sources, the authoritative
  promotion registry and existing approval record before any dispatch. The plan has no authority
  flags that can enable execution. Approved Action bytes/arguments are never rewritten to insert
  a subject or group. A legacy shadow notice does not become enforce-capable on replay.
4. Extend only the existing isolated Executor composition with its dedicated human-access identity,
  role allowlist, strict current-plan reader and membership-target lock. Do not route it through
  the operations gateway. Every effect must retain the seven shared safeguards plus current
  exact human approval; local authority cutover remains prohibited. Recheck deadlines and source
  fences after token, target, lock and provider reads. Unknown dispatch is retained and cannot
  automatically repeat an effect or trigger an unowned inverse change.
5. Independent membership observation uses an existing Heimdall-owned observation seam and a
  separate read identity. Saga seals exact observation evidence before the Core-owned assignment
  transition. Provider acknowledgement, requested desired state, or an Executor self-read cannot
  activate/revoke a case. Vidar's rollback only inverts a proven owned change under the same
  membership lock and the reviewed rollback contract; its effect also needs independent readback.

Critique/revision: the current Pantheon production callback is T2-route-specific, so merely adding
an isolated Graph adapter cannot complete the human-access flow. The existing general terminal
ActionRun hook is bound when its collector/verifier exist, but it does not yet implement this
membership collector. Existing bundle checks pin the original Action and proof reservation;
they do not authorize inventing a second approval field or interpreting a package as authority.
Core/Executor writer and read grants, stable source identity, delayed receipt recovery, actual
agent ingress, and current promotion/approval integration all need focused executable evidence.
This revised design is implementation scope, not a claim that any of steps3-5 already work.

### Isolated membership foundation checkpoint

Core now constructs `HumanAccessPlanner`, with no HTTP dependency, mutation provider or dedicated
Graph identity. Its refusal of local enforce is retained; the isolated path is separate. The
shared `human_access` contract preserves the old receipt digest and adds a subject/group-normalized
lock key independent of case, operation or retry. The legacy Core import is a facade, not a second
type. Focused planning/runtime/compatibility tests passed59; six source modules pass strict typing
and eleven changed files pass lint/format at that checkpoint.

An unbound isolated-only implementation now resolves an immutable original Action/material,
requires exact current preparation, original human approval slots, current Owner separation and
unchanged promotion/role-map evidence, and makes at most one Graph mutation. It persists pre-state
and intent before dispatch and an acknowledged result after204. A cancelled call, unknown provider
response or failed acknowledgement audit retains an unresolved attempt and cannot repeat the
effect. An already-satisfied membership is explicitly not an owned mutation. Shadow requests make
no token, source, Graph or assignment writes. These are mechanics, not live proof or a production
binding: current-source SQL, authoritative material/HIL production, runtime routing, independent
effect ingress and governed inverse execution remain unfinished source work.

Main ran26 contract cases and16 isolated adapter cases, then42 combined cases after formatting.
Five isolated/material source modules pass strict typing; six new/changed files pass lint/format.
The first adapter run failed3 cases because its classified base exception required a kind and a
message; the constructor was corrected without changing refusal semantics. A current-source
withdrawal during token I/O prevents Graph calls; deadlines are checked after source reads;
two different cases with opposite operations acquire the exact same target lock in the actual
service executor. None of those tests used a real provider, managed identity or production database.

Formatting evidence correction: a combined42KB terminal output lost its beginning, including the
initial AST hashes. It cannot prove all five delegated edits were AST-identical. Main reran the
owning tests and static checks on those current bytes. A separate complete one-file capture did
prove `human_access_execution` AST equality. No delegated validation was accepted.

### Executable connection design revision 2

Use a new versioned human-access execution notice and exact `human_access_execution` message kind
on existing owner topics. Old `iam_apply_requested` notices stay shadow-only. New material derives
its normalized membership target from the private plan before review, using the existing
`ActionBuilder` operator-request contract and current catalog/promotion state. Source change or
promotion never rewrites a retained Action. A new requested execution needs a new immutable identity.

The intended owner chain is Huginn -> Forseti material -> Saga -> Var existing HIL slots ->
Huginn decision notice -> Forseti source judgment -> Saga -> Var exact human quorum -> Saga ->
Muninn preparation -> Saga -> Var dispatch-ready approval -> Thor safeguarded isolated publication.
Thor's new exact-kind handling is separate from the legacy T2-route-only Boolean callback, uses
the existing safeguard coordinator rather than double-acquiring its physical lock, and retains
pending/unknown dispatch without reporting success or automatically invoking an inverse.

Preparation atomically records the material identity and original case digest with the case's
revision r->r+1. It does not rewrite approved `expected_revision=r`. Only that exact preparation
permits current-source admission. Existing Operator HIL decision records remain the human source;
the new metadata route is `human_access`, requires Owner, and forbids both requester and target.
Each elevated-role slot has a different immutable approval id and quorum remains a Var-owned join.
No fabricated Workflow Process, second approval writer or case-review-as-execution-approval is used.

Executor current-source reads are restricted to its exact material, preparation, original HIL
records, promotion record and bounded current identity snapshot; no raw assignment writer or
arbitrary private query is added. A mechanical bounded reconciliation notice makes delayed receipt
and observation work resumable. Heimdall resolves an actual dispatch receipt before independent
read-only membership I/O, publishes its owned Drift assessment, and Forseti -> Saga -> Muninn
records the matching effect. Current-source or receipt ambiguity stays held. A governed inverse
requires the original owned dispatch plus fresh inverse approval, unchanged membership lineage,
the same target lock and independent inverse readback; merely requesting it never reports rollback.

Implementation must prove the actual bindings as well as these components before removing source
gaps from readiness or delivery records. No agent name, role, topic ownership, current deployment,
enforcement flag or promotion record changes as a side effect of writing this code.

### Execution recovery design revision 3

The real shared coordinator/client test reproduced a lost pending-command classification when
publication ended in quarantine. Retain the original command reference while preserving the
failed/quarantined disposition. Independent observation must resolve the original atomic closure
before an assignment effect can be recorded; a dispatch receipt alone never clears a target fence.
One memory-store integration test currently passes. Actual SQL, isolated execution, trust binding,
failure recovery and late-input tests remain required; this is not a completed execution stage.

Implement a separately reviewed inverse, not a new grant/removal assignment and not a fabricated
Workflow Process. Reuse the two existing membership ActionTypes with an explicit `recovery_of`
argument. An inverse material binds the exact original material, retained Executor intent/result,
pre-state, latest membership attempt, current case digest and current demand. An inverse is allowed
only for a proven owned change; `already_applied`, a missing acknowledgement, an intervening target
attempt or unknown current demand cannot authorize it. The inverse restores the exact pre-state,
not an arbitrary caller-supplied role or membership. Original Action/material bytes remain immutable.

Vidar owns the recovery proposal on Rollback; Thor mechanically relays it on ActionRun, Heimdall
independently observes, and Forseti judges the exact inverse before Var creates fresh HIL slots.
The new independent Owner quorum binds the inverse Action and original mutation evidence. Approval
of the forward action is never imported. Expiry, rejection, missing Owners or absent evidence holds
recovery; neither an enqueue nor a reference string is a successful rollback. Every inverse uses
the same shared seven-proof dispatch and normalized membership lock as forward execution. Executor
checks its own immutable intent/result and latest target lineage again inside that held lock.

Muninn retains a separate inverse preparation in the exact case CAS, preserving the original
preparation and effect history. Inverse completion requires a separately attributed Heimdall read,
Forseti judgment, Saga seal and authoritative release reconciliation. A restored membership leaves
the assignment degraded for independently reviewed forward repair; it never restores duty, goal,
approval or promotion authority. Recursive automatic inversion is prohibited.

Critique/revision: the first research suggestion to reuse a normal removal case is rejected:
replacement coverage and case intent do not describe recovery of a failed grant. The suggestion to
close an effect when inverse human quorum is unavailable is also rejected. An operation-agnostic
membership lock is intentional, not an idempotency defect. Exact target lineage supplements that
lock; fresh random retry identities would defeat it. A generic Workflow recovery coordinator cannot
be reused by inventing a Process absent from the assignment lifecycle. New source must prove these
boundaries with deterministic provider fixtures and exact service-owned PostgreSQL roles.

Delivery authorization changed on 2026-09-15: after all requested implementation, distinct critique
rounds and validation, the operator now requests push and protected merge. This supersedes the old
PR-only stopping boundary. It does not authorize deployment, live providers or runtime promotion.

### Execution source critique checkpoint

The source connection now includes exact material/HIL preparation, Core-only planning, isolated
membership mutation, original Executor-owned intent/result, independent Heimdall observation,
atomic post-release reconciliation, and separately approved Vidar inverse. A recovered assignment
remains degraded or may be superseded; recovery does not restore duties or contribution authority.
All new ActionTypes still default to shadow and no registry record or live identity was changed.

Main's current owning execution batch passed132 tests. A separate21-test selection used real
loopback PostgreSQL service roles, Core and Executor locks, actual safeguard stores/bundles,
Operator decision transactions, isolated service command/receipt JSON, independent observation,
and actual Pantheon enforce/recovery handoffs. Provider HTTP and Owner directory observations were
synthetic. These selections overlap earlier results and are not summed into a product count.
Core package/wheel cold import plus narrow migration/projection selection passed8. Migration
inventory reached70 passes with one outdated order expectation; the corrected remaining node
passed separately. Latest source style passed27 files before the final small subsequent edits.
Final static, documentation, whole-task integration critique and delivery checks remain pending.

| Round | Distinct scrutiny and evidence | Resolution |
|-------|--------------------------------|------------|
| EX-01 | Real shared publication returned quarantine without pending-command metadata. | Preserved original pending identity without changing quarantine or claiming effect success. |
| EX-02 | Provider acknowledgement alone could precede assignment activation. | Original release plan plus independent observation now drives the existing atomic closure before effect recording. |
| EX-03 | New closure decorator omitted production eligibility. | Delegates the actual durable-store marker; real production-mode SQL composition passes. |
| EX-04 | SQL execution exposed membership audit records outside the Executor writer contract. | Corrected producer actor/phase, not the writer allowlist; direct regression failed before fix. |
| EX-05 | Normal forward ActionTypes did not express restoration of an owned failed mutation. | Added exact `recovery_of` material and original intent/result checks; pre-existing and unknown attempts are not invertible. |
| EX-06 | Inverse reused no valid degraded-to-degraded transition. | Exact preparation/effect-only CAS advances retain immutable original evidence; real inverse SQL test exposed and closed the gap. |
| EX-07 | A recovery request or reference could be mistaken for rollback success. | Vidar proposal remains pending; only new Operator approval, independent inverse observation and closure permit completion. |
| EX-08 | Two cases and opposite operations could choose different locks. | Both retain the normalized subject/group lock; isolated tests and real SQL shared-generation checks pass. |
| EX-09 | Prepared-before-publication crash had no safe continuation. | Bounded resume rechecks original review without renewing it; existing shared reservation prevents republishing an uncertain claim. |
| EX-10 | New owner path risked skipping the global stop and ActionType approval whitelist. | Current safety rechecked before publication and inside the shared lock; SQL source independently rereads the emergency halt. |
| EX-11 | Approval as Owner alone could bypass catalog/risk quorum or changed ActionType source. | Existing principal-to-ActionType policy, current mode/catalog and quorum ceilings are enforced. |
| EX-12 | Generic Pantheon enforce depended on the unrelated T2-only executor callback. | Complete membership/recovery binding satisfies only its own path; all generic unbound Thor work explicitly refuses. Real agent SQL inverse passes. |
| EX-13 | SQL revocation accepted two malformed dictionaries containing only effect kind names. | Exact receipt references/digests/aware timestamps and non-held replacement state now required; regression failed before fix. |
| EX-14 | Replacement loss, same-person backup, original hold change or another grant could invalidate removal. | Six actual SQL cases enforce current original/replacement/demand evidence. |
| EX-15 | A valid material referencing a malformed case stalled the page. | Content-free poison audit skips only invalid records; provider failures still propagate. Regression failed before fix. |
| EX-16 | Current Core role-map parsing and isolated parsing could disagree; identity case could hide sharing. | Shared strict four-role parser and normalized identity separation; nine composition cases plus approval negatives pass. |
| EX-17 | In-memory receipts hid service model identity and real SQL lock attestation. | Integration decodes JSON both ways and uses actual isolated service-role logins; no extra statistics privilege or weaker lock. |
| EX-18 | Material/release/observation evidence could be rewritten or Core could forge Executor ownership. | SQL retains immutable source and Executor-only append; exact Core-forgery rejection passes. |
| EX-19 | Recovery observed membership cannot substitute for original generation or request correlation. | Exact original target generation, request identity, source demand and fresh independent observation remain bound. |
| EX-20 | Migration metadata and bootstrap growth blocked normal delivery. | Literal rollback metadata, actual table ownership/dependency order and focused helper extraction; no gate or size threshold changed. |

No confirmed Medium/High execution finding is intentionally deferred as operational work. The
remaining final review must still examine full-task interactions on the latest delivered bytes;
these execution rounds are not the required ten final integrated rounds.

### Final integrated critique after remaining source implementation

The following are distinct integration questions, not repeated test runs counted as new rounds.
Main reviewed the source boundaries and executed the owning checks after the execution/inverse
implementation. No confirmed Medium/High finding remains open in the delivered source scope.
Live permissions, provider evidence, independent promotion and complete assistive-technology/UI
certification remain explicit external or unmeasured evidence, never a passed local claim.

| Round | Integration question | Evidence and outcome |
|-------|----------------------|----------------------|
| FI-01 | Does the original reviewed Action survive Core/SDK JSON and r->r+1 preparation? | Actual SQL source and fixed-agent tests preserve exact bytes and original human slots; no field is added after approval. |
| FI-02 | Can forward approval, pre-existing membership or a queued request authorize rollback? | Actual SQL inverse plus isolated ownership negatives require fresh Operator decisions and owned pre-state. Vidar completes only after independently observed inverse; the case stays degraded. |
| FI-03 | Can source changes or another grant invalidate removal without stopping it? | Six real SQL original-hold/replacement/demand scenarios reject changed revision, lost backup, same-person coverage and malformed receipts. |
| FI-04 | Can a role label, missing whitelist, old catalog or current emergency halt bypass authority? | Original-HIL and runtime negatives require current Owner plus ActionType policy, exact catalog, mode/quorum ceiling and current kill-switch; malformed false values do not clear the halt. |
| FI-05 | Does restart renew approval or republish an unknown mutation? | Prepared-source resume, immutable request-window, shared command claim and poison-case regressions pass; unknown attempt remains non-retryable. |
| FI-06 | Is dispatch acknowledgement mistaken for effect or release success? | Actual isolated service, dedicated SQL locks, current source, independent Heimdall and original atomic closure run in the same integration fixture. No provider self-read or pending message activates a case. |
| FI-07 | Do new assignment fields alter evidence admission, review or session authority? | Goal/revocation/replacement/Operator/Reader ACL/catalog selection passes145 tests. Missing inverse fields preserve old bytes; held assignments grant no new goal authority. |
| FI-08 | Can semantic growth activate a catalog or erase data without current retention permission? | Compiler/retention/Core source runtime selection passes61 tests on current ActionTypes. Packages remain inert; Mimir retirement is monotonic and unknown/legal-held sources cannot authorize scrubbing. |
| FI-09 | Does H10 create IAM authority or retain another account's Owner observation? | Prior unchanged-input95 unit and6 actual-route tests cover stable uncertain retries, Reader denial, independent review, account reset, mobile widths and contrast. No new Console source changed afterward; full rubric/assistive evidence remains unmeasured. |
| FI-10 | Does the new path bypass fixed ownership or require the unrelated T2 executor? | Actual Pantheon/SQL enforce and Vidar inverse chain passes without a T2 executor. Unrelated generic Thor work explicitly refuses. HIL/bootstrap/layout/doc-parity selection passes136 tests. |
| FI-11 | Can packaging, migration order or cross-service imports hide a disconnected source? | Core wheel and cold import pass; final SQL plus full owning migration inventory passes92 tests. Changed149 source modules have module docs and no Core provider/service-import violation; existing LOC ceilings are preserved. |
| FI-12 | Do documents or readiness overstate local completion as live operation? | Paired owner docs distinguish implemented sources, no operational readiness, and open #458 dependencies. Changed-path design-impact, document-size and append-only tracking pass; Korean quality passes12 changed files. Final generated/SHA sync follows the prose review. |

Execution source strict typing passes19 modules. Task-owned Python lint/format passed227 files;
six editor-preserved EOF corrections used the specifically scoped formatter after the operator's
autonomous continuation response, and all six before/after AST hashes matched. The full repository
suite was not run; exact pushed-SHA CI remains required for protected merge. The evidence counts
above overlap and are never added into one full-product total.
