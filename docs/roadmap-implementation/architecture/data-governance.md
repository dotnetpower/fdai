# Data Governance and Privacy Evidence implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Purpose, retention, deletion, and legal-hold contracts | implemented | `shared/contracts/models/document.py`; `core/case_history/`; `core/trajectory/`; `delivery/persistence/postgres_user_context_retention.py`; `infra/variables.tf`; focused retention tests | Multiple governed stores enforce bounded retention and legal-hold metadata. Azure case-history active, deletion-due, superseded-version, and change-feed defaults are 30 days; one approved deployment-wide schedule remains fork-owned. |
| Redaction and data-minimization controls | implemented | `rule_catalog/pipeline/distill/sensitivity.py`; `core/browser_evidence/redaction.py`; `delivery/azure/llm/model_trace.py`; `delivery/azure/llm/`; focused Azure model-boundary tests | Deterministic redaction now covers major document, browser, ontology, workflow, channel, model, and embedding boundaries. Production provider terms and privacy approval still bind at the deployment gate. |
| Append-only audit and privacy-bounded evidence | implemented | `core/audit/`; `delivery/persistence/postgres.py`; `core/operational_context/evidence_bundle.py`; focused audit and evidence tests | Hash-chained audit and redacted evidence projections exist. Deployment retention, anchoring cadence, WORM storage, and legal-hold operation remain environment evidence. |
| Production privacy assessment and compliance binding | not-started | `config/architecture-review.yaml`; [Production gate](../../roadmap/architecture/data-governance.md#production-gate) | Upstream defines required keys only. The approved assessment, owners, processor terms, regions, crosswalk, and operational evidence must be supplied by each deployment. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-16 | in-progress | Bounded the generic private-Blob change feed to each caller's version-retention schedule. Case history therefore uses 30 days while operational-history and decision-evidence metadata retain 90 days. | `current change`; `infra/modules/storage/case-history/main.tf`; focused case-history storage regression. | Publish the change, retain a protected plan and apply that converge the deployed change-feed policies, and independently verify expiry behavior. |
| 2026-09-16 | in-progress | Aligned the Azure case-history active, deletion-due, and superseded-version defaults at 30 days without changing operational-history or decision-evidence metadata retention. | `current change`; `infra/variables.tf`; focused case-history storage regression. | Publish the change, retain a protected plan and apply that converge the deployed case-history version policy from 90 to 30 days, and independently verify deletion behavior. |
| 2026-08-29 | in-progress | Added one typed pre-model and pre-embedding minimization receipt, enforced it across every direct Azure model and embedding boundary, and opened issue `#371` for the remaining deployment-owned privacy gate evidence. | `delivery/azure/llm/model_trace.py`; `delivery/azure/llm/`; `tests/delivery/azure/llm/test_model_trace.py`; `tests/delivery/azure/llm/test_adapters.py`; focused Azure LLM adapter tests; issue `#371` | Bind deployment-owned privacy approvals, retention evidence, and operational receipts at the production gate. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and separated reusable upstream controls from deployment-owned privacy approval. | `current change`; contracts, retention services, redaction paths, and audit evidence listed in the scope table. | Complete the shared pre-model evidence boundary and retain a deployment privacy gate receipt. |

### Remaining work

- [x] Enforce one typed pre-model and pre-embedding minimization receipt across every capability, then prove unredactable input is held without transmission.
- [ ] Bind an approved deployment data inventory, owners, retention schedule, model-provider terms, privacy assessment, and compliance crosswalk to the production gate. Tracked by issue `#371`.
- [ ] Retain deletion, legal-hold, access-review, audit-anchoring, and incident-response receipts on one pinned deployment revision before claiming operational validation. Tracked by issue `#371`.
