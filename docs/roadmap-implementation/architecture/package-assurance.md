# Package Assurance implementation ledger

This delivery ledger tracks the machine policy, focused gates, and bounded runtime tooling that
implement the package assurance design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Assurance-level policy | implemented | `config/package-assurance.json`; `check-package-assurance.py`; focused policy tests | Five levels separate internal, lockstep, independent-contract, effect-bearing, and knowledge-evidence obligations without weakening constitutional controls. |
| Dependency owner binding | implemented | Root and distribution manifests; package assurance checker | Root test mirrors name one owner and reason, and their version ranges cannot drift from that owner. |
| Compatibility scope | implemented | `fdai-service-contracts` compatibility manifest; package assurance policy and checker | N/N-1 remains mandatory for the independently released cross-process SDK and is not inferred from a filesystem package boundary. |
| Signed deployment profiles | implemented | `deployment-root.json` builder and verifier; offline-kit signer and acquisition path; focused profile tests | New offline kits bind offline membership to the exact legacy manifest digest. Connected source uses protected source and image manifests, while appliances add container provenance around the offline closure. Legacy kits remain accepted. No artifact publication or Azure deployment is claimed. |
| Linked lifecycle evidence | implemented | Package assurance policy and checker; capability lifecycle owner | Separate exact-artifact receipts can compose one complete lifecycle while conflicting or missing links stay incomplete. Operational receipts under #355 remain open. |
| Multi-target review envelope | implemented | `record_cost_governance_review_batch.py`; protected review workflow; focused batch and workflow tests | One bounded envelope decomposes into existing independent target records with stable child request ids and zero approval, execution, or promotion authority. |
| Capability-scoped optional readiness | implemented | Package assurance policy and checker; existing optional package readiness tests | A disabled unavailable package does not block unrelated complete paths. Enabled missing requirements still fail closed. |
| Stable extension facades | implemented | Package assurance policy; existing Code Assurance and Cost Governance public facades; independent-service checks | Authority-neutral exports are supported while Core-to-optional-package imports remain blocked. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-26 | implemented | Added tiered package assurance, source-bound root test mirrors, profile-bound signed roots, linked lifecycle evidence, bounded multi-target review envelopes, optional readiness, and facade rules. | `current change`; package assurance checker and focused policy, deployment-root, review batch, workflow, architecture, documentation, and localization checks. | Retain separately authorized operational lifecycle evidence under #355 and Cost Governance campaign/review evidence under #903/#904. No Azure deployment, artifact publication, activation, or promotion is part of this change. |

### Remaining work

- [ ] Retain the separately authorized operational receipts tracked by #355, #903, and #904.
  Source implementation and local focused checks do not replace those live evidence requirements.
