---
title: Deploy Quickstart
description: Provision the FDAI minimum-set inventory on Azure - two equivalent paths (azd turnkey or Terraform direct), preview first, apply only when the plan looks right.
derives_from:
  - source: docs/roadmap/deployment/deploy-and-onboard.md
    sha: 99ebe4c7d8c121c6358b9b49b82867120564748a
---

# Deploy Quickstart

FDAI is provisioned from infrastructure-as-code under `infra/`, with Terraform as
the execution engine and source of truth. Two equivalent paths stand up the same
minimum-set Azure inventory: a turnkey `azd` wrapper, or Terraform directly.
Both preview before they apply, so an accidental provision is not possible.

## Before you start

- An **Azure subscription** you can create resources in, and the **Azure CLI**
  (`az`) - plus the **Azure Developer CLI** (`azd`) for the turnkey path.
- A completed
  [deployment preflight](../roadmap/deployment/deployment-preflight.md) - it
  collects quota, permission, connectivity, and rollback blockers before the
  control loop starts.
- Per-environment values in a `*.tfvars` file, which is **never committed**.

## Provision the minimum-set inventory

Preview first. Apply only when the plan matches what you expect. Pick whichever
path fits your workflow - they provision the same `infra/` Terraform.

<!-- fdai:tabs -->

#### azd (turnkey)

```bash
azd auth login
azd env new fdai-dev
# safe preview - runs `azd provision --preview`, applies nothing
scripts/azd-up.sh
# provision for real - second gate prevents an accidental apply
FDAI_AZD_CONFIRM=1 scripts/azd-up.sh
```

#### terraform (direct)

```bash
az login
terraform -chdir=infra init
# copy a template and fill in your values (tfvars are never committed)
cp infra/envs/dev.tfvars.example infra/envs/dev.tfvars
terraform -chdir=infra plan  -var-file=envs/dev.tfvars
terraform -chdir=infra apply -var-file=envs/dev.tfvars
```

<!-- /fdai:tabs -->

## After provisioning

<!-- fdai:steps -->

1. **Verify the inventory.** Confirm the resources provisioned and the executor
   identity has only its scoped, least-privilege permissions.
2. **Onboard one bounded scope.** Start with a single resource-group-equivalent
   scope and name its owner.
3. **Observe in shadow mode.** Let FDAI judge and audit without mutating, and
   review its would-be actions.
4. **Promote one action.** Turn on enforcement only for an action that clears its
   promotion gate, and leave the rest in shadow.

The [Get started](../get-started/) guide covers this first safe rollout in
depth, and [deploy and onboard](../roadmap/deployment/deploy-and-onboard.md) is
the full deployment reference.

## Related

<!-- fdai:cards -->

- [Preflight](../roadmap/deployment/deployment-preflight.md) - Resolve blockers before you provision.
- [Deploy and onboard](../roadmap/deployment/deploy-and-onboard.md) - The full deployment reference and Azure inventory.
- [Get started](../get-started/) - Orientation and your first safe rollout.
- [Operator console](../roadmap/interfaces/operator-console.md) - Run and query FDAI once it is live.
