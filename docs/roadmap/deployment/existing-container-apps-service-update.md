---
title: Existing Container Apps Service Update
---
# Existing Container Apps Service Update

This document defines the exact-plan recovery path for one service in an existing development
Azure Container Apps installation. It keeps public image verification, private planning, human
approval, Managed Identity execution, rollback, and effect verification as separate stages.

> **Scope:** The implemented path updates only the existing `dev` Operator service. It does not
> restore GitHub Actions tenant deployment, migrate the runtime, or authorize `initial-cutover`.

## Design at a glance

Use an external coordinator for public source and OCI provenance checks. Use the eligible internal
deployment host only for private Terraform state, Azure Resource Manager readback, saved-plan apply,
and recovery. The path uses `manual_operator_update.py`; it never performs a raw Container Apps
image update.

```text
external coordinator: attest image -> retain content-bound receipt
internal host: recover inputs -> guard and save exact Terraform plan
active Azure human: approve exact review outside the host
internal host UAMI: claim -> apply saved plan -> verify or copy rollback revision
```

## Input recovery

The host reads the existing Operator Container App and the shared platform Terraform outputs.
`recover_operator_tfvars.py` reconstructs the current service input without reading a secret value:

- **Current service state:** Preserve workload identities, non-secret environment values, Key Vault
  references, probes, scale, tags, RBAC, callback settings, and rollback image.
- **Platform ownership:** Refresh the Container Apps environment, registry, Kafka, resource group,
  and Cost Governance pseudonym secret reference from the current platform state.
- **Peer isolation:** Omit the separately stateful channel edge from the recovered input and target
  only the main Operator Container App. Plan guards reject another resource change.
- **Fail-closed drift:** Stop when the live and platform bindings disagree, an identity is missing,
  a secret reference is malformed, or the current image is not digest-pinned.

## Exact plan and approval

Run `attest` on the external coordinator with provider-hosted GitHub authentication. Transfer only
the owner-only receipt and generic target manifest through the audited host access path. On the
internal host, `plan` verifies protected `origin/main`, logs in with the exact deployment
user-assigned Managed Identity (UAMI), initializes the existing platform and service backends, and
creates a 20-minute saved Terraform plan for one resource.

The active Azure human runs `approve` outside the execution host. Approval binds the Entra user
object ID, target, review digest, plan digest, and expiry. Apply requires a different deployment
UAMI principal and rejects changed source, target, plan bytes, plan projection, approval, or
rollback baseline.

### Platform prerequisite

When the existing platform state predates the Cost Governance pseudonym key,
`manual_operator_platform.py` prepares a separate saved plan in the same `fdai-dev.tfstate`
backend. Its focused Terraform root declares the canonical counted addresses for the 32-byte random ID,
Key Vault secret, and exact Operator `Key Vault Secrets User` assignment. All three resources use
the same definitions and addresses as the canonical platform root and pin the same AzureRM and
Random provider versions.

The platform guard admits exactly those three create actions and rejects drift, deferred changes,
updates, deletes, replacements, or another address. Apply writes a claim first, then independently
reads the exact secret reference and role assignment. This additive prerequisite is state-forward:
an uncertain apply remains claimed for authoritative verification and is never repeated or deleted
automatically. The Operator service plan starts only after the prerequisite receipt is complete.

## Apply and recovery

Apply writes an owner-only pre-effect claim before invoking `terraform apply` with the saved plan.
Success requires a new ready revision whose image equals the reviewed digest. Dispatch or Terraform
exit alone is not success.

If apply or readback fails, recovery copies the captured previous revision into a new revision and
requires the copied revision to become ready with the captured image. The claim remains evidence of
the attempted effect. An existing claim blocks another apply until authoritative recovery handles
the uncertain outcome.

## Operational closure

Source implementation is complete when focused coordinator tests, Ruff, design-route checks, and
documentation checks pass. Operational validation additionally requires the exact merged source,
reviewed platform prerequisite and service plans, deployed image and healthy revision readback,
unchanged peer evidence, service health, and an authenticated Console Dashboard check.

## Related docs

| To learn about | Read |
|----------------|------|
| Runtime selection and state ownership | [Runtime Deployment Profiles](runtime-deployment-profiles.md) |
| Private-host deployment rules | [Provisioning Execution Profiles](provisioning-execution-profiles.md) |
| Implementation progress | [Existing Container Apps service update implementation](../../roadmap-implementation/deployment/existing-container-apps-service-update.md) |
