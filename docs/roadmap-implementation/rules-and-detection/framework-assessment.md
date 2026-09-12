# WAF and CAF evidence-governed assessment implementation ledger

This delivery ledger tracks the shared shadow assessment boundary for WAF workload controls and CAF
estate guidance without duplicating the normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Shared catalog and evidence contracts | implemented | `framework_assessment.py`; generated WAF and CAF catalogs; focused schema tests | The content-addressed catalogs account for all 59 WAF controls, 186 WAF requirements, and all 15 CAF areas. |
| WAF 59-control assessment | implemented | `core/framework_assessment/`; Azure supporting-evidence adapter; focused runtime and adapter tests | Exact workload scope, inventory generation, evidence failure boundaries, approved N/A, tradeoffs, immutable replay, and no-authority output are enforced. |
| CAF 15-area assessment | implemented | `azure-caf.source.yaml`; `framework_assessment_cli.py`; focused catalog, runtime, provider, and live-runner tests | Strict deployment profiles cover all areas. Strategy, Plan, and Adopt require procedure plus execution evidence, while hierarchy evidence stays scope- and generation-bound. |
| Operator API and Console | implemented | `framework_assessment_projection.py`; `/caf-controls`; WAF detail extension; focused Operator and Console checks | The API and Console preserve separate reference, mapping, applicability, evaluation, and satisfaction states and reject authority-bearing or out-of-order events. |
| Review-only source changes | implemented | `framework_review.py`; `test_framework_review.py` | Proposed source generations remain pending until the exact review-package digest is approved; failed proposals retain the prior valid generation. |
| Governed live-Azure receipts | validated | Protected shadow run `34419989951`; sanitized framework assessment receipt | One required-CI-green source revision produced and retained a combined no-authority receipt. Independent review confirmed WAF reference and mapping coverage of 59/59, CAF reference coverage of 15/15, unknown satisfaction for every item, and `execution_authority: false`. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-12 | implemented | Kept the shared promotion-registry join limited to promotion-gate rows while reusing the Operator workflow adapters. | `current change`; focused Operator suites passed 119 tests with one optional PDF skip. | No WAF or CAF scope, evidence, satisfaction, replay, or authority behavior changed. |
| 2026-09-12 | implemented | Kept active-inventory provider type coverage isolated from WAF and CAF while extending the shared Operator PostgreSQL store. | `current change`; focused Operator inventory/workflow suites passed 83 tests. | No framework scope, evidence admission, satisfaction, replay, or authority behavior changed. |
| 2026-09-12 | implemented | Kept the Cost Governance disclosure-audit dependency inside its route family while sharing the existing Operator composition root. | `current change`; Operator composition and focused Cost Governance route checks. | No WAF or CAF evidence, topic, state, satisfaction, or authority behavior changed. |
| 2026-09-11 | implemented | Restricted the shared Operator source-state decoder to canonical machine-token reasons so principal text and provider details cannot enter WAF or CAF through that storage path. | `current change`; `postgres_family_store.py`; focused principal-text rejection check. | No framework-assessment behavior changed. |
| 2026-09-11 | implemented | Clarified that the shared Operator reader's generation-fenced runtime-call relationship decoder remains outside WAF and CAF evidence admission and results. | `current change`; `postgres_family_store.py`; focused mismatched-generation rejection check. | No framework-assessment behavior changed. |
| 2026-09-10 | validated | Retained and independently reviewed the governed live-Azure shadow receipt. The receipt covers all 59 WAF controls and all 15 CAF areas while keeping all satisfaction states unknown because decisive deployment evidence was not supplied. It grants no execution authority and makes no publication claim. | Protected run `34419989951`; source revision `d119212a02e3f334fd21a0f8e562e6da0927d841`; sanitized framework assessment receipt with `execution_authority: false` and `publication_status: not_requested_validation_only`. | No remaining work for issues #402 and #403. Any future enforcement proposal requires a separate design, representative cohort evidence, and independent approval. |
| 2026-09-10 | in-progress | Adopted one shared WAF/CAF assessment owner after critiquing duplicated WARA copies, browser-side evaluation, and framework compliance scoring. Earlier implementation provenance was not reconstructed. | `current change`; framework assessment design; issues #402 and #403. | Implement the catalog, runtime, provider, projection, Console, replay, and live validation slices. |
| 2026-09-10 | implemented | Added complete WAF and CAF catalogs, deterministic evidence admission, provider adapters, immutable replay, audit and event services, review-only updates, Operator projections, localized Console views, and the private-runner live validation workflow. | `current change`; 230 focused Python tests passed; 16 focused Console tests, TypeScript checks, production build, strict mypy, Ruff, deterministic regeneration, localization, roadmap, and design-route gates passed. | Push one exact required-CI-green revision, retain and review the two live shadow receipts, then run issue #404 plan-only validation. |
| 2026-09-10 | implemented | Rejected unknown decisive evidence targets instead of silently omitting them, restored the Operator composition fanout ceiling, and made sharded coverage defer its threshold to the combined 90% gate. | `current change`; framework core passed 43 tests at 93.01% branch coverage; focused CI-contract and Operator composition checks passed 85 tests. | Retain the governed live WAF and CAF receipts after required CI is green. |
| 2026-09-10 | implemented | Registered the new framework projection tests to the Operator service test owner after CI correctly rejected an unowned service test path. | `current change`; the service-suite manifest and runner contract tests passed. | Retain the governed live WAF and CAF receipts after required CI is green. |
| 2026-09-10 | implemented | Rebound the packaged System Knowledge catalog to a reachable post-rebase source revision so release evidence remains reproducible after integration. | `current change`; packaged catalog parity and ancestry check. | Retain the governed live WAF and CAF receipts after required CI is green. |
| 2026-09-10 | implemented | Removed the optional scheduled WARA Job as a live-validation scope prerequisite. Protected validation now selects exactly one topology-bound PostgreSQL workload and fails closed on zero, multiple, or invalid candidates. | Failed protected run `34402162140`; sanitized deployment query confirmed zero Container Apps Jobs; focused exporter and workflow tests. | Retain and review the governed live WAF and CAF receipts after required CI is green. |
| 2026-09-10 | implemented | Scoped realtime inventory invalidation to resources linked to the selected workload instead of blocking on unrelated subscription changes. New failed or abandoned full reconciliations remain global blockers. | Failed protected runs `34412977051` and `34418977608`; successful authoritative inventory refresh; focused persistence tests. | Retain and review the governed live WAF and CAF receipts after required CI is green. |

### Remaining work

- [x] Proved exact 59-control WAF and 15-area CAF catalog accounting with focused schema tests.
- [x] Proved missing, stale, conflicting, truncated, synthetic, wrong-scope, and unsupported evidence
  remains unknown in focused runtime tests.
- [x] Proved Strategy, Plan, and Adopt cannot pass without both procedure and execution evidence.
- [x] Proved external WAF reports and scores cannot establish satisfaction by themselves.
- [x] Proved immutable replay, tradeoff non-interference, event publication, and authority isolation.
- [x] Proved Operator API, Console, localization, and projection quarantine behavior.
- [x] Retained and independently reviewed governed live-Azure shadow evidence for WAF and CAF in
  protected run `34419989951`. The sanitized receipt covers 59/59 WAF controls and 15/15 CAF areas,
  preserves unknown satisfaction, grants no execution authority, and records validation-only
  publication status.
