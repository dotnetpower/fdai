# AIOpsPilot

Autonomous cloud operations control plane — an **AIOps** approach whose initial verticals
are **Resilience** (disaster recovery and chaos/resilience testing), **Change Safety** (safe
change and drift remediation), and **Cost Governance** (FinOps). The same architecture
applies to other AIOps domains (posture management, SRE/SLO, etc.), which are future scope.
Minimizes human intervention by resolving most events deterministically and using LLMs only
for the residual ambiguous cases.

## Documentation

- Contributor rules: [.github/copilot-instructions.md](.github/copilot-instructions.md)
- Detailed roadmap (structure → deployment): [docs/roadmap/README.md](docs/roadmap/README.md)

This repository is **generic and customer-agnostic**; per-customer customization lives in a
separate fork.