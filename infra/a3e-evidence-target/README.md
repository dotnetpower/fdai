# A3-E evidence target

This Terraform root prepares one isolated development VM for governed standing-authorization
(A3-E) and cross-path safeguard evidence. It creates a private target, separate executor and
observer identities, and minimum-permission role assignments without granting promotion or effect
authority.

> **Scope:** This root is an infrastructure prerequisite for issues `#632` and `#633`. A local
> preview is not an approved deployment plan, a runtime cohort, or operational evidence.

## Resources

The root references an existing protected holding resource group and creates only these disposable
children:

- one Virtual Network and one `/27` subnet with no public IP;
- one Network Security Group that denies Internet ingress and egress;
- one Trusted Launch Linux VM with an exact image version;
- one executor Managed Identity with only VM read, start, and deallocate actions;
- one observer Managed Identity with VM-scoped Reader access.

Every resource receives expiry, ownership, required-state, and no-authority tags. The required
post-provision state is `deallocated`, but reaching that state is a separate governed effect. The
Terraform apply does not implicitly authorize or perform the deallocation.

## Plan boundary

Supply deployment values through protected environment or owner-only variable files. Do not commit
subscription ids, principal ids, resource names, endpoints, or SSH key material.

Before an exact plan can be retained:

1. Confirm the region, VM SKU restrictions, family and regional quota, exact image version, and
   non-overlapping `/24` address space.
2. Bind the authenticated Terraform principal, existing holding resource group, expiry, and SSH
   public key through protected inputs.
3. Initialize an approved remote backend and run `terraform validate` before generating the plan.
4. Render the binary plan with `terraform show -json`, then run
   `scripts/deployment/azure/verify_a3e_evidence_plan.py` on the owner-only JSON file. The verifier
   requires the exact reviewed create set and rejects update, replace, delete, missing, duplicate,
   or unrelated addresses without printing plan values.
5. Retain the exact source revision, plan digest, actor binding, expiry, stop conditions, rollback,
   and cleanup plan for independent approval.

Do not run `terraform apply` from a local preview. Apply, initial deallocation, VM start,
compensation, cleanup, registry mutation, and promotion each remain separately approved operations.

## Local validation

Use provider-free initialization for source validation:

```bash
terraform -chdir=infra/a3e-evidence-target init -backend=false -input=false
terraform -chdir=infra/a3e-evidence-target fmt -check
terraform -chdir=infra/a3e-evidence-target validate
```

The focused repository contract is:

```bash
uv run pytest -q --no-cov tests/integration/infra/test_a3e_evidence_target.py
```

## Related docs

| To learn about | Read |
|----------------|------|
| Standing authorization | [Escalation and Standing Authority](../../docs/roadmap/decisioning/escalation-and-standing-authority.md) |
| Security evidence status | [Security and Identity implementation ledger](../../docs/roadmap-implementation/architecture/security-and-identity.md) |
| Deployment approval | [Deploy and Onboard](../../docs/roadmap/deployment/deploy-and-onboard.md) |
