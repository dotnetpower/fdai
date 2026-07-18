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
  [project-structure.md](../../docs/roadmap/architecture/project-structure.md#customization-via-dependency-injection).
- **Fork walkthrough (procedural)**: the Day-1 checklist, the seam-by-seam recipes
  (LlmBindings, OperatorMemoryStore, HilRejectMaterializer + second-approval channel,
  WebSearchProvider, HilChannel, ScopeResolver, Critic + Judge, rule catalog, Rego
  overlays), the upstream sync procedure, and the hard don'ts all live in
  [downstream-fork-guide.md](../../docs/roadmap/fork-and-sequencing/downstream-fork-guide.md). Point every fork
  maintainer at that guide first; `project-structure.md` is the seam catalog it operationalizes.
- Keep everything in this repo parameterized and configuration-driven so a fork supplies its
  own values (env vars, secret store references, config files) **without changing core code**
  (see the safety rules in [coding-conventions.instructions.md](coding-conventions.instructions.md)).
- **Downstream sync**: forks pull generic improvements from this upstream repo (rebase/merge
  from upstream `main`); upstream never pulls from a fork.
- **Contribution back**: reusable, generalizable improvements flow upstream as PRs that are
  scrubbed of all customer values first; bespoke logic stays in the fork.

## Editable vs Locked (agent-facing boundary)

An agent working **in a fork** MUST know, before it edits anything, whether a path
is fork-owned or upstream-locked. The single machine-readable source of truth for the
locked set is [scripts/lib/framework-surface.txt](../../scripts/lib/framework-surface.txt)
(consumed by both `check-protected-paths.sh` and the signed integrity manifest). The
rule of thumb: **if a path is listed there, it is LOCKED; otherwise it is editable.**

**LOCKED - a fork MUST NOT add, modify, or delete files here** (customize by DI instead):

| Locked path | What it is |
|-------------|------------|
| `src/fdai/core/` | control loop - never fork-edited |
| `src/fdai/composition.py` (and `src/fdai/composition/`) | the upstream composition root |
| `src/fdai/shared/providers/` | injectable Protocol seam **definitions** |
| `src/fdai/shared/contracts/` | versioned event / action / rule / ontology types |
| `src/fdai/agents/` | the 15-agent pantheon (role bindings fork-locked) |
| `rule-catalog/schema/` | catalog schemas (add entries, never widen a schema) |
| `.github/instructions/` | this normative rule set |

**EDITABLE - a fork owns these freely**:

- Its own `fork/` package: `composition_root.py` (wraps upstream `default_container()` +
  `dataclasses.replace()`), `entry.py`, `adapters/`, `rules/`, `overlays/`.
- **Concrete implementations** of any `shared/providers/` Protocol (the definition is
  locked; supplying an implementation and binding it at the fork composition root is the
  intended path): `LlmBindings`, `OperatorMemoryStore`, `HilRejectMaterializer`,
  `WebSearchProvider`, `HilChannel`, `ScopeResolver`, `CriticModel`/`JudgeModel`,
  delivery publishers, console `ReadPanel`, distillation seams.
- **Catalog and policy additions by entry** (schema unchanged): rule-catalog rules,
  ontology `ObjectType`/`LinkType`, `ActionType` entries, Rego risk overlays.
- **Contract extension by subclassing** `ContractBase` in the fork's own package - never
  by editing a module under `src/fdai/shared/contracts/`.
- `pyproject.toml` (a fork MAY add its own package + entry point).

**The distinction in one line**: changing a **definition** (Protocol signature, core logic,
schema shape, agent role binding) is LOCKED; **adding an implementation or data entry** that
conforms to an existing definition is EDITABLE. If you feel you must edit a locked file to
get something done, the seam you need either already exists (find it) or is a genuine
upstream gap (open an upstream issue or ship a fork-local wrapper) - see
[downstream-fork-guide.md § 3](../../docs/roadmap/fork-and-sequencing/downstream-fork-guide.md) and the
`fork-customization` skill.

## Enforcement

Do not rely on human review alone. Gate every change:

- **Secret scanning** in CI (e.g., `gitleaks` or `trufflehog`) blocks known secret patterns.
- **GUID gate**: `scripts/quality/repository/check-guids.sh` blocks any GUID-shaped id (8-4-4-4-12 hex)
  outside the all-zero placeholder pattern (`00000000-0000-0000-0000-XXXXXXXXXXXX`).
  Runs in CI as the `guids` job. Rationale: Azure tenant, subscription, and
  resource ids all share this shape; blocking them at commit time is the only
  reliable way to keep the repo customer-agnostic.
- **Custom regex check** in CI for other repo-specific tokens (known resource-name
  prefixes, `*.azure.com`/cloud endpoints) is future work.
- **Framework-surface guard**: `scripts/integrity/check-protected-paths.sh` warns (upstream)
  or hard-blocks (fork) any edit to the files a fork MUST NOT touch (`src/fdai/core/`,
  `src/fdai/composition.py`, `src/fdai/shared/providers/`, `src/fdai/shared/contracts/`,
  `src/fdai/agents/`, `rule-catalog/schema/`, `.github/instructions/`). A fork opts into
  block mode with `FDAI_FORK=1`, a `.fdai-fork` marker, or `git config fdai.fork true`.
  Runs in the pre-push hook and the `protected-paths` CI job; `.github/CODEOWNERS`
  is its review-time counterpart.
- **Signed integrity manifest** (offline, tamper-evident): `scripts/integrity/check-integrity.sh`
  verifies every framework-surface file against
  [security/integrity/manifest.json](../../security/integrity/manifest.json) (SHA-256 map,
  Ed25519-signed by upstream; the public key ships in the tree). It runs fully offline
  (openssl + python3, no network). A **signature** failure is always an error (a forged
  manifest - a fork cannot mint one without the upstream private key); a **content**
  mismatch is a hard fail in fork mode, advisory upstream. Wired into `scripts/verify.sh`
  as the `framework-integrity` gate, the **pre-push hook** (blocks a fork push that edits
  the surface), and **pre-commit** (runs only when a surface path changes). This is
  tamper-**evidence**, not tamper-**proof** (a fork owner still controls their runtime),
  so it complements - not replaces - the guard and CODEOWNERS.
- **Auto re-sign (upstream signer only)**: the `.githooks/pre-commit` hook runs
  `scripts/integrity/resign-if-surface-staged.sh`, which re-signs the manifest and stages it into
  the same commit **whenever a framework-surface file is staged AND the upstream private
  signing key is present** (`secrets/integrity-signing-key.pem` or `$FDAI_INTEGRITY_KEY`).
  This removes the manual "re-sign before release" chore for the maintainer. It is a
  no-op in a fork (no private key), so the fork-facing tamper-evidence is unchanged - a
  fork still cannot mint a verifying manifest. Bypass with `FDAI_SKIP_RESIGN=1`. (Caveat:
  the signer hashes the working tree, so avoid partial staging of a surface file.)
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
