---
title: Validate ownership handover
description: Collect separate accessibility, deployment, identity, and recovery evidence without treating a source check as operational approval.
---
# Validate ownership handover

Use this guide to prepare the remaining checks after the ownership-handover source and local UI
tests have passed. Record actual screen-reader output separately from deployment and operational
evidence. A passed preparation check never grants access, approves a plan, or enables enforcement.

> **Current boundary:** [#946](https://github.com/dotnetpower/fdai/issues/946) and
> [#1017](https://github.com/dotnetpower/fdai/issues/1017) completed source and local UI delivery.
> [#458](https://github.com/dotnetpower/fdai/issues/458) remains the operational acceptance issue.
> Keep its unsupported criteria open. Historical image or private-map evidence does not attest a
> newer release or prove that people, permissions, or sources are still current.

## Choose the evidence lane

Keep these results separate, even when they use the same source revision.

| Lane | What a successful result proves | What it does not prove |
|------|---------------------------------|------------------------|
| Source and local UI | The declared deterministic or synthetic scenarios pass for their exact inputs | Real speech, current provider state, deployment, or promotion |
| Assistive technology | A reviewer heard the required information with the recorded browser and screen reader | Another browser/reader pair, all WCAG criteria, or backend effect success |
| Publication | The exact reviewed source passed protected checks and was merged | Current image provenance, target selection, or apply approval |
| Deployment | The selected release reached its declared target through exact approved plans and independent readback | Complete identity, document, recovery, or adoption acceptance |
| Operations | Current source-bound receipts satisfy each selected operational criterion | New authority or permission to skip a later approval |

The [retained UI review](../../internals/handover-ui-evidence-20260915.md) covers 28 distinct
synthetic browser scenarios and 127 unit tests. It leaves `UX-39` unmeasured, with no final score.
Reuse those results only when the relevant code, tests, configuration, dependencies and environment
are unchanged. Never count DOM labels, an accessibility-tree snapshot, or a test rerun as speech.

## Prepare a real screen-reader session

1. **Declare the pair.** Use supported Microsoft Edge with Windows Narrator, or explicitly record
   another pair such as Chrome with NVDA. Record OS, browser and screen-reader versions, speech
   synthesizer and voice, language switching, scan/browse mode, verbosity, and date. Availability
   of an executable is not evidence that the reader is running or that a Korean voice works.
2. **Bind the surface.** Record the exact source revision, route, case/goal revision, data mode,
   desktop viewport and navigation state. Use the actual `/agent-oversight/mapping-reviews` and
   `/documents?handover_goal=<goal-id>` routes, not a replacement static page.
3. **Preserve the venue.** Reuse an authorized, healthy Console at `http://localhost:5273` for a
   full-stack session. Sign-in remains provider-hosted. Do not export credentials, change the
   browser principal, start services with unapproved provider probes, or substitute a test port
   and call it authenticated full-stack evidence.
4. **Separate test actions.** An explicitly isolated synthetic harness may supply pending,
   conflict and role-change states. Label it as test-only and use its leased port. A test operator
   must arrange those states before the reader session; this guide does not install a fixture in
   the interactive Console. On a real backend, submissions, approvals, uploads and outage drills
   require their own authorized cases and scope. Do not create them just to make a UI state appear.
5. **Listen before scoring.** A human reviewer listens in both English and Korean and records
   what was actually spoken, its order and the keyboard focus destination. If the reader, voice,
   authorized surface or human listener is unavailable, stop that scenario and record the gap.

Do not turn on a screen reader, install a voice, capture desktop audio, or change another person's
accessibility settings without agreeing the local session. Keep recordings in approved private
storage and capture only the authorized test window, not background conversations or credentials.

### Speech scenarios

Run each row separately in `en` and `ko`, for 24 scenario-locale records. These are required checks,
not a report that they passed. A controlled state means a prearranged isolated fixture or a
separately authorized real case. Never infer an unexercised state from a neighboring pass.

| ID | Action and controlled state | Required spoken information and focus observation |
|----|-----------------------------|---------------------------------------------------|
| SR-01 | Open Mapping reviews while its catalog loads, then becomes available | Loading and ready content are distinguishable; decorative skeleton blocks do not become fake values. |
| SR-02 | Enter an invalid scoped field and follow its correction link | The field name, invalid state and useful correction are available without guessing; focus reaches that field. |
| SR-03 | Add a declaration, then remove it | The new row or remaining add control has a meaningful name and useful focus; no keyboard trap. |
| SR-04 | Submit a permitted scoped request while its response is held, then return HTTP 202 | Pending and awaiting Core are conveyed without announcing approved, merged or applied success. |
| SR-05 | Expand immutable case details and read a two-review case | Expanded/collapsed state, review count and exact evidence remain understandable; two reviews do not mean a merge. |
| SR-06 | Observe expired/unavailable scope evidence or a denied case, then manually refresh | The unavailable/denied reason is conveyed; recovery does not announce nonexistent coverage or retain an obsolete error. |
| SR-07 | Open the checklist and expand its six evidence areas | Each area and missing/linked/exempt state is identifiable; goal/source detail can be read in order. |
| SR-08 | Enter an invalid source goal ID and navigate its help | The field name and 64-character format requirement are conveyed; a disabled request is not announced as completed. |
| SR-09 | Submit a permitted exemption, hold the response, return a conflict, then refresh | Pending, conflict and refreshed evidence are distinct; useful context survives and the obsolete error clears. |
| SR-10 | Separately exercise permitted Owner and backup review controls and observe each server result | Review versus acceptance is accurately conveyed; when the control disappears, focus returns usefully without stealing deliberate focus. |
| SR-11 | Change the goal/account while an old response is delayed | No old-goal acceptance or old-account authority is announced as current; new context and focus remain identifiable. |
| SR-12 | Use keyboard file selection, reject a multi-file handover input, and observe upload-with-link-failure | One-file guidance and the failed association are conveyed; uploaded does not mean linked or accepted. |

For each row retain the following evidence, not just a checklist tick:

| Field | Required content |
|-------|------------------|
| Identity | Scenario ID, locale, exact source and fixture or authorized case revision, UTC session time |
| Pair | OS/browser/reader versions, speech settings, viewport and venue |
| Interaction | Actual keys, starting state, expected semantic information and resulting focus |
| Speech | Verbatim heard output or a private recording/time range, including omissions and duplicate or interrupted announcements |
| Review | Reviewer attribution, result, issue reference for a defect, and whether retained content was checked for sensitive data |

Use `passed`, `failed`, `needs-human`, or `needs-infrastructure`. An unexercised assertion cannot
pass. Speech history may support a human's listening record; copied DOM text cannot replace it.
Missing human listening stays `needs-human`. Unavailable test infrastructure is recorded separately
with its owner. Keep `UX-39` as `U` and the final score unset until all required speech evidence
is reviewed. Even a complete [rubric](../../reference/ui-ux-quality-rubric.md) score is not WCAG
certification.

## Prepare the operational evidence packet

Before a provider read or change, the deployment owner selects the private target reference,
tenant/subscription, environment, region, runtime profile and exact release. Use existing identity
or a provider-hosted sign-in. Do not infer them from an issue title, an old run, the active default
subscription, or a cached artifact. Put populated target data and credentials only in approved
private configuration, never chat, this repository, a public issue, or command-line secret values.

| Gate | Local preparation | Current external evidence and accountable reviewer |
|------|-------------------|---------------------------------------------------|
| OP-01 Release and target | Preserve exact source/CI history; identify the approved artifact route without building or selecting a release | Deployment owner selects a complete signed kit and exact service-image digests; retain current signature, provenance and source-CI evidence for that release. |
| OP-02 Exact plans | Read the [standalone contract](../../roadmap/deployment/installable-deployment-cli.md); list intended scope and stop conditions | An independent human approves each current binary-plan digest and expiry; a destructive change requires a separate exact confirmation. A changed plan needs new approval. |
| OP-03 Private execution | Identify required Foundation, network, state and migration receipts | A dedicated managed-host user-assigned Managed Identity executes in the VNet through the coordinator. Retain host identity, pre-effect claims, Foundation handoff, exact migrations/images, health, peer isolation, second zero-change plan and cleanup. |
| OP-04 Current people and duties | Review the v2 shape and distinct-person rules without populating the upstream map | Identity/ownership reviewer verifies all 15 agents, two distinct FDAI maintainers, current primary plus distinct backup coverage for every non-autonomous agent, exact scope/effective dates, current group/schedule expansion and static fallback, plus separate role eligibility. |
| OP-05 GitHub ownership | Review the [App and merge contract](../../roadmap/interfaces/agent-stewardship-operations.md#deployment-configuration) | Repository owner proves the App installation and issued token are scoped to the intended private repository with required contents/PR/metadata/issues permissions. Retain protected key/webhook references, credential-refresh outcome without token values, independent human review/merge and exact signed-merge readback. No static personal token. |
| OP-06 ChatOps | Separate A1 human approval from A2 alerts and A4 digests | Channel owner verifies the selected A1 identity, delegated on-behalf-of (OBO) flow, consent, approved app installation and exact team/channel. Retain delivery, acknowledgement and decision correlation plus reviewed governance activation. A preparation proposal or A2/A4 success proves none of these. |
| OP-07 Documents | List source/version/digest, admission, reader-group ACL and retention/hold requirements | Document owner proves current access control list (ACL), admitted source and exact version, Reader backup access, source withdrawal and retention/legal-hold behavior. Unknown hold never permits erasure; unrelated document access stays denied. |
| OP-08 Membership effects | Select the authorized drill and expected observation, not a direct Graph command | Separate mutation and observation identities, current independent execution approvals, role map, promotion and all seven safeguards are verified. Heimdall's authoritative readback and audit closure, not an API acknowledgement, prove the exact membership effect. |
| OP-09 Recovery | Freeze each drill, deadline, stop condition, affected target and recovery owner | Recovery reviewer verifies owned inverse, normal revocation, duplicate, restart, outage and stale-to-clean drills below without duplicate effects or unrelated changes. |
| OP-10 Cohorts | Freeze the scenario set, baseline/treatment, version, inclusion rules, denominators and observation windows before measurement | Independent reviewer retains deployed urgency, adoption and applicable document-performance evidence against the owning policy. Synthetic counts, a drill success or issue closure never substitute for promotion evidence. |

The Owner-only `GET /handover/readiness` report summarizes existing records for ten minutes. It
does not run provider checks. `source_gaps=[]` means bounded source requirements are complete;
`mode=shadow` and `operationally_ready=false` remain explicit. Partial scans, invalid rows and
unmeasured intervals are not a complete healthy population. Never clear a blocker by editing the
report or by treating a role label as current identity or ACL proof.

### Use the current deployment path

Follow the [deployment quickstart](../deploy-quickstart.md) only after target and artifact
selection. `fdaictl provision azure` coordinates exact-plan review and the Bastion-reachable
managed host; GitHub Actions may validate source and publish releases, not plan/apply/resume or
tear down a tenant. A historical reference to a bot-owned workflow apply means separated
execution identity, not permission to revive that transport.

Static CLI help is safe before target selection. `doctor` and provider preflight inspect external
identity or target state and are not offline evidence. `--prepare-only` applies only to explicitly
selected source mode; it is not a signed-kit verification shortcut. Source mode currently stops
before connected application execution and is not a fallback that completes #458. Do not invent a
`provision apply` command or bypass the coordinator with a direct Terraform invocation.

After ambiguous apply, preserve the immutable claim and use verification-only recovery. Do not
repeat apply or create another run directory to evade the claim. Approval and execution identities
remain distinct. Release publication, app installation, runtime promotion and each new plan need
their own current evidence and authority.

### Run separately authorized drills

Each row needs a current target-bound plan, total/per-stage/no-progress deadlines, stop conditions,
an observation owner and a safe cleanup boundary before it starts. Fault injection is not an
implicit part of read-only validation. A provider timeout, 429/503 or unexpected model fallback
ends the attempt; retain bounded evidence rather than retrying the same live request.

| Drill | Observable exit | Stop or hold condition |
|-------|-----------------|------------------------|
| Draft, restart and reviewed merge | One admitted upload creates one review-only PR; identical-upload retry and restart reuse it; independent human merge yields one matching notification and Saga merge audit. | Missing App/consent/current source, uncertain delivery or mismatched candidate digest. |
| Duplicate delivery | Replaying the same signed delivery ID changes no effect, PR count, notification count or audit count. | Lost original correlation or unclear ownership of the first effect. |
| Identity outage and stale-to-clean | Graph failure retains last successful observation without refreshing it; expired data is unavailable. Fresh exact-map observation proves recovery and transition-only audit. | Incomplete coverage, wrong map revision or no independent current readback. |
| Membership and owned inverse | Independently observe the original owned effect; a new approved `recovery_of` inverse uses the same target lineage and lock and closes from independent readback. Core remains `degraded`; duties and goals are not restored. | `ALREADY_APPLIED`, unknown ownership, ambiguous dispatch, intervening attempts or expired approval. |
| Normal revocation | Current replacement coverage and fresh review precede IAM removal; independent removal precedes reviewed old-duty merge; unrelated role demand is preserved. | Missing pinned replacement, active or uncertain demand, or unmatched merge. This is not the recovery inverse. |
| Document withdrawal and retention | Current ACL/source changes remove eligibility without leaking content; legal hold preserves retained material, and permitted cleanup has independent absence evidence. | Unknown hold, unavailable source, changed version or incomplete purge coverage. |
| Approval continuity and cohorts | Delivery precedes human-silence timing; the current eligible fallback receives the unchanged action within its original deadline; frozen cohorts retain all eligible and excluded samples. | Unknown recipient, missing delivery, stale forecast or exceeded deadline. Silence never approves. |

Do not advance provider clocks to test token expiry in a deployment. Injected-clock refresh tests
are local mechanics only; a live refresh receipt requires an approved bounded real observation.
Review sanitized coordinator, managed-host and service audit records for leakage indicators. Stop
only resources owned by the selected run after every slot is idle; preserve required retention and
the no-deallocation condition where applicable. Failed cleanup leaves the run incomplete.

## Close only evidenced work

For every #458 criterion, retain its exact release/target binding, source identity, event/effective/
recorded times, expiry, completeness, digest, reviewer and private receipt location. Publish only
a sanitized English summary and non-sensitive evidence references. Mark an exit complete only
after its required current observation and independent review exist.

Report local implementation, source publication/merge, actual speech, deployment and operations
separately. Leave #458 open while any operational exit lacks evidence. Ask only for the next
necessary private target selection, session arrangement, provider-hosted action or exact-plan
approval. Never request a secret or ask for blanket approval of future plans.

## Related docs

| To learn about | Read |
|----------------|------|
| Ownership and access as separate axes | [Agent ownership](../concepts/ownership-and-handover.md) |
| Current implementation and remaining external scope | [Assignment implementation plan](../../roadmap/interfaces/human-agent-assignment-implementation-plan.md) |
| Operational source and failure contracts | [Ownership lifecycle](../../roadmap/interfaces/agent-stewardship-operations.md) |
| Actual UI measurements and their limits | [Retained UI review](../../internals/handover-ui-evidence-20260915.md) |
| Approval categories and trust | [Channels and notifications](../../roadmap/interfaces/channels-and-notifications.md) |
| Exact plans and managed-host execution | [Standalone deployment](../../roadmap/deployment/installable-deployment-cli.md) |
