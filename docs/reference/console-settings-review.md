# Console Settings Improvement Inventory

This review covers all eight production Settings menus. The baseline is `f8a0c49998`.
It distinguishes observed defects, source-supported defects, and useful usability improvements.
Implementation checks and browser acceptance are separate; an unavailable provider is never
replaced with sample data or treated as a successful operation.

## Scope and counts

| Menu | Original items | Additional items |
|------|----------------|------------------|
| Models | 12 | 1 |
| General | 12 | 0 |
| Environment and deployment | 10 | 1 |
| Runtime policies | 10 | 0 |
| Operator memory | 10 | 0 |
| Identity and access | 12 | 0 |
| Integrations | 12 | 0 |
| Diagnostics | 12 | 0 |
| Total | 90 | 2 |

## Models

The original authenticated Models request took 9,714 ms. The summary read must not wait for
Azure catalog discovery. Account metadata remains a bounded, explicit read with no inference,
deployment, role change, or execution authority.

| ID | Improvement |
|----|-------------|
| ML01 | Read authoritative configuration and save readback through `view=summary`; navigation prefetch uses the same fast representation instead of discovering provider models. |
| ML02 | Load the catalog only when its workspace is selected; distinguish not requested, loading, unavailable, and observed data. |
| ML03 | Read independent model, deployment, and quota metadata concurrently after exact account resolution; cancel siblings when the attempt fails. |
| ML04 | Keep summary and full projections in separate principal-client caches; coalesce matching reads and invalidate both after mutation or forced refresh. |
| ML05 | Retry a failed catalog read without blanking configuration, routing, or governance drafts. |
| ML06 | Preserve the actual catalog observation time and diagnostic reason; do not describe unavailable data as zero observed models. |
| ML07 | Render at most 12 catalog cards per page while filtering the complete returned catalog; retain honest result and page counts. |
| ML08 | Clear catalog search, restore search focus, and reset the page when the query changes. |
| ML09 | Restore the selected model workspace from its URL while preserving locale and unrelated query parameters. |
| ML10 | Include a domain typed but not yet added to the allowlist in the unsaved-changes guard. |
| ML11 | Show actionable feedback when clipboard access is unavailable instead of silently ignoring governance-draft copy. |
| ML12 | Reinitialize the mounted-client lifecycle guard so settled mutations can clear their busy state after a client change. |
| ML13 | Additional source defect: preserve authenticated management capability flags after narrator or web-search saves instead of incorrectly turning Owner controls read-only. |

Evidence: model catalog and IAM API unit tests, Models decoder/cache tests, and the production
`settings-model-binding-policy.spec.ts` interactions. Provider mocks prove mechanics only, not
live inference access or operational model latency.

## General

The 12 original items comprise six source defects and six usability improvements. The table
records source implementation, not browser acceptance.

| ID | Classification | Implemented change |
|----|----------------|--------------------|
| G01 | Source defect | Require loaded account context before a combined account/browser reset; do not treat an unknown preference as absent. |
| G02 | Source defect | Trim the timezone before validation and send that same normalized value in preference and briefing requests. |
| G03 | Source defect | Preserve newer account edits through preference save and readback instead of hydrating an older saved draft over them. |
| G04 | Source defect | Retain readback failures after successful briefing mutations and expose a GET-only context reload. |
| G05 | Source defect | Track unfinished response-policy synchronization and retry only that step after preferences have already been saved. |
| G06 | Source defect | Distinguish loading, failed/unknown, and loaded-empty account context; avoid false current/empty messages and offer reload. |
| G07 | Usability improvement | Confirm the browser/account reset scopes without deleting briefing subscriptions or saved memories. |
| G08 | Usability improvement | Discard unsaved account edits without a server mutation or broad preference reset. |
| G09 | Usability improvement | Show readable daily scheduling and formatted next-run time while retaining the exact cron expression in details. |
| G10 | Usability improvement | Give each subscription and memory removal action an item-specific accessible name. |
| G11 | Usability improvement | Associate timezone/hour errors with their fields, expose invalid state, and focus the first invalid field on a blocked action. |
| G12 | Usability improvement | Show loaded briefing-history counts and reveal results beyond the initial ten without inventing a complete server history. |

Implementation under `console/src/routes/`: `settings.tsx`, `settings.controller.ts`,
`settings.context.tsx`, `settings.model.ts`, and the paired `i18n/settings-general.*.json` catalogs.
Existing focused evidence: `settings-general.test.ts`, `settings-general.controller.test.ts`,
and `settings-general.catalog.test.ts` in the same directory. Controller cases use mocked hooks
for request payloads, draft races, partial-save recovery, readback failures, and discard.
Browser focus, accessible-name, schedule-layout, and history-expansion acceptance is not claimed.

## Environment and deployment

The ten original items comprise two source defects, seven usability improvements, and one
performance improvement. E11 is a separate additional improvement, not a replacement for E09.
The implementation remains read-only; this inventory does not establish browser acceptance.

| ID | Classification | Implemented change |
|----|----------------|--------------------|
| E01 | Source defect | Separate optional evidence-source absence from request or projection-validation errors instead of collapsing every failure into unavailable. |
| E02 | Source defect | Use the same effective expiry/status projection for visible proposals and published screen context. |
| E03 | Performance improvement | Replace the permanent one-second render interval with a bounded nearest-expiry timeout; idle empty/unavailable data needs no expiry timer. |
| E04 | Usability improvement | Distinguish expired evidence from no current proposal and retain the known expiry timestamp and refresh explanation. |
| E05 | Usability improvement | Offer an explicitly read-only deployment-evidence reconnect; it remounts the source view and does not retry a deployment. |
| E06 | Usability improvement | Search loaded observer targets, filter by effective status, and show displayed/loaded counts with a clear no-match state. |
| E07 | Usability improvement | Move tab focus with navigation keys without activating another network-backed panel; activate through the tab button. |
| E08 | Usability improvement | Add a canonical Readiness recovery link for an invalid environment tab while preserving data mode. |
| E09 | Usability improvement | Restore the deployment evidence subview from a validated `deployment-view` URL parameter across URL-keyed remounts, tab changes, and reloads; preserve locale, compatibility defaults, and inactive-content unmounting. |
| E10 | Usability improvement | Separate known blockers from missing evidence, label known prerequisite codes, and retain unknown source codes without inferring eligibility. |
| E11 | Additional usability improvement | Show the last successful projection-read completion time separately from authoritative expiry, without presenting receipt time as provider observation time. |

Implementation under `console/src/routes/`: `environment-deployment.tsx`,
`environment-deployment-observers.tsx`, `environment-deployment.i18n.ts`, and optional controlled
presentation props in `provision.tsx`/`provision-view.tsx`. The observer renderer reuses the
existing strict decoder; E09 adds no hidden stream or mutation authority.
Existing focused evidence in that directory: `environment-deployment.test.ts`,
`environment-deployment-observers.test.ts`, `environment-deployment.interaction.test.ts`,
`provision-view.controlled.test.ts`, and the `provision evidence tabs` cases in `provision.test.ts`.
Wrapper/controlled-view cases use mocked hooks. One isolated 1440x900 production-component
scenario with intercepted API/SSE responses passed expiry, URL/locale persistence through
tab changes and page reload, inactive-stream quietness, and GET-only reconnect checks.
This does not establish keyboard, responsive, or complete visual acceptance.

## Runtime policies

The ten original items comprise three source defects and seven usability improvements.
The table records source implementation and does not claim browser acceptance.

| ID | Classification | Implemented change |
|----|----------------|--------------------|
| R01 | Usability improvement | Remove net-noop scalar/object edits and redundant resets from the dirty batch while preserving meaningful override removal. |
| R02 | Source defect | Retain raw numeric edits, expose invalid input, and block the complete save batch rather than silently omitting an invalid visible edit. |
| R03 | Source defect | Preserve a conflicting draft for review against the latest revision; require an explicit reapply decision and a separate save. |
| R04 | Source defect | Retry a failed save without reloading away the draft; retain the existing initial-load retry path. |
| R05 | Usability improvement | Explain unavailable settings with the source-provided reason and a clear fallback when no reason is supplied. |
| R06 | Usability improvement | Validate structured-policy JSON syntax and object root locally, associate field errors, and block invalid submission without replacing server validation. |
| R07 | Usability improvement | Discard the unsaved batch without issuing persisted override-reset commands. |
| R08 | Usability improvement | Preview pending values and inheritance after override removal without labeling an uncommitted draft as effective. |
| R09 | Usability improvement | Search labels, canonical keys, and groups; add changed-only filtering and counts without dropping hidden pending changes from the batch. |
| R10 | Usability improvement | Distinguish a successfully loaded empty policy collection from loading, unavailable, and filtered-empty results. |

Implementation under `console/src/routes/`: `settings-runtime.tsx`, `settings-runtime.model.ts`,
and `settings-runtime.i18n.ts`; existing revisioned command authority remains unchanged.
Existing focused evidence in that directory: `settings-runtime.test.ts`,
`settings-runtime.policy.test.ts`, `settings-runtime.ux.test.ts`, and
`settings-runtime.controller.test.ts`. Mocked-hook cases cover invalid-input batch blocking,
failed-save recovery, explicit conflict review, and mutation-free discard. Actual browser
validation messages, filtering, and layout acceptance is not claimed.

## Operator memory

All ten original items are usability improvements, not ten established source defects.
The table records source implementation and does not claim browser acceptance.

| ID | Classification | Implemented change |
|----|----------------|--------------------|
| M01 | Usability improvement | Show loaded entry/candidate counts and the existing 100-entry request bound without inventing a total, cursor, or completeness guarantee. |
| M02 | Usability improvement | Restore validated scope filters from the URL and preserve applied filters through reload/back/forward navigation. |
| M03 | Usability improvement | Clear both scope filters, their owned URL parameters, and the applied query with one explicit action. |
| M04 | Usability improvement | Keep pending filter inputs separate from the scope attributed to displayed results. |
| M05 | Usability improvement | Add GET-only refresh/retry for the applied scope and show the last successful fetch time without applying unsent inputs. |
| M06 | Usability improvement | Expose creation/expiry timestamps and explicit no-expiry wording while preserving the existing expiry-boundary logic. |
| M07 | Usability improvement | Expose replacement memory references with local copy actions and links only to replacement records already loaded. |
| M08 | Usability improvement | Show supplied compaction review reasons and distinguish unreviewed records from missing review explanations. |
| M09 | Usability improvement | Localize known scope/state labels and keep unrecognized states neutral and inspectable instead of inferring approval. |
| M10 | Usability improvement | Provide keyboard-operable record details with identifiers, full text, individual source references, and local copy actions; do not invent evidence routes or approval operations. |

Implementation under `console/src/routes/`: `operator-memory.tsx`, `operator-memory.model.ts`,
and `operator-memory.i18n.ts`.
Existing focused evidence in that directory: `operator-memory.model.test.ts` and the memory-label
cases in `settings-general.catalog.test.ts`. These cover URL/filter helpers, decoding,
provenance, expiry boundaries, and labels. Actual detail expansion, clipboard, refresh,
keyboard, and viewport acceptance is not claimed.

## Identity and access

The 12 original items comprise seven source defects, one conditional source defect, and four
usability improvements. Request approval, observed membership, and verified provider effect
remain separate.

| ID | Classification | Implemented change |
|----|----------------|--------------------|
| I01 | Conditional source defect | Use the same server-owned management authority for supplemental reads and rendering when authority and capability projections disagree. |
| I02 | Source defect | Settle roster and request reads independently so a slow resource does not hide the other management tab. |
| I03 | Source defect | Stop deriving current roles or identity activity from access requests; directory fallback shows only the verified current principal. |
| I04 | Source defect | Label approved requests as effect not verified, and never describe an approved revocation as an assigned role. |
| I05 | Usability improvement | Expose request rationale, identifiers, provider/subject, review time, and review justification through native details. |
| I06 | Usability improvement | Filter loaded requests by status and identity, with clear filters and explicitly loaded-only counts. |
| I07 | Usability improvement | Filter the displayed roster locally by name, email, subject ID, and principal type without issuing directory searches. |
| I08 | Source defect | Give the role-request reason a persistent label, linked character guidance, invalid state, and draft-opening focus. |
| I09 | Source defect | Clear the reason and request identity when changing targets/roles, and block retargeting during submission. |
| I10 | Source defect | Keep the active tab and loaded request window through bounded refresh, and report request/review acceptance separately from provider effect. |
| I11 | Source defect | Distinguish unavailable reads from empty lists, mark retained failed-refresh records stale/read-only, and retry only the failed resource. |
| I12 | Usability improvement | Collapse complete capability lists behind localized disclosures while retaining every canonical capability ID. |

Implementation under `console/src/routes/`: `settings-iam.tsx`, `settings-iam-users.tsx`,
`settings-iam-requests.tsx`, `settings-iam-capabilities.tsx`, and paired IAM catalogs.
Passing focused evidence in that directory includes `settings-iam.test.ts` and the IAM cases in
`settings-administration.model.test.ts` and `settings-administration.lifecycle.test.tsx`.
These cover authority selection, independent reads, reference facts, filters, draft isolation,
request details, unavailable recovery, and bounded loaded-window refresh. Mocked hooks and
virtual nodes do not establish browser focus, keyboard, layout, or viewport acceptance.

## Integrations

The 12 original items comprise eleven source defects and one usability improvement.
Read recovery does not repeat delivery tests or change stored configuration.

| ID | Classification | Implemented change |
|----|----------------|--------------------|
| N01 | Source defect | Add independent read-only refresh/retry for integration status and the email preview. |
| N02 | Source defect | Retain verified data and its last successful read time with explicit stale/error feedback after refresh failure. |
| N03 | Source defect | Use bounded loading skeletons for saved binding metadata and document OCR status. |
| N04 | Source defect | Distinguish failed binding observation from missing configuration and provide metadata retry/refresh. |
| N05 | Source defect | Restore last confirmed preferences after failure and require exact-version preference readback before claiming confirmation. |
| N06 | Source defect | Serialize preference commands and disable conflicting controls until save/readback completes. |
| N07 | Source defect | Include recipient mode/email on first binding save, distinguish drafts from confirmed recipients, and disable unsupported standalone saving. |
| N08 | Source defect | Explain and expose the minimum-one rule for selected delivery targets and saved channels instead of silently ignoring toggles. |
| N09 | Source defect | Report secret-free clipboard failures consistently and announce successful copying. |
| N10 | Usability improvement | Add HTML/plain-text email preview selection while preserving the synthetic-data label, iframe sandbox, and referrer policy. |
| N11 | Source defect | Update Teams approval onboarding from current authoritative props and ignore stale request completions. |
| N12 | Source defect | Stop OCR loading after failure, offer a read-only retry, and disable actions that rely on unavailable/stale state. |

Implementation under `console/src/routes/`: `settings-system.tsx`,
`settings-administration-read.ts`, `settings-teams-workflow.model.ts`,
`settings-teams-a1-onboarding.tsx`, `document-ocr-settings.tsx`, and paired integration catalogs.
Passing focused model/lifecycle cases cover read recovery, stale retention, preference rollback
and serialization, recipient payloads, selection limits, draft clipboard failure, both preview
modes, onboarding state changes, and OCR retry. Existing Teams, Slack, email, and system unit
tests also passed in the seven-file, 90-test administration run. The updated Teams/email
Playwright cases were not run by this worker; no live delivery or browser acceptance is claimed.

## Diagnostics

The 12 original items comprise six source defects and six usability improvements.
Process response, authenticated read access, configuration facts, and operational success
remain distinct.

| ID | Classification | Implemented change |
|----|----------------|--------------------|
| D01 | Source defect | Give policy facts an independent refresh and provide an explicit refresh-all action for the three reads. |
| D02 | Source defect | Complete liveness and KPI probes independently while rejecting superseded results. |
| D03 | Source defect | Keep errors beside their owning probe and exclude raw provider errors from diagnostic results. |
| D04 | Source defect | Add initial probe skeletons, scoped busy state, and meaningful progress/completion announcements. |
| D05 | Usability improvement | Record actual probe completion times and publish named observation records instead of treating rerender time as evidence time. |
| D06 | Usability improvement | Show monotonic elapsed read durations without inferring SLO or operational health from latency. |
| D07 | Source defect | Distinguish Durable/Not durable, Configured/Not configured, and Enabled/Disabled values instead of labeling every boolean enabled. |
| D08 | Usability improvement | Copy an allowlisted diagnostic summary without display identity, credentials, endpoint values, raw errors, or pending probes. |
| D09 | Usability improvement | Link diagnostic rows to IAM, integration prerequisites, and the owning overview without adding mutations. |
| D10 | Source defect | Explain the local development authorization ceiling separately from production server-verified principal/roles. |
| D11 | Usability improvement | Summarize only the two live probes as available, unavailable, or checking; configuration flags are not health-test counts. |
| D12 | Usability improvement | Add correctly named, independently guarded per-probe retries separate from refresh-all. |

Implementation under `console/src/routes/`: `settings-diagnostics.tsx`,
`settings-diagnostics.model.ts`, `settings-diagnostics.i18n.ts`,
`settings-administration-read.ts`, and paired diagnostic catalogs.
Passing `settings-system.test.ts` and administration model/lifecycle cases cover health-response
validation, independent observations, safe errors/exports, timestamps, elapsed time, semantic
values, pending counts, scoped retry, initial busy regions, and local identity guidance.
Virtual-node checks do not establish actual navigation, clipboard, assistive-technology,
keyboard, or responsive acceptance.

## Validation and review boundary

Final measured acceptance and the UI/UX rubric record are added after integration.
No quality score is assigned from source inspection alone.

## Related docs

| To learn about | Read |
|----------------|------|
| Settings behavior and authority | [Settings presentation](console-settings-presentation.md) |
| Review criteria and evidence | [UI/UX quality rubric](ui-ux-quality-rubric.md) |
