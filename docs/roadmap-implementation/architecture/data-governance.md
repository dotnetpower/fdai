# Data Governance and Privacy Evidence implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Purpose, retention, deletion, and legal-hold contracts | implemented | `shared/contracts/models/document.py`; `core/case_history/`; `core/trajectory/`; `delivery/persistence/postgres_user_context_retention.py`; focused retention tests | Multiple governed stores enforce bounded retention and legal-hold metadata. One deployment-wide schedule for every data class remains fork-owned. |
| Redaction and data-minimization controls | in-progress | `rule_catalog/pipeline/distill/sensitivity.py`; `core/browser_evidence/redaction.py`; ontology ACL and workflow argument redaction tests | Deterministic redaction exists on major document, browser, ontology, workflow, and channel paths. One shared decision-critical pre-model receipt is not yet enforced at every model and embedding boundary. |
| Append-only audit and privacy-bounded evidence | implemented | `core/audit/`; `delivery/persistence/postgres.py`; `core/operational_context/evidence_bundle.py`; focused audit and evidence tests | Hash-chained audit and redacted evidence projections exist. Deployment retention, anchoring cadence, WORM storage, and legal-hold operation remain environment evidence. |
| Production privacy assessment and compliance binding | not-started | `config/architecture-review.yaml`; [Production gate](../../roadmap/architecture/data-governance.md#production-gate) | Upstream defines required keys only. The approved assessment, owners, processor terms, regions, crosswalk, and operational evidence must be supplied by each deployment. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and separated reusable upstream controls from deployment-owned privacy approval. | `current change`; contracts, retention services, redaction paths, and audit evidence listed in the scope table. | Complete the shared pre-model evidence boundary and retain a deployment privacy gate receipt. |

### Remaining work

- [ ] Enforce one typed pre-model and pre-embedding minimization receipt across every capability, then prove unredactable input is held without transmission.
- [ ] Bind an approved deployment data inventory, owners, retention schedule, model-provider terms, privacy assessment, and compliance crosswalk to the production gate.
- [ ] Retain deletion, legal-hold, access-review, audit-anchoring, and incident-response receipts on one pinned deployment revision before claiming operational validation.
