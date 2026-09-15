# Runtime Deployment Profile Implementation

This ledger tracks the implementation evidence for new-install runtime selection between Azure
Container Apps and Azure Kubernetes Service (AKS). The canonical design remains in
[Runtime Deployment Profiles](../../roadmap/deployment/runtime-deployment-profiles.md).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| AKS security scan remediation | implemented | `infra/runtimes/aks`; two cluster contract tests, two DSN rotation tests, three native workload plan tests; Checkov 3.2.256 reports 54 passed, 0 failed, and 8 resource-local exceptions. | Azure Policy, host encryption, 50-pod node limits, read-only service roots, bounded scratch storage, and explicit image pulls are configured. Scanner limitations, Managed OS disks, and coordinated DSN rotation have narrow documented exceptions. Azure operational evidence remains open. |
| Runtime profile and CLI grammar | implemented | `packages/deployment-cli/src/fdai_deployment_cli/runtime_profile.py`; `packages/deployment-cli/tests/test_runtime_profile.py`; 36 focused coordinator tests pass in the current change. | Container Apps with PostgreSQL Flexible Server remains the default. AKS node floors and the non-production `postgres-aks` combination are validated before deployment. |
| AKS network and cluster state | implemented | `infra/modules/network`; `infra/runtimes/aks/cluster`; `terraform validate` passes in the current change. | The private Standard-tier cluster uses separate system and autoscaled user pools, Microsoft Entra RBAC, Cilium, workload identity, managed Key Vault CSI, and a separate backend key. |
| AKS workload state | implemented | `infra/runtimes/aks/workloads`; `terraform validate` passes in the current change. | Typed Deployments, Services, ServiceAccounts, federated credentials, HPA, PDB, NetworkPolicy, four default CronJobs, and CSI secret synchronization share one workload state. |
| Compact in-cluster PostgreSQL | implemented | `infra/runtimes/aks/database`; `terraform validate` passes in the current change. | The non-production profile uses one pgvector StatefulSet, one Premium SSD claim, a private load balancer, generated credentials and TLS material, and a Key Vault DSN with `sslmode=require`. It does not claim HA, backup, or point-in-time recovery. |
| Managed-host stage routing | implemented | `standalone_application.py`; `standalone_host.py`; 36 focused coordinator tests pass in the current change. | Shared substrate, AKS cluster, optional database, migrations, workloads, and second plans use distinct exact-plan approvals and recovery receipts. |
| Signed online and offline kit inputs | implemented | `build-standalone-deployment-kit.sh`; `stage-offline-kit.sh`; `mirror-locked-providers.sh`; `test_extract_kubelogin_archive.py`; six extractor tests pass in the current change. | The exact-file-set kit includes the three AKS roots, provider locks, pgvector OCI archive, `kubectl`, and `kubelogin`. A complete kit build remains to be recorded. |
| Capacity and regional feasibility | in-progress | Structural node floors exist in `runtime_profile.py` and AKS Terraform checks. | SKU quota, zone availability, and workload-envelope calculations are not yet part of preflight. |
| Operational readiness | in-progress | Local source, test, and Terraform validation evidence only. | No live new-subscription online or artifact-offline AKS receipt exists yet. The path is not classified as production validated. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-14 | implemented | Remediated PR #1000's AKS security scan failure by enabling policy admission and host encryption, increasing node Pod limits, and hardening service filesystem and image-pull settings. Documented resource-local scanner and deployment constraints without a global baseline. | Failed CI `34863327772`, attempt 1, source `6850f3d2d2e51aedc011e7a113910f1d1d9db4d2`; current change; four Python contract cases and three Terraform workload plan cases pass; Checkov 3.2.256 reports zero failures across the three AKS roots. | Complete required CI for the updated PR and retain the separate deployment, host-encryption eligibility, capacity, rotation, and recovery evidence below. |
| 2026-09-15 | in-progress | Added the first implementation ledger. Earlier provenance was not reconstructed. Implemented sealed runtime selection, separate AKS cluster/database/workload states, managed-host routing, typed Kubernetes resources, compact pgvector placement, and signed kit inputs. | Current change paths listed in the scope table; 36 focused coordinator tests, six archive extraction tests, and Terraform validation for the shared, cluster, database, and workload roots pass. | Record complete kit-build evidence, deploy both AKS database profiles online and artifact-offline, close ingress and rollback evidence, and add capacity preflight. |
| 2026-09-15 | implemented | Kept assignment and HIL import grouping inside the existing Operator Service package and runtime. The IAM facade re-exports original adapter and factory objects without wrappers or changes to either renderer. | `current change`; [Operator composition](../../../services/operator-service/src/fdai_operator_service/composition.py); [identity regression](../../../services/operator-service/tests/test_operator_service_full_composition.py); the main implementation session reported 98 Operator composition/full-composition passes, 1 unchanged optional PDF-extra skip, and 39 distinct composition imports. No checks were run for this documentation edit. | Topology, workload identity, readiness, and exact-plan deployment approvals are unchanged. Existing operational criteria below remain open; composition checks do not certify either renderer or a live deployment. |

### Remaining work

- [ ] Build one complete signed kit and verify that its manifest contains the AKS roots, all three
  provider families, pgvector OCI archive, `kubectl`, and `kubelogin`.
- [ ] Record a successful new-subscription online deployment receipt for AKS with
  `postgres-flex`, including all second-plan and rollout checks.
- [ ] Record a successful new-subscription online deployment receipt for AKS with
  `postgres-aks`, including migration, pgvector extension, persistent-volume, and restart checks.
- [ ] Run both AKS profiles from an artifact-offline kit and record that no provider, image, or
  executable is downloaded after verification.
- [ ] Add subscription quota, regional SKU, availability-zone, and allocatable workload-envelope
  checks, including host-encryption eligibility, that block an infeasible profile before Terraform planning.
- [ ] Demonstrate coordinated `postgres-aks` credential rotation and workload rollout without
  relying on independent DSN expiration or claiming continuity from CSI synchronization alone.
- [ ] Add TLS-terminated operator ingress and prove Console-to-Operator authentication without
  exposing a plaintext public endpoint.
- [ ] Add exact schedule inputs and parity tests for optional Container Apps jobs before enabling
  their AKS CronJob counterparts.
- [ ] Demonstrate failed-rollout recovery to the prior healthy workload without repeating an
  ambiguous Terraform apply.
- [ ] Add immutable backup and point-in-time restore for `postgres-aks`, then record a restore
  drill before considering any production database profile.
