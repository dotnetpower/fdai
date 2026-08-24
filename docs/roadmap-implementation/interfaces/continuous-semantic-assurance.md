# Continuous Semantic Assurance implementation ledger

This delivery ledger tracks the bounded implementation and evidence needed to run semantic
assurance continuously without coupling a fixed corpus count to an unrelated roadmap package.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Exact-source corpus derivation | implemented | `eval/golden-dataset/`; `build_golden_dataset.py`; question-universe and golden-dataset checks | The current source derives 35 logical expectations across 8 wording styles and 2 locales. The manifest-derived count, not 560, is the contract. |
| Typed full-corpus oracle | implemented | `golden_question_dataset.py`; `golden_question_certification.py`; `golden-semantic-campaign*.ts`; focused checks | Acceptance reads typed frames, capabilities, paths, evidence, limitations, dispositions, pressure, and authority. It does not compare answer prose. |
| Strict and seeded release gates | validated | [Ontology Query Randomized Assurance](../../roadmap/interfaces/ontology-query-randomized-assurance.md); governed 2026-08-20 baseline | Strict v2 passed 22/22 and seeded assurance passed 100/100 for its exact certified source. Later revisions require new evidence. |
| Full current corpus certification | in-progress | [Continuous Question Space](../../roadmap/interfaces/continuous-question-space.md); authenticated no-T2 runner and readiness gate | The current full corpus has not retained one uninterrupted exact-source passing artifact. Partial and suffix runs remain diagnostic only. |
| Change-focused selection | in-progress | Question identity, novelty, adequacy, metamorphic, and release-assurance contracts | Deterministic identities and coverage dimensions exist. A source-diff-to-case selection receipt is not yet the shared entry point for every semantic change. |
| Scheduled delta and periodic full assurance | in-progress | Question schedule, workload-principal receipt, due gate, campaign ledger, and shared one-shot runner | Fail-closed scheduling foundations exist. Server-owned workload scope mapping, deployed shadow scheduling, and reviewed cost and cadence evidence remain open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-24 | in-progress | Established continuous semantic assurance as the owner of full-corpus, change-focused, release, and scheduled validation. Removed the direct 70-case campaign from OI-11 completion and retained OI-11's focused action-draft classification boundary. | `current change`; bilingual owner, roadmap links, exact structured corpus counts, and existing typed assurance contracts. | Bind deterministic changed-case selection, retain one uninterrupted full current-corpus artifact, and complete workload-principal scheduled shadow evidence. |

### Remaining work

- [ ] Emit one source-bound corpus manifest whose derived denominator includes every current locale,
  wording style, evidence posture, generated declaration case, and focused regression overlay.
- [ ] Bind semantic source changes to a deterministic affected-case selection receipt and require the
  strict bilingual gate plus every selected case before accepting the focused change.
- [ ] Retain one uninterrupted full-corpus certification for the exact integrated source with no
  pressure signal, typed oracle failure, capability substitution, unsupported operational claim,
  or authority violation.
- [ ] Complete the server-owned workload Reader mapping and retain scheduled delta-first shadow
  evidence before enabling a recurring cadence.
- [ ] Define the reviewed periodic full-run cadence from measured duration, provider pressure,
  token use, and cost. Do not encode a permanent question count or unconditional polling loop.
