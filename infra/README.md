# `infra/`

Infrastructure as Code — Terraform.

Renders the four CSP-neutrality contracts (event bus / runtime / secret / workload
identity) into Azure resources. Entry command: `terraform apply` per
[docs/roadmap/deploy-and-onboard.md](../docs/roadmap/deploy-and-onboard.md).

Environment values (subscription id, tenant id, resource group, etc.) are supplied
at apply time via env vars / tfvars files that are **never committed** — the repo
stays customer-agnostic per
[generic-scope.instructions.md](../.github/instructions/generic-scope.instructions.md).
