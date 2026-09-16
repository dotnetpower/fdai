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
