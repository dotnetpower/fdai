---
name: fork-customization
description: |
  Decision + workflow skill for an agent working INSIDE a downstream FDAI
  fork. Answers "can I edit this file, or must I customize by dependency
  injection?" and routes every customization to the right seam. The fork
  boundary is fork-locked: `services/core-control-plane/src/fdai/core/`, `services/core-control-plane/src/fdai/composition*`,
  `services/core-control-plane/src/fdai/shared/providers/`, `services/core-control-plane/src/fdai/shared/contracts/`,
  `services/core-control-plane/src/fdai/agents/`, `rule-catalog/schema/`, and `.github/instructions/`
  are LOCKED; a fork adds implementations + data entries instead. Load this
  skill when a maintainer asks to customize / extend / adapt FDAI in a fork,
  when a `check-protected-paths.sh` or `check-integrity.sh` gate fails in
  fork mode, when adding an LLM / HIL / search / scope adapter, a rule,
  an ActionType / ObjectType, or a Rego overlay, or when you are tempted to
  edit a file under `services/core-control-plane/src/fdai/core/`.
version: 1.0.0
scope: repository
---

# Fork Customization

This skill governs work **inside a downstream fork** (a repo that carries a
committed `.fdai-fork` marker, `FDAI_FORK=1`, or `git config fdai.fork true`).
Those signals select repository-integrity enforcement only. They MUST NOT select a
deployment environment, tenant, evidence profile, RBAC policy, or shadow/enforce mode.

A fork is an optional distribution customization boundary. Upstream and forks may each
have zero or many deployments in any environment. Runtime behavior continues to follow
the same contracts and authoritative configuration described by
[ADR-0002](../../../docs/roadmap/architecture/decisions/0002-independent-runtime-axes.md).
The always-loaded short contract is
[.github/instructions/generic-scope.instructions.md](../../instructions/generic-scope.instructions.md)
(§ "Editable vs Locked"). The procedural walkthrough is
[docs/roadmap/fork-and-sequencing/downstream-fork-guide.md](../../../docs/roadmap/fork-and-sequencing/downstream-fork-guide.md),
and the per-seam cookbook is
[downstream-fork-seam-recipes.md](../../../docs/roadmap/fork-and-sequencing/downstream-fork-seam-recipes.md).
This skill is the decision procedure that sits in front of them.

## The one machine-readable source of truth

Before editing ANY path, check it against
[scripts/lib/framework-surface.txt](../../../scripts/lib/framework-surface.txt).
That file is consumed by both the edit guard (`check-protected-paths.sh`) and
the signed integrity manifest (`check-integrity.sh`), so it never drifts.

**If the path is listed there, it is LOCKED. Otherwise it is editable.**

## Preflight (answer before you touch a file)

1. **Is the target path on the framework surface?** Run
   `git check-ignore` is irrelevant here; instead ask: does the path start
   with a `framework-surface.txt` directory prefix, or equal a file entry?
   If YES -> do NOT edit it. Go to the decision tree below.
2. **Am I changing a definition or adding an implementation/entry?**
   - Changing a **definition** (a Protocol method signature, core control-loop
     logic, a schema shape, an agent role binding, a contract model) = LOCKED,
     upstream-only.
   - Adding an **implementation** of an existing Protocol, or a **data entry**
     (rule, ActionType, ObjectType, Rego overlay) that conforms to an unchanged
     schema = EDITABLE, do it in the fork.
3. **Does the seam already exist?** Almost always yes. Search
   `services/core-control-plane/src/fdai/shared/providers/` for the Protocol before concluding you need a
   core edit.

## Decision tree

```text
Want to customize behavior X.
  |
  Is there a Protocol seam for X in services/core-control-plane/src/fdai/shared/providers/?
  |-- YES -> write a concrete class in fork/adapters/, bind it in
  |          fork/composition_root.py via dataclasses.replace(). DONE.
  |
  Is X a rule / ActionType / ObjectType / LinkType / Rego overlay?
  |-- YES -> add a catalog ENTRY under the fork's rules/ or overlays/
  |          (schema in rule-catalog/schema/ stays byte-identical). DONE.
  |
  Is X a new bespoke contract type?
  |-- YES -> subclass ContractBase in the fork package
  |          (never edit services/core-control-plane/src/fdai/shared/contracts/). DONE.
  |
  None of the above -> you have found a genuine upstream gap.
      -> open an upstream issue, OR ship a fork-local wrapper that
         composes around core/ without patching it. Do NOT edit core/.
```

## Where fork-owned work lives

```
your-fork/
  fork/
    composition_root.py   # upstream default_container() + dataclasses.replace()
    entry.py              # process entry point
    adapters/             # concrete Protocol implementations
    rules/                # rule-catalog additions (entries only)
    overlays/             # Rego risk-ceiling overlays
  <upstream tree - byte-identical except pyproject.toml>
```

Seam recipes are numbered 5.1-5.16 in
[downstream-fork-seam-recipes.md](../../../docs/roadmap/fork-and-sequencing/downstream-fork-seam-recipes.md):
`LlmBindings` (5.1), `OperatorMemoryStore` (5.2), `HilRejectMaterializer` (5.3),
`WebSearchProvider` (5.4), `HilChannel` (5.5), `ScopeResolver` (5.6),
`CriticModel`/`JudgeModel` (5.7), rule catalog (5.8), ontology types (5.8a),
Rego overlays (5.9), `ActionType` (5.12), delivery publisher (5.13), console
`ReadPanel` (5.14), fork entry point (5.15), distillation (5.16).

## If a gate blocks you

- `check-protected-paths: BLOCKED - fork edited the framework surface` -> you
  edited a locked path. Revert that edit and re-route it through a seam using
  the decision tree above. The `FDAI_ALLOW_PROTECTED=1` local override exists
  only for reviewed upstream-sync conflict resolution; it is IGNORED in CI and
  is never the right answer for a customization.
- `check-integrity: BLOCKED - fork altered the signed framework surface` -> a
  locked file's content no longer matches the upstream signed manifest. Restore
  it to the upstream version (`git checkout upstream/main -- <path>`), then make
  your change via a seam.
- `check-integrity: FAIL - manifest signature did NOT verify` -> the manifest or
  public key was tampered with, or your checkout is corrupt. Re-sync from
  upstream; never "fix" this by re-signing in a fork (a fork has no upstream key).

## Hard don'ts

- Do NOT edit any path in `framework-surface.txt` to make a feature work.
- Do NOT widen a schema in `rule-catalog/schema/` - add entries against the
  existing schema instead.
- Do NOT add / remove / rename an agent, or change an ActionType role binding
  (executor / judge / approver / auditor / initiators) - those are fork-locked.
- Do NOT disable, delete, or bypass `check-protected-paths.sh` /
  `check-integrity.sh` / the pre-push hook to land a change.
- Do NOT commit customer-identifying values (see generic-scope.instructions.md).
