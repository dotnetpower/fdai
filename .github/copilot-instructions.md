# FDAI - Copilot Instructions

Autonomous cloud operations control plane - an **AIOps** approach whose initial verticals
are **Resilience** (disaster recovery and chaos/resilience testing), **Change Safety** (safe
change and drift remediation), and **Cost Governance** (FinOps). The same architecture
applies to other AIOps domains (posture management, SRE/SLO, etc.), which are future scope.
Goal: minimize human intervention by resolving most events deterministically and using LLMs
only for the residual ambiguous cases.

This file is the small always-on contract. Detailed rules are loaded through
[`design-routes.json`](../scripts/lib/design-routes.json). Before an edit, read every
`must_read` document selected by all matching routes. The workspace hook blocks edits when
that context is missing or stale. A more specific instruction wins a conflict.

## Always-On Rules (MUST)

1. Read the route-selected design docs before editing. Update affected docs in the same PR.
2. Keep the repository customer-agnostic. Never commit secrets, tenant values, endpoints, or
   customer identifiers.
3. Resolve repeatable decisions deterministically. T2 output requires mixed-model,
   verifier, grounding, risk, and approval gates.
4. Every autonomous action needs a stop-condition, rollback, blast-radius limit, dry-run,
   per-resource lock, idempotency key, and audit record.
5. New capabilities start in shadow and use the authoritative promotion registry. Local,
   dev, production, and fork status never promote or demote a capability.
6. Human App Roles and the executor workload identity stay distinct. No self-approval.
7. Azure is the implemented target. Keep provider contracts neutral; non-Azure adapters are
   out of scope until explicitly approved.

## Issue Lifecycle (MUST)

- Every new issue includes explicit, observable **Exit criteria** as a checkbox list.
- After working on or reviewing an issue, add an English comment with evidence and residual work.
- When every exit criterion is satisfied, add the `completed` label. Keep the issue open while
  any residual work remains; close it only when no residual work remains.
- For another author's issue, add `review-needed` and wait for confirmation before closing. A
  reopened issue loses `completed` until its exit criteria are satisfied again.

English and Korean are both allowed in prose. Identifiers, paths, branches, punctuation, and
machine-record keys stay ASCII/English as defined by
[language.instructions.md](instructions/language.instructions.md). GitHub issues stay English.

## Routed Guides

- [architecture.instructions.md](instructions/architecture.instructions.md) - trust routing,
  control loop, action ontology, and safety invariants.
- [app-shape.instructions.md](instructions/app-shape.instructions.md) - topology, local/deployed
  parity, and console security boundaries.
- [coding-conventions.instructions.md](instructions/coding-conventions.instructions.md) - code,
  tests, docs-first/docs-after, and provider boundaries.
- [generic-scope.instructions.md](instructions/generic-scope.instructions.md) - generic upstream
  and downstream customization boundary.
- [agent-pantheon.instructions.md](instructions/agent-pantheon.instructions.md) - fixed agent roles.
- [documentation-style.instructions.md](instructions/documentation-style.instructions.md) and
  [language.instructions.md](instructions/language.instructions.md) - docs and localization.
- [ADR-0002](../docs/roadmap/architecture/decisions/0002-independent-runtime-axes.md) - independent
  runtime, environment, evidence, autonomy, identity, and fork axes.

## Verification

Run `scripts/verify.sh`; use `--full [<path>]` for pytest. Do not hand-edit generated runtime
artifacts (`resolved-models*.json`, Terraform state/plan, migrations, or `__pycache__`).
