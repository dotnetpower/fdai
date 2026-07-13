---
title: Downstream Fork Guide
---

# Downstream Fork Guide

How to fork this repo, keep the fork clean, and customize per customer.
This is the single entry point for **fork maintainers** - engineers
who take the upstream FDAI and adapt it to one specific
deployment (a customer tenant, a compliance regime, or a proof-of-
concept environment).

The upstream repo is deliberately generic and customer-agnostic
([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
A fork is where every customer-specific value, rule, adapter, and
secret lives. The rules below exist so a fork can sync with
upstream without conflict pain and so upstream sees zero
customer values.

Prerequisites: read
[project-structure.md § Customization via Dependency Injection](../architecture/project-structure.md#customization-via-dependency-injection)
first for the DI seam catalog, plus
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)
for the T0/T1/T2 trust router and quality-gate concepts referenced
throughout this guide. This document turns those references into
procedural recipes.

**Contents**

1. [Fork model at a glance](#1-fork-model-at-a-glance)
2. [Day-1 checklist](#2-day-1-checklist)
3. [The one hard rule](#3-the-one-hard-rule)
4. [Repo layout for a fork](#4-repo-layout-for-a-fork)
5. [Seam recipes and example vertical](#5-seam-recipes-and-example-vertical) - links out to companion docs
6. [Upstream sync + version-pinning strategy](#6-upstream-sync-procedure)
7. [Anti-patterns](#7-anti-patterns)
8. [Where to go next](#8-where-to-go-next)

**Recurring terms.** "Deny-by-default fake" = an upstream in-memory
Protocol implementation that returns empty / rejected on every call
(e.g., `NoOpWebSearchProvider`, `InMemoryHilChannel`), so a fork that
forgets to bind a real adapter fails safe rather than silently opening
a hole. "Shadow-before-enforce" = the invariant that every new
ActionType ships with `default_mode: shadow` (judge and log only, no
execution) and is promoted to `enforce` only after its declared
`promotion_gate` is measured green - defined in
[coding-conventions.instructions.md § Safety](../../../.github/instructions/coding-conventions.instructions.md#safety).

## 1. Fork model at a glance

- **Upstream** = this repository. Ships the generic control plane
  (core engine, DI seams, deny-by-default fakes, catalog schemas).
- **Fork** = a separate repository the customer team owns. Contains
  the tenant identity, secret refs, allowlists, per-customer rules,
  and any concrete adapters the deny-by-default fakes replace.
- **Direction of contribution**: upstream never pulls from a fork.
  A fork pulls from upstream `main` for improvements. When a fork
  produces a change that would be useful for every customer, the
  change is **scrubbed of customer values** and shipped as a
  standalone upstream PR.

## 2. Day-1 checklist

Do these before your first `git commit` on the fork.

1. **Confirm the baseline is green on your fresh clone**:
   `uv sync` then `uv run pytest -q`. If the upstream test suite
   fails on an untouched checkout, stop and diagnose before adding
   any fork code - the fork must never inherit a red baseline.
2. **Clone with a distinct default branch name** (optional but
   recommended): `fork/main` or `customer-x/main` so no `git push`
   accidentally targets upstream.
3. **Verify `git remote -v`**: `origin` MUST point at your fork
   repository, NOT at `dotnetpower/fdai`. Getting this wrong
   once has a chance of leaking customer commits upstream.
4. **Enable secret scanning** in the fork's CI - reuse the upstream
   `scripts/check-english-only.sh`, `scripts/check-punctuation.sh`,
   `scripts/check-guids.sh`, `scripts/check-core-imports.sh`, and
   `scripts/check-translations.sh`. **These are not sufficient on
   their own.** `check-guids.sh` matches the `8-4-4-4-12` hex shape
   only; it does not know about your customer's resource names,
   endpoints, bearer-token prefixes, or short account ids. Add
   fork-specific regex patterns (a `check-customer-tokens.sh` in
   the same style) covering: resource-name prefixes your customer
   uses (`acme-prod-*`), hostname suffixes (`*.customer.example`),
   API token prefixes if any (`sk-...`, `xoxb-...`, `Bearer eyJ`),
   and short account ids (12-digit AWS, 6-hex GCP project prefix).
   Run an OSS secret scanner (`gitleaks`, `trufflehog`) alongside.
5. **Never commit** an Azure tenant / subscription id, a customer
   resource name, an endpoint, or a secret. Load them from
   environment or Key Vault at runtime. Every SDK-family secret
   (API key, connection string, DSN with password) goes through
   `fdai.shared.providers.secret_provider.SecretProvider` -
   the Protocol contract forbids logging or persisting the value.
6. **Create a `fork/` (or `customer/`) top-level directory** for
   fork-owned modules. This is where your composition-root override,
   adapters, and rule additions live. `core/` stays 100% upstream.
7. **Register your fork package in `pyproject.toml`**: add your
   `fork/` directory to `[tool.setuptools.packages.find]` (or the
   equivalent for your build backend) and register your process
   entry point under `[project.scripts]`. The upstream `pyproject`
   ships a working baseline; the fork edit is a minimal delta.
8. **Wire your composition root**: a thin Python module that imports
   upstream `default_container(...)` and applies `dataclasses.replace`
   to swap the seams your fork owns. Rename your process entry point
   to import from this module instead of upstream's `__main__`.
9. **Set up upstream sync**: `git remote add upstream
   https://github.com/dotnetpower/fdai.git`. Rehearse the
   [Upstream sync procedure](#upstream-sync-procedure) once before
   the first divergence.

## 3. The one hard rule

**Never edit files under `src/fdai/core/`.** Everything a
fork wants to customize has a seam. If you find yourself wanting to
edit `core/`, one of two things is happening:

1. You are trying to inject a value that belongs in configuration
   or a fake. Find the seam that already exists.
2. You have found a genuine gap in the upstream design. Open an
   upstream issue OR ship your change as a fork-local wrapper that
   composes around `core/` without patching it. Then contribute
   the wrapper upstream, scrubbed.

The rule is enforced by three invariants:

- Upstream's `scripts/check-core-imports.sh` refuses any `core/`
  file that imports from `delivery/*` or from a cloud SDK.
- Upstream's `scripts/check-protected-paths.sh` inspects the
  changed files and warns (upstream) or **hard-blocks (fork)** any
  edit to the framework surface - `src/fdai/core/`,
  `src/fdai/composition/`, `src/fdai/shared/providers/`,
  `src/fdai/shared/contracts/`, `src/fdai/agents/`,
  `rule-catalog/schema/`, and `.github/instructions/`. A fork opts
  into block mode with `FDAI_FORK=1` (local shells), a **committed**
  `.fdai-fork` marker file (the reliable signal for CI, because it
  travels in the tree - an env var does not), or
  `git config fdai.fork true`; the guard runs in the pre-push
  hook and as the `protected-paths` CI job (which also posts a
  `::warning::` annotation per file on the PR Files tab).
- The composition root
  ([`src/fdai/composition/`](../../../src/fdai/composition))
  is the only place where concrete implementations bind to
  Protocols in `shared/providers/`. A fork writes its own
  composition root; it does not edit this file. `.github/CODEOWNERS`
  is the review-time counterpart: framework-surface paths route to
  the owners team.

## 4. Repo layout for a fork

Recommended shape:

```
customer-x-fork/
  fork/
    __init__.py
    composition_root.py    # calls upstream default_container() + replace()
    entry.py               # customer process entry (was __main__.py upstream)
    adapters/
      web_search.py        # concrete WebSearchProvider
      hil_channel.py       # concrete HilChannel (Teams / Slack)
      scope_resolver.py    # ARM-id -> OperatorScope parser
    rules/
      customer.yaml        # per-customer rule catalog additions
    overlays/
      risk_gate.rego       # per-customer risk ceiling overlays
  <upstream tree, unchanged>
```

Everything under `fork/` is customer-owned. Upstream files remain
byte-identical except for `pyproject.toml` (a fork MAY add its own
package + entry point).

## 5. Seam recipes and example vertical

The per-seam cookbook lives in a companion file:
[downstream-fork-seam-recipes.md](downstream-fork-seam-recipes.md).
Each recipe follows the same shape - **when to override**, **the
seam**, **how to bind**, **how to test** - and every snippet
assumes Python 3.12+ and the upstream package importable as
`fdai`. The recipes are organised in bind-order (you typically
land ObjectType before the Rule that references it, ActionType
before the Rule that names it, and so on):

| Recipe | Topic |
|--------|-------|
| [5.1](downstream-fork-seam-recipes.md#51-azure-openai-adapters-llmbindings) | Azure OpenAI adapters (`LlmBindings`) |
| [5.2](downstream-fork-seam-recipes.md#52-operatormemorystore-in-memory--postgres--custom) | `OperatorMemoryStore` (in-memory / Postgres / custom) |
| [5.3](downstream-fork-seam-recipes.md#53-hilrejectmaterializer--second-approval-channel) | `HilRejectMaterializer` + second-approval channel |
| [5.4](downstream-fork-seam-recipes.md#54-websearchprovider) | `WebSearchProvider` |
| [5.5](downstream-fork-seam-recipes.md#55-hilchannel-teams--slack--custom) | `HilChannel` (Teams / Slack / custom) |
| [5.6](downstream-fork-seam-recipes.md#56-scoperesolver-arm-id---operatorscope) | `ScopeResolver` (ARM id → `OperatorScope`) |
| [5.7](downstream-fork-seam-recipes.md#57-criticmodel--judgemodel-debate-activation) | `CriticModel` + `JudgeModel` (debate activation) |
| [5.8](downstream-fork-seam-recipes.md#58-rule-catalog-additions) | Rule catalog additions |
| [5.8a](downstream-fork-seam-recipes.md#58a-ontology-object-type--link-type-additions) | Ontology `ObjectType` / `LinkType` additions |
| [5.9](downstream-fork-seam-recipes.md#59-risk-overlays-rego) | Risk overlays (Rego) |
| [5.10](downstream-fork-seam-recipes.md#510-runtime-failure-modes-and-abstain-contracts) | Runtime failure modes and abstain contracts |
| [5.11](downstream-fork-seam-recipes.md#511-testing-your-fork-end-to-end) | Testing your fork end-to-end |
| [5.12](downstream-fork-seam-recipes.md#512-actiontype-catalog-additions) | `ActionType` catalog additions |
| [5.13](downstream-fork-seam-recipes.md#513-delivery-adapter-custom-publisher) | Delivery adapter (custom publisher) |
| [5.14](downstream-fork-seam-recipes.md#514-console-readpanel-additions) | Console `ReadPanel` additions |
| [5.15](downstream-fork-seam-recipes.md#515-fork-entry-point-entrypy) | Fork entry point (`entry.py`) |
| [5.16](downstream-fork-seam-recipes.md#516-manual-distillation-manualsource--manualclassifier--distiller) | Manual distillation (`ManualSource` / `ManualClassifier` / `Distiller`) |

**Building a new business-object vertical**: a fork that adds a
non-Resource ObjectType lifecycle (architecture-review proposal,
compliance-attestation record, incident-postmortem workflow) has a
stitched-together walkthrough in
[downstream-fork-example-vertical.md](downstream-fork-example-vertical.md).
It uses a generic `GovernanceProposal` example and cross-references
every recipe above in the order they are needed.

**Copy-ready shipped example**: upstream also ships a smaller
end-to-end reference - the **`ops.change-summary`** on-demand
`resource-group` change-summary generator. Six files
(ObjectType `ChangeSummary`, LinkType `summarizes`, ActionType
`ops.publish-change-summary`, rule `ops.change-summary`, Rego,
Markdown template) plus one test file
([`tests/verticals/test_change_summary_example.py`](../../../tests/verticals/test_change_summary_example.py))
form the minimum working scaffold. Fork copies the six files, renames
to its own business object, and has a green baseline before adding
lifecycle. The walkthrough above shows what grows on top when the
workflow needs reviewers and multi-step approval.

**Extending a contract model (rare)**: the six domain contract
modules live under [`src/fdai/shared/contracts/models/`](../../../src/fdai/shared/contracts/models)
(`event.py` / `action.py` / `rule.py` / `incident.py` / `ontology.py`
/ `workflow.py`), each re-exported from the package facade. A fork
that legitimately needs a bespoke contract subclasses `ContractBase`
(the public alias of the internal `_Base`) so the four invariants
(`extra=forbid`, `frozen`, `str_strip_whitespace`, `validate_default`)
are inherited without re-declaring `model_config`:

```python
from fdai.shared.contracts.models import ContractBase, SemVer

class ForkAuditNote(ContractBase):
    schema_version: SemVer
    note_text: str
```

The upstream models MUST NOT be edited (they are on the framework
surface guarded by [`check-protected-paths.sh`](../../../scripts/check-protected-paths.sh));
add a fork submodule under the fork's own package instead.

## 6. Upstream sync procedure

The fork stays healthy by pulling upstream `main` on a schedule
(weekly is a good default). Because a fork never edits `core/` and
never commits customer values, merges are typically clean.

### 6.1 Version-pinning strategy

"Track upstream `main` weekly" is aspirational; in practice a fork
SHOULD pin to a **known-good upstream ref** and advance the pin
deliberately. Two acceptable strategies:

1. **Pin to a tag** (recommended). Upstream cuts semver-adjacent
   tags at milestone boundaries. The fork's `pyproject.toml`
   dependency on the upstream package (if it uses one) or the
   fork's `git subtree` / submodule pointer references that tag.
   Advancing the pin is a reviewed PR: read the upstream CHANGELOG,
   run the fork test suite, then advance.
2. **Pin to a SHA on `upstream/main`** with a stated cadence. Same
   idea, coarser granularity. Suitable while upstream is pre-1.0.

**Breaking Protocol changes**. Any upstream change that alters a
seam Protocol's method signature is treated as a breaking change
even if not tagged as such. The upstream policy is to ship the new
Protocol alongside the old one for one release, then remove the
old; a fork should complete the migration within that window.
Watch `src/fdai/shared/providers/**` and
`src/fdai/composition/` diffs on every sync.

### 6.2 Sync workflow

```bash
# One-time setup
git remote add upstream https://github.com/dotnetpower/fdai.git

# Every sync
git fetch upstream --tags
git checkout main
git merge upstream/main            # or rebase - team choice
# Resolve conflicts (usually zero if the fork rule is honored)
./scripts/check-english-only.sh    # sanity gates
./scripts/check-translations.sh
uv run pytest -q tests/ fork/tests/  # full suite
git push origin main
```

If a merge lands a conflict inside `core/`, that is a signal your
fork has silently violated the hard rule. Revert the fork-side
edit, move the change into your composition root or an adapter, and
re-run the sync.

## 7. Anti-patterns

Hard don'ts. Any of these is a merge-blocker:

- **Committing an Azure tenant id, subscription id, resource name,
  endpoint, or secret** anywhere in the fork. Load them from
  environment or Key Vault via `SecretProvider`. Upstream's
  `check-guids.sh` only catches the `8-4-4-4-12` GUID shape - it
  does not catch customer resource names, hostnames, or bearer
  tokens. The fork MUST layer its own regex gate + an OSS secret
  scanner (see §2 item 4).
- **Modifying files under `src/fdai/core/**` or
  `src/fdai/composition/` in place**. A fork MUST `import`
  from these modules (that is the whole point of the seams), but
  MUST NOT edit them. Every customization goes through
  `dataclasses.replace()` on a container returned by
  `default_container(...)`. See
  [The one hard rule](#3-the-one-hard-rule).
- **Editing `rule-catalog/schema/**`**. Extend by adding new
  catalog entries under a fork-unique id namespace, not by widening
  the schema.
- **Disabling upstream tests to make a green CI**. If an upstream
  test blocks your fork, that is a signal upstream needs a design
  change - open an issue.
- **Auto-executing a fork-added action without shadow mode first**.
  The shadow-before-enforce invariant applies to every fork-added
  ActionType exactly as it does to upstream ones.
- **Contributing back a change that carries customer identity**.
  Every upstream PR from a fork MUST be scrubbed of customer names,
  ids, endpoints, and any private dataset references.
- **Committing a `-ko.md` translation without updating the paired
  English source's `translation_source_sha`**. The upstream
  `check-translations.sh` gate applies to fork-added user-facing
  docs too.

## 8. Where to go next

- [project-structure.md § Customization via Dependency Injection](../architecture/project-structure.md#customization-via-dependency-injection) -
  the DI seam catalog this guide operationalizes.
- [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) -
  the T0/T1/T2 trust router, quality gate, risk gate, and the
  living-rules discovery loop the fork's rules feed into.
- [coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md) -
  safety invariants, shadow-mode default, async-Protocol contracts,
  and the docs-first + docs-after rule the fork inherits.
- [deploy-and-onboard.md](../deployment/deploy-and-onboard.md) - the Azure
  resource inventory a fork provisions (Container Apps, Event Hubs,
  Postgres, Key Vault, ...).
- [prompt-composition.md](../decisioning/prompt-composition.md) - the full design
  of the evolving system prompt (Base + Task Pack + Tool Manifest +
  Operator Memory + Debate).
- [csp-neutrality.md](../architecture/csp-neutrality.md) - how a fork replaces the
  Azure resource layer with an alternative implementation.
- [`docs/runbooks/`](../../runbooks) - the operational procedures a
  fork's on-call runs (exemption workflow, HIL escalation,
  rollback, incident replay). Fork-specific runbooks live under
  `fork/runbooks/` and reference these upstream templates.
- [generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md) -
  the customer-agnostic scope contract every fork honors.
