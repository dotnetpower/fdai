# Operational learning hardening checkpoint (2026-10-17)

This record separates locally verified source repairs from unfinished implementation and
operational qualification. It is not a release, deployment, or whole-scope completion receipt.

> The work started at `24d437ba9f`. The current GitHub identity has READ permission and
> issue creation was refused by Enterprise Managed User policy. Publication and protected merge
> were requested but are blocked by that permission. No alternative identity, remote-only commit,
> force push, or protected-merge bypass was used.

## Review boundary

The checkpoint covers attributed scalar feedback, frozen predictions, correction/rebuild
components, independent measurement consumers, deferred holdout work, default-off T1 eligibility
comparison, and independently reviewed promotion bindings. Synthetic observations and loopback
PostgreSQL fixtures are not operational recovery or cross-environment generalization evidence.

The owning designs remain [Assurance Twin](../roadmap/operations/assurance-twin.md) and
[Operational Learning Ontology](../roadmap/rules-and-detection/operational-learning-ontology.md).

## Round 1: integrated source critique

The independent review reported ten concrete source defects. Their severity is the severity
before repair, not a claim that the defect remains active.

| # | Concern | Initial severity | Repair and focused evidence |
|---|---------|------------------|-----------------------------|
| 1 | Passing receipt metrics substituted onto a failing admitted promotion batch | High | Production preparation independently evaluates the admitted batch and authenticates the complete evaluation subject. Promotion binding and restart substitution regressions cover it. |
| 2 | Source expiry during asynchronous promotion preparation | High | Completion-time authoritative metadata and source deadlines bound preparation and consumption. Expiry-during-I/O and expiry-before-consumption cases cover it. |
| 3 | Incremental scalar models ignored their configured current-source verifier | High | New applicable feedback and reads validate retained revision manifests. Missing or unavailable current sources withhold learned models; static registered seeds are not new learned samples. |
| 4 | PostgreSQL's update-only CAS could not create the first pending-growth index | High | Audited atomic creation precedes CAS updates. An actual private-schema PostgreSQL test creates, restarts, finishes and verifies the audit chain. |
| 5 | Rebuild accepted substituted seed statistics or causal provenance | Medium | Registered seed body and digest are retained atomically and must match the replay seed. A substituted 999-sample seed is rejected. |
| 6 | UUID order changed order-sensitive calibration error statistics | Medium | Unseen input replay is chronological with a deterministic tie-break. Recorded applied order is retained in generation evidence rather than inferred from UUIDs. |
| 7 | Multiple dependent outcomes erased an already accepted episode | Medium | Replay retains the previously applied representative, or the first eligible canonical representative for an unseen group, without counting retries as independent samples. |
| 8 | Renewed admissions collided with immutable measurement receipts | Medium | Complete immutable evaluated content remains pinned; renewable admission references can refresh without changing measured metrics or overwriting original provenance. |
| 9 | Excluded future records blocked an as-of rebuild | Medium | Prediction checks and covered-input metadata use only the manifest's as-of source set. An unretained future prediction does not enter the historical candidate. |
| 10 | Pending builders consumed every invocation before fresh intake opened | Medium | A bounded pending phase reserves fresh-intake budget and reports exhaustion. Repeated invocation tests verify fresh source progress. |

An additional real PostgreSQL check found the same absent-row CAS assumption in the source
watermark. The cursor now uses atomic initial creation before revision-checked updates.

## Round 2: integrated source critique

The second independent review checked more than ten concerns and reported five further defects.
The third review did not reproduce these five repaired cases, but found three additional gaps.

| # | Concern | Initial severity | Repair and regression boundary |
|---|---------|------------------|--------------------------------|
| 1 | Prediction-retention failure removed unit/provenance verification requirements and could turn invalid effect evidence into success | High | Retention outages and identity conflicts no longer discard the snapshot's verification requirements. Healthy/outage/conflict cases each reject wrong-unit and receipt-less observations. |
| 2 | Reviewed rebuild counted cross-outcome idempotency conflicts as independent samples | Medium | Included revision chains enforce idempotency and logical action/prediction ownership before replay. Conflicting inputs cannot be approved into independent training cases. |
| 3 | JSONB numeric normalization invalidated equivalent model checksums | Medium | Typed floating model fields and nested seed parameters use storage-stable normalization. Actual PostgreSQL round trips cover integral large-float values for active and challenger slots. |
| 4 | Pending writer or completion-audit I/O consumed the reserved fresh budget | Medium | The complete item path is bounded, not only its builder. Fresh work obtains durable ownership first; ambiguous ownership prevents source acknowledgment. A stalled pending writer cannot starve fresh intake. |
| 5 | A deletion-fence PermissionError aborted unrelated compatibility-mode consumers | Medium | That explicit refusal preserves a failing aggregate status while allowing independent consumers to finish. The source/signature deletion fence is unchanged. |

The fixes also address the following reviewed concerns without treating them as new
operational capabilities:

1. A held or missing challenger cannot remove a configured Dynamic guard.
2. Dynamic request and model I/O have one cooperative total deadline; caller cancellation propagates.
3. Original authorization is required by the response builder and is independent of effect labels.
4. Equivalent time-zone and signed-zero representations preserve the new outcome identity.
5. Detected model projection corruption raises an explicit recovery error.
6. Unknown-only replay cannot reset a model into apparent readiness.
7. Source cursors record completed per-record handoffs, so bounded runs need not repeat an
   indefinitely unfinished source page.
8. No snapshot, prediction score, evaluation result, or shadow comparison grants execution or
   promotion authority.

## Rounds 3-5: fairness and immutable registration lineage

Each independent round exercised more than ten concrete scenarios. Counts below are confirmed
findings, not a manufactured quota of ten defects. Negative controls remain negative evidence.

| Round | Confirmed finding | Initial severity | Repair |
|-------|-------------------|------------------|--------|
| 3 | Timed-out oldest pending item kept permanent retry priority | Medium | The audited index retains a monotonic attempt revision and advances it before potentially blocking work. A frozen-clock regression proves ready work is attempted on a later invocation. |
| 3 | Owned but unacknowledged rows re-entered fresh processing and starved later rows | Medium | Durable ownership is tracked independently of attempted items. Source rows already handed off to the queue can acknowledge without another fresh-budget attempt. |
| 3 | One Cost Governance integration caller omitted explicit authorization | Medium | The unknown-authorization fixture explicitly passes `abstain`; effects cannot supply permission. |
| 4 | Unavailable source made an existing model look absent, bypassing configuration lineage checks | High | Registration inspection is separate from operational `get()`. Atomic creation or persisted lineage validation is required even during a source outage. Recovery cannot expose an incompatible configured version. |
| 5 | Same identity/revision accepted a conflicting body; evolved models accepted a substituted configured origin | High | Same-revision models require complete equality. Evolved models additionally require the exact retained registered seed, whose digest is validated independently of source availability. Unsupported legacy ancestry requires reviewed recovery. |

Round 5 reported 13 mutation controls: model ID, version, predictor reference, predictor digest,
unit, evidence grade, causal allowlist, learning origin time, bias, MAE, interval radius, sample
count and knowledge cutoff. The five body/cutoff controls exposed the one lineage finding rather
than five independent bugs.

The real restart fixture now retains a prediction, invokes the actual learner and reloads its
31-sample/revision-2 challenger. It no longer forges a model row without its checksum. Explicit
current-source DI is available through runtime composition; no production source is fabricated.

## Round 6: final scoped recheck

The independent reviewer passed 141 focused checks and the 13 named mutation controls above.
Prior outage/recovery, frozen-clock retry fairness, owned-row restart progress, legacy-lineage
refusal and non-operational registration inspection also passed. No confirmed above-Low source
defect remains in this bounded rechecked slice. This closes the scoped source review, not G/H or
the whole user-requested delivery.

The review's 66-file Python fingerprint was
`17b498375cc3131ad9456a9c8ba2c0f69dc20ad054d3d0786fe0ca1bd88b55ff`.
The later test-only deadline clarification below does not change production source.

## Evidence selection

Focused source and test owners are:

- `tests/contracts/test_response_outcome.py`
- `tests/core/mscp_profile/test_response_outcome.py`
- `tests/core/mscp_profile/test_feedback_authorization.py`
- `tests/assurance_twin/test_prediction_feedback_contract.py`
- `tests/assurance_twin/test_feedback_rebuild.py`
- `tests/assurance_twin/test_feedback_reliability.py`
- `tests/assurance_twin/test_feedback_registry_boundaries.py`
- `tests/assurance_twin/test_runtime.py`
- `tests/core/test_scalar_feedback_loop.py`
- `tests/core/tiers/t1_lightweight/`
- `tests/delivery/measurement/`
- `tests/core/operational_learning/test_promotion_binding.py`
- `tests/core/operational_learning/test_promotion_review.py`
- `tests/persistence/test_scalar_feedback_transaction.py`
- the owning promotion measurement, persistence and three agent composition files.

Database tests run only through `scripts/automation/with-local-test-database.py`, using private
schemas on the isolated loopback validation cluster. No remote database or runtime database
is used. The schema generator supports `--check`; generated version 1.1 does not rewrite 1.0.

Registry branch-inclusive coverage reached **92.84%** with 76 focused tests. The smaller initial
selection measured 83.06% and failed the 90% floor; boundary, stale-evidence, corruption and
lineage regressions were added rather than lowering that threshold.

The primary contract/control-loop/consumer matrix and promotion/agent matrix are separately
reported; their overlapping coverage runs are not added to test totals. PostgreSQL evidence is
six real loopback cases, not six operational observations.

Source plus every new regression module passes mypy (47 files). An optional expansion to all
existing changed tests is not clean: the immutable HEAD shadow baseline already has 58 errors in
eight tracked test files. The final expansion retains 52 baseline diagnostics in six existing test
files. New fixture errors were corrected without suppressions; this exploratory check is not
reported as passing or confused with the source type gate.

The synthetic full-path regression still freezes a later observation and reads the stored model
through Event -> T1 -> Dynamic -> review guard: challenger absolute error changes from 10 to 0,
baseline error stays 10, and interval width increases from 20 to 40. Execution and promotion stay
zero. One synthetic episode is wiring/regression evidence, not operational effect or generalization.

Final command results are recorded after the final tested input is frozen. Earlier worker counts
overlap and are not added together or reused for changed inputs.

### Final local validation

| Check | Result | Scope |
|-------|--------|-------|
| Contract, ControlLoop, scalar feedback, T1 and independent consumer pytest matrix | 631 passed | Owning selectors under Core tests plus the one repaired Cost Governance response-contract integration node |
| Exact promotion binding and three agent integration files | 223 passed | Nine promotion measurement/delivery/persistence files and three agent fixture files |
| Private-schema PostgreSQL scalar feedback transaction tests | 6 passed | Actual atomic rollback/concurrency, initial pending/cursor creation and active/challenger large-float JSONB round trips |
| Scalar registry coverage | 76 passed; 92.84% branch-inclusive coverage | `--cov=fdai.core.assurance_twin.model_registry --cov-branch --cov-fail-under=90` |
| Source and new-regression mypy | Passed, 47 files | 37 source/generator files and 10 new test modules |
| Ruff format/check | Passed, 66 Python files | Task-owned paths only |
| Response 1.1 schema generator `--check` | Passed | Existing 1.0 resource preserved |
| Translation sync and Korean quality | Passed, 7 pairs | Semantically reviewed changed owners only |
| Roadmap tracking, document size, design impact | Passed with existing size/status advisories | Seven changed owners; no product readiness upgraded |

One 10 ms pending-writer fixture hit the outer deadline when both timeout callbacks expired in one
scheduler turn. The test now explicitly accepts either pending-budget deferral or the stronger
whole-run timeout while requiring durable handoff preservation in both cases. Separate tests still
require fresh-intake progress under a stalled pending writer and a whole-run timeout for a stalled
fresh source. Production timeout behavior was not weakened.

## Resumed delivery and additional source hardening

The permission snapshot above describes the first checkpoint, not current delivery status.
On resumption, GitHub reported ADMIN access. Issue #2193 was created; Project synchronization
remained best-effort because the token lacks `read:project`. The local merge `db4a786104` preserves
both `68a0703bde` threshold-policy pins and the exact reviewed-replay binding. Combined receipts
use version 1.3 while retaining legacy reading/demotion; the focused promotion matrix passed
228 checks after integration.

The new PostgreSQL scalar revision source and local reviewed rebuild command were then connected.
The first additional independent source round checked more than ten named concerns and found:

| Concern | Initial severity | Repair |
|---------|------------------|--------|
| Raw UUID text lookup omitted an uppercase or alternate-wire correction | High | Canonical parsed witness identities and UUID-valued history comparison cover uppercase, compact hexadecimal, URN and brace spellings. Eleven actual PostgreSQL cases include five correction forms. |
| Deployed rebuild used local StateStore admission | High | The local utility refuses deployed venue before database/admission access. There is no fallback around the private deployed admission provider. |
| Logging `extra` hid the review manifest from the actual CLI formatter | Medium | Review-required stdout is explicit JSON with exact manifest and false execution/promotion flags; tests assert the full shape. |

Execution qualification was separately examined. PR publication alone does not prove an
intervention, but its built-in missing rollback state keeps it ineligible. Direct API `dispatched`
can instead map from an executor's postcondition-verified `SUCCEEDED`; blanket status rejection
would discard different evidence. No live completed-intervention qualification is claimed.

The next source round found two Medium availability defects: a raw UUID cast let an unrelated
invalid row abort every source check, and unrelated legacy records poisoned versioned rebuild
discovery. History lookup now compares non-throwing normalized hexadecimal text; discovery
selects 1.1 candidates while selected-UUID currency still reads every version. Actual PostgreSQL
tests prove unrelated malformed-row isolation and hidden same-UUID legacy withholding.

Parent-source round 9 passed 13 named query/discovery controls, recovered the exact failed
watermark/restart probe, and found no confirmed above-Low defect in that slice. Sixteen focused
source/CLI checks and twelve real isolated PostgreSQL checks pass. The parent review fingerprint
was `7097979aa1f3af3be20ef2a3eeffd246fb92bd21baac96a90b32f07bdb9a37ec`.

The separate G review found two Medium withdrawal defects: reusing an old current-reuse
admission after awaited reads, and a concrete statistics binding that returned only a captured
snapshot. The first repair reread providers and rescreened, but a second independent probe
showed the final awaited screen could still lose changes to measurement, negative cohort
artifacts, or Pattern-read admission. The final repair requires a distinct exact-subject
`retained-pattern-final-qualification` admission from a trusted coherent tuple issuer. Missing,
ordinary-purpose, mismatched, expired or timed-out qualification clears eligibility. No
production issuer or accepting default is installed.

The third independent G review found no confirmed above-Low defect in its six-file fail-closed
scope. It checked sixteen named controls and ran 56 focused tests. The three final-screen
withdrawals hold with an explicit synthetic no-yield/version qualifier; a missing qualifier
separately holds with no candidates/challenger. This proves neither an operational coherent
issuer nor deployment activation.

Final focused implementation evidence is 703 primary owning tests, 228 promotion-policy/replay
integration tests and twelve actual isolated PostgreSQL tests. Source/new-test mypy passes
58 files; Ruff passes all 74 task-owned Python files. Registry branch-inclusive coverage is
92.61% in 78 focused cases. Overlapping worker/coverage selections are not added to those totals.
Enforced official structural checks report zero failures, and the link gate finds zero broken
targets in 1,069 documents. Immutable fast preflight and protected delivery remain separate stages.

## Remaining operational and delivery conditions

- [x] Implement optional baseline-isolated retained Pattern comparison and bounded audit without
  copied case/vector storage; source deletion is observed through the owning read path.
- [x] Bind audit-backed versioned outcome currency and an independently admitted local rebuild
  command, retaining exact seed/order and atomic generation history.
- [ ] Qualify the trusted coherent final issuer and installation-owned request, registered
  action/statistics/current-reuse sources before retained challenger eligibility (#2194).
- [ ] Qualify original HIL/terminal execution, frozen predictor/observer provenance and
  source-owned prediction/generation retention in an explicitly selected venue (#2194).
- [ ] Produce paired, episode-separated operational evaluation and target-specific runtime receipts.
  No production experiment, live model call, Azure mutation or deployment was performed here.
- [x] Finish the bounded source rechecks: parent round 9 and G round 3 found no confirmed
  above-Low source defect in their final reviewed slices.
- [ ] Complete installation-owned qualification before claiming a whole operational closed loop.
  A held capability or a synthetic pass does not complete the operational requirements.
- [x] Obtain ordinary repository write and issue permission; #2193 and #2194 preserve the boundary.
- [ ] Perform immutable delivery preflight, non-force publication, protected CI/review and verified merge.

These are unfinished work or blocked evidence requirements, not Low findings manufactured to
meet the user's exit condition. Local checkpoint commits must not be reported as publication,
merge, deployment, or demonstrated operational policy improvement.

## Isolated LOCAL coherent qualification follow-up

The foundation above was delivered in PR #2195 as `21390f29b3`, with green exact-head CI and
supply-chain checks. The remaining operational conditions are not closed by that merge.
This follow-up implements the bounded LOCAL portion of #2194, not a production issuer.

The concrete `LocalPostgresPatternBackend` owns all dependency facts in existing `state_kv`
rows. Its exact PostgreSQL `FOR SHARE` lease lasts through synchronous positive comparison
construction. It consumes separate existing read/reuse admissions and grants no new permission.
The returned comparison is historical: its lease guard is inactive after release.

The independent follow-up critique exercised these 21 controls:

1. Real PostgreSQL writers wait on locks.
2. Positive comparison construction precedes writer release.
3. Negative artifact deletion blocks during the lease and holds the next comparison.
4. Artifact corruption before acquisition rejects.
5. Negative metadata deletion cannot escape the final check.
6. Projection withdrawal invalidates qualification.
7. Measurement authorization revocation invalidates qualification.
8. Principal revocation invalidates qualification.
9. Authentication-request substitution rejects.
10. Natural principal expiry rejects.
11. Current reuse-policy denial rejects.
12. Independent read-admission withdrawal rejects.
13. Independent reuse-admission withdrawal rejects separately.
14. Registered action withdrawal/schema substitution rejects.
15. Unleased qualification holds and issues no permission.
16. Natural case expiry caps acceptance.
17. Cancellation and deadline release actual locks.
18. Lease-exit failure discards a positive result.
19. Non-LOCAL venues and runtime port 5432 reject.
20. Default-off baseline selection and restarted composition remain intact.
21. Positive audit contains digests, not execution authority or operational proof.

No confirmed above-Low defect remained in that reviewed eight-file LOCAL slice. This is a
bounded review result, not a claim that all operational requirements or all repository defects
are Low. Eleven additional pre-acquisition mutation probes passed; repeated fixtures are not
independent generalization samples. Parent integration made the same existing admission check
explicit for the official decision-boundary inventory without weakening its conditions.

Final focused integration evidence: 214 retained T1/inventory tests and 21 PostgreSQL/venue tests
passed. Ruff passed; `mypy --follow-imports=silent` passed the eight changed source/test files.
An unrestricted follow-imports invocation also inspected unchanged fixture-imported tests and
reported 30 existing typing errors in four unmodified files; those are not hidden as a clean
whole-test-tree type result.

## Authorization provenance follow-up

Reconfirmed upstream main at `db740d8dd443c1667714ae91ec9048113d13bc24`, with #2195 and
#2196 merged at the reported revisions. Both recorded #2196 head workflows completed successfully
on `980ee61f3be3ff9e5a9a60c329e4a4c5f9efb99b`, attempt 1. These remain prior-input evidence.
The follow-up uses a new topic from current main; it does not revive an old work branch.
No installation, live source, Azure target or model invocation is selected.

### Source owners and actual connections

This is a source-code trace, not a claim about the configuration of an inspected installation.

| Input | Producer and owning storage | Existing consumer and currency boundary | Remaining retained-Pattern connection |
|-------|-----------------------------|----------------------------------------|---------------------------------------|
| Authenticated request and principal | Operator `semantic_authentication_receipts.py` retains `operator_authentication_receipt` before transport; Core `semantic_turn_request.py` binds receipt/request references | `OperatingPatternQuery` requires the exact authenticated operations-review context and independent read admission | Standard T1 bootstrap supplies no `RetainedPatternRequest` source. A retained receipt alone does not prove current IdP authorization. |
| Registered action, arguments and schema | Catalog loaders in `runtime/control_loop.py`; LOCAL owner has an explicit `register_action` writer | Retained source checks registered identity and JSON schema; LOCAL qualifier locks its actual action row | No installed retained-action resolver is bound. A catalog declaration is not a resolved invocation. |
| Independent measured statistics | LOCAL `retain_statistics` stores an explicitly supplied `RetainedReuseStatistics`; the baseline pgvector library separately owns historical rates | Retained source re-reads statistics; LOCAL final lease locks authorization and the exact measured DTO until acceptance | No production independent `RetainedReuseStatistics` producer/retention binding was found. Cohort counts and baseline rates are not substitutes. |
| Policy and reuse admission | Azure operational evidence adapters, inventory reader and decision-evidence providers; LOCAL policy/reuse/admission rows have one real owner | Ordinary T1 current-reuse checks and read/reuse admissions remain authoritative | External inventory, policy and proof owners have no composed whole-tuple checked-version/lease/fence in standard bootstrap. |
| Complete cohort, including negative cases | Muninn materialization and deletion-fenced case projections; case metadata and artifacts retain versions | Pattern query recompiles and checks every case; LOCAL lease locks exact projection, metadata and artifact rows | LOCAL protection is not a lock on external Blob or other production writers. |
| Frozen prediction, execution and independent observation | `_execution_effects.py`, `prediction_evidence.py`, response-outcome audit and configured independent observer | `PostgresFeedbackRevisionSource` checks complete current audit chains; registry persists atomic challenger state; configured Dynamic runtime reads it | Actual predictor/observer identity, completed intervention and source-owned retention still need installation qualification. Standard retained-Pattern runtime intake remains unbound. |

The chosen change preserves original authorization across no-effect terminals and observation
revisions. Copying external sources into LOCAL, adding a writer-ignored epoch, treating sequential
reads as one snapshot, or installing an accepting qualifier would not close the production gap.
An external issuer requires the actual source owners and revocation semantics; none is fabricated.

### Critique round 1: original authorization and source boundaries

| # | Concrete concern | Result and evidence |
|---|------------------|---------------------|
| 1 | Can a correction change `deny` or `abstain` into permission? | Confirmed Medium: the old rebuild and evaluator each accepted one synthetic sample. Full-chain validation now rejects decision changes. |
| 2 | Can a correction turn shadow into an executed observation? | Same provenance defect: old code trained/scored one sample. Both mode directions now reject; no permission is inferred from the effect. |
| 3 | Do no-effect workflow terminals retain the original gate decision? | Confirmed Medium: 12 of 16 new cases failed before repair because all became `abstain`. The original typed decision is now passed through; all effects remain unscorable. |
| 4 | Can valid observed-value corrections still replace a label? | Existing correction/rebuild and new four-decision controls preserve valid lineage without adding samples. |
| 5 | Can withdrawal or unobserved results become failure/success? | Unknown corrections remain unscorable, with no absolute-error result; original denial remains denied. |
| 6 | Can wrong action/event/predictor/unit provenance calibrate? | Frozen snapshot and feedback contract regressions reject identity and unit/receipt substitutions. |
| 7 | Can a complete but authorization-rewritten audit chain qualify a model? | Unit source diagnostics and actual PostgreSQL restart cases reject it as `feedback_source_revision_chain_invalid`. |
| 8 | Can duplicate, concurrent or lost-response processing double-learn? | Existing reliability and actual SQL transactions preserve one receipt/sample and roll back partial audit failure. |
| 9 | Can a negative case disappear during an intake await? | Committed withdrawal matrix covers artifact deletion, corruption, metadata deletion and projection withdrawal at every named intake boundary. |
| 10 | Can measurement, principal or policy revocation survive the last awaited screen? | Real LOCAL source rows are changed, including authentication-request substitution; the exact final lease rejects. |
| 11 | Can ordinary read/reuse admission replace final coherent qualification? | Independent admission withdrawal tests and missing/rejected qualifier controls preserve the existing distinction. |
| 12 | Are installation wiring and operational improvement demonstrated by these tests? | No. The standard source is unbound; the data is synthetic with real local storage. These are unfinished operational prerequisites, not Low findings. |

### Critique round 2: repaired paths and negative controls

The second review checked the repaired terminal/revision paths and the controls below, then
extended the producer trace to every dispatch completion branch. That trace found a further Medium
provenance omission: three early holds did not forward the original decision. Nine of twelve new
branch controls failed before repair; the three existing abstention controls remained valid.
All three branches now forward the typed value, and the private completion method requires it
instead of silently defaulting. Unqualified installation/source/effect work remains open.

1. Six decision/mode substitutions reject in both chronological and reordered/duplicate revision input.
2. Original `auto`, `hil`, `deny` and `abstain` survive no-effect recording in both execution modes.
3. No-effect recording calls neither predictor nor observer and retains no invented measured value.
4. Valid value corrections retain authorization; unknown corrections remove scoring eligibility.
5. Audit-source malformed, future, legacy, missing and superseded chains remain explicit holds.
6. Restarted SQL learning refuses authorization rewriting while the active baseline is unchanged.
7. Stored learning changes the next real Dynamic shadow prediction from 80 to 60 while active
   stays 80; this synthetic consumption test does not assert that 60 is more accurate.
8. Withdrawal of that observation makes the same restarted runtime explicitly unavailable,
   without manufacturing a replacement or promoting the challenger.
9. Eleven owner mutations at ten named awaited boundaries reject: request, initial read, direct
   projection read, resolver, first statistics, first verification, second statistics, final read,
   final verification and pre-lease acquisition. This is 110 real PostgreSQL probes, not 110
   independent operational incidents and not exhaustive nested-provider instruction interleaving.
10. Deadline and caller cancellation at those ten boundaries preserve the baseline and release
    source access; the existing held-lease cancellation tests separately prove actual lock release.
11. Existing case expiry, lease-exit failure, source writer blocking, restarted LOCAL composition
    and disabled-comparison controls remain intact. No broad database/table lock is added.
12. T1 current safeguards, final-admission inventory, original independent-effect scenario,
    predictor retention and registry corruption controls pass without changing their authority.
13. External IdP, Inventory and Blob are not covered by LOCAL row protection; production startup
    is not modified or described as wired.
14. Shadow scoring is not policy effect: no unexecuted candidate label, propensity, overlap,
    cross-environment holdout, live recovery or confidence claim is invented.

### Critique round 3: complete producer trace

No confirmed above-Low defect remains in the three changed production modules after this round.
This is a bounded source conclusion, not operational qualification. The twelve controls are:

1. Conflict holds preserve each of the four original gate decisions.
2. Kinetic evidence-writer failures preserve those decisions without reaching the executor.
3. Missing workflow safeguard commitments preserve those decisions and remain rejected.
4. Normal terminal completion and all three early branches explicitly supply authorization.
5. The private completion signature has no accepting/defaulted authorization value; mypy checks
   all actual call sites. The public dispatch default still truthfully represents unknown input.
6. All no-effect terminals remain unscorable, with no predictor/observer or successful-recovery label.
7. Observation corrections cannot rewrite decision or execution mode, in either direction.
8. Valid value corrections and unknown withdrawal preserve their distinct effect semantics.
9. Actual SQL restart/source checks cannot consume an authorization-rewritten outcome.
10. Stored challenger consumption, independent source withdrawal and unchanged active predictions
    remain covered by the SQL/runtime regression; there is no active-model writer in this change.
11. The 110 LOCAL withdrawal probes and 20 deadline/cancellation probes still cover their exact
    source-owned boundary, with held-lease release/expiry/exit-failure tests separately retained.
12. No policy, RBAC, approval, execution, promotion, rollback or blast-radius gate is removed or
    broadened; no copied external source or fixture becomes operational evidence.

### Evaluation and delivery boundaries

Before examining operational results, a reviewed plan still needs the existing target SLO and
safety-budget revisions, observation/recurrence windows, chronological prediction ledger,
incident/retry/replica/common-cause grouping, and service/cluster/topology holdouts where claimed.
The source classes must distinguish synthetic, simulation, historical and live observations.
No target is selected here, so inventing a sample threshold would not satisfy this requirement.

Recovery rate/time, recurrence, rollback, side effects, risk costs, recommendation coverage,
abstention, conditional success, probability calibration/Brier score, scalar prediction error,
interval coverage, independent incident counts and uncertainty need explicit denominators and
missing-data treatment. The existing pure scalar evaluator covers only a subset; there is no
paired operational baseline/challenger dataset or resolved selection bias in this follow-up.
No deployment, promotion, managed-resource mutation or live model call was performed.

Current GitHub repository permissions report read access without push access. Do not switch
identity, create a remote-only commit or bypass protection. Local implementation and verification
can finish, but publication, exact-head CI and protected merge require ordinary write permission.

Before the final producer-trace repair, the integrated selection passed 527 tests in 94.03
seconds. The final round adds twelve explicit early-dispatch controls to the same selection,
using the existing
`python3 scripts/automation/with-local-test-database.py uv run --no-sync pytest -q --no-cov`
entry point and these selectors (no repository-wide suite):

```text
services/core-control-plane/tests/core/mscp_profile/test_control_loop_shadow.py
services/core-control-plane/tests/assurance_twin/test_prediction_feedback_contract.py
services/core-control-plane/tests/assurance_twin/test_model_registry.py
services/core-control-plane/tests/assurance_twin/test_feedback_rebuild.py
services/core-control-plane/tests/delivery/measurement/test_feedback_revision_source.py
services/core-control-plane/tests/assurance_twin/test_feedback_reliability.py
services/core-control-plane/tests/assurance_twin/test_feedback_registry_boundaries.py
services/core-control-plane/tests/assurance_twin/test_runtime.py
services/core-control-plane/tests/scenarios/test_v2026_07_replay.py::test_sre_successful_full_loop_closes_only_on_independent_effect_observation
services/core-control-plane/tests/core/test_control_loop_t1_wire.py
tests/integration/scripts/test_decision_boundary_coverage.py
services/core-control-plane/tests/core/tiers/t1_lightweight/test_retained_patterns.py
services/core-control-plane/tests/core/tiers/t1_lightweight/test_retained_pattern_audit.py
services/core-control-plane/tests/core/tiers/t1_lightweight/test_eligibility_comparison.py
services/core-control-plane/tests/core/tiers/t1_lightweight/test_contextual_reuse.py
services/core-control-plane/tests/persistence/test_local_pattern_withdrawal.py
services/core-control-plane/tests/persistence/test_local_pattern_qualification.py
services/core-control-plane/tests/persistence/test_scalar_feedback_transaction.py
```

The final round-three selection passed all 539 tests in 100.67 seconds (exit 0).
Of that selection, 166 PostgreSQL/venue cases include 161 actual private-schema PostgreSQL
checks and five venue/runtime refusal checks. Repeated runs are not added to the count.
Ruff and eight-file `mypy --follow-imports=silent` pass. Paired translation, Korean prose,
punctuation, readable Hangul, design routes and the append-only ledger check pass.
The final immutable fast/structural preflight is a separate delivery stage, not implied by these
focused results. The best-effort Project update was refused by Enterprise Managed User policy.

Checkpoint `bff2adece1` committed the verified source and regressions with normal integrity
signing/hooks. Its route-selected documentation advisory identified the shared project-structure
owner; the follow-up updates that English/Korean owner and its append-only ledger. The remaining
authority/profile selectors passed 241 additional checks, excluding the already-tested shadow
control-loop file. This yields 780 distinct focused checks, not an operational sample count.

No external IdP/Inventory/Blob source, production bootstrap, live recovery comparison, deployment,
model call or Azure mutation was performed. #2194 retains those authorization and evidence gates.
