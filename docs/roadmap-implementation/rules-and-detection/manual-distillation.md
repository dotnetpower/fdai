# Manual Distillation implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Migrated legacy status | in-progress | Legacy status detail below | The prior owner did not use the structured ledger shape. |

#### Migrated legacy status detail

The ingestion and verification mechanism ships upstream; the LLM-backed and
customer-connector parts are fork seams with abstaining defaults.

| Design element | Shipped as | Home |
|---|---|---|
| Access seam | `ManualSource` + `DropDirectoryManualSource`, bound by `bind_drop_directory_manual_source` | `shared/providers/manual_source.py` |
| Sensitivity guard | `scan_sensitivity` - value-free findings, `HOLD` -> HIL | `rule_catalog/pipeline/distill/sensitivity.py` |
| Triage (deterministic) | `triage_filter`, `dedupe_exact`, `authority_score`, `prioritize` | `rule_catalog/pipeline/distill/triage.py` |
| Classifier seam | `ManualClassifier` (abstaining default marks all `UNCERTAIN` -> HIL) | `shared/providers/manual_classifier.py` |
| Freshness + deletion | `diff_snapshot`, `plan_retirements` (tombstone) | `rule_catalog/pipeline/distill/freshness.py` |
| Coverage diff | `analyze_coverage` | `rule_catalog/pipeline/distill/coverage.py` |
| Compile seam | `Distiller` (abstaining default extracts nothing) | `shared/providers/distiller.py` |
| Ontology claim inventory | `inventory_claims`, `reconcile_claims` | `rule_catalog/pipeline/distill/ontology_claims.py` |
| Envelope provenance and format equivalence | `manual_document_from_envelope`, normalized claim/proposal/graph digests | `rule_catalog/pipeline/distill/ontology_ingestion.py`, `ontology_evaluation.py` |
| Ontology proposal + verifier | strict compiler, authority/identity/evidence gates, review package | `rule_catalog/pipeline/distill/ontology_*.py` |
| Orchestrator + CLI | `build_distillation_plan`, `distill_cli` | `rule_catalog/pipeline/distill/orchestrator.py`, `distill_cli.py` |
| Source parser id | `manual-distill` source-manifest parser | `rule_catalog/schema/source_manifest.schema.json` |
| Container wiring | `distiller`, default `AbstainingDistiller` | `composition/` |
| Back-translation | Not implemented; tracked as backlog | - |

The deterministic stages run upstream with no fork work. The `ManualClassifier`
and `Distiller` seams stay abstaining upstream (no model shipped), so an unwired
deployment distills nothing rather than fabricating a rule; a fork wires
LLM-backed implementations and any siloed-source connector via the seam recipe in
[downstream-fork-seam-recipes.md § 5.16](../../roadmap/fork-and-sequencing/downstream-fork-seam-recipes.md#516-manual-distillation-manualsource--manualclassifier--distiller).

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-24 | in-progress | Migrated the legacy status into the delegated ledger without reconstructing earlier provenance. | `current change`; preserved owner status from `docs/roadmap/rules-and-detection/manual-distillation.md`. | Replace the legacy summary with bounded evidence-backed scope rows and observable exits. |

### Remaining work

- [ ] Replace the migrated legacy summary with bounded evidence-backed scope rows and observable
	remaining-work exits.
