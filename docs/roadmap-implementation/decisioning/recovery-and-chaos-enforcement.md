# Recovery and Chaos Enforcement implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Impact analysis and envelope compilation | implemented | [`impact_analysis`](../../../services/core-control-plane/src/fdai/core/impact_analysis), [`test_impact_analysis.py`](../../../services/core-control-plane/tests/core/impact_analysis/test_impact_analysis.py) | Bounded traversal, feature calculation, incomplete-evidence refusal, and impact caps have focused coverage. |
| Recovery-plan contracts and state transitions | implemented | [`test_recovery_plan.py`](../../../services/core-control-plane/tests/core/verticals/test_recovery_plan.py), [Ontology contract](../../roadmap/decisioning/recovery-and-chaos-enforcement.md#ontology-contract) | Versioned plans and recovery transitions exist; this does not prove a live recovery outcome. |
| Continuous guard and independent verification | implemented | [`test_impact_analysis.py`](../../../services/core-control-plane/tests/core/impact_analysis/test_impact_analysis.py), [Runtime state machine](../../roadmap/decisioning/recovery-and-chaos-enforcement.md#runtime-state-machine) | Guard and verification mechanics fail closed on stale, incomplete, or over-envelope evidence. |
| Disposable reference scenario substrate | implemented | `infra/scenario-lab/`; `.github/workflows/sre-demo-lab.yml`; `tools/dev-access/scripts/`; focused scenario-lab and dev-access contracts; Terraform, Trivy, and Checkov validation | The private AKS, VM, MySQL, Azure OpenAI, and evidence target use tagged child resources in an existing protected holding resource group and one disposable state. An opt-in direct P2S path adds peering, gateway transit, private DNS, and minimum operator RBAC without enabling public access. No live plan, apply, fault injection, or destroy receipt exists for this source. |
| S1-S14 governed chaos campaign and executor binding | in-progress | [`constitution-traceability.json`](../../../config/constitution-traceability.json), [Delivery status](../../roadmap/decisioning/recovery-and-chaos-enforcement.md#delivery-status) | Scenario taxonomy exists, but constitutional domain coverage remains incomplete and no governed live executor campaign is retained. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-24 | implemented | Corrected the disposable deployment boundary after live preflight found that the private runner could not create resource groups, the original VNet CIDR overlapped an existing network, a non-scenario Key Vault prevented complete prompt cleanup, raw workflow logs were not a safe evidence surface, and VM readiness was not verified. The root now uses a protected holding group, a non-overlapping CIDR, no persistent secret store, temporary scoped authority, runner-local raw logs, repository-safe outcome projection, strict ten-scenario verification, and cloud-init readiness. | `current change`; scenario-lab Terraform validation; scenario and lifecycle contracts `8 passed`; workflow and CI contracts `47 passed`; focused planner behavior `524 passed` | Run the exact-revision protected plan, apply, VPN verification, approved sweep, independent result review, and destroy; retain the protected run and repository-safe summary references. |
| 2026-08-24 | implemented | Added opt-in workstation testing through the existing P2S VPN and hardened the disposable target with Key Vault purge protection, secret expiry, MySQL TLS, and subnet and NIC NSGs. Scanner exceptions are limited to MySQL cross-resource false positives and documented lab tradeoffs. | `current change`; scenario-lab and dev-access contracts `13 passed`; Terraform format and validation; Ruff and ShellCheck; scenario-scoped Trivy and Checkov `0 findings` | Run the exact-revision protected plan, regenerate the VPN profile, verify workstation route and DNS, then retain apply, fault, recovery, cleanup, and destroy evidence. |
| 2026-08-24 | implemented | Added an expiry-tagged scenario-lab Terraform root and protected plan, apply, approved-sweep, and destroy workflow. It remains separate from scenario promotion and the governed executor contract. | `current change`; scenario-lab Terraform, runner scripts, workflow, focused contracts `5 passed`, Terraform format and validation, ShellCheck, Ruff, and CI contracts | Run a protected plan from an exact committed revision, then retain apply, readiness, approved fault, independent recovery, cleanup, and destroy evidence. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and separated tested mechanics from operational enforcement evidence. | `current change`; current source, focused tests, and constitutional traceability listed in the scope table. | Bind the governed executor and complete the frozen recovery and chaos campaign. |

### Remaining work

- [ ] Bind an injected `GovernedChaosExecutor` through deployment composition and prove startup
  refuses enforcement when the binding or required authority is absent.
- [ ] Apply and destroy the disposable reference substrate through the protected workflow, then
  retain exact-revision readiness, approved fault, independent recovery, and cleanup receipts.
- [ ] Execute the frozen S1-S14 campaign with approved impact envelopes, continuous stop guards,
  independent recovery verification, and retained replayable receipts.
- [ ] Close the missing constitutional scenario dimensions for recovery and Chaos Engineering before
  claiming domain validation or enforce readiness.
