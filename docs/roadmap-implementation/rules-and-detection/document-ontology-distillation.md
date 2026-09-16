# Document Ontology Distillation implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status (2026-08-03):** D0-D4 contracts, claim inventory, strict proposal
> compilation, deterministic gates, review packages, lifecycle plans, and frozen-corpus scoring are
> implemented. D4b adds the canonical `DocumentEnvelope` provenance bridge, structured Office and
> PDF locators, OCR fallback, and synthetic cross-format conformance. D4c adds real-document
> parsing, provider conformance, and annotated public-corpus evaluation. D4b results do not prove
> production extraction quality. D4d adds a tool-free T2 ontology model council with blind ballots,
> deterministic consensus, and bounded disagreement evidence. D5 promotion assessment remains
> evidence-only; no live-shadow evidence or automatic promotion is claimed.
> The 2026-09-16 evidence hardening binds production conformance to an exact partition profile,
> independently verified source and pricing receipts, and sealed revision-bound shadow batches.
> It does not manufacture elapsed live-shadow days, reviewed proposals, or external pricing.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Proposal, claim inventory, and deterministic gates | implemented | `services/core-control-plane/src/fdai/rule_catalog/pipeline/distill/ontology_claims.py`; `ontology_verify.py`; `ontology_review.py`; focused tests in `tests/rule_catalog/pipeline/distill/` | D0-D4 contracts and fail-closed review packaging are implemented. Structural inventory remains unclassified until model and governed evidence supply meaning. |
| Envelope provenance and format equivalence | implemented | `services/core-control-plane/src/fdai/rule_catalog/pipeline/distill/ontology_ingestion.py`; `ontology_evaluation.py`; `tests/rule_catalog/pipeline/distill/test_ontology_format_equivalence.py` | Structured locators and normalized proposal identities are covered with synthetic cross-format evidence. |
| Synthetic format and language corpus partitions | implemented | `golden_document_corpus.py`; `test_ontology_format_equivalence.py`; `test_ontology_conformance.py`; focused corpus checks (`47 passed`) | English native PDF, Office, and OCR plus Korean Office and OCR-backed scanned PDF preserve extraction equivalence. A deterministic bound provider passes `pdf:en`, `ooxml:en`, `pdf:ko`, `ooxml:ko`, and `ocr:ko` without granting production availability. |
| Isolated native-PDF parsing | implemented | `services/document-processing-worker/src/fdai_document_worker_service/adapters/pdf_isolation.py`; focused isolation and parser-parity checks | Production PDF text extraction runs in a spawned process with wall-time, CPU, address-space, page, and character ceilings. Failure returns `extraction_unsafe_package`; the parent worker remains available. |
| Real-corpus extraction conformance | in-progress | `services/core-control-plane/src/fdai/rule_catalog/pipeline/distill/ontology_conformance.py`; `ontology_conformance_models.py`; `ontology_corpus_gate.py`; `tests/rule_catalog/pipeline/distill/test_ontology_conformance.py` | Production availability requires the exact seven-partition profile, independently verified non-synthetic source receipts, current usage-bound pricing, and one self-consistent provider report. Real-provider PDF, Office, OCR, and Korean evidence remains open. |
| T2 ontology model council | implemented | `services/core-control-plane/src/fdai/rule_catalog/pipeline/distill/ontology_council.py`; `ontology_council_reducer.py`; `tests/rule_catalog/pipeline/distill/test_ontology_council.py` | Blind ballots, deterministic consensus, disagreement evidence, and bounded receipts are implemented without authority. |
| Shadow measurement and promotion assessment | in-progress | `services/core-control-plane/src/fdai/rule_catalog/pipeline/distill/ontology_evaluation.py`; `ontology_shadow_evidence.py`; `ontology_shadow_evidence_io.py`; [Evaluation and promotion](../../roadmap/rules-and-detection/document-ontology-distillation.md#evaluation-and-promotion) | Governed collection, content-addressed publication, restart loading, manifest verification, and sealed assessment bind the exact revision, release, model, policy, actors, receipts, corrections, and guard flags. The elapsed live-shadow duration and proposal volume are not present. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; current source, hardening record, and focused tests listed in the scope table. | Close the missing corpus partitions and retain governed shadow evidence. |
| 2026-08-21 | implemented | Removed lexical semantic and authority inference from structural claim inventory. Model-cited source ranges remain content-addressed and replayable, but claims stay unclassified and non-critical until model output and governed evidence classify them. Provider-observation verification now requires an explicitly classified claim plus a fresh external receipt. | `current change`; focused ontology format, verifier, semantic investigation, and public-corpus regressions passed within the 304-case slice; diff-scoped changed tests passed 3176 cases with 7 environment-gated skips. | Keep missing PDF, Office, OCR, and Korean provider partitions and live-shadow promotion evidence open. |
| 2026-08-27 | implemented | Added synthetic English and Korean Office, PDF, and OCR-backed corpus partitions and exercised them through extraction equivalence and the bound-provider conformance gate. Korean cases contain literal readable Hangul rather than a language label over English text. | `current change`; `golden_document_corpus.py`; format-equivalence, conformance, and corpus-gate checks (`47 passed`). | Retain real-provider public-corpus evidence separately; complete isolated PDF processing and the elapsed live-shadow gates below. |
| 2026-08-27 | implemented | Moved production native-PDF text extraction into a spawned child process with server-owned resource limits and typed fail-closed parent handling. Blank pages remain eligible for OCR and no parser process can mutate document lifecycle state. | `current change`; `pdf_isolation.py`; document worker parser parity and isolation checks. | Retain real-provider corpus and elapsed live-shadow evidence separately. |
| 2026-09-16 | in-progress | Hardened promotion evidence admission through 12 distinct critique rounds. Production availability now rejects reduced partitions, synthetic-only cases, cost-optional policies, stale or unverified pricing, provider/report splicing, and unverified source manifests. Shadow assessment uses independently verified, revision- and policy-bound sealed batches with append-only correction semantics. | `current change`; `ontology_conformance.py`; `ontology_conformance_models.py`; `ontology_corpus_gate.py`; `ontology_evaluation.py`; focused conformance, corpus-gate, and promotion regressions (`73 passed`); related Ruff, format, and strict mypy passed. | Accumulate 30 actual shadow days and 500 eligible reviews, and supply current externally verified model pricing. Until then, deployment availability remains unpassed. |
| 2026-09-16 | implemented | Added the governed live-shadow evidence accumulation path after the promotion-evidence gates. An injected deployment source now produces immutable content-addressed snapshots, a strict manifest authenticates source and review receipts, and restart reads fail closed on tampering, path, size, or identity drift. Ten adversarial collection rounds fixed one order-dependent retry defect. | `current change`; `ontology_shadow_evidence.py`; `ontology_shadow_evidence_io.py`; `test_ontology_shadow_evidence.py` (`6 passed`); related Ruff, format, and strict mypy passed. | Run the deployment-owned source over real reviewed proposals until the elapsed gate below is satisfied; source implementation does not substitute synthetic observations. |

### Remaining work

- [x] Add synthetic annotations for the required PDF, Office, OCR, and Korean partitions and pass
  the corpus gate with a deterministic bound provider (`47 passed`). This is implementation
  evidence, not production extraction validation.
- [x] Run untrusted native-PDF parsing in the document processing worker's spawned isolation
  boundary and retain fail-closed malformed and page-budget evidence.
- [x] Complete 12 promotion-evidence critique and hardening rounds with no confirmed
  Medium-or-higher source finding remaining; focused regressions passed 73 cases.
- [x] Implement governed live-shadow outcome collection, immutable content-addressed snapshots,
  strict manifest verification, and restart-safe loading; focused regressions passed 6 cases.
- [ ] Retain at least 30 distinct live-shadow days and 500 eligible reviewed proposals with zero guard violations before promotion review.
- [x] Keep deployment availability unpassed when current independently verified model pricing is
  absent; stale, fabricated, cost-optional, or context-mismatched evidence cannot pass the gate.
