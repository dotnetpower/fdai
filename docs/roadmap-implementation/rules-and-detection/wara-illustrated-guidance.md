# Illustrated WARA guidance implementation ledger

This ledger separates implemented public instructional content from visual validation and
operational assessment evidence.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Source-bound shared guidance contract | implemented | `packages/service-contracts/src/fdai_service_contracts/wara_guidance.py`; shared/corpus/API/export/guard cohort: 161 passed | Strict inert localized text, original graph and exact public-origin contracts; 15 bounded digest-verified shards and APRL MIT notice ship in the independent shared wheel. |
| Complete lifecycle corpus | implemented | `scripts/catalog/build_wara_guidance.py --check`; `rule-catalog/guidance/azure-wara/coverage.json`; corpus regressions | All 456 identities, 393 active and 63 historical, use 45 reviewed mechanism families and explicit per-GUID bindings. Three pilots and 16 qualified cases are separately authored; 437 retain source prose with shared context, not independent latest-document or live validation. |
| Detail read and Console renderer | implemented | Operator WARA detail; Console guidance contracts; 38 focused Console unit tests, TypeScript and production build | Detail-only attachment binds source identity and content digest while lists remain bounded. Detail revision combines catalog and guide identity; examples never change actual assessment state. |
| Presentation benchmark and responsive evidence | implemented | `console/tests/e2e/wara-guidance.spec.ts`: final desktop corpus sweep 1 passed; subsequent pilot/error/keyboard/print/long-detail checks 4 passed; #2677 | All 456 English desktop entries and 45 families passed with zero overflow, clipped text or node intrusion; maximum figure 793.1 px within 842 px. Three pilots additionally passed English/Korean at 1440, 993 and 390 widths. Evidence is isolated fixtures, not authenticated live assessment. |
| Public vector presentation export | implemented | `core/wara/guidance_report.py`; `delivery/wara_guidance_presentation.py`; `scripts/catalog/export_wara_guidance.py`; export regressions | Native vector nodes/connectors, complete source text and citations, readable Korean-aware pagination and historical warnings remain separate from private assessment exports. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-30 | in-progress | Established illustrated guidance scope, strict shared presentation contract and three semantic benchmark cases after privately inspecting the reference presentation. | `current change`; #2677; owning bilingual design. | Complete and verify corpus, source/API/renderer regressions and desktop-before-responsive evidence before publication. |
| 2026-10-30 | implemented | Completed the corpus and corrected the benchmark twice: moved architecture above long rationale without shrinking text, then replaced repeated case paragraphs with 102 concise entity-specific node explanations in 16 qualified diagrams. Preserved long prose outside the primary diagram, fixed current source conflicts and a detail-cache revision gap, and retained exact public-reference hygiene. | `current change`; 161 focused Python checks; 38 Console checks, TypeScript and build; final 456-entry desktop sweep and four subsequent browser checks passed. Corpus `sha256:9a90c5a3dab8d6ed4d7e4b386985795bbb7c7e2688aaa8fa2a970d7016f0eb7b`; #2677 retains delivery evidence. | Live installation evidence, assistive-technology certification and independent latest-document review of all 437 shared-context entries are not claimed. |

### Remaining work

- [x] Recorded passing strict contracts, 456-entry source/corpus, API, Console and public-ID guard
  regressions; generator `--check` and independent shared-wheel asset checks passed.
- [x] Compared the benchmark with the explanation/diagram/action hierarchy, fixed both observed
  shortfalls and retained passing final desktop, constrained and mobile fixture evidence.
- [x] Completed this bounded public-guidance implementation; #2677 owns exact-head CI and protected
  delivery tracking. No customer assets, live Azure validation, deployment or execution is implied.
