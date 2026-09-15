# Cloud Resource Knowledge Lifecycle implementation ledger

This ledger tracks local implementation of the reviewed public-resource documentation lifecycle. The
[design owner](../../roadmap/interfaces/cloud-resource-knowledge-lifecycle.md) defines source dates,
periodic refresh, offline security review, admitted generations, and dated answers. The
[operator runbook](../../runbooks/cloud-resource-knowledge.md) separates software operation from
production prerequisites.

> **Snapshot:** [Issue #975](https://github.com/dotnetpower/fdai/issues/975) is complete for its
> software scope. [PR #976](https://github.com/dotnetpower/fdai/pull/976) merged reviewed head
> `109190429696d83790e3acafbf38fc38ff9600d4` as `c8b34034e4953c2ace27a7ace1c4baf6de417484` after
> [exact-head CI](https://github.com/dotnetpower/fdai/actions/runs/34846556314) succeeded.
> [Issue #995](https://github.com/dotnetpower/fdai/issues/995) tracks the blocked operational
> qualification. Source integration is complete; production and deployment are not.
> An `implemented` row describes only its bounded software slice and supplied focused evidence.
> No row claims production trust, live source enrollment, automatic prior-version restoration, or
> a successful operating-system-enforced air-gap rollout. Local containment and readback are not
> full Vidar restoration authority or production effect receipts.

> **Normalized-only follow-up:** The current change adds v2 package emission without original
> bodies, while preserving v1 reading and rollback lineage. This is a bounded source change, not
> operational qualification. The real collection pilot and remaining extraction-quality findings
> are recorded in [Issue #995](https://github.com/dotnetpower/fdai/issues/995#issuecomment-5667579564).

## Local evidence boundary

The separately scoped [structured RAG extension](cloud-resource-knowledge-structured-rag.md)
records v3 software, bilingual query contracts and fourteen critique rounds. It retains explicit
source-quality holds and does not close this ledger's operating prerequisites.

The original implementation session supplied the following final results. Later follow-up evidence
is recorded in its own history row; it is not added to this original owning batch.

| Run | Supplied result | Evidence boundary |
|-----|-----------------|-------------------|
| Final owning pytest batch | 560 passed, 1 skipped in 5.50s across 29 selected files | Includes the composed local flow and all six task-owned loopback PostgreSQL cases. The sole skip is the pre-existing search database fixture described below. |
| Final Python static checks | Ruff lint and format pass for all 63 task-owned Python files; strict mypy passes for all 45 task-owned source Python files | Task-owned scope only, not repository-wide validation. |
| Frontend after view extraction | 38 Vitest tests passed; both TypeScript configurations passed | [Cloud knowledge model](../../../console/src/routes/cloud-knowledge.model.test.ts), [knowledge sources](../../../console/src/routes/knowledge-sources.test.ts), and [document client](../../../console/src/ingestion-api.documents.test.ts); [application configuration](../../../console/tsconfig.json) and [test configuration](../../../console/tsconfig.tests.json). |
| Browser after view extraction and rollback control | 2 Playwright cases passed in 4.6s | [Browser cases](../../../console/tests/e2e/cloud-knowledge.spec.ts) use mocked API responses: exact inspected/imported bytes, review-only requests, one confirmed rollback submission that does not mark its candidate active, no overflow at 1440/993/390 widths, and unavailable-policy controls. No server or deployment authority is proved by these mocks. |
| Existing focused service migration inventory | 63 passed, 4 deselected; reused | [Migration inventory](../../../tests/integration/services/test_service_migration_inventory.py), part of the prior 99-test run. Ownership inputs are unchanged; this is not another current acceptance batch. |

The 29-file selection covers source/package/document-lifecycle contracts; API collection, scheduler,
intake, offline, search, preview, download, service behavior and composition; worker extraction,
activation, composed offline flow, parser parity, artifact/index lifecycle, adapter readiness and
protection reconciliation; Core cloud reference, governed reader/queries/knowledge evidence/RCA,
semantic cloud reference, governed-document planning/runtime and agent chain; and PostgreSQL integration.

The original batch's sole skip was [the pre-existing search fixture](../../../services/document-ingestion-api/tests/test_document_search.py):
neither `FDAI_VALIDATION_DATABASE_URL` nor `FDAI_DATABASE_URL` was selected. The separate task-owned
[loopback PostgreSQL file](../../../tests/integration/services/test_cloud_knowledge_postgres.py)
did run: six cases within the 560 passes cover leases, release high-water/replay, and activation
parametrized over clean rows, body tamper, provenance tamper, and changes after readback. They also
exercise unavailable pending/failed generations, lexical retrieval, and exact applicability filtering.

The prior 95-test semantic pass is subset evidence, not additional passes. The owning session reports
only a non-semantic long-f-string wrap after the final Python batch; result reuse applies. The
frontend and browser results above are current after view extraction and rollback-control work.

The [composed offline flow](../../../services/document-processing-worker/tests/test_cloud_knowledge_offline_flow.py)
uses real signed intake, pantheon events, Var self-approval rejection and independent-review logic,
worker/extraction, and the authorized Core reader and dated renderer. Its in-process memory stores,
stage claims, reviewer membership, scanner transport, search/access fixtures, and readback digest are
synthetic. Socket/DNS denial is a test guard, not OS air-gap enforcement. The separate PostgreSQL
cases prove database mechanics; combining their counts with the composed flow does not produce one
real deployed drill, service-role/broker receipt, live-source result, or production trust ceremony.
The CI repair supplies full lifecycle records in that search fixture and executes it against a
separate loopback database; orphaned, inactive, unavailable, or non-ready chunks remain excluded.
EN/KO rendering has [separate Core regression evidence](../../../services/core-control-plane/tests/core/knowledge/test_cloud_reference.py)
within the same batch; the composed flow currently asserts the English answer.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Lifecycle design and bounded v1 decisions | not-applicable | [Design owner](../../roadmap/interfaces/cloud-resource-knowledge-lifecycle.md) and [runbook](../../runbooks/cloud-resource-knowledge.md) | Reviewed design now has local implementation slices below; design agreement is not operational evidence. |
| K1: Source/release contracts and fake-clock freshness policy | implemented | [Source contracts](../../../packages/service-contracts/src/fdai_service_contracts/cloud_knowledge.py), [release contracts](../../../packages/service-contracts/src/fdai_service_contracts/cloud_knowledge_release.py), and [contract tests](../../../packages/service-contracts/tests/test_cloud_knowledge.py); final owning batch | Closed revision/check/release records separate source dates from package/import dates. Cases cover exact 7/30-day and 30/90-day thresholds, same-body/strong-304 binding, non-renewal, unknown time, and typed applicability. |
| K2: Bounded source collection and durable checkpoints | implemented | [Collector](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/cloud_knowledge/collector.py), [scheduler](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/cloud_knowledge/scheduler.py), [checkpoint store](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/cloud_knowledge/store.py), [collection](../../../services/document-ingestion-api/tests/test_cloud_knowledge_collection.py) and [scheduler tests](../../../services/document-ingestion-api/tests/test_cloud_knowledge_scheduler.py); final batch including PostgreSQL | Due selection, conditional/full fetch, unchanged reuse, bounded failures, append-only checks, and lease/revision fencing have local evidence. Changed content stays a candidate; failure or a withdrawal candidate does not silently delete the active source. |
| K2: Approved live-source enrollment | not-started | [Disabled Azure templates](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/cloud_knowledge/azure_templates.py) and [connected collection design](../../roadmap/interfaces/cloud-resource-knowledge-lifecycle.md#connected-collection) | APIM, VNet, NSG, and Private DNS templates are not source rights, an enrolled corpus, or measured coverage. |
| K3: Canonical signed JSON package and offline inspect/assemble | implemented | [Ed25519 codec](../../../packages/service-contracts/src/fdai_service_contracts/cloud_knowledge_package.py), [offline CLI](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/cloud_knowledge/__main__.py), and [package tests](../../../packages/service-contracts/tests/test_cloud_knowledge_package.py); final owning batch | Complete, data-only canonical JSON is capped at 16 MiB with purpose-bound signatures and independent trust. CLI inspection/assembly consumes a detached signature, never a private key, and grants no import, approval, or activation authority. General archives and embedding payloads are outside v1. |
| K3: Normalized-only v2 emission and legacy compatibility | implemented | [Text release contracts](../../../packages/service-contracts/src/fdai_service_contracts/cloud_knowledge_release.py), [v2 and legacy regressions](../../../packages/service-contracts/tests/test_cloud_knowledge_text_package.py), [intake](../../../services/document-ingestion-api/tests/test_cloud_knowledge_intake.py), [offline CLI](../../../services/document-ingestion-api/tests/test_cloud_knowledge_offline.py), and [worker extraction](../../../services/document-processing-worker/tests/test_cloud_knowledge_extraction.py) | New export, signing, assembly, collected staging and rollback exclude original bodies. Collector checkpoints remain unchanged; exact v1 signatures/digests stay readable. Receivers hash included normalized bytes, not absent originals. Current scope, rights, source dates, approval and activation gates remain required. |
| K3: Production trust, security inputs, and transfer authorization | not-started | [Runbook prerequisites](../../runbooks/cloud-resource-knowledge.md#prerequisites) and [offline trust ceremony](../../runbooks/offline-trust-ceremony.md) | Independent production roots/revocation evidence, legal rights, current internal scanner signature data, reviewer identities, and deployment configuration remain external prerequisites. A valid package signature is not internal approval. |
| K4: Governed admission, independent approval, and bounded extraction | implemented | [Worker](../../../services/document-processing-worker/src/fdai_document_worker_service/processing.py), [section extractor](../../../services/document-processing-worker/src/fdai_document_worker_service/adapters/cloud_knowledge.py), [agent-chain tests](../../../services/core-control-plane/tests/agents/test_document_ingestion_agent_chain.py), and [extraction tests](../../../services/document-processing-worker/tests/test_cloud_knowledge_extraction.py); final owning batch | Signed `cloud_reference` releases still require Huginn, Heimdall, Forseti, Saga, independent Var approval, and Muninn. Extraction holds a complete section plus context above 8 KiB rather than slicing table headers, exceptions, or footnotes. |
| K4: Fenced activation, independent readback, and crash containment | implemented | [Activation orchestration](../../../services/document-processing-worker/src/fdai_document_worker_service/cloud_activation.py), [read-only verifier](../../../services/document-processing-worker/src/fdai_document_worker_service/adapters/cloud_index_verification.py), [metadata transaction](../../../services/document-processing-worker/src/fdai_document_worker_service/adapters/postgres.py), [worker regressions](../../../services/document-processing-worker/tests/test_cloud_activation.py), and [PostgreSQL cases](../../../tests/integration/services/test_cloud_knowledge_postgres.py); final owning batch | A `KNOWLEDGE_ACTIVATION` effect journal precedes the first compare-and-swap (CAS): `READY`, `active=true`, `available=false`, chunks `verifying`. A separate `READ ONLY`, `REPEATABLE READ` connection compares every persisted row's exact text, null vector, provenance, and active metadata with sealed-source reread. The final CAS rechecks the observed digest before visibility and terminal `document.ready` audit. Readback failures contain the candidate as unavailable and append `document.failed`; revision conflicts cannot overwrite newer state. Crashed pending work resumes from the journal, never reauthorizing a prior version. |
| K4: Manual higher-sequence rollback request and control | implemented | [Rollback intake](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/cloud_knowledge/service.py), [intake tests](../../../services/document-ingestion-api/tests/test_cloud_knowledge_intake.py), [extracted Console control](../../../console/src/routes/cloud-knowledge.views.tsx), and [current browser cases](../../../console/tests/e2e/cloud-knowledge.spec.ts) | An Owner confirms a new review request for an eligible retained version. Higher sequence, original source dates/expiry, withdrawal/revocation gates, and independent Var approval remain required. One submitted request is neither active content nor a verified rollback effect. |
| K4: Automatic prior-version restoration | deferred | [Accepted v1 boundary](../../roadmap/interfaces/cloud-resource-knowledge-lifecycle.md#implemented-v1-boundary) and [recovery requirements](../../roadmap/interfaces/cloud-resource-knowledge-lifecycle.md#internal-review-and-activation) | Automatic unavailable-state containment is implemented; prior-generation reactivation needs separate Vidar-owned authority and evidence. Neither containment nor manual intake claims the full restoration workflow. |
| K5: Source dates and inspect-confirm-import UI | implemented | [Knowledge panel](../../../console/src/routes/cloud-knowledge.tsx), [extracted views](../../../console/src/routes/cloud-knowledge.views.tsx), and [model tests](../../../console/src/routes/cloud-knowledge.model.test.ts); current frontend/browser results | Bilingual source ranges, weakest freshness, outcomes, unavailable states, exact inspected-byte confirmation, and review-only requests survive view extraction. Import acknowledgement never grants activation or execution authority. |
| K5: Dated lexical retrieval and source-check rendering | implemented | [Governed reader](../../../services/core-control-plane/src/fdai/core/knowledge/governed_document_reader.py), [check overlay](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_cloud_knowledge_read.py), [date rendering](../../../services/core-control-plane/src/fdai/core/knowledge/cloud_reference.py), and [Core tests](../../../services/core-control-plane/tests/core/knowledge/test_cloud_reference.py); final owning batch | Per-source collection/check dates and freshness survive EN/KO rendering and redaction. Same-body checks preserve historical identity; pending updates do not renew old content. Unqualified documents are labeled dated reference, not current operational evidence. |
| K5: Model-judged exact targets through planning and SQL | implemented | [Typed target bridge](../../../services/core-control-plane/src/fdai/core/conversation/semantic_cloud_reference.py), [existing planner](../../../services/core-control-plane/src/fdai/core/conversation/semantic_governed_document_planning.py), [query function](../../../services/core-control-plane/src/fdai/core/ontology_platform/governed_document_queries.py), [SQL prefilter](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_governed_document_read.py), and [semantic tests](../../../services/core-control-plane/tests/conversation/test_semantic_cloud_reference.py); final batch including Core/PostgreSQL | Existing model-judged current-turn spans for provider, resource type, generation, SKU, API version, region, and deployment mode become canonical frame constraints, then plan arguments and SQL filters before ranking, with Core rechecks. No keyword routing or alias guesses. `cloud_as_of` requires fresh matching applicability; missing conditions hold operational guidance. `cloud_current` terminates with a new-observation requirement, without fetching. No live model was used for this evidence. |
| K6: Composed local control flow | implemented | [Signed-package-to-answer test](../../../services/document-processing-worker/tests/test_cloud_knowledge_offline_flow.py) and [EN/KO Core rendering tests](../../../services/core-control-plane/tests/core/knowledge/test_cloud_reference.py); included in 560 passes | Signed intake, actual pantheon review logic, worker/extractor, controlled readback, and the real authorized Core reader/dated renderer are composed locally. The synthetic and language-specific boundaries above apply; this is not a production acceptance drill. |
| K6: Authorized connected and OS-air-gap production drills | not-started | [Acceptance matrix](../../roadmap/interfaces/cloud-resource-knowledge-lifecycle.md#acceptance-matrix) and [runbook evidence requirements](../../runbooks/cloud-resource-knowledge.md#verification-and-evidence) | Actual trust, source rights/enrollment, scanner data, reviewers, mounted policies, service roles, broker delivery, independent operational effects, and bounded coverage/quality receipts remain external prerequisites and evidence. |
| Optional expansion beyond accepted v1 | deferred | [Accepted v1 boundary](../../roadmap/interfaces/cloud-resource-knowledge-lifecycle.md#implemented-v1-boundary) and [delivery plan](../../roadmap/interfaces/cloud-resource-knowledge-lifecycle.md#dependency-ordered-delivery-plan) | Non-Azure adapters, deltas, mirror-specific upstream proof, embeddings, broader applicability aliases, and automatic content activation need separate decisions and evidence. Mirror time is not upstream freshness; no model download or automatic activation fallback is introduced. |

Existing rule/table/function code-update constraints and fixed agent roles are unchanged. These
software slices introduce no new agent or managed-resource executor authority.

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-15 | implemented | Removed original bodies from new package emission with a separate normalized-only v2 record. Exact v1 reading, original-hash checking, signed canonical identity and retained rollback remain compatible; new rollback candidates are v2 with the old manifest digest and unchanged evidence. | `current change`; the 11-file focused selection passed 270 cases initially, then its single composed-flow assertion was updated for v2 and passed separately. Five-source strict mypy and task-owned Ruff passed. The retained four-source pilot was projected offline: review JSON decreased from 327648 to 49655 bytes (84.85%); text, evidence and dates were unchanged, with no new network call, signature, import or activation. | Retain exact protected delivery evidence. Original-body hashes at a v2 receiver are signed assertions, not rehashed bytes. Real-page extraction quality and the independent production prerequisites in Issue #995 remain open; no compression/delta or operational-readiness claim. |
| 2026-09-14 | not-started | Recorded the collection-date-aware knowledge lifecycle proposal, critique/revision, 7/30-day profiles, security-reviewed offline delivery, and K1-K6 sequence. | `current change`; bilingual design owner, roadmap navigation, design route, and this ledger. Scoped translation, quality, punctuation, readable-Hangul, roadmap tracking/size, route, and 313 local-link checks passed. No runtime implementation history or runtime test result is inferred. | Agree source/security policies and implement K1-K6 with their focused and composed evidence before claiming support. |
| 2026-09-14 | in-progress | Added local K1-K5 software slices: source/release contracts, bounded collection/checkpoints, signed JSON and offline CLI, the existing independent approval/index path, atomic visibility, manual rollback requests, and dated lexical/UI surfaces. This supersedes the proposal-only scope without changing its history. | `current change` (uncommitted); source/test paths in the scope table and the separate owning-session results above: 464 passed with 1 pre-existing database-environment skip, 38 frontend tests plus TypeScript check, 2 browser tests before rollback UI, and 3 actual loopback PostgreSQL tests after the fixture correction. These are not a final combined acceptance result. | Reconcile current applicability and rollback evidence; finish automatic Vidar recovery, independent effect verification, and typed natural-language planning. Establish external production prerequisites and retain K6 composed/live/air-gap receipts under separate authorization. |
| 2026-09-14 | implemented | Completed bounded K4 verified activation/containment and rollback controls, K5 exact typed planning/filtering and dated surfaces, and K6 composed local control flow. Complete-section extraction holds oversized context instead of slicing it. This supersedes the prior pending software evidence, not its history or external gaps. | `current change` (uncommitted); task-owned source/test paths above. Final 29-file pytest batch: 560 passed, 1 pre-existing search-database skip in 5.50s, including six real loopback PostgreSQL cases and the synthetic composed flow; prior 95 semantic passes are a subset. Ruff lint/format: all 63 Python files; strict mypy: all 45 source files. Frontend after extraction: 38 Vitest tests and both TypeScript configurations passed. Current rollback-inclusive Playwright: 2 passed in 4.6s. Existing migration inventory: 63 passed, 4 deselected, reused with unchanged inputs. The only later source edit is a non-semantic f-string wrap; evidence reuse applies. | Production rights/enrollment, trust/revocation, reviewers/scanner/policy mounting, release evidence, and authorized connected/OS-air-gap drills remain open. Synthetic control flow and separate database mechanics are not one deployed receipt. Automatic prior-version restoration and optional expansion remain deferred; no full Vidar restoration or live-model claim. |
| 2026-09-14 | implemented | Repaired PR #976 attempt-1 integration failures without relaxing evidence or secret controls: scalar applicability selectors replace a literal object input; service tests and the existing direct aiohttp import are registered; the search fixture now creates active lifecycle rows and excludes high-ranked inactive/unavailable/non-ready content; semantic coverage was regenerated. The exact public Python type-name scanner false positive has a value-only exception, with no path exemption. | `current change`; CI run `34839970865`, attempt 1, head `91fb575f2`; 114 focused repair tests passed in 56.96s, including the formerly skipped real PostgreSQL search and generated-source parity. Three-source strict mypy, seven-file Ruff, 33 focused frontend cases, and pinned gitleaks commit-range/control checks passed. | Publish the corrected local commit and retain its exact protected CI/merge result. Production prerequisites and deferred scope remain unchanged. |
| 2026-09-14 | implemented | Integrated attachment handoff `42dd0da64` without widening exact document context. The reader preserves upstream current-version and conversation authorization, intersects exact versions with cloud applicability before ranking, and holds if the combined capability is absent. | `current change`; 168 focused merged-path checks passed in 19.69s, including real PostgreSQL exact-version/generation rejection, source dates, original CI regressions, and generated-source parity. Five-source strict mypy, six-file Ruff, and both TypeScript configurations passed. | Publish this reviewed local integration and require exact-head protected CI/merge. No attachment or cloud execution authority changed. |
| 2026-09-14 | implemented | Reconciled final protected source delivery and linked operational follow-up without rewriting pre-merge history. The first failed CI attempt was repaired locally; the final head passed required checks and merged. | [Issue #975 final receipt](https://github.com/dotnetpower/fdai/issues/975#issuecomment-5664458094); [PR #976](https://github.com/dotnetpower/fdai/pull/976); head `109190429696d83790e3acafbf38fc38ff9600d4`, merge `c8b34034e4953c2ace27a7ace1c4baf6de417484`, CI `34846556314` attempt 1 success. Remote-main ancestry and identical reviewed/merged trees were verified. | [Issue #995](https://github.com/dotnetpower/fdai/issues/995) owns approved source/trust prerequisites and connected/restricted-network evidence. [Issue #994](https://github.com/dotnetpower/fdai/issues/994) separately tracks unfinished inline vision under #303; neither is closed by this delivery. |

### Remaining work

- [x] **Normalized-only package transport:** New v2 excludes original fields and bodies. Focused
  contract, CLI, intake, legacy rollback and worker tests above cover version matching, exact v1
  canonical identity, normalized tamper rejection and unchanged source evidence. This does not
  claim compressed/delta transport or repair the pilot's normalization/context limitations.
- [ ] **Real-page extraction quality:** Resolve or explicitly hold hidden UI, lost link/heading
  context and cross-section table caveats before operational use; retain regressions and real-source
  evidence for the findings in [Issue #995](https://github.com/dotnetpower/fdai/issues/995#issuecomment-5667579564).
- [x] **PR #976 repair evidence:** [CI `34846556314`](https://github.com/dotnetpower/fdai/actions/runs/34846556314)
  passed for final head `109190429696d83790e3acafbf38fc38ff9600d4`, and the protected merge is
  recorded above. Service ownership, direct `aiohttp` classification, semantic source coverage,
  scalar applicability and real-DB fixture corrections are included.
  The secret-scan exception matches only the public `Ed25519PrivateKey` identifier, with no file
  exemption; the pinned scanner still detects a synthetic secret-shaped control.
- [x] **Current local evidence:** Recorded the final owning Python, static, frontend, browser, and
  reusable migration results in [the evidence boundary](#local-evidence-boundary), including the
  exact pre-existing skip and six executed PostgreSQL cases. Both prior history rows remain unchanged;
  no SHA is invented.
- [x] **K4 activation and containment:** [Real worker orchestration tests](../../../services/document-processing-worker/tests/test_cloud_activation.py)
  cover guard revocation, stale scanner data, pending restart, terminal replay, missing verifier,
  and revision conflict. [PostgreSQL cases](../../../tests/integration/services/test_cloud_knowledge_postgres.py)
  separately prove exact persisted readback, body/provenance tamper rejection, post-readback-change
  fencing, and unavailable failures. These are local software results, not automatic restoration.
- [x] **K4 manual rollback control:** [Intake regressions](../../../services/document-ingestion-api/tests/test_cloud_knowledge_intake.py)
  and [current browser cases](../../../console/tests/e2e/cloud-knowledge.spec.ts) cover the higher-sequence,
  date-preserving review request and one-shot confirmation without claiming activation or approval.
- [x] **K5 planning and dated surfaces:** [Semantic tests](../../../services/core-control-plane/tests/conversation/test_semantic_cloud_reference.py),
  [Core date tests](../../../services/core-control-plane/tests/core/knowledge/test_cloud_reference.py),
  PostgreSQL applicability cases, and current frontend evidence support exact targets, held current
  guidance, EN/KO dates/redaction, and unavailable controls without keyword routing or live fetching.
- [x] **K6 composed local flow:** The [signed-package-to-answer regression](../../../services/document-processing-worker/tests/test_cloud_knowledge_offline_flow.py)
  passed within the final batch. It composes review, extraction, controlled readback, and authorized
  dated English rendering under socket/DNS denial; its synthetic boundary remains explicit above.
- [ ] **K1/K3 production prerequisites:** Retain approved source storage/transfer rights, registry
  and purpose-bound signing-root/revocation evidence, actual independent reviewers, current scanner
  signature data, and read-only service-owned policy mounts with protected parent directories per
  the [runbook](../../runbooks/cloud-resource-knowledge.md#prerequisites) and [Issue #995](https://github.com/dotnetpower/fdai/issues/995).
  Missing/expired inputs hold use; test keys, fabricated approvals, and package-supplied trust are not substitutes.
- [ ] **K2 enrollment:** Approve the bounded APIM/VNet/NSG/DNS inventory before enabling sources.
  Retain authorized [collection outcomes](../../roadmap/interfaces/cloud-resource-knowledge-lifecycle.md#connected-collection)
  for its declared coverage denominator, including due/restart behavior, changed/unchanged bodies,
  partial failures, and withdrawal candidates without inferred deletion; tracked by [Issue #995](https://github.com/dotnetpower/fdai/issues/995).
- [ ] **Deferred K4 restoration:** Before expanding beyond containment, approve separate
  [Vidar-owned restoration authority](../../roadmap/interfaces/cloud-resource-knowledge-lifecycle.md#internal-review-and-activation)
  and retain tested higher-sequence recovery, current trust/access/approval gates, no revoked-content
  resurrection, restart/duplicate convergence, two-phase audit, and independent restored-effect evidence.
- [ ] **K6 authorized operational drills:** Retain one connected-source campaign and one internally
  reviewed OS-egress-denied package-to-answer drill against the [acceptance matrix](../../roadmap/interfaces/cloud-resource-knowledge-lifecycle.md#acceptance-matrix) under [Issue #995](https://github.com/dotnetpower/fdai/issues/995).
  Use actual approved trust, rights, reviewers, scanner data, service identities/roles, broker, and
  mounted policies. Record bounded coverage/quality and failures, zero external DNS/HTTP/model calls
  for the restricted drill, stored-citation access, revocation/rollback cases, and independent effects.
  Neither the memory composition nor its separate PostgreSQL evidence closes this item.
- [ ] **Runtime release and deployment evidence:** Source integration and exact-head CI are complete
  above. Select an eligible immutable runtime release containing this implementation, then retain
  separately authorized deployment and operational receipts under [Issue #995](https://github.com/dotnetpower/fdai/issues/995).
  The r4 application-kit evidence reconciled in [PR #992](https://github.com/dotnetpower/fdai/pull/992)
  predates this implementation and cannot certify cloud-reference support.
- [ ] **Deferred expansion:** Keep non-Azure adapters, deltas, mirror-specific upstream proof,
  embeddings, broader applicability aliases, and automatic content activation outside the
  [accepted v1 claim](../../roadmap/interfaces/cloud-resource-knowledge-lifecycle.md#implemented-v1-boundary)
  until separate scope, rights, security, promotion, and acceptance evidence are approved.

## Related docs

| To learn about | Read |
|----------------|------|
| Source dates, refresh, admission, and answer requirements | [Design owner](../../roadmap/interfaces/cloud-resource-knowledge-lifecycle.md) |
| Configuration, inspection/import, and manual recovery procedure | [Operator runbook](../../runbooks/cloud-resource-knowledge.md) |
| Existing independent approval, audit, and indexing owners | [Document ingestion agent ownership](../../roadmap/interfaces/document-ingestion-agent-ownership.md) |
