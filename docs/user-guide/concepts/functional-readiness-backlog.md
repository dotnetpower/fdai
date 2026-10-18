---
title: F10-F15 Readiness Audit and Completion Plan
description: A complete subfunction inventory, evidence gaps, and dependency-ordered completion plan for F10 through F15.
---

# F10-F15 Readiness Audit and Completion Plan

This audit reconciles the [functional specification](functional-specification.md) with its
[assessment](functional-readiness.md), implementation owners, and remaining acceptance gates.
Use the work IDs below to resume implementation without confusing local tests with operational
completion.

> **Boundary:** F10 is included. All 21 subfunctions through F15 were reviewed at source revision
> `8819a28951fd5c21858adc0a8e7a6d5278ba4745` on 2026-10-18. This is a source, ledger, and
> exact-issue-state audit, not a new runtime test campaign or live deployment validation.
> F01-F09 retain their previous assessments and are not recertified by this audit.

## Audit results at a glance

The previous F10-F15 result was Ready 13 and Partial 8. **Ten Ready decisions become Partial**:
F10.1, F10.2, F10.4, F11.3, F13.2, F14.1-F14.4, and F15.1. The corrected result is
**Ready 3 and Partial 18**. Across all 52 subfunctions, the inherited and corrected results total
**Ready 28 and Partial 24**.

The plan contains **29 unchecked work packages** and **seven deferred or conditional scope
records**. Shared work is linked once rather than counted again for every affected function.

Three causes explain the misleading labels:

- **Implementation was mistaken for completion:** a passing local cohort did not close a required
  composed, authenticated, or independently observed acceptance gate.
- **Real source work was called configuration:** requester-policy activation, Release maximums,
  source-deployment cleanup, and source-specific health exporters still need implementation or wiring.
- **Task markers and issue states disagreed:** a closed issue can leave deferred work; an open
  checkbox can also describe code already delivered. Neither is completion evidence by itself.

Ordinary installation values do not make a generic read-model implementation incomplete.
However, an owner's explicit required operational gate cannot be excluded merely by calling it
"installation qualification." Optional expansion remains separate from the accepted support scope.

Concrete source cross-checks include the
[protected-download denial](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/download.py),
[independent activation readback](../../../services/document-processing-worker/src/fdai_document_worker_service/cloud_activation.py),
[whole-tuple retained-Pattern qualification contract](../../../services/core-control-plane/src/fdai/core/tiers/t1_lightweight/retained_pattern_bindings.py),
and the Release maximum and CLI paths linked below. These support bounded conclusions, not a
claim that every source file was reviewed.

## Complete subfunction inventory

`Local` below means the owner records implementation and focused checks, not that those tests
were rerun in this audit. Work IDs refer to the unchecked exit criteria in the following sections.
The final column is the exact machine-readable mandatory package list. Use comma-separated IDs,
not ranges; `-` means no mandatory package was identified for that bounded function.

| Function | Previous -> current | What exists | Remaining mandatory work | Required packages |
|----------|---------------------|-------------|--------------------------|-------------------|
| F10.1 | Ready -> Partial | Local ingestion, versioning, extraction/retrieval/deletion and purpose-bound protected source export | Exact-topology lifecycle and approved protected-source provider qualification | K01, K02 |
| F10.2 | Ready -> Partial | Local manual and explicit prior-policy v2/v3 API admission, collection, dated retrieval, and containment | Actual prior-policy qualification/promotion, source-quality holds, and authorized source/answer receipts | K03, K04, K05 |
| F10.3 | Partial -> Partial | Local current-schema Rules and all nine revision phases | Retained legacy migration and governed rollout; do not reimplement completed phases | R01 |
| F10.4 | Ready -> Partial | Local inert semantic compilation, independent deterministic verification, and retirement | Governed ownership handover/withdrawal/hold receipts and actual bilingual assistive output | K06, K07 |
| F11.1 | Partial -> Partial | Attributed immutable cases, feedback, prediction outcomes, and local retention controls | Complete source histories, authorized context lifecycle, and retained-Pattern qualification | L01, L02, L03 |
| F11.2 | Partial -> Partial | Local replay, scenario evaluation, threshold-bound O7 measurement, and isolated LOCAL comparison | Coherent external sources, preregistered paired evaluation, and complete live cohorts | L03, L04 |
| F11.3 | Ready -> Partial | Durable promotion/recall, override attribution, demotion, and read projections | Production Release maximums and governed activation/recall evidence | A01, A02 |
| F12.1 | Partial -> Partial | Exact approvals, profiles, revocation, and inert standing-authority/lease contracts | Live authority behavior and provider-commit fencing; no shipped A3-E adapter is eligible | A02, A03, L02 |
| F12.2 | Partial -> Partial | Local risk/policy checks, seven safeguards, signed kill switch, and state readback | Release bounds, cross-path effects, and measured stop/recovery receipts | A01, A02, A03, A04 |
| F12.3 | Partial -> Partial | Hash-chained audit, minimization, retention/deletion, legal holds, and redacted export | Approved privacy gate and pinned operational governance receipts | D01, D02 |
| F12.4 | Partial -> Partial | Fifteen-signal policy, three actual signal/field bindings, health/readiness and exact canary-consumption check | Twelve signal/five field sources, measured delivery/recovery, stabilization, and unresolved operating decisions | H01, H02, H03 |
| F13.1 | Ready -> Ready | Authorized, source-qualified read views with explicit partial/unavailable states | No new mandatory read-view implementation gap found; dataset freshness and production source enrollment are not certified | - |
| F13.2 | Ready -> Partial | Local report engine/exports and historical authenticated built-in RCA/PDF evidence | Production-datasource and authenticated error/isolation matrix beyond that built-in receipt | V01 |
| F13.3 | Partial -> Partial | Baseline/treatment formulas, guard metrics, independent settlement, and censored outcomes | Qualifying episodes, comparable windows, denominators, and uncertainty | L04 |
| F14.1 | Ready -> Partial | Source deployment, Trial, health, update/rollback, and one historical new-Trial receipt | Unchanged Trial rerun and both full-entitlement acceptance cases | I01 |
| F14.2 | Ready -> Partial | Source distribution and signed offline-package mechanics with retained isolated install evidence | Superseded path retirement and remaining distribution acceptance; Hub is not an available path | I02, I03 |
| F14.3 | Ready -> Partial | Availability/mode/profile, Trial watermark, model-health, and recall presentation | Real Release ceiling input and entitlement-transition readback | A01, I01 |
| F14.4 | Ready -> Partial | Typed bundle registration, publisher trust, disabled-first lifecycle, and revocation | Linked exact-artifact install/enable/disable/revoke/restart/disclosure receipts | X01 |
| F15.1 | Ready -> Partial | Exact-revision acquisition, independent local acceptance, workers, and historical isolation probes | Terminal installed scan, scheduled publication, and same-correlation business acceptance | S01, S02 |
| F15.2 | Ready -> Ready | Deterministic canonicalization, severity/confidence/priority separation, and adjudication | No new mandatory detected-issue processing gap found; detector calibration/promotion is separate S03 work | - |
| F15.3 | Ready -> Ready | Signed scoped packs, guarded developer helper, and coverage-equivalent rescan verification | No new mandatory pack/rescan gap found; neither customer-repository editing nor arbitrary scanner accuracy is claimed | - |

## F10: knowledge and rule work

The owning records are [ingestion](../../roadmap-implementation/interfaces/document-ingestion.md),
[cloud knowledge](../../roadmap-implementation/interfaces/cloud-resource-knowledge-lifecycle.md),
[structured retrieval](../../roadmap-implementation/interfaces/cloud-resource-knowledge-structured-rag.md),
[distillation](../../roadmap-implementation/rules-and-detection/manual-distillation.md), and
[Rule governance](../../roadmap-implementation/rules-and-detection/rule-governance.md).

- [ ] **K01, composed ingestion acceptance:** Retain local and deployed five-service receipts for
  upload, malware/protection inspection, extraction, index/citation, deletion, restart, and failure
  recovery, bound to exact service identities, versions, and contracts.
- [ ] **K02, protected sources:** Add and test the purpose-specific delegated provider authorization
  receipt before rights-managed download. Bind approved protection/SharePoint identities and policy;
  retain inspection, revocation, deletion propagation, cursor recovery, and backpressure readback.
  Local receipt, admission, bounded streaming, library availability and production binding are now
  implemented under [#2214](https://github.com/dotnetpower/fdai/issues/2214), with 132 behavior and
  29 service-suite ownership checks.
  The approved external bindings and operational receipts keep this package open.
- [ ] **K03, requester-policy implementation:** Implement the accepted v2/v3 requester path with
  exact requester/policy/content/collection binding, independent prior authority, request-time and
  final-visibility checks, denial of self-grants and missing/expired/revoked authority, all required
  safeguards, and independent persisted readback. Until then, retain the manual lane.
  The explicit authenticated API path is now implemented under #2217 with a final 672 focused passes
  and 24 actual loopback PostgreSQL passes. Manual remains the default; actual independently
  approved policy, deployment read grants and operational promotion keep this parent package open.
- [ ] **K04, extraction and answer quality:** Resolve or explicitly hold hidden UI, lost link/heading
  context, cross-section table caveats, and every pilot source hold. Retain regression cases and
  independently reviewed EN/KO query/claim evidence before declaring the corpus retrieval-ready.
  #2232 adds opt-in normalizer `2.1.1` and reader `3.1.1` for duplicate scope/chrome, ancestor and
  authentication-control validation, with retained-byte upgrade and 329 focused passes.
  Old normalizer results stay immutable. Actual pilot-source holds and independently reviewed
  paired-language claims keep this parent package open.
- [ ] **K05, source qualification:** Retain rights, purpose-bound trust/revocation, independent
  reviewers, current scanner data, protected policy mounts, and bounded source enrollment.
  Exercise connected collection, due/restart behavior, changed/unchanged and partial outcomes,
  plus an internally reviewed OS-egress-denied package-to-answer drill with zero external calls.
  Bind an eligible immutable runtime release; older application-kit receipts cannot qualify it.
- [ ] **K06, distillation conformance:** Under [#458](https://github.com/dotnetpower/fdai/issues/458),
  retain deployed ACL/purpose, withdrawal, legal-hold release/deletion, provider and cohort evidence
  before separate promotion. Inert compilation and local SQL tests are not these receipts.
- [ ] **K07, human accessibility evidence:** Retain actual EN/KO status/error/disclosure speech
  with the declared browser and screen reader. Keep `UX-39` as `U` and `needs-human` until reviewed.
- [ ] **R01, Rule upgrade and rollout:** Close the existing
  [F06.2 operational list](functional-readiness.md#f062-deployment-and-policy-rollout):
  legacy migration, complete provider collection, trusted verifier, blocked-then-cleared review,
  scheduled expiry/notifier, override source, replica convergence, direct/offline activation, and
  frozen drift-quality measurement. Current code already implements phases 7-9.

## F11-F13: learning, authority, health, and outcomes

The [learning ledger](../../roadmap-implementation/rules-and-detection/operational-learning-ontology.md)
delegates source/context/Pattern details to the
[prediction ledger](../../roadmap-implementation/rules-and-detection/prediction-learning-and-case-history.md).
The [governance](../../roadmap-implementation/decisioning/operator-governance-profiles.md),
[standing-authority](../../roadmap-implementation/decisioning/escalation-and-standing-authority.md),
[security](../../roadmap-implementation/architecture/security-and-identity.md),
[privacy](../../roadmap-implementation/architecture/data-governance.md),
[health](../../roadmap/operations/operating-and-verification.md#implementation-status), and
[reporting](../../roadmap-implementation/interfaces/reporting-subsystem.md) owners retain authority.

- [ ] **L01, complete prediction inputs:** Prove four independent source slices: external-change
  start anchor and journal continuity; target-scoped action/event-time watermark and contiguous
  audit; revisioned excluded-window history with positive initial/empty state; and post-window
  lifecycle reconciliation. Missing history remains unknown. Apply the closure-observation migration;
  wire audited EN/KO Settings preference and per-source availability to the actual collectors.
  #2224 removes false positive completeness from the current action-audit adapter: it emits
  `complete=False` with `action_history_proof_unavailable` and no normalized intervention records.
  Source/producer tests (58), Core consumer tests (41), Operator settings tests (4) and Console
  consumer tests (21) pass. This is a safety correction, not delivery of the missing positive
  event-time source; the package remains open.
- [ ] **L02, context safety:** Complete authenticated exact-target proposal/review, bounded activation,
  expiry/revocation, Forseti decisions, Saga audit, and dispatch revalidation. Retain live queued and
  in-flight revocation/expiry, hold, stop/recovery, deadline, and subscriber-isolation receipts.
- [ ] **L03, retained Patterns:** Qualify current case/revision selection, copied-data lifecycle,
  frozen/access-scoped cohorts, restart-safe publication, and candidate promotion/demotion.
  Supply a trusted coherent external issuer covering the whole read/reuse tuple through acceptance;
  the isolated LOCAL lease implementation is not a production issuer. Close
  [#2194](https://github.com/dotnetpower/fdai/issues/2194) and the prediction owner's P4-P6 gates,
  including its full-scope critique/hardening exit, without reopening already tested cleanup fixes.
- [ ] **L04, measured outcomes:** Freeze a source-versioned SLO/safety-budget evaluation plan before
  observing results. Retain independent grouped baseline/treatment episodes, mechanism evidence
  before upgrading raw response outcomes beyond O2, O7 action-specific days/sample sizes,
  complete recurrence windows, Wilson bounds, zero-escape evidence, missing/censored results, and
  uncertainty. Reuse the [F07 measurement work](functional-readiness.md#f07-installation-activation-and-measurement)
  for cost settlement rather than counting it twice.
- [ ] **A01, Release ceilings:** Replace the interim
  [shadow-only source](../../../services/core-control-plane/src/fdai/runtime/policy_administration.py)
  with production Release `capabilities` maximums under
  [#1822](https://github.com/dotnetpower/fdai/issues/1822). Prove trusted exact-release admission,
  missing/mismatched input denial, and rejection above the ceiling without weakening recall.
- [ ] **A02, governed authority receipts:** Retain fresh policy-administrator assignment/consent
  readback and one exact-revision single-operator approve/execute/independent-effect receipt with
  reduced quorum visible in audit. Exercise promotion, override, recall/demotion, restart, and
  rollback without interpreting display state as authority.
- [ ] **A03, standing authority boundary:** Resolve the provider constraint with a durable boundary
  that atomically checks the current lease/fencing generation at effect commit before admitting any
  A3-E ActionType. Separately bind the independent approval verifier and authorize effect-failure
  reversion; retain urgency and pinned live cohort/promotion evidence. ARM acceptance alone cannot
  satisfy the fence. This is deferred work, not an enabled automatic-execution path.
- [ ] **A04, safety drills:** Retain pinned cross-path safeguard/independent-effect, kill-switch
  engage/no-execute/disengage, break-glass, rollback, identity-recertification, audit-anchor, and
  no-execute approval receipts. Existing signed command and state-read implementations remain done.
- [ ] **D01, privacy gate:** Approve the deployment data inventory, accountable owners, retention
  schedule, model-provider terms, privacy assessment, regions, and compliance crosswalk.
- [ ] **D02, operational data governance:** Retain pinned deletion, legal-hold, access-review,
  audit-anchoring/WORM as required, and incident-response receipts. Verify deployed case-history
  retention/change-feed convergence and expiry rather than inferring it from defaults.
- [ ] **H01, source exporters:** Compose every one of the 15 catalog signals with a real runtime
  exporter; retain source identity/freshness, primary/fallback delivery, and recovery-drill receipts.
  Complete the linked Azure guest-event, throttling, and cross-service parity evidence.
  #2218 / [PR #2220](https://github.com/dotnetpower/fdai/pull/2220) now binds three actual local
  signals and three fields with 92 focused passes. #2228 adds a process-scoped duration from
  runtime entry to first protected readiness with a frozen observation timestamp and 80 focused passes in an
  overlapping test slice. Four signals and three fields are now bound. The remaining eleven
  signal sources and five field sources stay explicitly unavailable; this package is not complete.
- [ ] **H02, canary and stabilization:** Retain the exact consumed canary audit within the
  implemented 30-second budget, frozen shadow replay, stop/no-execute receipts, daily jobs, and
  recurrent-query signal. Prove stabilization opens, lowers authority on breach, and exits only
  when its configured conditions hold.
- [ ] **H03, operating decisions:** Resolve and version all seven open owner decisions: canary
  audit-freshness/round-trip alert budget; smoke fixtures/budgets/promotion wiring; alert ownership
  and fallback; audit investigation retention/query model; cold-start deadline; stabilization
  length/exit signals; and pre-launch load generator/per-tier budgets. The implemented five-minute
  cadence and 30-second consumed-audit check do not settle every decision.
- [ ] **V01, report acceptance:** For each declared production datasource retain identity, cutoff,
  freshness, unavailable/timeout, partial-widget isolation, and no synthetic-to-live substitution.
  Retain authenticated inventory/selection, rejected variables/formats, render-error isolation,
  and GET-only enforcement across Operator and Console. Historical built-in RCA/PDF evidence is
  reusable only for that unchanged scope.

## F14-F15: distribution, extensions, and scanning

Use the [source-deployment ledger](../../roadmap-implementation/deployment/source-deployment.md),
[distribution ledger](../../roadmap-implementation/deployment/installable-deployment-cli.md),
[productization ledger](../../roadmap-implementation/fork-and-sequencing/productization-and-extensibility.md),
[bundle ledger](../../roadmap-implementation/architecture/capability-bundle-lifecycle.md), and
[scan ledger](../../roadmap-implementation/operations/code-security-scanning.md).
The [detected-issue processing ledger](../../roadmap-implementation/operations/code-security-findings.md)
supports the bounded Ready decisions for F15.2/F15.3.

- [ ] **I01, source acceptance:** Complete WP6's three missing cases: unchanged keyless rerun,
  new full-entitlement installation, and existing Trial-to-full rerun with watermark removal.
  Retain exact digests, migration/health/readback and second-plan results; preserve the completed
  new-Trial and teardown receipts as historical evidence.
- [ ] **I02, superseded paths:** After I01, complete WP8: retire `--online` kit acquisition and
  source signed-kit adoption redirection; decide whether `azd-up.sh` is retired or diagnostic-only.
  CLI help/tests and quickstart/skill should advertise only source and signed offline installation.
  The [current parser](../../../packages/deployment-cli/src/fdai_deployment_cli/cli_parser.py)
  and [help](../../../packages/deployment-cli/src/fdai_deployment_cli/cli_help.py) still expose `--online`.
- [ ] **I03, distribution validation:** Reconcile the distribution owner's older recovery/host
  claims against newer source-deployment receipts, then retain any still-required connected
  deployment, update/recovery, and live disposable-migration acceptance on the selected revision.
  Do not repeat proven shipped-wheel/offline construction work or require a public release for source installation.
- [ ] **X01, extension lifecycle:** Retain one complete linked exact-artifact lineage covering
  install, enable, disable, revoke, restart, disclosure reload, typed action routing, and audit.
  Match artifact/release/environment identities and prove no bundle bypasses the governed path.
- [ ] **S01, installed scan terminal:** Resume [#2128](https://github.com/dotnetpower/fdai/issues/2128)
  only after its pause is lifted and a target is authorized. Retain terminal Console request,
  exact revision, coverage, isolated independent acceptance, publication, and readback. Local
  acquisition/worker/acceptance code exists; a ready worker or processing request is not a completed scan.
- [ ] **S02, scheduled and business acceptance:** Retain a scheduled scan/publication and the same
  correlation's authoritative Incident, scan result (including an explicit result with no detected
  issues), external notification, and ownership handover. Supply real Owner access, protected
  source/channel bindings, primary/backup ownership,
  and duplicate replay checks. Do not restart paused work or fabricate provider identities.
- [ ] **S03, detector quality:** Before expanding promoted coverage, retain precision >=0.90 and
  at least one true positive in both `dev` and `holdout`, without tuning on `holdout`, for the
  remaining JavaScript path, C# command/path, Java SQL/path, and C# SQL verifiers. Broader owned
  analysis calibration and production promotion remain separate; deterministic issue processing
  and pack verification do not certify these detectors.
  #2237 fixes the qualification predicate to compare exact observed counts rather than rounded
  receipt precision, with 32 focused core/receipt-path passes and unchanged recorded outcomes.
  This arithmetic correction neither evaluates nor promotes the remaining detectors.

## Deferred or conditional scope, not hidden completion work

| Item | Treatment and observable condition for resumption |
|------|--------------------------------------------------|
| Ingestion capacity and pagination | Record reviewed-corpus p50/p95 stage/queue latency, throughput, growth, and failure rate before capacity claims. Add server pagination before raising the bounded collection window. Neither is proof of unlimited scale. |
| Automatic prior-version restoration | Keep containment separate. Resume only with Vidar-owned authority, higher-sequence tested recovery, no revoked-content resurrection, restart/duplicate convergence, two-phase audit, and independent effect. |
| Policy-authoring UI and physical policy tables | Later/conditional work in the governance owner; preserve current Operator API and StateStore CAS semantics. Review policy-key/crypto-role provisioning before enabling that add-on in a new topology. |
| Hub-managed lifecycle | [Hub ledger](../../roadmap-implementation/deployment/hub-managed-lifecycle.md) has partial software but no complete install/update lifecycle. It is not a third available installation path or a prerequisite for source/offline use. |
| Public CLI publication | Protected release-batch workflow, first signed publication, and pinned public-install receipt remain productization work. Local source and signed offline paths do not depend on it. |
| EvaluationHost adapters | Dormant. If reactivated, admit results only as canonical operational cases; golden-answer success never grants promotion. |
| Broader knowledge and scan support | Non-Azure/delta/mirror/embedding expansion, arbitrary model fidelity, native coverage-guided fuzzing, and unmeasured detector classes require separate accepted scope and evidence. |

## Dependency-ordered execution plan

These are proposed work packages, not deployment authorization or a promise of calendar dates.
Run no more than two independent active outcomes per FDAI maintainer. Each batch closes its owner
ledger, assessment row, counts, and bilingual text together.

| Wave | Work and accountable lane | Prerequisite | Exit |
|------|---------------------------|--------------|------|
| 0 | Evidence reconciliation, FDAI maintainer | This audit | Each work ID has an owner, current scope/revision, receipt requirement, and valid issue before tracked delivery; stale done/deferred markers are distinguished |
| 1 | K02-K04, knowledge owners; A01, Mimir/release owner; L01-L03, learning/evidence owners; H01, runtime owner | Reviewed small designs where public contracts/authority change | Focused source/composition/persistence and negative tests pass; independently review source work; retain observation mode |
| 2 | I01 -> I02; I03; X01; R01; D01; K05 preparation, release/installation/security/privacy owners | Selected immutable release, authorized target, approved identities/trust; relevant wave-1 source | Exact source, policy, grants, retention, and rollback bindings plus independent readback; missing prerequisites stay explicit |
| 3 | K01/K05-K07; A02-A04; D02; H02-H03; V01; L02/P6; S01 -> S02, installation and capability owners | Corresponding source/configuration ready, fresh explicit live authorization, and #2128 pause lifted for scans | Terminal correlated receipts cover positive, denied, unavailable, restart, expiry/revocation, duplicate, and recovery behavior |
| 4 | L04 and any elected S03 expansion, measurement/review owners | Preregistered cohort and thresholds; admitted source histories and complete windows | Independent comparable outcomes, denominators, uncertainty, guard metrics, and separate promotion decision |

**Reassessment rule:** no mandatory checkbox is erased by narrowing the scope after testing.
Mark Ready only when its accepted scope has implementation, focused verification, and every
required owner gate. Otherwise keep Partial with exact remaining IDs; use Not assessed when
evidence is unavailable rather than claiming a new defect. Routine per-installation configuration
and explicitly deferred expansion remain visible without pretending they were validated.

## Evidence reconciliation notes

- **Historical tests:** The assessment's A-P cohorts and F06/F07 908+8 results are retained historical
  evidence, not newly executed results and not additive evidence for this audit.
- **Stale completed task:** Exact issue readback on 2026-10-18 shows #1061 closed as completed.
  Its older structured-retrieval publication checkbox is reconciliation work, not proof that the
  implemented extension is missing.
- **Still open:** Exact readback shows #1822, #2194, and #2128 open, and #458 reopened.
  The latest #2128 evidence retains the operator pause and all seven original criteria unchecked.
- **Closed but unfinished:** The owners record #355, #371, #372, #424, #632, #633, and #995
  closed as not planned, not operationally validated. Schedule a new issue or the documented
  successor before delivery; this audit does not reopen them or remove their residual work.
- **No unsupported renewal:** No Azure/model call, scanner run, database access, deployment,
  promotion, issue mutation, or external recovery was performed for this audit.

## Source-delivery hardening checkpoint

The first follow-up delivery is tracked by [#2211](https://github.com/dotnetpower/fdai/issues/2211).
It implemented a repository regression guard, not the 29 feature packages. At that checkpoint,
protected source download was unavailable. **All 29 packages still remain open**, but #2214 has
since implemented K02's local export contract and production binding as recorded above. #2217
implements the explicit K03 prior-policy API lane, and #2218 binds three H01 signals and fields.
#2228 adds the fourth H01 signal, a process-scoped guarded-startup duration rather than fleet health.
A01, learning integration, the remaining health sources and other source work are still incomplete;
live, human, provider and cohort gates remain separate. A shadow-only maximum
cannot be replaced by an unsigned file or a test approval.

The [owning test](../../../site/test/functional-readiness.test.mjs) is already selected by CI and
Pages. It now joins the specification, assessment, inventory and exact required-package column;
rejects unfinished mandatory work behind Ready; and compares bilingual work IDs and completion.
It does not authenticate receipts or prove that an author identified every obligation. Removing
an obligation or changing scope still needs owner review.

Four direct critique rounds covered these twelve concerns each. Round 1 added the backlog
guard. Round 2 corrected multiple-badge ambiguity, contradictory display labels, localized
Not assessed handling, and incomplete aggregate checks. Round 3 corrected identity substitution
and made mutation tests require the intended assertion rather than any thrown error. Round 4
applied the mandatory pre-publication gates, corrected seven display-terminology violations,
and repeated the bounded review without changing readiness or closing any feature package.

| Concern | Final bounded result |
|---------|----------------------|
| Accepted scope and authority | No runtime, approval, protection or execution behavior changed |
| Stable function identity | Exact F10-F15 ID set is checked, not merely 21 arbitrary rows |
| Complete inventory | Missing, extra and duplicate function rows are rejected |
| Mandatory completion | Ready with an unchecked required package is rejected even if document states agree |
| Valid completion transition | Completed packages allow Ready without deleting its obligation history |
| Work identity | Missing/duplicate package IDs and unknown references are rejected |
| Exact mapping | Duplicate required IDs, ranges and missing required columns are rejected |
| Bilingual parity | Current states, prior states, package references and completion match |
| Badge cardinality | Missing or multiple badges cannot hide a second visual state |
| State and display meaning | Unknown states and contradictory labels fail; localized Not assessed remains valid |
| Aggregation | Group and specification/assessment totals cover every present state |
| Regression and execution venue | Malformed transitions, mismatches and untracked Partial rows fail with intended assertions; existing CI runner selects the test |

Final focused command: `node --test site/test/functional-readiness.test.mjs`, **25 passed, no
skips**. No confirmed above-Low defect remains in this bounded guard after round 4. This is not
a Low-only assessment of the 29 unfinished packages, the entire product, or a live installation.

## Related docs

| To learn about | Read |
|----------------|------|
| Product requirements and corrected badges | [Functional specification](functional-specification.md) |
| Per-function decisions and historical test evidence | [Readiness assessment](functional-readiness.md) |
| Normative owners rather than this cross-cutting index | [Roadmap index](../../roadmap/README.md) |
