# Structured cloud-document retrieval implementation ledger

This ledger records bounded software implementation and critique evidence for the
[structured retrieval design](../../roadmap/interfaces/cloud-resource-knowledge-structured-rag.md).
Issue #1019 / PR #1047 completed the original source delivery; Issue #1061 owns the retained-source
follow-up. Issue #995 continues to own independent operational qualification.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|---|---|---|---|
| Structured v3, extraction and deterministic excerpts | implemented | Structured contracts, parser and focused tests; rounds 1-16 below | Supported structures are bounded and reproducible; unsupported media/tables/relationships remain explicit holds, not silently accepted content. |
| Worker, package and retrieval integration | implemented | Final focused tests, v2/v3 composed chain and 10 loopback PostgreSQL cases | Actual stored-row mechanics are verified separately from synthetic reviewers, scanners and transport. |
| Bilingual query and evaluation boundaries | implemented | Query/evaluation tests and rounds 15-16: 72 semantic/gate and 207 frame/query cases passed | The CI-exposed recovery regression is repaired without raising budgets. Actual model quality and independent labels remain separate. |
| Ten-round critique and hardening | implemented | Sixteen separate rounds below, including two post-publication corrections | Bounded re-review found no further confirmed Medium-or-higher source defect; exact-head CI remains mandatory. |
| Real runtime trust, human review and live/air-gap qualification | not-started | Issue #995 | External prerequisites are not downgraded or replaced by test fixtures. |
| Retained-source extension and offline review tooling | implemented | [Review command](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/cloud_knowledge/review.py), [regressions](../../../services/document-ingestion-api/tests/test_cloud_knowledge_review.py), and follow-up evidence below | Explicit normalizer/reader compatibility, supported structures and bounded local review preserve every requested outcome. Source-quality and operating approval remain separate. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|---|---|---|---|---|
| 2026-09-15 | in-progress | PR #1068 exposed a test coupling, not a production fail-open: a controlled-clock publication test also required a real child to start within one second. CI correctly returned the earlier child-timeout hold. The test now injects an actually derived worker result before advancing its fake clock; separate real-child and timeout tests remain. | Exact head `1419765ba`, CI run `34956931240` attempt 1, completed regression job `104341216279`, step `Run regression shard`; its assertion reproduced deterministically with an injected cold-start timeout. Production source and deadlines are unchanged. | Verify the repaired focused tests, publish the new local commit and require its own exact-head CI/protected merge. Prior bounded no-finding statements apply to their checkpoints; Issue #995 remains separate. |
| 2026-09-15 | implemented | Reconciled the original protected delivery without rewriting its pre-merge history. | [PR #1047](https://github.com/dotnetpower/fdai/pull/1047), head `9006a9d57`, squash `672bc81d4`, exact-head CI `34946844303` and merged-main CI `34947425231` succeeded; [Issue #1019 closure](https://github.com/dotnetpower/fdai/issues/1019#issuecomment-5677313393). | Retained-source follow-up is Issue #1061; operational qualification remains Issue #995. |
| 2026-09-15 | implemented | Added opt-in normalizer `2.1.0` with reader `3.1.0`, complete supported disclosures/tabs/composites, exact-source checkpoint upgrades and bounded original-free offline review. | `current change`; [Issue #1061](https://github.com/dotnetpower/fdai/issues/1061), source/test paths and follow-up review below; 392 focused cases, eleven-source strict typing and seventeen-file Ruff/format passed. Actual local network-isolated retained-source preparation and independent file readback preserved the frozen denominator and original evidence. | Exact-head protected delivery remains pending. Private corpus holds, independent semantic labels, production rights/trust/reviewers and operational receipts are not completed by this source evidence. |
| 2026-09-15 | not-started | Recorded structured-release compatibility, source-clock, safe-chunk and bilingual evaluation decisions before implementation. | `current change`; design, critique and Issue #1019 | Implement and verify the bounded source scope; preserve external qualification boundaries. |
| 2026-09-15 | in-progress | Added original-free structured v3 contracts, bounded article/block extraction, explicit recipe/checkpoint identity, v3 package/CLI/staging/worker paths and accepted-model bilingual query binding. Added an offline paired-locale evaluation reducer with no operational authority. | `current change`; 660 focused cases across 18 explicitly selected contract, ingestion, worker, semantic and evaluation test files passed; strict source typing and task-owned lint/format passed. | Complete real-page hold classification, actual loopback database evidence, ten focused hardening rounds and protected delivery. Live evaluation and operational prerequisites remain external. |
| 2026-09-15 | implemented | Completed fourteen separately committed critique rounds, v3 producer/readback/approval parity and prompt-profile gating. Confirmed source-scope, context, size, freshness and retrieval defects were corrected without weakening failure holds. | Foundation `4044597c2`; rounds through `47fdd8659`. Final selected regression run: 872 passed across 25 files; final publisher-control change: 56 normalization cases passed. Separate real loopback database matrix: 10 passed. Task-owned Ruff/format checked 34 Python files and strict mypy checked 23 source files. Counts overlap and are not summed. | Protected publication/merge, approved source qualification, actual bilingual semantic quality, production identities/trust/reviewers and authorized operating receipts remain separate. |
| 2026-09-15 | in-progress | Integrated protected main `95d4f6eab`, preserving both shared-owner designs and the independent semantic test-context seam; regenerated conflicted knowledge data from its canonical builder. | Main CI [34943027781](https://github.com/dotnetpower/fdai/actions/runs/34943027781) succeeded. Post-integration selection: 885 passed across 26 explicit files; separate actual loopback PostgreSQL matrix: 10 passed. These replace affected pre-integration receipts rather than adding unique test counts. | Publish and verify this task's exact PR head, protected checks and merge. Source qualification and live operating evidence remain outside these local receipts. |
| 2026-09-15 | in-progress | PR #1047 attempt 1 exposed exact-locale validation flagged as lexical routing and a real recovery prompt-budget regression. The first is now expressed through closed typed validation with unchanged accepted values; no lexical intent router was found. | CI [34944978183](https://github.com/dotnetpower/fdai/actions/runs/34944978183), head `7cfd3e2d6`, regression jobs `104302209873` and `104302209839`; both assertions reproduced locally. Round 15: 72 focused semantic/query/gate tests passed after the locale repair. | Repair recovery-schema scope, re-review the final source snapshot and obtain fresh exact-head protected CI. Earlier no-finding statements apply only to their checkpoint. |
| 2026-09-15 | implemented | Repaired the frame-model schema boundary: accepted-judgment query state remains internally validated but is not requested again from a frame model. This removes the duplicate schema cost while preserving recovery budgets, query binding and legacy serialization. | `current change`; round 16's schema regression failed before the fix; 207 focused planning, recovery, query, judgment and test-context cases passed afterward. Ruff/format and strict typing passed for the affected source/test. | Fresh exact-head CI, protected merge and delivery reconciliation remain pending. No live model or source-quality evidence is inferred from mocked adapter requests. |

### Remaining work

- [x] Retain focused implementation and legacy-compatibility evidence for structured text, extraction and complete-generation chunking, as recorded above.
- [x] Retain admitted-worker/readback, retrieval-query and lifecycle regression evidence with actual local database results identified separately above.
- [x] Complete sixteen critique rounds and bounded re-review with no further confirmed in-scope Medium-or-higher defect after rounds 15-16. Unsupported-source qualification and operating prerequisites are not downgraded to satisfy this condition.
- [x] Complete the original protected source delivery: [PR #1047](https://github.com/dotnetpower/fdai/pull/1047), exact head `9006a9d57`, squash `672bc81d4`, CI `34946844303` and merged-main CI `34947425231` succeeded; [closure evidence](https://github.com/dotnetpower/fdai/issues/1019#issuecomment-5677313393).
- [x] Implement the versioned retained-source extension and bounded offline review; retain focused tests and actual local OS-isolated preparation/readback evidence as recorded below.
- [ ] Complete [Issue #1061](https://github.com/dotnetpower/fdai/issues/1061) through exact-head CI, protected merge and cleanup, linking its final source-delivery receipt.
- [ ] Resolve every declared pilot source hold and obtain independently reviewed paired-language query/claim receipts before claiming the corpus is RAG-ready. Implemented evaluation contracts and synthetic wording are not those receipts.
- [ ] Keep Issue #995 open until its actual trust, rights, reviewer, service and authorized runtime receipts are supplied.

## Critique and hardening rounds

Severity reflects the demonstrated defect, not missing external operating approval. Each numbered
round is a separate local checkpoint; false positives are retained rather than turned into fixes.

The bounded final review covers contract/identity, article/context, byte amplification, source-clock
updates, query/prompt scope, approval/index/rollback, persisted effects and evaluation evidence.
No production rollout, source-rights clearance, independent human review or live model quality is
claimed. These are required completion conditions for the operational parent, not Low findings.

| Round | Severity | Finding and disposition | Verification |
|---|---|---|---|
| 1 | Medium | Selecting inner content regions could omit an adjacent applicability paragraph. Unaccounted structural content now holds the candidate. | Added regression failed before the fix; the focused normalization module passes after it. |
| 2 | Medium | An old structured checkpoint masked a newer raw source when evaluating pending updates. Compare raw identity first and reject cross-source structure. | New changed-body regression failed before the fix; structured contract regressions pass afterward. |
| 3 | Medium | Global required context could reference a block with another unexpanded dependency. Reject nested global context, preserving the installed one-level closure. | New dependency-closure regression failed before the fix; structured tests pass afterward. |
| 4 | High | Repeated context had only per-excerpt bounds and could amplify a complete release excessively. Enforce aggregate expanded-byte and block ceilings before accepting the generation. | Reduced-ceiling reproduction failed before the fix; structured and legacy package regressions pass afterward. |
| 5 | Medium | Table rows lost applicability expressed as an ordinary preceding paragraph. Bind preceding paragraph/list context in the same heading ancestry with the existing context and byte ceilings. | Exact table-condition reproduction failed before the fix; normalization regressions pass afterward. |
| 6 | High | Retrieval compared only original hashes and accepted substituted normalized provenance. Recheck all immutable source evidence while allowing only the verified newer check overlay. | Altered-normalization reproduction failed before the fix; cloud reference and reader regressions pass afterward. |
| 7 | Medium | Generic per-document diversity limited a whole cloud collection to two excerpts. Retain the total eight-excerpt ceiling while treating a cloud version as a collection; ordinary-document diversity is unchanged. | Three-excerpt cloud reproduction failed before the fix; cloud and generic reader regressions pass afterward. |
| 8 | Medium | On-demand export could derive unpersisted structure while the durable checkpoint remained legacy, leaving the admitted generation permanently pending until another fetch. Add a leased processing-only sweep and require that checkpoint at export. | New no-network upgrade reproduction failed before the fix; collection/scheduler/intake regressions pass afterward. |
| 9 | Low | Critiqued whether v3 could bypass persisted activation/readback despite legacy coverage. No defect reproduced; expanded the exact legacy/structured matrix rather than inventing a fix. | 10 actual loopback PostgreSQL cases passed, including four v3 tamper/activation cases; isolated synthetic identities and test source remain non-production evidence. |
| 10 | Low | Critiqued v3 approval, audit, index and dated-answer composition. No authority escape reproduced. Extended the real-handler synthetic flow to structured input and both date renderings. | Two v2/v3 composed cases passed. The first new fixture correctly failed chronology and was corrected, not bypassed. This remains synthetic transport/scanner/reviewer evidence, distinct from round 9's database proof. |
| 11 | Medium | Final review found old shadow prompt packs explicitly request schema 1.1 while capability presence selected 1.2. Added a separately selected shadow document-query pack and require its exact replay layer before the schema upgrade. Historical prompt artifacts and active profile remain unchanged. | Prompt/schema identity and composed adapter regressions verify the gate and bilingual query flow without live model calls. |
| 12 | Medium | Re-review found the first omission guard covered paragraph tags but missed bare container text and headings. Replace the tag list with complete residual text accounting outside excluded chrome. | Two new heading/container variants failed before the fix; all normalization regressions pass afterward. |
| 13 | Low | Reviewed v3 producer staging and rollback parity. No defect reproduced; extended complete-scope, received-only, preserved processing identity and higher-sequence rollback regressions to v3. | 22 intake cases passed; an explicit retained-state fixture is not worker or human-approval evidence. |
| 14 | Medium | Retained-page remeasurement exposed missing publisher page-action, authorization-template and feedback roles, causing false omission holds. Classify these exact structural controls while preserving arbitrary-text and hidden-tab guards. | Synthetic reproduction failed before the fix; normalization regressions and separate retained-byte measurements verify the revised boundary without network calls. |
| 15 | Low | CI's lexical-routing detector classified an exact locale membership check as natural-language judgment. No language inference or authority escape was found. Use a closed typed locale validator rather than widening the baseline or changing the gate. | Exact baseline assertion reproduced red; 72 focused gate/judgment/query cases passed, including six additional invalid-locale cases and existing EN/KO checks. Recovery-budget failure remains tracked separately. |
| 16 | Medium | The frame-model schema advertised Core-only accepted retrieval terms and their nested definition, exceeding the existing compact recovery system budget. Exclude this field from generated model schemas while retaining internal validation, serialization and independent query binding. | Exact recovery assertion and explicit schema-boundary regression reproduced red; 207 focused cases passed afterward, including unchanged over-budget holds and forged-query replacement checks. No budget or authority gate was relaxed. |

## Retained-source follow-up evidence

The Issue #1061 feature batch was reviewed and hardened locally before publication. The checks
below are not additional claims about the sixteen historical commits, and overlapping test runs
are not summed. Confirmed defects have regressions; supported-source gaps are not all software bugs.

| Review area | Finding or decision | Evidence and disposition |
|---|---|---|
| Version identity | Preserve legacy bytes rather than silently improve old extraction | Explicit `2.1.0` plus reader `3.1.0`; old-reader rejection, unknown versions and signed round trips pass. |
| Source metadata | Same-body 200/304 reused stale title and rights (Medium) | Reproduced and repaired material metadata comparison; not-due upgrades retain source checks. |
| Source origin | A changed registered URL reused old collection/validator identity (Medium) | Exact-origin regression reproduced and repaired; collection clock and validators never cross origins. |
| Tab labels | A verified same-group control was rendered as a nested tab (Medium) | Exact label rendering repaired; cross-group, unlabelled and referenced-duplicate holds remain. |
| Required attributes | Newly supported elements and nested code missed retained conditions (Medium) | Dependency and descendant-condition regressions reproduced and repaired without dropping attributes. |
| Table vocabulary | Shared table inspection bypassed the selected inline normalizer (Medium) | Two top-level/nested `nobr` cases reproduced and repaired through versioned dispatch. |
| Disclosure integrity | Orphan summaries were accepted without a valid disclosure (Medium) | Orphan, late and duplicate-summary cases hold; only a unique first direct summary is supported. |
| Notice ownership | Explicit notices on new elements lost required-context ownership (Medium) | Two regressions reproduced and repaired; later excerpts retain the complete restriction. |
| JSON numbers | Numeric underflow became zero before validation (Medium) | Reproduced and rejected together with overflow, duplicate keys and depth violations. |
| Resource isolation | Excerpt expansion escaped the timed child and late results could succeed (Medium) | Both regressions reproduced and repaired; parsing and measurement share child budgets, and publication rechecks the deadline. |
| Report integrity | Held/unprocessed rows accepted excerpt measurements (Medium) | Contradictory outcomes now reject; lineage, hashes, complete denominator and absent-metric tests pass. |
| Files and lifecycle | No additional bypass reproduced in confined I/O, reader staging, rollback or governed worker checks (Low) | Links, special files, traversal, overwrite, budget limits, exact rollback documents and processing-digest mismatch are covered. |

Final local source validation: **392 passed** across thirteen explicitly selected cloud contract,
ingestion and worker files, including the real-handler synthetic governance chain. Strict mypy
passed for eleven changed source modules; Ruff lint/format passed for seventeen source/test files.
No new database, live source, model, signing trust, approval or activation was introduced.

Actual retained-source preparation and independent file readback also ran in fresh Linux user/network
namespaces with only loopback, empty IPv4/IPv6 routes and unreachable TCP/DNS-transport probes.
They bound exact source/dependency hashes and preserved legacy normalized hashes, blocks, holds,
all original evidence and the pre-existing original-free review package. Resolver lookup was not
performed. Private source scope, per-document outcomes and receipts remain outside source control;
this proves local preparation, not the internal package-to-answer production drill in Issue #995.

No further confirmed Medium-or-higher finding remained in this bounded source review. Unresolved
media, ambiguous source relationships, oversized required context, independent EN/KO claim labels,
production rights/trust/reviewers and the selected operating target remain separate completion conditions.

PR #1068's later test-only correction is recorded in history rather than hidden by that checkpoint.
All 34 offline-review cases passed with four workers after separating the fake publication clock
from real child startup. The production source, subprocess timeout, late-publication hold and
actual retained-corpus results were unchanged; exact-head delivery still needs its own CI result.
