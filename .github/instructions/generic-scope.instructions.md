---
description: Customer-agnostic scope and the fork-per-customer model.
applyTo: "**"
---

# Customer-Agnostic Scope

This repository is the **general-purpose, reusable** control plane. It must stay
customer-agnostic so it can be adopted by any tenant, team, or cloud provider (CSP).
**Customer-agnostic** means the code, config, docs, and history contain only generic,
synthetic, or placeholder values - never anything that identifies or belongs to a
specific customer environment.

This file is the single source of truth for scope; the repo root
[copilot-instructions.md](../copilot-instructions.md) and sibling guides
([coding-conventions.instructions.md](coding-conventions.instructions.md),
[language.instructions.md](language.instructions.md)) defer to it.

## Why

- The control plane is designed to be portable across teams, tenants, and clouds; embedded
  customer values break that portability (see [app-shape.instructions.md](app-shape.instructions.md)).
- Customer identifiers, secrets, or private data in a public/shared repo are a security and
  compliance incident, not just a style defect.
- A clean generic core keeps the rule catalog and audit format reusable
  (see [architecture.instructions.md](architecture.instructions.md)).

## Must Not Contain

No customer-specific information of any kind, in **any** artifact (source, config, docs,
tests, fixtures, sample data, commit messages, branch names, PR titles, or git history):

- customer, company, project, or team names
- cloud account identifiers: Azure tenant IDs, subscription IDs, resource IDs (non-Azure
  identifiers such as AWS account IDs or GCP project IDs are TBD; see
  [Implementation Focus](../copilot-instructions.md#implementation-focus-must))
- resource group, resource, cluster, storage account, or container-registry names
- endpoints, hostnames, IP addresses, resource URLs, connection strings, credentials, secrets,
  tokens, or SAS URLs
- private datasets, logs, traces, screenshots, diagrams, or recorded payloads captured from a
  customer environment
- embeddings, vector indexes, or model artifacts derived from customer data
- rules, thresholds, or policies written for a single customer's setup

## May Contain (Generic Substitutes)

To keep examples concrete without leaking anything, use synthetic placeholders:

- GUIDs: `00000000-0000-0000-0000-000000000000`
- hostnames/emails: `example.com`, `user@example.com`
- names: `acme`, `example-team`, `<customer-name>`, or clearly fictional values
- config keys and env-var names (the *schema*), never their populated customer values
- generic, portable rules that apply to any tenant

## Fork-Per-Customer Model

- Customer-specific customization lives in a **separate downstream fork**, never here.
- This repo is the **main project**; a fork customizes it by **dependency injection** - it
  registers its own implementations (provider adapters, rules/policies, secret/config providers,
  delivery adapters, risk thresholds, model providers) at the composition root and selects
  bindings via configuration. A fork MUST NOT patch `core/`. See the injectable seams in
  [project-structure.md](../../docs/roadmap/project-structure.md#customization-via-dependency-injection).
- **Fork walkthrough (procedural)**: the Day-1 checklist, the seam-by-seam recipes
  (LlmBindings, OperatorMemoryStore, HilRejectMaterializer + second-approval channel,
  WebSearchProvider, HilChannel, ScopeResolver, Critic + Judge, rule catalog, Rego
  overlays), the upstream sync procedure, and the hard don'ts all live in
  [downstream-fork-guide.md](../../docs/roadmap/downstream-fork-guide.md). Point every fork
  maintainer at that guide first; `project-structure.md` is the seam catalog it operationalizes.
- Keep everything in this repo parameterized and configuration-driven so a fork supplies its
  own values (env vars, secret store references, config files) **without changing core code**
  (see the safety rules in [coding-conventions.instructions.md](coding-conventions.instructions.md)).
- **Downstream sync**: forks pull generic improvements from this upstream repo (rebase/merge
  from upstream `main`); upstream never pulls from a fork.
- **Contribution back**: reusable, generalizable improvements flow upstream as PRs that are
  scrubbed of all customer values first; bespoke logic stays in the fork.

## Enforcement

Do not rely on human review alone. Gate every change:

- **Secret scanning** in CI (e.g., `gitleaks` or `trufflehog`) blocks known secret patterns.
- **GUID gate**: `scripts/check-guids.sh` blocks any GUID-shaped id (8-4-4-4-12 hex)
  outside the all-zero placeholder pattern (`00000000-0000-0000-0000-XXXXXXXXXXXX`).
  Runs in CI as the `guids` job. Rationale: Azure tenant, subscription, and
  resource ids all share this shape; blocking them at commit time is the only
  reliable way to keep the repo customer-agnostic.
- **Custom regex check** in CI for other repo-specific tokens (known resource-name
  prefixes, `*.azure.com`/cloud endpoints) is future work.
- **Pre-commit hook** running the same checks locally so violations never reach a push.
- Checks run on the **full diff and on new/changed fixtures**, and fail the build on match.

## Review Check

Author and reviewer are both responsible.

- If a diff introduces any customer-identifying value or one-off customer logic, treat it as a
  defect and **block the merge** - no exceptions.
- Fix by moving the value into configuration (env var / config file / secret-store reference)
  and moving the logic into the downstream customer fork.
- If customer data was already committed, it also exists in git history: rotate any exposed
  secret and rewrite history (e.g., `git filter-repo`) before considering it resolved.
