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

## Unclosed whole-scope conditions

- [ ] Complete qualified Pattern-to-T1 enrollment with shadow storage that cannot perturb baseline
  search, and source-owned copied-data retention/deletion.
- [ ] Bind authoritative outcome revisions, original HIL/terminal authorization, frozen predictor
  provenance, current-revision sources, rebuild admissions and retention in a packaged venue.
- [ ] Produce paired, episode-separated operational evaluation and target-specific runtime receipts.
  No production experiment, live model call, Azure mutation or deployment was performed here.
- [x] Finish the bounded source recheck after repairs; round 6 found no confirmed above-Low source
  defect in its reviewed slice.
- [ ] Complete the missing whole-plan components and reach the requested whole-scope Low-only exit.
  A disabled/unavailable path or a synthetic pass is not completion of this item.
- [ ] Obtain ordinary repository write/issue/PR permission, then perform immutable delivery
  preflight, non-force publication, protected CI/review and verified merge.

These are unfinished work or blocked evidence requirements, not Low findings manufactured to
meet the user's exit condition. Local checkpoint commits must not be reported as publication,
merge, deployment, or demonstrated operational policy improvement.
