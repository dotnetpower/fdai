# Ownership handover operational evidence preparation

This scrubbed engineering record tracks local preparation in #1043 for the remaining human and
operational work in #458. It preserves completed source/UI delivery and records unavailable
evidence honestly. It is not a screen-reader pass, target selection, release, deployment,
provider consent, execution approval or promotion receipt.

## Observed baseline

- **Completed source:** #946 is closed; #1017 is closed. PR #1031 reviewed head
  `d5837147da2c9cce3d19122732767a31c5800e76` was protected-squashed as
  `33c76944cec4489b51bc3bb90820cc273159d99d`. Exact PR CI `34933740673` succeeded.
- **Previously pending main CI:** `34934077457` is completed/success for that exact squash,
  updated `2026-09-15T05:52:32Z`. It is no longer a delivery blocker.
- **Starting source:** protected main `97a72cc1d2785dd7ca847ae52f7b71bbaa0c0b07`, with successful
  exact-main CI `34935957375`, contains the squash. Its Console/shared-UI diff from the squash is
  empty. The primary checkout was clean; this task uses a new isolated checkout and preserves all
  other worktrees, environments, settings and services. The prior UI worktree/branch was absent.
- **Retained evidence:** the frozen browser report still hashes to
  `602c06ccbbfc590f8665b56978ef1f55c0ede6f88f586e00e6817d3cde9ffc3a` and reports 28 expected,
  zero unexpected, zero skipped, zero flaky scenarios in 48466.671 ms. It was not rerun or counted
  as new speech. [The original record](handover-ui-evidence-20260915.md) owns the 127 unit results,
  numeric geometry, contrast, 50-ID rubric and prior critique rounds.
- **#458 snapshot:** open/blocked, two historical checked criteria (source/images and private v2
  map), eight unchecked operational exits. Latest prior evidence was comment `5675421524`.
  Neither historical check establishes current image/map validity for an unselected target/release.

## Actual assistive-technology availability

The bounded inventory read product/version/process metadata only. No browser profile, tokens,
document content, private deployment state or credentials were inspected or copied.

| Item | Observation | Consequence |
|------|-------------|-------------|
| Linux workspace | WSL2; no installed Orca/browser/speech-dispatcher command found; no Orca process | Linux DOM/browser automation cannot become a real speech result. |
| Host OS | Windows 11 Enterprise, version 10.0.26200 | Record the actual host, not merely the workspace OS. |
| Selected candidate pair | Microsoft Edge 153.0.4234.32 and Windows Narrator 10.0.26100.8972 | A declared available pair for a human session, not a tested compatibility claim. |
| Reader process | No active Narrator or NVDA process observed; standard NVDA installation entries absent | Do not start a reader or change shared accessibility settings without arranging the session. Portable installations were not exhaustively searched. |
| Browser process | Edge process present; installation metadata also reports Chrome 152.0.7977.83 | An open browser process does not prove a shared, authenticated Console page. |
| Actual Console | No Linux listener on the standard port 5273 at observation | No startup/restart or provider/model probes performed. Authorized surface preparation remains necessary. |
| Speech | No heard utterance, audio capture, speech-history transcript, voice/language proof or human reviewer | `UX-39=U`, disposition `needs-human`, final score unset. No WCAG claim. |

The new [EN/KO guide](../user-guide/guides/validate-ownership-handover.md) declares 12 speech
scenarios in each locale. All 24 remain unexecuted and require actual human evidence. Existing
DOM/live-region/focus tests remain useful local mechanics, not an equivalent to listening.

## Bounded correction and review plan

This is a documentation-only continuation of approved contracts. No runtime, UI, provider,
configuration, permission, approval, ActionType or test behavior changes. The actual defects are
current prose that still directs tenant deployment through GitHub workflow variables, places an
injected-clock check under live verification, and calls completed localized/removal source absent.

The correction keeps existing history intact, uses one operator-facing guide rather than another
readiness authority, and links it from the existing owners. The inline operations ledger remains
authoritative; the older mirrored ledger is not duplicated or migrated in this task. None of the
changed documents is a source in the current System Knowledge seeds, so no catalog regeneration
or runtime-test fan-out is warranted.

### Ten focused documentation critiques

These are distinct questions against inspected evidence, not repeated tests or new source-hardening
rounds. The original source/UI rounds remain completed. Findings below are corrected in this
documentation batch or retain a named external gap.

| Round | Falsifiable question and inspected evidence | Resolution |
|-------|--------------------------------------------|------------|
| DR-01 | Did newer main invalidate the prior UI evidence? Exact ancestry, Console/UI diff and retained JSON hash. | No relevant input diff; retain measured results without reopening #1017. |
| DR-02 | Does an accessibility tree or installed executable prove spoken output? OS/process inventory and UI rubric UX-39. | No; declare Edge/Narrator, record no speech and require EN/KO human listening. |
| DR-03 | Can current instructions send the user to retired tenant workflow transport? Operations deployment paragraph versus standalone owner. | Confirmed documentation defect; replace current guidance, preserve historical rows. |
| DR-04 | Does every no-mutation command remain offline? CLI parser and source-mode help. | No; doctor/preflight read external state. Static help only before selection; source prepare is not a kit shortcut. |
| DR-05 | Can source transfer complete the selected application deployment? Standalone source-transfer boundary. | No; explicitly retain the application-execution gap and never use source mode as an automatic fallback. |
| DR-06 | Does a historical v2 map prove current scope/group/schedule/person or role/ACL eligibility? Assignment implementation plan and readiness external blockers. | No; require current distinct people, exact revisions/effective dates, fallback, separate role and ACL evidence. |
| DR-07 | Can App installation, callback reachability or A2/A4 delivery prove A1 approval? Operations App contract and channel category owner. | No; separate App grants, signed merge, OBO/consent/install/delivery/decision; no static personal token. |
| DR-08 | Can dispatch or a script reference prove membership effect or owned inverse? Execution plan, closure and recovery contract. | No; independent effect closure, fresh inverse approval, same target lineage and degraded outcome remain required. |
| DR-09 | Does an injected-clock test belong in live token-refresh verification? Existing operations verification step 7. | Confirmed documentation defect; separate local clock mechanics from bounded real renewal observation. |
| DR-10 | Are localized invitation/removal source gaps still real? Current handover i18n source and completed assignment plan. | No; correct stale concept text, retain explicit source-vs-live and no-manual-bypass boundaries. |

## #458 criterion crosswalk

The original check states are retained as history, not converted into present-tense authorization.
No missing receipt is inferred from an empty upstream template or from another deployment.

| Original criterion | Current evidence | Remaining current exit |
|--------------------|------------------|------------------------|
| Protected source and affected images | Source/CI delivery verified; old image checkbox remains historical | Owner-selected current signed release and exact image/supply-chain evidence for that source; not built here. |
| Protected Terraform plan | No target/release or current binary plan selected | Standalone exact plan, reviewed private secret references, no unexpected destruction, exact digest and expiry. |
| Independently approved apply | No apply attempted | Independent human versus managed-host UAMI, exact approval, private execution, claims, health, peer isolation and independent effects. |
| Authoritative Azure readback | No live provider read requested or performed | Exact image, ready revision/replica or selected-runtime equivalent, migrations, cadences and second zero-change plan. |
| Private v2 ownership map | Historical completion retained; private data not read | Current all-15/two-maintainer/distinct-backup, group/schedule/static fallback, scope/time, role and ACL evidence. |
| GitHub App | Older evidence records missing inputs; current installation unknown | Minimum required repository grants, protected key/webhook refs, refresh and signed-merge readback; no token disclosure. |
| Approved ChatOps and activation | Older preparation/notification evidence is not current A1 consent or installation | Current OBO/app/team/channel, independently approved activation and correlated delivery/decision. |
| Bounded end-to-end drill | Implemented mechanics and synthetic tests already complete | Real draft/retry/restart/reviewed merge/notification/audit/duplicate/stale-to-clean, plus separately authorized inverse/revocation/outage/source/cohort evidence. |
| Audit and idle-runner shutdown | No cloud slot or host touched | Sanitized coordinator/host/service audit review, all selected slots idle, owned cleanup and applicable no-deallocation proof. |
| English evidence comment | Prior comment accurately retained external blockers | Add this continuation's publication and human/operational status without checking the unmeasured exits. |

## Validation and delivery

The task-owned scope is three English/Korean document pairs plus this scrubbed internal record.
Focused checks passed for three reviewed translation pairs, three Korean-quality files, seven
punctuation/readable-Korean files, two changed roadmap documents, and one authoritative owner
ledger. A task-bounded Markdown parse resolved 137 relative links/images and checked new-guide
anchors. Both locales contain the same 12 speech families and 10 operational gates. All 13 prior
English history rows remain byte-identical; one current correction row is added. The bounded
key/token/GUID pattern scan found no such private material; this is not a general security
certification. The seven-path diff changes no runtime or selected catalog source.

Static `fdaictl provision azure --help` ran with the isolated Python environment and passed,
confirming artifact-source exclusivity, source-only preparation and the incomplete source
application boundary without a provider call. The project-board update deferred after its bounded
read timed out; issue #1043 remains authoritative. Two documentation checks were inadvertently
submitted together; they were read-only and their overlapping results are not counted twice or
as separate critique rounds. Subsequent terminal work is serial.

Tooling mistakes were resolved without changing product code: host-native `jq` could not open a
WSL path, so the retained report was passed on stdin; the roadmap checker has a diff-range argument
rather than `--help`, so the inspected no-argument changed-path contract was used. Standard Git
grep in this environment does not support `-m`; subsequent source reads used exact paths. No failed
invocation is counted as validation evidence.

No local whole-suite, runtime reimplementation, UI rerun, catalog rewrite, live model, provider
mutation, deployment, release build or promotion is part of this batch.

### Ten final integrated documentation reviews

These distinct integrated questions were checked after the last public-document correction
(explicit Owner-and-backup speech coverage and repository-scoped App/token wording). No product
source changed, so the previously completed source/UI critique rounds are preserved, not rerun.
The rows are reviews of different evidence boundaries, not repeated test counts.

| Round | Integrated question and inspected evidence | Conclusion |
|-------|--------------------------------------------|------------|
| DI-01 | Can the new guide's lane table turn publication into deployment approval? Full guide, original delivery/CI and criterion crosswalk. | No; release/target, exact plans, live speech and operations each require separate current evidence. |
| DI-02 | Can the bilingual matrix omit a role-specific or locale-specific path while claiming coverage? SR-01 through SR-12 in both files and current review controls. | Both locales retain all IDs; SR-10 requires Owner and backup subcases, and all 24 records remain unexecuted. |
| DI-03 | Can arranging speech scenarios mutate the interactive backend or expose a desktop session? Session prerequisites, venue rules and capture fields. | Isolated fixtures are explicit; real submissions/faults require separate authority, and recording is private and session-bound. |
| DI-04 | Can an old result cross goal/account or case/revision boundaries in the proposed acceptance record? Speech identity fields, SR-11 and OP evidence envelope. | Exact source, case/fixture revision, locale, time and observed focus are retained; no older result is promoted. |
| DI-05 | Does the handoff sequence admit apply before current human/host separation or allow ambiguous retry? OP-01 through OP-03 and recovery paragraphs. | Target/release precede exact digest/expiry approval; current managed-host UAMI and verification-only recovery remain mandatory. |
| DI-06 | Do independently true App, notification, role or map facts combine into authority? OP-04 through OP-08 plus current readiness contract. | No; A1 differs from A2/A4, ownership differs from RBAC/ACL, and dispatch differs from independent effect closure. |
| DI-07 | Does successful inverse or cleanup restore unrelated duty, goal or promotion state? Inverse/revocation/cleanup drill rows and execution plan. | No; inverse stays degraded, normal revocation is separate, and cleanup touches only run-owned idle resources. |
| DI-08 | Does the evidence update rewrite history or mark unsupported parent exits complete? All 13 prior owner rows and ten original #458 criteria. | History is preserved, source completion remains completed, and current external criteria are not checked by this task. |
| DI-09 | Can documentation synchronization silently alter generated or runtime inputs? Exact seven-path allowlist, source-seed intersection and linked file/anchor checks. | No runtime diff or catalog-source overlap; no generation, runtime suite or browser rerun is required for these prose-only inputs. |
| DI-10 | Can delivery or issue wording close the operational parent or overclaim accessibility? Three pairs, this record, bounded #1043 exits and planned PR wording. | Only #1043 owns local preparation; #458 stays open/blocked and UX-39 stays U with no final score or WCAG claim. |

No confirmed Medium/High defect remains in this bounded documentation change. Human listening,
target selection, provider actions, current exact-plan approval and operational receipts remain
external requirements, not downgraded local findings. Until protected merge and task-only cleanup
are verified, #1043 publication remains incomplete.

### Protected-main reconciliation

Local commit `cd6fce51a5f778f719708cc4dc0d351a43bfa17c` passed normal commit and pre-push
hooks and was published without force; the remote branch resolved to the same SHA. PR #1044
retains the bounded documentation scope and does not close #458. The mandatory pre-push
structural stage passed; no separate worker-wide validation was requested or duplicated.

Before integration, main advanced to `511178272e7cb7994609dd45f147aead5562cfa1` with successful
exact-main CI `34939635808`. Its four commits change other Console and prediction/case-retention
surfaces. A normal local merge has no conflicts and leaves all seven task documents, their
language/history checkers and dependency lock inputs unchanged. The ten integrated documentation
questions remain valid for this delta. Prior browser results remain historical results for their
frozen inputs, not a new whole-Console claim: upstream changed the broader Console manifest,
including removal of Live-only stylesheet rules. No new browser, speech or provider pass is claimed.

The initial PR head's running CI is superseded by the locally integrated head, not rerun as an
edit-loop test. Exact final-head CI, protected merge, remote ancestry and task-only cleanup remain
delivery requirements to reconcile on #1043. #458's current operational evidence remains open.

## F06 readiness closure evidence - 2026-10-18

This section records the bounded F06.1-F06.3 source and documentation closure performed from
protected main `966082d265a7a230b41394b67e63ccd6fd328fa9`. It does not update the functional-readiness
owner, select a customer target, supply production owners or evidence, deploy a verifier App,
activate enforcement, call a live provider, or record a promotion receipt.

### Mandatory behavior inventory

| Boundary | Mandatory verbs inspected | Result |
|----------|---------------------------|--------|
| F06.1 proposed change | normalize, type, bind target and revision, scope, compare alternatives, simulate, retain stop conditions, retain rollback, separate approval, close by independent observation | Reverified. The 120-case planning/change-assessment cohort found no hidden local gap. |
| F06.2 drift and compliance | collect current state, detect drift and control gaps, cite the active Rule, resolve scope, evaluate policy, resolve conflicts, apply exemptions/overrides, revision activation, retain rollback, emit only inert correction proposals | Implemented locally. The 78-case drift and Rule-activation cohort passed. Legacy migration, complete provider collection, trusted-verifier deployment, and operational rollout remain evidence-bound deployment work. |
| F06.3 ARB and ORR | freeze evidence, assess constraints, verify ownership/readiness, fail closed, derive an immutable receipt, persist review identity, publish a shadow correction request, enter unified risk evaluation, prohibit dispatch, require separate approval and promotion | The missing upstream runtime and receipt boundaries were implemented. Production provider/owner/report bindings and governed runtime/promotion receipts remain external. |

### Ten cumulative critique rounds

Each round used 10 distinct controls against the final cumulative F06 slice. "Rejected" means the
suspected issue was disproved by source and focused evidence, not ignored.

| Round | Ten controls | Confirmed or rejected findings and resolution |
|-------|--------------|-----------------------------------------------|
| F06-C01 mandatory verbs | 1 typed change; 2 exact target; 3 source revision; 4 bounded scope; 5 alternative comparison; 6 simulation; 7 stop condition; 8 rollback; 9 approval separation; 10 independent effect closure | Rejected hidden F06.1 gap. All 10 controls are owned by existing planning/change-assessment paths; 120 focused tests passed. |
| F06-C02 drift and compliance | 1 provider-neutral baseline; 2 current evidence; 3 field-level difference; 4 control-gap issue; 5 active Rule citation; 6 scoped policy; 7 exemption; 8 deterministic conflict; 9 revisioned activation; 10 inert remediation | Confirmed one documentation defect: phases 7-9 were implemented but still unchecked. The Rule governance ledger now records the implemented identity upgrade, pair CAS, retention, retirement, and rollback; 78 focused tests passed. |
| F06-C03 ORR adapter selection | 1 complete posture/report pair; 2 active Rule generation; 3 active ontology digest; 4 non-empty `remediates`; 5 exact Rule parameters; 6 explicit DI precedence; 7 shadow mode; 8 no executor identity; 9 unified risk gate; 10 no dispatch | Confirmed a Medium wiring gap: the concrete typed adapter existed but no upstream runtime selected it. Runtime now selects it after Rule-generation reconciliation, preserves explicit DI, and fails closed on incomplete identities; 11 focused tests passed. |
| F06-C04 ARB receipt authority | 1 receipt required; 2 digest; 3 review identity; 4 evidence set; 5 target revision; 6 conformant outcome; 7 effective interval; 8 human approval; 9 authoritative projection; 10 `execution_authority=false` | Confirmed a High readiness gap: provider attestations and mutable manifest state could satisfy the gate without resolving the immutable Decision receipt. Runtime readiness now requires and revalidates the projected receipt; 32 focused tests passed. |
| F06-C05 receipt retrieval | 1 bounded query; 2 source completeness; 3 truncation; 4 latest timestamp; 5 same-time ambiguity; 6 timezone; 7 typed reconstruction; 8 digest revalidation; 9 expired receipt; 10 missing receipt | Confirmed a Medium hardening defect: a bounded ontology query could select an apparently latest receipt from an incomplete candidate set. Truncated or source-incomplete scans now fail closed; the focused projection/readiness cohort passed 25 cases. |
| F06-C06 ARB observation composition | 1 complete source bundle; 2 ontology store; 3 Forseti-only binding; 4 no direct agent call; 5 deadline; 6 deterministic scenario; 7 DecisionCase; 8 ImpactEnvelope; 9 read-only projection; 10 no action authority | Confirmed a Medium composition gap: the implemented loop existed only in tests. Core now binds the complete source bundle to Forseti when prerequisites exist and otherwise leaves it unavailable; the 194-case observation/runtime/layout cohort passed. |
| F06-C07 persistence and replay | 1 atomic first writer; 2 key hashing; 3 cross-replica conflict; 4 stored Change digest; 5 projection status; 6 CAS retry bound; 7 restart; 8 incomplete projection hold; 9 no evidence reread; 10 no authority restoration | Confirmed a Medium persistence gap: runtime composition had no durable ARB idempotency/projection fence. The StateStore adapter now persists both. Four tests passed through the isolated PostgreSQL 5433 wrapper, including restart readback. |
| F06-C08 documentation truth | 1 canonical owner; 2 Korean parity; 3 one authoritative ledger; 4 append-only history; 5 evidence strength; 6 implementation vs validation; 7 wiring vs activation; 8 no production inference; 9 no functional-readiness edit; 10 no F07 edit | Confirmed duplicate/stale ORR ledger truth. The owner was migrated to its mirrored ledger, paired translations were reviewed and refreshed, and every current state is no stronger than local evidence. F06 and framework owners only were changed. |
| F06-C09 failure and degradation | 1 missing source; 2 partial source; 3 missing ontology store; 4 state conflict; 5 projection failure; 6 broker failure; 7 malformed proposal; 8 stale report; 9 receipt ambiguity; 10 provider outage | Rejected fail-open behavior after fixes. Each condition disables, holds, retries with stable identity, or raises; none promotes, approves, dispatches, or executes. |
| F06-C10 final integrated | 1 implementation; 2 runtime wiring; 3 persistence; 4 default activation; 5 measurement; 6 authority ceiling; 7 exact evidence; 8 bilingual/ledger truth; 9 scope isolation; 10 residual honesty | No confirmed defect above Low remained. Production activation and measurement are explicitly absent rather than inferred from code or tests. |

### Before and after reproductions

| Finding | Before | After |
|---------|--------|-------|
| ORR adapter selection | Baseline `bootstrap_readiness.py` at `966082d` contains no `EventBusReadinessRemediationPublisher` selection. | Current source contains the selector and the focused ORR cohort passes 11 cases. |
| ARB observation runtime | Baseline `bootstrap_pantheon.py` contains no `_build_architecture_review_loop`. | Current runtime builds the loop from the complete source bundle and binds it only to Forseti. |
| Receipt-derived readiness | Baseline has no `delivery/architecture_review_decision_receipt.py`. | Current runtime resolves the projected receipt; missing, drifted, expired, ambiguous, or incomplete receipt evidence fails closed. |
| Rule revision ledger | Baseline records `- [ ] Implement phases 7 through 9`. | Current ledger records `- [x]` and cites the existing phase 7-9 implementations plus the passing 78-case recheck. |
| ARB persistence | Baseline has no durable ARB observation StateStore adapter. | `with-local-test-database.py uv run pytest ...test_state_store_architecture_review.py` passed 4 cases against isolated PostgreSQL. |

### Implementation and operational state matrix

| F06 slice | Implemented | Actually wired | Persistent | Operationally active | Measured |
|-----------|-------------|----------------|------------|----------------------|----------|
| F06.1 planning boundary | Yes | Yes, through planned-change assessment | Existing Process/evidence owners | Product path available; execution remains separate | 120 local focused cases; no live change |
| F06.2 drift/control evaluation | Yes | Yes, through detection, T0 governance, and typed proposals | Yes, including activation generations and rollback lineage | Depends on deployment provider coverage and selected profile | 78 local focused cases; no provider completeness measurement |
| F06.2 revision phases 1-9 | Yes | Yes, authority CAS paths exist | Yes, PostgreSQL ledgers and retained artifacts | No production upgrade/rollback receipt supplied here | Existing phase tests plus current 78-case bounded recheck |
| F06.3 ARB observation path | Yes | Conditional on one complete authenticated source bundle and ontology store | Yes, idempotency and projection status in StateStore | Inactive upstream without deployment-owned sources | 194 local focused cases and 4 isolated PostgreSQL cases |
| F06.3 receipt production gate | Yes | Yes, in the workflow guard with ontology receipt provider | Decision and Approval ontology records | Inactive until owners, evidence, approval, and a current receipt exist | 32 local focused cases plus 25-case hardening recheck |
| F06.3 ORR review | Yes | Conditional on the complete posture/report pair | Report/audit state uses StateStore | Inactive upstream without production providers | Existing readiness cohorts; no governed shadow receipt |
| F06.3 ORR remediation ingress | Yes | Yes, selected after active Rule reconciliation when ORR is active | EventBus durability is deployment-owned; request identity is stable | Shadow-only; no live publication or approval claimed | 11 local focused cases; no live broker receipt |

### Exact validation evidence

- `uv run pytest -q --no-cov services/core-control-plane/tests/core/operational_planning ...`:
  120 passed for the F06.1 boundary.
- `uv run pytest -q --no-cov services/core-control-plane/tests/core/rule_activation ...`:
  78 passed for F06.2 drift, review, configuration, and activation.
- Focused ORR publisher/runtime tests: 11 passed; task-scoped Ruff and strict mypy passed.
- Focused ARB readiness/projection/checker tests: 32 passed; the final receipt-selection recheck
  passed 25 tests; task-scoped Ruff and strict mypy passed.
- Focused ARB observation, persistence, Forseti, runtime, layout, and composition-split tests:
  194 passed; task-scoped Ruff and strict mypy passed.
- `uv run python scripts/automation/with-local-test-database.py uv run pytest -q --no-cov
  services/core-control-plane/tests/delivery/persistence/test_state_store_architecture_review.py`:
  4 passed against the isolated loopback database.
- Translation quality, translation SHA parity, punctuation, roadmap tracking, ARB structure,
  derived-source, framework-integrity, and commit contract checks passed for their task-owned
  inputs. No repository-wide suite, live Azure/model/provider call, push, PR mutation, deployment,
  or promotion was performed.

### Residual conditions and readiness decision

- **F06.1:** remains truthfully `Ready`; no hidden local implementation gap was confirmed.
- **F06.2:** must remain `Partial`. Legacy installation migration, complete current provider
  collection, the trusted Entra verifier deployment, a blocked-then-cleared governed review, and
  operational rollout receipts were not supplied.
- **F06.3:** must remain `Partial`. Production posture/report providers, accountable owner and
  evidence bindings, a governed ownership-handover/ARB receipt, shadow cohort measurement, and an
  authoritative promotion record were not supplied.
- **ARB roadmap expansion outside the current F06.3 supported scope:** the observation trace still
  lacks distinct owned records for every context, specialist, bundle, envelope, recommendation,
  and projection stage. Adding those records requires accepted schemas and fixed-owner topic
  bindings across multiple Pantheon agents; inventing them here would broaden the public contract
  and agent ownership beyond the approved boundary. The implemented provider-neutral path holds
  when deployment sources are absent and does not synthesize those records.

Therefore neither F06.2 nor F06.3 may truthfully become `Ready` from this local closure alone.
All confirmed locally actionable defects in the stated F06 readiness slice are fixed; the
remaining conditions are external evidence, deployment bindings, governed promotion, or a
separately designed broader ARB topic-contract expansion.
