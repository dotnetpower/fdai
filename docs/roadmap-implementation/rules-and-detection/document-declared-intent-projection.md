# Approved Document Intent Projection implementation ledger

This ledger separates the bounded private Core SDK path from full G02 upload and ordinary
product-query integration.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Closed default-validator wire compatibility | implemented | Canonical SDK event/approval/diff models, generator/`--check`, adversarial default-validator tests, and actual PostgreSQL/runtime bridge selection | Fixes the prior permissive test-bus gap without disabling validation. Standard bootstrap now supplies the same repository only when real PostgreSQL, current identity and Pantheon prerequisites are present. |
| Private governed-envelope approval and projection | implemented | Current change; `runtime/document_intent.py`, owned handler, PostgreSQL adapters and Core migration; `test_document_intent_postgres.py` | Explicit typed JSON BusinessService add/update only. Exact Var approval, Saga audit, atomic CAS, independent readback and recovery are connected without common observation writes. |
| Current source-aware private graph read | implemented | `postgres_document_intent_reader.py`; actual service-role PostgreSQL tests | Current directory role and source ACL are checked before/after reads. No Owner bypass or retained-result fallback. |
| Standard worker-to-Core ingress | implemented | Current change; worker-owned envelope migration/consumer, existing content-free ready/deleted events, Core ingress and normal bootstrap/task supervision; actual PostgreSQL flow | Ordinary prose is unchanged. Exact typed envelopes are retained privately and re-read only after ready; mismatched facts dead-letter without proposals. Deletion removes private bytes and drives source-owned rollback. |
| Protected review UI | not-started | #2256 G02; #2268 | Exact diff is available through the authenticated runtime contract but has no ordinary Console review surface. |
| Common graph/query manifest and cache join | not-started | [Owning boundary](../../roadmap/rules-and-detection/document-declared-intent-projection.md#current-authorized-queries-and-remaining-integration) | Private rows never enter common graph or ordinary answers. Full G02 remains open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-11-01 | implemented | Hardened `document_intent_ingress.py`, `postgres_document_intent.py`, and `postgres_document_intent_reader.py` (`G044`, `G046`, `G047`) to accept tuple purpose sequences, reject boolean target revisions, and require non-empty purpose strings before computing scope digests. | `current change`; focused document-intent and conversation suites passed. | Protected UI and common graph/cache exposure remain open below. |
| 2026-10-31 | implemented | Wired Pantheon bootstrap kinetic-proposal source and recent-activity state projection in `bootstrap_pantheon.py` (#2741) while leaving document-intent ingress and review authority unchanged. | `current change`; #2741; `bootstrap_pantheon.py`, `agent_activity.py`; focused delivery and Pantheon tests passed. | Protected UI and common graph/cache exposure remain open below. |
| 2026-10-20 | implemented | Connected normal worker completion to Core without putting source bodies on the bus. Added worker-owned immutable envelope storage, a restricted Core read function, ready-fact revalidation, deterministic add/update revision selection, normal Pantheon binding and supervised at-least-once consumption. Worker cleanup and purge verification include the private envelope; deletion facts trigger independent readback and rollback. | Current change; final non-database bootstrap/worker/deletion/wire/wheel selection passed 125 tests and final migration/actual PostgreSQL selection passed 109. The standard add -> exact review -> approval -> private read -> same-document update -> delete/rollback flow and mismatched ready-fact rejection run on loopback PostgreSQL 5433. The two new ingress/worker modules separately pass 36 cases with 96.12% branch-inclusive coverage; ten changed sources pass strict mypy. Earlier counts overlap and are not added. | Protected UI and common/cached ordinary-query exposure remain separate. Authenticated Console, approved real corpus, deployment and elapsed qualification are not inferred. |
| 2026-10-20 | implemented | Repaired fresh-database migration order after exact CI attempt `39293023442`: the worker no longer assumes the Core role exists, and a Core-owned follow-up grants only the restricted function after its role baseline. | Current change; exact legacy round-trip reproducer passed; both inventory certification migration cases passed against the disposable loopback administrator with encoded credentials; service migration inventory passed 74 cases. No credential value was logged or retained. | Protected merge and target deployment evidence remain separate. |
| 2026-10-19 | implemented | Corrected default-validator incompatibility using canonical SDK contracts, generated closed schemas and actual default-on PostgreSQL and PantheonRuntime bridge tests. Extra fields, execution authority, owner/topic/state/revision and approval splices are rejected. | Current correction; 111 focused tests passed, including 15 actual PostgreSQL cases and the real default runtime factory/bridge; schema generation/check, Ruff and strict four-source typing passed. | Normal bootstrap does not provide this binding; upload/UI, common graph/cache, generated-catalog delivery reconciliation and live qualification remain open. |
| 2026-10-19 | implemented | Added the private intent namespace, exact-diff authorization, owned pub/sub, atomic source/approval/release/revision checks, immutable event outbox, independent readback and Vidar rollback. | Current change; actual PostgreSQL flow and framework layout: 28 passed; strict mypy: six new source files passed. Provider and directory inputs are synthetic, not operational qualification. | Final scoped criticism/static/translation checks and local checkpoint; upload/UI, generic query/cache join, and operational qualification remain separate. |

### Remaining work

- [ ] Add protected exact-diff review UI without disclosing source properties on general topics.
- [ ] Adjudicate common graph/query-manifest exposure and current source-aware cached-result
  admission before private rows can enter ordinary conversation or Console results.
- [ ] Retain target-specific deployment and operational evidence separately; local tests do not
  establish live corpus, model/provider effects, elapsed observation, or promotion.

### Final integration critique

| Round | Hypothesis | Result |
|-------|------------|--------|
| 1 | Publishing an envelope on `object.event` could disclose source content. | Rejected by design: the existing ready event remains content-free; Core re-reads one exact private row through a restricted function. |
| 2 | Worker staging could grant graph authority. | The worker can only insert/select its envelope table. It cannot read or mutate the Core intent namespace. |
| 3 | A ready event could make an indexing approval act as graph approval. | Core only opens a proposal; Var's distinct current exact-diff approval and Saga seal still gate materialization. |
| 4 | The pre-ready worker callback could race current source checks. | Staging happens before readiness, but Core consumption begins only from the committed `document.ready` outbox fact and then rechecks the current row. |
| 5 | Ordinary prose could accidentally become intent. | Non-JSON, multiple-unit and other-kind documents are no-ops; the exact kind uses a closed properties model. |
| 6 | Re-delivery could change staged content. | Same bytes are idempotent; a changed envelope for the same document/version is rejected. |
| 7 | A forged ready fact could rebind digest, identity or state. | Document/version/key/hash and ready/index/retention/protection state are compared before proposal; mismatch dead-letters. |
| 8 | A restart could lose the proposal. | The durable worker envelope and lifecycle outbox replay the same content-bound proposal; downstream transition/outbox identity already suppresses duplicates. |
| 9 | Automatic updates could overwrite another source owner. | Operation/revision is derived from the current private target, and the existing atomic apply still requires the same document owner and exact revision. |
| 10 | Core bootstrap could silently use a synthetic identity. | Binding requires the existing current Entra-backed handover identity reader and real PostgreSQL ontology store; missing prerequisites leave ingress absent. |
| 11 | Optional ingress failure could stop unrelated raw event processing. | It has its own consumer group and content-free dead-letter outcome; no direct agent call or shared mutable workflow state is introduced. |
| 12 | Local success could be described as deployment qualification. | The design, ledger and issue evidence keep authenticated UI, real corpus, deployment and elapsed evidence explicitly open. |
